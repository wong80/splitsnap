# Grilling Amendments

Decisions made during the design grilling session (2026-09-16) that amend, clarify, or extend `plan.md`. Integrate these into the plan before implementation begins.

---

## Data model changes

1. **`quantity` defaults to 1** when the LLM doesn't extract one. It is no longer purely informational — it caps claim weights (see ADR 0001).

2. **Claim weight is capped at `quantity`** (1 to `quantity`, not unbounded). When the organizer edits quantity downward, existing claims are auto-clamped to the new value.

3. **Rename `ShareResult` → `SplitSnapshot`** in the data model. Avoids overloading "share" (share link, share result, custom shares). Aligns with the engine's `SplitResult` type.

4. **`printed_total_minor` is editable** by the organizer on the review screen. Covers receipts that are wrong or don't reflect verbal discounts/tips.

5. **Participant name uniqueness is case-insensitive, whitespace-trimmed.** Store the display form, compare lowercased.

6. **Soft cap of 20 participants per bill** to prevent abuse via self-add.

## Status machine

7. **`review → open` requires an explicit "Confirm" action**, even if the reconciliation gap is zero. The organizer must verify extracted data.

8. **`open → review` is allowed.** Show a warning: "N friends have claimed items — edits will affect their shares." Keep existing claims; drop claims on deleted items.

9. **All item/charge editing requires `review` status.** No edits while in `open`.

10. **Unlock returns the bill to `open`**, not `review`.

## Extraction

11. **Extraction retry fully replaces** attempt 1's items and charges (no merge).

12. **Both attempts failing schema validation → bill enters `review` with empty items.** The organizer adds everything manually using the receipt image as reference.

13. **Unsupported currency is not a schema error.** Bill enters `review` with items intact and a "Select a supported currency" prompt. Does not consume a retry attempt.

14. **LLM extracts the bill title** (restaurant/shop name). Fallback: date-based title. Editable on review.

## UX flows

15. **Share page before identity:** item list visible read-only. Interaction requires "I am..." selection first.

16. **Share page in `extracting`/`review` status:** waiting screen with "The organizer is still setting up this bill" and polling for `open`.

17. **Share page after lock:** server-side 302 redirect to summary. HTMX polling sends `HX-Redirect`.

18. **Claim UX:** toggle on (weight=1) → optional stepper shown after claiming → toggle off to unclaim. Stepper hidden until item is claimed.

19. **Full claim visibility.** Every friend sees who claimed each item and their weights.

20. **Friend identity switching allowed.** "Not Alice? Switch" link clears the cookie and returns to the identity picker. Claims stay on the original participant.

21. **Self-add name collision:** if a friend types a name that matches an existing participant (case-insensitive), treat it as selecting that participant.

22. **Payment entry:** "Add payer" button (not a list of all participants). Section lives on admin page below claims. Running total shown: "Payments: RM 85.00 / RM 100.00".

23. **Lock button with live precondition checklist.** Always visible, enabled only when all preconditions pass. Shows check/cross per condition.

24. **No split preview before lock.** Live per-person totals provide enough signal. Unlock is the safety net.

25. **Admin page is one URL** (`/b/<token>/`) that renders different content per status. No separate sub-URLs.

26. **Share link delivery:** copy button + Web Share API button on admin page. Admin link is the current URL (not shown separately).

## Layout

27. **Mobile review screen:** collapsible receipt image (collapsed by default), editor always visible.

28. **Presigned URL refresh:** lazy reload via HTMX endpoint (`hx-trigger="load, every 240s"`), keeping the 5-min expiry.

## Summary

29. **Summary web page:** full per-person breakdown — claimed items with share and amount, portion of each charge, total owed, total paid, net, plus settlement transfers.

30. **Summary text (copy):** settlement + per-person totals only (not full breakdown). Suitable for chat apps.

## Edge cases

31. **Negative owed is valid.** A participant whose item subtotal is small relative to a large discount can owe a negative amount (they become a creditor in settlement).

32. **Both admin and share pages poll** at 5s for live updates.

33. **Rate limit feedback:** clear error message with time estimate ("Upload limit reached. Try again in X minutes.").

34. **Purged bills return generic 404.** No tombstone records.

35. **`kind` on BillCharge is display metadata only.** The signed `amount_minor` drives all math. No sign enforcement by kind.

36. **Extraction loading:** spinner on the upload page via long HTMX POST with `hx-indicator`. No separate waiting page.
