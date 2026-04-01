# finance.py
# Core financial math for the Polymarket Copy-Bot

from dataclasses import dataclass

@dataclass
class HarvestResult:
    triggered: bool
    transfer_amount: float
    new_baseline: float
    new_balance: float
    profit: float

class FinanceController:
    """
    Handles bankroll management, position sizing, and profit harvesting logic.

    Most methods accept an optional `cfg` dict (loaded from the DB bot_config
    table) so every parameter is tunable via the Settings UI without code changes.
    When cfg is None, the original hardcoded defaults are used — so existing
    call sites and tests continue to work unchanged.
    """

    @staticmethod
    def _get_base_percent(balance: float, tier: str, cfg: dict = None) -> float:
        """
        Graduated base percentage that tapers as bankroll grows.
        Keeps bets meaningful at $50, prevents oversized bets at $1000+.

        SHARP:  $0-199 → 5%  |  $200-999 → 3%  |  $1000+ → 1.5%
        WHALE:  $0-199 → 3%  |  $200-999 → 2%  |  $1000+ → 1%
        """
        if tier == 'SHARP':
            if balance < 200:
                pct = float(cfg.get('sharp_bet_pct_low', 5.0)) if cfg else 5.0
            elif balance < 1000:
                pct = float(cfg.get('sharp_bet_pct_mid', 3.0)) if cfg else 3.0
            else:
                pct = float(cfg.get('sharp_bet_pct_high', 1.5)) if cfg else 1.5
        else:  # WHALE
            if balance < 200:
                pct = float(cfg.get('whale_bet_pct_low', 3.0)) if cfg else 3.0
            elif balance < 1000:
                pct = float(cfg.get('whale_bet_pct_mid', 2.0)) if cfg else 2.0
            else:
                pct = float(cfg.get('whale_bet_pct_high', 1.0)) if cfg else 1.0
        return pct / 100.0

    @staticmethod
    def calculate_bet_size(current_balance: float, tier: str, win_rate: float, cfg: dict = None) -> float:
        """
        Dynamic Position Sizing with graduated bankroll scaling.

        Base percentages taper as the bankroll grows to keep position count
        sustainable and avoid outsized single-trade risk:

            SHARP:  $0-199 → 5%  |  $200-999 → 3%  |  $1000+ → 1.5%
            WHALE:  $0-199 → 3%  |  $200-999 → 2%  |  $1000+ → 1%

        Win rate multiplier still applies: (win_rate / 50.0).
        Pass a cfg dict (from TradingDB.get_all_config()) to override defaults.
        """
        base_percent = FinanceController._get_base_percent(current_balance, tier, cfg)

        # Scale the bet size dynamically by their historical win rate
        # A 75% win rate grinder will place 1.5x larger bets automatically
        win_rate_multiplier = (win_rate / 50.0) if win_rate > 0 else 1.0

        return current_balance * base_percent * win_rate_multiplier

    @staticmethod
    def check_harvest(current_balance: float, baseline_capital: float, cfg: dict = None) -> HarvestResult:
        """
        Growth-First Harvesting.
        Trigger: If Wallet_Balance >= N * Baseline_Capital  (default N=2, the "2x Rule").
        Action:
          1. Profit = Balance - Baseline
          2. Transfer X% of Profit to Main Wallet  (default X=50%)
          3. Set New Baseline = Current Balance - Transfer Amount
        """
        trigger_mult = float(cfg.get('harvest_trigger_multiplier', 2.0)) if cfg else 2.0
        transfer_pct = float(cfg.get('harvest_transfer_pct', 50.0)) / 100.0 if cfg else 0.50

        if current_balance >= trigger_mult * baseline_capital:
            profit = current_balance - baseline_capital
            transfer_amount = profit * transfer_pct
            new_balance = current_balance - transfer_amount
            new_baseline = new_balance

            return HarvestResult(
                triggered=True,
                transfer_amount=transfer_amount,
                new_baseline=new_baseline,
                new_balance=new_balance,
                profit=profit
            )

        # No harvest triggered
        return HarvestResult(
            triggered=False,
            transfer_amount=0.0,
            new_baseline=baseline_capital,
            new_balance=current_balance,
            profit=0.0
        )

    @staticmethod
    def get_max_price_for_tag(tag_id: str, cfg: dict = None) -> float:
        """
        Adaptive "Value Caps" — max entry price by category.

        Raised to 0.82 for most categories based on pro copy-trading research:
        - Previous caps (0.55-0.65) filtered out specialists' high-conviction
          trades where they actually had edge.
        - Pro services (Polycule, PolyCop) typically cap at 0.80-0.85.
        - Only filter truly extreme prices (0.90+) where implied probability
          leaves almost no edge for the copy-trader.
        """
        sports_cap = float(cfg.get('value_cap_sports', 0.82)) if cfg else 0.82
        politics_cap = float(cfg.get('value_cap_politics', 0.75)) if cfg else 0.75

        SPORTS_TAGS = {
            "745", "28", "100350", "100977", "306", "82",
            "100381", "678", "899", "100088", "100089",
            "64", "102366", "1", "100639",
        }
        POLITICS_TAGS = {"2", "144", "100265"}

        tag = str(tag_id)
        if tag in SPORTS_TAGS:
            return sports_cap
        if tag in POLITICS_TAGS:
            return politics_cap
        return politics_cap  # conservative default for unknown categories

    @staticmethod
    def calculate_conviction_size(current_balance: float, tier: str,
                                  win_rate: float, specialist_size: float,
                                  specialist_avg_size: float, cfg: dict = None) -> float:
        """
        Conviction-aware position sizing.

        Uses the specialist's bet size relative to their average as a conviction
        signal. When they bet big (relative to their own history), we size up.
        When they bet small (noise/hedging), we size down or skip.

        conviction_ratio = specialist_size / specialist_avg_size
            < 0.3  → skip (likely noise/hedge)
            0.3-1  → normal sizing
            1-3    → 1.0-1.5x multiplier
            3+     → 1.5x cap (don't overweight outliers)

        Falls back to standard calculate_bet_size if no specialist data.
        """
        base_bet = FinanceController.calculate_bet_size(current_balance, tier, win_rate, cfg)

        if specialist_avg_size <= 0 or specialist_size <= 0:
            return base_bet

        ratio = specialist_size / specialist_avg_size

        if ratio < 0.3:
            return 0.0  # Skip — too small, likely noise

        if ratio <= 1.0:
            multiplier = 1.0  # Normal conviction
        elif ratio <= 3.0:
            # Linear scale from 1.0x to 1.5x
            multiplier = 1.0 + 0.25 * (ratio - 1.0)
        else:
            multiplier = 1.5  # Cap at 1.5x

        return base_bet * multiplier

    @staticmethod
    def is_slippage_acceptable(specialist_price: float, current_market_price: float, cfg: dict = None) -> bool:
        """
        The "No Chase" Rule.
        If current market price is > slippage_threshold_pct% higher than the
        specialist's price, abort. Default threshold is 2.5%.
        """
        threshold = float(cfg.get('slippage_threshold_pct', 2.5)) / 100.0 if cfg else 0.025
        max_acceptable_price = specialist_price * (1 + threshold)
        return current_market_price <= max_acceptable_price

    @staticmethod
    def check_liquidity(book_data: dict, bet_size: float, cfg: dict = None) -> tuple[bool, float]:
        """
        Order Book Depth Check.
        Verifies there is sufficient liquidity at the best ask to fill the bet.
        Returns (is_sufficient, available_liquidity).
        Requires at least liquidity_multiple × bet_size in the top 3 asks.
        """
        liq_multiple = float(cfg.get('liquidity_multiple', 2.0)) if cfg else 2.0
        asks = book_data.get('asks', [])
        if not asks:
            return False, 0.0

        # Sum available liquidity across top 3 price levels
        total_liquidity = 0.0
        for ask in asks[:3]:
            price = float(ask.get('price', 0))
            size = float(ask.get('size', 0))
            total_liquidity += price * size

        is_sufficient = total_liquidity >= (bet_size * liq_multiple)
        return is_sufficient, total_liquidity

    @staticmethod
    def estimate_taker_fee(price: float, tag_id: str) -> float:
        """
        Estimate Polymarket taker fee for a given price and category.

        Fees are dynamic and peak around 50¢ prices, tapering to zero near 0¢/100¢.
        Returns the estimated fee as a dollar amount per $1 of bet size.

        Current peak rates (post-March 30, 2026):
            Sports: 0.75%
            Politics/Tech: 1.00%
            Pop Culture: 1.25%
            Crypto: 1.56% → 1.80%
        """
        SPORTS_TAGS = {"745", "28", "100350", "100977", "306", "82", "100381", "678", "899", "100088", "100089", "64", "102366", "1", "100639"}
        POLITICS_TAGS = {"2", "144", "100265"}
        POP_CULTURE_TAGS: set = set()

        tag = str(tag_id)
        if tag in SPORTS_TAGS:
            peak_rate = 0.0075  # 0.75%
        elif tag in POLITICS_TAGS:
            peak_rate = 0.0100  # 1.00%
        elif tag in POP_CULTURE_TAGS:
            peak_rate = 0.0125  # 1.25%
        else:
            peak_rate = 0.0100  # Default conservative

        # Fees peak at price=0.50, taper toward 0 and 1
        # Using a simple parabolic model: fee_rate = peak_rate * 4 * price * (1 - price)
        fee_rate = peak_rate * 4 * price * (1 - price)

        return fee_rate

    @staticmethod
    def calculate_slippage_pct(leader_price: float, market_price: float) -> float:
        """
        Calculate the percentage difference between leader price and our market price.
        Positive means we paid more (bad slippage).
        """
        if leader_price <= 0:
            return 0.0
        return ((market_price - leader_price) / leader_price) * 100
