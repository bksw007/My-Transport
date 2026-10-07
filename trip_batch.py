from __future__ import annotations

from typing import Any


MAX_ROUND_COUNT = 100


def parse_round_count(value: str | None) -> int:
    cleaned = (value or "").strip()
    if not cleaned:
        return 1

    try:
        round_count = int(cleaned)
    except (TypeError, ValueError) as exc:
        raise ValueError("จำนวนรอบต้องเป็นเลขจำนวนเต็มตั้งแต่ 1 ถึง 100") from exc

    if round_count < 1 or round_count > MAX_ROUND_COUNT:
        raise ValueError("จำนวนรอบต้องอยู่ระหว่าง 1 ถึง 100")
    return round_count


def _append_note(base_note: str, *labels: str) -> str:
    parts = [str(base_note or "").strip(), *labels]
    return " · ".join(part for part in parts if part)


def build_trip_batch(
    base_trip: dict[str, Any],
    round_count: int,
    return_pickup: bool,
) -> list[dict[str, Any]]:
    trips: list[dict[str, Any]] = []
    base_note = str(base_trip.get("note") or "").strip()

    for round_number in range(1, round_count + 1):
        round_label = "" if round_count == 1 else f"รอบ {round_number}"
        outbound = dict(base_trip)
        outbound["note"] = _append_note(base_note, round_label)
        trips.append(outbound)

        if return_pickup:
            inbound = dict(base_trip)
            inbound["origin"] = base_trip["destination"]
            inbound["destination"] = base_trip["origin"]
            inbound["note"] = _append_note(base_note, round_label, "รับกลับ")
            trips.append(inbound)

    return trips
