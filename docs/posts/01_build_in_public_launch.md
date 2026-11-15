# 草稿 01 — 首条公开构建帖（build in public #1）

状态：**草稿，未发布**。发布须 Jason 点头（PLAN.md §5 卡点 4）。
拟用账号：新建项目专用 X 号（PLAN.md §5 卡点 2）。
正文为英文，长度已按 X 单帖 280 字符校验（见文末计数）。

---

Building SealCall in public for the @buildonbase Stocks Maxxing Season: an agent that researches tokenized stocks on Base and seals every call on-chain before revealing it — no edited track records. Data layer is live: 12 NAV-bearing tokenized stocks tracked.

---

备选第二帖（同日连发或次日用，同样 ≤280 字符）：

How it works: the agent reads Coinbase's Tokenized Stocks API, writes a brief per stock, and commits keccak256(decision + salt) to a CommitRegistry contract. At reveal time it publishes the decision; anyone can check the hash matches. Research only — it never trades.

---

字符计数（2026-11-16 实测，Python len，X 上限 280）：正文 259、备选帖 267，均达标。
