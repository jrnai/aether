import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from src.servers.mail_server import (
    fetch_unread_emails,
    get_email_details,
    stage_email_draft,
    send_email,
    load_inbox_emails,
)


@pytest.fixture(autouse=True)
def isolate_mail_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tests run against an isolated data directory with test fixture emails."""
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GMAIL_USER", "")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "")
    monkeypatch.setenv("OUTLOOK_USER", "")
    monkeypatch.setenv("OUTLOOK_PASSWORD", "")
    monkeypatch.setenv("SCHOOL_EMAIL", "")
    monkeypatch.setenv("SCHOOL_PASSWORD", "")
    monkeypatch.setenv("IMAP_USER", "")
    monkeypatch.setenv("IMAP_PASSWORD", "")
    monkeypatch.setenv("IMAP_SERVER", "")
    monkeypatch.setenv("MS_GRAPH_CLIENT_ID", "")
    sample_emails = [
        {
            "id": "msg_sarah_budget",
            "account": "personal",
            "account_label": "Personal Gmail",
            "sender": "sarah.connor@example.com",
            "subject": "Q3 Budget Review Reschedule",
            "date": "2026-09-04T09:15:00+08:00",
            "read": False,
            "body": "Hey team, can we move tomorrow's budget review to Friday afternoon? Let me know if that works.",
        },
        {
            "id": "msg_alex_domain",
            "account": "personal",
            "account_label": "Personal Gmail",
            "sender": "alex.tech@example.com",
            "subject": "Domain renewal invoice ready",
            "date": "2026-09-04T11:42:00+08:00",
            "read": False,
            "body": "Your annual domain registration for aether-agent.local is due next Tuesday.",
        },
    ]
    with open(tmp_path / "mail_inbox.json", "w", encoding="utf-8") as f:
        json.dump(sample_emails, f)


def test_fetch_unread_emails_quarantines_untrusted_content() -> None:
    emails = fetch_unread_emails(limit=5)
    assert len(emails) >= 2

    for msg in emails:
        assert "id" in msg
        assert "sender" in msg
        assert "subject" in msg
        preview = msg["preview"]
        assert "<untrusted_content" in preview
        assert "</untrusted_content>" in preview
        assert f'source="email"' in preview
        assert f'id="{msg["id"]}"' in preview


def test_get_email_details_existing_and_nonexistent() -> None:
    details = get_email_details("msg_sarah_budget")
    assert details["sender"] == "sarah.connor@example.com"
    assert "budget review" in details["content"].lower()
    assert "<untrusted_content" in details["content"]

    missing = get_email_details("nonexistent_id_999")
    assert missing["status"] == "error"


def test_stage_email_draft_creates_eml_and_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))

    res = stage_email_draft(
        to="sarah.connor@example.com",
        subject="Re: Q3 Budget Review Reschedule",
        body="Friday afternoon at 2 PM works great for me.",
        in_reply_to="msg_sarah_budget",
    )

    assert res["status"] == "success"
    assert "draft_" in res["draft_id"]

    drafts_dir = tmp_path / "drafts"
    assert drafts_dir.exists()

    # Check .eml file
    eml_file = drafts_dir / f"{res['draft_id']}.eml"
    assert eml_file.exists()
    eml_content = eml_file.read_text(encoding="utf-8")
    assert "To: sarah.connor@example.com" in eml_content
    assert "Subject: Re: Q3 Budget Review Reschedule" in eml_content
    assert "X-Unsent: 1" in eml_content
    assert "Friday afternoon at 2 PM works great for me." in eml_content

    # Check .json metadata
    json_file = drafts_dir / f"{res['draft_id']}.json"
    assert json_file.exists()


def test_send_email_validations_and_dispatch() -> None:
    # Validation errors
    err1 = send_email(to="", subject="Hi", body="Text")
    assert err1["status"] == "error"
    assert "Recipient email address" in err1["message"]

    err2 = send_email(to="test@example.com", subject="Hi", body="")
    assert err2["status"] == "error"
    assert "body ('body') cannot be empty" in err2["message"]

    # Mock dispatch
    with patch("src.servers.mail_server.MultiAccountEmailManager") as mock_mgr_cls:
        mock_mgr = MagicMock()
        mock_mgr_cls.return_value = mock_mgr
        mock_mgr.send_email.return_value = {
            "status": "success",
            "from": "sender@gmail.com",
            "to": "sarah@example.com",
            "subject": "Re: Budget",
            "message": "Email successfully sent",
        }

        res = send_email(
            to="sarah@example.com",
            subject="Re: Budget",
            body="Approved!",
            account="personal",
        )
        assert res["status"] == "success"
        mock_mgr.send_email.assert_called_once_with(
            to="sarah@example.com",
            subject="Re: Budget",
            body="Approved!",
            account_id="personal",
            in_reply_to=None,
        )
