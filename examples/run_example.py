"""Run a governed queue on synthetic candidate records."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from governed_queues import ReservePolicy, select_governed_queue


def load_candidates(path: Path) -> list[dict[str, object]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["global_score"] = float(row["global_score"])
        row["reserve_score"] = float(row["reserve_score"])
        row["protected_profile"] = row["protected_profile"].lower() == "true"
    return rows


def main() -> None:
    candidates = load_candidates(Path(__file__).with_name("synthetic_candidates.csv"))
    result = select_governed_queue(
        candidates,
        burden=0.40,
        reserves=[
            ReservePolicy(
                name="protected_profile",
                eligibility_field="protected_profile",
                fraction=0.25,
                score_field="reserve_score",
            )
        ],
    )
    print(json.dumps(result.as_dict(), indent=2))


if __name__ == "__main__":
    main()
