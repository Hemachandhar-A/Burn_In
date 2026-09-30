"""Seed the two named accounts (E10) into the local SQLite file.

DRAFT (session L1): this will not run clean until P2.1 lands storage's `accounts` table and
`save_account`. Its exact signature is not fixed by Part 5.5 ("save_account(...)"); the call
below assumes keyword arguments matching the Account columns, with the PIN already hashed here.
If P2's signature differs, adjust the one call in `seed()` - nothing else depends on it.

SQLite is a local file per machine, so EVERY developer runs this once during their own setup:

    python -m scripts.seed

(run as a module, from the project root - `python scripts/seed.py` puts `scripts/` on
sys.path instead of the project root, so `from storage.repository import ...` fails with
"No module named 'storage'"; confirmed by the Lead, 2026-09-30, BLOCKERS.md.)

PINs are a deterrence/auditability speed bump, not security (context.md Part 8.1). They are
demo values, hashed with Argon2id before storage; the raw PIN is never stored.
"""
from argon2 import PasswordHasher

ACCOUNTS = [
    {"account_id": "a.sharma", "display_name": "A. Sharma", "role": "Quality Engineer", "pin": "1234"},
    {"account_id": "r.mehta", "display_name": "R. Mehta", "role": "Reliability Engineer", "pin": "5678"},
]


def seed() -> None:
    try:
        from storage.repository import init_db, save_account  # P2's exposed API (Part 5.5)
    except ImportError as exc:
        raise SystemExit(
            "storage.repository is not available yet - this script needs P2.1 "
            f"(accounts table + save_account). Expected at session L1. ({exc})"
        )

    hasher = PasswordHasher()  # Argon2id defaults
    init_db()
    for acct in ACCOUNTS:
        save_account(
            account_id=acct["account_id"],
            display_name=acct["display_name"],
            role=acct["role"],
            pin_hash=hasher.hash(acct["pin"]),
        )
        print(f"seeded {acct['account_id']} ({acct['role']})")


if __name__ == "__main__":
    seed()
