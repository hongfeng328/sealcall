"""Universe selection and research-brief generation.

The coverage universe is dynamic: every token in the Tokenized Stocks
API whose record carries NAV data (per the phase-1 data layer, a token
without NAV has no usable price and is excluded). Nothing is hardcoded.

Each brief is a structured JSON dict:
  ticker, name, contract_address, nav_price, nav_updated_at,
  nav_age_seconds, nav_stale (vs the NYSE-calendar policy in
  data/market_calendar.py), total_supply,
  multiplier, corporate_actions, momentum_pct (vs the previous engine
  snapshot, when one exists), supply_change_pct (same, phase 4; None
  until history carries total_supply), brief_text, generated_at.

Corporate actions: the API exposes them only by UUID via
/corporate-actions/{id} and token records do not carry IDs, so the
brief surfaces what is actually observable — a multiplier != 1 means a
corporate-action adjustment (dividend reinvestment / split) has been
applied to the share-to-token ratio — plus any corporate-action entries
found in the token's metadata payload. It does not invent events.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

from data.client import TokenizedStocksClient, TokenRecord
from data.market_calendar import MAX_MARKET_AGE_SECONDS, nav_freshness

# Engine staleness policy (phase 3): NYSE-calendar-aware, see
# data/market_calendar.py. Age is measured in market-open seconds, so a
# quote frozen at Friday's close stays fresh all weekend, while a quote
# that has sat through > MAX_MARKET_AGE_SECONDS of live trading is
# stale. The raw wall-clock age is still reported verbatim.

HISTORY_FILENAME = "nav_history.json"


def fetch_universe(client: TokenizedStocksClient) -> list[TokenRecord]:
    """All tokens whose record carries NAV data (the coverage universe)."""
    return [t for t in client.list_all_tokens() if t.nav_price is not None]


def _corporate_actions(record: TokenRecord, metadata: Optional[dict]) -> list[dict]:
    """Observable corporate-action signals for one token (see module docstring)."""
    actions: list[dict] = []
    if record.multiplier is not None and record.multiplier != 1:
        actions.append({
            "type": "multiplier_adjustment",
            "multiplier": record.multiplier,
            "detail": "share-to-token ratio != 1: a corporate-action "
                      "adjustment (e.g. reinvested distributions or a "
                      "split) has been applied by the issuer",
            "source": "token record multiplier field",
        })
    if metadata:
        for key, value in metadata.items():
            if "corporate" in key.lower() and value:
                actions.append({
                    "type": "metadata_entry",
                    "field": key,
                    "value": value,
                    "source": "token metadata endpoint",
                })
    return actions


def _find_momentum(history: dict, ticker: str, nav_price: Optional[str]) -> Optional[float]:
    """% change vs the previous snapshot in nav_history, or None if unknown."""
    prev = history.get(ticker)
    if not prev or nav_price is None:
        return None
    try:
        prev_price = float(prev["nav_price"])
        cur_price = float(nav_price)
    except (TypeError, ValueError):
        return None
    if prev_price == 0:
        return None
    return round((cur_price - prev_price) / prev_price * 100.0, 4)


def _find_supply_change(history: dict, ticker: str,
                        supply: Any) -> Optional[float]:
    """% change in total supply vs the previous snapshot, or None.

    History entries written before phase 4 carry no ``total_supply``,
    so this returns None until one full cycle has run with the extended
    history format — the signal is reported as unavailable, never faked.
    """
    prev = history.get(ticker)
    if not prev or supply is None or prev.get("total_supply") is None:
        return None
    try:
        prev_supply = float(prev["total_supply"])
        cur_supply = float(supply)
    except (TypeError, ValueError):
        return None
    if prev_supply == 0:
        return None
    return round((cur_supply - prev_supply) / prev_supply * 100.0, 4)


def build_brief(client: TokenizedStocksClient, record: TokenRecord,
                history: dict, now: Optional[datetime] = None,
                fetch_metadata: bool = True) -> dict:
    """Build one structured research brief for a universe token."""
    now = now or datetime.now(timezone.utc)
    quote = client.get_nav(record, now=now)
    # Calendar-aware verdict supersedes the client's fixed-hour bound:
    # a present quote is stale only if too much *open-market* time has
    # passed since it was stamped; a missing quote is always unusable.
    fresh = (nav_freshness(quote.updated_at, now)
             if quote.present and quote.updated_at is not None else None)
    nav_stale = (not quote.present) or (fresh is not None and not fresh.is_fresh)
    metadata: Optional[dict] = None
    metadata_error: Optional[str] = None
    if fetch_metadata:
        try:
            metadata = client.get_metadata(record.symbol)
        except Exception as exc:  # metadata is enrichment, never fatal
            metadata_error = str(exc)
    supply = record.total_supply
    if supply is None:
        try:
            supply = client.get_total_supply(record.contract_address)
        except Exception:
            supply = None
    actions = _corporate_actions(record, metadata)
    momentum = _find_momentum(history, record.symbol, record.nav_price)
    supply_change = _find_supply_change(history, record.symbol, supply)
    age_h = (quote.age_seconds or 0) / 3600.0
    market_age_h = ((fresh.market_age_seconds if fresh else 0) or 0) / 3600.0
    lines = [
        f"{record.name} ({record.symbol}): NAV reference "
        f"{record.nav_price} (Chainlink reference value, not a live quote), "
        f"last updated {record.nav_price_updated_at} "
        f"({age_h:.1f}h wall age, {market_age_h:.1f}h market-open age, "
        f"stale={nav_stale} per nyse-calendar-v1).",
        f"Token supply {supply}; share-to-token multiplier {record.multiplier}.",
    ]
    if actions:
        lines.append("Corporate-action signals: "
                     + "; ".join(a["type"] for a in actions) + ".")
    else:
        lines.append("No corporate-action signals observable in API data.")
    if momentum is not None:
        lines.append(f"NAV momentum vs previous engine snapshot: {momentum:+.2f}%.")
    else:
        lines.append("No previous NAV snapshot; momentum unknown.")
    if supply_change is not None:
        lines.append(f"Total supply change vs previous snapshot: {supply_change:+.2f}%.")
    else:
        lines.append("No previous supply snapshot; supply change unknown.")
    brief = {
        "ticker": record.symbol,
        "name": record.name,
        "contract_address": record.contract_address,
        "isin": record.isin,
        "nav_price": record.nav_price,
        "nav_updated_at": record.nav_price_updated_at,
        "nav_age_seconds": quote.age_seconds,
        "nav_stale": nav_stale,
        "nav_freshness_policy": "nyse-calendar-v1",
        "nav_market_age_seconds": fresh.market_age_seconds if fresh else None,
        "nav_max_market_age_seconds": MAX_MARKET_AGE_SECONDS,
        "total_supply": supply,
        "multiplier": record.multiplier,
        "corporate_actions": actions,
        "momentum_pct": momentum,
        "supply_change_pct": supply_change,
        "brief_text": " ".join(lines),
        "generated_at": now.isoformat(),
    }
    if metadata_error:
        brief["metadata_error"] = metadata_error
    return brief


# -- NAV history (engine memory across runs) ------------------------------

def load_history(out_dir: str) -> dict:
    path = os.path.join(out_dir, HISTORY_FILENAME)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_history(out_dir: str, briefs: list[dict]) -> None:
    history = {
        b["ticker"]: {
            "nav_price": b["nav_price"],
            "nav_updated_at": b["nav_updated_at"],
            "total_supply": b.get("total_supply"),
            "snapshot_at": b["generated_at"],
        }
        for b in briefs if b.get("nav_price") is not None
    }
    path = os.path.join(out_dir, HISTORY_FILENAME)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(history, fh, indent=2, ensure_ascii=False)
