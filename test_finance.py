from finance import FinanceController

def run_tests():
    # 1. Test Bet Sizing (Updated for Phase 1-2: 5% SHARP, 3% WHALE)
    print("--- Testing Position Sizing (Sharp vs Whale) ---")
    size_sharp = FinanceController.calculate_bet_size(100.0, 'SHARP', 50.0)
    size_whale = FinanceController.calculate_bet_size(100.0, 'WHALE', 50.0)
    size_sharp_high_wr = FinanceController.calculate_bet_size(100.0, 'SHARP', 75.0)
    print(f"Balance: $100 -> Sharp (50% WR): ${size_sharp:.2f} | Expected: $5.00")
    print(f"Balance: $100 -> Whale (50% WR): ${size_whale:.2f} | Expected: $3.00")
    print(f"Balance: $100 -> Sharp (75% WR): ${size_sharp_high_wr:.2f} | Expected: $7.50")
    assert size_sharp == 5.0, f"Expected 5.0, got {size_sharp}"
    assert size_whale == 3.0, f"Expected 3.0, got {size_whale}"
    assert size_sharp_high_wr == 7.5, f"Expected 7.5, got {size_sharp_high_wr}"

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

    # 4. Test Adaptive Value Caps (raised to 0.82 for sports, 0.75 for politics)
    print("\n--- Testing Adaptive Value Caps ---")
    nba_cap = FinanceController.get_max_price_for_tag("745")
    soccer_cap = FinanceController.get_max_price_for_tag("100350")
    mlb_cap = FinanceController.get_max_price_for_tag("100381")
    politics_cap = FinanceController.get_max_price_for_tag("2")
    default_cap = FinanceController.get_max_price_for_tag("unknown_tag")
    print(f"NBA Max Entry Price: {nba_cap}")
    print(f"Soccer Max Entry Price: {soccer_cap}")
    print(f"MLB Max Entry Price: {mlb_cap}")
    print(f"Politics Max Entry Price: {politics_cap}")
    print(f"Default Max Entry Price: {default_cap}")
    assert nba_cap == 0.82, f"Expected 0.82, got {nba_cap}"
    assert soccer_cap == 0.82, f"Expected 0.82, got {soccer_cap}"
    assert mlb_cap == 0.82, f"Expected 0.82, got {mlb_cap}"
    assert politics_cap == 0.75, f"Expected 0.75, got {politics_cap}"
    assert default_cap == 0.75, f"Expected 0.75, got {default_cap}"

    # 4b. Test Conviction-Based Sizing
    print("\n--- Testing Conviction-Based Sizing ---")
    # Normal conviction (ratio = 1.0) → same as base bet
    normal = FinanceController.calculate_conviction_size(100.0, 'SHARP', 50.0, 500.0, 500.0)
    print(f"Normal conviction (1.0x avg): ${normal:.2f} | Expected: $5.00")
    assert normal == 5.0, f"Expected 5.0, got {normal}"

    # High conviction (ratio = 3.0) → 1.5x base bet
    high = FinanceController.calculate_conviction_size(100.0, 'SHARP', 50.0, 1500.0, 500.0)
    print(f"High conviction (3.0x avg): ${high:.2f} | Expected: $7.50")
    assert high == 7.5, f"Expected 7.5, got {high}"

    # Low conviction (ratio = 0.2) → skip (returns 0)
    low = FinanceController.calculate_conviction_size(100.0, 'SHARP', 50.0, 100.0, 500.0)
    print(f"Low conviction (0.2x avg): ${low:.2f} | Expected: $0.00")
    assert low == 0.0, f"Expected 0.0, got {low}"

    # No specialist data → falls back to normal
    fallback = FinanceController.calculate_conviction_size(100.0, 'SHARP', 50.0, 0, 0)
    print(f"No data fallback: ${fallback:.2f} | Expected: $5.00")
    assert fallback == 5.0, f"Expected 5.0, got {fallback}"

    # 5. Test Liquidity Check
    print("\n--- Testing Order Book Liquidity Check ---")
    good_book = {"asks": [{"price": "0.55", "size": "100"}, {"price": "0.56", "size": "200"}]}
    empty_book = {"asks": []}
    thin_book = {"asks": [{"price": "0.55", "size": "1"}]}
    
    ok, liq = FinanceController.check_liquidity(good_book, 5.0)
    print(f"Good book ($5 bet): sufficient={ok}, liquidity=${liq:.2f}")
    assert ok  # 0.55*100 + 0.56*200 = 55 + 112 = $167 >> $10 needed
    
    ok, liq = FinanceController.check_liquidity(empty_book, 5.0)
    print(f"Empty book ($5 bet): sufficient={ok}, liquidity=${liq:.2f}")
    assert not ok
    
    ok, liq = FinanceController.check_liquidity(thin_book, 5.0)
    print(f"Thin book ($5 bet): sufficient={ok}, liquidity=${liq:.2f}")
    assert not ok  # Only $0.55 available, need $10

    print("\n✅ All finance math rules passed!")

if __name__ == "__main__":
    run_tests()

