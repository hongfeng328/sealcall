"""Phase-3 probe: deploy SealCall registries to Base Sepolia (testnet).

This is the ONLY external network this probe may touch: Base Sepolia
(chain id 84532). It never touches mainnet and never uses any wallet
other than the project-only deployer in sealcall/.env.local (gitignored;
the private key is read into memory only and never printed or logged).

Flow:
  1. read deployer address (and, only if funded, key) from .env.local
  2. check the deployer balance on https://sepolia.base.org
  3. if the balance is zero, record status=BLOCKED with the faucet
     attempts made for this phase (see FAUCET_ATTEMPTS) and stop —
     no deployment is faked, ever
  4. if funded: run one real engine cycle, deploy CommitRegistry +
     FollowRegistry from contracts/out artifacts, then commit() the
     cycle's first decision (its real commitment hash + reveal time)
     and record every tx hash / address / explorer link

Output: probe/sepolia_deploy.json (observed values only).

Usage (from sealcall/ root):
    .venv/bin/python probe/sepolia_deploy.py
Exit codes: 0 = deployed, 3 = blocked (zero balance).
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from web3 import Web3  # noqa: E402

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")
OUT_PATH = os.path.join(HERE, "sepolia_deploy.json")
ENV_PATH = os.path.join(ROOT, ".env.local")

RPC_URL = "https://sepolia.base.org"
CHAIN_ID = 84532
EXPLORER = "https://sepolia.basescan.org"

# Faucet attempts for the project deployer address, 2026-11-16.
# Each outcome was verified live (faucet page text / sign-in wall /
# connection test) before being recorded here.
FAUCET_ATTEMPTS = [
    {
        "faucet": "Coinbase Developer Platform faucet",
        "url": "https://portal.cdp.coinbase.com/products/faucet",
        "outcome": "blocked",
        "reason": "requires signing in with a Coinbase Developer Platform "
                  "account; creating accounts is out of scope for this "
                  "phase and no existing account was used",
    },
    {
        "faucet": "Alchemy Base Sepolia faucet",
        "url": "https://www.alchemy.com/faucets/base-sepolia",
        "outcome": "ineligible",
        "reason": "faucet requires the claiming wallet to hold at least "
                  "0.001 ETH on Ethereum mainnet (stated on the faucet "
                  "page); the fresh project wallet holds none",
    },
    {
        "faucet": "QuickNode Base Sepolia faucet",
        "url": "https://faucet.quicknode.com/base/sepolia",
        "outcome": "ineligible",
        "reason": "faucet requires a small mainnet balance on the "
                  "claiming wallet plus a browser bot check (stated on "
                  "the faucet page); the fresh project wallet has no "
                  "mainnet balance",
    },
    {
        "faucet": "Superchain Faucet (Optimism)",
        "url": "https://app.optimism.io/faucet",
        "outcome": "blocked",
        "reason": "requires Optimism Dev Console sign-in and reCAPTCHA",
    },
    {
        "faucet": "Chainstack faucet",
        "url": "https://faucet.chainstack.com",
        "outcome": "blocked",
        "reason": "requires signing in to a Chainstack account",
    },
    {
        "faucet": "Bware Labs faucet",
        "url": "https://faucet.bwarelabs.com",
        "outcome": "unreachable",
        "reason": "site connection failed from this environment "
                  "(curl HTTP 000, retried twice)",
    },
    {
        "faucet": "Nodies faucet",
        "url": "https://faucet.nodies.app",
        "outcome": "unreachable",
        "reason": "site connection failed from this environment "
                  "(curl HTTP 000)",
    },
    {
        "faucet": "Circle faucet",
        "url": "https://faucet.circle.com",
        "outcome": "not_applicable",
        "reason": "dispenses test USDC/EURC only, not the ETH needed "
                  "for deployment gas; also reCAPTCHA-gated",
    },
    {
        "faucet": "Zalalena Base faucet",
        "url": "https://faucet.zalalena.com/base",
        "outcome": "blocked",
        "reason": "hCaptcha verification required before delivery",
    },
]

UNBLOCK_OPTIONS = [
    "Sign in to the Coinbase Developer Platform faucet and drip Base "
    "Sepolia ETH to the project address (works for fresh wallets).",
    "Transfer >= 0.01 Base Sepolia ETH to the project address from any "
    "already-funded Base Sepolia wallet.",
    "Sign in to the Superchain faucet (GitHub) and drip to the project "
    "address.",
]


def load_env_local() -> dict:
    env: dict = {}
    with open(ENV_PATH, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    return env


def load_artifact(name: str):
    out_dir = os.path.join(ROOT, "contracts", "out")
    with open(os.path.join(out_dir, f"{name}_sol_{name}.abi"),
              "r", encoding="utf-8") as fh:
        abi = json.load(fh)
    with open(os.path.join(out_dir, f"{name}_sol_{name}.bin"),
              "r", encoding="utf-8") as fh:
        bytecode = fh.read().strip()
    return abi, bytecode


def main() -> int:
    log: dict = {
        "probe": "sealcall-sepolia-deploy",
        "network": "Base Sepolia (testnet)",
        "chain_id": CHAIN_ID,
        "rpc": RPC_URL,
        "explorer": EXPLORER,
        "ran_at_utc": datetime.now(timezone.utc).isoformat(),
        "faucet_attempts": FAUCET_ATTEMPTS,
    }
    try:
        env = load_env_local()
        address = env["SEALCALL_DEPLOYER_ADDRESS"]
        log["deployer_address"] = address

        w3 = Web3(Web3.HTTPProvider(RPC_URL,
                                    request_kwargs={"timeout": 30}))
        if not w3.is_connected() or w3.eth.chain_id != CHAIN_ID:
            raise RuntimeError("RPC did not report Base Sepolia chain id")
        balance = w3.eth.get_balance(address)
        log["deployer_balance_wei"] = balance
        log["deployer_balance_eth"] = str(w3.from_wei(balance, "ether"))
        log["latest_block"] = w3.eth.block_number

        if balance == 0:
            log["status"] = "BLOCKED"
            log["blocked_reason"] = (
                "deployer balance is 0 and every public faucet route is "
                "gated (account sign-in, captcha, or a mainnet-balance "
                "eligibility check the fresh project wallet cannot meet) "
                "or unreachable from this environment; see faucet_attempts")
            log["unblock_options"] = UNBLOCK_OPTIONS
            log["contracts"] = None
            log["commit"] = None
            print("[sepolia] BLOCKED: zero balance, see sepolia_deploy.json")
            return 3

        # --- funded path: real engine cycle, deploy, one real commit ---
        from eth_account import Account
        from agent.engine import run_cycle

        acct = Account.from_key(env["SEALCALL_DEPLOYER_PRIVATE_KEY"])
        assert acct.address == address, "env key/address mismatch"

        result = run_cycle()
        decision = result["decisions"][0]
        log["engine_cycle"] = {
            "universe_size": result["cycle"]["universe_size"],
            "analyst": result["cycle"]["analyst"],
            "decision_ticker": decision["ticker"],
            "commitment_hash": decision["commitment_hash"],
            "reveal_at": decision["reveal_at"],
        }

        def send(fn_or_factory_tx):
            tx = fn_or_factory_tx.build_transaction({
                "from": address,
                "nonce": w3.eth.get_transaction_count(address),
                "chainId": CHAIN_ID,
            })
            signed = acct.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash,
                                                          timeout=180)
            if receipt.status != 1:
                raise RuntimeError(f"tx {tx_hash.hex()} reverted")
            return tx_hash, receipt

        contracts: dict = {}
        for name in ("CommitRegistry", "FollowRegistry"):
            abi, bytecode = load_artifact(name)
            factory = w3.eth.contract(abi=abi, bytecode=bytecode)
            tx_hash, receipt = send(factory.constructor())
            contracts[name] = {
                "address": receipt.contractAddress,
                "deploy_tx": tx_hash.hex(),
                "deploy_block": receipt.blockNumber,
                "explorer_url": f"{EXPLORER}/address/{receipt.contractAddress}",
                "deploy_tx_url": f"{EXPLORER}/tx/{tx_hash.hex()}",
            }
        log["contracts"] = contracts

        commit_abi, _ = load_artifact("CommitRegistry")
        registry = w3.eth.contract(
            address=contracts["CommitRegistry"]["address"], abi=commit_abi)
        tx_hash, receipt = send(registry.functions.commit(
            bytes.fromhex(decision["commitment_hash"][2:]),
            decision["reveal_at"]))
        commitment_id = registry.functions.commitmentCount().call() - 1
        log["commit"] = {
            "commitment_id": commitment_id,
            "ticker": decision["ticker"],
            "commitment_hash": decision["commitment_hash"],
            "reveal_at": decision["reveal_at"],
            "tx_hash": tx_hash.hex(),
            "block": receipt.blockNumber,
            "explorer_url": f"{EXPLORER}/tx/{tx_hash.hex()}",
        }
        log["status"] = "DEPLOYED"
        print(f"[sepolia] DEPLOYED commit tx {tx_hash.hex()}")
        return 0
    except Exception:
        log["status"] = "ERROR"
        log["error"] = traceback.format_exc()
        print("[sepolia] ERROR, see sepolia_deploy.json", file=sys.stderr)
        return 1
    finally:
        with open(OUT_PATH, "w", encoding="utf-8") as fh:
            json.dump(log, fh, indent=2, ensure_ascii=False)
        print(f"[sepolia] wrote {OUT_PATH} status={log.get('status')}")


if __name__ == "__main__":
    raise SystemExit(main())
