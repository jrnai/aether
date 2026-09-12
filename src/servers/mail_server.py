"""FastMCP server for multi-account email triage, untrusted content quarantine, and draft staging."""
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from src.servers.email_client import MultiAccountEmailManager
from src.servers.outlook_graph_client import OutlookGraphManager

mcp = FastMCP("MailService")

IMPORTANT_KEYWORDS = [
    "urgent", "action required", "important", "invitation", "appointment",
    "doctor", "interview", "offer", "deadline", "security alert",
    "verification code", "reminder", "schedule", "exam", "test"
]


def detect_importance(subject: str = "", body: str = "", sender: str = "") -> bool:
    """Heuristic check whether an email has high importance."""
    text = f"{subject} {body[:300]} {sender}".lower()
    return any(kw in text for kw in IMPORTANT_KEYWORDS)


def normalize_email_flags(msg: dict[str, Any]) -> dict[str, Any]:
    """Ensure standard boolean flags exist on email dictionaries."""
    msg["read"] = bool(msg.get("read", False))
    msg["starred"] = bool(msg.get("starred", False))
    msg["pinned"] = bool(msg.get("pinned", False))
    if "important" not in msg:
        msg["important"] = detect_importance(
            subject=msg.get("subject", ""),
            body=msg.get("body", ""),
            sender=msg.get("sender", ""),
        )
    else:
        msg["important"] = bool(msg["important"])
    return msg


def is_within_days(date_str: str, days: int) -> bool:
    """Return True if ISO date_str occurred within the last `days` days."""
    if not date_str:
        return False
    try:
        dt = datetime.fromisoformat(date_str)
    except Exception:
        try:
            import email.utils
            dt = email.utils.parsedate_to_datetime(date_str)
        except Exception:
            return True
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    cutoff = now - timedelta(days=days)
    return dt >= cutoff


def get_mail_dir() -> Path:
    """Return the root data directory for local mail and drafts."""
    data_dir = Path(os.environ.get("AETHER_DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "drafts").mkdir(parents=True, exist_ok=True)
    return data_dir


def load_inbox_emails() -> list[dict[str, Any]]:
    """Load local/cached email inbox messages with normalized flags."""
    mail_dir = get_mail_dir()
    inbox_file = mail_dir / "mail_inbox.json"

    if not inbox_file.exists():
        return []

    try:
        with open(inbox_file, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return [normalize_email_flags(e) for e in data]
            return []
    except Exception:
        return []


def save_inbox_emails(emails: list[dict[str, Any]]) -> None:
    """Save email inbox messages to local store with normalized flags."""
    mail_dir = get_mail_dir()
    inbox_file = mail_dir / "mail_inbox.json"
    normalized = [normalize_email_flags(e) for e in emails]
    with open(inbox_file, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2)


def wrap_untrusted(content: str, email_id: str, sender: str, account: str = "") -> str:
    """Quarantine untrusted external email content within security tags."""
    acc_attr = f' account="{account}"' if account else ""
    return f'<untrusted_content source="email" id="{email_id}" sender="{sender}"{acc_attr}>\n{content.strip()}\n</untrusted_content>'


@mcp.tool()
def update_email_flag(email_id: str, flag: str, value: bool | None = None) -> dict[str, Any]:
    """Toggle or set an email flag (read, starred, pinned, important)."""
    valid_flags = {"read", "starred", "pinned", "important"}
    flag_clean = flag.strip().lower()
    if flag_clean not in valid_flags:
        return {
            "status": "error",
            "message": f"Invalid flag '{flag}'. Must be one of: {sorted(list(valid_flags))}",
        }

    emails = load_inbox_emails()
    target = None
    for em in emails:
        if em.get("id") == email_id:
            target = em
            break

    if not target:
        return {"status": "error", "message": f"Email with ID '{email_id}' not found."}

    if value is None:
        target[flag_clean] = not target.get(flag_clean, False)
    else:
        target[flag_clean] = bool(value)

    save_inbox_emails(emails)
    return {
        "status": "success",
        "id": email_id,
        "flag": flag_clean,
        "value": target[flag_clean],
        "email": target,
    }


@mcp.tool()
def get_filtered_emails(
    status: str = "all",
    days: str | int | None = None,
    flag: str = "all",
    search: str = "",
    account: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Filter emails by status (read/unread/all), time window (1/5/7 days/all), flags (pinned/starred/important), and search query."""
    emails = load_inbox_emails()

    # Aggregate counts across entire dataset
    total_count = len(emails)
    unread_count = sum(1 for e in emails if not e.get("read", False))
    read_count = sum(1 for e in emails if e.get("read", False))
    starred_count = sum(1 for e in emails if e.get("starred", False))
    pinned_count = sum(1 for e in emails if e.get("pinned", False))
    important_count = sum(1 for e in emails if e.get("important", False))

    filtered = emails

    # 1. Account filter
    if account and account.lower() not in ("all", "both", "any"):
        ac = account.strip().lower()
        filtered = [
            e for e in filtered
            if ac in e.get("account", "").lower() or ac in e.get("account_label", "").lower()
        ]

    # 2. Status filter
    status_clean = (status or "all").strip().lower()
    if status_clean == "unread":
        filtered = [e for e in filtered if not e.get("read", False)]
    elif status_clean == "read":
        filtered = [e for e in filtered if e.get("read", False)]

    # 3. Flag filter
    flag_clean = (flag or "all").strip().lower()
    if flag_clean == "pinned":
        filtered = [e for e in filtered if e.get("pinned", False)]
    elif flag_clean == "starred":
        filtered = [e for e in filtered if e.get("starred", False)]
    elif flag_clean == "important":
        filtered = [e for e in filtered if e.get("important", False)]

    # 4. Days cutoff
    if days is not None and str(days).strip().lower() not in ("all", "none", "0", ""):
        try:
            d_int = int(str(days).strip())
            filtered = [e for e in filtered if is_within_days(e.get("date", ""), d_int)]
        except (ValueError, TypeError):
            pass

    # 5. Search query
    if search:
        s_clean = search.strip().lower()
        filtered = [
            e for e in filtered
            if s_clean in e.get("subject", "").lower()
            or s_clean in e.get("sender", "").lower()
            or s_clean in e.get("body", "").lower()
        ]

    # 6. Sorting: Pinned items first, then date descending
    def sort_key(e: dict[str, Any]):
        is_pin = 1 if e.get("pinned", False) else 0
        date_str = e.get("date", "")
        return (is_pin, date_str)

    filtered.sort(key=sort_key, reverse=True)

    # Format result items with quarantined previews
    presented: list[dict[str, Any]] = []
    for msg in filtered[:limit]:
        body_snippet = msg.get("body", "")[:250]
        item = dict(msg)
        item["preview"] = wrap_untrusted(
            body_snippet,
            msg.get("id", ""),
            msg.get("sender", ""),
            account=msg.get("account_label", msg.get("account", "")),
        )
        presented.append(item)

    return {
        "emails": presented,
        "count": len(presented),
        "total_count": total_count,
        "unread_count": unread_count,
        "read_count": read_count,
        "starred_count": starred_count,
        "pinned_count": pinned_count,
        "important_count": important_count,
    }


@mcp.tool()
def fetch_unread_emails(
    limit: int = 10,
    folder: str = "INBOX",
    account: str | None = None,
    max_count: int | None = None,
    count: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch unread emails across personal and school accounts. Body snippets are quarantined in <untrusted_content> tags."""
    if max_count is not None:
        limit = max_count
    elif count is not None:
        limit = count

    # 1. Attempt live IMAP fetch (e.g. Gmail)
    manager = MultiAccountEmailManager()
    live_emails = manager.fetch_all_unread(limit_per_account=limit, account_filter=account, folder=folder)

    # 2. Attempt live Microsoft Graph fetch (e.g. School Outlook)
    outlook_manager = OutlookGraphManager()
    if outlook_manager.is_configured() and outlook_manager.is_logged_in():
        if not account or any(k in account.lower() for k in ("all", "both", "any", "school", "outlook", "ntu")):
            outlook_emails = outlook_manager.fetch_unread_emails(limit=limit)
            live_emails.extend(outlook_emails)

    has_live_accounts = bool(manager.accounts or (outlook_manager.is_configured() and outlook_manager.is_logged_in()))

    if has_live_accounts:
        if live_emails:
            cached = load_inbox_emails()
            cached_by_id = {e["id"]: e for e in cached}
            merged: list[dict[str, Any]] = []

            for live in live_emails:
                if live["id"] in cached_by_id:
                    old = cached_by_id[live["id"]]
                    live["pinned"] = old.get("pinned", False)
                    live["starred"] = old.get("starred", False)
                    live["important"] = old.get("important", False)
                    if old.get("read") is True:
                        live["read"] = True
                else:
                    normalize_email_flags(live)
                merged.append(live)

            # Preserve cached emails not in current live fetch
            live_ids = {e["id"] for e in live_emails}
            for c in cached:
                if c.get("id") not in live_ids:
                    merged.append(c)

            save_inbox_emails(merged)
        emails_to_present = live_emails
    else:
        # Fallback to local offline cache
        cached = load_inbox_emails()
        if account and account.lower() not in ("all", "both", "any"):
            filter_clean = account.strip().lower()
            cached = [
                e for e in cached
                if filter_clean in e.get("account", "").lower() or filter_clean in e.get("account_label", "").lower()
            ]
        emails_to_present = [e for e in cached if not e.get("read", False)]

    results: list[dict[str, Any]] = []
    for msg in emails_to_present[:limit]:
        body_snippet = msg.get("body", "")[:250]
        results.append({
            "id": msg["id"],
            "account": msg.get("account", "primary"),
            "account_label": msg.get("account_label", "Email"),
            "sender": msg["sender"],
            "subject": msg["subject"],
            "date": msg["date"],
            "read": msg.get("read", False),
            "starred": msg.get("starred", False),
            "pinned": msg.get("pinned", False),
            "important": msg.get("important", False),
            "preview": wrap_untrusted(
                body_snippet,
                msg["id"],
                msg["sender"],
                account=msg.get("account_label", msg.get("account", "")),
            ),
        })

    return results


@mcp.tool()
def get_email_details(email_id: str = "", id: str | None = None) -> dict[str, Any]:
    """Retrieve full email content and headers, enclosed in untrusted quarantine tags."""
    target_id = (email_id or id or "").strip()
    emails = load_inbox_emails()
    for msg in emails:
        if msg.get("id") == target_id:
            return {
                "id": msg["id"],
                "account": msg.get("account", "primary"),
                "account_label": msg.get("account_label", "Email"),
                "sender": msg["sender"],
                "subject": msg["subject"],
                "date": msg["date"],
                "content": wrap_untrusted(
                    msg.get("body", ""),
                    msg["id"],
                    msg["sender"],
                    account=msg.get("account_label", msg.get("account", "")),
                ),
            }

    return {
        "status": "error",
        "message": f"Email with ID '{target_id}' not found.",
    }


@mcp.tool()
def stage_email_draft(
    to: str = "",
    subject: str = "",
    body: str = "",
    in_reply_to: str | None = None,
    account: str | None = None,
    from_account: str | None = None,
    recipient: str | None = None,
    title: str | None = None,
    content: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    """Stage an email draft locally for human review. (Mutating action. NEVER sends directly)."""
    to = (to or recipient or "").strip()
    subject = (subject or title or "No Subject").strip()
    body = (body or content or message or "").strip()
    chosen_account = (from_account or account or "personal").strip().lower()

    manager = MultiAccountEmailManager()
    from_email = ""
    for acc in manager.accounts:
        if chosen_account in acc.account_id.lower() or chosen_account in acc.label.lower():
            from_email = acc.username
            break
    if not from_email and manager.accounts:
        from_email = manager.accounts[0].username

    mail_dir = get_mail_dir()
    drafts_dir = mail_dir / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)

    draft_id = f"draft_{uuid.uuid4().hex[:8]}"
    created_at = datetime.now().astimezone().isoformat()

    draft_payload = {
        "draft_id": draft_id,
        "from": from_email,
        "account": chosen_account,
        "to": to,
        "subject": subject,
        "body": body,
        "in_reply_to": in_reply_to,
        "created_at": created_at,
        "status": "STAGED_DRAFT",
    }

    # Save as JSON draft and .eml formatted file
    json_path = drafts_dir / f"{draft_id}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(draft_payload, f, indent=2)

    eml_path = drafts_dir / f"{draft_id}.eml"
    from_header = f"From: {from_email}\n" if from_email else ""
    eml_content = (
        f"{from_header}"
        f"To: {to}\n"
        f"Subject: {subject}\n"
        f"Date: {created_at}\n"
        f"X-Unsent: 1\n\n"
        f"{body}\n"
    )
    with open(eml_path, "w", encoding="utf-8") as f:
        f.write(eml_content)

    return {
        "status": "success",
        "draft_id": draft_id,
        "account": chosen_account,
        "from": from_email,
        "location": str(eml_path),
        "message": f"Draft staged for '{to}' ({from_email or chosen_account}) with subject '{subject}'. Open {eml_path.name} in your email client to review and send.",
    }


@mcp.tool()
def send_email(
    to: str = "",
    subject: str = "",
    body: str = "",
    in_reply_to: str | None = None,
    account: str | None = None,
    from_account: str | None = None,
    recipient: str | None = None,
    title: str | None = None,
    content: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    """Send an email directly over SMTP after human approval. (Mutating action. Requires HITL authorization)."""
    to = (to or recipient or "").strip()
    subject = (subject or title or "No Subject").strip()
    body = (body or content or message or "").strip()
    chosen_account = (from_account or account or "personal").strip().lower()

    if not to:
        return {
            "status": "error",
            "message": "Recipient email address ('to') is required.",
        }
    if not body:
        return {
            "status": "error",
            "message": "Email message body ('body') cannot be empty.",
        }

    manager = MultiAccountEmailManager()
    return manager.send_email(
        to=to,
        subject=subject,
        body=body,
        account_id=chosen_account,
        in_reply_to=in_reply_to,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
