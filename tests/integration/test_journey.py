"""End-to-end user journey through the HTTP layer and the database.

upload -> review -> confirm -> participants -> claims -> payments -> lock -> summary
"""

import io
import re

import pytest
from django.test import Client
from PIL import Image

from bills.models import Bill, BillStatus, SplitSnapshot, Transfer


def _receipt_png() -> io.BytesIO:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, format="PNG")
    buf.seek(0)
    buf.name = "receipt.png"
    return buf


@pytest.fixture
def demo_extractor(monkeypatch, settings, tmp_path):
    monkeypatch.setenv("RECEIPT_EXTRACTOR", "demo")
    settings.MEDIA_ROOT = tmp_path


@pytest.mark.django_db
def test_full_bill_journey(demo_extractor):
    organizer = Client()

    # 1. Upload: demo extractor returns a reconciled MYR receipt (30.20).
    resp = organizer.post("/", {"receipt": _receipt_png()})
    assert resp.status_code == 302
    admin_url = resp["Location"]
    bill = Bill.objects.get()
    assert bill.status == BillStatus.REVIEW
    assert bill.printed_total_minor == 3020
    assert bill.line_items.count() == 3
    assert bill.charges.count() == 2

    # 2. Review page renders with a zero reconciliation gap, then confirm.
    resp = organizer.get(admin_url)
    assert resp.status_code == 200
    assert resp.context["gap"] == 0
    organizer.post(admin_url, {"action": "confirm"})
    bill.refresh_from_db()
    assert bill.status == BillStatus.OPEN

    # 3. Organizer adds participants and records that Alice paid everything.
    for name in ("Alice", "Bob"):
        organizer.post(admin_url, {"action": "add_participant", "name": name})
    alice = bill.participants.get(name="Alice")
    bob = bill.participants.get(name="Bob")
    organizer.post(
        admin_url, {"action": "add_payment", "participant_id": alice.id, "amount": "30.20"}
    )

    # 4. Friends identify themselves via the share link and claim items.
    share_url = f"/s/{bill.share_token}/"
    nasi, teh, roti = bill.line_items.order_by("position")
    friend_alice, friend_bob = Client(), Client()
    friend_alice.post(share_url, {"action": "identify", "participant_id": alice.id})
    friend_bob.post(share_url, {"action": "identify", "participant_id": bob.id})

    friend_alice.post(share_url, {"action": "toggle_claim", "item_id": nasi.id})
    friend_bob.post(share_url, {"action": "toggle_claim", "item_id": teh.id})
    friend_alice.post(share_url, {"action": "toggle_claim", "item_id": roti.id})
    friend_bob.post(share_url, {"action": "toggle_claim", "item_id": roti.id})
    # Bob ate 2 of the 3 roti.
    friend_bob.post(share_url, {"action": "set_weight", "item_id": roti.id, "weight": "2"})

    # 5. Lock.
    resp = organizer.get(admin_url)
    assert resp.context["can_lock"]
    organizer.post(admin_url, {"action": "lock"})
    bill.refresh_from_db()
    assert bill.status == BillStatus.LOCKED

    # 6. Snapshot: shares sum exactly to the printed total; Bob pays Alice once.
    owed = {s.participant.name: s.owed_minor for s in SplitSnapshot.objects.filter(bill=bill)}
    assert sum(owed.values()) == bill.printed_total_minor
    transfers = list(Transfer.objects.filter(bill=bill))
    assert len(transfers) == 1
    assert transfers[0].from_participant == bob
    assert transfers[0].to_participant == alice
    assert transfers[0].amount_minor == owed["Bob"]

    # 7. Summary is visible to friends and contains the copy-as-text settlement.
    resp = friend_bob.get(share_url)
    assert resp.status_code == 302
    resp = friend_bob.get(resp["Location"])
    assert resp.status_code == 200
    text = resp.context["plain_text"]
    assert re.search(r"Bob → Alice: \d+\.\d{2} MYR", text)
