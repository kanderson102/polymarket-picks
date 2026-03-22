import streamlit as st
import pandas as pd
import os
from dotenv import load_dotenv
from database import TradingDB

load_dotenv()

TAG_MAP = {
    "100381": "NBA",
    "100382": "NCAAM",
    "100101": "Soccer",
    "100102": "UCL",
    "100383": "MLB",
    "100384": "NHL",
    "100401": "Tennis",
    "100601": "Tech",
    "100701": "Politics",
    "100801": "Pop Culture"
}

def get_human_readable_tags(tags):
    return " ".join([f"`{TAG_MAP.get(str(t).strip(), 'Other')}`" for t in tags])

REVERSE_TAG_MAP = {v: k for k, v in TAG_MAP.items()}

def main():
    st.set_page_config(page_title="Polymarket Copy-Bot", layout="wide")
    db = TradingDB()

    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to", ["Dashboard", "Strategy & SOP", "Architecture & Deployment", "Logs"])

    if page == "Dashboard":
        render_dashboard(db)
    elif page == "Strategy & SOP":
        render_strategy()
    elif page == "Architecture & Deployment":
        render_architecture()
    else:
        render_logs()
        
def render_dashboard(db):
    st.title("📈 Polymarket Specialist Copy-Bot")
    
    # Use standard dotenv to grab the bot's public proxy
    bot_address = os.environ.get("BOT_WALLET_ADDRESS")
    
    if bot_address:
         st.markdown(f"**[🤖 View Bot's Live Polymarket Profile](https://polymarket.com/profile/{bot_address})**")
         st.markdown("---")
    
    server_status = "🟢 LIVE" if db.is_server_alive() else "🔴 OFFLINE"
    st.markdown(f"**Bot Status**: {server_status}")
    
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
        history_df = pd.DataFrame(balance_history, columns=['Date', 'Balance', 'Harvested'])
        history_df['Date'] = pd.to_datetime(history_df['Date'])
        history_df = history_df.groupby('Date').agg({'Balance': 'last', 'Harvested': 'sum'})
        st.line_chart(history_df)
    else:
        st.info("Awaiting sufficient data to plot balance history.")

    st.markdown("---")

    # 2. Live Activity Log
    st.header("Live Activity Log")
    
    # Human readable view above
    st.subheader("Recent Highlights")
    log_path = os.path.join(os.path.dirname(__file__), "polymarket_bot.log")
    if os.path.exists(log_path):
        with open(log_path, "r") as f:
            lines = f.readlines()
        highlights = [l.strip() for l in lines if "✅" in l or "⚠️" in l or "🚨" in l]
        if highlights:
            for hl in highlights[-3:][::-1]: # show last 3 highlights
                st.write(f"- {hl}")
        else:
            st.write("No major highlights yet.")
    else:
        st.write("Log file not created yet.")
        
    st.write("")
    
    recent_trades = db.get_all_recent_trades(limit=20)
    col_active, col_empty = st.columns([1, 3])
    active_positions = sum(1 for t in recent_trades if t[4] == 'PENDING') if recent_trades else 0
    col_active.metric("Active Pending Positions", active_positions)
    
    if recent_trades:
        trades_df = pd.DataFrame(recent_trades, columns=['Specialist', 'Market', 'Entry Price', 'Timestamp', 'Status'])
        trades_df['Entry Price'] = trades_df['Entry Price'].apply(lambda x: f"${x:.2f}")
        st.dataframe(trades_df, use_container_width=True, hide_index=True)
    else:
        st.info("No trades executed yet.")

    st.markdown("---")

    # 3. Specialist Roster & Health Monitor
    st.header("Specialist Roster & Health")
    st.write("Toggle Alpha wallets to monitor and copy their trades on Polymarket.")
    
    # Add new trader form
    with st.expander("➕ Add New Trader"):
        with st.form("add_trader_form"):
            new_name = st.text_input("Trader Name")
            new_wallet = st.text_input("Wallet Address (0x...)")
            
            # User-friendly multi-select instead of manual tag IDs
            available_categories = list(TAG_MAP.values())
            selected_categories = st.multiselect("Target Categories", available_categories, help="Select ONLY the markets you have proven they consistently win in.")
            new_tags = ",".join([REVERSE_TAG_MAP[c] for c in selected_categories])
            
            # Clarified Tier explanations
            st.markdown("* **SHARP**: Volume traders (hundreds of picks). They grind 55-65% win rates consistently. (Allocated 1% per bet)*")
            st.markdown("* **WHALE**: Swing for the fences (long-shots) or 'Buy-the-Clear-Win' (huge capital yield farming). Heavy variance. (Allocated 2% per bet)*")
            new_tier = st.selectbox("Strategy Tier", ["SHARP", "WHALE"])
            
            # Vetting Mechanism
            vetted = st.checkbox("I have manually verified on Polymarket Analytics (or similar) that this trader has a high historical Win Rate specifically in the target categories listed above.")
            
            if st.form_submit_button("Add Trader"):
                if new_name and new_wallet and new_tags:
                    if not vetted:
                        st.error("⚠️ You must verify their historical category win-rate before placing them onto the active roster!")
                    else:
                        db.add_specialist(new_name, new_wallet, new_tags, new_tier)
                        st.success(f"Added {new_name} as {new_tier}!")
                        st.rerun()
                else:
                    st.error("Please fill all fields.")
                    
    st.write("")
    
    specialists = db.get_all_specialists()
    for spec in specialists:
        with st.container():
            c1, c2, c3, c4, c5, c6 = st.columns([1.5, 2, 1, 1, 0.5, 0.5])
            with c1:
                st.markdown(f"**[{spec['name']}](https://polymarket.com/@{spec['name']})**")
                st.caption(f"Strategy: {spec.get('tier', 'SHARP')}")
                if "MOCK" in spec['wallet']:
                    st.caption("⚠️ Needs Wallet Edit")
            with c2:
                # Display target tags mapped to readable names natively
                st.markdown(f"🎯 Tags: {get_human_readable_tags(spec['tags'])}")
            with c3:
                win_rate = db.get_specialist_win_rate(spec['name'])
                min_win_rate = 40.0 if spec.get('tier', 'SHARP') == 'WHALE' else 55.0
                if win_rate >= min_win_rate:
                    st.success(f"Win Rate: {win_rate}%")
                else:
                    st.error(f"Probation ({win_rate}% < {min_win_rate}%)")
            with c4:
                st.toggle("Active", value=(win_rate >= min_win_rate), key=f"tgl_{spec['name']}")
            with c5:
                if st.button("✏️", key=f"edit_btn_{spec['name']}"):
                    st.session_state[f"edit_{spec['name']}"] = not st.session_state.get(f"edit_{spec['name']}", False)
            with c6:
                if st.button("🗑️", key=f"del_btn_{spec['name']}"):
                    st.session_state[f"confirm_delete_{spec['name']}"] = True
                    
        # Edit Wallet inline form
        if st.session_state.get(f"edit_{spec['name']}", False):
            with st.container():
                col_w1, col_w2 = st.columns([4, 1])
                with col_w1:
                    new_wallet_val = st.text_input("Update Wallet Address (0x...)", value=spec['wallet'], key=f"in_{spec['name']}")
                with col_w2:
                    st.write("") # Spacing down
                    st.write("") 
                    if st.button("Save", key=f"save_{spec['name']}"):
                        if new_wallet_val:
                            db.update_specialist_wallet(spec['name'], new_wallet_val)
                            st.session_state[f"edit_{spec['name']}"] = False
                            st.rerun()

        # Trade History Expander
        with st.expander(f"📊 View Bot's Trade History for {spec['name']}"):
            spec_trades = db.get_specialist_all_trades(spec['name'])
            if spec_trades:
                tdf = pd.DataFrame(spec_trades, columns=['Market', 'Entry Price', 'Timestamp', 'Result'])
                tdf['Entry Price'] = tdf['Entry Price'].apply(lambda x: f"${x:.2f}")
                
                wins = sum(1 for t in spec_trades if t[3] == "WON")
                losses = sum(1 for t in spec_trades if t[3] == "LOST")
                pending = sum(1 for t in spec_trades if t[3] == "PENDING")
                st.write(f"**Local Bot Stats:** {wins} Wins | {losses} Losses | {pending} Pending")
                
                st.dataframe(tdf, use_container_width=True, hide_index=True)
            else:
                st.info("The bot hasn't executed any trades for this specialist yet.")
                        
        # Confirmation dialog below the row
        if st.session_state.get(f"confirm_delete_{spec['name']}", False):
            st.warning(f"Are you sure you want to delete {spec['name']}?")
            col_y, col_n = st.columns([1,1])
            with col_y:
                if st.button("Yes, Delete", key=f"yes_{spec['name']}"):
                    db.delete_specialist(spec['name'])
                    st.session_state[f"confirm_delete_{spec['name']}"] = False
                    st.rerun()
            with col_n:
                if st.button("Cancel", key=f"no_{spec['name']}"):
                    st.session_state[f"confirm_delete_{spec['name']}"] = False
                    st.rerun()
        st.write("")

def render_architecture():
    st.title("🏛️ Architecture & Deployment")
    arch_path = os.path.join(os.path.dirname(__file__), "architecture.md")
    if os.path.exists(arch_path):
        with open(arch_path, "r") as f:
            content = f.read()
        st.markdown(content)
    else:
        st.error("Architecture document not found.")

def render_strategy():
    st.title("📚 Strategy & Standard Operating Procedures")
    strategy_path = os.path.join(os.path.dirname(__file__), "strategy.md")
    if os.path.exists(strategy_path):
        with open(strategy_path, "r") as f:
            content = f.read()
        st.markdown(content)
    else:
        st.error("Strategy document not found.")

def render_logs():
    st.title("Server Logs")
    
    # Refresh logs on manual trigger
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("🔄 Refresh"):
            st.rerun()
            
    log_path = os.path.join(os.path.dirname(__file__), "polymarket_bot.log")
    if os.path.exists(log_path):
        with open(log_path, "r") as f:
            log_content = f.read()
        st.text_area("Live bot output", log_content, height=600)
    else:
        st.info("Log file does not exist yet. Run the bot to generate logs.")

if __name__ == "__main__":
    main()
