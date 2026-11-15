"""Paper portfolio valued at NAV (PLAN.md §2 feature 4, local form).

A pure paper construct: starts at PAPER_START_CASH USD, takes the
cycle's BUY decisions at their target weights, and values every holding
at the brief's NAV reference price. No orders, no custody, no trading —
positions are arithmetic on API reference values only.
"""

from __future__ import annotations

from typing import Optional

PAPER_START_CASH = 100_000.0


def build_portfolio(briefs: list[dict], decisions: list[dict],
                    valued_at: str) -> dict:
    """Snapshot the paper portfolio implied by one cycle's decisions."""
    brief_by_ticker = {b["ticker"]: b for b in briefs}
    holdings = []
    invested = 0.0
    for d in decisions:
        weight = d["target_weight_pct"]
        if d["view"] != "BUY" or weight <= 0:
            continue
        brief = brief_by_ticker[d["ticker"]]
        nav = float(brief["nav_price"])
        value = PAPER_START_CASH * weight / 100.0
        invested += value
        holdings.append({
            "ticker": d["ticker"],
            "weight_pct": weight,
            "nav_price": brief["nav_price"],
            "nav_updated_at": brief["nav_updated_at"],
            "units": round(value / nav, 6) if nav else None,
            "value_usd": round(value, 2),
        })
    holdings.sort(key=lambda h: h["ticker"])
    return {
        "kind": "paper_portfolio_nav_valued",
        "start_cash_usd": PAPER_START_CASH,
        "cash_usd": round(PAPER_START_CASH - invested, 2),
        "invested_usd": round(invested, 2),
        "total_value_usd": round(PAPER_START_CASH, 2) if holdings else PAPER_START_CASH,
        "holdings": holdings,
        "valued_at": valued_at,
        "note": "Paper only: values are target weights x start cash, marked "
                "at the API NAV reference (not an execution price). Total "
                "equals start cash at inception by construction; later "
                "cycles re-mark holdings at fresh NAVs.",
    }


def remark_portfolio(previous: Optional[dict], briefs: list[dict],
                     valued_at: str) -> Optional[dict]:
    """Re-mark an existing snapshot's holdings at the briefs' current NAVs."""
    if not previous or not previous.get("holdings"):
        return None
    brief_by_ticker = {b["ticker"]: b for b in briefs}
    holdings = []
    total_holdings_value = 0.0
    for h in previous["holdings"]:
        brief = brief_by_ticker.get(h["ticker"])
        if brief is None or h.get("units") is None:
            holdings.append(h)
            total_holdings_value += h["value_usd"]
            continue
        nav = float(brief["nav_price"])
        value = round(h["units"] * nav, 2)
        total_holdings_value += value
        holdings.append({
            **h,
            "nav_price": brief["nav_price"],
            "nav_updated_at": brief["nav_updated_at"],
            "value_usd": value,
        })
    return {
        **previous,
        "holdings": holdings,
        "invested_usd": round(total_holdings_value, 2),
        "total_value_usd": round(previous["cash_usd"] + total_holdings_value, 2),
        "valued_at": valued_at,
    }
