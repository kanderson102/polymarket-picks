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
    st.subheader("Growth vs. Harvest")
    balance_history = db.get_balance_history()
    
    if balance_history:
        # Aggregate by date if multiple entries per day
        history_df = pd.DataFrame(balance_history, columns=['Date', 'Balance', 'Harvested'])
        # Convert Date string to datetime for better plotting
        history_df['Date'] = pd.to_datetime(history_df['Date'])
        # Group by Date and take the last balance of the day, sum harvested
        history_df = history_df.groupby('Date').agg({'Balance': 'last', 'Harvested': 'sum'})
        st.line_chart(history_df)
    else:
        st.info("Awaiting sufficient data to plot balance history. The chart will appear here once the bot completes its first daily cycle.")

    st.markdown("---")

    # 2. Live Activity Log
    st.header("Live Activity Log")
    recent_trades = db.get_all_recent_trades(limit=20)
    
    col_active, col_empty = st.columns([1, 3])
    active_positions = sum(1 for t in recent_trades if t[4] == 'PENDING') if recent_trades else 0
    col_active.metric("Active Pending Positions", active_positions)
    
    if recent_trades:
        trades_df = pd.DataFrame(recent_trades, columns=['Specialist', 'Market', 'Entry Price', 'Timestamp', 'Status'])
        # Format Entry Price
        trades_df['Entry Price'] = trades_df['Entry Price'].apply(lambda x: f"${x:.2f}")
        st.dataframe(trades_df, use_container_width=True, hide_index=True)
    else:
        st.info("No trades executed yet. The bot is actively monitoring for opportunities.")

    st.markdown("---")

    # 3. Specialist Roster & Health Monitor
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
