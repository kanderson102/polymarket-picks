import streamlit as st
import pandas as pd
from database import TradingDB
from bot import SPECIALISTS

def main():
    st.set_page_config(page_title="Polymarket Copy-Bot", layout="wide")
    st.title("📈 Polymarket Specialist Copy-Bot")
    
    db = TradingDB()
    baseline, harvested = db.get_performance()
    
    # 1. Dashboard Metrics
    st.header("Financial Performance")
    col1, col2, col3 = st.columns(3)
    
    # For Phase 1 we mock the current wallet balance here as $50
    current_wallet_balance = 50.0  
    profit = current_wallet_balance - baseline if current_wallet_balance > baseline else 0
    
    col1.metric("Current Balance (USDC)", f"${current_wallet_balance:.2f}", f"${profit:.2f} profit")
    col2.metric("Baseline Capital", f"${baseline:.2f}")
    col3.metric("Total Harvested (to Main Wallet)", f"${harvested:.2f}")

    # Growth vs Harvest Chart
    # Mocking historical growth over time for the UI
    st.subheader("Growth vs. Harvest")
    chart_data = pd.DataFrame({
        'Date': pd.date_range(start='1/1/2026', periods=5),
        'Balance': [50, 65, 80, 105, 75],      # Hit 100+ -> Harvest triggers
        'Harvested': [0, 0, 0, 25, 25]         # Harvested $25 to Main Wallet
    }).set_index('Date')
    st.line_chart(chart_data)

    st.markdown("---")

    # 2. Specialist Roster & Health Monitor
    st.header("Specialist Roster & Health")
    st.write("Toggle Alpha wallets to monitor and copy their trades on Polymarket.")
    
    for spec in SPECIALISTS:
        with st.container():
            c1, c2, c3, c4 = st.columns([1, 2, 1, 1])
            with c1:
                st.write(f"**{spec.name}**")
            with c2:
                # Display target tags mapped to readable names natively if we had a dictionary
                st.write(f"🎯 Tags: {', '.join(spec.target_tags)}")
            with c3:
                win_rate = db.get_specialist_win_rate(spec.name)
                # If Win Rate < 55%, show warning
                if win_rate >= 55.0:
                    st.success(f"Win Rate: {win_rate}%")
                else:
                    st.error(f"Probation ({win_rate}%)")
            with c4:
                # Toggle Status
                st.toggle(f"Active", value=(win_rate >= 55.0), key=spec.name)
        st.write("") # Spacing

if __name__ == "__main__":
    main()
