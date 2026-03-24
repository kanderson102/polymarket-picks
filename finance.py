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
            "100381": 0.55,  # NBA
            "100382": 0.55,  # NCAAM (Basketball handles both)
            "100101": 0.60,  # Soccer
            "100102": 0.60,  # UCL
            "100383": 0.65,  # MLB
            "100384": 0.65,  # NHL
            "100401": 0.65,  # Tennis
            "100601": 0.90,  # Tech (High Probability setups)
            "100701": 0.55,  # Politics (High Volatility)
            "100801": 0.60   # Pop Culture
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

