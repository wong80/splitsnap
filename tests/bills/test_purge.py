import datetime

import pytest
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from bills.models import Bill, BillStatus, LineItem, Participant


@pytest.fixture
def _now():
    return timezone.now()


def _setup_lockable_bill(db):
    from tests.bills.test_views import _setup_lockable_bill

    return _setup_lockable_bill(db)


class TestPurgeExpiredBills:
    def test_purge_unlocked_expired(self, db, _now):
        Bill.objects.create(
            title="Old",
            status=BillStatus.OPEN,
            expires_at=_now - datetime.timedelta(days=1),
        )
        call_command("purge_expired_bills")
        assert Bill.objects.count() == 0

    def test_purge_locked_expired(self, db, _now):
        Bill.objects.create(
            title="Old Locked",
            status=BillStatus.LOCKED,
            locked_at=_now - datetime.timedelta(days=31),
            expires_at=_now - datetime.timedelta(days=1),
        )
        call_command("purge_expired_bills")
        assert Bill.objects.count() == 0

    def test_non_expired_untouched(self, db, _now):
        Bill.objects.create(
            title="Fresh",
            status=BillStatus.OPEN,
            expires_at=_now + datetime.timedelta(days=3),
        )
        call_command("purge_expired_bills")
        assert Bill.objects.count() == 1

    def test_no_expires_at_untouched(self, db):
        Bill.objects.create(title="No expiry", status=BillStatus.OPEN)
        call_command("purge_expired_bills")
        assert Bill.objects.count() == 1

    def test_cascades_related_objects(self, db, _now):
        bill = Bill.objects.create(
            title="Old",
            status=BillStatus.OPEN,
            expires_at=_now - datetime.timedelta(days=1),
        )
        LineItem.objects.create(bill=bill, position=1, description="X", amount_minor=100)
        Participant.objects.create(bill=bill, name="Alice")
        call_command("purge_expired_bills")
        assert Bill.objects.count() == 0
        assert LineItem.objects.count() == 0
        assert Participant.objects.count() == 0

    def test_expires_at_set_on_lock(self, db, _now):
        bill, _a, _b = _setup_lockable_bill(db)
        client = Client()
        client.post(f"/b/{bill.admin_token}/", {"action": "lock"})
        bill.refresh_from_db()
        assert bill.expires_at is not None
        assert bill.expires_at > _now + datetime.timedelta(days=29)

    def test_expires_at_set_on_unlock(self, db, _now):
        bill, _a, _b = _setup_lockable_bill(db)
        client = Client()
        client.post(f"/b/{bill.admin_token}/", {"action": "lock"})
        client.post(f"/b/{bill.admin_token}/", {"action": "unlock"})
        bill.refresh_from_db()
        assert bill.expires_at is not None
        assert bill.expires_at <= bill.created_at + datetime.timedelta(days=7, seconds=1)
