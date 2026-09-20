import logging

from core.logging import TokenRedactionFilter


class TestTokenRedactionFilter:
    def test_redacts_tokens_in_url_path(self):
        f = TokenRedactionFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "", (), None)
        token = "a" * 43
        record.msg = f"GET /b/{token}/ HTTP/1.1"
        f.filter(record)
        assert record.msg == f"GET /b/{token[:8]}.../ HTTP/1.1"

    def test_redacts_share_token_in_url_path(self):
        f = TokenRedactionFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "", (), None)
        token = "x" * 43
        record.msg = f"GET /s/{token}/ HTTP/1.1"
        f.filter(record)
        assert record.msg == f"GET /s/{token[:8]}.../ HTTP/1.1"

    def test_leaves_bare_token_alone(self):
        f = TokenRedactionFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "", (), None)
        record.msg = "Token: " + "a" * 43
        f.filter(record)
        assert "a" * 43 in record.msg

    def test_non_string_messages_pass_through(self):
        f = TokenRedactionFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "", (), None)
        record.msg = 42
        assert f.filter(record)
