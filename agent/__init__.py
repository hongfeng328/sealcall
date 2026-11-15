"""SealCall agent engine (phase 2).

Generates research briefs and decision objects for the NAV-bearing
universe of the Coinbase Tokenized Stocks API, seals decisions with a
hash that is byte-compatible with contracts/CommitRegistry.sol, and
values a paper portfolio at NAV. No real model key is wired in: the
analyst is a documented rule-based placeholder behind an interface
(see analyst.py / llm.py).
"""
