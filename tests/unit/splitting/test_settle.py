from splitting.settle import Transfer, settle


class TestSettle:
    def test_simple_two_person(self):
        transfers = settle({1: -500, 2: 500})
        assert len(transfers) == 1
        assert transfers[0] == Transfer(from_id=1, to_id=2, amount_minor=500)

    def test_three_person(self):
        transfers = settle({1: -300, 2: -200, 3: 500})
        total_transferred = sum(t.amount_minor for t in transfers)
        assert total_transferred == 500
        assert len(transfers) <= 2
        assert all(t.amount_minor > 0 for t in transfers)

    def test_balanced_no_transfers(self):
        transfers = settle({1: 0, 2: 0, 3: 0})
        assert transfers == []

    def test_at_most_n_minus_1_transfers(self):
        balances = {1: -100, 2: -200, 3: -300, 4: 600}
        transfers = settle(balances)
        assert len(transfers) <= 3

    def test_all_amounts_positive(self):
        transfers = settle({1: -100, 2: -50, 3: 150})
        assert all(t.amount_minor > 0 for t in transfers)

    def test_transfers_zero_all_balances(self):
        balances = {1: -300, 2: -200, 3: 100, 4: 400}
        transfers = settle(balances)
        adjusted = dict(balances)
        for t in transfers:
            adjusted[t.from_id] += t.amount_minor
            adjusted[t.to_id] -= t.amount_minor
        assert all(v == 0 for v in adjusted.values())

    def test_single_person_zero_balance(self):
        transfers = settle({1: 0})
        assert transfers == []

    def test_two_creditors_one_debtor(self):
        transfers = settle({1: -500, 2: 300, 3: 200})
        assert len(transfers) <= 2
        adjusted = {1: -500, 2: 300, 3: 200}
        for t in transfers:
            adjusted[t.from_id] += t.amount_minor
            adjusted[t.to_id] -= t.amount_minor
        assert all(v == 0 for v in adjusted.values())
