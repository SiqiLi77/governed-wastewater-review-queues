"""Deterministic fixed-capacity selection with auditable reserve slots."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Iterable, Mapping, Sequence


Record = Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ReservePolicy:
    """A declared share of queue capacity for one eligible domain."""

    name: str
    eligibility_field: str
    fraction: float
    score_field: str | None = None


@dataclass(frozen=True, slots=True)
class SelectedCandidate:
    """One selected candidate and the policy step that assigned its slot."""

    rank: int
    candidate_id: str
    source: str


@dataclass(frozen=True, slots=True)
class ReserveAudit:
    """Requested and realized slots for one reserve policy."""

    name: str
    requested_fraction: float
    requested_slots: int
    eligible_candidates: int
    realized_slots: int


@dataclass(frozen=True, slots=True)
class QueueResult:
    """Selected queue plus the policy ledger needed to reproduce it."""

    candidate_count: int
    capacity: int
    selected: tuple[SelectedCandidate, ...]
    reserve_audit: tuple[ReserveAudit, ...]

    @property
    def selected_ids(self) -> tuple[str, ...]:
        return tuple(item.candidate_id for item in self.selected)

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_count": self.candidate_count,
            "capacity": self.capacity,
            "selected": [asdict(item) for item in self.selected],
            "reserve_audit": [asdict(item) for item in self.reserve_audit],
        }


def _candidate_id(record: Record, id_field: str) -> str:
    value = record.get(id_field)
    if value is None or not str(value).strip():
        raise ValueError(f"every candidate requires a non-empty {id_field}")
    return str(value)


def _score(record: Record, field: str) -> float:
    value = record.get(field)
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return -math.inf
    return numeric if math.isfinite(numeric) else -math.inf


def _resolve_capacity(
    candidate_count: int,
    *,
    burden: float | None,
    capacity: int | None,
) -> int:
    if (burden is None) == (capacity is None):
        raise ValueError("provide exactly one of burden or capacity")
    if candidate_count == 0:
        return 0
    if burden is not None:
        if not 0 < burden <= 1:
            raise ValueError("burden must be in (0, 1]")
        return min(candidate_count, max(1, math.ceil(candidate_count * burden)))
    if capacity is None or isinstance(capacity, bool) or capacity < 0:
        raise ValueError("capacity must be a non-negative integer")
    if int(capacity) != capacity:
        raise ValueError("capacity must be a non-negative integer")
    return min(candidate_count, int(capacity))


def _validate_reserves(reserves: Sequence[ReservePolicy]) -> None:
    names: set[str] = set()
    total_fraction = 0.0
    for reserve in reserves:
        if not reserve.name.strip():
            raise ValueError("reserve names must be non-empty")
        if reserve.name in names:
            raise ValueError(f"duplicate reserve name: {reserve.name}")
        if not 0 <= reserve.fraction <= 1:
            raise ValueError("reserve fractions must be in [0, 1]")
        names.add(reserve.name)
        total_fraction += reserve.fraction
    if total_fraction > 1 + 1e-12:
        raise ValueError("reserve fractions cannot sum to more than 1")


def select_governed_queue(
    records: Iterable[Record],
    *,
    burden: float | None = None,
    capacity: int | None = None,
    reserves: Sequence[ReservePolicy] = (),
    id_field: str = "candidate_id",
    global_score_field: str = "global_score",
) -> QueueResult:
    """Select one deterministic queue and return its complete assignment ledger.

    Reserve slots use floor rounding and are applied in declared order. Any
    unfilled reserve slots return to the global ranking. Candidate identifiers
    break score ties so the same input values produce the same selection even
    when row order changes.
    """

    candidates = [dict(record) for record in records]
    candidate_ids = [_candidate_id(record, id_field) for record in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError(f"{id_field} values must be unique")

    queue_capacity = _resolve_capacity(
        len(candidates), burden=burden, capacity=capacity
    )
    reserve_policies = tuple(reserves)
    _validate_reserves(reserve_policies)

    selected_indices: list[int] = []
    selected_ids: set[str] = set()
    audits: list[ReserveAudit] = []

    def ranked_indices(
        score_field: str,
        *,
        eligible_indices: Iterable[int] | None = None,
    ) -> list[int]:
        indices = (
            list(range(len(candidates)))
            if eligible_indices is None
            else list(eligible_indices)
        )
        available = [
            index
            for index in indices
            if candidate_ids[index] not in selected_ids
        ]
        return sorted(
            available,
            key=lambda index: (
                -_score(candidates[index], score_field),
                candidate_ids[index],
            ),
        )

    for reserve in reserve_policies:
        requested = math.floor(queue_capacity * reserve.fraction)
        eligible = [
            index
            for index, record in enumerate(candidates)
            if bool(record.get(reserve.eligibility_field, False))
        ]
        score_field = reserve.score_field or global_score_field
        available_slots = max(0, queue_capacity - len(selected_indices))
        take = min(requested, available_slots, len(eligible))
        chosen = ranked_indices(score_field, eligible_indices=eligible)[:take]
        for index in chosen:
            selected_indices.append(index)
            selected_ids.add(candidate_ids[index])
        audits.append(
            ReserveAudit(
                name=reserve.name,
                requested_fraction=reserve.fraction,
                requested_slots=requested,
                eligible_candidates=len(eligible),
                realized_slots=len(chosen),
            )
        )

    fill_slots = max(0, queue_capacity - len(selected_indices))
    for index in ranked_indices(global_score_field)[:fill_slots]:
        selected_indices.append(index)
        selected_ids.add(candidate_ids[index])

    reserve_sources: dict[str, str] = {}
    cursor = 0
    for audit in audits:
        for index in selected_indices[cursor : cursor + audit.realized_slots]:
            reserve_sources[candidate_ids[index]] = f"reserve:{audit.name}"
        cursor += audit.realized_slots

    selected = tuple(
        SelectedCandidate(
            rank=rank,
            candidate_id=candidate_ids[index],
            source=reserve_sources.get(candidate_ids[index], "global_fill"),
        )
        for rank, index in enumerate(selected_indices, start=1)
    )
    return QueueResult(
        candidate_count=len(candidates),
        capacity=queue_capacity,
        selected=selected,
        reserve_audit=tuple(audits),
    )
