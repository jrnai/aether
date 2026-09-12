"""Unit tests for email filtering, triage flags, and time window queries."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from src.servers.mail_server import (
    detect_importance,
    get_filtered_emails,
    is_within_days,
    normalize_email_flags,
    update_email_flag,
)


@pytest.fixture
def sample_emails():
    now = datetime.now(timezone.utc)
    return [
        {
            "id": "mail_1",
            "account": "personal",
            "account_label": "Personal Gmail",
            "sender": "Professor Tan <tan@ntu.edu.sg>",
            "subject": "Important: SC3021 Exam Schedule",
            "body": "Please review the examination room and schedule for tomorrow.",
            "date": (now - timedelta(hours=2)).isoformat(),
            "read": False,
            "starred": True,
            "pinned": True,
            "important": True,
        },
        {
            "id": "mail_2",
            "account": "school",
            "account_label": "School Outlook",
            "sender": "Library Services <library@ntu.edu.sg>",
            "subject": "Book Due Reminder",
            "body": "Your borrowed book is due in 3 days.",
            "date": (now - timedelta(days=3)).isoformat(),
            "read": False,
            "starred": False,
            "pinned": False,
            "important": False,
        },
        {
            "id": "mail_3",
            "account": "personal",
            "account_label": "Personal Gmail",
            "sender": "Newsletter <news@daily.com>",
            "subject": "Weekly Tech Digest",
            "body": "Here are the top stories of the week.",
            "date": (now - timedelta(days=6)).isoformat(),
            "read": True,
            "starred": False,
            "pinned": False,
            "important": False,
        },
        {
            "id": "mail_4",
            "account": "school",
            "account_label": "School Outlook",
            "sender": "Career Office <career@ntu.edu.sg>",
            "subject": "Interview Invitation with Google",
            "body": "Congratulations, you have been invited to interview.",
            "date": (now - timedelta(days=10)).isoformat(),
            "read": True,
            "starred": True,
            "pinned": False,
            "important": True,
        },
    ]


def test_detect_importance():
    assert detect_importance(subject="Action Required: Verify Account") is True
    assert detect_importance(subject="Doctor Appointment Confirmation") is True
    assert detect_importance(body="Here is your interview schedule") is True
    assert detect_importance(subject="Random spam newsletter") is False


def test_normalize_email_flags():
    raw = {"subject": "Urgent Server Alert"}
    normalized = normalize_email_flags(raw)
    assert normalized["read"] is False
    assert normalized["starred"] is False
    assert normalized["pinned"] is False
    assert normalized["important"] is True


def test_is_within_days():
    now = datetime.now(timezone.utc)
    t_2h = (now - timedelta(hours=2)).isoformat()
    t_3d = (now - timedelta(days=3)).isoformat()
    t_6d = (now - timedelta(days=6)).isoformat()
    t_10d = (now - timedelta(days=10)).isoformat()

    assert is_within_days(t_2h, 1) is True
    assert is_within_days(t_3d, 1) is False
    assert is_within_days(t_3d, 5) is True
    assert is_within_days(t_6d, 5) is False
    assert is_within_days(t_6d, 7) is True
    assert is_within_days(t_10d, 7) is False


def test_filter_by_status(sample_emails):
    with patch("src.servers.mail_server.load_inbox_emails", return_value=sample_emails):
        # All
        res_all = get_filtered_emails(status="all", days="all")
        assert res_all["count"] == 4

        # Unread
        res_unread = get_filtered_emails(status="unread", days="all")
        assert res_unread["count"] == 2
        assert all(not e["read"] for e in res_unread["emails"])

        # Read
        res_read = get_filtered_emails(status="read", days="all")
        assert res_read["count"] == 2
        assert all(e["read"] for e in res_read["emails"])


def test_filter_by_days(sample_emails):
    with patch("src.servers.mail_server.load_inbox_emails", return_value=sample_emails):
        # 1 Day (only mail_1)
        res_1d = get_filtered_emails(status="all", days=1)
        assert res_1d["count"] == 1
        assert res_1d["emails"][0]["id"] == "mail_1"

        # 5 Days (mail_1, mail_2)
        res_5d = get_filtered_emails(status="all", days=5)
        assert res_5d["count"] == 2
        ids_5d = [e["id"] for e in res_5d["emails"]]
        assert "mail_1" in ids_5d
        assert "mail_2" in ids_5d

        # 7 Days (mail_1, mail_2, mail_3)
        res_7d = get_filtered_emails(status="all", days=7)
        assert res_7d["count"] == 3


def test_filter_by_flag(sample_emails):
    with patch("src.servers.mail_server.load_inbox_emails", return_value=sample_emails):
        # Starred (mail_1, mail_4)
        res_starred = get_filtered_emails(status="all", days="all", flag="starred")
        assert res_starred["count"] == 2
        assert all(e["starred"] for e in res_starred["emails"])

        # Pinned (mail_1)
        res_pinned = get_filtered_emails(status="all", days="all", flag="pinned")
        assert res_pinned["count"] == 1
        assert res_pinned["emails"][0]["id"] == "mail_1"

        # Important (mail_1, mail_4)
        res_imp = get_filtered_emails(status="all", days="all", flag="important")
        assert res_imp["count"] == 2


def test_search_and_pinned_sorting(sample_emails):
    with patch("src.servers.mail_server.load_inbox_emails", return_value=sample_emails):
        # Search for Exam
        res_search = get_filtered_emails(status="all", days="all", search="Exam")
        assert res_search["count"] == 1
        assert res_search["emails"][0]["id"] == "mail_1"

        # Verify pinned items sort to the top
        res_all = get_filtered_emails(status="all", days="all")
        assert res_all["emails"][0]["pinned"] is True


def test_update_email_flag(sample_emails):
    with patch("src.servers.mail_server.load_inbox_emails", return_value=sample_emails), \
         patch("src.servers.mail_server.save_inbox_emails") as mock_save:
        # Toggle star on mail_2
        res = update_email_flag("mail_2", "starred")
        assert res["status"] == "success"
        assert res["value"] is True
        mock_save.assert_called_once()

        # Explicit set read to True on mail_1
        res2 = update_email_flag("mail_1", "read", value=True)
        assert res2["status"] == "success"
        assert res2["value"] is True
