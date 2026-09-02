"""Run the server-side privacy retention job.

Schedule this once per day in the backend environment. It intentionally touches
only raw trace fields and route geometry; derived gameplay history is immutable.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# `python scripts/...` otherwise places only scripts/ on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import SessionLocal  # noqa: E402
from app.services.privacy import enforce_retention  # noqa: E402


def _parse_now(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("--now must include a UTC offset")
    return parsed.astimezone(UTC)


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete expired raw location evidence.")
    parser.add_argument(
        "--now",
        type=_parse_now,
        default=None,
        help="UTC timestamp for deterministic runs, e.g. 2026-08-12T00:00:00Z",
    )
    args = parser.parse_args()

    with SessionLocal() as session:
        result = enforce_retention(session, now=args.now)
        session.commit()

    print(
        json.dumps(
            {
                "raw_traces_deleted": result.raw_traces_deleted,
                "route_polylines_reduced": result.route_polylines_reduced,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
