# SealCall

决策全程上链封存、可验证战绩的代币化股票研究 agent。
参赛：Base Builder Quest — Stocks Maxxing Season，Agentic Stock Finance 赛道。
总方案见上级目录 `../PLAN.md`；本仓含一期骨架（数据层 + 合约骨架）与
二期成果（agent 引擎 + 本地链端到端自测 + Web 看板骨架）。

## 它做什么

Agent 对 Coinbase 在 Base 上发行的代币化股票做研究并给出决策（观点/目标配置）。
每个决策在公布前先把哈希上链封存（CommitRegistry），到期揭示原文，任何人可验证
「决策确实在揭示前就已定下、未被事后修改」；业绩用官方参考价（NAV）从链上
数据计算。用户可跟随某个 agent（FollowRegistry），跟随动作本身是零资金、
非托管的链上记录。不托管资金、不执行交易——见 PLAN.md §2 的合规口径。

## 架构

```
sealcall/
├── data/                  # 数据层（PLAN.md §2 功能 1）
│   └── client.py          # Tokenized Stocks API 客户端 + NAV 时效检查
├── contracts/             # 链上注册表（PLAN.md §2 功能 3）
│   ├── CommitRegistry.sol # 决策封存 commit / 揭示 reveal
│   ├── FollowRegistry.sol # follow / unfollow + 计数
│   └── BUILD_STATUS.md    # 编译器版本、命令、产物、未部署声明
├── agent/                 # Agent 引擎（功能 2，二期）
│   ├── briefs.py          # 动态宇宙（带 NAV 的代币）+ 结构化研究简报
│   ├── analyst.py         # Analyst 接口 + 规则版占位实现（rules-v0）
│   ├── llm.py             # LLM 接口与未配置桩（未接真实模型 key）
│   ├── decisions.py       # 决策对象 + keccak 封存哈希（与合约兼容）
│   ├── portfolio.py       # 纸面组合按 NAV 计值（功能 4 的本地形态）
│   ├── engine.py / run.py # 周期编排与 CLI；产出 JSON 在 agent/out/
│   └── requirements.txt
├── web/                   # Web 看板骨架（功能 5，二期）：index.html/app.js/style.css
├── probe/
│   ├── api_smoke.py       # 真实调用 API 的冒烟探针
│   ├── api_smoke.json     # 探针实测输出（真实数据，非手写）
│   ├── phase2_e2e.py      # 二期端到端自测（本地 eth-tester 链）
│   └── phase2_e2e.json    # 自测实测日志（verdict=PASS，见下）
└── .venv/                 # 项目 venv（web3/eth-tester 等，不入库）
```

后续阶段：测试网部署与演示组合上链（功能 3/4 的部署部分）、公开构建与
提交包（功能 6/7）。**合约仍未部署到任何外部网络**（二期自测只用本地模拟链）。

## 与 PLAN.md §2 v1 功能清单的对应

| PLAN 功能 | 本仓对应 | 状态 |
|---|---|---|
| 1. 数据层：API 接入 + NAV 时效检查 | `data/client.py` | ✅ 骨架完成，smoke 实测通过 |
| 2. Agent 引擎（简报/决策对象/封存揭示流程） | `agent/` | ✅ 二期完成：动态宇宙、结构化简报、规则版决策、keccak 封存哈希与合约对齐；封存/揭示已在本地链实测 |
| 3. 合约 CommitRegistry + FollowRegistry | `contracts/*.sol` | ✅ 骨架完成，solc 0.8.28 编译通过，**未部署到任何外部网络**（仅本地模拟链部署过） |
| 4. 演示组合（测试网纸面组合） | `agent/portfolio.py` | ◐ 本地形态完成：纸面组合按 NAV 计值 + 净值历史快照；测试网部署未做（属部署步骤） |
| 5. Web 看板 | `web/` | ✅ 二期骨架完成：覆盖清单/封存决策时间线/纸面净值三区块，渲染真实运行 JSON |
| 6. 公开构建（仓库公开/X 帖） | — | 未开始（发帖须 Jason 逐批点头） |
| 7. 提交包 | — | 未开始 |

## 数据层用法

官方文档：https://docs.base.org/sdks/tokenized-stocks/overview
Base URL（取自官方 API reference 的 cURL 示例，并已实测）：
`https://api.coinbase.com/v1/tokenized-stocks`（只读、免 key；
可用环境变量 `TOKENIZED_STOCKS_BASE_URL` 覆盖）。

```python
from data.client import TokenizedStocksClient

client = TokenizedStocksClient()
tokens = client.list_all_tokens()            # 自动分页拉全量清单
token = client.find_token(tokens, "TSLAc")
quote = client.get_nav(token)                # NAV + 时效判定
if quote.present and quote.is_fresh:
    ...  # 只有新鲜 NAV 才可用于计值；缺失/过期一律不用（官方文档口径）
meta = client.get_metadata("TSLAc")          # /metadata/{ticker}
supply = client.get_total_supply(token.contract_address)  # 返回裸数字
```

NAV 时效：`nav_price` 是 Chainlink 参考值而非实时报价，源 feed 只在价格
偏离或心跳时更新、非交易时段冻结。默认过期阈值 24h（`DEFAULT_NAV_MAX_AGE_SECONDS`，
可配）。注意：周末跑 smoke 时 NAV 时间戳停在周五收盘后，`is_fresh=false`
是正确判定而非故障；生产环境应换成与美股交易日历对齐的阈值策略。

实测基线（2026-11-16 00:23 CST 探针运行）：全量 358 只代币、4 页拉完、
仅 12 只带 NAV 数据；样例 TSLAc NAV 387.793、NVDAc 160.76543559、
AAPLc 355.585，更新时间均为 2026-11-13（周五）晚间。详见 `probe/api_smoke.json`。

## 如何跑 smoke

```bash
cd sealcall
python3 probe/api_smoke.py                 # 真实调用官方 API，结果写入 probe/api_smoke.json
python3 probe/api_smoke.py --max-age-seconds 3600   # 自定义 NAV 时效阈值
```

依赖：Python 3.12 + `requests`（系统已装）。

## 二期：引擎、自测与看板

环境（项目 venv，依赖见 `agent/requirements.txt`）：

```bash
cd sealcall
python3 -m venv .venv && .venv/bin/pip install -r agent/requirements.txt
```

跑一轮引擎周期（真实调用 API，产出 `agent/out/` 下的 briefs/decisions/
portfolio 等 JSON）：

```bash
.venv/bin/python -m agent.run
```

链下端到端自测（本地 eth-tester 模拟链，部署两合约并跑通
封存→到期揭示校验→follow/unfollow 计数；实测日志写 `probe/phase2_e2e.json`）：

```bash
.venv/bin/python probe/phase2_e2e.py --commit-count 3
```

2026-11-16 实测：verdict=PASS。宇宙 12 只（实时 API）；3 笔决策封存上链，
过早揭示被合约 RevealTooEarly 正确拒绝，时间旅行到揭示时间后 3 笔全部
揭示成功且链上 decisionHash 与 Python 计算的 keccak256(payload) 逐一一致；
follow 计数 1→2→unfollow→1。决策哈希方案：keccak256( canonical JSON
payload ‖ 32 字节 salt )，与 `CommitRegistry.reveal` 的
`keccak256(abi.encodePacked(decision, salt))` 字节级兼容（见
`agent/decisions.py` 文件头）。

看板（纯静态，从仓库根目录起服务器）：

```bash
python3 -m http.server 8000   # 在 sealcall/ 目录下
# 浏览器打开 http://localhost:8000/web/
```

分析师说明：当前是规则版占位（`agent/analyst.py` 的 rules-v0：供给数据
质量门 → 7 天硬过期 → 动量 -5% 地板 → 等权 BUY），LLM 只留接口
（`agent/llm.py`），未接任何真实模型 key。NAV 时效：引擎阈值暂用 96h
（容纳周末冻结），简报中逐只报告真实年龄；交易日历对齐的阈值策略未做。

## 合约

```bash
cd contracts
npx -y solc@0.8.28 --bin --abi --optimize -o out CommitRegistry.sol FollowRegistry.sol
```

编译状态与产物大小见 `contracts/BUILD_STATUS.md`。**两合约均未部署到任何网络**；
部署（先 Base Sepolia、后主网）是 PLAN 时间表里后续单独批准的步骤。
