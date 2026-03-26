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
    def calculate_bet_size(current_balance: float, tier: str, win_rate: float) -> float:
        """
        Dynamic Position Sizing.
        Automatically scales portfolio capital towards sharp traders over time.
        Whales get a lower base allocation (3%) to balance out their higher variance, 
        but large enough to clear gas fees. Sharp traders get a standard allocation (5%).
        
        Phase 1-2 ($50 bankroll): 5% SHARP / 3% WHALE
        Phase 3 ($1000+ bankroll): Scale down to 1-2% as bankroll grows.
        """
        # Base capital percentage
        # Phase 1-2: SHARP 5%, WHALE 3% (meaningful size on small bankroll)
        base_percent = 0.05 if tier == 'SHARP' else 0.03
        
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
        Adaptive "Value Caps".
        Returns the maximum acceptable entry price based on the sport tag.
        """
        # Dictionary mapping Tag IDs to Max Prices
        tag_limits = {
            "745": 0.55,      # NBA
            "28": 0.55,       # Basketball
            "100350": 0.60,   # Soccer
            "100977": 0.60,   # UCL
            "306": 0.60,      # EPL
            "82": 0.60,       # Premier League
            "100381": 0.65,   # MLB
            "678": 0.65,      # baseball
            "899": 0.65,      # NHL
            "100088": 0.65,   # Hockey
            "100089": 0.65,   # Stanley Cup
            "64": 0.65,       # Esports
            "2": 0.55,        # Politics (High Volatility)
            "144": 0.55,      # Elections
            "100265": 0.55,   # Geopolitics
            "1": 0.60,        # Sports (generic)
            "100639": 0.60,   # Games (generic)
        }
        
        return tag_limits.get(str(tag_id), 0.50)  # Default fallback 0.50

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



