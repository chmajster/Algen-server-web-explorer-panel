#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from app.local_auth import repository


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the initial WebNAS local-database administrator")
    parser.add_argument("--username", default="admin")
    args = parser.parse_args()

    user, password = repository().bootstrap_admin(args.username)
    if user is None:
        print(json.dumps({"created": False}, separators=(",", ":")))
        return 0
    print(
        json.dumps(
            {
                "created": True,
                "username": user["username"],
                "password": password,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
