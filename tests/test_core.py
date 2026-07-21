from __future__ import annotations

import unittest

from governed_queues import ReservePolicy, select_governed_queue


class GovernedQueueTests(unittest.TestCase):
    def test_global_queue_uses_stable_identifier_ties(self) -> None:
        records = [
            {"candidate_id": "b", "global_score": 0.8},
            {"candidate_id": "a", "global_score": 0.8},
            {"candidate_id": "c", "global_score": 0.1},
        ]
        result = select_governed_queue(records, capacity=2)
        self.assertEqual(result.selected_ids, ("a", "b"))

    def test_reserve_preserves_capacity_and_global_fill(self) -> None:
        records = [
            {"candidate_id": "a", "global_score": 0.99, "protected": False},
            {"candidate_id": "b", "global_score": 0.90, "protected": False},
            {"candidate_id": "c", "global_score": 0.80, "protected": False},
            {
                "candidate_id": "d",
                "global_score": 0.20,
                "protected": True,
                "reserve_score": 0.95,
            },
            {
                "candidate_id": "e",
                "global_score": 0.10,
                "protected": True,
                "reserve_score": 0.85,
            },
            {"candidate_id": "f", "global_score": 0.05, "protected": False},
        ]
        result = select_governed_queue(
            records,
            capacity=4,
            reserves=[
                ReservePolicy("protected", "protected", 0.50, "reserve_score")
            ],
        )
        self.assertEqual(result.selected_ids, ("d", "e", "a", "b"))
        self.assertEqual(len(set(result.selected_ids)), 4)
        self.assertEqual(result.reserve_audit[0].realized_slots, 2)

    def test_overlapping_reserves_do_not_duplicate_candidates(self) -> None:
        records = [
            {
                "candidate_id": "x",
                "global_score": 0.2,
                "domain_a": True,
                "domain_b": True,
                "reserve_score": 1.0,
            },
            {
                "candidate_id": "y",
                "global_score": 0.3,
                "domain_a": False,
                "domain_b": True,
                "reserve_score": 0.9,
            },
            {"candidate_id": "z", "global_score": 0.8},
            {"candidate_id": "w", "global_score": 0.7},
        ]
        result = select_governed_queue(
            records,
            capacity=4,
            reserves=[
                ReservePolicy("a", "domain_a", 0.25, "reserve_score"),
                ReservePolicy("b", "domain_b", 0.25, "reserve_score"),
            ],
        )
        self.assertEqual(result.selected_ids, ("x", "y", "z", "w"))

    def test_unused_reserve_capacity_returns_to_global_fill(self) -> None:
        records = [
            {"candidate_id": "a", "global_score": 0.9, "protected": True},
            {"candidate_id": "b", "global_score": 0.8, "protected": False},
            {"candidate_id": "c", "global_score": 0.7, "protected": False},
            {"candidate_id": "d", "global_score": 0.6, "protected": False},
        ]
        result = select_governed_queue(
            records,
            capacity=4,
            reserves=[ReservePolicy("protected", "protected", 0.75)],
        )
        self.assertEqual(len(result.selected_ids), 4)
        self.assertEqual(result.reserve_audit[0].requested_slots, 3)
        self.assertEqual(result.reserve_audit[0].realized_slots, 1)

    def test_missing_scores_rank_last(self) -> None:
        records = [
            {"candidate_id": "a", "global_score": None},
            {"candidate_id": "b", "global_score": 0.5},
        ]
        result = select_governed_queue(records, capacity=1)
        self.assertEqual(result.selected_ids, ("b",))

    def test_duplicate_ids_are_rejected(self) -> None:
        records = [
            {"candidate_id": "a", "global_score": 0.9},
            {"candidate_id": "a", "global_score": 0.8},
        ]
        with self.assertRaisesRegex(ValueError, "must be unique"):
            select_governed_queue(records, capacity=1)

    def test_reserve_fractions_cannot_exceed_capacity(self) -> None:
        records = [{"candidate_id": "a", "global_score": 0.9}]
        reserves = [
            ReservePolicy("a", "domain_a", 0.6),
            ReservePolicy("b", "domain_b", 0.5),
        ]
        with self.assertRaisesRegex(ValueError, "cannot sum"):
            select_governed_queue(records, capacity=1, reserves=reserves)

    def test_empty_pool_has_zero_capacity(self) -> None:
        result = select_governed_queue([], burden=0.20)
        self.assertEqual(result.capacity, 0)
        self.assertEqual(result.selected_ids, ())


if __name__ == "__main__":
    unittest.main()
