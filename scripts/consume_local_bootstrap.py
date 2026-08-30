#!/usr/bin/env python3
from __future__ import annotations

import argparse

from app.local_auth import bootstrap_initial_admin


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("password")
    args = parser.parse_args()
    user, password = bootstrap_initial_admin(args.username, args.password)
    if user is None:
        print("Local user database already initialized; existing accounts preserved.")
        return 0
    print("Default local administrator created:")
    print(f"Username: {user['username']}")
    print(f"Password: {password}")
    print("IMPORTANT: change this default password immediately after the first login.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
