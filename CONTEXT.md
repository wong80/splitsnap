# SplitSnap

A receipt bill splitter: upload a receipt photo, extract line items with a vision LLM, let friends claim items via a share link, and calculate exactly who owes whom in the currency's minor units.

## Language

### The bill

**Bill**:
The central entity. A receipt upload plus all associated items, charges, participants, claims, payments, and (once locked) the computed allocation and settlement.
_Avoid_: Receipt (when referring to the data model — "receipt" means the image)

**Receipt**:
The physical or digital image of a bill from a restaurant or shop. The source document that the LLM reads.
_Avoid_: Photo, image (in domain discussions — "receipt" is the domain term)

**Line Item**:
A single product or dish on the receipt. Has a description, a quantity (informational, defaults to 1), and a total amount as printed. Net amount = amount minus item discount.
_Avoid_: Item (acceptable shorthand in code and UI), product, entry

**Bill Charge**:
A bill-level line that applies to the entire bill: tax, service charge, discount, voucher, rounding adjustment, or a manual adjustment. Stored as a signed amount — negative for discounts and vouchers. The `kind` label is display metadata; the sign drives all math.
_Avoid_: Fee, surcharge, bill-level line (in code — acceptable in conversation)

**Printed Total**:
The total amount as shown on the receipt. Editable by the organizer when the receipt is wrong or doesn't reflect what was paid. The authoritative number that payments must equal.
_Avoid_: Receipt total, original total

**Reconciliation Gap**:
`sum(item net amounts) + sum(bill charge amounts) − printed total`. Must be zero before locking. A nonzero gap means the extracted data doesn't match the receipt.

**Adjustment Line**:
A bill charge auto-prefilled with the reconciliation gap, offered as a one-click fix for small discrepancies between extraction and the printed total.

### People

**Organizer**:
The person who uploads the receipt and manages the bill via the admin link. Has full control: edit items, manage participants, record payments, lock/unlock.
_Avoid_: Admin, owner, host

**Friend**:
A person who accesses the bill via the share link. Can identify themselves, claim items, and set weights. Cannot edit items, charges, payments, or lock state.
_Avoid_: Guest, viewer, user

**Participant**:
A named person on a bill. Can be added by the organizer or self-added by a friend via the share link (up to 20 per bill). Name uniqueness is case-insensitive, whitespace-trimmed.
_Avoid_: Member, person

**Payer**:
A participant who contributed money toward the bill. One payment amount per payer. A participant can be a payer without claiming any items.

### Claiming and splitting

**Claim**:
A participant's assertion that they consumed part of a line item. One claim per (item, participant) pair, carrying a weight.
_Avoid_: Selection, pick

**Weight**:
An integer (1 to the item's quantity) on a claim, representing the participant's share ratio for that item. Default 1. Weights are ratios — a 2:1 split means the first person pays twice as much as the second, regardless of how many people claim the item.
_Avoid_: Share (overloaded), portion, fraction

**Allocation**:
The mathematical operation of splitting a monetary amount across participants proportionally by their weights, using largest-remainder rounding (ties broken by participant ID ascending). Guarantees the parts sum exactly to the whole, with no participant off by more than one minor unit.

**Settlement**:
The set of transfers that resolves all debts after allocation. Computed by greedy matching: repeatedly pair the largest debtor with the largest creditor. Guarantees at most n−1 transfers.
_Avoid_: Payback, reimbursement

**Transfer**:
A single directed payment in the settlement: one debtor pays one creditor a specific amount.

### Access and lifecycle

**Admin Link**:
The private URL (`/b/<token>/`) for the organizer. A 256-bit unguessable token. The admin link is the URL the organizer is already on — it is not displayed separately.
_Avoid_: Admin URL, management link

**Share Link**:
The URL (`/s/<token>/`) sent to friends. A separate 256-bit token. Grants claim-only access. Delivered via copy button and Web Share API.
_Avoid_: Friend link, public link (it's not public — it's unguessable)

**Lock**:
Freezing a bill to compute the final allocation and settlement, writing a snapshot. Preconditions: every item has at least one claim, reconciliation gap is zero, payments equal printed total, item subtotals are positive when charges exist.
_Avoid_: Finalize, close

**Snapshot**:
The allocation results and settlement transfers written at lock time (stored as `SplitSnapshot` and `Transfer` rows). Deleted on unlock. The summary page reads from the snapshot, not live data.
_Avoid_: Result, freeze

**Unlock**:
Reversing a lock. Deletes the snapshot and returns the bill to `open` status. Friends can adjust claims; the organizer can re-lock.
