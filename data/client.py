"""Client for the Base (Coinbase) Tokenized Stocks public API.

Source of truth for endpoints and field semantics:
https://docs.base.org/sdks/tokenized-stocks/overview

- Read-only, no API key required.
- Base URL (taken from the cURL examples in the official API reference,
  verified live 2026-11-16): https://api.coinbase.com/v1/tokenized-stocks
- The API omits default-valued fields, empty arrays and unset timestamps.
  In particular a token record may carry no NAV data at all; per the docs,
  missing NAV data must NOT be treated as a usable price. This client
  surfaces that as ``nav_price is None`` and ``NavQuote.present == False``.
- ``nav_price`` is a Chainlink-based NAV/reference value, not a live
  bid/ask. Feeds update only on price deviation or heartbeat and hold
  their last value outside market hours, so always check
  ``nav_price_updated_at`` against a staleness bound before using it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

import requests

BASE_URL = os.environ.get(
    "TOKENIZED_STOCKS_BASE_URL", "https://api.coinbase.com/v1/tokenized-stocks"
)

# Default staleness bound for NAV quotes: 24h. NAV feeds heartbeat at most
# daily and freeze outside market hours (weekends included), so anything
# tighter would flag every quote on a Sunday. Callers that need fresher
# data (e.g. during US market hours) should pass a smaller bound.
DEFAULT_NAV_MAX_AGE_SECONDS = 24 * 3600

DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_PAGE_SIZE = 500  # values above 500 are capped by the API


class TokenizedStocksError(RuntimeError):
    """Raised on any non-2xx API response or malformed payload."""

    def __init__(self, message: str, http_status: Optional[int] = None,
                 api_code: Optional[int] = None):
        super().__init__(message)
        self.http_status = http_status
        self.api_code = api_code


def _parse_iso8601(value: str) -> datetime:
    """Parse an ISO-8601 timestamp into an aware UTC datetime."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class TokenRecord:
    """One tokenized-stock record as returned by the list endpoint."""

    contract_address: str
    symbol: str
    name: str
    decimals: Optional[int] = None
    isin: Optional[str] = None
    adgm_isin: Optional[str] = None
    multiplier: Optional[float] = None
    total_supply: Optional[str] = None
    nav_price: Optional[str] = None
    nav_price_updated_at: Optional[str] = None
    first_mint_date: Optional[str] = None
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, payload: dict) -> "TokenRecord":
        return cls(
            contract_address=payload.get("contract_address", ""),
            symbol=payload.get("symbol", ""),
            name=payload.get("name", ""),
            decimals=payload.get("decimals"),
            isin=payload.get("isin"),
            adgm_isin=payload.get("adgm_isin"),
            multiplier=payload.get("multiplier"),
            total_supply=payload.get("total_supply"),
            nav_price=payload.get("nav_price"),
            nav_price_updated_at=payload.get("nav_price_updated_at"),
            first_mint_date=payload.get("first_mint_date"),
            raw=payload,
        )


@dataclass
class NavQuote:
    """A NAV/reference quote plus its freshness verdict."""

    symbol: str
    present: bool                       # False => API carried no NAV data
    nav_price: Optional[str] = None     # string, exactly as the API sent it
    updated_at: Optional[datetime] = None
    age_seconds: Optional[float] = None
    max_age_seconds: float = DEFAULT_NAV_MAX_AGE_SECONDS
    is_fresh: bool = False              # present AND age <= max_age_seconds


class TokenizedStocksClient:
    """Thin, dependency-light wrapper over the Tokenized Stocks API."""

    def __init__(self, base_url: str = BASE_URL,
                 timeout: float = DEFAULT_TIMEOUT_SECONDS,
                 session: Optional[requests.Session] = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    # -- low level ------------------------------------------------------

    def _get_json(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        resp = None
        last_exc: Optional[Exception] = None
        # One retry on transport errors / 503 (the API's "data temporarily
        # unavailable" code): the list payload is large and slow to arrive.
        for attempt in range(2):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                last_exc = None
                if resp.status_code != 503:
                    break
            except requests.RequestException as exc:
                last_exc = exc
            if attempt == 0:
                import time
                time.sleep(1.0)
        if resp is None:
            raise TokenizedStocksError(f"GET {url} failed: {last_exc}") from last_exc
        if resp.status_code != 200:
            api_code, message = None, resp.text[:200]
            try:
                body = resp.json()
                api_code = body.get("code")
                message = body.get("message", message)
            except ValueError:
                pass
            raise TokenizedStocksError(
                f"GET {url} -> HTTP {resp.status_code}: {message}",
                http_status=resp.status_code, api_code=api_code,
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise TokenizedStocksError(f"GET {url}: response is not JSON") from exc

    # -- endpoints ------------------------------------------------------

    def list_token_page(self, page_size: int = 100,
                        page_token: Optional[str] = None) -> tuple[list[TokenRecord], Optional[str]]:
        """Fetch one page of the token list. Returns (records, next_page_token)."""
        if page_size < 0:
            raise ValueError("page_size must be >= 0")
        params: dict[str, Any] = {"page_size": min(page_size, MAX_PAGE_SIZE)}
        if page_token:
            params["page_token"] = page_token
        # The list endpoint IS the base URL itself; a trailing slash 404s.
        body = self._get_json("", params=params)
        records = [TokenRecord.from_json(t) for t in body.get("tokens", [])]
        return records, body.get("next_page_token") or None

    def iter_all_tokens(self, page_size: int = 100) -> Iterator[TokenRecord]:
        """Yield every token record, following next_page_token to the end."""
        page_token: Optional[str] = None
        while True:
            records, page_token = self.list_token_page(page_size, page_token)
            yield from records
            if not page_token:
                return

    def list_all_tokens(self, page_size: int = 100) -> list[TokenRecord]:
        return list(self.iter_all_tokens(page_size=page_size))

    def get_metadata(self, ticker: str) -> dict:
        """GET /metadata/{ticker} — raw metadata dict for one ticker."""
        return self._get_json(f"/metadata/{ticker}")

    def get_total_supply(self, contract_address: str) -> Any:
        """GET /total-supply/{contract_address} — normalized token supply.

        Note: this endpoint returns a bare JSON number, not an object.
        """
        return self._get_json(f"/total-supply/{contract_address}")

    def get_corporate_action(self, action_id: str) -> dict:
        """GET /corporate-actions/{id} — one corporate action by UUID."""
        return self._get_json(f"/corporate-actions/{action_id}")

    def list_chains(self) -> dict:
        """GET /chains — protocol contract addresses per chain."""
        return self._get_json("/chains")

    # -- NAV ------------------------------------------------------------

    def get_nav(self, record: TokenRecord,
                max_age_seconds: float = DEFAULT_NAV_MAX_AGE_SECONDS,
                now: Optional[datetime] = None) -> NavQuote:
        """Build a NavQuote from a token record, with a staleness verdict.

        ``is_fresh`` is True only when NAV data is present and its
        ``nav_price_updated_at`` is no older than ``max_age_seconds``.
        """
        now = now or datetime.now(timezone.utc)
        if record.nav_price is None or not record.nav_price_updated_at:
            return NavQuote(symbol=record.symbol, present=False,
                            max_age_seconds=max_age_seconds)
        updated_at = _parse_iso8601(record.nav_price_updated_at)
        age = (now - updated_at).total_seconds()
        return NavQuote(
            symbol=record.symbol,
            present=True,
            nav_price=record.nav_price,
            updated_at=updated_at,
            age_seconds=age,
            max_age_seconds=max_age_seconds,
            is_fresh=age <= max_age_seconds,
        )

    def find_token(self, tokens: list[TokenRecord], ticker: str) -> Optional[TokenRecord]:
        """Exact symbol match (API symbols look like 'TSLAc', 'RKTc')."""
        for token in tokens:
            if token.symbol == ticker:
                return token
        return None
