"""Phase-2 end-to-end probe: SealCall full flow on a LOCAL EVM only.

Runs the real engine cycle against the live Tokenized Stocks API, then
deploys the phase-1 CommitRegistry + FollowRegistry contracts to an
in-process eth-tester (py-evm) chain — never to any external network —
and exercises:

  1. commit(decision) for the first N cycle decisions
  2. a too-early reveal attempt (must revert with RevealTooEarly)
  3. time travel past reveal_at, then reveal(payload, salt) per decision
  4. on-chain verification: revealed flag + stored decisionHash equals
     the Python-computed keccak256(payload)
  5. follow / follow / unfollow across two follower accounts, with
     followerCount + isFollowing checks after each step

Every step's observed output (tx hashes, block numbers, revert errors,
read-back values) is recorded verbatim into probe/phase2_e2e.json.
Nothing in that file is hand-written; if a step fails, the failure is
recorded and the run stops with a nonzero exit code.

Usage (from sealcall/ root):
    .venv/bin/python probe/phase2_e2e.py [--commit-count 3]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eth_tester import EthereumTester  # noqa: E402
from web3 import Web3  # noqa: E402
from web3.providers.eth_tester import EthereumTesterProvider  # noqa: E402

from agent.engine import run_cycle  # noqa: E402

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")
OUT_PATH = os.path.join(HERE, "phase2_e2e.json")
E2E_OUT_DIR = os.path.join(HERE, ".e2e_engine_out")
REVEAL_DELAY_SECONDS = 120
COMMIT_COUNT_DEFAULT = 3


def load_artifact(name: str):
    out_dir = os.path.join(ROOT, "contracts", "out")
    abi_path = os.path.join(out_dir, f"{name}_sol_{name}.abi")
    bin_path = os.path.join(out_dir, f"{name}_sol_{name}.bin")
    with open(abi_path, "r", encoding="utf-8") as fh:
        abi = json.load(fh)
    with open(bin_path, "r", encoding="utf-8") as fh:
        bytecode = fh.read().strip()
    return abi, bytecode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit-count", type=int, default=COMMIT_COUNT_DEFAULT)
    args = parser.parse_args()

    log: dict = {
        "probe": "sealcall-phase2-e2e",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "network": "local eth-tester (py-evm) in-process chain — NOT an external network",
        "steps": [],
        "errors": [],
    }

    def step(name: str, **fields):
        entry = {"step": name, **fields}
        log["steps"].append(entry)
        print(f"[e2e] {name}: { {k: v for k, v in fields.items() if k != 'detail'} }")
        return entry

    try:
        # --- 1. real engine cycle (live API data, short reveal delay) ---
        result = run_cycle(out_dir=E2E_OUT_DIR,
                           reveal_delay_seconds=REVEAL_DELAY_SECONDS)
        cycle = result["cycle"]
        decisions = result["decisions"]
        step("engine_cycle",
             universe_size=cycle["universe_size"],
             universe=cycle["universe"],
             views=cycle["views"],
             analyst=cycle["analyst"])
        log["briefs"] = result["briefs"]
        log["portfolio"] = result["portfolio"]

        # --- 2. local chain + contract deployment -----------------------
        tester = EthereumTester()
        w3 = Web3(EthereumTesterProvider(tester))
        accounts = w3.eth.accounts
        agent_acct, follower1, follower2 = accounts[0], accounts[1], accounts[2]
        step("chain_setup", chain_id=w3.eth.chain_id,
             agent_account=agent_acct,
             block_number=w3.eth.block_number)

        deployed = {}
        for name in ("CommitRegistry", "FollowRegistry"):
            abi, bytecode = load_artifact(name)
            factory = w3.eth.contract(abi=abi, bytecode=bytecode)
            tx = factory.constructor().transact({"from": agent_acct})
            receipt = w3.eth.wait_for_transaction_receipt(tx)
            deployed[name] = w3.eth.contract(
                address=receipt.contractAddress, abi=abi)
            step(f"deploy_{name}",
                 address=receipt.contractAddress,
                 tx_hash=tx.hex(), block=receipt.blockNumber,
                 status=receipt.status)
        commit_reg = deployed["CommitRegistry"]
        follow_reg = deployed["FollowRegistry"]
        log["contracts"] = {
            name: deployed[name].address
            for name in ("CommitRegistry", "FollowRegistry")
        }

        # --- 3. commit the first N decisions -----------------------------
        chosen = decisions[: args.commit_count]
        committed = []
        for d in chosen:
            tx = commit_reg.functions.commit(
                bytes.fromhex(d["commitment_hash"][2:]), d["reveal_at"]
            ).transact({"from": agent_acct})
            receipt = w3.eth.wait_for_transaction_receipt(tx)
            cid = commit_reg.functions.commitmentCount().call() - 1
            committed.append({"decision": d, "commitment_id": cid,
                              "commit_tx": tx.hex(),
                              "commit_block": receipt.blockNumber})
            step("commit", ticker=d["ticker"], commitment_id=cid,
                 commitment_hash=d["commitment_hash"], tx_hash=tx.hex(),
                 status=receipt.status)

        # --- 4. too-early reveal must revert ------------------------------
        first = committed[0]
        payload = first["decision"]["payload_canonical_json"].encode("utf-8")
        salt = bytes.fromhex(first["decision"]["salt_hex"][2:])
        try:
            commit_reg.functions.reveal(
                first["commitment_id"], payload, salt
            ).transact({"from": agent_acct})
            step("reveal_too_early", outcome="NO REVERT (unexpected!)")
            log["errors"].append("early reveal did not revert")
        except Exception as exc:
            step("reveal_too_early", outcome="reverted as expected",
                 error=f"{type(exc).__name__}: {exc}")

        # --- 5. time travel past reveal_at, then reveal all ---------------
        target_ts = first["decision"]["reveal_at"] + 5
        tester.time_travel(target_ts)
        tester.mine_block()
        step("time_travel", to_timestamp=target_ts,
             chain_timestamp=w3.eth.get_block("latest").timestamp)

        reveal_records = []
        for c in committed:
            d = c["decision"]
            payload = d["payload_canonical_json"].encode("utf-8")
            salt = bytes.fromhex(d["salt_hex"][2:])
            tx = commit_reg.functions.reveal(
                c["commitment_id"], payload, salt
            ).transact({"from": agent_acct})
            receipt = w3.eth.wait_for_transaction_receipt(tx)
            onchain = commit_reg.functions.getCommitment(
                c["commitment_id"]).call()
            record = {
                "ticker": d["ticker"],
                "commitment_id": c["commitment_id"],
                "commit_tx": c["commit_tx"],
                "reveal_tx": tx.hex(),
                "reveal_block": receipt.blockNumber,
                "reveal_status": receipt.status,
                "commitment_hash": d["commitment_hash"],
                "python_decision_hash": d["decision_hash"],
                "onchain_decision_hash": "0x" + onchain[5].hex(),
                "onchain_revealed": onchain[4],
                "hash_match": "0x" + onchain[5].hex() == d["decision_hash"],
                "view": d["view"],
                "target_weight_pct": d["target_weight_pct"],
                "reveal_at": d["reveal_at"],
                "payload_canonical_json": d["payload_canonical_json"],
                "salt_hex": d["salt_hex"],
            }
            reveal_records.append(record)
            step("reveal", ticker=d["ticker"],
                 commitment_id=c["commitment_id"], tx_hash=tx.hex(),
                 status=receipt.status,
                 onchain_revealed=record["onchain_revealed"],
                 hash_match=record["hash_match"])
        log["decisions_onchain"] = reveal_records

        # --- 6. follow / unfollow flow ------------------------------------
        follow_log = []

        def follow_action(fn_name, frm, note):
            fn = getattr(follow_reg.functions, fn_name)
            tx = fn(agent_acct).transact({"from": frm})
            receipt = w3.eth.wait_for_transaction_receipt(tx)
            entry = {
                "action": fn_name, "follower": frm, "note": note,
                "tx_hash": tx.hex(), "status": receipt.status,
                "follower_count_after":
                    follow_reg.functions.followerCount(agent_acct).call(),
                "is_following_after":
                    follow_reg.functions.isFollowing(agent_acct, frm).call(),
            }
            follow_log.append(entry)
            step(fn_name, **{k: entry[k] for k in
                             ("follower", "follower_count_after",
                              "is_following_after", "status")})

        follow_action("follow", follower1, "follower1 follows agent")
        follow_action("follow", follower2, "follower2 follows agent")
        follow_action("unfollow", follower1, "follower1 unfollows agent")
        log["follow_flow"] = follow_log
        log["final_follower_count"] = \
            follow_reg.functions.followerCount(agent_acct).call()

        ok = (all(r["hash_match"] and r["onchain_revealed"]
                  for r in reveal_records)
              and log["final_follower_count"] == 1
              and not log["errors"])
        log["verdict"] = "PASS" if ok else "FAIL"
    except Exception:
        log["errors"].append(traceback.format_exc())
        log["verdict"] = "ERROR"
        print("[e2e] fatal error, see phase2_e2e.json", file=sys.stderr)
    finally:
        log["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        with open(OUT_PATH, "w", encoding="utf-8") as fh:
            json.dump(log, fh, indent=2, ensure_ascii=False)
        print(f"[e2e] wrote {OUT_PATH} verdict={log['verdict']}")
    return 0 if log["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
