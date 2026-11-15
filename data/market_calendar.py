"""NYSE trading-calendar-aware NAV freshness (phase 3).

Why this exists: the Tokenized Stocks NAV feed is a Chainlink reference
value that updates on price deviation / heartbeat while the US market is
open and *freezes* when the market is closed. A fixed wall-clock
staleness bound (24h in the phase-1 client, 96h in the phase-2 engine)
cannot express that: it flags every quote on a Sunday, yet waves through
a days-old quote on a Wednesday afternoon.

Policy (``nyse-calendar-v1``): measure a quote's age in *market-open
seconds* — the amount of time the NYSE was actually open between the
quote's ``updated_at`` and ``now``. Closed-market time (nights,
weekends, holidays) contributes zero age, so a quote frozen at Friday's
close is still fresh on Sunday; once the market reopens, age accrues in
real time and a quote older than ``MAX_MARKET_AGE_SECONDS`` of open
market time is stale.

Calendar data: NYSE 2026 full-day holidays and scheduled early closes
(13:00 ET), per the exchange's published 2026 calendar. Regular hours
09:30–16:00 America/New_York. Only 2026 is encoded; dates outside 2026
raise ``ValueError`` rather than silently guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)

# Freshness bound, in seconds of *market-open* time. A quote may lag up
# to 4 open-market hours (heartbeat tolerance inside a session); a quote
# that has sat through more than that of live trading is stale.
MAX_MARKET_AGE_SECONDS = 4 * 3600

# NYSE 2026 full-day holidays (exchange closed).
NYSE_HOLIDAYS_2026: frozenset[date] = frozenset({
    date(2026, 1, 1),    # New Year's Day
    date(2026, 1, 19),   # Martin Luther King, Jr. Day
    date(2026, 2, 16),   # Washington's Birthday
    date(2026, 4, 3),    # Good Friday
    date(2026, 5, 25),   # Memorial Day
    date(2026, 6, 19),   # Juneteenth National Independence Day
    date(2026, 7, 3),    # Independence Day (observed; Jul 4 is a Saturday)
    date(2026, 9, 7),    # Labor Day
    date(2026, 11, 26),  # Thanksgiving Day
    date(2026, 12, 25),  # Christmas Day
})

# NYSE 2026 scheduled early closes (13:00 ET).
NYSE_EARLY_CLOSES_2026: frozenset[date] = frozenset({
    date(2026, 11, 27),  # day after Thanksgiving
    date(2026, 12, 24),  # Christmas Eve
})

_HOLIDAYS = {2026: NYSE_HOLIDAYS_2026}
_EARLY_CLOSES = {2026: NYSE_EARLY_CLOSES_2026}


def _check_year(d: date) -> None:
    if d.year not in _HOLIDAYS:
        raise ValueError(
            f"NYSE calendar only encoded for {sorted(_HOLIDAYS)}; "
            f"got {d.isoformat()}")


def is_trading_day(d: date) -> bool:
    """True if NYSE holds a session (full or early-close) on date ``d``."""
    _check_year(d)
    if d.weekday() >= 5:  # Saturday / Sunday
        return False
    return d not in _HOLIDAYS[d.year]


def session_bounds(d: date) -> Optional[tuple[datetime, datetime]]:
    """(open, close) as aware ET datetimes for date ``d``, or None if closed."""
    if not is_trading_day(d):
        return None
    close_t = EARLY_CLOSE if d in _EARLY_CLOSES[d.year] else MARKET_CLOSE
    return (datetime.combine(d, MARKET_OPEN, tzinfo=ET),
            datetime.combine(d, close_t, tzinfo=ET))


def market_open_seconds(start: datetime, end: datetime) -> float:
    """Seconds of NYSE-open time inside [start, end] (aware datetimes).

    Iterates calendar days in ET; spans here are days-to-weeks, so the
    day loop is cheap and exact (DST handled by zoneinfo).
    """
    if end <= start:
        return 0.0
    start_et = start.astimezone(ET)
    end_et = end.astimezone(ET)
    total = 0.0
    day = start_et.date()
    last_day = end_et.date()
    one_day = timedelta(days=1)
    while day <= last_day:
        bounds = session_bounds(day)
        if bounds is not None:
            open_dt, close_dt = bounds
            lo = max(start_et, open_dt)
            hi = min(end_et, close_dt)
            if hi > lo:
                total += (hi - lo).total_seconds()
        day += one_day
    return total


@dataclass
class NavFreshness:
    """Calendar-aware freshness verdict for one NAV quote."""

    is_fresh: bool
    market_age_seconds: float          # age counted in market-open seconds
    wall_age_seconds: float            # plain wall-clock age, for reporting
    max_market_age_seconds: float
    policy: str = "nyse-calendar-v1"


def nav_freshness(updated_at: datetime, now: datetime,
                  max_market_age_seconds: float = MAX_MARKET_AGE_SECONDS
                  ) -> NavFreshness:
    """Verdict for a quote stamped ``updated_at`` evaluated at ``now``.

    Fresh iff the market-open time elapsed since the quote was published
    is within ``max_market_age_seconds``. While the market is closed the
    market-age does not grow, so a quote frozen at the last close stays
    fresh through weekends and holidays.
    """
    if updated_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("updated_at and now must be timezone-aware")
    updated_at = updated_at.astimezone(timezone.utc)
    now = now.astimezone(timezone.utc)
    wall_age = max(0.0, (now - updated_at).total_seconds())
    m_age = market_open_seconds(updated_at, now)
    return NavFreshness(
        is_fresh=m_age <= max_market_age_seconds,
        market_age_seconds=m_age,
        wall_age_seconds=wall_age,
        max_market_age_seconds=max_market_age_seconds,
    )
