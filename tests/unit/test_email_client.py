"""Unit tests for MultiAccountEmailManager (Gmail & School Outlook)."""
import email.message
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch
from src.servers.email_client import (
    EmailAccountConfig,
    MultiAccountEmailManager,
    decode_mime_words,
    extract_plain_body,
)


def test_decode_mime_words() -> None:
    # Plain ascii
    assert decode_mime_words("Simple Subject") == "Simple Subject"
    # RFC 2047 encoded
    encoded = "=?utf-8?b?VGVzdCBTdWJqZWN0?="
    assert decode_mime_words(encoded) == "Test Subject"
    # None/empty
    assert decode_mime_words(None) == ""


def test_extract_plain_body_plain_text() -> None:
    msg = email.message.EmailMessage()
    msg.set_content("Hello from team, please review Q3 budget.")
    body = extract_plain_body(msg)
    assert "review Q3 budget" in body


def test_extract_plain_body_html_stripping() -> None:
    msg = email.message.EmailMessage()
    msg.add_header("Content-Type", "text/html")
    msg.set_payload("<html><body><p>Class is rescheduled to <b>Friday 3 PM</b>.</p></body></html>")
    body = extract_plain_body(msg)
    assert "Class is rescheduled to Friday 3 PM" in body
    assert "<html>" not in body


def test_load_accounts_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GMAIL_USER", "personal@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setenv("OUTLOOK_USER", "student@university.edu")
    monkeypatch.setenv("OUTLOOK_PASSWORD", "secret_pass_123")

    manager = MultiAccountEmailManager()
    accounts = manager.get_configured_accounts()

    assert len(accounts) == 2
    acc_ids = [a["account_id"] for a in accounts]
    assert "personal" in acc_ids
    assert "school" in acc_ids

    personal = next(a for a in manager.accounts if a.account_id == "personal")
    assert personal.server == "imap.gmail.com"
    assert personal.username == "personal@gmail.com"
    assert personal.password == "abcdefghijklmnop"  # Spaces stripped

    school = next(a for a in manager.accounts if a.account_id == "school")
    assert school.server == "outlook.office365.com"
    assert school.username == "student@university.edu"


def test_mocked_imap_fetch() -> None:
    account = EmailAccountConfig(
        account_id="personal",
        label="Personal Gmail",
        server="imap.gmail.com",
        port=993,
        username="personal@gmail.com",
        password="secretpassword",
    )

    manager = MultiAccountEmailManager()

    # Create mock raw email
    raw_bytes = (
        b"From: professor@university.edu\r\n"
        b"To: student@university.edu\r\n"
        b"Subject: Assignment 1 Due Date\r\n"
        b"Date: Fri, 05 Sep 2026 09:00:00 +0800\r\n"
        b"\r\n"
        b"The due date has been extended to next Monday.\r\n"
    )

    with patch("imaplib.IMAP4_SSL") as mock_imap_cls:
        mock_imap = MagicMock()
        mock_imap_cls.return_value = mock_imap
        mock_imap.login.return_value = ("OK", [b"LOGIN completed"])
        mock_imap.select.return_value = ("OK", [b"1"])
        mock_imap.search.return_value = ("OK", [b"101"])
        mock_imap.fetch.return_value = ("OK", [(b"101 (BODY[]", raw_bytes)])

        emails = manager.fetch_unread_for_account(account=account, limit=5)

        # Ensure search was for UNSEEN and fetch used BODY.PEEK
        mock_imap.search.assert_called_with(None, "UNSEEN")
        mock_imap.fetch.assert_called_with(b"101", "(BODY.PEEK[])")

        assert len(emails) == 1
        e = emails[0]
        assert e["subject"] == "Assignment 1 Due Date"
        assert e["sender"] == "professor@university.edu"
        assert "extended to next Monday" in e["body"]
        assert e["account"] == "personal"


def test_mocked_smtp_send(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    account = EmailAccountConfig(
        account_id="personal",
        label="Personal Gmail",
        server="imap.gmail.com",
        port=993,
        username="personal@gmail.com",
        password="secretpassword",
        smtp_server="smtp.gmail.com",
        smtp_port=465,
        smtp_use_ssl=True,
    )

    manager = MultiAccountEmailManager()

    with patch("smtplib.SMTP_SSL") as mock_smtp_cls:
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_smtp

        result = manager.send_email_for_account(
            account=account,
            to="sarah.connor@example.com",
            subject="Status Update",
            body="All tests are passing smoothly.",
            in_reply_to="msg_sarah_123",
        )

        assert result["status"] == "success"
        assert result["from"] == "personal@gmail.com"
        assert result["to"] == "sarah.connor@example.com"
        assert result["subject"] == "Status Update"

        mock_smtp.login.assert_called_once_with("personal@gmail.com", "secretpassword")
        mock_smtp.send_message.assert_called_once()
        sent_msg = mock_smtp.send_message.call_args[0][0]
        assert sent_msg["To"] == "sarah.connor@example.com"
        assert sent_msg["From"] == "personal@gmail.com"
        assert sent_msg["Subject"] == "Status Update"
        assert sent_msg["In-Reply-To"] == "msg_sarah_123"

        # Verify sent archive was written to data/drafts/sent/
        sent_dir = tmp_path / "drafts" / "sent"
        assert sent_dir.exists()
        sent_json = list(sent_dir.glob("*.json"))
        assert len(sent_json) == 1
        sent_eml = list(sent_dir.glob("*.eml"))
        assert len(sent_eml) == 1


def test_mocked_smtp_send_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    account = EmailAccountConfig(
        account_id="personal",
        label="Personal Gmail",
        server="imap.gmail.com",
        port=993,
        username="personal@gmail.com",
        password="secretpassword",
        smtp_server="smtp.gmail.com",
        smtp_port=465,
        smtp_use_ssl=True,
    )
    manager = MultiAccountEmailManager()

    with patch("smtplib.SMTP_SSL", side_effect=Exception("Connection refused")):
        result = manager.send_email_for_account(
            account=account,
            to="fail@example.com",
            subject="Fail",
            body="Fail body",
        )
        assert result["status"] == "error"
        assert "SMTP transmission failed" in result["message"]
