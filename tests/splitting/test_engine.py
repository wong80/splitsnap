import pytest

from splitting.engine import Charge, Item, PaymentEntry, ShareResult, allocate, compute_shares


class TestAllocate:
    def test_even_split(self):
        result = allocate(900, [(1, 1), (2, 1), (3, 1)])
        shares = dict(result)
        assert sum(shares.values()) == 900
        assert shares == {1: 300, 2: 300, 3: 300}

    def test_10_split_three_ways(self):
        result = allocate(1000, [(1, 1), (2, 1), (3, 1)])
        shares = dict(result)
        assert sum(shares.values()) == 1000
        assert shares == {1: 334, 2: 333, 3: 333}

    def test_weighted_2_1(self):
        result = allocate(900, [(1, 2), (2, 1)])
        shares = dict(result)
        assert sum(shares.values()) == 900
        assert shares == {1: 600, 2: 300}

    def test_single_participant(self):
        result = allocate(1000, [(1, 1)])
        assert dict(result) == {1: 1000}

    def test_zero_total(self):
        result = allocate(0, [(1, 1), (2, 1)])
        shares = dict(result)
        assert sum(shares.values()) == 0

    def test_negative_total(self):
        result = allocate(-100, [(1, 1), (2, 1)])
        shares = dict(result)
        assert sum(shares.values()) == -100

    def test_empty_weights_raises(self):
        with pytest.raises(ValueError, match="weights must not be empty"):
            allocate(100, [])

    def test_tie_broken_by_pid_ascending(self):
        result = allocate(10, [(3, 1), (1, 1), (2, 1)])
        shares = dict(result)
        assert sum(shares.values()) == 10
        assert shares[1] >= shares[2] >= shares[3]


class TestComputeShares:
    def test_simple_equal_split(self):
        items = [Item(amount_minor=1000, discount_minor=0, claims=[(1, 1), (2, 1), (3, 1)])]
        payments = [PaymentEntry(participant_id=1, amount_minor=1000)]
        result = compute_shares(items, [], payments)
        assert sum(result.owed.values()) == 1000
        assert result.owed[1] == 334
        assert result.owed[2] == 333
        assert result.owed[3] == 333

    def test_weighted_claim(self):
        items = [Item(amount_minor=900, discount_minor=0, claims=[(1, 2), (2, 1)])]
        result = compute_shares(items, [], [])
        assert result.owed[1] == 600
        assert result.owed[2] == 300

    def test_item_discount(self):
        items = [Item(amount_minor=1000, discount_minor=200, claims=[(1, 1), (2, 1)])]
        result = compute_shares(items, [], [])
        assert result.owed[1] == 400
        assert result.owed[2] == 400
        assert sum(result.owed.values()) == 800

    def test_negative_voucher_charge(self):
        items = [Item(amount_minor=1000, discount_minor=0, claims=[(1, 1), (2, 1)])]
        charges = [Charge(amount_minor=-200)]
        result = compute_shares(items, charges, [])
        assert result.item_subtotals[1] == 500
        assert result.item_subtotals[2] == 500
        assert result.charge_totals[1] == -100
        assert result.charge_totals[2] == -100
        assert result.owed[1] == 400
        assert result.owed[2] == 400

    def test_rounding_adjustment(self):
        items = [Item(amount_minor=1000, discount_minor=0, claims=[(1, 1), (2, 1)])]
        charges = [Charge(amount_minor=-2)]
        result = compute_shares(items, charges, [])
        total_owed = sum(result.owed.values())
        assert total_owed == 998

    def test_payer_with_no_claims(self):
        items = [Item(amount_minor=1000, discount_minor=0, claims=[(1, 1)])]
        payments = [PaymentEntry(participant_id=2, amount_minor=1000)]
        result = compute_shares(items, [], payments)
        assert result.owed[1] == 1000
        assert result.owed[2] == 0
        assert result.net[1] == -1000
        assert result.net[2] == 1000

    def test_jpy_bill(self):
        items = [Item(amount_minor=1000, discount_minor=0, claims=[(1, 1), (2, 1), (3, 1)])]
        charges = [Charge(amount_minor=100)]
        payments = [PaymentEntry(participant_id=1, amount_minor=1100)]
        result = compute_shares(items, charges, payments)
        total_owed = sum(result.owed.values())
        assert total_owed == 1100

    def test_two_payers_three_debtors(self):
        items = [
            Item(amount_minor=3000, discount_minor=0, claims=[(1, 1), (2, 1), (3, 1)]),
        ]
        payments = [
            PaymentEntry(participant_id=4, amount_minor=1500),
            PaymentEntry(participant_id=5, amount_minor=1500),
        ]
        result = compute_shares(items, [], payments)
        assert result.owed[1] == 1000
        assert result.owed[2] == 1000
        assert result.owed[3] == 1000
        assert result.owed[4] == 0
        assert result.owed[5] == 0
        assert result.net[4] == 1500
        assert result.net[5] == 1500

    def test_negative_owed_large_voucher(self):
        items = [Item(amount_minor=100, discount_minor=0, claims=[(1, 1), (2, 1)])]
        charges = [Charge(amount_minor=-500)]
        result = compute_shares(items, charges, [])
        assert result.owed[1] < 0
        assert result.owed[2] < 0

    def test_service_charge_allocated_by_subtotals(self):
        items = [
            Item(amount_minor=300, discount_minor=0, claims=[(1, 1)]),
            Item(amount_minor=100, discount_minor=0, claims=[(2, 1)]),
        ]
        charges = [Charge(amount_minor=40)]
        result = compute_shares(items, charges, [])
        assert result.charge_totals[1] == 30
        assert result.charge_totals[2] == 10

    def test_multiple_items_multiple_charges(self):
        items = [
            Item(amount_minor=500, discount_minor=0, claims=[(1, 1), (2, 1)]),
            Item(amount_minor=300, discount_minor=100, claims=[(2, 1), (3, 1)]),
        ]
        charges = [
            Charge(amount_minor=60),
            Charge(amount_minor=-20),
        ]
        payments = [PaymentEntry(participant_id=1, amount_minor=740)]
        result = compute_shares(items, charges, payments)
        assert sum(result.owed.values()) == sum(it.amount_minor - it.discount_minor for it in items) + sum(
            ch.amount_minor for ch in charges
        )
