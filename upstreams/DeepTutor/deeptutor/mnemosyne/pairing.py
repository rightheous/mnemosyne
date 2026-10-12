"""Issue one-time Mnemosyne device pairing codes from the server host."""

from __future__ import annotations

import argparse

from deeptutor.mnemosyne.security import MnemosyneSessionStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Issue a one-time Mnemosyne pairing code")
    parser.add_argument("issue", choices=["issue"])
    args = parser.parse_args()
    if args.issue == "issue":
        code, expires_at = MnemosyneSessionStore().issue_pairing_code()
        print(f"Pairing code: {code}")
        print(f"Expires at: {expires_at.isoformat()}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
