"""One-click daily cycle: fetch -> briefs/decisions -> local commit
-> portfolio history, for N rounds (default 2).

Each round runs the real engine cycle against the live Tokenized
Stocks API (agent/engine.py), then seals every decision on a LOCAL
eth-tester (py-evm) chain via CommitRegistry — never an external
network — and records what actually happened (decision count, commit
count and failures, paper-portfolio totals before/after) into
probe/cycle_log.json. The chain is created once and shared across
rounds, so round 2's commitments continue round 1's registry.

Usage (from sealcall/ root):
    .venv/bin/python -m agent.cycle [--rounds 2]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eth_tester import EthereumTester  # noqa: E402
from web3 import Web3  # noqa: E402
from web3.providers.eth_tester import EthereumTesterProvider  # noqa: E402

from .engine import DEFAULT_OUT_DIR, run_cycle  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
LOG_PATH = os.path.join(ROOT, "probe", "cycle_log.json")
REVEAL_DELAY_SECONDS = 3600


def _load_artifact(name: str):
    out_dir = os.path.join(ROOT, "contracts", "out")
    with open(os.path.join(out_dir, f"{name}_sol_{name}.abi"),
              "r", encoding="utf-8") as fh:
        abi = json.load(fh)
    with open(os.path.join(out_dir, f"{name}_sol_{name}.bin"),
              "r", encoding="utf-8") as fh:
        bytecode = fh.read().strip()
    return abi, bytecode


def _portfolio_state(out_dir: str) -> dict:
    path = os.path.join(out_dir, "portfolio_history.json")
    if not os.path.exists(path):
        return {"snapshots": 0, "last_total_usd": None, "totals": []}
    with open(path, "r", encoding="utf-8") as fh:
        snaps = json.load(fh)
    return {
        "snapshots": len(snaps),
        "last_total_usd": snaps[-1]["total_value_usd"] if snaps else None,
        "totals": [s["total_value_usd"] for s in snaps],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SealCall daily cycles")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    log: dict = {
        "probe": "sealcall-daily-cycle",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "network": "local eth-tester (py-evm) in-process chain — NOT an external network",
        "rounds": [],
        "errors": [],
    }

    tester = EthereumTester()
    w3 = Web3(EthereumTesterProvider(tester))
    agent_acct = w3.eth.accounts[0]
    abi, bytecode = _load_artifact("CommitRegistry")
    factory = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx = factory.constructor().transact({"from": agent_acct})
    receipt = w3.eth.wait_for_transaction_receipt(tx)
    registry = w3.eth.contract(address=receipt.contractAddress, abi=abi)
    log["commit_registry"] = {
        "address": receipt.contractAddress,
        "deploy_tx": tx.hex(),
        "deploy_block": receipt.blockNumber,
        "agent_account": agent_acct,
    }
    print(f"[cycle] CommitRegistry (local) at {receipt.contractAddress}")

    for rnd in range(1, args.rounds + 1):
        before = _portfolio_state(args.out_dir)
        entry: dict = {"round": rnd,
                       "started_at_utc": datetime.now(timezone.utc).isoformat()}
        result = run_cycle(out_dir=args.out_dir,
                           reveal_delay_seconds=REVEAL_DELAY_SECONDS)
        cycle = result["cycle"]
        decisions = result["decisions"]
        entry["engine"] = {
            "generated_at": cycle["generated_at"],
            "analyst": cycle["analyst"],
            "universe_size": cycle["universe_size"],
            "views": cycle["views"],
        }
        entry["decisions"] = len(decisions)

        commits, failures = 0, []
        for d in decisions:
            try:
                tx = registry.functions.commit(
                    bytes.fromhex(d["commitment_hash"][2:]), d["reveal_at"]
                ).transact({"from": agent_acct})
                rcpt = w3.eth.wait_for_transaction_receipt(tx)
                if rcpt.status == 1:
                    commits += 1
                else:
                    failures.append({"ticker": d["ticker"],
                                     "error": f"tx status {rcpt.status}"})
            except Exception as exc:  # record, never swallow silently
                failures.append({"ticker": d["ticker"],
                                 "error": f"{type(exc).__name__}: {exc}"})
        entry["commits"] = commits
        entry["commit_failures"] = failures
        entry["commitment_count_onchain"] = \
            registry.functions.commitmentCount().call()

        after = _portfolio_state(args.out_dir)
        appended = after["totals"][before["snapshots"]:]
        entry["portfolio"] = {
            "snapshots_before": before["snapshots"],
            "snapshots_after": after["snapshots"],
            "appended_totals_usd": appended,
            "last_total_before_usd": before["last_total_usd"],
            "last_total_after_usd": after["last_total_usd"],
            "change_usd": (round(after["last_total_usd"]
                                 - before["last_total_usd"], 2)
                           if before["last_total_usd"] is not None
                           and after["last_total_usd"] is not None else None),
        }
        entry["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        log["rounds"].append(entry)
        print(f"[cycle] round {rnd}: decisions={entry['decisions']} "
              f"commits={commits} failures={len(failures)} "
              f"views={cycle['views']} "
              f"portfolio_change={entry['portfolio']['change_usd']}")

    log["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    log["verdict"] = ("PASS" if all(
        r["commits"] == r["decisions"] and not r["commit_failures"]
        for r in log["rounds"]) else "FAIL")
    with open(LOG_PATH, "w", encoding="utf-8") as fh:
        json.dump(log, fh, indent=2, ensure_ascii=False)
    print(f"[cycle] wrote {LOG_PATH} verdict={log['verdict']}")
    return 0 if log["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
