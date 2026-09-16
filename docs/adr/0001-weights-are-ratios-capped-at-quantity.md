# Claim weights are ratios, capped at the item's quantity

Claim weights are positive integers that express each participant's share as a ratio (2:1 means "twice as much"), not a unit count ("I had 2 beers"). Despite being ratios, the maximum weight on any claim is capped at the line item's `quantity` field (which defaults to 1 when the receipt doesn't state one). This means a single-quantity item forces all claimants to weight 1 (equal split), while a "3x Beer" line allows weights up to 3.

The cap is a deliberate UX guardrail, not a mathematical constraint — the allocation engine works with any positive integer weights. Capping at quantity gives friends an intuitive upper bound ("there were 3 beers, I can't claim more than 3") while keeping the underlying math simple (weighted proportional split with largest-remainder rounding). The trade-off is that `quantity` — originally informational metadata from the receipt — becomes load-bearing for claim validation. When the organizer edits quantity downward, existing claims are auto-clamped to the new value.

## Considered options

- **No cap, arbitrary sanity bound (99):** Simpler, but "99" is meaningless and doesn't help friends understand what number to enter.
- **Uncapped:** Allows accidental fat-finger entries (weight 9999 on mobile).
