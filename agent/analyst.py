"""Analyst: turns a research brief into a view + rationale.

The Analyst protocol is the swap point for a future LLM-backed analyst
(see llm.py — no real model is wired in phase 2). The active
implementation, RuleBasedAnalyst, is an explicit placeholder with
simple, auditable rules over the brief's hard data:

  1. Data quality gate: missing/zero total supply -> AVOID (weight 0).
     A token we cannot size is not a position.
  2. Hard staleness: NAV older than HARD_STALE_SECONDS (7 days, beyond
     any market-holiday explanation) -> HOLD at weight 0 (no new risk
     on a price we cannot trust).
  3. Momentum (vs previous engine snapshot, when known):
       <= -5% -> HOLD at weight 0 (do not add into a falling reference)
       otherwise -> BUY candidate.
  4. BUY candidates receive an equal target weight across the cycle's
     BUY set; the engine performs that normalization, so analyze()
     returns weight=None for BUY and the engine fills it in.

Every rationale cites the actual numbers used, so a human (or a later
LLM analyst) can audit exactly why a view was produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

HARD_STALE_SECONDS = 7 * 24 * 3600
MOMENTUM_FLOOR_PCT = -5.0


@dataclass
class Analysis:
    view: str                       # BUY | HOLD | AVOID
    target_weight_pct: Optional[float]  # None => engine assigns (BUY equal-weight)
    rationale: str


class Analyst(Protocol):
    def analyze(self, brief: dict) -> Analysis:
        ...


class RuleBasedAnalyst:
    """Deterministic placeholder analyst (phase 2). No LLM involved."""

    name = "rules-v0"

    def analyze(self, brief: dict) -> Analysis:
        ticker = brief["ticker"]
        supply = brief.get("total_supply")
        try:
            supply_val = float(supply) if supply is not None else None
        except (TypeError, ValueError):
            supply_val = None
        if supply_val is None or supply_val <= 0:
            return Analysis(
                view="AVOID",
                target_weight_pct=0.0,
                rationale=(
                    f"{ticker}: total supply missing or zero in API data "
                    f"(got {supply!r}); data-quality gate excludes it from "
                    "the paper portfolio until supply is reported."
                ),
            )
        age = brief.get("nav_age_seconds")
        if age is not None and age > HARD_STALE_SECONDS:
            return Analysis(
                view="HOLD",
                target_weight_pct=0.0,
                rationale=(
                    f"{ticker}: NAV reference {brief.get('nav_price')} is "
                    f"{age / 3600.0:.1f}h old, beyond the 7d hard-stale bound; "
                    "no new exposure on an untrusted reference price."
                ),
            )
        momentum = brief.get("momentum_pct")
        if momentum is not None and momentum <= MOMENTUM_FLOOR_PCT:
            return Analysis(
                view="HOLD",
                target_weight_pct=0.0,
                rationale=(
                    f"{ticker}: NAV momentum {momentum:+.2f}% vs previous "
                    "snapshot breaches the -5% floor; hold, do not add."
                ),
            )
        mom_txt = (f"momentum {momentum:+.2f}%" if momentum is not None
                   else "no prior snapshot (momentum neutral)")
        return Analysis(
            view="BUY",
            target_weight_pct=None,
            rationale=(
                f"{ticker}: NAV reference {brief.get('nav_price')} usable "
                f"(age {(age or 0) / 3600.0:.1f}h within bound), supply "
                f"{supply_val} reported, {mom_txt}; equal-weight BUY "
                "candidate for this cycle."
            ),
        )
