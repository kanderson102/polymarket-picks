import streamlit as st
import pandas as pd
import numpy as np
import os
import json
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from database import TradingDB
from finance import FinanceController

load_dotenv()

DATA_API_URL = "https://data-api.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com"

TAG_MAP = {
    "745": "NBA",
    "28": "Basketball",
    "100350": "Soccer",
    "100977": "UCL",
    "306": "EPL",
    "82": "Premier League",
    "100381": "MLB",
    "678": "baseball",
    "899": "NHL",
    "100088": "Hockey",
    "100089": "Stanley Cup",
    "64": "Esports",
    "2": "Politics",
    "144": "Elections",
    "100265": "Geopolitics",
    "1": "Sports",
    "100639": "Games",
}

def get_human_readable_tags(tags):
    return " ".join([f"`{TAG_MAP.get(str(t).strip(), 'Other')}`" for t in tags])

REVERSE_TAG_MAP = {v: k for k, v in TAG_MAP.items()}

def _init_saved_views():
    """Initialize session state for saved backtest views."""
    if "saved_mc_views" not in st.session_state:
        st.session_state.saved_mc_views = []
    if "saved_hb_views" not in st.session_state:
        st.session_state.saved_hb_views = []


def main():
    st.set_page_config(page_title="Polymarket Copy-Bot", layout="wide")
    _init_saved_views()
    db = TradingDB()

    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to", ["Dashboard", "Backtest Simulator", "Historical Backtest", "Strategy & SOP", "Architecture & Deployment", "Logs"])

    if page == "Dashboard":
        render_dashboard(db)
    elif page == "Backtest Simulator":
        render_backtest(db)
    elif page == "Historical Backtest":
        render_historical_backtest(db)
    elif page == "Strategy & SOP":
        render_strategy()
    elif page == "Architecture & Deployment":
        render_architecture()
    else:
        render_logs()
        
def render_dashboard(db):
    st.title("📈 Polymarket Specialist Copy-Bot")
    
    # Use standard dotenv to grab the bot's public proxy
    bot_address = os.environ.get("BOT_WALLET_ADDRESS", "").strip("\"'")
    
    if bot_address:
         st.markdown(f"**[🤖 View Bot's Live Polymarket Profile](https://polymarket.com/profile/{bot_address})**")
         st.markdown("---")
    
    server_status = "🟢 LIVE" if db.is_server_alive() else "🔴 OFFLINE"
    st.markdown(f"**Bot Status**: {server_status}")
    
    baseline, harvested = db.get_performance()
    
    # 1. Dashboard Metrics
    st.header("Financial Performance")
    col1, col2, col3 = st.columns(3)
    
    # For Phase 1 we calculate available balance based on pending exposure
    exposure = db.get_total_pending_exposure()
    current_wallet_balance = 50.0 - exposure
    profit = (current_wallet_balance + exposure) - baseline if (current_wallet_balance + exposure) > baseline else 0
    
    col1.metric("Current Balance (USDC)", f"${current_wallet_balance:.2f}", f"${profit:.2f} profit")
    col2.metric("Baseline Capital", f"${baseline:.2f}")
    col3.metric("Total Harvested (to Main Wallet)", f"${harvested:.2f}")
    
    st.write("")
    if st.button("🧹 Purge All Pending Trades (Reset Simulator Budget)", help="Clears all active pending trades from the local database to reset your paper balance back to original budget."):
        db.clear_all_pending_trades()
        st.rerun()

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
    st.write("")
    
    recent_trades = db.get_all_recent_trades(limit=1000)
    col_active, col_empty = st.columns([1, 3])
    active_positions = sum(1 for t in recent_trades if t[4] == 'PENDING') if recent_trades else 0
    col_active.metric("Active Pending Positions", active_positions)
    
    if recent_trades:
        trades_df = pd.DataFrame(recent_trades[:20], columns=['Specialist', 'Market', 'Entry Price', 'Timestamp', 'Status', 'Slug', 'Outcome', 'Bet Size', 'End Date'])
        trades_df['Entry Price'] = trades_df['Entry Price'].apply(lambda x: f"${x:.2f}")
        trades_df['Bet Size'] = trades_df['Bet Size'].apply(lambda x: f"${x:.2f}" if x and x > 0 else "—")
        # Make Specialist name a clickable link to their Polymarket profile
        trades_df['Specialist'] = trades_df['Specialist'].apply(lambda x: f"https://polymarket.com/@{x}")
        # Make Market a clickable link to the event
        trades_df['Market Link'] = trades_df.apply(
            lambda r: f"https://polymarket.com/event/{r['Slug']}" if r['Slug'] else "", axis=1
        )
        # Format end date as readable
        trades_df['Est. Close'] = trades_df['End Date'].apply(
            lambda x: x.split('T')[0] if x and 'T' in str(x) else (x if x else "—")
        )
        # Select and reorder columns
        trades_df = trades_df[['Specialist', 'Market', 'Market Link', 'Outcome', 'Entry Price', 'Bet Size', 'Status', 'Timestamp', 'Est. Close']]
        
        st.dataframe(
            trades_df, 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "Specialist": st.column_config.LinkColumn("Specialist", display_text=r"https://polymarket\.com/@(.+)"),
                "Market Link": st.column_config.LinkColumn("Market", display_text="Open ↗"),
            }
        )
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
            st.markdown("* **SHARP**: Volume traders (hundreds of picks). They grind 55-65% win rates consistently. (Allocated 5% per bet)*")
            st.markdown("* **WHALE**: Swing for the fences (long-shots) or 'Buy-the-Clear-Win' (huge capital yield farming). Heavy variance. (Allocated 3% per bet)*")
            new_tier = st.selectbox("Strategy Tier", ["SHARP", "WHALE"])
            
            # Vetting Mechanism
            vetted = st.checkbox("I have manually verified on Polymarket Analytics (or similar) that this trader has a high historical Win Rate specifically in the target categories listed above.")
            
            if st.form_submit_button("Add Trader"):
                if new_name and new_wallet and new_tags:
                    if not vetted:
                        st.error("⚠️ You must verify their historical category win-rate before placing them onto the active roster!")
                    else:
                        try:
                            db.add_specialist(new_name, new_wallet, new_tags, new_tier)
                            st.success(f"Added {new_name} as {new_tier}!")
                            st.rerun()
                        except ValueError as e:
                            st.error(f"Duplicate wallet: {e}")
                        except Exception as e:
                            st.error(f"Failed to add: {e}")
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
                
                # Read actual toggle state from DB
                is_active_val = spec.get('is_active', True)
            with c4:
                def toggle_act(n=spec['name']):
                    db.set_specialist_active(n, st.session_state[f"tgl_{n}"])
                st.toggle("Active", value=is_active_val, key=f"tgl_{spec['name']}", on_change=toggle_act)
            with c5:
                if st.button("✏️", key=f"edit_btn_{spec['name']}"):
                    st.session_state[f"edit_{spec['name']}"] = not st.session_state.get(f"edit_{spec['name']}", False)
            with c6:
                if st.button("🗑️", key=f"del_btn_{spec['name']}"):
                    st.session_state[f"confirm_delete_{spec['name']}"] = True
                    
        # Edit inline form
        if st.session_state.get(f"edit_{spec['name']}", False):
            with st.container():
                col_w1, col_w2, col_w3 = st.columns([2, 2, 1])
                with col_w1:
                    new_wallet_val = st.text_input("Update Wallet Address", value=spec['wallet'], key=f"in_{spec['name']}")
                with col_w2:
                    current_mapped = [TAG_MAP[t] for t in spec['tags'] if t in TAG_MAP]
                    selected_cats = st.multiselect("Update Categories", list(TAG_MAP.values()), default=current_mapped, key=f"tg_{spec['name']}")
                with col_w3:
                    st.write("") # Spacing down
                    st.write("") 
                    if st.button("Save", key=f"save_{spec['name']}"):
                        new_tags_val = ",".join([REVERSE_TAG_MAP[c] for c in selected_cats])
                        if new_wallet_val and new_tags_val:
                            try:
                                db.update_specialist_wallet(spec['name'], new_wallet_val)
                                db.update_specialist_tags(spec['name'], new_tags_val)
                                st.session_state[f"edit_{spec['name']}"] = False
                                st.rerun()
                            except ValueError as e:
                                st.error(f"Duplicate wallet: {e}")

        # Trade History Expander
        with st.expander(f"📊 View Bot's Trade History for {spec['name']}"):
            spec_trades = db.get_specialist_all_trades(spec['name'])
            if spec_trades:
                tdf = pd.DataFrame(spec_trades, columns=['Market', 'Entry Price', 'Timestamp', 'Result', 'Slug', 'Outcome', 'Bet Size', 'End Date'])
                tdf['Entry Price'] = tdf['Entry Price'].apply(lambda x: f"${x:.2f}")
                tdf['Bet Size'] = tdf['Bet Size'].apply(lambda x: f"${x:.2f}" if x and x > 0 else "—")
                tdf['Market Link'] = tdf['Slug'].apply(lambda x: f"https://polymarket.com/event/{x}" if x else "")
                tdf['Est. Close'] = tdf['End Date'].apply(
                    lambda x: x.split('T')[0] if x and 'T' in str(x) else (x if x else "—")
                )
                # Reorder columns
                tdf = tdf[['Market', 'Market Link', 'Outcome', 'Entry Price', 'Bet Size', 'Result', 'Timestamp', 'Est. Close']]
                
                wins = sum(1 for t in spec_trades if t[3] == "WON")
                losses = sum(1 for t in spec_trades if t[3] == "LOST")
                pending = sum(1 for t in spec_trades if t[3] == "PENDING")
                st.write(f"**Local Bot Stats:** {wins} Wins | {losses} Losses | {pending} Pending")
                
                st.dataframe(
                    tdf, 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={
                        "Market Link": st.column_config.LinkColumn("Link", display_text="Open ↗")
                    }
                )
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

def render_backtest(db):
    st.title("🧪 Backtest Simulator")
    st.markdown("Monte Carlo simulation using the bot's actual Kelly criterion sizing, value caps, slippage, and harvest logic.")

    # --- Sidebar Controls ---
    st.sidebar.markdown("---")
    st.sidebar.header("Simulation Parameters")

    bankroll = st.sidebar.number_input("Starting Bankroll ($)", min_value=10.0, max_value=100000.0, value=50.0, step=10.0)
    days = st.sidebar.slider("Simulation Days", min_value=7, max_value=365, value=90)
    num_simulations = st.sidebar.slider("Monte Carlo Runs", min_value=50, max_value=2000, value=500, step=50)

    st.sidebar.markdown("---")
    st.sidebar.subheader("Specialist Mix")
    num_sharp = st.sidebar.number_input("SHARP Specialists", min_value=0, max_value=20, value=7)
    num_whale = st.sidebar.number_input("WHALE Specialists", min_value=0, max_value=10, value=2)
    sharp_wr = st.sidebar.slider("SHARP Avg Win Rate (%)", min_value=40.0, max_value=80.0, value=58.0, step=1.0)
    whale_wr = st.sidebar.slider("WHALE Avg Win Rate (%)", min_value=30.0, max_value=70.0, value=48.0, step=1.0)

    st.sidebar.markdown("---")
    st.sidebar.subheader("Market Conditions")
    trades_per_day = st.sidebar.slider("Avg Trades/Day (all specialists)", min_value=1, max_value=30, value=8)
    avg_entry_price = st.sidebar.slider("Avg Entry Price ($)", min_value=0.10, max_value=0.90, value=0.45, step=0.05)
    slippage_pct = st.sidebar.slider("Avg Slippage (%)", min_value=0.0, max_value=5.0, value=1.0, step=0.25)
    avg_fee_rate = st.sidebar.slider("Avg Taker Fee (%)", min_value=0.0, max_value=2.0, value=0.75, step=0.05)

    st.sidebar.markdown("---")
    st.sidebar.subheader("Risk & Harvest")
    enable_harvest = st.sidebar.checkbox("Enable 2x Harvest Rule", value=True)
    min_buffer = st.sidebar.number_input("Min Buffer ($)", min_value=1.0, max_value=50.0, value=5.0, step=1.0)
    max_slippage = st.sidebar.slider("Max Slippage Reject (%)", min_value=0.5, max_value=10.0, value=2.5, step=0.5)

    # Collect current params for saved views
    mc_params = {
        "bankroll": bankroll, "days": days, "num_simulations": num_simulations,
        "num_sharp": num_sharp, "num_whale": num_whale,
        "sharp_wr": sharp_wr, "whale_wr": whale_wr,
        "trades_per_day": trades_per_day, "avg_entry_price": avg_entry_price,
        "slippage_pct": slippage_pct, "avg_fee_rate": avg_fee_rate,
        "enable_harvest": enable_harvest, "min_buffer": min_buffer,
        "max_slippage": max_slippage,
    }

    if st.button("Run Simulation", type="primary"):
        results = _run_monte_carlo(**mc_params)
        st.session_state["_last_mc_results"] = results
        st.session_state["_last_mc_params"] = mc_params

    # Render last results if available
    results = st.session_state.get("_last_mc_results")
    params = st.session_state.get("_last_mc_params")
    if results is not None and params is not None:
        _render_backtest_results(results, params["bankroll"], params["days"], params["enable_harvest"])
        _render_save_view_mc(results, params)

    # Always show saved views comparison at bottom
    _render_saved_mc_comparison()


def _run_monte_carlo(*, bankroll, days, num_simulations, num_sharp, num_whale,
                     sharp_wr, whale_wr, trades_per_day, avg_entry_price,
                     slippage_pct, avg_fee_rate, enable_harvest, min_buffer,
                     max_slippage):
    """Run Monte Carlo simulation using actual strategy parameters."""
    rng = np.random.default_rng(seed=42)
    total_specialists = num_sharp + num_whale

    if total_specialists == 0:
        return None

    # Pre-compute specialist profiles
    specs = []
    for _ in range(num_sharp):
        # Add some variance around the average win rate
        wr = np.clip(rng.normal(sharp_wr, 4.0), 40, 85)
        specs.append(("SHARP", wr))
    for _ in range(num_whale):
        wr = np.clip(rng.normal(whale_wr, 6.0), 25, 75)
        specs.append(("WHALE", wr))

    all_equity_curves = np.zeros((num_simulations, days + 1))
    final_balances = np.zeros(num_simulations)
    total_harvested_all = np.zeros(num_simulations)
    total_trades_all = np.zeros(num_simulations, dtype=int)
    total_wins_all = np.zeros(num_simulations, dtype=int)
    total_losses_all = np.zeros(num_simulations, dtype=int)
    total_skipped_all = np.zeros(num_simulations, dtype=int)
    max_drawdown_all = np.zeros(num_simulations)

    progress = st.progress(0, text="Running simulations...")

    for sim in range(num_simulations):
        balance = bankroll
        baseline = bankroll
        harvested = 0.0
        equity = [balance]
        peak = balance
        max_dd = 0.0
        wins = 0
        losses = 0
        skipped = 0
        trades_count = 0

        for day in range(days):
            # Random number of trades today (Poisson distribution)
            n_trades = rng.poisson(trades_per_day)

            for _ in range(n_trades):
                if balance < min_buffer:
                    skipped += 1
                    continue

                # Pick a random specialist
                idx = rng.integers(0, total_specialists)
                tier, wr = specs[idx]

                # Simulate entry price with some variance
                entry = np.clip(rng.normal(avg_entry_price, 0.10), 0.05, 0.95)

                # Value cap check
                max_price = 0.65  # Average across categories
                if entry > max_price:
                    skipped += 1
                    continue

                # Slippage simulation
                actual_slippage = abs(rng.normal(slippage_pct, 0.5))
                if actual_slippage > max_slippage:
                    skipped += 1
                    continue

                # Calculate bet size using actual Kelly formula
                bet_size = FinanceController.calculate_bet_size(balance, tier, wr)
                available = balance - min_buffer
                if bet_size > available:
                    bet_size = available
                if bet_size <= 0:
                    skipped += 1
                    continue

                # Apply slippage cost to entry price
                effective_entry = entry * (1 + actual_slippage / 100)

                # Fee cost
                fee = bet_size * (avg_fee_rate / 100)

                # Determine win/loss using specialist's actual win rate
                won = rng.random() < (wr / 100)

                trades_count += 1
                if won:
                    # Payout: bet_size / entry_price (shares purchased), minus fees
                    payout = (bet_size / effective_entry) - fee
                    profit = payout - bet_size
                    balance += profit
                    wins += 1
                else:
                    balance -= (bet_size + fee)
                    losses += 1

                balance = max(0.0, balance)

                # Track drawdown
                if balance > peak:
                    peak = balance
                dd = (peak - balance) / peak if peak > 0 else 0
                if dd > max_dd:
                    max_dd = dd

            # Harvest check at end of day
            if enable_harvest:
                result = FinanceController.check_harvest(balance, baseline)
                if result.triggered:
                    harvested += result.transfer_amount
                    balance = result.new_balance
                    baseline = result.new_baseline

            equity.append(balance + harvested)

        all_equity_curves[sim] = equity
        final_balances[sim] = balance + harvested
        total_harvested_all[sim] = harvested
        total_trades_all[sim] = trades_count
        total_wins_all[sim] = wins
        total_losses_all[sim] = losses
        total_skipped_all[sim] = skipped
        max_drawdown_all[sim] = max_dd

        if (sim + 1) % max(1, num_simulations // 20) == 0:
            progress.progress((sim + 1) / num_simulations, text=f"Simulation {sim+1}/{num_simulations}")

    progress.empty()

    return {
        "equity_curves": all_equity_curves,
        "final_balances": final_balances,
        "harvested": total_harvested_all,
        "trades": total_trades_all,
        "wins": total_wins_all,
        "losses": total_losses_all,
        "skipped": total_skipped_all,
        "max_drawdown": max_drawdown_all,
    }


def _render_backtest_results(results, bankroll, days, enable_harvest):
    """Render the simulation results with highlights, charts, and tables."""
    if results is None:
        st.error("Add at least one specialist to run the simulation.")
        return

    finals = results["final_balances"]
    harvested = results["harvested"]
    trades = results["trades"]
    wins = results["wins"]
    losses = results["losses"]
    skipped = results["skipped"]
    max_dd = results["max_drawdown"]
    curves = results["equity_curves"]

    # --- Highlight Metrics ---
    st.header("Simulation Results")

    median_final = np.median(finals)
    mean_final = np.mean(finals)
    roi = ((median_final - bankroll) / bankroll) * 100

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Median Final Value", f"${median_final:.2f}", f"{roi:+.1f}% ROI")
    col2.metric("Mean Final Value", f"${mean_final:.2f}")
    col3.metric("Best Case (95th)", f"${np.percentile(finals, 95):.2f}")
    col4.metric("Worst Case (5th)", f"${np.percentile(finals, 5):.2f}")

    st.markdown("")

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Median Trades", f"{int(np.median(trades))}")
    avg_wr = np.mean(wins / np.maximum(wins + losses, 1)) * 100
    col6.metric("Avg Win Rate", f"{avg_wr:.1f}%")
    col7.metric("Avg Max Drawdown", f"{np.mean(max_dd)*100:.1f}%")
    if enable_harvest:
        col8.metric("Median Harvested", f"${np.median(harvested):.2f}")
    else:
        col8.metric("Ruin Rate (<$5)", f"{np.mean(finals < 5)*100:.1f}%")

    st.markdown("---")

    # --- Equity Curve Fan Chart ---
    st.subheader("Equity Curves (Fan Chart)")
    st.caption("Shaded regions show 10th-90th percentile range. Bold line is the median path.")

    p10 = np.percentile(curves, 10, axis=0)
    p25 = np.percentile(curves, 25, axis=0)
    p50 = np.percentile(curves, 50, axis=0)
    p75 = np.percentile(curves, 75, axis=0)
    p90 = np.percentile(curves, 90, axis=0)

    day_labels = list(range(days + 1))
    chart_df = pd.DataFrame({
        "Day": day_labels,
        "10th Pct": p10,
        "25th Pct": p25,
        "Median": p50,
        "75th Pct": p75,
        "90th Pct": p90,
    }).set_index("Day")
    st.area_chart(chart_df, color=["#ff6b6b", "#ffa94d", "#51cf66", "#339af0", "#845ef7"])

    # --- Sample Paths ---
    st.subheader("Sample Equity Paths (10 Random Runs)")
    rng = np.random.default_rng(seed=0)
    sample_idxs = rng.choice(len(finals), size=min(10, len(finals)), replace=False)
    sample_df = pd.DataFrame(
        {f"Run {i+1}": curves[idx] for i, idx in enumerate(sample_idxs)},
        index=day_labels
    )
    sample_df.index.name = "Day"
    st.line_chart(sample_df)

    st.markdown("---")

    # --- Final Balance Distribution ---
    st.subheader("Final Balance Distribution")
    hist_df = pd.DataFrame({"Final Balance ($)": finals})
    st.bar_chart(hist_df["Final Balance ($)"].value_counts(bins=40).sort_index())

    st.markdown("---")

    # --- Probability Table ---
    st.subheader("Outcome Probabilities")
    thresholds = [
        ("Break Even", bankroll),
        ("1.5x ($" + f"{bankroll*1.5:.0f})", bankroll * 1.5),
        ("2x ($" + f"{bankroll*2:.0f})", bankroll * 2),
        ("3x ($" + f"{bankroll*3:.0f})", bankroll * 3),
        ("5x ($" + f"{bankroll*5:.0f})", bankroll * 5),
        ("10x ($" + f"{bankroll*10:.0f})", bankroll * 10),
    ]
    prob_data = []
    for label, threshold in thresholds:
        prob = np.mean(finals >= threshold) * 100
        prob_data.append({"Target": label, "Probability": f"{prob:.1f}%", "Odds": f"1 in {max(1, int(100/prob))}" if prob > 0 else "Very unlikely"})
    st.table(pd.DataFrame(prob_data))

    # --- Ruin & Drawdown ---
    st.subheader("Risk Metrics")
    col_r1, col_r2, col_r3 = st.columns(3)
    col_r1.metric("Ruin Rate (Balance < $1)", f"{np.mean(finals < 1)*100:.1f}%")
    col_r2.metric("Loss Rate (Below Start)", f"{np.mean(finals < bankroll)*100:.1f}%")
    col_r3.metric("Worst Drawdown (Median)", f"{np.median(max_dd)*100:.1f}%")

    st.markdown("---")

    # --- Summary Statistics Table ---
    st.subheader("Detailed Statistics")
    stats = {
        "Metric": [
            "Starting Bankroll", "Simulation Period",
            "Median Final", "Mean Final", "Std Dev",
            "Min Final", "Max Final",
            "5th Percentile", "25th Percentile", "75th Percentile", "95th Percentile",
            "Median ROI", "Mean Trades/Sim", "Mean Skipped/Sim",
            "Avg Win Rate", "Mean Max Drawdown",
        ],
        "Value": [
            f"${bankroll:.2f}", f"{days} days",
            f"${np.median(finals):.2f}", f"${np.mean(finals):.2f}", f"${np.std(finals):.2f}",
            f"${np.min(finals):.2f}", f"${np.max(finals):.2f}",
            f"${np.percentile(finals, 5):.2f}", f"${np.percentile(finals, 25):.2f}",
            f"${np.percentile(finals, 75):.2f}", f"${np.percentile(finals, 95):.2f}",
            f"{roi:+.1f}%", f"{np.mean(trades):.0f}", f"{np.mean(skipped):.0f}",
            f"{avg_wr:.1f}%", f"{np.mean(max_dd)*100:.1f}%",
        ]
    }
    if enable_harvest:
        stats["Metric"].extend(["Median Harvested", "Mean Harvested", "Max Harvested"])
        stats["Value"].extend([
            f"${np.median(harvested):.2f}", f"${np.mean(harvested):.2f}", f"${np.max(harvested):.2f}",
        ])
    st.table(pd.DataFrame(stats))


def _render_save_view_mc(results, params):
    """Save current Monte Carlo results as a named view."""
    st.markdown("---")
    st.subheader("Save This View")
    col_name, col_btn = st.columns([3, 1])
    with col_name:
        view_name = st.text_input("View Name", value=f"View {len(st.session_state.saved_mc_views) + 1}", key="mc_view_name")
    with col_btn:
        st.write("")  # spacer
        if st.button("Save View", key="mc_save_btn"):
            finals = results["final_balances"]
            harvested = results["harvested"]
            trades = results["trades"]
            wins = results["wins"]
            losses = results["losses"]
            max_dd = results["max_drawdown"]
            bankroll = params["bankroll"]
            median_final = float(np.median(finals))
            roi = ((median_final - bankroll) / bankroll) * 100
            avg_wr = float(np.mean(wins / np.maximum(wins + losses, 1)) * 100)
            view = {
                "name": view_name,
                "params": params.copy(),
                "metrics": {
                    "median_final": median_final,
                    "mean_final": float(np.mean(finals)),
                    "p5": float(np.percentile(finals, 5)),
                    "p95": float(np.percentile(finals, 95)),
                    "roi": roi,
                    "avg_win_rate": avg_wr,
                    "avg_max_dd": float(np.mean(max_dd) * 100),
                    "median_trades": int(np.median(trades)),
                    "median_harvested": float(np.median(harvested)),
                    "ruin_rate": float(np.mean(finals < 5) * 100),
                },
            }
            st.session_state.saved_mc_views.append(view)
            st.success(f"Saved **{view_name}**")
            st.rerun()


def _render_saved_mc_comparison():
    """Show saved Monte Carlo views in a comparison table."""
    views = st.session_state.saved_mc_views
    if not views:
        return

    st.markdown("---")
    st.header("Saved Views Comparison")

    # Build comparison table
    rows = []
    for v in views:
        m = v["metrics"]
        p = v["params"]
        rows.append({
            "View": v["name"],
            "Bankroll": f"${p['bankroll']:.0f}",
            "Days": p["days"],
            "Sims": p["num_simulations"],
            "SHARP/WHALE": f"{p['num_sharp']}/{p['num_whale']}",
            "SHARP WR": f"{p['sharp_wr']:.0f}%",
            "WHALE WR": f"{p['whale_wr']:.0f}%",
            "Trades/Day": p["trades_per_day"],
            "Median Final": f"${m['median_final']:.2f}",
            "ROI": f"{m['roi']:+.1f}%",
            "Win Rate": f"{m['avg_win_rate']:.1f}%",
            "Max DD": f"{m['avg_max_dd']:.1f}%",
            "P5": f"${m['p5']:.2f}",
            "P95": f"${m['p95']:.2f}",
            "Harvested": f"${m['median_harvested']:.2f}",
            "Ruin %": f"{m['ruin_rate']:.1f}%",
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Delete buttons
    st.caption("Remove saved views:")
    cols = st.columns(min(len(views), 6))
    for i, v in enumerate(views):
        with cols[i % len(cols)]:
            if st.button(f"Delete: {v['name']}", key=f"mc_del_{i}"):
                st.session_state.saved_mc_views.pop(i)
                st.rerun()


SPORTS_TAGS = {"745", "28", "100350", "100977", "306", "82", "100381", "678", "899", "100088", "100089", "1", "100639", "64", "102366"}
MAX_DAYS_SPORTS = 30
MAX_DAYS_DEFAULT = 14

# Tag groups: tags in the same group are considered equivalent for matching.
# If a specialist has any tag in a group, they match markets with any tag in that group.
TAG_GROUPS = [
    {"745", "28"},                              # NBA / Basketball
    {"100350", "306", "82", "100977", "101962"}, # Soccer / EPL / Premier League / UCL
    {"100381", "678"},                           # MLB / baseball
    {"899", "100088", "100089"},                 # NHL / Hockey / Stanley Cup
    {"64", "102366"},                            # Esports / Dota 2
    {"2", "144", "100265"},                      # Politics / Elections / Geopolitics
    {"1", "100639"},                             # Sports / Games (generic parents)
]


def _expand_tags(tags: list[str]) -> set[str]:
    """Expand a list of tags to include all related tags from the same groups."""
    expanded = set(tags)
    for group in TAG_GROUPS:
        if expanded & group:  # If any of our tags are in this group
            expanded |= group  # Add all tags from this group
    return expanded


def _resolve_trade(event_info: dict, trade_title: str, our_outcome: str, trade_dt: datetime) -> str:
    """Determine if a trade WON, LOST, or is PENDING using Gamma market data.

    Uses outcomePrices from the Gamma API: if a market is closed and
    outcomePrices shows one outcome at "1" and others at "0", it's resolved.
    """
    markets = event_info.get("markets", [])

    for market in markets:
        # Match our trade to the correct market within the event
        question = market.get("question", "")
        if trade_title not in question and question not in trade_title:
            # Try fuzzy match — sometimes titles differ slightly
            # Use the slug-based match or check if the key terms overlap
            title_words = set(trade_title.lower().split())
            question_words = set(question.lower().split())
            if len(title_words & question_words) < 2:
                continue

        if not market.get("closed", False):
            return "PENDING"

        outcomes = market.get("outcomes", [])
        outcome_prices = market.get("outcomePrices", [])

        if not outcomes or not outcome_prices:
            continue

        # Find winning outcome (the one with price "1" or close to it)
        winning_outcome = None
        for i, op in enumerate(outcome_prices):
            try:
                if float(op) >= 0.95 and i < len(outcomes):
                    winning_outcome = outcomes[i]
                    break
            except (ValueError, TypeError):
                continue

        if winning_outcome is None:
            return "PENDING"

        return "WON" if our_outcome == winning_outcome else "LOST"

    # No matching market found — check end date
    end_date_str = event_info.get("end_date", "")
    if end_date_str:
        try:
            end_dt = datetime.strptime(end_date_str, "%Y-%m-%d")
            if end_dt < datetime.utcnow():
                return "LOST"  # Market ended, no resolution data, assume loss
        except ValueError:
            pass

    # Fallback: if trade is old enough, mark as lost
    if (datetime.utcnow() - trade_dt).days > 3:
        return "LOST"

    return "PENDING"


def _fetch_specialist_activity(wallet: str, limit: int = 200) -> list[dict]:
    """Fetch trade activity for a specialist from Polymarket Data API."""
    all_activity = []
    offset = 0
    batch = 50
    while offset < limit:
        try:
            resp = requests.get(
                f"{DATA_API_URL}/activity",
                params={"user": wallet, "limit": min(batch, limit - offset), "offset": offset},
                timeout=10,
            )
            if resp.status_code != 200:
                break
            data = resp.json()
            if not data:
                break
            all_activity.extend(data)
            if len(data) < batch:
                break
            offset += batch
        except Exception:
            break
    return all_activity


def _lookup_event_info(event_slug: str) -> dict:
    """Look up market tags, end date, and resolution from Gamma API (cached in session state).
    Returns {"tags": [...], "end_date": "YYYY-MM-DD", "markets": [...]}."""
    cache_key = f"_event_info_{event_slug}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]
    result = {"tags": [], "end_date": "", "markets": []}
    try:
        resp = requests.get(f"{GAMMA_API_URL}/events?slug={event_slug}", timeout=5)
        if resp.status_code == 200:
            events = resp.json()
            if events:
                event = events[0]
                for tag in event.get("tags", []):
                    tag_id = str(tag.get("id", "")) if isinstance(tag, dict) else str(tag)
                    if tag_id:
                        result["tags"].append(tag_id)
                # Get market resolution data
                markets = event.get("markets", [])
                for m in markets:
                    # outcomes and outcomePrices may be JSON strings from the API
                    raw_outcomes = m.get("outcomes", [])
                    raw_prices = m.get("outcomePrices", [])
                    if isinstance(raw_outcomes, str):
                        try:
                            raw_outcomes = json.loads(raw_outcomes)
                        except (json.JSONDecodeError, TypeError):
                            raw_outcomes = []
                    if isinstance(raw_prices, str):
                        try:
                            raw_prices = json.loads(raw_prices)
                        except (json.JSONDecodeError, TypeError):
                            raw_prices = []
                    market_info = {
                        "question": m.get("question", ""),
                        "slug": m.get("slug", ""),
                        "closed": bool(m.get("closed", False)),
                        "outcomes": raw_outcomes,
                        "outcomePrices": raw_prices,
                        "endDate": m.get("endDate", ""),
                        "conditionId": m.get("conditionId", ""),
                    }
                    result["markets"].append(market_info)
                # End date from first market
                if markets:
                    end = markets[0].get("endDate", "")
                    if end:
                        result["end_date"] = end.split("T")[0] if "T" in end else end
                if not result["end_date"]:
                    end = event.get("endDate", "") or event.get("end_date_iso", "")
                    if end:
                        result["end_date"] = end.split("T")[0] if "T" in end else end
    except Exception:
        pass
    st.session_state[cache_key] = result
    return result


def _lookup_event_tags(event_slug: str) -> list[str]:
    """Convenience wrapper returning just tags."""
    return _lookup_event_info(event_slug).get("tags", [])


def render_historical_backtest(db):
    st.title("📜 Historical Backtest")
    st.markdown("Replay your specialists' **real Polymarket trades** through the bot's strategy rules to see what it would have copied and the resulting P&L.")

    # --- Controls ---
    st.sidebar.markdown("---")
    st.sidebar.header("Historical Backtest")
    bankroll = st.sidebar.number_input("Starting Bankroll ($)", min_value=10.0, max_value=100000.0, value=50.0, step=10.0, key="hb_bankroll")
    max_trades_per_spec = st.sidebar.slider("Max Trades to Fetch (per specialist)", 50, 500, 200, step=50, key="hb_limit")
    lookback_days = st.sidebar.slider("Lookback Window (days)", 7, 180, 60, key="hb_lookback")
    enable_harvest = st.sidebar.checkbox("Enable 2x Harvest Rule", value=True, key="hb_harvest")
    min_buffer = st.sidebar.number_input("Min Buffer ($)", min_value=1.0, max_value=50.0, value=5.0, step=1.0, key="hb_buffer")
    st.sidebar.markdown("---")
    st.sidebar.subheader("Date Filter")
    max_days_sports = st.sidebar.slider("Max Days Out (Sports)", 7, 90, 30, key="hb_max_days_sports")
    max_days_other = st.sidebar.slider("Max Days Out (Non-Sports)", 7, 90, 14, key="hb_max_days_other")

    specialists = db.get_all_specialists()
    active_specs = [s for s in specialists if s.get("is_active", True) and "MOCK" not in s["wallet"]]

    if not active_specs:
        st.warning("No active specialists with real wallets found.")
        return

    spec_names = [s["name"] for s in active_specs]
    selected = st.sidebar.multiselect("Specialists to Include", spec_names, default=spec_names, key="hb_specs")

    hb_params = {
        "bankroll": bankroll, "max_trades_per_spec": max_trades_per_spec,
        "lookback_days": lookback_days, "enable_harvest": enable_harvest,
        "min_buffer": min_buffer, "max_days_sports": max_days_sports,
        "max_days_other": max_days_other, "selected": selected,
    }

    run_clicked = st.button("Run Historical Backtest", type="primary", key="hb_run")

    # Always show saved views comparison
    _render_saved_hb_comparison()

    if not run_clicked:
        if "_last_hb_results" not in st.session_state:
            st.info("Configure parameters in the sidebar and click **Run Historical Backtest** to begin.")
        else:
            # Re-render last results
            last = st.session_state["_last_hb_results"]
            _render_historical_results(
                last["trade_log"], last["equity_curve"], last["stats"],
                last["bankroll"], last["final_balance"],
                last["harvested_total"], last["lookback_days"], last["enable_harvest"],
            )
            _render_save_view_hb(last)
        return

    selected_specs = [s for s in active_specs if s["name"] in selected]
    if not selected_specs:
        st.error("Select at least one specialist.")
        return

    # --- Fetch Activity ---
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)
    progress = st.progress(0, text="Fetching specialist trade history...")
    all_buys = []  # (timestamp, specialist_dict, trade_dict)

    for i, spec in enumerate(selected_specs):
        progress.progress((i) / len(selected_specs), text=f"Fetching {spec['name']}...")
        activity = _fetch_specialist_activity(spec["wallet"], limit=max_trades_per_spec)

        for act in activity:
            ts = act.get("timestamp", 0)
            if isinstance(ts, str):
                try:
                    trade_dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
                except Exception:
                    continue
            else:
                trade_dt = datetime.utcfromtimestamp(ts / 1000 if ts > 1e12 else ts)

            if trade_dt < cutoff:
                continue

            if act.get("type") == "TRADE" and act.get("side") == "BUY":
                all_buys.append((trade_dt, spec, act))

    progress.progress(1.0, text="Processing trades...")

    if not all_buys:
        progress.empty()
        st.warning(f"No BUY trades found in the last {lookback_days} days for selected specialists.")
        return

    # Sort chronologically
    all_buys.sort(key=lambda x: x[0])

    # --- Simulate ---
    balance = bankroll
    baseline = bankroll
    harvested_total = 0.0
    equity_curve = [(all_buys[0][0], balance)]
    trade_log = []
    seen_slugs = set()  # slug+outcome collision tracking
    stats = {"copied": 0, "skipped_tag": 0, "skipped_price": 0, "skipped_buffer": 0, "skipped_collision": 0, "skipped_date": 0, "won": 0, "lost": 0, "pending": 0}

    for trade_dt, spec, act in all_buys:
        title = act.get("title", "Unknown")
        event_slug = act.get("eventSlug", act.get("slug", ""))
        outcome = act.get("outcome", "Yes")
        price = float(act.get("price", 0))
        asset = act.get("asset", "")

        if price <= 0:
            continue

        # --- Apply Strategy Filters ---

        # 1. Collision check
        collision_key = f"{event_slug}:{outcome}"
        if collision_key in seen_slugs:
            stats["skipped_collision"] += 1
            trade_log.append({"Date": trade_dt, "Specialist": spec["name"], "Market": title, "Outcome": outcome, "Price": price, "Action": "SKIP: Collision", "P&L": 0, "Balance": balance})
            continue

        # 2. Tag matching — use full event info with tag group expansion
        event_info = _lookup_event_info(event_slug) if event_slug else {"tags": [], "end_date": "", "markets": []}
        market_tags = event_info["tags"]
        expanded_spec_tags = _expand_tags(spec["tags"])
        matched_tag = None
        for tag in market_tags:
            if tag in expanded_spec_tags:
                matched_tag = tag
                break
        if market_tags and matched_tag is None:
            tag_names = [TAG_MAP.get(t, t) for t in market_tags[:3]]
            stats["skipped_tag"] += 1
            trade_log.append({"Date": trade_dt, "Specialist": spec["name"], "Market": title, "Outcome": outcome, "Price": price, "Action": f"SKIP: Tag mismatch ({', '.join(tag_names)})", "P&L": 0, "Balance": balance})
            continue
        if not market_tags:
            matched_tag = spec["tags"][0] if spec["tags"] else "1"

        # 3. Value cap
        max_price = FinanceController.get_max_price_for_tag(matched_tag)
        if price > max_price:
            stats["skipped_price"] += 1
            trade_log.append({"Date": trade_dt, "Specialist": spec["name"], "Market": title, "Outcome": outcome, "Price": price, "Action": f"SKIP: Price ${price:.2f} > cap ${max_price:.2f}", "P&L": 0, "Balance": balance})
            continue

        # 4. Date filter — use end date from Gamma API
        end_date_str = event_info.get("end_date", "")
        if end_date_str:
            try:
                end_dt = datetime.strptime(end_date_str, "%Y-%m-%d")
                days_out = (end_dt - trade_dt).days
                is_sports = any(t in SPORTS_TAGS for t in market_tags)
                max_days = max_days_sports if is_sports else max_days_other
                if days_out > max_days:
                    stats["skipped_date"] += 1
                    cat = "Sports" if is_sports else "Other"
                    trade_log.append({"Date": trade_dt, "Specialist": spec["name"], "Market": title, "Outcome": outcome, "Price": price, "Action": f"SKIP: {days_out}d out > {max_days}d ({cat})", "P&L": 0, "Balance": balance})
                    continue
            except ValueError:
                pass

        # 5. Buffer check
        if balance < min_buffer:
            stats["skipped_buffer"] += 1
            trade_log.append({"Date": trade_dt, "Specialist": spec["name"], "Market": title, "Outcome": outcome, "Price": price, "Action": "SKIP: Low balance", "P&L": 0, "Balance": balance})
            continue

        # 6. Size the bet
        tier = spec.get("tier", "SHARP")
        win_rate = 50.0  # Use neutral for historical (no prior bot data)
        bet_size = FinanceController.calculate_bet_size(balance, tier, win_rate)
        available = balance - min_buffer
        if bet_size > available:
            bet_size = available
        if bet_size <= 0:
            stats["skipped_buffer"] += 1
            continue

        # Fee
        fee = bet_size * FinanceController.estimate_taker_fee(price, matched_tag)

        # Determine outcome from Gamma API market resolution data
        # Check if the market is closed and who won via outcomePrices
        trade_result = _resolve_trade(event_info, title, outcome, trade_dt)

        seen_slugs.add(collision_key)
        stats["copied"] += 1

        if trade_result == "WON":
            payout = (bet_size / price) - fee
            pnl = payout - bet_size
            balance += pnl
            stats["won"] += 1
            action = "WON"
        elif trade_result == "LOST":
            pnl = -(bet_size + fee)
            balance += pnl
            stats["lost"] += 1
            action = "LOST"
        else:
            pnl = 0
            stats["pending"] += 1
            action = "PENDING"

        balance = max(0.0, balance)

        # Harvest
        if enable_harvest:
            result = FinanceController.check_harvest(balance, baseline)
            if result.triggered:
                harvested_total += result.transfer_amount
                balance = result.new_balance
                baseline = result.new_baseline

        equity_curve.append((trade_dt, balance + harvested_total))
        trade_log.append({
            "Date": trade_dt, "Specialist": spec["name"], "Market": title,
            "Outcome": outcome, "Price": price,
            "Action": f"COPIED → {action}", "Bet": bet_size,
            "P&L": pnl, "Balance": balance,
        })

    progress.empty()

    # Cache results for re-rendering and saving
    hb_result_data = {
        "trade_log": trade_log, "equity_curve": equity_curve, "stats": stats,
        "bankroll": bankroll, "final_balance": balance,
        "harvested_total": harvested_total, "lookback_days": lookback_days,
        "enable_harvest": enable_harvest, "params": hb_params,
    }
    st.session_state["_last_hb_results"] = hb_result_data

    # --- Render Results ---
    _render_historical_results(
        trade_log, equity_curve, stats, bankroll, balance,
        harvested_total, lookback_days, enable_harvest,
    )
    _render_save_view_hb(hb_result_data)


def _render_historical_results(trade_log, equity_curve, stats, bankroll, final_balance,
                               harvested_total, lookback_days, enable_harvest):
    """Render the historical backtest results."""
    total_value = final_balance + harvested_total
    roi = ((total_value - bankroll) / bankroll) * 100
    total_resolved = stats["won"] + stats["lost"]
    win_rate = (stats["won"] / total_resolved * 100) if total_resolved > 0 else 0

    # --- Headline Metrics ---
    st.header("Results")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Final Portfolio Value", f"${total_value:.2f}", f"{roi:+.1f}% ROI")
    col2.metric("Remaining Balance", f"${final_balance:.2f}")
    col3.metric("Trades Copied", stats["copied"])
    col4.metric("Win Rate", f"{win_rate:.0f}%" if total_resolved > 0 else "N/A")

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Won", stats["won"])
    col6.metric("Lost", stats["lost"])
    col7.metric("Pending", stats["pending"])
    if enable_harvest:
        col8.metric("Harvested", f"${harvested_total:.2f}")
    else:
        total_skipped = stats["skipped_tag"] + stats["skipped_price"] + stats["skipped_buffer"] + stats["skipped_collision"] + stats["skipped_date"]
        col8.metric("Total Skipped", total_skipped)

    st.markdown("---")

    # --- Equity Curve ---
    st.subheader("Portfolio Equity Curve")
    if len(equity_curve) > 1:
        eq_df = pd.DataFrame(equity_curve, columns=["Date", "Portfolio Value ($)"])
        eq_df = eq_df.set_index("Date")
        st.line_chart(eq_df)
    else:
        st.info("Not enough data points for an equity curve.")

    st.markdown("---")

    # --- Filter Breakdown ---
    st.subheader("Trade Filter Breakdown")
    filter_data = {
        "Filter": ["Copied", "Tag Mismatch", "Price > Value Cap", "Date Too Far Out", "Collision (Duplicate)", "Low Balance"],
        "Count": [stats["copied"], stats["skipped_tag"], stats["skipped_price"], stats["skipped_date"], stats["skipped_collision"], stats["skipped_buffer"]],
    }
    filter_df = pd.DataFrame(filter_data)
    col_chart, col_table = st.columns([2, 1])
    with col_chart:
        st.bar_chart(filter_df.set_index("Filter"))
    with col_table:
        st.table(filter_df)

    st.markdown("---")

    # --- Per-Specialist Breakdown ---
    st.subheader("Per-Specialist Performance")
    if trade_log:
        log_df = pd.DataFrame(trade_log)
        copied = log_df[log_df["Action"].str.startswith("COPIED")]
        if not copied.empty:
            spec_stats = []
            for name, group in copied.groupby("Specialist"):
                wins = (group["Action"] == "COPIED → WON").sum()
                losses = (group["Action"] == "COPIED → LOST").sum()
                pending = (group["Action"] == "COPIED → PENDING").sum()
                total_pnl = group["P&L"].sum()
                resolved = wins + losses
                wr = (wins / resolved * 100) if resolved > 0 else 0
                spec_stats.append({
                    "Specialist": name, "Copied": len(group),
                    "Won": wins, "Lost": losses, "Pending": pending,
                    "Win Rate": f"{wr:.0f}%", "P&L": f"${total_pnl:+.2f}",
                })
            st.table(pd.DataFrame(spec_stats))
        else:
            st.info("No trades were copied.")

    st.markdown("---")

    # --- Full Trade Log ---
    st.subheader("Full Trade Log")
    if trade_log:
        log_df = pd.DataFrame(trade_log)
        log_df["Date"] = pd.to_datetime(log_df["Date"]).dt.strftime("%Y-%m-%d %H:%M")
        log_df["Price"] = log_df["Price"].apply(lambda x: f"${x:.3f}")
        if "Bet" in log_df.columns:
            log_df["Bet"] = log_df["Bet"].apply(lambda x: f"${x:.2f}" if pd.notna(x) and x > 0 else "—")
        log_df["P&L"] = log_df["P&L"].apply(lambda x: f"${x:+.2f}" if x != 0 else "—")
        log_df["Balance"] = log_df["Balance"].apply(lambda x: f"${x:.2f}")

        # Color-code actions
        st.dataframe(log_df, use_container_width=True, hide_index=True, height=500)
    else:
        st.info("No trades to display.")


def _render_save_view_hb(result_data):
    """Save current historical backtest results as a named view."""
    st.markdown("---")
    st.subheader("Save This View")
    col_name, col_btn = st.columns([3, 1])
    with col_name:
        view_name = st.text_input("View Name", value=f"View {len(st.session_state.saved_hb_views) + 1}", key="hb_view_name")
    with col_btn:
        st.write("")
        if st.button("Save View", key="hb_save_btn"):
            s = result_data["stats"]
            p = result_data.get("params", {})
            total_resolved = s["won"] + s["lost"]
            win_rate = (s["won"] / total_resolved * 100) if total_resolved > 0 else 0
            total_value = result_data["final_balance"] + result_data["harvested_total"]
            roi = ((total_value - result_data["bankroll"]) / result_data["bankroll"]) * 100
            view = {
                "name": view_name,
                "params": p,
                "metrics": {
                    "final_value": total_value,
                    "final_balance": result_data["final_balance"],
                    "roi": roi,
                    "copied": s["copied"],
                    "won": s["won"],
                    "lost": s["lost"],
                    "pending": s["pending"],
                    "win_rate": win_rate,
                    "skipped_tag": s["skipped_tag"],
                    "skipped_price": s["skipped_price"],
                    "skipped_date": s["skipped_date"],
                    "skipped_collision": s["skipped_collision"],
                    "harvested": result_data["harvested_total"],
                },
            }
            st.session_state.saved_hb_views.append(view)
            st.success(f"Saved **{view_name}**")
            st.rerun()


def _render_saved_hb_comparison():
    """Show saved historical backtest views in a comparison table."""
    views = st.session_state.saved_hb_views
    if not views:
        return

    st.markdown("---")
    st.header("Saved Views Comparison")

    rows = []
    for v in views:
        m = v["metrics"]
        p = v["params"]
        rows.append({
            "View": v["name"],
            "Bankroll": f"${p.get('bankroll', 0):.0f}",
            "Lookback": f"{p.get('lookback_days', 0)}d",
            "Sports Max": f"{p.get('max_days_sports', 0)}d",
            "Other Max": f"{p.get('max_days_other', 0)}d",
            "Specialists": len(p.get("selected", [])),
            "Final Value": f"${m['final_value']:.2f}",
            "ROI": f"{m['roi']:+.1f}%",
            "Copied": m["copied"],
            "Won": m["won"],
            "Lost": m["lost"],
            "Pending": m["pending"],
            "Win Rate": f"{m['win_rate']:.0f}%",
            "Tag Skip": m["skipped_tag"],
            "Price Skip": m["skipped_price"],
            "Date Skip": m["skipped_date"],
            "Harvested": f"${m['harvested']:.2f}",
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.caption("Remove saved views:")
    cols = st.columns(min(len(views), 6))
    for i, v in enumerate(views):
        with cols[i % len(cols)]:
            if st.button(f"Delete: {v['name']}", key=f"hb_del_{i}"):
                st.session_state.saved_hb_views.pop(i)
                st.rerun()


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
            lines = f.readlines()
        log_content = "".join(reversed(lines))
        st.text_area("Live bot output", log_content, height=600)
    else:
        st.info("Log file does not exist yet. Run the bot to generate logs.")

if __name__ == "__main__":
    main()
