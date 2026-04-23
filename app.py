import streamlit as st
import pandas as pd
import numpy as np
import os
import json
import time
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
    """Initialize session state for saved backtest views and MC sidebar defaults."""
    if "saved_mc_views" not in st.session_state:
        st.session_state.saved_mc_views = []
    if "saved_hb_views" not in st.session_state:
        st.session_state.saved_hb_views = []
    # MC sidebar defaults (used for pre-population when loading a saved view)
    mc_defaults = {
        "mc_bankroll": 50.0, "mc_days": 90, "mc_num_simulations": 500,
        "mc_num_sharp": 7, "mc_num_whale": 2,
        "mc_sharp_wr": 58.0, "mc_whale_wr": 48.0,
        "mc_trades_per_day": 8, "mc_avg_entry_price": 0.45,
        "mc_slippage_pct": 1.0, "mc_avg_fee_rate": 0.75,
        "mc_enable_harvest": True, "mc_min_buffer": 5.0, "mc_max_slippage": 2.5,
    }
    for k, v in mc_defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _inject_css():
    dark = st.session_state.get("dark_mode", True)

    # ── Palette ──────────────────────────────────────────────────
    if dark:
        bg          = "#0a0d12"
        bg2         = "#111720"
        bg3         = "#0d1219"
        border      = "#1e2d42"
        border2     = "#1a2236"
        text        = "#dde3ee"
        text2       = "#c8d6ef"
        text3       = "#9aabbf"
        muted       = "#5c7a9a"
        sidebar_bg  = "#080b10"
        primary     = "#00e5a0"
        primary_btn = "linear-gradient(135deg,#00c48a 0%,#00a0f0 100%)"
        btn_text    = "#000"
    else:
        bg          = "#f4f6f9"
        bg2         = "#ffffff"
        bg3         = "#f0f2f5"
        border      = "#d0dae8"
        border2     = "#e2e8f0"
        text        = "#1a202c"
        text2       = "#2d3748"
        text3       = "#4a5568"
        muted       = "#718096"
        sidebar_bg  = "#edf0f5"
        primary     = "#0096c7"
        primary_btn = "linear-gradient(135deg,#0096c7 0%,#7c3aed 100%)"
        btn_text    = "#fff"

    st.markdown(f"""
<style>
/* ── Global ──────────────────────────────────────────────────── */
html, body,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {{
    background-color: {bg} !important;
    color: {text} !important;
}}
/* Remove the fixed Streamlit header bar that overlaps content */
[data-testid="stHeader"] {{
    background: {bg} !important;
    border-bottom: 1px solid {border2} !important;
}}
/* Prevent content from being hidden under the header */
.main .block-container {{
    padding-top: 2.5rem !important;
    max-width: 1400px !important;
}}

/* ── Typography ──────────────────────────────────────────────── */
h1 {{
    padding-bottom: 0.5rem;
    border-bottom: 1px solid {border2};
    letter-spacing: -0.02em;
    font-size: 1.8rem !important;
    color: {text} !important;
}}
h2 {{ letter-spacing: -0.01em; color: {text2} !important; }}
h3 {{ color: {text3} !important; font-size: 0.9rem !important;
      text-transform: uppercase; letter-spacing: 0.07em; }}
p, li, label {{ color: {text} !important; }}

/* ── Sidebar ─────────────────────────────────────────────────── */
[data-testid="stSidebar"] {{
    background: {sidebar_bg} !important;
    border-right: 1px solid {border2} !important;
}}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] span {{
    color: {text} !important;
}}

/* ── Metric cards ────────────────────────────────────────────── */
[data-testid="stMetric"] {{
    background: {bg2} !important;
    border: 1px solid {border} !important;
    border-radius: 8px !important;
    padding: 1rem 1.2rem !important;
    transition: border-color 0.2s;
}}
[data-testid="stMetric"]:hover {{ border-color: {primary} !important; }}
[data-testid="stMetricValue"] {{
    font-size: 1.75rem !important;
    font-weight: 700 !important;
    color: {text} !important;
    font-family: 'SF Mono','Fira Code',monospace !important;
}}
[data-testid="stMetricLabel"] {{
    font-size: 0.7rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
    color: {muted} !important;
}}
[data-testid="stMetricDelta"] svg {{ display: none; }}

/* ── Primary button ──────────────────────────────────────────── */
.stButton > button[kind="primary"] {{
    background: {primary_btn} !important;
    border: none !important;
    color: {btn_text} !important;
    font-weight: 700 !important;
    letter-spacing: 0.04em !important;
    border-radius: 6px !important;
    padding: 0.5rem 1.4rem !important;
    transition: opacity 0.15s, transform 0.1s !important;
}}
.stButton > button[kind="primary"]:hover {{
    opacity: 0.88 !important;
    transform: translateY(-1px) !important;
}}

/* ── Secondary buttons ───────────────────────────────────────── */
.stButton > button[kind="secondary"],
.stButton > button {{
    background: {bg2} !important;
    border: 1px solid {border} !important;
    color: {text3} !important;
    border-radius: 6px !important;
    transition: border-color 0.15s, color 0.15s !important;
}}
.stButton > button:hover {{
    border-color: {primary} !important;
    color: {primary} !important;
}}

/* ── Dataframes ──────────────────────────────────────────────── */
[data-testid="stDataFrame"] {{
    border: 1px solid {border2} !important;
    border-radius: 8px !important;
    overflow: hidden !important;
}}

/* ── Expanders ───────────────────────────────────────────────── */
[data-testid="stExpander"] {{
    border: 1px solid {border2} !important;
    border-radius: 8px !important;
    background: {bg3} !important;
}}

/* ── Inputs ──────────────────────────────────────────────────── */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input {{
    background: {bg3} !important;
    border-color: {border} !important;
    color: {text} !important;
}}

/* ── Horizontal rule ─────────────────────────────────────────── */
hr {{ border-color: {border2} !important; }}

/* ── View cards (saved backtest views) ───────────────────────── */
.view-card {{
    background: {bg2};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 0.9rem 1.1rem;
    margin-bottom: 0.5rem;
    transition: border-color 0.2s;
}}
.view-card:hover {{ border-color: {primary}; }}
.view-card-title {{
    font-size: 0.85rem; font-weight: 600;
    color: {text}; margin-bottom: 0.4rem; letter-spacing: 0.02em;
}}
.view-card-meta {{
    font-size: 0.72rem; color: {muted};
    font-family: 'SF Mono', monospace;
}}
.view-card-metric {{
    font-size: 1.1rem; font-weight: 700;
    font-family: 'SF Mono', monospace;
}}
.pos     {{ color: #22c55e; }}
.neg     {{ color: #ef4444; }}
.neutral {{ color: #f59e0b; }}
</style>
""", unsafe_allow_html=True)


def main():
    st.set_page_config(
        page_title="Polymarket Copy-Bot",
        page_icon="📡",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _init_saved_views()
    _inject_css()
    db = TradingDB()

    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to", [
        "Dashboard",
        "Specialists",
        "Copy-Bot Backtest",
        "No-Bot Backtest",
        "Backtest Simulator",
        "Settings",
        "Strategy & SOP",
        "Architecture & Deployment",
        "Logs",
    ])

    st.sidebar.markdown("---")
    if "dark_mode" not in st.session_state:
        st.session_state["dark_mode"] = True
    dark_label = "🌙 Dark Mode" if st.session_state["dark_mode"] else "☀️ Light Mode"
    if st.sidebar.toggle(dark_label, value=st.session_state["dark_mode"], key="_dark_mode_toggle"):
        if not st.session_state["dark_mode"]:
            st.session_state["dark_mode"] = True
            st.rerun()
    else:
        if st.session_state["dark_mode"]:
            st.session_state["dark_mode"] = False
            st.rerun()

    if page == "Dashboard":
        render_dashboard(db)
    elif page == "Specialists":
        render_specialists(db)
    elif page == "Backtest Simulator":
        render_backtest(db)
    elif page == "Copy-Bot Backtest":
        render_historical_backtest(db)
    elif page == "No-Bot Backtest":
        render_no_bot(db)
    elif page == "Settings":
        render_settings(db)
    elif page == "Strategy & SOP":
        render_strategy()
    elif page == "Architecture & Deployment":
        render_architecture()
    else:
        render_logs()
        
def render_no_bot_positions_inline(db):
    """Live No-Bot positions section — rendered on the main Dashboard."""
    import sqlite3
    from pathlib import Path as _Path

    st.header("🚫 No-Bot Live Positions")
    trading_db = _Path(__file__).parent / "trading.db"
    conn = sqlite3.connect(trading_db)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS no_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT NOT NULL, event_id TEXT, question TEXT, category TEXT,
            entry_no_price REAL, bet_size_usd REAL, fee_paid_usd REAL,
            placed_at TEXT, resolved_at TEXT, resolved_yes INTEGER,
            pnl_usd REAL, status TEXT, mock INTEGER DEFAULT 1
        );
    """)
    rows = conn.execute(
        "SELECT category, question, entry_no_price, bet_size_usd, status, "
        "placed_at, resolved_at, pnl_usd, mock "
        "FROM no_positions ORDER BY placed_at DESC LIMIT 100"
    ).fetchall()
    conn.close()

    nb_cfg = db.get_all_config()
    nb_bankroll = float(nb_cfg.get("nb_bankroll", {}).get("value", 50.0))
    nb_live = nb_cfg.get("nb_live_mode", {}).get("value", "0") == "1"
    mode_label = "🟢 LIVE" if nb_live else "📝 PAPER"

    c1, c2, c3, c4 = st.columns(4)
    open_n = sum(1 for r in rows if r[4] == "open")
    total_pnl = sum((r[7] or 0) for r in rows if r[4] != "open")
    c1.metric("Mode", mode_label)
    c2.metric("Bankroll", f"${nb_bankroll:.2f}")
    c3.metric("Open positions", open_n)
    c4.metric("Closed P&L", f"${total_pnl:+,.2f}")

    if rows:
        df = pd.DataFrame(rows, columns=[
            "Category", "Question", "Entry No", "Bet $", "Status",
            "Placed", "Resolved", "PnL $", "Mock"])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.caption("No positions yet. Settings for this bot are on the **Settings → No-Bot** tab.")


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
        trades_df = pd.DataFrame(recent_trades[:20], columns=['Specialist', 'Market', 'Entry Price', 'Timestamp', 'Status', 'Slug', 'Outcome', 'Bet Size', 'End Date', 'Leader Price', 'Market Price'])
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

    # 3. No-Bot Live Positions
    render_no_bot_positions_inline(db)

    st.markdown("---")

    active_n = sum(1 for s in db.get_all_specialists() if s.get("is_active") and "MOCK" not in s["wallet"])
    st.info(f"**Specialists:** {active_n} active. Manage them in the **Specialists** tab.")

def render_specialists(db):
    st.title("👥 Specialist Roster & Health")
    st.caption("Toggle Alpha wallets to monitor and copy their trades on Polymarket. All specialists start inactive — flip them on explicitly before go-live.")

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
                tdf = pd.DataFrame(spec_trades, columns=['Market', 'Entry Price', 'Timestamp', 'Result', 'Slug', 'Outcome', 'Bet Size', 'End Date', 'Leader Price', 'Market Price'])
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
    st.title("🧪 Monte Carlo Simulator")
    st.markdown("Simulate strategy performance across hundreds of random scenarios using the bot's actual Kelly sizing, value caps, slippage, and harvest logic.")

    # --- Sidebar Controls (session-state keys allow pre-population from saved views) ---
    st.sidebar.markdown("---")
    st.sidebar.header("Simulation Parameters")

    bankroll        = st.sidebar.number_input("Starting Bankroll ($)", min_value=10.0, max_value=100000.0, step=10.0, key="mc_bankroll")
    days            = st.sidebar.slider("Simulation Days", min_value=7, max_value=365, key="mc_days")
    num_simulations = st.sidebar.slider("Monte Carlo Runs", min_value=50, max_value=2000, step=50, key="mc_num_simulations")

    st.sidebar.markdown("---")
    st.sidebar.subheader("Specialist Mix")
    num_sharp  = st.sidebar.number_input("SHARP Specialists", min_value=0, max_value=20, key="mc_num_sharp")
    num_whale  = st.sidebar.number_input("WHALE Specialists", min_value=0, max_value=10, key="mc_num_whale")
    sharp_wr   = st.sidebar.slider("SHARP Avg Win Rate (%)", min_value=40.0, max_value=80.0, step=1.0, key="mc_sharp_wr")
    whale_wr   = st.sidebar.slider("WHALE Avg Win Rate (%)", min_value=30.0, max_value=70.0, step=1.0, key="mc_whale_wr")

    st.sidebar.markdown("---")
    st.sidebar.subheader("Market Conditions")
    trades_per_day  = st.sidebar.slider("Avg Trades/Day (all specialists)", min_value=1, max_value=30, key="mc_trades_per_day")
    avg_entry_price = st.sidebar.slider("Avg Entry Price ($)", min_value=0.10, max_value=0.90, step=0.05, key="mc_avg_entry_price")
    slippage_pct    = st.sidebar.slider("Avg Slippage (%)", min_value=0.0, max_value=5.0, step=0.25, key="mc_slippage_pct")
    avg_fee_rate    = st.sidebar.slider("Avg Taker Fee (%)", min_value=0.0, max_value=2.0, step=0.05, key="mc_avg_fee_rate")

    st.sidebar.markdown("---")
    st.sidebar.subheader("Risk & Harvest")
    enable_harvest = st.sidebar.checkbox("Enable 2x Harvest Rule", key="mc_enable_harvest")
    min_buffer     = st.sidebar.number_input("Min Buffer ($)", min_value=1.0, max_value=50.0, step=1.0, key="mc_min_buffer")
    max_slippage   = st.sidebar.slider("Max Slippage Reject (%)", min_value=0.5, max_value=10.0, step=0.5, key="mc_max_slippage")

    mc_params = {
        "bankroll": bankroll, "days": days, "num_simulations": num_simulations,
        "num_sharp": num_sharp, "num_whale": num_whale,
        "sharp_wr": sharp_wr, "whale_wr": whale_wr,
        "trades_per_day": trades_per_day, "avg_entry_price": avg_entry_price,
        "slippage_pct": slippage_pct, "avg_fee_rate": avg_fee_rate,
        "enable_harvest": enable_harvest, "min_buffer": min_buffer,
        "max_slippage": max_slippage,
    }

    # Auto-run if a view was just loaded
    autorun = st.session_state.pop("_mc_autorun", False)
    if st.button("▶  Run Simulation", type="primary") or autorun:
        with st.spinner("Running simulations..."):
            results = _run_monte_carlo(**mc_params)
        st.session_state["_last_mc_results"] = results
        st.session_state["_last_mc_params"] = mc_params

    # Render last results if available
    results = st.session_state.get("_last_mc_results")
    params  = st.session_state.get("_last_mc_params")
    if results is not None and params is not None:
        _render_backtest_results(results, params["bankroll"], params["days"], params["enable_harvest"])
        _render_save_view_mc(results, params)

    # Always show saved views at bottom
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
    st.subheader("💾 Save This View")
    col_name, col_btn = st.columns([3, 1])
    with col_name:
        view_name = st.text_input("View Name", value=f"Sim {len(st.session_state.saved_mc_views) + 1} · ${params['bankroll']:.0f} · {params['days']}d", key="mc_view_name")
    with col_btn:
        st.write("")
        if st.button("Save View", key="mc_save_btn"):
            finals    = results["final_balances"]
            harvested = results["harvested"]
            trades    = results["trades"]
            wins      = results["wins"]
            losses    = results["losses"]
            max_dd    = results["max_drawdown"]
            bankroll  = params["bankroll"]
            median_final = float(np.median(finals))
            roi = ((median_final - bankroll) / bankroll) * 100
            avg_wr = float(np.mean(wins / np.maximum(wins + losses, 1)) * 100)
            view = {
                "id": f"mc_{int(time.time())}_{len(st.session_state.saved_mc_views)}",
                "name": view_name,
                "params": params.copy(),
                "results": results,   # full numpy results stored for reload
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
    """Show saved Monte Carlo views as interactive cards + comparison table."""
    views = st.session_state.saved_mc_views
    if not views:
        return

    st.markdown("---")
    st.subheader("📂 Saved Simulations")

    # Cards row
    cols = st.columns(min(len(views), 4))
    for i, v in enumerate(views):
        m = v["metrics"]
        p = v["params"]
        roi_cls = "pos" if m["roi"] >= 0 else "neg"
        with cols[i % min(len(views), 4)]:
            st.markdown(f"""
<div class="view-card">
  <div class="view-card-title">{v['name']}</div>
  <div class="view-card-meta">${p['bankroll']:.0f} · {p['days']}d · {p['num_simulations']} runs</div>
  <div class="view-card-meta">{p['num_sharp']}S / {p['num_whale']}W · {p['sharp_wr']:.0f}%/{p['whale_wr']:.0f}% WR</div>
  <div style="margin-top:0.5rem">
    <span class="view-card-metric {roi_cls}">{m['roi']:+.1f}% ROI</span>
    <span class="view-card-meta" style="margin-left:0.6rem">${m['median_final']:.0f} median</span>
  </div>
  <div class="view-card-meta" style="margin-top:0.2rem">
    P5 ${m['p5']:.0f} · P95 ${m['p95']:.0f} · DD {m['avg_max_dd']:.0f}%
  </div>
</div>
""", unsafe_allow_html=True)
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                if st.button("⬆ Load", key=f"mc_load_{v['id']}", help="Restore this simulation's results and parameters"):
                    # Restore display results
                    st.session_state["_last_mc_results"] = v["results"]
                    st.session_state["_last_mc_params"]  = v["params"]
                    # Pre-populate sidebar for the loaded params
                    p = v["params"]
                    st.session_state["mc_bankroll"]         = float(p["bankroll"])
                    st.session_state["mc_days"]             = int(p["days"])
                    st.session_state["mc_num_simulations"]  = int(p["num_simulations"])
                    st.session_state["mc_num_sharp"]        = int(p["num_sharp"])
                    st.session_state["mc_num_whale"]        = int(p["num_whale"])
                    st.session_state["mc_sharp_wr"]         = float(p["sharp_wr"])
                    st.session_state["mc_whale_wr"]         = float(p["whale_wr"])
                    st.session_state["mc_trades_per_day"]   = int(p["trades_per_day"])
                    st.session_state["mc_avg_entry_price"]  = float(p["avg_entry_price"])
                    st.session_state["mc_slippage_pct"]     = float(p["slippage_pct"])
                    st.session_state["mc_avg_fee_rate"]     = float(p["avg_fee_rate"])
                    st.session_state["mc_enable_harvest"]   = bool(p["enable_harvest"])
                    st.session_state["mc_min_buffer"]       = float(p["min_buffer"])
                    st.session_state["mc_max_slippage"]     = float(p["max_slippage"])
                    st.rerun()
            with btn_col2:
                if st.button("🗑 Delete", key=f"mc_del_{v['id']}"):
                    st.session_state.saved_mc_views = [sv for sv in st.session_state.saved_mc_views if sv["id"] != v["id"]]
                    st.rerun()

    # Comparison table
    if len(views) > 1:
        st.markdown("---")
        st.subheader("Side-by-Side Comparison")
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


def _fetch_specialist_activity(wallet: str, cutoff_dt: datetime = None, limit: int = 2000) -> list[dict]:
    """Fetch trade activity for a specialist from Polymarket Data API.

    Paginates until cutoff_dt is reached (date-based) or limit records fetched (safety cap).
    This ensures heavy traders (15+ trades/day) don't run out of records before the lookback window.
    """
    all_activity = []
    offset = 0
    batch = 100
    while len(all_activity) < limit:
        try:
            resp = requests.get(
                f"{DATA_API_URL}/activity",
                params={"user": wallet, "limit": batch, "offset": offset},
                timeout=10,
            )
            if resp.status_code != 200:
                break
            data = resp.json()
            if not data:
                break
            all_activity.extend(data)
            # If cutoff provided, check if oldest record in this page is already past cutoff
            if cutoff_dt and data:
                oldest = data[-1]
                ts = oldest.get("timestamp", 0)
                if isinstance(ts, str):
                    try:
                        oldest_dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
                    except Exception:
                        oldest_dt = None
                else:
                    oldest_dt = datetime.utcfromtimestamp(ts / 1000 if ts > 1e12 else ts)
                if oldest_dt and oldest_dt < cutoff_dt:
                    break  # We've gone past the lookback window — stop fetching
            if len(data) < batch:
                break  # API returned fewer than requested — no more pages
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


def _aggregate_fills(all_events: list, window_minutes: int = 10) -> list[dict]:
    """
    Aggregate rapid-fire fills into single position entries.

    When a specialist places a large order, Polymarket's CLOB splits it into many
    small fills (often 30-50 fills within minutes for a single position). This
    function groups fills by specialist+slug+outcome within a time window and
    produces one aggregated position entry with:
      - VWAP price (volume-weighted average)
      - Total USD size
      - Fill count
      - Timestamp of the first fill
    """
    if not all_events:
        return []

    window = timedelta(minutes=window_minutes)
    positions = []
    # Buffer: key = (spec_name, slug, outcome, side) -> list of (dt, price, size_usd)
    buffer = {}
    buffer_start = {}  # key -> first timestamp

    def flush_key(key):
        fills = buffer.pop(key, [])
        start_dt = buffer_start.pop(key, None)
        if not fills:
            return
        total_size = sum(f[2] for f in fills)
        vwap = sum(f[1] * f[2] for f in fills) / total_size if total_size > 0 else fills[0][1]
        spec_name, slug, outcome, side = key
        # Find the spec dict from the first fill
        spec_dict = fills[0][3] if len(fills[0]) > 3 else {}
        title = fills[0][4] if len(fills[0]) > 4 else "Unknown"
        positions.append({
            "dt": start_dt, "spec": spec_dict, "side": side,
            "title": title, "slug": slug, "outcome": outcome,
            "vwap": vwap, "total_size": total_size,
            "fill_count": len(fills),
        })

    for trade_dt, spec, act in all_events:
        slug = act.get("eventSlug", act.get("slug", ""))
        outcome = act.get("outcome", "Yes")
        side = act.get("side", "BUY")
        price = float(act.get("price", 0))
        # Size in USD: quantity * price. Activity API gives "size" as share count.
        share_count = float(act.get("size", 0))
        size_usd = share_count * price if share_count > 0 else price

        key = (spec["name"], slug, outcome, side)

        if key in buffer:
            # Check if within the time window from the first fill
            if trade_dt - buffer_start[key] <= window:
                buffer[key].append((trade_dt, price, size_usd, spec, act.get("title", "Unknown")))
                continue
            else:
                # Window expired — flush and start new
                flush_key(key)

        # Start new buffer entry
        buffer[key] = [(trade_dt, price, size_usd, spec, act.get("title", "Unknown"))]
        buffer_start[key] = trade_dt

    # Flush remaining
    for key in list(buffer.keys()):
        flush_key(key)

    # Sort by timestamp
    positions.sort(key=lambda x: x["dt"])
    return positions


def render_historical_backtest(db):
    st.title("📜 Historical Backtest")
    st.markdown("Replay your specialists' **real Polymarket trades** through the bot's strategy rules to see what it would have copied and the resulting P&L.")

    # --- Controls ---
    st.sidebar.markdown("---")
    st.sidebar.header("Historical Backtest")
    bankroll = st.sidebar.number_input("Starting Bankroll ($)", min_value=10.0, max_value=100000.0, value=50.0, step=10.0, key="hb_bankroll")
    lookback_days = st.sidebar.slider("Lookback Window (days)", 7, 180, 60, key="hb_lookback")
    enable_harvest = st.sidebar.checkbox("Enable 2x Harvest Rule", value=True, key="hb_harvest")
    min_buffer = st.sidebar.number_input("Min Buffer ($)", min_value=1.0, max_value=50.0, value=5.0, step=1.0, key="hb_buffer")

    st.sidebar.markdown("---")
    st.sidebar.subheader("Strategy Filters")
    enable_tag_filter = st.sidebar.checkbox("Enable Category Filtering",
        value=False, key="hb_tag_filter",
        help="OFF = copy everything the specialist trades (recommended). ON = only copy trades matching their assigned tags.")
    max_price_cap = st.sidebar.slider("Max Entry Price (Value Cap)", 0.50, 0.95, 0.82, step=0.01, key="hb_price_cap",
        help="Skip trades priced above this. Pro services use 0.80-0.85.")
    enable_fill_aggregation = st.sidebar.checkbox("Aggregate Fills (Debounce)",
        value=True, key="hb_aggregate",
        help="Group rapid-fire fills for the same market into one position entry with VWAP price.")
    fill_window_min = st.sidebar.slider("Fill Aggregation Window (minutes)", 1, 30, 10, key="hb_fill_window",
        help="Time window to group fills from the same specialist on the same market.")
    enable_exit_copy = st.sidebar.checkbox("Copy Exits (Sell Signals)",
        value=True, key="hb_exit_copy",
        help="When a specialist sells shares, close the position proportionally.")

    st.sidebar.markdown("---")
    st.sidebar.subheader("Date Filter")
    max_days_sports = st.sidebar.slider("Max Days Out (Sports)", 7, 180, 60, key="hb_max_days_sports")
    max_days_other = st.sidebar.slider("Max Days Out (Non-Sports)", 7, 180, 90, key="hb_max_days_other")

    specialists = db.get_all_specialists()
    active_specs = [s for s in specialists if s.get("is_active", True) and "MOCK" not in s["wallet"]]

    if not active_specs:
        st.warning("No active specialists with real wallets found.")
        return

    spec_names = [s["name"] for s in active_specs]
    selected = st.sidebar.multiselect("Specialists to Include", spec_names, default=spec_names, key="hb_specs")

    hb_params = {
        "bankroll": bankroll,
        "lookback_days": lookback_days, "enable_harvest": enable_harvest,
        "min_buffer": min_buffer, "max_days_sports": max_days_sports,
        "max_days_other": max_days_other, "selected": selected,
        "enable_tag_filter": enable_tag_filter, "max_price_cap": max_price_cap,
        "enable_fill_aggregation": enable_fill_aggregation,
        "fill_window_min": fill_window_min, "enable_exit_copy": enable_exit_copy,
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
                last.get("pending_exposure", 0.0),
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
    all_events = []  # (timestamp, specialist_dict, trade_dict)

    for i, spec in enumerate(selected_specs):
        progress.progress((i) / len(selected_specs), text=f"Fetching {spec['name']}...")
        activity = _fetch_specialist_activity(spec["wallet"], cutoff_dt=cutoff)

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

            side = act.get("side", "")
            if act.get("type") == "TRADE" and side in ("BUY", "SELL"):
                all_events.append((trade_dt, spec, act))

    progress.progress(0.8, text="Aggregating fills...")

    if not all_events:
        progress.empty()
        st.warning(f"No trades found in the last {lookback_days} days for selected specialists.")
        return

    # Sort chronologically
    all_events.sort(key=lambda x: x[0])

    # --- Fill Aggregation ---
    # Group rapid-fire fills for the same specialist+slug+outcome into single positions
    if enable_fill_aggregation:
        aggregated = _aggregate_fills(all_events, fill_window_min)
    else:
        # No aggregation — each fill is its own position entry
        aggregated = []
        for trade_dt, spec, act in all_events:
            size_usd = float(act.get("size", 0)) * float(act.get("price", 0))
            aggregated.append({
                "dt": trade_dt, "spec": spec, "side": act.get("side"),
                "title": act.get("title", "Unknown"),
                "slug": act.get("eventSlug", act.get("slug", "")),
                "outcome": act.get("outcome", "Yes"),
                "vwap": float(act.get("price", 0)),
                "total_size": size_usd,
                "fill_count": 1,
            })

    progress.progress(0.9, text="Running simulation...")

    # Compute per-specialist average position size for conviction sizing
    spec_sizes = {}  # spec_name -> list of position sizes
    for pos in aggregated:
        if pos["side"] == "BUY" and pos["total_size"] > 0:
            spec_sizes.setdefault(pos["spec"]["name"], []).append(pos["total_size"])
    spec_avg_size = {name: sum(sizes) / len(sizes) for name, sizes in spec_sizes.items() if sizes}

    # --- Simulate ---
    balance = bankroll
    baseline = bankroll
    harvested_total = 0.0
    equity_curve = [(aggregated[0]["dt"], balance)]
    trade_log = []
    open_positions = {}  # collision_key -> {"bet_size": x, "price": y, "tag": z}
    pending_exposure = 0.0
    stats = {"copied": 0, "skipped_tag": 0, "skipped_price": 0, "skipped_buffer": 0,
             "skipped_collision": 0, "skipped_date": 0, "skipped_conviction": 0,
             "sold": 0, "won": 0, "lost": 0, "pending": 0}

    for pos in aggregated:
        trade_dt = pos["dt"]
        spec = pos["spec"]
        title = pos["title"]
        event_slug = pos["slug"]
        outcome = pos["outcome"]
        price = pos["vwap"]
        side = pos["side"]
        fill_count = pos["fill_count"]
        spec_position_size = pos["total_size"]

        if price <= 0:
            continue

        collision_key = f"{event_slug}:{outcome}"

        # --- SELL handling (exit copying) ---
        if side == "SELL":
            if not enable_exit_copy:
                continue
            if collision_key in open_positions:
                held = open_positions[collision_key]
                # Specialist is selling — close our position proportionally
                # Return the bet_size (shares convert back to cash at current price)
                sell_value = held["bet_size"] * (price / held["price"])  # Approximate
                balance += sell_value
                pending_exposure -= held["bet_size"]
                pending_exposure = max(0.0, pending_exposure)
                pnl = sell_value - held["bet_size"]
                stats["sold"] += 1
                if pnl >= 0:
                    stats["won"] += 1
                else:
                    stats["lost"] += 1
                trade_log.append({
                    "Date": trade_dt, "Specialist": spec["name"], "Market": title,
                    "Outcome": outcome, "Price": price,
                    "Action": f"EXIT → {'PROFIT' if pnl >= 0 else 'LOSS'}",
                    "Bet": held["bet_size"], "P&L": pnl, "Balance": balance,
                })
                del open_positions[collision_key]
                equity_curve.append((trade_dt, balance + pending_exposure + harvested_total))
            continue

        # --- BUY handling ---

        # 1. Collision check
        if collision_key in open_positions:
            stats["skipped_collision"] += 1
            trade_log.append({"Date": trade_dt, "Specialist": spec["name"], "Market": title,
                "Outcome": outcome, "Price": price,
                "Action": f"SKIP: Collision ({fill_count} fills)", "P&L": 0, "Balance": balance})
            continue

        # 2. Tag matching — optional
        event_info = _lookup_event_info(event_slug) if event_slug else {"tags": [], "end_date": "", "markets": []}
        market_tags = event_info["tags"]
        matched_tag = None

        if enable_tag_filter:
            expanded_spec_tags = _expand_tags(spec["tags"])
            for tag in market_tags:
                if tag in expanded_spec_tags:
                    matched_tag = tag
                    break
            if market_tags and matched_tag is None:
                tag_names = [TAG_MAP.get(t, t) for t in market_tags[:3]]
                stats["skipped_tag"] += 1
                trade_log.append({"Date": trade_dt, "Specialist": spec["name"], "Market": title,
                    "Outcome": outcome, "Price": price,
                    "Action": f"SKIP: Tag mismatch ({', '.join(tag_names)})", "P&L": 0, "Balance": balance})
                continue

        # Pick a tag for fee estimation (first market tag, or specialist's primary)
        if matched_tag is None:
            matched_tag = market_tags[0] if market_tags else (spec["tags"][0] if spec["tags"] else "1")

        # 3. Value cap (using sidebar-configurable cap)
        if price > max_price_cap:
            stats["skipped_price"] += 1
            trade_log.append({"Date": trade_dt, "Specialist": spec["name"], "Market": title,
                "Outcome": outcome, "Price": price,
                "Action": f"SKIP: Price ${price:.2f} > cap ${max_price_cap:.2f}",
                "P&L": 0, "Balance": balance})
            continue

        # 4. Date filter
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
                    trade_log.append({"Date": trade_dt, "Specialist": spec["name"], "Market": title,
                        "Outcome": outcome, "Price": price,
                        "Action": f"SKIP: {days_out}d out > {max_days}d ({cat})",
                        "P&L": 0, "Balance": balance})
                    continue
            except ValueError:
                pass

        # 5. Buffer check
        if balance < min_buffer:
            stats["skipped_buffer"] += 1
            trade_log.append({"Date": trade_dt, "Specialist": spec["name"], "Market": title,
                "Outcome": outcome, "Price": price,
                "Action": "SKIP: Low balance", "P&L": 0, "Balance": balance})
            continue

        # 6. Size the bet — conviction-aware
        tier = spec.get("tier", "SHARP")
        win_rate = 50.0
        avg_size = spec_avg_size.get(spec["name"], 0)
        bet_size = FinanceController.calculate_conviction_size(
            balance, tier, win_rate, spec_position_size, avg_size)

        if bet_size <= 0:
            stats["skipped_conviction"] += 1
            trade_log.append({"Date": trade_dt, "Specialist": spec["name"], "Market": title,
                "Outcome": outcome, "Price": price,
                "Action": "SKIP: Low conviction (small bet)", "P&L": 0, "Balance": balance})
            continue

        available = balance - min_buffer
        if bet_size > available:
            bet_size = available
        if bet_size <= 0:
            stats["skipped_buffer"] += 1
            continue

        # Fee
        fee = bet_size * FinanceController.estimate_taker_fee(price, matched_tag)

        # Determine outcome from Gamma API resolution data
        trade_result = _resolve_trade(event_info, title, outcome, trade_dt)

        # Track the position
        open_positions[collision_key] = {"bet_size": bet_size, "price": price, "tag": matched_tag}
        stats["copied"] += 1

        # Simulate real wallet: USDC leaves on buy
        balance -= (bet_size + fee)

        if trade_result == "WON":
            payout = bet_size / price
            balance += payout
            pnl = payout - bet_size - fee
            stats["won"] += 1
            action = "WON"
            if collision_key in open_positions:
                del open_positions[collision_key]
        elif trade_result == "LOST":
            pnl = -(bet_size + fee)
            stats["lost"] += 1
            action = "LOST"
            if collision_key in open_positions:
                del open_positions[collision_key]
        else:
            pending_exposure += bet_size
            pnl = -fee
            stats["pending"] += 1
            action = "PENDING"

        balance = max(0.0, balance)

        if enable_harvest:
            result = FinanceController.check_harvest(balance, baseline)
            if result.triggered:
                harvested_total += result.transfer_amount
                balance = result.new_balance
                baseline = result.new_baseline

        conviction_label = ""
        if avg_size > 0 and spec_position_size > 0:
            ratio = spec_position_size / avg_size
            if ratio >= 2.0:
                conviction_label = " [HIGH]"
            elif ratio < 0.5:
                conviction_label = " [low]"

        equity_curve.append((trade_dt, balance + pending_exposure + harvested_total))
        trade_log.append({
            "Date": trade_dt, "Specialist": spec["name"], "Market": title,
            "Outcome": outcome, "Price": price,
            "Action": f"COPIED → {action}{conviction_label} ({fill_count} fills)",
            "Bet": bet_size, "P&L": pnl, "Balance": balance,
        })

    progress.empty()

    # Cache results for re-rendering and saving
    hb_result_data = {
        "trade_log": trade_log, "equity_curve": equity_curve, "stats": stats,
        "bankroll": bankroll, "final_balance": balance,
        "pending_exposure": pending_exposure,
        "harvested_total": harvested_total, "lookback_days": lookback_days,
        "enable_harvest": enable_harvest, "params": hb_params,
    }
    st.session_state["_last_hb_results"] = hb_result_data

    # --- Render Results ---
    _render_historical_results(
        trade_log, equity_curve, stats, bankroll, balance,
        harvested_total, lookback_days, enable_harvest,
        pending_exposure,
    )
    _render_save_view_hb(hb_result_data)


def _render_historical_results(trade_log, equity_curve, stats, bankroll, final_balance,
                               harvested_total, lookback_days, enable_harvest,
                               pending_exposure=0.0):
    """Render the historical backtest results."""
    # Total value = cash + shares still open + harvested profits
    total_value = final_balance + pending_exposure + harvested_total
    roi = ((total_value - bankroll) / bankroll) * 100
    total_resolved = stats["won"] + stats["lost"]
    win_rate = (stats["won"] / total_resolved * 100) if total_resolved > 0 else 0

    # --- Headline Metrics ---
    st.header("Results")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Final Portfolio Value", f"${total_value:.2f}", f"{roi:+.1f}% ROI")
    col2.metric("Cash Balance", f"${final_balance:.2f}")
    col3.metric("Trades Copied", stats["copied"])
    col4.metric("Win Rate", f"{win_rate:.0f}%" if total_resolved > 0 else "N/A")

    col5, col6, col7, col8 = st.columns(4)
    sold = stats.get("sold", 0)
    col5.metric("Won" + (f" ({sold} exits)" if sold else ""), stats["won"])
    col6.metric("Lost", stats["lost"])
    col7.metric(f"Pending (${pending_exposure:.2f} in shares)", stats["pending"])
    if enable_harvest:
        col8.metric("Harvested", f"${harvested_total:.2f}")
    else:
        total_skipped = stats.get("skipped_tag", 0) + stats["skipped_price"] + stats["skipped_buffer"] + stats["skipped_collision"] + stats["skipped_date"] + stats.get("skipped_conviction", 0)
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
    filters = ["Copied", "Collision", "Price > Cap", "Tag Mismatch", "Date Too Far", "Low Conviction", "Low Balance"]
    counts = [stats["copied"], stats["skipped_collision"], stats["skipped_price"],
              stats.get("skipped_tag", 0), stats["skipped_date"],
              stats.get("skipped_conviction", 0), stats["skipped_buffer"]]
    # Only show non-zero filters
    filter_data = {"Filter": [], "Count": []}
    for f, c in zip(filters, counts):
        if c > 0:
            filter_data["Filter"].append(f)
            filter_data["Count"].append(c)
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
        # Match both COPIED and EXIT actions for per-specialist stats
        acted = log_df[log_df["Action"].str.startswith(("COPIED", "EXIT"))]
        if not acted.empty:
            spec_stats = []
            for name, group in acted.groupby("Specialist"):
                wins = group["Action"].str.contains("WON|PROFIT").sum()
                losses = group["Action"].str.contains("LOST|LOSS").sum()
                pending = group["Action"].str.contains("PENDING").sum()
                total_pnl = group["P&L"].sum()
                resolved = wins + losses
                wr = (wins / resolved * 100) if resolved > 0 else 0
                # EV analysis: at avg entry price P, need WR > P to profit
                # EV = WR*(1-P)/P - (1-WR)  →  positive means +edge
                avg_price = group["Price"].mean() if "Price" in group.columns else 0
                if resolved > 0 and avg_price > 0:
                    wr_frac = wr / 100
                    ev = wr_frac * (1 - avg_price) / avg_price - (1 - wr_frac)
                    breakeven_wr = avg_price * 100  # Need WR% > avg_price% to profit
                    ev_str = f"{ev:+.3f}"
                    verdict = "✅" if ev > 0 else ("⚠️" if ev > -0.05 else "❌")
                else:
                    ev_str = "N/A"
                    breakeven_wr = 0
                    verdict = "⏳" if pending > 0 else "N/A"
                spec_stats.append({
                    "Specialist": name,
                    "Copied": len(group),
                    "Won": wins,
                    "Lost": losses,
                    "Pending": pending,
                    "Win Rate": f"{wr:.0f}%" if resolved > 0 else "—",
                    "Breakeven": f"{breakeven_wr:.0f}%" if breakeven_wr else "—",
                    "Edge": f"{verdict} {ev_str}",
                    "P&L": f"${total_pnl:+.2f}",
                })
            st.table(pd.DataFrame(spec_stats))
            st.caption(
                "**Breakeven**: minimum win rate needed at avg entry price to be profitable. "
                "**Edge**: positive = +EV, negative = you need better accuracy than these picks provide. "
                "⚠️ within 5% of breakeven. ⏳ all trades still pending."
            )
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
    st.subheader("💾 Save This View")

    p = result_data.get("params", {})
    s = result_data["stats"]
    n_specs = len(p.get("selected", []))
    auto_name = (
        f"${p.get('bankroll', 0):.0f} · {p.get('lookback_days', 0)}d · "
        f"{p.get('max_price_cap', 0.82):.0%} cap · {n_specs} specialists"
    )

    save_count = len(st.session_state.saved_hb_views)
    col_name, col_btn = st.columns([3, 1])
    with col_name:
        view_name = st.text_input("View Name", value=auto_name, key=f"hb_view_name_{save_count}")
    with col_btn:
        st.write("")
        if st.button("Save View", key=f"hb_save_btn_{save_count}"):
            total_resolved = s["won"] + s["lost"]
            win_rate = (s["won"] / total_resolved * 100) if total_resolved > 0 else 0
            total_value = result_data["final_balance"] + result_data.get("pending_exposure", 0.0) + result_data["harvested_total"]
            roi = ((total_value - result_data["bankroll"]) / result_data["bankroll"]) * 100
            view = {
                "id": f"hb_{save_count}_{int(time.time())}",
                "name": view_name,
                "params": p,
                "result_data": result_data,   # full results stored for reload
                "metrics": {
                    "final_value": total_value,
                    "final_balance": result_data["final_balance"],
                    "roi": roi,
                    "copied": s["copied"],
                    "won": s["won"],
                    "lost": s["lost"],
                    "pending": s["pending"],
                    "win_rate": win_rate,
                    "skipped_tag": s.get("skipped_tag", 0),
                    "skipped_price": s["skipped_price"],
                    "skipped_date": s["skipped_date"],
                    "skipped_collision": s["skipped_collision"],
                    "skipped_conviction": s.get("skipped_conviction", 0),
                    "sold": s.get("sold", 0),
                    "harvested": result_data["harvested_total"],
                },
            }
            st.session_state.saved_hb_views.append(view)
            st.success(f"Saved **{view_name}**")
            st.rerun()


def _render_saved_hb_comparison():
    """Show saved historical backtest views as cards + comparison table."""
    views = st.session_state.saved_hb_views
    if not views:
        return

    st.markdown("---")
    st.subheader("📂 Saved Backtests")

    # Cards row
    cols = st.columns(min(len(views), 4))
    for i, v in enumerate(views):
        m = v["metrics"]
        p = v["params"]
        roi_cls = "pos" if m["roi"] >= 0 else "neg"
        wr_cls  = "pos" if m["win_rate"] >= 55 else ("neutral" if m["win_rate"] >= 45 else "neg")
        with cols[i % min(len(views), 4)]:
            st.markdown(f"""
<div class="view-card">
  <div class="view-card-title">{v['name']}</div>
  <div class="view-card-meta">${p.get('bankroll',0):.0f} · {p.get('lookback_days',0)}d lookback · {len(p.get('selected',[]))} specs</div>
  <div style="margin-top:0.5rem">
    <span class="view-card-metric {roi_cls}">{m['roi']:+.1f}% ROI</span>
    <span class="view-card-meta" style="margin-left:0.6rem">${m['final_value']:.0f} final</span>
  </div>
  <div class="view-card-meta" style="margin-top:0.2rem">
    <span class="{wr_cls}">{m['win_rate']:.0f}% WR</span>
    · {m['copied']} copied · {m['won']}W/{m['lost']}L
  </div>
</div>
""", unsafe_allow_html=True)
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                if st.button("⬆ Load", key=f"hb_load_{v['id']}", help="Restore this backtest's results"):
                    st.session_state["_last_hb_results"] = v["result_data"]
                    st.rerun()
            with btn_col2:
                if st.button("🗑 Delete", key=f"hb_del_{v['id']}"):
                    st.session_state.saved_hb_views = [sv for sv in st.session_state.saved_hb_views if sv["id"] != v["id"]]
                    st.rerun()

    # Comparison table
    if len(views) > 1:
        st.markdown("---")
        st.subheader("Side-by-Side Comparison")
        rows = []
        for v in views:
            m = v["metrics"]
            p = v["params"]
            rows.append({
                "View": v["name"],
                "Bankroll": f"${p.get('bankroll', 0):.0f}",
                "Lookback": f"{p.get('lookback_days', 0)}d",
                "Cap": f"{p.get('max_price_cap', 0.82):.0%}",
                "Tags": "ON" if p.get("enable_tag_filter") else "OFF",
                "Agg": "ON" if p.get("enable_fill_aggregation", True) else "OFF",
                "Specs": len(p.get("selected", [])),
                "Final $": f"${m['final_value']:.2f}",
                "ROI": f"{m['roi']:+.1f}%",
                "Copied": m["copied"],
                "Won": m["won"],
                "Lost": m["lost"],
                "Pending": m["pending"],
                "Win %": f"{m['win_rate']:.0f}%",
                "Harvested": f"${m['harvested']:.2f}",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_no_bot(db):
    """No-Bot Backtest tab. Live positions live on the Dashboard; settings on Settings → No-Bot."""
    st.title("🚫 No-Bot Backtest")
    st.caption("Interactive historical sim for the 'Nothing Ever Happens' strategy. See `docs/no-bot-strategy.md` for the thesis. Live positions are on the **Dashboard**; strategy variables are on **Settings → No-Bot**.")

    import sqlite3
    from pathlib import Path as _Path

    st.markdown("### Interactive Backtest")
    st.caption("Re-runs the historical sim with your chosen parameters.")

    markets_db = _Path(__file__).parent / "backtest" / "markets.db"
    if not markets_db.exists():
        st.error("`backtest/markets.db` not found. Run `python backtest/fetch_markets.py` first.")
        return

    try:
        from backtest import deep_analysis as da
    except Exception as e:
        st.error(f"Could not import backtest.deep_analysis: {e}")
        return

    col1, col2, col3 = st.columns(3)
    capital = col1.number_input("Starting capital ($)", 50.0, 10000.0, 500.0, 50.0, key="nb_cap")
    no_price = col2.slider("Assumed No entry price", 0.25, 0.80, 0.50, 0.05, key="nb_price")
    min_vol = col3.number_input("Min market volume ($)", 1_000.0, 500_000.0, 20_000.0, 5_000.0, key="nb_minvol")

    col4, col5 = st.columns(2)
    max_per_event = col4.slider("Max positions per event", 1, 5, 2, key="nb_maxpe")
    per_bet_cap = col5.slider("Per-bet cap (% of bankroll)", 1, 20, 5, key="nb_pbcap")

    if st.button("Run backtest", key="nb_run"):
        with st.spinner("Loading markets and simulating..."):
            sim_conn = sqlite3.connect(markets_db)
            markets = da.load_markets(sim_conn)
            sim_conn.close()
            result = da.simulate(
                markets,
                starting_capital=capital,
                assumed_no_price=no_price,
                min_volume=min_vol,
                max_per_event=max_per_event,
            )
        final = result["final_bankroll"]
        bets = result["bets_placed"]
        wins = result["bets_won"]
        roi = (final - capital) / capital * 100
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Final bankroll", f"${final:,.0f}", f"{roi:+.1f}%")
        c2.metric("Bets placed", f"{bets:,}")
        c3.metric("Win rate", f"{(wins/max(bets,1))*100:.1f}%")
        c4.metric("Wagered", f"${result['total_wagered']:,.0f}")

        if result["history"]:
            import pandas as _pd
            hdf = _pd.DataFrame(result["history"], columns=["date", "equity", "open_pos"])
            hdf["date"] = _pd.to_datetime(hdf["date"])
            st.line_chart(hdf.set_index("date")[["equity"]], height=280)
            st.area_chart(hdf.set_index("date")[["open_pos"]], height=180)

    st.markdown("### Pre-generated charts")
    charts_dir = _Path(__file__).parent / "backtest" / "charts"
    for name in ["01_no_rate_by_year.png", "02_duration_vs_no_rate.png",
                 "03_ev_vs_entry_price.png", "04_bankroll_simulation.png",
                 "05_annualized_return.png", "06_fee_impact.png"]:
        p = charts_dir / name
        if p.exists():
            st.image(str(p), use_container_width=True)


def render_architecture():
    st.title("🏛️ Architecture & Deployment")
    docs_dir = os.path.dirname(__file__)

    tab_arch, tab_runbook = st.tabs(["Architecture", "Server Runbook"])

    with tab_arch:
        arch_path = os.path.join(docs_dir, "docs", "architecture.md")
        if os.path.exists(arch_path):
            with open(arch_path, "r") as f:
                st.markdown(f.read())
        else:
            st.error("Architecture document not found.")

    with tab_runbook:
        runbook_path = os.path.join(docs_dir, "docs", "server-runbook.md")
        if os.path.exists(runbook_path):
            with open(runbook_path, "r") as f:
                st.markdown(f.read())
        else:
            st.error("server-runbook.md not found.")

def render_strategy():
    st.title("📚 Strategy & Standard Operating Procedures")
    strategy_path = os.path.join(os.path.dirname(__file__), "docs", "strategy.md")
    if os.path.exists(strategy_path):
        with open(strategy_path, "r") as f:
            content = f.read()
        st.markdown(content)
    else:
        st.error("Strategy document not found.")

def render_settings(db):
    st.title("⚙️ Settings")
    st.caption("All tunable parameters for both bots plus system-wide controls. Changes take effect on the next polling cycle.")

    tab_copy, tab_no, tab_sys = st.tabs(["Copy-Bot", "No-Bot", "System"])

    with tab_copy:
        _render_copy_bot_settings(db)
    with tab_no:
        _render_no_bot_settings(db)
    with tab_sys:
        _render_system_settings(db)


def _render_copy_bot_settings(db):
    st.caption("Settings for the specialist copy-bot. Changes take effect on the bot's next polling cycle.")

    cfg = db.get_all_config()

    def val(key, cast=float, default=None):
        if key in cfg:
            return cast(cfg[key]["value"])
        return default

    st.markdown("---")

    # --- Position Sizing ---
    st.subheader("Position Sizing")
    st.caption("Bet size as a % of current wallet balance, graduated by bankroll tier.")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**SHARP tier** (volume grinders, 55%+ win rate)")
        s_low  = st.number_input("Balance < $200 (%)",    min_value=0.1, max_value=25.0, value=val("sharp_bet_pct_low"),  step=0.1, key="s_low",  format="%.1f")
        s_mid  = st.number_input("Balance $200–$999 (%)", min_value=0.1, max_value=25.0, value=val("sharp_bet_pct_mid"),  step=0.1, key="s_mid",  format="%.1f")
        s_high = st.number_input("Balance ≥ $1000 (%)",   min_value=0.1, max_value=25.0, value=val("sharp_bet_pct_high"), step=0.1, key="s_high", format="%.1f")
    with col2:
        st.markdown("**WHALE tier** (swing traders, 40%+ win rate)")
        w_low  = st.number_input("Balance < $200 (%)",    min_value=0.1, max_value=25.0, value=val("whale_bet_pct_low"),  step=0.1, key="w_low",  format="%.1f")
        w_mid  = st.number_input("Balance $200–$999 (%)", min_value=0.1, max_value=25.0, value=val("whale_bet_pct_mid"),  step=0.1, key="w_mid",  format="%.1f")
        w_high = st.number_input("Balance ≥ $1000 (%)",   min_value=0.1, max_value=25.0, value=val("whale_bet_pct_high"), step=0.1, key="w_high", format="%.1f")

    st.markdown("---")

    # --- Win Rate Thresholds ---
    st.subheader("Win Rate Thresholds")
    st.caption("Specialists below their tier threshold are placed on probation and skipped.")

    col3, col4 = st.columns(2)
    with col3:
        sharp_wr = st.slider("SHARP min win rate (%)", 30.0, 80.0, val("sharp_min_win_rate"), 1.0, key="sharp_wr")
    with col4:
        whale_wr = st.slider("WHALE min win rate (%)", 20.0, 70.0, val("whale_min_win_rate"), 1.0, key="whale_wr")

    st.markdown("---")

    # --- Entry Filters ---
    st.subheader("Entry Filters")

    col5, col6 = st.columns(2)
    with col5:
        v_sports   = st.slider("Value cap — Sports (max entry price)", 0.50, 0.99, val("value_cap_sports"),   0.01, key="v_sports",   format="%.2f")
        v_politics = st.slider("Value cap — Politics (max entry price)", 0.50, 0.99, val("value_cap_politics"), 0.01, key="v_politics", format="%.2f")
    with col6:
        slip_thr   = st.slider("Slippage threshold (%)", 0.5, 15.0, val("slippage_threshold_pct"), 0.5, key="slip_thr")
        liq_mult   = st.slider("Liquidity multiple (vs bet size)", 1.0, 5.0, val("liquidity_multiple"), 0.5, key="liq_mult")

    st.markdown("---")

    # --- Market Filters ---
    st.subheader("Market Filters")

    col7, col8 = st.columns(2)
    with col7:
        max_d_sports  = st.number_input("Max days-to-expiry — Sports",    min_value=1, max_value=365, value=val("max_days_sports",  int), key="max_d_sp")
        max_d_default = st.number_input("Max days-to-expiry — Non-sports", min_value=1, max_value=365, value=val("max_days_default", int), key="max_d_df")
    with col8:
        tag_filter = st.toggle("Enable tag filter (strict domain only)", value=val("enable_tag_filter", int) == 1, key="tag_filt",
                               help="OFF = copy all trades. ON = only copy markets within a specialist's assigned categories.")

    st.markdown("---")

    # --- Harvest & Reserve ---
    st.subheader("Harvest & Reserve")

    col9, col10 = st.columns(2)
    with col9:
        harv_mult   = st.number_input("Harvest trigger (N× baseline)", min_value=1.1, max_value=10.0, value=val("harvest_trigger_multiplier"), step=0.1, format="%.1f", key="harv_mult")
        harv_pct    = st.number_input("Harvest transfer (%)",           min_value=10.0, max_value=100.0, value=val("harvest_transfer_pct"), step=5.0, format="%.0f", key="harv_pct")
    with col10:
        min_buf     = st.number_input("Min wallet buffer ($)",          min_value=1.0, max_value=100.0, value=val("min_wallet_buffer"), step=1.0, format="%.1f", key="min_buf")
        poll_int    = st.number_input("Poll interval (seconds)",        min_value=5, max_value=300, value=val("poll_interval", int), step=5, key="poll_int")

    st.markdown("---")

    if st.button("💾 Save All Settings", type="primary"):
        updates = {
            "sharp_bet_pct_low":          s_low,
            "sharp_bet_pct_mid":          s_mid,
            "sharp_bet_pct_high":         s_high,
            "whale_bet_pct_low":          w_low,
            "whale_bet_pct_mid":          w_mid,
            "whale_bet_pct_high":         w_high,
            "sharp_min_win_rate":         sharp_wr,
            "whale_min_win_rate":         whale_wr,
            "value_cap_sports":           v_sports,
            "value_cap_politics":         v_politics,
            "slippage_threshold_pct":     slip_thr,
            "liquidity_multiple":         liq_mult,
            "max_days_sports":            max_d_sports,
            "max_days_default":           max_d_default,
            "enable_tag_filter":          1 if tag_filter else 0,
            "harvest_trigger_multiplier": harv_mult,
            "harvest_transfer_pct":       harv_pct,
            "min_wallet_buffer":          min_buf,
            "poll_interval":              poll_int,
        }
        for key, value in updates.items():
            db.set_config(key, value)
        st.success("Settings saved. The bot will pick them up on its next poll cycle.")
        st.rerun()

    with st.expander("Reset to Defaults"):
        st.warning("This will restore all algorithm settings to their original values.")
        if st.button("Reset All to Defaults", key="reset_defaults"):
            defaults = {
                "sharp_bet_pct_low": 5.0, "sharp_bet_pct_mid": 3.0, "sharp_bet_pct_high": 1.5,
                "whale_bet_pct_low": 3.0, "whale_bet_pct_mid": 2.0, "whale_bet_pct_high": 1.0,
                "harvest_trigger_multiplier": 2.0, "harvest_transfer_pct": 50.0,
                "value_cap_sports": 0.82, "value_cap_politics": 0.75,
                "slippage_threshold_pct": 2.5, "min_wallet_buffer": 5.0,
                "sharp_min_win_rate": 55.0, "whale_min_win_rate": 40.0,
                "max_days_sports": 60, "max_days_default": 90,
                "poll_interval": 30, "enable_tag_filter": 0,
            }
            for key, value in defaults.items():
                db.set_config(key, value)
            st.success("Settings reset to defaults.")
            st.rerun()


def _render_no_bot_settings(db):
    st.caption("Strategy variables for the 'Nothing Ever Happens' No-Bot. See `docs/no-bot-strategy.md` for thesis.")

    cfg = db.get_all_config()

    def cval(key, cast=float, default=None):
        if key in cfg:
            try:
                return cast(cfg[key]["value"])
            except (TypeError, ValueError):
                return default
        return default

    st.markdown("---")
    st.subheader("Mode & Bankroll")

    col1, col2, col3 = st.columns(3)
    with col1:
        nb_live = st.toggle(
            "🟢 Live mode",
            value=cval("nb_live_mode", int, 0) == 1,
            key="nb_live_mode_tgl",
            help="OFF = paper (simulated fills). ON = real money. Keep OFF until go-live."
        )
    with col2:
        nb_bankroll = st.number_input(
            "Starting bankroll ($)",
            min_value=10.0, max_value=100_000.0,
            value=cval("nb_bankroll", float, 50.0),
            step=10.0, format="%.2f", key="nb_bankroll",
            help="Baseline capital. Sizing scales from here."
        )
    with col3:
        nb_small_bankroll = st.toggle(
            "Small-bankroll mode",
            value=cval("nb_small_bankroll", int, 1) == 1,
            key="nb_small_bankroll_tgl",
            help="Bankroll < $250: use fixed $5 bets (Polymarket minimum) instead of %-of-bankroll Kelly. Auto-disables once bankroll > $250."
        )

    col4, col5 = st.columns(2)
    with col4:
        nb_min_bet = st.number_input(
            "Min bet ($)", min_value=1.0, max_value=100.0,
            value=cval("nb_min_bet_usd", float, 5.0), step=1.0, format="%.2f",
            key="nb_min_bet", help="Polymarket enforces $5 minimum per order."
        )
    with col5:
        nb_max_bet_pct = st.slider(
            "Max bet (% of bankroll)", 1.0, 25.0,
            cval("nb_max_bet_pct", float, 5.0), 0.5, key="nb_max_bet_pct",
            help="Caps Kelly-sized bets once small-bankroll mode is off."
        )

    st.markdown("---")
    st.subheader("Turnover & Categories")

    col6, col7 = st.columns(2)
    with col6:
        nb_fast_turnover = st.toggle(
            "Fast-turnover mode",
            value=cval("nb_fast_turnover", int, 1) == 1,
            key="nb_fast_turnover_tgl",
            help="Prioritize Sports-Other (12d median) and Politics (33d median) over Tech-AI (75d median) to recycle capital faster with a small bankroll."
        )
    with col7:
        nb_min_volume = st.number_input(
            "Min market volume ($)",
            min_value=1_000.0, max_value=500_000.0,
            value=cval("nb_min_volume_usd", float, 10_000.0),
            step=1_000.0, format="%.0f", key="nb_min_vol"
        )

    st.markdown("**Category toggles** — disable categories you don't want to trade.")
    c1, c2, c3 = st.columns(3)
    with c1:
        cat_tech = st.toggle("Tech-AI (77% No, 75d median)",
            value=cval("nb_cat_tech_ai", int, 1) == 1, key="nb_cat_tech")
    with c2:
        cat_sports = st.toggle("Sports-Other (70% No, 12d median)",
            value=cval("nb_cat_sports_other", int, 1) == 1, key="nb_cat_sports")
    with c3:
        cat_politics = st.toggle("Politics (70.5% No, 33d median)",
            value=cval("nb_cat_politics", int, 1) == 1, key="nb_cat_politics")

    st.markdown("---")
    st.subheader("Entry Rules & Risk")

    col8, col9 = st.columns(2)
    with col8:
        nb_ceiling_tech = st.slider("Tech-AI — max No entry price", 0.30, 0.95,
            cval("nb_ceiling_tech_ai", float, 0.60), 0.01, key="nb_ceil_tech", format="%.2f")
        nb_ceiling_sports = st.slider("Sports-Other — max No entry price", 0.30, 0.95,
            cval("nb_ceiling_sports_other", float, 0.55), 0.01, key="nb_ceil_sports", format="%.2f")
        nb_ceiling_politics = st.slider("Politics — max No entry price", 0.30, 0.95,
            cval("nb_ceiling_politics", float, 0.55), 0.01, key="nb_ceil_politics", format="%.2f")
    with col9:
        nb_kelly_tech = st.slider("Tech-AI — Kelly fraction", 0.05, 0.50,
            cval("nb_kelly_tech_ai", float, 0.20), 0.05, key="nb_k_tech", format="%.2f")
        nb_kelly_sports = st.slider("Sports-Other — Kelly fraction", 0.05, 0.50,
            cval("nb_kelly_sports_other", float, 0.15), 0.05, key="nb_k_sports", format="%.2f")
        nb_kelly_politics = st.slider("Politics — Kelly fraction", 0.05, 0.50,
            cval("nb_kelly_politics", float, 0.15), 0.05, key="nb_k_politics", format="%.2f")

    col10, col11 = st.columns(2)
    with col10:
        nb_cat_exposure = st.slider("Max single-category exposure (% of bankroll)", 10.0, 100.0,
            cval("nb_max_category_exposure", float, 40.0), 5.0, key="nb_cat_exp")
    with col11:
        nb_drawdown = st.slider("Drawdown halt (% from start)", 10.0, 80.0,
            cval("nb_drawdown_halt", float, 30.0), 5.0, key="nb_dd")

    st.markdown("---")
    st.subheader("No-Bot Telegram Notifications")

    col12, col13, col14 = st.columns(3)
    with col12:
        nb_notify_buy = st.toggle("Notify on BUY",
            value=db.get_config("notify_nb_buy", "1") == "1", key="nb_n_buy")
    with col13:
        nb_notify_resolve = st.toggle("Notify on WIN/LOSS",
            value=db.get_config("notify_nb_resolve", "1") == "1", key="nb_n_res")
    with col14:
        nb_notify_threshold = st.toggle("Notify on price threshold crossed",
            value=db.get_config("notify_nb_threshold", "0") == "1", key="nb_n_thr",
            help="(Requires websocket listener — coming soon.)")

    st.markdown("---")

    if st.button("💾 Save No-Bot Settings", type="primary", key="save_nb"):
        updates = {
            "nb_live_mode":           1 if nb_live else 0,
            "nb_bankroll":            nb_bankroll,
            "nb_small_bankroll":      1 if nb_small_bankroll else 0,
            "nb_min_bet_usd":         nb_min_bet,
            "nb_max_bet_pct":         nb_max_bet_pct,
            "nb_fast_turnover":       1 if nb_fast_turnover else 0,
            "nb_min_volume_usd":      nb_min_volume,
            "nb_cat_tech_ai":         1 if cat_tech else 0,
            "nb_cat_sports_other":    1 if cat_sports else 0,
            "nb_cat_politics":        1 if cat_politics else 0,
            "nb_ceiling_tech_ai":     nb_ceiling_tech,
            "nb_ceiling_sports_other": nb_ceiling_sports,
            "nb_ceiling_politics":    nb_ceiling_politics,
            "nb_kelly_tech_ai":       nb_kelly_tech,
            "nb_kelly_sports_other":  nb_kelly_sports,
            "nb_kelly_politics":      nb_kelly_politics,
            "nb_max_category_exposure": nb_cat_exposure,
            "nb_drawdown_halt":       nb_drawdown,
            "notify_nb_buy":          1 if nb_notify_buy else 0,
            "notify_nb_resolve":      1 if nb_notify_resolve else 0,
            "notify_nb_threshold":    1 if nb_notify_threshold else 0,
        }
        for key, value in updates.items():
            db.set_config(key, value)
        st.success("No-Bot settings saved.")
        st.rerun()


def _render_system_settings(db):
    st.caption("System-wide controls: Telegram notifications, database actions, and a full config snapshot.")

    cfg = db.get_all_config()
    telegram_enabled = cfg.get("enable_telegram", {}).get("value", "1") == "1"

    st.markdown("---")
    st.subheader("Telegram — Master Switch")
    col1, col2 = st.columns([1, 3])
    with col1:
        new_tg = st.toggle("Enable Telegram", value=telegram_enabled, key="tg_toggle")
        if new_tg != telegram_enabled:
            db.set_config("enable_telegram", 1 if new_tg else 0)
            st.rerun()
    with col2:
        st.caption("When disabled, the bots run silently. Per-notification toggles below.")

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip("\"'")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip("\"'")
    tg_configured = bool(token and chat_id)
    if not tg_configured:
        st.info("Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in your `.env` to enable notifications.")
    else:
        st.success("Telegram credentials are configured.")
        if telegram_enabled and st.button("Send Test Message", key="tg_test"):
            try:
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                resp = requests.post(url, json={"chat_id": chat_id, "text": "✅ Test message from Polymarket dashboard."}, timeout=5)
                if resp.status_code == 200:
                    st.success("Test message sent!")
                else:
                    st.error(f"Telegram returned HTTP {resp.status_code}: {resp.text}")
            except Exception as e:
                st.error(f"Failed: {e}")

    st.markdown("---")
    st.subheader("Copy-Bot Notification Categories")
    st.caption("Defaults: buy / resolve / error are ON; hourly summary and skip messages are OFF.")

    def _ntoggle(label, key, default):
        cur = db.get_config(key, default) == "1"
        new = st.toggle(label, value=cur, key=f"tg_{key}")
        if new != cur:
            db.set_config(key, 1 if new else 0)

    c1, c2, c3 = st.columns(3)
    with c1:
        _ntoggle("BUY confirmations", "notify_buy", "1")
        _ntoggle("WIN/LOSS resolutions", "notify_resolve", "1")
    with c2:
        _ntoggle("CRITICAL errors", "notify_error", "1")
        _ntoggle("Hourly summary", "notify_summary", "0")
    with c3:
        _ntoggle("SKIP / REJECT messages", "notify_skip", "0")

    st.markdown("---")
    st.subheader("Database Actions")

    col3, col4 = st.columns(2)
    with col3:
        st.markdown("**Purge pending copy-bot trades**")
        st.caption("Clears all PENDING trades to free up paper capital.")
        if st.button("🧹 Purge Pending Trades", key="purge_pending_ctrl"):
            db.clear_all_pending_trades()
            st.success("All pending trades cleared.")
            st.rerun()

    st.markdown("---")
    st.subheader("Active Configuration Snapshot")
    st.caption("Read-only view of all current settings.")
    all_cfg = db.get_all_config()
    cfg_rows = [{"Setting": k, "Value": v["value"], "Description": v["description"]} for k, v in sorted(all_cfg.items())]
    st.dataframe(pd.DataFrame(cfg_rows), use_container_width=True, hide_index=True)


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
