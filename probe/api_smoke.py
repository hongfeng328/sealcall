#!/usr/bin/env python3
"""Live smoke probe for the Tokenized Stocks API client.

Makes REAL calls to the public API and writes the measured results to
probe/api_smoke.json next to this script:

- total number of tokenized-stock records (full paginated list)
- how many records carry NAV data at all
- for 3 sample tickers: NAV price, NAV update timestamp, NAV age,
  freshness verdict under the configured staleness threshold,
  a /metadata/{ticker} round-trip, and /total-supply/{address}

Sample selection is deterministic: well-known underlyings first
(TSLA, NVDA, AAPL, GOOGL, MSFT, AMZN, META), then the first records
(by symbol order) that carry NAV data. If fewer than 3 records carry
NAV, records without NAV are included and marked nav.present=false —
nothing is invented.

Usage:  python3 probe/api_smoke.py [--max-age-seconds N]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.client import (  # noqa: E402
    BASE_URL,
    DEFAULT_NAV_MAX_AGE_SECONDS,
    TokenizedStocksClient,
)

PREFERRED_UNDERLYINGS = ["TSLA", "NVDA", "AAPL", "GOOGL", "MSFT", "AMZN", "META"]
OUT_PATH = Path(__file__).resolve().parent / "api_smoke.json"


def pick_samples(tokens, count=3):
    with_nav = [t for t in tokens if t.nav_price is not None]
    by_symbol = {t.symbol: t for t in with_nav}
    picked, seen = [], set()
    for underlying in PREFERRED_UNDERLYINGS:
        for symbol, token in sorted(by_symbol.items()):
            if symbol.upper().startswith(underlying) and symbol not in seen:
                picked.append(token)
                seen.add(symbol)
                break
        if len(picked) >= count:
            return picked
    for token in sorted(with_nav, key=lambda t: t.symbol):
        if len(picked) >= count:
            break
        if token.symbol not in seen:
            picked.append(token)
            seen.add(token.symbol)
    if len(picked) < count:  # not enough NAV-carrying records: pad honestly
        for token in sorted(tokens, key=lambda t: t.symbol):
            if len(picked) >= count:
                break
            if token.symbol not in seen:
                picked.append(token)
                seen.add(token.symbol)
    return picked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-age-seconds", type=float,
                        default=DEFAULT_NAV_MAX_AGE_SECONDS)
    args = parser.parse_args()

    client = TokenizedStocksClient()
    fetched_at = datetime.now(timezone.utc)

    pages = 0
    tokens = []
    page_token = None
    while True:
        records, page_token = client.list_token_page(page_size=100,
                                                     page_token=page_token)
        pages += 1
        tokens.extend(records)
        if not page_token:
            break

    samples = []
    for token in pick_samples(tokens):
        quote = client.get_nav(token, max_age_seconds=args.max_age_seconds,
                               now=fetched_at)
        metadata = client.get_metadata(token.symbol)
        supply = client.get_total_supply(token.contract_address)
        samples.append({
            "symbol": token.symbol,
            "name": token.name,
            "contract_address": token.contract_address,
            "nav": {
                "present": quote.present,
                "nav_price": quote.nav_price,
                "nav_price_updated_at": token.nav_price_updated_at,
                "age_seconds": (round(quote.age_seconds, 1)
                                if quote.age_seconds is not None else None),
                "is_fresh": quote.is_fresh,
            },
            "metadata_ok": metadata.get("symbol") == token.symbol,
            "total_supply_response": supply,
        })

    result = {
        "probe": "tokenized-stocks-api-smoke",
        "fetched_at_utc": fetched_at.isoformat(),
        "base_url": BASE_URL,
        "staleness_threshold_seconds": args.max_age_seconds,
        "total_tokens": len(tokens),
        "pages_fetched": pages,
        "tokens_with_nav": sum(1 for t in tokens if t.nav_price is not None),
        "samples": samples,
    }
    OUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"total_tokens={result['total_tokens']} pages={pages} "
          f"tokens_with_nav={result['tokens_with_nav']}")
    for s in samples:
        nav = s["nav"]
        print(f"{s['symbol']}: nav_price={nav['nav_price']} "
              f"updated_at={nav['nav_price_updated_at']} "
              f"age_s={nav['age_seconds']} fresh={nav['is_fresh']} "
              f"metadata_ok={s['metadata_ok']}")
    print(f"wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
