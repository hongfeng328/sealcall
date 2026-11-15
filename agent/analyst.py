"""Analyst: turns a research brief into a view + rationale.

The Analyst protocol is the swap point for a future LLM-backed analyst
(see llm.py — no real model is wired in). Two rule implementations live
here:

- ``RuleBasedAnalyst`` (``rules-v0``, phase 2): the original placeholder.
  Kept for reproducibility of the phase-2 e2e evidence. Its failure
  mode is documented: with NAVs frozen (weekend) every gate passes and
  it BUYs the whole universe — no discrimination.

- ``SignalAnalyst`` (``signals-v1``, phase 4): the active analyst.
  Deterministic and auditable, driven only by signals that are really
  observable from the API + local history:

    * cross-cycle NAV momentum (brief ``momentum_pct``), used both
      absolutely and as a cross-sectional relative-strength rank;
    * total-supply change vs the previous snapshot
      (brief ``supply_change_pct``);
    * tokenized float value (total_supply x NAV) — a depth proxy for
      how much real tokenized stock backs the reference price;
    * NAV freshness under the NYSE-calendar policy (brief
      ``nav_stale`` / ``nav_market_age_seconds``).

  Honesty rules: a signal that is missing — or present but carrying no
  information (e.g. momentum identically 0.00% across the universe
  because NAVs are frozen and the prior snapshot was taken from the
  same frozen values) — is *degraded*: excluded from the score and
  named as degraded in the rationale and in ``signal_log``. Nothing is
  extrapolated or invented.

  Decision ladder (first matching rung wins):
    1. Data-quality gate: supply missing/zero -> AVOID (weight 0).
    2. Stale-reference gate: NAV stale per nyse-calendar-v1 -> HOLD
       (weight 0) until the feed refreshes.
    3. Negligible-float gate: float < FLOAT_AVOID_USD and < 10% of the
       universe median float -> AVOID (weight 0): the on-chain
       reference rests on a negligible tokenized float.
    4. Directional score (only from live signals; momentum weight 0.7,
       supply-change weight 0.3, renormalized over what is available):
       score >= +0.25 -> BUY, score <= -0.25 -> AVOID, else HOLD.
    5. No directional evidence (all directional signals degraded):
       posture falls back to float depth, stated as such in the
       rationale — float >= FLOAT_BUY_USD -> BUY (equal-weight
       candidate, low conviction), otherwise HOLD (thin float, observe).

  Cross-sectional context (ranks, median float, momentum degeneracy)
  is computed by ``prepare(briefs)``, which the engine calls once per
  cycle when present. ``analyze()`` also works without ``prepare()``
  (single-brief context; rank-based components then degrade).
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Optional, Protocol

HARD_STALE_SECONDS = 7 * 24 * 3600
MOMENTUM_FLOOR_PCT = -5.0

# signals-v1 constants (documented, deliberately round numbers).
FLOAT_BUY_USD = 1_000_000.0        # float depth bar for a fallback BUY
FLOAT_AVOID_USD = 250_000.0        # negligible-float gate (absolute)
FLOAT_AVOID_MEDIAN_SHARE = 0.10    # ...and relative to universe median
SCORE_BUY = 0.25
SCORE_AVOID = -0.25
MOMENTUM_FULL_PCT = 5.0            # |momentum| that saturates the signal
SUPPLY_FULL_PCT = 2.0              # |supply change| that saturates it
W_MOMENTUM = 0.7
W_SUPPLY = 0.3


@dataclass
class Analysis:
    view: str                       # BUY | HOLD | AVOID
    target_weight_pct: Optional[float]  # None => engine assigns (BUY equal-weight)
    rationale: str


class Analyst(Protocol):
    def analyze(self, brief: dict) -> Analysis:
        ...
    # Optional per-cycle hook: prepare(briefs: list[dict]) -> None.
    # The engine calls it once with the full brief list when the
    # analyst provides it (cross-sectional analysts need the universe).


def _as_float(value) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _percentile_midrank(values: dict, key) -> Optional[float]:
    """Mid-rank percentile in [0, 1] of ``key`` within ``values``."""
    v = values.get(key)
    if v is None or not values:
        return None
    less = sum(1 for x in values.values() if x is not None and x < v)
    equal = sum(1 for x in values.values() if x is not None and x == v)
    n = sum(1 for x in values.values() if x is not None)
    if n == 0:
        return None
    return (less + 0.5 * equal) / n


class RuleBasedAnalyst:
    """Deterministic placeholder analyst (phase 2). No LLM involved."""

    name = "rules-v0"

    def analyze(self, brief: dict) -> Analysis:
        ticker = brief["ticker"]
        supply = brief.get("total_supply")
        supply_val = _as_float(supply)
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


class SignalAnalyst:
    """signals-v1: cross-sectional, degradation-aware rule analyst."""

    name = "signals-v1"

    def __init__(self) -> None:
        self._ctx: Optional[dict] = None
        # Per-ticker record of the signals behind each view, filled by
        # analyze(); consumed by probe/analyst_v1_report.py.
        self.signal_log: dict[str, dict] = {}

    # -- cross-sectional context ----------------------------------------

    def prepare(self, briefs: list[dict]) -> None:
        """Compute universe context from one cycle's briefs."""
        moms = {b["ticker"]: _as_float(b.get("momentum_pct")) for b in briefs}
        known = [v for v in moms.values() if v is not None]
        if not known:
            mom_status, mom_reason = "unavailable", (
                "no previous NAV snapshot for any universe token")
        elif len(known) < max(2, len(briefs) // 2):
            mom_status, mom_reason = "unavailable", (
                f"momentum known for only {len(known)}/{len(briefs)} tokens")
        elif max(known) - min(known) <= 1e-9:
            mom_status, mom_reason = "degenerate", (
                f"momentum is {known[0]:+.2f}% for every token — NAVs are "
                "frozen (market closed) and the previous snapshot was taken "
                "from the same frozen values, so momentum carries no "
                "cross-sectional information this cycle")
        else:
            mom_status, mom_reason = "live", ""

        floats: dict[str, Optional[float]] = {}
        for b in briefs:
            supply = _as_float(b.get("total_supply"))
            nav = _as_float(b.get("nav_price"))
            floats[b["ticker"]] = (supply * nav
                                   if supply and nav else None)
        known_floats = sorted(v for v in floats.values() if v is not None)
        median_float = median(known_floats) if known_floats else None
        # Rank 1 = largest float.
        float_rank = {
            t: (1 + sum(1 for v in known_floats if v > f))
            if f is not None else None
            for t, f in floats.items()
        }
        sups = {b["ticker"]: _as_float(b.get("supply_change_pct"))
                for b in briefs}
        sup_known_vals = [v for v in sups.values() if v is not None]
        if len(sup_known_vals) < max(2, len(briefs) // 2):
            sup_status, sup_reason = "unavailable", (
                f"supply change known for {len(sup_known_vals)}/{len(briefs)} "
                "tokens: nav_history.json carried no total_supply before "
                "phase 4 (the format was extended, so the signal starts "
                "with the next full cycle — it is not back-filled)")
        elif max(sup_known_vals) - min(sup_known_vals) <= 1e-9:
            sup_status, sup_reason = "degenerate", (
                f"total supply change is {sup_known_vals[0]:+.2f}% for every "
                "token — supplies are frozen with the market closed, so "
                "the signal carries no directional information this cycle")
        else:
            sup_status, sup_reason = "live", ""

        self._ctx = {
            "momentum": moms,
            "momentum_status": mom_status,
            "momentum_reason": mom_reason,
            "momentum_percentile": {
                t: _percentile_midrank(moms, t) for t in moms},
            "floats": floats,
            "median_float": median_float,
            "float_rank": float_rank,
            "float_percentile": {
                t: _percentile_midrank(floats, t) for t in floats},
            "supply_changes": sups,
            "supply_known": len(sup_known_vals),
            "supply_status": sup_status,
            "supply_reason": sup_reason,
            "universe_size": len(briefs),
        }

    def context(self) -> Optional[dict]:
        return self._ctx

    # -- per-brief analysis ----------------------------------------------

    def analyze(self, brief: dict) -> Analysis:
        ticker = brief["ticker"]
        if self._ctx is None:
            self.prepare([brief])
        ctx = self._ctx
        n = ctx["universe_size"]

        supply = _as_float(brief.get("total_supply"))
        nav = _as_float(brief.get("nav_price"))
        momentum = _as_float(brief.get("momentum_pct"))
        supchg = _as_float(brief.get("supply_change_pct"))
        float_usd = ctx["floats"].get(ticker)
        rank = ctx["float_rank"].get(ticker)
        market_age_h = (_as_float(brief.get("nav_market_age_seconds")) or 0.0) / 3600.0
        stale = bool(brief.get("nav_stale"))

        sig = {
            "momentum_pct": momentum,
            "momentum_status": (ctx["momentum_status"] if momentum is not None
                                else "unavailable"),
            "supply_change_pct": supchg,
            "supply_status": (ctx["supply_status"] if supchg is not None
                              else "unavailable"),
            "float_usd": round(float_usd, 2) if float_usd is not None else None,
            "float_rank": (f"{rank} of {n}" if rank is not None else None),
            "median_float_usd": (round(ctx["median_float"], 2)
                                 if ctx["median_float"] is not None else None),
            "nav_stale": stale,
            "nav_market_age_h": round(market_age_h, 2),
            "score": None,
            "branch": None,
        }

        def done(view: str, weight: Optional[float], rationale: str,
                 branch: str) -> Analysis:
            sig["branch"] = branch
            self.signal_log[ticker] = sig
            return Analysis(view=view, target_weight_pct=weight,
                            rationale=rationale)

        # Rung 1: data-quality gate.
        if supply is None or supply <= 0:
            return done("AVOID", 0.0,
                        f"{ticker}: total supply missing or zero in API "
                        f"data (got {brief.get('total_supply')!r}); "
                        "data-quality gate — a token we cannot size is "
                        "not a position.",
                        "gate_supply")

        # Rung 2: stale-reference gate (NYSE-calendar policy).
        if stale:
            return done("HOLD", 0.0,
                        f"{ticker}: NAV reference {brief.get('nav_price')} "
                        f"has sat through {market_age_h:.1f}h of open-market "
                        "time, beyond the 4h nyse-calendar-v1 bound; no view "
                        "on a stale reference until the feed refreshes.",
                        "gate_stale")

        # Rung 3: negligible-float gate.
        med = ctx["median_float"]
        if (float_usd is not None and float_usd < FLOAT_AVOID_USD
                and med is not None and float_usd < FLOAT_AVOID_MEDIAN_SHARE * med):
            return done("AVOID", 0.0,
                        f"{ticker}: tokenized float is only "
                        f"${float_usd:,.0f} (supply {supply:,.0f} x NAV "
                        f"{brief.get('nav_price')}), {float_usd / med:.0%} of "
                        f"the universe median float ${med:,.0f} and ranked "
                        f"{rank} of {n}; the on-chain reference rests on a "
                        "negligible float — avoid until the float deepens.",
                        "gate_float")

        # Rung 4: directional score from live signals only.
        components: list[tuple[float, float, str]] = []  # (weight, value, text)
        if momentum is not None and ctx["momentum_status"] == "live":
            pct = ctx["momentum_percentile"].get(ticker)
            value = (0.6 * _clamp(momentum / MOMENTUM_FULL_PCT)
                     + 0.4 * (2.0 * pct - 1.0 if pct is not None else 0.0))
            components.append((W_MOMENTUM, value,
                               f"momentum {momentum:+.2f}% vs previous "
                               f"snapshot (relative-strength percentile "
                               f"{(pct or 0) * 100:.0f}%)"))
        if supchg is not None and ctx["supply_status"] == "live":
            components.append((W_SUPPLY, _clamp(supchg / SUPPLY_FULL_PCT),
                               f"total supply {supchg:+.2f}% vs previous "
                               "snapshot"))
        if components:
            total_w = sum(w for w, _, _ in components)
            score = sum(w * v for w, v, _ in components) / total_w
            sig["score"] = round(score, 4)
            parts = "; ".join(t for _, _, t in components)
            degraded = []
            if ctx["momentum_status"] != "live":
                degraded.append(f"momentum {ctx['momentum_status']}")
            if ctx["supply_status"] != "live":
                degraded.append(f"supply-change {ctx['supply_status']}")
            deg_txt = (f" Degraded this cycle: {', '.join(degraded)}."
                       if degraded else "")
            if score >= SCORE_BUY:
                return done("BUY", None,
                            f"{ticker}: directional score {score:+.2f} from "
                            f"{parts}; tokenized float ${float_usd:,.0f} "
                            f"(ranked {rank} of {n}), NAV fresh "
                            f"({market_age_h:.1f}h market age). "
                            f"Equal-weight BUY candidate.{deg_txt}",
                            "score")
            if score <= SCORE_AVOID:
                return done("AVOID", 0.0,
                            f"{ticker}: directional score {score:+.2f} from "
                            f"{parts}; weakest evidence in the universe — "
                            f"avoid this cycle.{deg_txt}",
                            "score")
            return done("HOLD", 0.0,
                        f"{ticker}: directional score {score:+.2f} from "
                        f"{parts} — inside the +/-{SCORE_BUY:.2f} neutral "
                        f"band; hold, no new exposure.{deg_txt}",
                        "score")

        # Rung 5: no directional evidence — float-depth posture, stated.
        why_no_dir = []
        why_no_dir.append(
            f"momentum {ctx['momentum_status']}"
            + (f" ({ctx['momentum_reason']})"
               if ctx["momentum_reason"] else ""))
        if ctx["supply_status"] != "live":
            why_no_dir.append(
                f"supply-change {ctx['supply_status']}"
                + (f" ({ctx['supply_reason']})"
                   if ctx["supply_reason"] else ""))
        no_dir = "; ".join(why_no_dir)
        if float_usd is not None and float_usd >= FLOAT_BUY_USD:
            return done("BUY", None,
                        f"{ticker}: no directional signal this cycle — "
                        f"{no_dir}. Posture rests on depth and freshness "
                        f"only: tokenized float ${float_usd:,.0f} (ranked "
                        f"{rank} of {n}, median ${med:,.0f}), NAV reference "
                        f"{brief.get('nav_price')} fresh at "
                        f"{market_age_h:.1f}h market age. Equal-weight BUY "
                        "candidate at low conviction until directional "
                        "signals come live.",
                        "fallback_depth")
        return done("HOLD", 0.0,
                    f"{ticker}: no directional signal this cycle — "
                    f"{no_dir}. Tokenized float ${float_usd:,.0f} is below "
                    f"the ${FLOAT_BUY_USD:,.0f} depth bar for an "
                    "equal-weight candidate (ranked "
                    f"{rank} of {n}); observe until the float deepens or "
                    "directional signals come live.",
                    "fallback_depth")
