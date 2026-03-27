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
    """

    @staticmethod
    def _get_base_percent(balance: float, tier: str) -> float:
        """
        Graduated base percentage that tapers as bankroll grows.
        Keeps bets meaningful at $50, prevents oversized bets at $1000+.

        SHARP:  $0-199 → 5%  |  $200-999 → 3%  |  $1000+ → 1.5%
        WHALE:  $0-199 → 3%  |  $200-999 → 2%  |  $1000+ → 1%
        """
        if tier == 'SHARP':
            if balance < 200:
                return 0.05
            elif balance < 1000:
                return 0.03
            else:
                return 0.015
        else:  # WHALE
            if balance < 200:
                return 0.03
            elif balance < 1000:
                return 0.02
            else:
                return 0.01

    @staticmethod
    def calculate_bet_size(current_balance: float, tier: str, win_rate: float) -> float:
        """
        Dynamic Position Sizing with graduated bankroll scaling.

        Base percentages taper as the bankroll grows to keep position count
        sustainable and avoid outsized single-trade risk:

            SHARP:  $0-199 → 5%  |  $200-999 → 3%  |  $1000+ → 1.5%
            WHALE:  $0-199 → 3%  |  $200-999 → 2%  |  $1000+ → 1%

        Win rate multiplier still applies: (win_rate / 50.0).
        """
        base_percent = FinanceController._get_base_percent(current_balance, tier)

        # Scale the bet size dynamically by their historical win rate
        # A 75% win rate grinder will place 1.5x larger bets automatically
        win_rate_multiplier = (win_rate / 50.0) if win_rate > 0 else 1.0

        return current_balance * base_percent * win_rate_multiplier

    @staticmethod
    def check_harvest(current_balance: float, baseline_capital: float) -> HarvestResult:
        """
        Growth-First Harvesting (2x Rule).
        Trigger: If Wallet_Balance >= 2 * Baseline_Capital.
        Action: 
          1. Profit = Balance - Baseline
          2. Transfer 50% of Profit to Main Wallet
          3. Set New Baseline = Current Balance - Transfer Amount
        """
        if current_balance >= 2 * baseline_capital:
            profit = current_balance - baseline_capital
            transfer_amount = profit * 0.50
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
    def get_max_price_for_tag(tag_id: str) -> float:
        """
        Adaptive "Value Caps" — max entry price by category.

        Raised to 0.82 for most categories based on pro copy-trading research:
        - Previous caps (0.55-0.65) filtered out specialists' high-conviction
          trades where they actually had edge.
        - Pro services (Polycule, PolyCop) typically cap at 0.80-0.85.
        - Only filter truly extreme prices (0.90+) where implied probability
          leaves almost no edge for the copy-trader.
        """
        tag_limits = {
            "745": 0.82,      # NBA
            "28": 0.82,       # Basketball
            "100350": 0.82,   # Soccer
            "100977": 0.82,   # UCL
            "306": 0.82,      # EPL
            "82": 0.82,       # Premier League
            "100381": 0.82,   # MLB
            "678": 0.82,      # baseball
            "899": 0.82,      # NHL
            "100088": 0.82,   # Hockey
            "100089": 0.82,   # Stanley Cup
            "64": 0.82,       # Esports
            "102366": 0.82,   # Dota 2
            "2": 0.75,        # Politics (higher volatility, tighter cap)
            "144": 0.75,      # Elections
            "100265": 0.75,   # Geopolitics
            "1": 0.82,        # Sports (generic)
            "100639": 0.82,   # Games (generic)
        }

        return tag_limits.get(str(tag_id), 0.75)  # Default fallback 0.75

    @staticmethod
    def calculate_conviction_size(current_balance: float, tier: str,
                                  win_rate: float, specialist_size: float,
                                  specialist_avg_size: float) -> float:
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
        base_bet = FinanceController.calculate_bet_size(current_balance, tier, win_rate)

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
    def is_slippage_acceptable(specialist_price: float, current_market_price: float) -> bool:
        """
        The "No Chase" Rule.
        If current market price is > 2.5% higher than the specialist's price, Abort.
        (e.g., Target paid 0.50 -> 2.5% higher is 0.5125. If current is 0.52, return False)
        """
        max_acceptable_price = specialist_price * 1.025
        return current_market_price <= max_acceptable_price

    @staticmethod
    def check_liquidity(book_data: dict, bet_size: float) -> tuple[bool, float]:
        """
        Order Book Depth Check.
        Verifies there is sufficient liquidity at the best ask to fill the bet.
        Returns (is_sufficient, available_liquidity).
        """
        asks = book_data.get('asks', [])
        if not asks:
            return False, 0.0
        
        # Sum available liquidity across top 3 price levels
        total_liquidity = 0.0
        for ask in asks[:3]:
            price = float(ask.get('price', 0))
            size = float(ask.get('size', 0))
            total_liquidity += price * size
        
        # Require at least 2x bet size in available liquidity
        is_sufficient = total_liquidity >= (bet_size * 2)
        return is_sufficient, total_liquidity

    @staticmethod
    def estimate_taker_fee(price: float, tag_id: str) -> float:
        """
        Estimate Polymarket taker fee for a given price and category.
        
        Fees are dynamic and peak around 50¢ prices, tapering to zero near 0¢/100¢.
        Returns the estimated fee as a dollar amount per $1 of bet size.
        
        Current peak rates (pre-March 30, 2026):
            Sports: 0.44%  |  After March 30: 0.75%
            Politics/Tech: 1.00%
            Pop Culture: 1.25%
            Crypto: 1.56% → 1.80%
        """
        # Peak fee rates by category (as of March 30, 2026 schedule)
        SPORTS_TAGS = {"745", "28", "100350", "100977", "306", "82", "100381", "678", "899", "100088", "100089", "64", "102366", "1", "100639"}
        POLITICS_TAGS = {"2", "144", "100265"}
        TECH_TAGS = set()
        POP_CULTURE_TAGS = set()
        
        tag = str(tag_id)
        if tag in SPORTS_TAGS:
            peak_rate = 0.0075  # 0.75%
        elif tag in POLITICS_TAGS or tag in TECH_TAGS:
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



