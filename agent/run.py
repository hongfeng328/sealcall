"""CLI: run one SealCall engine cycle against the live API.

Usage (from the sealcall/ repo root, using the project venv):
    .venv/bin/python -m agent.run [--reveal-delay-seconds 86400]

Writes JSON outputs to agent/out/ and prints a one-line summary.
"""

from __future__ import annotations

import argparse

from .engine import run_cycle


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one SealCall cycle")
    parser.add_argument("--reveal-delay-seconds", type=int, default=24 * 3600)
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()
    kwargs = {"reveal_delay_seconds": args.reveal_delay_seconds}
    if args.out_dir:
        kwargs["out_dir"] = args.out_dir
    result = run_cycle(**kwargs)
    c = result["cycle"]
    print(f"cycle ok: universe={c['universe_size']} views={c['views']} "
          f"analyst={c['analyst']} at {c['generated_at']}")


if __name__ == "__main__":
    main()
