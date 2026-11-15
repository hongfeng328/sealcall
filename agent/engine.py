"""Engine orchestration: one full SealCall cycle.

cycle = fetch universe (NAV-bearing tokens, dynamic)
      -> build a research brief per token
      -> analyst produces a view per brief
      -> engine normalizes BUY weights to an equal-weight set
      -> decision objects are created (hash-sealed format, see decisions.py)
      -> paper portfolio snapshot valued at NAV
      -> NAV history updated for the next cycle's momentum

Outputs (JSON, under agent/out/ by default):
  briefs.json, decisions.json, portfolio.json, portfolio_history.json,
  nav_history.json (engine memory), cycle.json (run summary).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.client import TokenizedStocksClient  # noqa: E402

from . import briefs as brief_mod  # noqa: E402
from .analyst import Analyst, RuleBasedAnalyst  # noqa: E402
from .decisions import make_decision  # noqa: E402
from .portfolio import build_portfolio, remark_portfolio  # noqa: E402

DEFAULT_REVEAL_DELAY_SECONDS = 24 * 3600
DEFAULT_OUT_DIR = os.path.join(os.path.dirname(__file__), "out")


def _dump(out_dir: str, name: str, obj) -> str:
    path = os.path.join(out_dir, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)
    return path


def run_cycle(out_dir: str = DEFAULT_OUT_DIR,
              client: Optional[TokenizedStocksClient] = None,
              analyst: Optional[Analyst] = None,
              reveal_delay_seconds: int = DEFAULT_REVEAL_DELAY_SECONDS,
              now: Optional[datetime] = None) -> dict:
    """Run one full cycle and persist all outputs. Returns the cycle dict."""
    os.makedirs(out_dir, exist_ok=True)
    client = client or TokenizedStocksClient()
    analyst = analyst or RuleBasedAnalyst()
    now = now or datetime.now(timezone.utc)
    created_at = int(now.timestamp())

    history = brief_mod.load_history(out_dir)
    universe = brief_mod.fetch_universe(client)
    brief_list = [brief_mod.build_brief(client, rec, history, now=now)
                  for rec in universe]

    analyses = {b["ticker"]: analyst.analyze(b) for b in brief_list}
    buy_tickers = [t for t, a in analyses.items() if a.view == "BUY"]
    equal_weight = round(100.0 / len(buy_tickers), 4) if buy_tickers else 0.0

    decision_list = []
    for brief in brief_list:
        a = analyses[brief["ticker"]]
        weight = equal_weight if a.view == "BUY" else (a.target_weight_pct or 0.0)
        d = make_decision(
            ticker=brief["ticker"],
            view=a.view,
            target_weight_pct=weight,
            rationale=a.rationale,
            brief=brief,
            created_at=created_at,
            reveal_delay_seconds=reveal_delay_seconds,
        )
        decision_list.append(d.to_json())

    portfolio = build_portfolio(brief_list, decision_list, now.isoformat())

    # Append a re-marked snapshot to the history when a previous
    # portfolio exists, so the dashboard can show a NAV series.
    hist_path = os.path.join(out_dir, "portfolio_history.json")
    snapshots = []
    if os.path.exists(hist_path):
        with open(hist_path, "r", encoding="utf-8") as fh:
            snapshots = json.load(fh)
    if snapshots:
        remarked = remark_portfolio(snapshots[-1], brief_list, now.isoformat())
        if remarked and remarked["total_value_usd"] != snapshots[-1]["total_value_usd"]:
            snapshots.append(remarked)
    snapshots.append(portfolio)

    brief_mod.save_history(out_dir, brief_list)

    cycle = {
        "generated_at": now.isoformat(),
        "universe_size": len(universe),
        "universe": [b["ticker"] for b in brief_list],
        "views": {v: sum(1 for d in decision_list if d["view"] == v)
                  for v in ("BUY", "HOLD", "AVOID")},
        "analyst": getattr(analyst, "name", type(analyst).__name__),
        "reveal_delay_seconds": reveal_delay_seconds,
        "briefs_file": "briefs.json",
        "decisions_file": "decisions.json",
        "portfolio_file": "portfolio.json",
    }
    _dump(out_dir, "briefs.json", brief_list)
    _dump(out_dir, "decisions.json", decision_list)
    _dump(out_dir, "portfolio.json", portfolio)
    _dump(out_dir, "portfolio_history.json", snapshots)
    _dump(out_dir, "cycle.json", cycle)
    return {"cycle": cycle, "briefs": brief_list,
            "decisions": decision_list, "portfolio": portfolio}
