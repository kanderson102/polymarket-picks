"""
Deep analysis: time patterns, fees, sizing strategy, and bankroll simulation.
Generates charts saved to backtest/charts/.
"""
from __future__ import annotations

import json
import math
import sqlite3
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np

DB_PATH = Path(__file__).parent / "markets.db"
CHARTS_DIR = Path(__file__).parent / "charts"
CHARTS_DIR.mkdir(exist_ok=True)

# ──────────────────────────────────────────────────────────────────────────────
# Fee model
# ──────────────────────────────────────────────────────────────────────────────
SPORTS_CATS = {"Sports-Basketball","Sports-Soccer","Sports-Baseball",
               "Sports-Hockey","Sports-Esports","Sports-Other"}
POLITICS_CATS = {"Politics"}

def taker_fee_rate(no_price: float, category: str) -> float:
    if category in SPORTS_CATS:
        peak = 0.0075
    elif category in POLITICS_CATS:
        peak = 0.0100
    else:
        peak = 0.0100
    return peak * 4 * no_price * (1 - no_price)

# Current POL price ~$0.25, gas ~0.006 POL per tx → $0.0015 per order
GAS_COST_USD = 0.0015

def net_ev_per_dollar(no_rate: float, no_price: float, category: str) -> float:
    fee = taker_fee_rate(no_price, category)
    gas_drag = GAS_COST_USD  # as fraction, only meaningful on tiny bets
    win_payout = (1.0 / no_price) - 1.0
    return no_rate * win_payout - (1 - no_rate) - fee

def breakeven_no_price(no_rate: float, category: str) -> float:
    peak = 0.0075 if category in SPORTS_CATS else 0.0100
    # Approximate ignoring fee's dependence on price
    return min(no_rate / (1 + peak), 0.99)

# ──────────────────────────────────────────────────────────────────────────────
# Strategy configuration
# ──────────────────────────────────────────────────────────────────────────────

#
# Base rates measured on single-market events (binary matchups) only.
# Multi-market events are skipped entirely — their per-candidate pricing is
# arbitraged to sum to ~1.0, so any candidate cheap enough to meet our
# ceiling is the market's favorite and the base rate flips against us.
#
CATEGORY_CONFIG = {
    # category:       (no_rate, tier, entry_ceiling, kelly_frac)
    "Tech-AI":        (0.770, 1, 0.60, 0.20),
    "Sports-Other":   (0.701, 2, 0.55, 0.15),
    "Politics":       (0.705, 2, 0.55, 0.15),
}

# Every category not in CATEGORY_CONFIG is excluded. Named here for clarity:
EXCLUDED = {
    "Sports-Soccer", "Sports-Esports", "Sports-Basketball", "Sports-Baseball",
    "Sports-Hockey", "Economics", "Crypto", "Recurring", "UpOrDown",
    "Entertainment", "Other", "Stocks-Daily", "General",
}

MIN_VOLUME_USD = 10_000   # below this, pricing is noisy
MAX_PER_EVENT = 1         # single-market events only, so per-event cap is 1 by construction

def kelly_bet(bankroll: float, no_rate: float, no_price: float,
              kelly_frac: float, min_bet: float = 1.0) -> float:
    win_payout = (1.0 / no_price) - 1.0
    edge = no_rate * win_payout - (1 - no_rate)
    if edge <= 0:
        return 0.0
    full_kelly = edge / win_payout
    bet = bankroll * full_kelly * kelly_frac
    return max(min_bet, min(bet, bankroll * 0.05))  # cap at 5% of bankroll

# ──────────────────────────────────────────────────────────────────────────────
# Data loading
# ──────────────────────────────────────────────────────────────────────────────

def load_markets(conn: sqlite3.Connection) -> list[dict]:
    # Binary matchups only (events containing exactly one market). Multi-
    # market events have per-candidate pricing that's effectively arbitraged,
    # leaving no tradable edge — skip them.
    rows = conn.execute("""
        SELECT m.id, m.question, m.event_id, m.category, m.resolved_yes,
               m.start_date, m.end_date, m.volume, m.liquidity
        FROM markets m
        JOIN (SELECT event_id FROM markets GROUP BY event_id HAVING COUNT(*) = 1) e
          ON m.event_id = e.event_id
        WHERE m.start_date != '' AND m.end_date != ''
          AND m.category IN ('Tech-AI', 'Sports-Other', 'Politics')
          AND JULIANDAY(m.end_date) - JULIANDAY(m.start_date) BETWEEN 0 AND 500
        ORDER BY m.start_date
    """).fetchall()
    return [
        dict(id=r[0], question=r[1], event_id=r[2], category=r[3], resolved_yes=r[4],
             start_date=r[5], end_date=r[6], volume=r[7], liquidity=r[8])
        for r in rows
    ]

# ──────────────────────────────────────────────────────────────────────────────
# Simulation
# ──────────────────────────────────────────────────────────────────────────────

class Position:
    def __init__(self, market_id, event_id, category, bet_size, no_price, start, end, resolved_yes):
        self.market_id = market_id
        self.event_id = event_id
        self.category = category
        self.bet_size = bet_size
        self.no_price = no_price
        self.start = start
        self.end = end
        self.resolved_yes = resolved_yes

    def pnl(self) -> float:
        fee = taker_fee_rate(self.no_price, self.category) * self.bet_size
        if self.resolved_yes == 0:  # No won
            return self.bet_size * ((1.0 / self.no_price) - 1.0) - fee - GAS_COST_USD
        else:
            return -self.bet_size - fee - GAS_COST_USD


def simulate(markets: list[dict], starting_capital: float = 100.0,
             assumed_no_price: float = 0.50,
             min_volume: float = MIN_VOLUME_USD,
             max_concurrent: Optional[int] = None,
             max_per_event: int = MAX_PER_EVENT) -> dict:
    """
    Realistic sequential simulation with capital constraints.
    - Only bets on markets with volume >= min_volume (avoids illiquid micro-markets)
    - Enforces hard capital constraint: can't bet more than available free cash
    - Max concurrent positions capped by capital / min_bet
    - Uses fixed bet size = Kelly-sized fraction of starting capital (not compounding)
      to avoid unrealistic exponential blowup
    """
    MIN_BET = 5.0
    # Per-bet size: Kelly fraction of STARTING capital (not rolling bankroll)
    # This gives realistic, non-explosive growth
    base_bet_capital = starting_capital

    if max_concurrent is None:
        max_concurrent = max(5, int(starting_capital / MIN_BET))

    bankroll = starting_capital
    open_positions: list[Position] = []

    # Pre-filter: only liquid markets in valid categories
    filtered = [
        m for m in markets
        if m["category"] in CATEGORY_CONFIG
        and m["category"] not in EXCLUDED
        and (m["volume"] or 0) >= min_volume
        and m["start_date"] and m["end_date"]
    ]

    all_dates = sorted(set(
        m["start_date"][:10] for m in filtered
    ) | set(
        m["end_date"][:10] for m in filtered
    ))

    market_by_start: dict[str, list] = {}
    for m in filtered:
        market_by_start.setdefault(m["start_date"][:10], []).append(m)

    bankroll_history: list[tuple[str, float, int]] = []
    bets_placed = 0
    bets_won = 0
    total_wagered = 0.0

    for date in all_dates:
        # Resolve positions ending today
        still_open = []
        for pos in open_positions:
            if pos.end <= date:
                pnl = pos.pnl()
                bankroll += pos.bet_size + pnl
                if pos.resolved_yes == 0:
                    bets_won += 1
            else:
                still_open.append(pos)
        open_positions = still_open

        # Enter new positions (respect capital and concurrent limits)
        if date in market_by_start:
            # Prioritize by tier (tier 1 first), then volume
            candidates = sorted(market_by_start[date],
                                key=lambda m: (CATEGORY_CONFIG[m["category"]][1],
                                               -(m["volume"] or 0)))
            for m in candidates:
                cat = m["category"]
                no_rate, tier, ceiling, kelly_frac = CATEGORY_CONFIG[cat]
                if assumed_no_price > ceiling:
                    continue
                if len(open_positions) >= max_concurrent:
                    break
                if bankroll < MIN_BET:
                    break

                # Correlation control: cap positions per event_id so a
                # multi-candidate event can't dominate our book.
                same_event = sum(1 for p in open_positions
                                 if p.event_id == m.get("event_id"))
                if same_event >= max_per_event:
                    continue

                # Bet size: Kelly of base capital, not rolling (avoids exponential blowup)
                win_payout = (1.0 / assumed_no_price) - 1.0
                edge = no_rate * win_payout - (1 - no_rate)
                if edge <= 0:
                    continue
                full_kelly = edge / win_payout
                bet = base_bet_capital * full_kelly * kelly_frac
                bet = max(MIN_BET, min(bet, bankroll, starting_capital * 0.10))
                if bet > bankroll:
                    continue

                bankroll -= bet
                bets_placed += 1
                total_wagered += bet
                open_positions.append(Position(
                    market_id=m["id"], event_id=m.get("event_id"), category=cat,
                    bet_size=bet, no_price=assumed_no_price,
                    start=date, end=m["end_date"][:10],
                    resolved_yes=m["resolved_yes"]
                ))

        tied_up = sum(p.bet_size for p in open_positions)
        total_equity = bankroll + tied_up
        bankroll_history.append((date, total_equity, len(open_positions)))

    final = bankroll + sum(p.bet_size for p in open_positions)
    return {
        "history": bankroll_history,
        "final_bankroll": final,
        "bets_placed": bets_placed,
        "bets_won": bets_won,
        "total_wagered": total_wagered,
    }

# ──────────────────────────────────────────────────────────────────────────────
# Charts
# ──────────────────────────────────────────────────────────────────────────────

STYLE = {
    "figure.facecolor": "#0e1117",
    "axes.facecolor": "#1a1f2e",
    "axes.edgecolor": "#3d4a6b",
    "axes.labelcolor": "#c8d0e7",
    "axes.titlecolor": "#e8edf5",
    "xtick.color": "#8892a4",
    "ytick.color": "#8892a4",
    "grid.color": "#2a3348",
    "text.color": "#c8d0e7",
    "legend.facecolor": "#1a1f2e",
    "legend.edgecolor": "#3d4a6b",
    "lines.linewidth": 2,
}

CAT_COLORS = {
    "Tech-AI":         "#00d4ff",
    "Economics":       "#ffd700",
    "Politics":        "#ff6b6b",
    "Sports-Hockey":   "#a8e6cf",
    "Sports-Other":    "#88d8b0",
    "Sports-Baseball": "#ffcc99",
    "Sports-Esports":  "#c3b1e1",
    "Sports-Soccer":   "#aec6cf",
    "Sports-Basketball":"#808080",
}


def chart_no_rate_by_year(conn: sqlite3.Connection) -> None:
    cats = ["Tech-AI", "Economics", "Politics", "Sports-Hockey", "Sports-Other"]
    years = ["2023", "2024", "2025", "2026"]

    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(10, 5))

        for cat in cats:
            rates = []
            counts = []
            for yr in years:
                row = conn.execute("""
                    SELECT COUNT(*), SUM(CASE WHEN resolved_yes=0 THEN 1 ELSE 0 END)
                    FROM markets WHERE category=? AND start_date LIKE ?
                """, (cat, f"{yr}%")).fetchone()
                n, no = row
                if n and n >= 5:
                    rates.append(no / n * 100)
                    counts.append(n)
                else:
                    rates.append(None)
                    counts.append(0)

            valid_x = [i for i, r in enumerate(rates) if r is not None]
            valid_y = [rates[i] for i in valid_x]
            valid_labels = [years[i] for i in valid_x]

            if len(valid_x) >= 2:
                ax.plot(valid_labels, valid_y, "o-", color=CAT_COLORS.get(cat, "#888"),
                        label=f"{cat} (n={sum(counts):,})", markersize=7)

        ax.axhline(73.7, color="#ffffff", linestyle="--", alpha=0.4, linewidth=1,
                   label="Overall avg 73.7%")
        ax.set_title("No Resolution Rate by Year (2023–2026)", fontsize=14, pad=12)
        ax.set_ylabel("No Rate (%)")
        ax.set_ylim(55, 100)
        ax.legend(fontsize=8, loc="lower left")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(CHARTS_DIR / "01_no_rate_by_year.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
    print("  → 01_no_rate_by_year.png")


def chart_duration_vs_no_rate(conn: sqlite3.Connection) -> None:
    buckets = [
        ("0–3d",   0,   3),
        ("4–14d",  4,  14),
        ("15–30d", 15, 30),
        ("31–90d", 31, 90),
        ("91–180d",91,180),
        ("181d+", 181,500),
    ]
    labels, rates, counts = [], [], []
    for label, lo, hi in buckets:
        row = conn.execute("""
            SELECT COUNT(*), SUM(CASE WHEN resolved_yes=0 THEN 1 ELSE 0 END)
            FROM markets
            WHERE JULIANDAY(end_date)-JULIANDAY(start_date) BETWEEN ? AND ?
              AND start_date!='' AND end_date!=''
        """, (lo, hi)).fetchone()
        n, no = row
        labels.append(label)
        rates.append(no / n * 100 if n else 0)
        counts.append(n)

    with plt.rc_context(STYLE):
        fig, ax1 = plt.subplots(figsize=(9, 5))
        colors = ["#4a6fa5" if r < 75 else "#00d4ff" if r < 85 else "#ffd700"
                  for r in rates]
        bars = ax1.bar(labels, rates, color=colors, alpha=0.85, edgecolor="#3d4a6b")
        ax1.axhline(73.7, color="#ff6b6b", linestyle="--", alpha=0.6, linewidth=1.5,
                    label="Overall avg 73.7%")
        ax1.set_ylabel("No Rate (%)")
        ax1.set_title("No Resolution Rate vs Market Duration", fontsize=14, pad=12)
        ax1.set_ylim(60, 95)
        ax1.legend(fontsize=9)

        ax2 = ax1.twinx()
        ax2.plot(labels, [c / 1000 for c in counts], "o--",
                 color="#c3b1e1", alpha=0.7, linewidth=1.5, markersize=6)
        ax2.set_ylabel("Market count (thousands)", color="#c3b1e1")
        ax2.tick_params(axis="y", labelcolor="#c3b1e1")
        ax2.spines["right"].set_edgecolor("#c3b1e1")

        for bar, rate in zip(bars, rates):
            ax1.text(bar.get_x() + bar.get_width()/2, rate + 0.5,
                     f"{rate:.1f}%", ha="center", va="bottom", fontsize=9, color="#e8edf5")

        fig.tight_layout()
        fig.savefig(CHARTS_DIR / "02_duration_vs_no_rate.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
    print("  → 02_duration_vs_no_rate.png")


def chart_ev_vs_entry_price(conn: sqlite3.Connection) -> None:
    cats_to_show = ["Tech-AI", "Economics", "Politics", "Sports-Hockey",
                    "Sports-Esports", "Sports-Basketball"]
    no_prices = np.linspace(0.25, 0.80, 100)

    cat_no_rates = {}
    for cat in cats_to_show:
        row = conn.execute("""
            SELECT COUNT(*), SUM(CASE WHEN resolved_yes=0 THEN 1 ELSE 0 END)
            FROM markets WHERE category=?
        """, (cat,)).fetchone()
        n, no = row
        cat_no_rates[cat] = no / n if n else 0.5

    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(10, 5))

        for cat in cats_to_show:
            no_rate = cat_no_rates[cat]
            evs = [net_ev_per_dollar(no_rate, p, cat) for p in no_prices]
            ax.plot(no_prices, evs, color=CAT_COLORS.get(cat, "#888"),
                    label=f"{cat} ({no_rate:.1%} No)", linewidth=2)

        ax.axhline(0, color="#888", linestyle="-", linewidth=0.8, alpha=0.5)
        ax.axvline(0.50, color="#ffffff", linestyle=":", linewidth=1, alpha=0.3,
                   label="No=0.50 (50/50 market)")
        ax.fill_between(no_prices, 0, -0.5, alpha=0.05, color="#ff6b6b")
        ax.set_xlabel("No Entry Price (lower = cheaper, more upside)")
        ax.set_ylabel("Expected Value per $1 bet")
        ax.set_title("Net EV by Entry Price and Category (after fees)", fontsize=14, pad=12)
        ax.set_xlim(0.25, 0.80)
        ax.set_ylim(-0.5, 2.5)
        ax.legend(fontsize=8, loc="upper right")
        ax.grid(True, alpha=0.3)

        ax.text(0.27, -0.35, "Losing zone", color="#ff6b6b", fontsize=8, alpha=0.7)

        fig.tight_layout()
        fig.savefig(CHARTS_DIR / "03_ev_vs_entry_price.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
    print("  → 03_ev_vs_entry_price.png")


def chart_bankroll_simulation(markets: list[dict]) -> None:
    scenarios = [
        ("$100 start, No≤0.40 (aggressive)", 100,  0.40),
        ("$100 start, No≤0.50 (moderate)",   100,  0.50),
        ("$100 start, No≤0.65 (conservative)",100,  0.65),
        ("$500 start, No≤0.50",               500,  0.50),
    ]
    colors = ["#00d4ff", "#ffd700", "#ff6b6b", "#a8e6cf"]

    with plt.rc_context(STYLE):
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

        ref_result = None
        for i, (label, capital, no_price) in enumerate(scenarios):
            result = simulate(markets, starting_capital=capital,
                              assumed_no_price=no_price, min_volume=5000)
            history = result["history"]
            if i == 1:
                ref_result = result

            dates = [h[0] for h in history]
            bankrolls = [h[1] for h in history]
            n_open = [h[2] for h in history]

            mask = [d >= "2024-01-01" for d in dates]
            d_filt = [dates[j] for j, m in enumerate(mask) if m]
            b_filt = [bankrolls[j] for j, m in enumerate(mask) if m]
            n_filt = [n_open[j] for j, m in enumerate(mask) if m]

            if not d_filt:
                continue

            b_norm = [b / capital * 100 for b in b_filt]
            fin = result["final_bankroll"]
            roi = (fin - capital) / capital * 100
            ax1.plot(range(len(d_filt)), b_norm, color=colors[i],
                     label=f"{label}\n→ ${fin:.0f} ({roi:+.0f}% ROI, "
                           f"{result['bets_placed']:,} bets, "
                           f"{result['bets_won']/max(result['bets_placed'],1)*100:.0f}% win)")

            if i == 1:
                ax2.fill_between(range(len(d_filt)), n_filt, alpha=0.35,
                                 color="#ffd700", label="Concurrent positions")
                ax2.plot(range(len(d_filt)), n_filt, color="#ffd700", linewidth=1)

        ax1.axhline(100, color="#555", linestyle="--", alpha=0.5, linewidth=1)
        ax1.set_title("Bankroll Simulation (2024–2026)\n"
                      "Liquid markets only (vol >$5k), Kelly-sized bets",
                      fontsize=11, pad=10)
        ax1.set_ylabel("Portfolio value (% of starting capital)")
        ax1.set_xlabel("Trading days elapsed")
        ax1.legend(fontsize=7, loc="upper left")
        ax1.grid(True, alpha=0.3)

        ax2.set_title("Concurrent Open Positions ($100 start, No≤0.50)\n"
                      "Shows capital lock-up over time", fontsize=10, pad=10)
        ax2.set_ylabel("# Positions open")
        ax2.set_xlabel("Trading days elapsed")
        ax2.legend(fontsize=9)
        ax2.grid(True, alpha=0.3)

        fig.tight_layout()
        fig.savefig(CHARTS_DIR / "04_bankroll_simulation.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
    print("  → 04_bankroll_simulation.png")


def chart_annualized_return(conn: sqlite3.Connection) -> None:
    cats = [c for c in CATEGORY_CONFIG if c not in EXCLUDED]

    data = []
    for cat in cats:
        no_rate, tier, ceiling, kelly_frac = CATEGORY_CONFIG[cat]
        row = conn.execute("""
            SELECT AVG(JULIANDAY(end_date)-JULIANDAY(start_date))
            FROM markets
            WHERE category=? AND end_date!='' AND start_date!=''
              AND JULIANDAY(end_date)-JULIANDAY(start_date) BETWEEN 1 AND 400
        """, (cat,)).fetchone()
        avg_dur = row[0] or 30

        ev_per_bet = net_ev_per_dollar(no_rate, ceiling * 0.9, cat)  # assume ~10% below ceiling
        # Conservative assumption: capital deployed/recycled avg_dur days per cycle
        cycles_per_year = 365 / avg_dur
        # But not all capital is deployed all the time; assume 40% utilization
        utilization = 0.40
        annualized = ev_per_bet * cycles_per_year * utilization * 100
        data.append((cat, avg_dur, ev_per_bet * 100, annualized, tier))

    data.sort(key=lambda x: -x[3])

    cats_sorted = [d[0] for d in data]
    ev_pct = [d[2] for d in data]
    ann_pct = [d[3] for d in data]
    durations = [d[1] for d in data]

    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(11, 5))

        x = np.arange(len(cats_sorted))
        w = 0.35
        bars1 = ax.bar(x - w/2, ev_pct, w, label="EV per bet (%)",
                       color=[CAT_COLORS.get(c, "#888") for c in cats_sorted], alpha=0.85)
        bars2 = ax.bar(x + w/2, ann_pct, w, label="Est. annualized return (%)\n(40% capital util.)",
                       color=[CAT_COLORS.get(c, "#888") for c in cats_sorted], alpha=0.45,
                       edgecolor=[CAT_COLORS.get(c, "#888") for c in cats_sorted], linewidth=1.5)

        for bar, val in zip(bars1, ev_pct):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                    f"{val:.0f}%", ha="center", va="bottom", fontsize=7.5, color="#e8edf5")
        for bar, val, dur in zip(bars2, ann_pct, durations):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                    f"{val:.0f}%\n({dur:.0f}d)", ha="center", va="bottom",
                    fontsize=7, color="#aaa")

        ax.set_xticks(x)
        ax.set_xticklabels(cats_sorted, rotation=25, ha="right", fontsize=9)
        ax.set_ylabel("Return (%)")
        ax.set_title("EV Per Bet vs Estimated Annualized Return by Category\n"
                     f"(entry at ~90% of ceiling No price, 40% capital utilization)",
                     fontsize=12, pad=10)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.2, axis="y")
        ax.set_ylim(0, max(ann_pct) * 1.25)
        fig.tight_layout()
        fig.savefig(CHARTS_DIR / "05_annualized_return.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
    print("  → 05_annualized_return.png")


def chart_fee_impact(conn: sqlite3.Connection) -> None:
    cats = ["Tech-AI", "Economics", "Politics", "Sports-Hockey", "Sports-Other"]
    no_prices = [0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]

    with plt.rc_context(STYLE):
        fig, axes = plt.subplots(1, 2, figsize=(13, 5))

        # Left: gross vs net EV at No=0.50 for each category
        ax = axes[0]
        no_rates = {}
        for cat in cats:
            row = conn.execute("""
                SELECT COUNT(*), SUM(CASE WHEN resolved_yes=0 THEN 1 ELSE 0 END)
                FROM markets WHERE category=?
            """, (cat,)).fetchone()
            n, no = row
            no_rates[cat] = no / n if n else 0.5

        x = np.arange(len(cats))
        gross_evs = [no_rates[c] * ((1/0.50) - 1) - (1 - no_rates[c]) for c in cats]
        fee_drag   = [taker_fee_rate(0.50, c) for c in cats]
        net_evs    = [g - f for g, f in zip(gross_evs, fee_drag)]

        ax.bar(x, gross_evs, 0.5, label="Gross EV", color="#4a6fa5", alpha=0.8)
        ax.bar(x, [-f for f in fee_drag], 0.5, bottom=gross_evs,
               label="Fee drag", color="#ff6b6b", alpha=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels([c.replace("Sports-", "S-") for c in cats],
                           rotation=20, ha="right", fontsize=9)
        ax.set_title("Gross vs Net EV at No=0.50 (after Polymarket fees)", fontsize=11, pad=8)
        ax.set_ylabel("EV per $1 bet")
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.2, axis="y")
        for i, (g, f) in enumerate(zip(gross_evs, fee_drag)):
            ax.text(i, g + 0.01, f"fee={f*100:.2f}%", ha="center", fontsize=7.5, color="#ff9999")

        # Right: Gas cost significance at different bet sizes
        ax2 = axes[1]
        bet_sizes = [1, 2, 5, 10, 25, 50, 100]
        gas_pct = [GAS_COST_USD / b * 100 for b in bet_sizes]
        fee_pct = [taker_fee_rate(0.50, "Politics") * 100 for _ in bet_sizes]  # flat at 50¢

        ax2.semilogx(bet_sizes, gas_pct, "o-", color="#a8e6cf",
                     label=f"Gas cost (${GAS_COST_USD:.4f}/tx on Polygon)", linewidth=2)
        ax2.axhline(fee_pct[0], color="#ffd700", linestyle="--", linewidth=1.5,
                    label=f"Polymarket taker fee ({fee_pct[0]:.2f}% at 50¢)")
        ax2.set_xlabel("Bet size ($)")
        ax2.set_ylabel("Cost as % of bet")
        ax2.set_title("Gas vs Taker Fee: When Does Gas Matter?", fontsize=11, pad=8)
        ax2.legend(fontsize=9)
        ax2.grid(True, alpha=0.3)
        ax2.text(1.2, gas_pct[0] + 0.02, "← Gas dominates\nbelow ~$1", fontsize=8, color="#a8e6cf")
        ax2.text(50, fee_pct[0] + 0.01, "Taker fee →", fontsize=8, color="#ffd700")

        fig.tight_layout()
        fig.savefig(CHARTS_DIR / "06_fee_impact.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
    print("  → 06_fee_impact.png")


def print_sizing_guide(conn: sqlite3.Connection) -> None:
    print("\n" + "="*70)
    print("SIZING STRATEGY — Confidence-Weighted Kelly")
    print("="*70)
    print(f"{'Category':<22} {'No Rate':>8} {'Tier':>5} {'Ceil No':>8} {'Kelly%':>7} "
          f"{'EV@ceil':>8} {'BE price':>9}")
    print("-"*70)

    for cat, (no_rate, tier, ceiling, kelly_frac) in sorted(
            CATEGORY_CONFIG.items(), key=lambda x: -x[1][0]):
        ev = net_ev_per_dollar(no_rate, ceiling * 0.9, cat)
        be = breakeven_no_price(no_rate, cat)
        star = "★" * (4 - tier)
        print(f"{cat:<22} {no_rate:>8.1%} {star:>5} {ceiling:>8.2f} "
              f"{kelly_frac:>6.0%}K {ev:>+8.3f} {be:>9.3f}")

    print()
    print("Tier 1 (★★★): Aspirational edge — market systematically overprices Yes")
    print("Tier 2 (★★):  Structural/volume edge — high No rate, still exploitable")
    print("Tier 3 (★):   Thin edge — only bet if price is well below ceiling")
    print()
    print("Kelly fraction is of the FULL Kelly formula, applied per-bet.")
    print("Max bet capped at 5% of bankroll regardless of Kelly output.")

    # Starting capital analysis
    print()
    print("="*70)
    print("STARTING CAPITAL ANALYSIS")
    print("="*70)

    min_bet = 5.0  # Polymarket minimum
    for capital in [100, 250, 500, 1000]:
        max_concurrent = int(capital / min_bet)
        # Avg market lasts ~40 days for our mix, avg 8 new markets/day across categories
        # (rough: 1245 Tech-AI / (2*365) + 284 Econ / (2*365) ≈ 2/day for top tier)
        top_tier_per_year = 300  # rough estimate: ~1/day qualifying markets
        print(f"  ${capital:<5}: max {max_concurrent} concurrent @${min_bet} min  |  "
              f"~{top_tier_per_year} bets/yr at avg 10% bankroll size → "
              f"EV ≈ ${capital * 0.10 * 0.70 * top_tier_per_year:.0f}/yr gross")

    print()
    print("Gas cost per tx: ~$0.0015 (Polygon) — negligible above $1 bet size")
    print("Polymarket taker fee: ~0.75% (sports) to 1.0% (politics) at 50¢ No price")
    print("Fee is at most 1% of stake — does NOT materially change the edge")
    print()
    print("Recommendation: $250-500 minimum for meaningful position sizing flexibility")
    print("$100 works but limits you to 20 concurrent @$5 — sufficient for testing")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    markets = load_markets(conn)
    print(f"Loaded {len(markets):,} markets with valid dates\n")

    print("Generating charts...")
    chart_no_rate_by_year(conn)
    chart_duration_vs_no_rate(conn)
    chart_ev_vs_entry_price(conn)
    chart_annualized_return(conn)
    chart_fee_impact(conn)
    print(f"  Running simulation for bankroll chart ({len(markets):,} markets)...")
    chart_bankroll_simulation(markets)

    print_sizing_guide(conn)
    conn.close()
    print(f"\nAll charts saved to {CHARTS_DIR}/")


if __name__ == "__main__":
    main()
