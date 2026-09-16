import logging

from core.logging import TokenRedactionFilter


class TestTokenRedactionFilter:
    def test_redacts_long_hex_tokens(self):
        f = TokenRedactionFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "", (), None)
        record.msg = "Token: abcdef01234567890123456789abcdef01234567890123456789abcdef012345"
        f.filter(record)
        assert record.msg == "Token: abcdef01..."

    def test_leaves_short_hex_alone(self):
        f = TokenRedactionFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "", (), None)
        record.msg = "Short: abcdef0123456"
        f.filter(record)
        assert "abcdef0123456" in record.msg

    def test_non_string_messages_pass_through(self):
        f = TokenRedactionFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "", (), None)
        record.msg = 42
        assert f.filter(record)
