from finance import FinanceController

def run_tests():
    # 1. Test Bet Sizing
    print("--- Testing Position Sizing (Sharp vs Whale) ---")
    size_sharp = FinanceController.calculate_bet_size(100.0, 'SHARP', 50.0)
    size_whale = FinanceController.calculate_bet_size(100.0, 'WHALE', 50.0)
    size_sharp_high_wr = FinanceController.calculate_bet_size(100.0, 'SHARP', 75.0)
    print(f"Balance: $100 -> Sharp (50% WR): ${size_sharp:.2f} | Expected: $1.00")
    print(f"Balance: $100 -> Whale (50% WR): ${size_whale:.2f} | Expected: $2.00")
    print(f"Balance: $100 -> Sharp (75% WR): ${size_sharp_high_wr:.2f} | Expected: $1.50")
    assert size_sharp == 1.0
    assert size_whale == 2.0
    assert size_sharp_high_wr == 1.5

    # 2. Test Harvest Logic (No Trigger)
    print("\n--- Testing Harvest Trigger (Below 2x) ---")
    res = FinanceController.check_harvest(99.0, 50.0)
    print(f"Baseline $50, Balance $99 -> Triggered? {res.triggered}")
    assert not res.triggered
    assert res.new_balance == 99.0
    assert res.new_baseline == 50.0

    # 3. Test Harvest Logic (Trigger)
    print("\n--- Testing Harvest Trigger (At 2x Baseline) ---")
    res = FinanceController.check_harvest(100.0, 50.0)
    print(f"Triggered: {res.triggered}")
    print(f"Profit calculated: ${res.profit:.2f}")
    print(f"Transfer to Main Wallet (50% of profit): ${res.transfer_amount:.2f}")
    print(f"New Balance remaining in bot: ${res.new_balance:.2f}")
    print(f"New Baseline registered: ${res.new_baseline:.2f}")

    assert res.triggered
    assert res.profit == 50.0
    assert res.transfer_amount == 25.0
    assert res.new_balance == 75.0
    assert res.new_baseline == 75.0

    # 4. Test Adaptive Value Caps
    print("\n--- Testing Adaptive Value Caps ---")
    nba_cap = FinanceController.get_max_price_for_tag("100381")
    soccer_cap = FinanceController.get_max_price_for_tag("100101")
    print(f"NBA Max Entry Price: {nba_cap}")
    print(f"Soccer Max Entry Price: {soccer_cap}")
    assert nba_cap == 0.55
    assert soccer_cap == 0.60

    print("\n✅ All finance math rules passed!")

if __name__ == "__main__":
    run_tests()
