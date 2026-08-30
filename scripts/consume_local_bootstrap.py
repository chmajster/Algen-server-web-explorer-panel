#!/usr/bin/env python3
from __future__ import annotations

from app.local_auth import consume_initial_admin_credentials


def main() -> int:
    credentials = consume_initial_admin_credentials()
    if not credentials:
        return 0
    print("Initial local administrator credentials:")
    print(f"Username: {credentials['username']}")
    print(f"Password: {credentials['password']}")
    print("IMPORTANT: this password is displayed once and is not stored in plaintext.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
