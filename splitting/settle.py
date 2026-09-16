from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Transfer:
    from_id: int
    to_id: int
    amount_minor: int


def settle(net_balances: dict[int, int]) -> list[Transfer]:
    """Compute settlement transfers using greedy matching.

    *net_balances* maps participant IDs to their net balance (paid minus owed).
    Positive = creditor (overpaid), negative = debtor (underpaid).

    Returns a list of transfers where each debtor pays a creditor.
    Guarantees: at most n-1 transfers, all amounts > 0, applying all
    transfers zeroes every balance.
    """
    debtors: list[list[int]] = []
    creditors: list[list[int]] = []

    for pid, bal in net_balances.items():
        if bal < 0:
            debtors.append([pid, -bal])
        elif bal > 0:
            creditors.append([pid, bal])

    transfers: list[Transfer] = []

    while debtors and creditors:
        debtors.sort(key=lambda x: (-x[1], x[0]))
        creditors.sort(key=lambda x: (-x[1], x[0]))

        debtor = debtors[0]
        creditor = creditors[0]

        amount = min(debtor[1], creditor[1])
        transfers.append(Transfer(from_id=debtor[0], to_id=creditor[0], amount_minor=amount))

        debtor[1] -= amount
        creditor[1] -= amount

        if debtor[1] == 0:
            debtors.pop(0)
        if creditor[1] == 0:
            creditors.pop(0)

    return transfers
