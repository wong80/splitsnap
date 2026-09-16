import pytest
from django.core.exceptions import ValidationError

from bills.models import (
    Bill,
    BillStatus,
    ItemClaim,
    LineItem,
    Participant,
    Payment,
)


@pytest.fixture
def bill(db):
    return Bill.objects.create(title="Test Bill", currency="MYR", status=BillStatus.OPEN)


@pytest.fixture
def line_item(bill):
    return LineItem.objects.create(
        bill=bill, position=1, description="Nasi Lemak", amount_minor=1200, quantity=3
    )


@pytest.fixture
def participant_a(bill):
    return Participant.objects.create(bill=bill, name="Alice")


@pytest.fixture
def participant_b(bill):
    return Participant.objects.create(bill=bill, name="Bob")


class TestBill:
    def test_token_generation(self, bill):
        assert len(bill.admin_token) == 64
        assert len(bill.share_token) == 64
        assert bill.admin_token != bill.share_token

    def test_tokens_are_256_bit(self, bill):
        assert len(bytes.fromhex(bill.admin_token)) == 32
        assert len(bytes.fromhex(bill.share_token)) == 32

    def test_unique_tokens(self, db):
        bills = [Bill.objects.create(title=f"Bill {i}") for i in range(5)]
        admin_tokens = {b.admin_token for b in bills}
        share_tokens = {b.share_token for b in bills}
        assert len(admin_tokens) == 5
        assert len(share_tokens) == 5

    def test_default_status(self, db):
        bill = Bill.objects.create()
        assert bill.status == BillStatus.EXTRACTING


class TestLineItem:
    def test_discount_within_amount(self, bill):
        item = LineItem(
            bill=bill, position=1, description="X", amount_minor=100, item_discount_minor=50
        )
        item.clean()

    def test_discount_exceeds_amount(self, bill):
        item = LineItem(
            bill=bill, position=1, description="X", amount_minor=100, item_discount_minor=150
        )
        with pytest.raises(ValidationError, match="discount cannot exceed"):
            item.clean()


class TestParticipant:
    def test_name_trimmed(self, bill):
        p = Participant(bill=bill, name="  Alice  ")
        p.save()
        assert p.name == "Alice"

    def test_case_insensitive_unique(self, bill, participant_a):
        p = Participant(bill=bill, name="alice")
        with pytest.raises(ValidationError, match="already exists"):
            p.clean()

    def test_soft_cap_20(self, bill):
        for i in range(20):
            Participant.objects.create(bill=bill, name=f"Person {i}")
        p = Participant(bill=bill, name="Person 20")
        with pytest.raises(ValidationError, match="more than 20"):
            p.clean()

    def test_blank_name_rejected(self, bill):
        p = Participant(bill=bill, name="   ")
        with pytest.raises(ValidationError, match="cannot be blank"):
            p.clean()


class TestItemClaim:
    def test_valid_claim(self, line_item, participant_a):
        claim = ItemClaim(line_item=line_item, participant=participant_a, weight=2)
        claim.clean()

    def test_weight_exceeds_quantity(self, line_item, participant_a):
        claim = ItemClaim(line_item=line_item, participant=participant_a, weight=5)
        with pytest.raises(ValidationError, match="cannot exceed"):
            claim.clean()


class TestPayment:
    def test_positive_amount(self, bill, participant_a):
        p = Payment(bill=bill, participant=participant_a, amount_minor=0)
        with pytest.raises(ValidationError, match="must be positive"):
            p.clean()
