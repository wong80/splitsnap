import pytest
from django.test import Client


@pytest.fixture
def client():
    return Client()


class TestRequestIDMiddleware:
    def test_adds_request_id_header(self, client, db):
        resp = client.get("/healthz")
        assert "X-Request-ID" in resp

    def test_echoes_provided_request_id(self, client, db):
        resp = client.get("/healthz", HTTP_X_REQUEST_ID="test-123")
        assert resp["X-Request-ID"] == "test-123"


class TestSecurityHeadersMiddleware:
    def test_referrer_policy(self, client, db):
        resp = client.get("/healthz")
        assert resp["Referrer-Policy"] == "same-origin"

    def test_robots_tag(self, client, db):
        resp = client.get("/healthz")
        assert resp["X-Robots-Tag"] == "noindex"
