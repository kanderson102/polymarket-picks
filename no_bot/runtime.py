"""Runtime config for the No-Bot — loads UI-editable overrides from trading.db.

Any setting with an `nb_*` key in the shared `bot_config` table overrides the
corresponding static default in `config.py`. The bot polls these on each scan
so dashboard changes take effect without a restart.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .config import (
    CATEGORY_CONFIG, CategoryRule, DRAWDOWN_HALT,
    MAX_BET_FRAC_BANKROLL, MAX_CATEGORY_EXPOSURE, MAX_PER_EVENT,
    MIN_BET_USD, MIN_VOLUME_USD,
)

_DB_PATH = Path(__file__).resolve().parent.parent / "trading.db"


@dataclass(frozen=True)
class RuntimeConfig:
    live: bool
    bankroll: float
    small_bankroll_mode: bool
    fast_turnover: bool
    min_bet_usd: float
    max_bet_frac: float
    max_category_exposure: float
    max_per_event: int
    min_volume_usd: float
    drawdown_halt: float
    categories: dict[str, CategoryRule]


def _load_cfg() -> dict[str, str]:
    try:
        conn = sqlite3.connect(_DB_PATH)
        rows = conn.execute("SELECT key, value FROM bot_config").fetchall()
        conn.close()
        return {k: v for k, v in rows}
    except sqlite3.OperationalError:
        return {}


def _f(cfg: dict[str, str], key: str, default: float) -> float:
    try:
        return float(cfg.get(key, default))
    except (TypeError, ValueError):
        return default


def _b(cfg: dict[str, str], key: str, default: bool) -> bool:
    return cfg.get(key, "1" if default else "0") == "1"


def load() -> RuntimeConfig:
    cfg = _load_cfg()
    bankroll = _f(cfg, "nb_bankroll", 50.0)
    small_bankroll = _b(cfg, "nb_small_bankroll", True) and bankroll < 250.0

    enabled = {
        "Tech-AI":      _b(cfg, "nb_cat_tech_ai", True),
        "Sports-Other": _b(cfg, "nb_cat_sports_other", True),
        "Politics":     _b(cfg, "nb_cat_politics", True),
    }
    kelly = {
        "Tech-AI":      _f(cfg, "nb_kelly_tech_ai", 0.20),
        "Sports-Other": _f(cfg, "nb_kelly_sports_other", 0.15),
        "Politics":     _f(cfg, "nb_kelly_politics", 0.15),
    }
    ceilings = {
        "Tech-AI":      _f(cfg, "nb_ceiling_tech_ai", 0.60),
        "Sports-Other": _f(cfg, "nb_ceiling_sports_other", 0.55),
        "Politics":     _f(cfg, "nb_ceiling_politics", 0.55),
    }
    categories = {
        name: CategoryRule(
            no_rate=CATEGORY_CONFIG[name].no_rate,
            tier=CATEGORY_CONFIG[name].tier,
            ceiling=ceilings[name],
            kelly_frac=kelly[name],
        )
        for name in CATEGORY_CONFIG
        if enabled.get(name, True)
    }

    return RuntimeConfig(
        live=_b(cfg, "nb_live_mode", False),
        bankroll=bankroll,
        small_bankroll_mode=small_bankroll,
        fast_turnover=_b(cfg, "nb_fast_turnover", True),
        min_bet_usd=_f(cfg, "nb_min_bet_usd", MIN_BET_USD),
        max_bet_frac=_f(cfg, "nb_max_bet_pct", MAX_BET_FRAC_BANKROLL * 100) / 100.0,
        max_category_exposure=_f(cfg, "nb_max_category_exposure", MAX_CATEGORY_EXPOSURE * 100) / 100.0,
        max_per_event=MAX_PER_EVENT,
        min_volume_usd=_f(cfg, "nb_min_volume_usd", MIN_VOLUME_USD),
        drawdown_halt=_f(cfg, "nb_drawdown_halt", DRAWDOWN_HALT * 100) / 100.0,
        categories=categories,
    )
