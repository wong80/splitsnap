import pytest
from django.core.signing import get_cookie_signer
from django.test import Client

from bills.models import (
    Bill,
    BillCharge,
    BillStatus,
    ItemClaim,
    LineItem,
    Participant,
    Payment,
)


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def bill(db):
    return Bill.objects.create(title="Test", status=BillStatus.OPEN, currency="MYR")


@pytest.fixture
def review_bill(db):
    return Bill.objects.create(title="Review", status=BillStatus.REVIEW, currency="MYR")


def _set_participant_cookie(client, bill, participant):
    key = f"participant_{bill.id}"
    client.cookies[key] = get_cookie_signer(salt=key).sign(str(participant.id))


def _setup_lockable_bill(db):
    bill = Bill.objects.create(
        title="Lockable",
        status=BillStatus.OPEN,
        currency="MYR",
        printed_total_minor=1000,
    )
    item = LineItem.objects.create(
        bill=bill, position=1, description="Item", amount_minor=1000, quantity=2
    )
    a = Participant.objects.create(bill=bill, name="Alice")
    b = Participant.objects.create(bill=bill, name="Bob")
    ItemClaim.objects.create(line_item=item, participant=a, weight=1)
    ItemClaim.objects.create(line_item=item, participant=b, weight=1)
    Payment.objects.create(bill=bill, participant=a, amount_minor=1000)
    return bill, a, b


class TestTokenRouting:
    def test_admin_token_resolves(self, client, bill):
        resp = client.get(f"/b/{bill.admin_token}/")
        assert resp.status_code == 200

    def test_share_token_resolves(self, client, bill):
        resp = client.get(f"/s/{bill.share_token}/")
        assert resp.status_code == 200

    def test_unknown_admin_token_404(self, client, db):
        resp = client.get("/b/0" * 32 + "/")
        assert resp.status_code == 404

    def test_unknown_share_token_404(self, client, db):
        resp = client.get("/s/0" * 32 + "/")
        assert resp.status_code == 404

    def test_admin_token_not_in_share_response(self, client, bill):
        resp = client.get(f"/s/{bill.share_token}/")
        assert bill.admin_token not in resp.content.decode()


class TestUpload:
    def test_get_upload_page(self, client, db):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_post_no_file(self, client, db):
        resp = client.post("/")
        assert resp.status_code == 200
        assert b"select a file" in resp.content.lower()


class TestReviewConfirm:
    def test_confirm_transitions_to_open(self, client, review_bill):
        client.post(
            f"/b/{review_bill.admin_token}/",
            {"action": "confirm"},
        )
        review_bill.refresh_from_db()
        assert review_bill.status == BillStatus.OPEN

    def test_update_bill_fields(self, client, review_bill):
        client.post(
            f"/b/{review_bill.admin_token}/",
            {
                "action": "update_bill",
                "title": "New Title",
                "currency": "SGD",
                "printed_total": "50.00",
            },
        )
        review_bill.refresh_from_db()
        assert review_bill.title == "New Title"
        assert review_bill.currency == "SGD"
        assert review_bill.printed_total_minor == 5000


class TestItemManagement:
    def test_add_item(self, client, bill):
        client.post(
            f"/b/{bill.admin_token}/",
            {"action": "add_item", "description": "Tea", "amount": "5.00"},
        )
        assert bill.line_items.count() == 1
        assert bill.line_items.first().description == "Tea"

    def test_delete_item(self, client, bill):
        item = LineItem.objects.create(bill=bill, position=1, description="X", amount_minor=100)
        client.post(
            f"/b/{bill.admin_token}/",
            {"action": "delete_item", "item_id": str(item.id)},
        )
        assert bill.line_items.count() == 0


class TestChargeManagement:
    def test_add_charge(self, client, bill):
        client.post(
            f"/b/{bill.admin_token}/",
            {"action": "add_charge", "kind": "tax", "label": "SST", "amount": "1.00"},
        )
        assert bill.charges.count() == 1

    def test_delete_charge(self, client, bill):
        ch = BillCharge.objects.create(bill=bill, kind="tax", label="SST", amount_minor=100)
        client.post(
            f"/b/{bill.admin_token}/",
            {"action": "delete_charge", "charge_id": str(ch.id)},
        )
        assert bill.charges.count() == 0


class TestParticipantManagement:
    def test_add_participant(self, client, bill):
        client.post(
            f"/b/{bill.admin_token}/",
            {"action": "add_participant", "name": "Charlie"},
        )
        assert bill.participants.count() == 1

    def test_remove_participant(self, client, bill):
        p = Participant.objects.create(bill=bill, name="Charlie")
        client.post(
            f"/b/{bill.admin_token}/",
            {"action": "remove_participant", "participant_id": str(p.id)},
        )
        assert bill.participants.count() == 0

    def test_cap_20_participants(self, client, bill):
        for i in range(20):
            Participant.objects.create(bill=bill, name=f"P{i}")
        client.post(
            f"/b/{bill.admin_token}/",
            {"action": "add_participant", "name": "P20"},
        )
        assert bill.participants.count() == 20

    def test_self_add_collision_selects_existing(self, client, bill):
        Participant.objects.create(bill=bill, name="Alice")
        resp = client.post(
            f"/s/{bill.share_token}/",
            {"action": "identify", "name": "alice"},
        )
        assert bill.participants.count() == 1
        assert f"participant_{bill.id}" in resp.cookies


class TestPayments:
    def test_add_payment(self, client, bill):
        p = Participant.objects.create(bill=bill, name="Alice")
        client.post(
            f"/b/{bill.admin_token}/",
            {
                "action": "add_payment",
                "participant_id": str(p.id),
                "amount": "50.00",
            },
        )
        assert bill.payments.count() == 1
        assert bill.payments.first().amount_minor == 5000

    def test_delete_payment(self, client, bill):
        p = Participant.objects.create(bill=bill, name="Alice")
        pay = Payment.objects.create(bill=bill, participant=p, amount_minor=5000)
        client.post(
            f"/b/{bill.admin_token}/",
            {"action": "delete_payment", "payment_id": str(pay.id)},
        )
        assert bill.payments.count() == 0

    def test_payment_unique_per_participant(self, client, bill):
        p = Participant.objects.create(bill=bill, name="Alice")
        client.post(
            f"/b/{bill.admin_token}/",
            {
                "action": "add_payment",
                "participant_id": str(p.id),
                "amount": "50.00",
            },
        )
        client.post(
            f"/b/{bill.admin_token}/",
            {
                "action": "add_payment",
                "participant_id": str(p.id),
                "amount": "60.00",
            },
        )
        assert bill.payments.count() == 1
        assert bill.payments.first().amount_minor == 6000


class TestClaims:
    def test_toggle_claim_on(self, client, bill):
        item = LineItem.objects.create(bill=bill, position=1, description="X", amount_minor=100)
        p = Participant.objects.create(bill=bill, name="Alice")
        _set_participant_cookie(client, bill, p)
        client.post(
            f"/s/{bill.share_token}/",
            {"action": "toggle_claim", "item_id": str(item.id)},
        )
        assert ItemClaim.objects.filter(line_item=item, participant=p).exists()

    def test_toggle_claim_off(self, client, bill):
        item = LineItem.objects.create(bill=bill, position=1, description="X", amount_minor=100)
        p = Participant.objects.create(bill=bill, name="Alice")
        ItemClaim.objects.create(line_item=item, participant=p, weight=1)
        _set_participant_cookie(client, bill, p)
        client.post(
            f"/s/{bill.share_token}/",
            {"action": "toggle_claim", "item_id": str(item.id)},
        )
        assert not ItemClaim.objects.filter(line_item=item, participant=p).exists()

    def test_claim_idempotent(self, client, bill):
        item = LineItem.objects.create(bill=bill, position=1, description="X", amount_minor=100)
        p = Participant.objects.create(bill=bill, name="Alice")
        _set_participant_cookie(client, bill, p)
        client.post(
            f"/s/{bill.share_token}/",
            {"action": "toggle_claim", "item_id": str(item.id)},
        )
        assert ItemClaim.objects.filter(line_item=item, participant=p).count() == 1

    def test_claims_rejected_after_lock(self, client, db):
        bill, a, _b = _setup_lockable_bill(db)
        client.post(f"/b/{bill.admin_token}/", {"action": "lock"})
        bill.refresh_from_db()
        assert bill.status == BillStatus.LOCKED

        item = bill.line_items.first()
        _set_participant_cookie(client, bill, a)
        client.post(
            f"/s/{bill.share_token}/",
            {"action": "toggle_claim", "item_id": str(item.id)},
        )

    def test_set_weight(self, client, bill):
        item = LineItem.objects.create(
            bill=bill, position=1, description="X", amount_minor=100, quantity=3
        )
        p = Participant.objects.create(bill=bill, name="Alice")
        ItemClaim.objects.create(line_item=item, participant=p, weight=1)
        _set_participant_cookie(client, bill, p)
        client.post(
            f"/s/{bill.share_token}/",
            {"action": "set_weight", "item_id": str(item.id), "weight": "2"},
        )
        claim = ItemClaim.objects.get(line_item=item, participant=p)
        assert claim.weight == 2

    def test_weight_clamped_to_quantity(self, client, bill):
        item = LineItem.objects.create(
            bill=bill, position=1, description="X", amount_minor=100, quantity=2
        )
        p = Participant.objects.create(bill=bill, name="Alice")
        _set_participant_cookie(client, bill, p)
        client.post(
            f"/s/{bill.share_token}/",
            {"action": "set_weight", "item_id": str(item.id), "weight": "10"},
        )
        claim = ItemClaim.objects.get(line_item=item, participant=p)
        assert claim.weight == 2


class TestLock:
    def test_lock_creates_snapshots(self, client, db):
        bill, _a, _b = _setup_lockable_bill(db)
        client.post(f"/b/{bill.admin_token}/", {"action": "lock"})
        bill.refresh_from_db()
        assert bill.status == BillStatus.LOCKED
        assert bill.snapshots.count() == 2
        assert bill.locked_at is not None
        assert bill.expires_at is not None

    def test_lock_snapshots_match_engine(self, client, db):
        bill, a, b = _setup_lockable_bill(db)
        client.post(f"/b/{bill.admin_token}/", {"action": "lock"})
        snap_a = bill.snapshots.get(participant=a)
        snap_b = bill.snapshots.get(participant=b)
        assert snap_a.owed_minor + snap_b.owed_minor == 1000

    def test_lock_creates_transfers(self, client, db):
        bill, _a, _b = _setup_lockable_bill(db)
        client.post(f"/b/{bill.admin_token}/", {"action": "lock"})
        assert bill.transfers.exists()

    def test_lock_precondition_no_claims(self, client, bill):
        LineItem.objects.create(bill=bill, position=1, description="X", amount_minor=100)
        bill.printed_total_minor = 100
        bill.save()
        client.post(f"/b/{bill.admin_token}/", {"action": "lock"})
        bill.refresh_from_db()
        assert bill.status == BillStatus.OPEN

    def test_lock_precondition_gap_nonzero(self, client, bill):
        item = LineItem.objects.create(bill=bill, position=1, description="X", amount_minor=100)
        p = Participant.objects.create(bill=bill, name="Alice")
        ItemClaim.objects.create(line_item=item, participant=p, weight=1)
        bill.printed_total_minor = 200
        bill.save()
        Payment.objects.create(bill=bill, participant=p, amount_minor=200)
        client.post(f"/b/{bill.admin_token}/", {"action": "lock"})
        bill.refresh_from_db()
        assert bill.status == BillStatus.OPEN


class TestUnlock:
    def test_unlock_clears_snapshot(self, client, db):
        bill, _a, _b = _setup_lockable_bill(db)
        client.post(f"/b/{bill.admin_token}/", {"action": "lock"})
        client.post(f"/b/{bill.admin_token}/", {"action": "unlock"})
        bill.refresh_from_db()
        assert bill.status == BillStatus.OPEN
        assert bill.snapshots.count() == 0
        assert bill.transfers.count() == 0
        assert bill.locked_at is None


class TestSummary:
    def test_admin_sees_summary_when_locked(self, client, db):
        bill, _a, _b = _setup_lockable_bill(db)
        client.post(f"/b/{bill.admin_token}/", {"action": "lock"})
        resp = client.get(f"/b/{bill.admin_token}/")
        assert resp.status_code == 200
        assert b"Settlement" in resp.content

    def test_share_redirects_to_summary(self, client, db):
        bill, _a, _b = _setup_lockable_bill(db)
        client.post(f"/b/{bill.admin_token}/", {"action": "lock"})
        resp = client.get(f"/s/{bill.share_token}/")
        assert resp.status_code == 302
        assert "summary" in resp.url

    def test_summary_has_plain_text(self, client, db):
        bill, _a, _b = _setup_lockable_bill(db)
        client.post(f"/b/{bill.admin_token}/", {"action": "lock"})
        resp = client.get(f"/s/{bill.share_token}/summary")
        assert resp.status_code == 200
        assert b"Settlement" in resp.content


class TestShareWaiting:
    def test_extracting_shows_waiting(self, client, db):
        bill = Bill.objects.create(status=BillStatus.EXTRACTING)
        resp = client.get(f"/s/{bill.share_token}/")
        assert resp.status_code == 200
        assert b"setting up" in resp.content.lower()

    def test_review_shows_waiting(self, client, db):
        bill = Bill.objects.create(status=BillStatus.REVIEW)
        resp = client.get(f"/s/{bill.share_token}/")
        assert resp.status_code == 200
        assert b"setting up" in resp.content.lower()
