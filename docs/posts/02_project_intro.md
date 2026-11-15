# 草稿 02 — 项目介绍帖（串帖）

状态：**草稿，未发布**。发布须 Jason 点头（PLAN.md §5 卡点 4）。
用途：置顶帖 / 项目号首串介绍。每帖 ≤280 字符（见文末计数）。

---

**1/**

Meet SealCall — a research agent for tokenized stocks on Base. It studies the stocks, forms a view, and seals that view on-chain before revealing it, so its track record is verifiable by anyone and cannot be edited after the fact.

**2/**

The problem it addresses: AI "stock pickers" can quietly rewrite their history. SealCall can't. Every decision is committed as keccak256(decision + salt) to a public registry first; the reveal only counts if the hash matches what was sealed earlier.

**3/**

Inputs are public data only: Coinbase's Tokenized Stocks API (reference NAV, supply, corporate actions), checked against the NYSE calendar so a quote frozen over a weekend is not mistaken for a fresh one. When a signal carries no information, the agent says so.

**4/**

What SealCall is not: it does not trade, does not hold funds, and does not promise returns. It is a paper-portfolio research log with an on-chain audit trail, built for the @buildonbase Stocks Maxxing Season, Agentic Stock Finance track.

---

字符计数（2026-11-16 实测，Python len，X 上限 280）：四帖分别为 230 / 249 / 261 / 237，均达标。
