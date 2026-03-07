"""Tests for core.discord_client.DiscordClient."""

import pytest
from unittest.mock import patch, MagicMock, call

from core.discord_client import DiscordClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(webhook_url="https://mock.discord.webhook"):
    """Construct a DiscordClient with ConfigLoader patched out."""
    with patch("core.discord_client.ConfigLoader") as MockLoader:
        instance = MockLoader.return_value
        instance.load_config.return_value = {
            "DISCORD_WEBHOOK_URL": webhook_url,
        }
        client = DiscordClient()
    # Ensure the webhook URL is correctly set even after __init__ completes
    client.webhook_url = webhook_url
    return client


# ---------------------------------------------------------------------------
# 1. 1,900자 분할 전송
# ---------------------------------------------------------------------------

def test_long_message_split_into_multiple_sends():
    """A 3000-char message is split and send_message is called 2+ times."""
    client = _make_client()
    # Build a message that is guaranteed to exceed MAX_LEN (1900)
    # Use lines of 100 chars each — 30 lines = 3000 chars total
    line = "A" * 99  # 99 chars + "\n" = 100 per line
    message = "\n".join([line] * 30)
    assert len(message) > DiscordClient.MAX_LEN

    with patch.object(client, "send_message") as mock_send:
        client.send(message)

    assert mock_send.call_count >= 2


# ---------------------------------------------------------------------------
# 2. 1,900자 미만 → 단일 전송
# ---------------------------------------------------------------------------

def test_short_message_single_send():
    """A message shorter than MAX_LEN is sent in a single call."""
    client = _make_client()
    message = "안녕하세요 " * 10  # well under 1900 chars

    with patch.object(client, "send_message") as mock_send:
        client.send(message)

    mock_send.assert_called_once()


# ---------------------------------------------------------------------------
# 3. webhook URL 미설정 시 no-op
# ---------------------------------------------------------------------------

def test_no_webhook_url_is_noop():
    """send_message returns without error when webhook_url is not set."""
    client = _make_client(webhook_url=None)
    # Override to simulate missing URL
    client.webhook_url = None

    with patch("requests.post") as mock_post:
        client.send_message("test message")

    mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# 4. send_alert() 포맷 확인
# ---------------------------------------------------------------------------

def test_send_alert_format():
    """send_alert() builds the expected message format and calls send_message."""
    client = _make_client()

    with patch.object(client, "send_message") as mock_send:
        client.send_alert(
            title="삼성전자 급등",
            link="https://news.example.com/123",
            keyword="삼성전자",
        )

    mock_send.assert_called_once()
    sent_message = mock_send.call_args[0][0]
    assert "삼성전자" in sent_message
    assert "삼성전자 급등" in sent_message
    assert "https://news.example.com/123" in sent_message


# ---------------------------------------------------------------------------
# 5. 긴 메시지 줄 단위 분할 정확성 — 각 청크가 MAX_LEN 이하
# ---------------------------------------------------------------------------

def test_each_chunk_respects_max_len():
    """Every chunk passed to send_message must be <= MAX_LEN characters."""
    client = _make_client()
    line = "B" * 190  # 190 chars per line; 10 lines per chunk max
    message = "\n".join([line] * 20)  # 20 lines → must split

    chunks = []
    with patch.object(client, "send_message", side_effect=lambda m: chunks.append(m)):
        client.send(message)

    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= DiscordClient.MAX_LEN, (
            f"Chunk length {len(chunk)} exceeds MAX_LEN {DiscordClient.MAX_LEN}"
        )
