"""Phase-4 probe: run one real engine cycle under signals-v1 and
record, per token, the view, the human-readable rationale and the exact
signal values (plus each signal's live/degraded/unavailable status)
that produced it.

Output: probe/analyst_v1_report.json — written from the real run only.
Degraded signals are reported as degraded; nothing is back-filled.

Usage (from sealcall/ root):
    .venv/bin/python probe/analyst_v1_report.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.analyst import SignalAnalyst  # noqa: E402
from agent.engine import run_cycle  # noqa: E402

HERE = os.path.dirname(__file__)
OUT_PATH = os.path.join(HERE, "analyst_v1_report.json")


def main() -> int:
    analyst = SignalAnalyst()
    result = run_cycle(analyst=analyst)
    cycle = result["cycle"]
    ctx = analyst.context() or {}

    tokens = []
    for d in result["decisions"]:
        sig = analyst.signal_log.get(d["ticker"], {})
        tokens.append({
            "ticker": d["ticker"],
            "view": d["view"],
            "target_weight_pct": d["target_weight_pct"],
            "rationale": d["rationale"],
            "signals": sig,
        })

    degraded = []
    if ctx.get("momentum_status") != "live":
        degraded.append({
            "signal": "cross_cycle_nav_momentum",
            "status": ctx.get("momentum_status"),
            "reason": ctx.get("momentum_reason"),
        })
    if ctx.get("supply_status") != "live":
        degraded.append({
            "signal": "total_supply_change",
            "status": ctx.get("supply_status"),
            "reason": ctx.get("supply_reason"),
        })

    report = {
        "probe": "sealcall-analyst-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "analyst": cycle["analyst"],
        "universe_size": cycle["universe_size"],
        "universe": cycle["universe"],
        "view_distribution": cycle["views"],
        "degraded_signals": degraded,
        "tokens": tokens,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print(f"[analyst-v1] wrote {OUT_PATH}")
    print(f"[analyst-v1] distribution: {cycle['views']}")
    for t in tokens:
        print(f"  {t['ticker']:8s} {t['view']:5s} w={t['target_weight_pct']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
