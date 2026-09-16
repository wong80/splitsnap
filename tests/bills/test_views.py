import pytest
from django.test import Client

from bills.models import Bill, BillStatus


@pytest.fixture
def bill(db):
    return Bill.objects.create(title="Test", status=BillStatus.OPEN)


@pytest.fixture
def client():
    return Client()


class TestTokenRouting:
    def test_admin_token_resolves(self, client, bill):
        resp = client.get(f"/b/{bill.admin_token}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(bill.id)

    def test_share_token_resolves(self, client, bill):
        resp = client.get(f"/s/{bill.share_token}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(bill.id)

    def test_unknown_admin_token_404(self, client, db):
        resp = client.get("/b/0000000000000000000000000000000000000000000000000000000000000000/")
        assert resp.status_code == 404

    def test_unknown_share_token_404(self, client, db):
        resp = client.get("/s/0000000000000000000000000000000000000000000000000000000000000000/")
        assert resp.status_code == 404

    def test_admin_token_not_in_share_response(self, client, bill):
        resp = client.get(f"/s/{bill.share_token}/")
        assert bill.admin_token not in resp.content.decode()
