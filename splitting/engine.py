from __future__ import annotations

from dataclasses import dataclass


def allocate(total_minor: int, weights: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Split *total_minor* across participants proportionally by weight.

    *weights* is a list of ``(participant_id, weight)`` pairs.  Returns a list of
    ``(participant_id, share)`` pairs whose shares sum exactly to *total_minor*.

    Uses largest-remainder allocation: each participant gets the floor of their
    exact share, then the remaining units go one each to the participants with the
    largest fractional remainders (ties broken by ascending participant ID).
    """
    if not weights:
        raise ValueError("weights must not be empty")
    total_weight = sum(w for _, w in weights)
    if total_weight <= 0:
        raise ValueError("Total weight must be positive")

    negative = total_minor < 0
    abs_total = abs(total_minor)

    floors: list[tuple[int, int, int]] = []
    for pid, w in weights:
        exact_times_tw = abs_total * w
        floor_val = exact_times_tw // total_weight
        remainder_num = exact_times_tw % total_weight
        floors.append((pid, floor_val, remainder_num))

    floor_sum = sum(f for _, f, _ in floors)
    leftover = abs_total - floor_sum

    ranked = sorted(floors, key=lambda t: (-t[2], t[0]))
    result: list[tuple[int, int]] = []
    for i, (pid, floor_val, _) in enumerate(ranked):
        share = floor_val + (1 if i < leftover else 0)
        if negative:
            share = -share
        result.append((pid, share))

    result.sort(key=lambda t: t[0])
    return result


@dataclass(frozen=True)
class ShareResult:
    owed: dict[int, int]
    net: dict[int, int]
    item_subtotals: dict[int, int]
    charge_totals: dict[int, int]


@dataclass(frozen=True)
class Item:
    amount_minor: int
    discount_minor: int
    claims: list[tuple[int, int]]


@dataclass(frozen=True)
class Charge:
    amount_minor: int


@dataclass(frozen=True)
class PaymentEntry:
    participant_id: int
    amount_minor: int


def compute_shares(
    items: list[Item],
    charges: list[Charge],
    payments: list[PaymentEntry],
) -> ShareResult:
    all_pids: set[int] = set()
    for it in items:
        for pid, _ in it.claims:
            all_pids.add(pid)
    for p in payments:
        all_pids.add(p.participant_id)

    item_subtotals: dict[int, int] = {pid: 0 for pid in all_pids}
    for it in items:
        net = it.amount_minor - it.discount_minor
        if not it.claims:
            continue
        shares = allocate(net, it.claims)
        for pid, share in shares:
            item_subtotals[pid] += share

    charge_totals: dict[int, int] = {pid: 0 for pid in all_pids}
    for ch in charges:
        subtotal_abs = {pid: abs(st) for pid, st in item_subtotals.items()}
        total_abs = sum(subtotal_abs.values())
        if total_abs == 0:
            if not all_pids:
                continue
            charge_weights = [(pid, 1) for pid in sorted(all_pids)]
        else:
            charge_weights = [(pid, subtotal_abs[pid]) for pid in sorted(all_pids) if subtotal_abs[pid] > 0]
        if not charge_weights:
            continue
        shares = allocate(ch.amount_minor, charge_weights)
        for pid, share in shares:
            charge_totals[pid] += share

    owed: dict[int, int] = {}
    paid: dict[int, int] = {pid: 0 for pid in all_pids}
    for p in payments:
        paid[p.participant_id] += p.amount_minor

    for pid in all_pids:
        owed[pid] = item_subtotals[pid] + charge_totals[pid]

    net = {pid: paid[pid] - owed[pid] for pid in all_pids}
    return ShareResult(owed=owed, net=net, item_subtotals=item_subtotals, charge_totals=charge_totals)
