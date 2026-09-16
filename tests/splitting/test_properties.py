from hypothesis import assume, given, settings
from hypothesis import strategies as st

from splitting.engine import Charge, Item, allocate, compute_shares
from splitting.settle import settle

pid_strategy = st.integers(min_value=1, max_value=100)
weight_strategy = st.integers(min_value=1, max_value=10)
minor_strategy = st.integers(min_value=0, max_value=1_000_000)


weights_strategy = st.lists(
    st.tuples(pid_strategy, weight_strategy),
    min_size=1,
    max_size=10,
).filter(lambda ws: len({pid for pid, _ in ws}) == len(ws))


class TestAllocateProperties:
    @given(total=st.integers(min_value=0, max_value=1_000_000), weights=weights_strategy)
    @settings(max_examples=200)
    def test_sum_equals_total(self, total, weights):
        result = allocate(total, weights)
        assert sum(s for _, s in result) == total

    @given(total=st.integers(min_value=0, max_value=1_000_000), weights=weights_strategy)
    @settings(max_examples=200)
    def test_each_share_within_one_unit(self, total, weights):
        result = allocate(total, weights)
        total_weight = sum(w for _, w in weights)
        shares = dict(result)
        for pid, w in weights:
            exact = total * w / total_weight
            assert abs(shares[pid] - exact) < 1

    @given(total=st.integers(min_value=0, max_value=1_000_000), weights=weights_strategy)
    @settings(max_examples=100)
    def test_deterministic(self, total, weights):
        r1 = allocate(total, weights)
        r2 = allocate(total, weights)
        assert r1 == r2

    @given(total=st.integers(min_value=0, max_value=1_000_000), weights=weights_strategy)
    @settings(max_examples=100)
    def test_order_independent(self, total, weights):
        import random

        r1 = allocate(total, weights)
        shuffled = list(weights)
        random.shuffle(shuffled)
        r2 = allocate(total, shuffled)
        assert dict(r1) == dict(r2)


item_strategy = st.builds(
    Item,
    amount_minor=st.integers(min_value=0, max_value=100_000),
    discount_minor=st.just(0),
    claims=weights_strategy,
)


class TestComputeSharesProperties:
    @given(
        items=st.lists(item_strategy, min_size=1, max_size=5),
        charge_amounts=st.lists(st.integers(min_value=0, max_value=10_000), max_size=3),
    )
    @settings(max_examples=200)
    def test_owed_sums_to_bill_total(self, items, charge_amounts):
        charges = [Charge(amount_minor=a) for a in charge_amounts]
        result = compute_shares(items, charges, [])
        expected = sum(it.amount_minor - it.discount_minor for it in items) + sum(charge_amounts)
        assert sum(result.owed.values()) == expected

    @given(items=st.lists(item_strategy, min_size=1, max_size=5))
    @settings(max_examples=100)
    def test_non_negative_owed_no_negative_charges(self, items):
        result = compute_shares(items, [], [])
        for _pid, owed in result.owed.items():
            assert owed >= 0


@st.composite
def balanced_balances(draw):
    n = draw(st.integers(min_value=2, max_value=10))
    pids = draw(st.lists(pid_strategy, min_size=n, max_size=n, unique=True))
    values = [draw(st.integers(min_value=-10_000, max_value=10_000)) for _ in range(n - 1)]
    values.append(-sum(values))
    assume(any(v != 0 for v in values))
    return dict(zip(pids, values, strict=True))


class TestSettleProperties:
    @given(balances=balanced_balances())
    @settings(max_examples=200)
    def test_transfers_zero_all_balances(self, balances):
        transfers = settle(balances)
        adjusted = dict(balances)
        for t in transfers:
            adjusted[t.from_id] += t.amount_minor
            adjusted[t.to_id] -= t.amount_minor
        assert all(v == 0 for v in adjusted.values())

    @given(balances=balanced_balances())
    @settings(max_examples=200)
    def test_at_most_n_minus_1_transfers(self, balances):
        transfers = settle(balances)
        assert len(transfers) <= len(balances) - 1

    @given(balances=balanced_balances())
    @settings(max_examples=200)
    def test_all_amounts_positive(self, balances):
        transfers = settle(balances)
        assert all(t.amount_minor > 0 for t in transfers)
