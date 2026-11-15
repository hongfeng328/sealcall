// SealCall dashboard (phase 2 skeleton). Renders only real run outputs:
//   ../probe/phase2_e2e.json      — engine cycle + local-chain e2e results
//   ../agent/out/decisions.json   — full decision set of the latest CLI cycle
//   ../agent/out/portfolio_history.json — paper-portfolio NAV snapshots
// Serve from the sealcall/ repo root, e.g.:
//   python3 -m http.server 8000   then open http://localhost:8000/web/

const short = (h) => (h && h.length > 14 ? h.slice(0, 10) + "…" + h.slice(-4) : h);
const ts = (unix) => new Date(unix * 1000).toISOString().replace("T", " ").slice(0, 19) + " UTC";
const rows = (tbody, cellsList) => {
  tbody.innerHTML = cellsList
    .map((cells) => "<tr>" + cells.map((c) => `<td>${c}</td>`).join("") + "</tr>")
    .join("");
};

async function renderSepolia() {
  const el = document.getElementById("sepolia");
  try {
    const d = await fetch("../probe/sepolia_deploy.json").then((r) => r.json());
    const addrLink =
      `<a href="${d.explorer}/address/${d.deployer_address}">${d.deployer_address}</a>`;
    if (d.status === "DEPLOYED" && d.contracts) {
      const c = Object.entries(d.contracts)
        .map(([name, v]) =>
          `${name}: <a href="${v.explorer_url}">${v.address}</a>（部署 tx <a href="${v.deploy_tx_url}">${short(v.deploy_tx)}</a>）`)
        .join("<br>");
      el.innerHTML =
        `状态 DEPLOYED · 网络 ${d.network}（chain ${d.chain_id}）· 部署钱包 ${addrLink}<br>${c}<br>` +
        `真实 commit：#${d.commit.commitment_id} ${d.commit.ticker} ` +
        `<a href="${d.commit.explorer_url}">${short(d.commit.tx_hash)}</a>`;
    } else {
      el.innerHTML =
        `状态 ${d.status} · 网络 ${d.network}（chain ${d.chain_id}）· 项目部署钱包 ${addrLink} · ` +
        `余额 ${d.deployer_balance_eth} ETH<br>原因：${d.blocked_reason}<br>` +
        `解阻办法：${(d.unblock_options || []).join("；")}`;
    }
  } catch (e) {
    el.textContent = "probe/sepolia_deploy.json 未找到（部署探针尚未运行）。";
  }
}

async function main() {
  renderSepolia();
  const [e2e, decisions, pfHistory] = await Promise.all([
    fetch("../probe/phase2_e2e.json").then((r) => r.json()),
    fetch("../agent/out/decisions.json").then((r) => r.json()),
    fetch("../agent/out/portfolio_history.json").then((r) => r.json()),
  ]);

  document.getElementById("meta").textContent =
    `自测结论 ${e2e.verdict} · 网络：${e2e.network} · ` +
    `CommitRegistry ${e2e.contracts.CommitRegistry} · FollowRegistry ${e2e.contracts.FollowRegistry} · ` +
    `自测时间 ${e2e.started_at_utc}`;

  // 1. coverage universe
  rows(document.querySelector("#universe tbody"), e2e.briefs.map((b) => [
    b.ticker, b.name, b.nav_price, b.nav_updated_at,
    (b.nav_age_seconds / 3600).toFixed(1),
    b.nav_stale ? '<span class="bad">是</span>' : '<span class="ok">否</span>',
    b.total_supply,
    b.corporate_actions.length ? b.corporate_actions.map((a) => a.type).join(", ") : "—",
  ]));

  // 2a. on-chain sealed + revealed decisions
  rows(document.querySelector("#onchain tbody"), e2e.decisions_onchain.map((d) => [
    d.commitment_id, d.ticker, d.view, d.target_weight_pct,
    short(d.commit_tx), ts(d.reveal_at), short(d.reveal_tx),
    d.onchain_revealed ? '<span class="ok">是</span>' : '<span class="bad">否</span>',
    d.hash_match ? '<span class="ok">一致</span>' : '<span class="bad">不一致</span>',
  ]));
  const ff = e2e.follow_flow.map(
    (f) => `${f.action}(${short(f.follower)}) → 粉丝数 ${f.follower_count_after}`
  ).join(" · ");
  document.getElementById("follow").textContent =
    `FollowRegistry 实测：${ff} · 最终粉丝数 ${e2e.final_follower_count}`;

  // 2b. all decisions of the latest engine cycle (hash-sealed, not yet on-chain)
  rows(document.querySelector("#pending tbody"), decisions.map((d) => [
    d.ticker, d.view, d.target_weight_pct, short(d.commitment_hash), ts(d.reveal_at),
  ]));

  // 3. paper portfolio
  const pf = e2e.portfolio;
  document.getElementById("pf-meta").textContent =
    `起始纸面资金 $${pf.start_cash_usd} · 已投 $${pf.invested_usd} · 现金 $${pf.cash_usd} · ` +
    `总净值 $${pf.total_value_usd} · 计值时间 ${pf.valued_at}（${pf.note}）`;
  rows(document.querySelector("#portfolio tbody"), pf.holdings.map((h) => [
    h.ticker, h.weight_pct, h.nav_price, h.units, h.value_usd,
  ]));

  // NAV history snapshots
  const hist = document.getElementById("pf-history");
  if (pfHistory.length) {
    const pts = pfHistory.map((s) => `${s.valued_at}: $${s.total_value_usd}`).join("<br>");
    hist.innerHTML = `<p class="sub">${pfHistory.length} 个快照</p><p>${pts}</p>`;
  } else {
    hist.textContent = "暂无历史快照。";
  }
}

main().catch((e) => {
  document.getElementById("meta").textContent =
    "数据加载失败（请从 sealcall/ 仓库根目录起静态服务器后打开 /web/）：" + e;
});
