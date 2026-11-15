"""Decision objects and their on-chain-compatible sealing hash.

Hash scheme (must stay byte-compatible with contracts/CommitRegistry.sol):

- The decision payload is a canonical JSON document (sorted keys, tight
  separators, UTF-8). Its exact bytes are what gets revealed on-chain as
  the ``decision`` calldata.
- commitment_hash = keccak256(payload_bytes || salt), where salt is 32
  random bytes. This matches the contract's reveal check
  ``keccak256(abi.encodePacked(decision, salt))`` because
  abi.encodePacked of (bytes, bytes32) is plain concatenation.
- decision_hash = keccak256(payload_bytes), matching the contract's
  stored ``decisionHash = keccak256(decision)`` set at reveal time.

We use Ethereum keccak256 (via eth_utils), NOT NIST sha3_256 — the two
differ and only keccak256 verifies against the contract.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from typing import Any, Optional

from eth_utils import keccak

VIEWS = ("BUY", "HOLD", "AVOID")
PAYLOAD_VERSION = 1
AGENT_ID = "sealcall-rules-v0"


def canonical_json(obj: Any) -> bytes:
    """Canonical byte encoding used for payloads and brief references."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def brief_reference(brief: dict) -> str:
    """sha256 hex of the canonical brief JSON; links a decision to its brief."""
    return hashlib.sha256(canonical_json(brief)).hexdigest()


@dataclass
class Decision:
    """One agent decision, ready to be sealed via CommitRegistry."""

    ticker: str
    view: str                              # BUY | HOLD | AVOID
    target_weight_pct: float               # % of paper portfolio, 0..100
    rationale: str                         # human-readable reason (正文)
    created_at: int                        # unix seconds
    reveal_at: int                         # unix seconds, >= created_at
    brief_sha256: str                      # brief_reference() of the source brief
    salt: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    agent_id: str = AGENT_ID

    def __post_init__(self) -> None:
        if self.view not in VIEWS:
            raise ValueError(f"view must be one of {VIEWS}, got {self.view!r}")
        if not (0.0 <= self.target_weight_pct <= 100.0):
            raise ValueError("target_weight_pct out of range")
        if self.reveal_at < self.created_at:
            raise ValueError("reveal_at before created_at")
        if len(self.salt) != 32:
            raise ValueError("salt must be exactly 32 bytes")

    # -- payload / hashes ------------------------------------------------

    def payload(self) -> dict:
        """The canonical payload dict; its bytes are the on-chain `decision`."""
        return {
            "v": PAYLOAD_VERSION,
            "agent": self.agent_id,
            "ticker": self.ticker,
            "view": self.view,
            "target_weight_pct": round(self.target_weight_pct, 4),
            "rationale": self.rationale,
            "brief_sha256": self.brief_sha256,
            "created_at": self.created_at,
            "reveal_at": self.reveal_at,
        }

    def payload_bytes(self) -> bytes:
        return canonical_json(self.payload())

    def commitment_hash(self) -> bytes:
        """keccak256(payload || salt) — pass to CommitRegistry.commit()."""
        return keccak(self.payload_bytes() + self.salt)

    def decision_hash(self) -> bytes:
        """keccak256(payload) — equals the contract's stored decisionHash."""
        return keccak(self.payload_bytes())

    # -- serialization ---------------------------------------------------

    def to_json(self) -> dict:
        return {
            "ticker": self.ticker,
            "view": self.view,
            "target_weight_pct": round(self.target_weight_pct, 4),
            "rationale": self.rationale,
            "created_at": self.created_at,
            "reveal_at": self.reveal_at,
            "brief_sha256": self.brief_sha256,
            "agent_id": self.agent_id,
            "payload_canonical_json": self.payload_bytes().decode("utf-8"),
            "salt_hex": "0x" + self.salt.hex(),
            "commitment_hash": "0x" + self.commitment_hash().hex(),
            "decision_hash": "0x" + self.decision_hash().hex(),
            "hash_scheme": "keccak256(canonical_json_payload || salt32), "
                           "compatible with CommitRegistry.reveal",
        }


def make_decision(ticker: str, view: str, target_weight_pct: float,
                  rationale: str, brief: dict, created_at: int,
                  reveal_delay_seconds: int,
                  salt: Optional[bytes] = None,
                  agent_id: Optional[str] = None) -> Decision:
    """Build a Decision bound to a brief, with reveal time = created + delay."""
    d = Decision(
        ticker=ticker,
        view=view,
        target_weight_pct=target_weight_pct,
        rationale=rationale,
        created_at=created_at,
        reveal_at=created_at + reveal_delay_seconds,
        brief_sha256=brief_reference(brief),
        salt=salt if salt is not None else secrets.token_bytes(32),
        agent_id=agent_id or AGENT_ID,
    )
    return d
