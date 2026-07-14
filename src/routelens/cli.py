from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .collector import run_all_checks
from .store import RouteLensStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RouteLens check runner")
    parser.add_argument(
        "--db",
        default=os.environ.get("ROUTELENS_DATABASE", "/var/lib/routelens/routelens.db"),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    db = Path(args.db).expanduser()
    store = RouteLensStore(db)
    results = run_all_checks(store)
    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        for result in results:
            print(f"{result['resource']} {result['check_type']} {result['status']}: {result['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
