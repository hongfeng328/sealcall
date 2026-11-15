"""Phase-3 probe: NYSE-calendar NAV freshness policy, fixed scenarios.

Exercises data/market_calendar.nav_freshness on four hand-picked
(updated_at, now) pairs and records the observed verdicts verbatim into
probe/nav_calendar_test.json, alongside what the retired fixed-hour
bounds (24h phase-1 client default, 96h phase-2 engine bound) would
have said. Nothing here is hand-written output: the JSON is dumped
from the actual function results, and the probe exits nonzero if any
scenario's calendar verdict differs from its expectation.

Scenarios (all 2026, America/New_York):
  weekend_freeze    Fri close quote read on Sunday -> fresh
  open_market_fresh same-session quote, 45 min old -> fresh
  open_market_stale Monday quote read Wednesday afternoon -> stale
  holiday_freeze    Thanksgiving-eve close quote read Friday pre-open
                    (Thanksgiving Day closed) -> fresh  [bonus]

Usage (from sealcall/ root):
    .venv/bin/python probe/nav_calendar_test.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.market_calendar import nav_freshness  # noqa: E402

HERE = os.path.dirname(__file__)
OUT_PATH = os.path.join(HERE, "nav_calendar_test.json")


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


SCENARIOS = [
    {
        "name": "weekend_freeze",
        "description": "NAV stamped Fri 2026-11-13 15:55 ET (just before "
                       "the close); evaluated Sun 2026-11-15 11:30 ET. "
                       "Market closed the whole weekend: freeze is not "
                       "staleness.",
        "updated_at": utc("2026-11-13T20:55:00"),
        "now": utc("2026-11-15T16:30:00"),
        "expect_fresh": True,
    },
    {
        "name": "open_market_fresh",
        "description": "NAV stamped Wed 2026-11-18 10:15 ET, evaluated "
                       "same session 11:00 ET: 45 minutes of open-market "
                       "age, well within the 4h bound.",
        "updated_at": utc("2026-11-18T15:15:00"),
        "now": utc("2026-11-18T16:00:00"),
        "expect_fresh": True,
    },
    {
        "name": "open_market_stale",
        "description": "NAV stamped Mon 2026-11-16 15:00 ET, evaluated "
                       "Wed 2026-11-18 14:00 ET: it has sat through "
                       "1h (Mon) + 6.5h (Tue) + 4.5h (Wed) = 12h of live "
                       "trading without updating -> stale.",
        "updated_at": utc("2026-11-16T20:00:00"),
        "now": utc("2026-11-18T19:00:00"),
        "expect_fresh": False,
    },
    {
        "name": "holiday_freeze",
        "description": "Bonus: NAV stamped Wed 2026-11-25 15:55 ET; "
                       "evaluated Fri 2026-11-27 09:00 ET (pre-open on "
                       "the early-close day). Thanksgiving Day (Thu) "
                       "the exchange was closed, so the quote is still "
                       "fresh.",
        "updated_at": utc("2026-11-25T20:55:00"),
        "now": utc("2026-11-27T14:00:00"),
        "expect_fresh": True,
    },
]


def main() -> int:
    results = []
    all_ok = True
    for sc in SCENARIOS:
        verdict = nav_freshness(sc["updated_at"], sc["now"])
        wall_age = verdict.wall_age_seconds
        entry = {
            "name": sc["name"],
            "description": sc["description"],
            "updated_at_utc": sc["updated_at"].isoformat(),
            "now_utc": sc["now"].isoformat(),
            "wall_age_hours": round(wall_age / 3600.0, 3),
            "market_age_hours": round(verdict.market_age_seconds / 3600.0, 3),
            "max_market_age_hours": verdict.max_market_age_seconds / 3600.0,
            "calendar_is_fresh": verdict.is_fresh,
            "expected_is_fresh": sc["expect_fresh"],
            "match": verdict.is_fresh == sc["expect_fresh"],
            "retired_fixed_24h_is_fresh": wall_age <= 24 * 3600,
            "retired_fixed_96h_is_fresh": wall_age <= 96 * 3600,
        }
        all_ok = all_ok and entry["match"]
        results.append(entry)
        print(f"[nav-cal] {entry['name']}: market_age="
              f"{entry['market_age_hours']}h fresh={verdict.is_fresh} "
              f"expected={sc['expect_fresh']} match={entry['match']}")

    log = {
        "probe": "sealcall-nav-calendar-test",
        "policy": "nyse-calendar-v1 (data/market_calendar.py)",
        "ran_at_utc": datetime.now(timezone.utc).isoformat(),
        "scenarios": results,
        "verdict": "PASS" if all_ok else "FAIL",
    }
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(log, fh, indent=2, ensure_ascii=False)
    print(f"[nav-cal] wrote {OUT_PATH} verdict={log['verdict']}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
