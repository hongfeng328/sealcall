# 草稿 01 — 首条公开构建帖（build in public #1）

状态：**已发布**（2026-11-16 03:26 CST，Jason 本人在手机 X 应用内发布；助理公开页亲验：简介与正文与草稿逐字一致）。
帖子链接：https://x.com/niuxhq/status/2122048524259049819
账号：@niuxhq（显示名 Jason，简介已按定稿设置）。
正文为英文，长度已按 X 单帖 280 字符校验（见文末计数）。

---

Building SealCall in public for the @buildonbase Stocks Maxxing Season: an agent that researches tokenized stocks on Base and seals every call on-chain before revealing it — no edited track records. Data layer is live: 12 NAV-bearing tokenized stocks tracked.

---

备选第二帖（同日连发或次日用，同样 ≤280 字符）：

How it works: the agent reads Coinbase's Tokenized Stocks API, writes a brief per stock, and commits keccak256(decision + salt) to a CommitRegistry contract. At reveal time it publishes the decision; anyone can check the hash matches. Research only — it never trades.

---

字符计数（2026-11-16 实测，Python len，X 上限 280）：正文 259、备选帖 267，均达标。
