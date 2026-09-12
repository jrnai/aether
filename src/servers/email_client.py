"""Multi-account IMAP and SMTP client for live email triage, draft staging, and HITL sending."""
import email
import email.header
import email.message
import email.utils
import imaplib
import json
import logging
import os
import re
import smtplib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger("aether.email_client")


@dataclass
class EmailAccountConfig:
    """Configuration for an IMAP and SMTP email account."""
    account_id: str          # e.g. "personal", "school"
    label: str               # e.g. "Personal Gmail", "School Outlook"
    server: str              # e.g. "imap.gmail.com", "outlook.office365.com"
    port: int                # e.g. 993
    username: str            # email address
    password: str            # password or app password
    use_ssl: bool = True     # standard SSL connection for IMAP
    smtp_server: str = ""    # e.g. "smtp.gmail.com", "smtp.office365.com"
    smtp_port: int = 465     # e.g. 465 (SSL) or 587 (STARTTLS)
    smtp_use_ssl: bool = True


def decode_mime_words(s: str | None) -> str:
    """Decode MIME-encoded email headers (RFC 2047) into Unicode string."""
    if not s:
        return ""
    try:
        decoded_parts = email.header.decode_header(s)
        result = []
        for part, enc in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(enc or "utf-8", errors="replace"))
            else:
                result.append(str(part))
        return "".join(result).strip()
    except Exception:
        return str(s).strip()


def extract_plain_body(msg: email.message.Message) -> str:
    """Extract plain text body from an email Message object."""
    body_text = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            # Skip attachments
            if "attachment" in content_disposition:
                continue

            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body_text = payload.decode(charset, errors="replace")
                    break
            elif content_type == "text/html" and not body_text:
                # Fallback to HTML if plain text not found
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    raw_html = payload.decode(charset, errors="replace")
                    # Clean tags
                    body_text = re.sub(r"<[^<]+?>", " ", raw_html)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            body_text = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                body_text = re.sub(r"<[^<]+?>", " ", body_text)

    # Normalize whitespace
    return re.sub(r"\s+", " ", body_text).strip()


def is_valid_credential(val: str | None) -> bool:
    """Check if a credential value is set and not a placeholder template string."""
    if not val:
        return False
    v = val.strip().lower()
    placeholders = {
        "yourname@gmail.com",
        "your_personal_email@gmail.com",
        "xxxx xxxx xxxx xxxx",
        "your_school_email@university.edu",
        "your_school_password",
        "your_student_id@university.edu",
    }
    if v in placeholders or "xxxx" in v or v.startswith("your_"):
        return False
    return True


class MultiAccountEmailManager:
    """Manages connections and message fetching across multiple live email accounts."""

    def __init__(self, env_path: str | None = None) -> None:
        if env_path is not None:
            load_dotenv(dotenv_path=env_path, override=True)
        else:
            load_dotenv(override=False)
        self.accounts: list[EmailAccountConfig] = self._load_accounts_from_env()

    def _load_accounts_from_env(self) -> list[EmailAccountConfig]:
        """Detect and configure email accounts from environment variables."""
        accounts: list[EmailAccountConfig] = []

        # 1. Personal Gmail
        gmail_user = os.environ.get("GMAIL_USER") or os.environ.get("PERSONAL_EMAIL")
        gmail_pass = os.environ.get("GMAIL_APP_PASSWORD") or os.environ.get("PERSONAL_PASSWORD")
        if is_valid_credential(gmail_user) and is_valid_credential(gmail_pass):
            accounts.append(
                EmailAccountConfig(
                    account_id="personal",
                    label="Personal Gmail",
                    server=os.environ.get("GMAIL_IMAP_SERVER", "imap.gmail.com"),
                    port=int(os.environ.get("GMAIL_IMAP_PORT", "993")),
                    username=gmail_user.strip(),
                    password=gmail_pass.strip().replace(" ", ""),  # Remove spaces often copied in app passwords
                    use_ssl=True,
                    smtp_server=os.environ.get("GMAIL_SMTP_SERVER", "smtp.gmail.com"),
                    smtp_port=int(os.environ.get("GMAIL_SMTP_PORT", "465")),
                    smtp_use_ssl=True,
                )
            )

        # 2. School Outlook / Office 365
        outlook_user = os.environ.get("OUTLOOK_USER") or os.environ.get("SCHOOL_EMAIL")
        outlook_pass = os.environ.get("OUTLOOK_PASSWORD") or os.environ.get("SCHOOL_PASSWORD")
        if is_valid_credential(outlook_user) and is_valid_credential(outlook_pass):
            accounts.append(
                EmailAccountConfig(
                    account_id="school",
                    label="School Outlook",
                    server=os.environ.get("OUTLOOK_IMAP_SERVER", "outlook.office365.com"),
                    port=int(os.environ.get("OUTLOOK_IMAP_PORT", "993")),
                    username=outlook_user.strip(),
                    password=outlook_pass.strip(),
                    use_ssl=True,
                    smtp_server=os.environ.get("OUTLOOK_SMTP_SERVER", "smtp.office365.com"),
                    smtp_port=int(os.environ.get("OUTLOOK_SMTP_PORT", "587")),
                    smtp_use_ssl=False,
                )
            )

        # 3. Generic primary account fallback
        generic_user = os.environ.get("IMAP_USER")
        generic_pass = os.environ.get("IMAP_PASSWORD")
        generic_server = os.environ.get("IMAP_SERVER")
        if generic_user and generic_pass and generic_server:
            # Only add if not already covered
            if not any(a.username == generic_user.strip() for a in accounts):
                accounts.append(
                    EmailAccountConfig(
                        account_id="primary",
                        label="Primary IMAP",
                        server=generic_server.strip(),
                        port=int(os.environ.get("IMAP_PORT", "993")),
                        username=generic_user.strip(),
                        password=generic_pass.strip(),
                        use_ssl=True,
                        smtp_server=os.environ.get("SMTP_SERVER", generic_server.strip().replace("imap.", "smtp.")),
                        smtp_port=int(os.environ.get("SMTP_PORT", "465")),
                        smtp_use_ssl=True,
                    )
                )

        return accounts

    def get_configured_accounts(self) -> list[dict[str, Any]]:
        """Return list of configured account metadata (omitting passwords)."""
        return [
            {
                "account_id": a.account_id,
                "label": a.label,
                "server": a.server,
                "port": a.port,
                "username": a.username,
                "smtp_server": a.smtp_server,
                "smtp_port": a.smtp_port,
            }
            for a in self.accounts
        ]

    def test_connection(self, account_id: str) -> dict[str, Any]:
        """Test IMAP connection and credentials for a specific account."""
        account = next((a for a in self.accounts if a.account_id == account_id), None)
        if not account:
            return {"status": "error", "message": f"Account '{account_id}' not found in configuration."}

        try:
            client = imaplib.IMAP4_SSL(host=account.server, port=account.port, timeout=10.0)
            client.login(account.username, account.password)
            client.select("INBOX", readonly=True)
            status, count_data = client.search(None, "ALL")
            client.logout()

            total_messages = len(count_data[0].split()) if status == "OK" and count_data[0] else 0
            return {
                "status": "success",
                "account_id": account.account_id,
                "label": account.label,
                "username": account.username,
                "message": f"Successfully connected to {account.server} ({total_messages} total messages found in INBOX).",
            }
        except Exception as e:
            return {
                "status": "error",
                "account_id": account.account_id,
                "label": account.label,
                "username": account.username,
                "message": f"Connection failed: {e}",
            }

    def fetch_unread_for_account(
        self,
        account: EmailAccountConfig,
        limit: int = 10,
        folder: str = "INBOX",
    ) -> list[dict[str, Any]]:
        """Fetch unread emails from a single IMAP account using read-only PEEK."""
        results: list[dict[str, Any]] = []
        client = None

        try:
            client = imaplib.IMAP4_SSL(host=account.server, port=account.port, timeout=12.0)
            client.login(account.username, account.password)
            # Select folder with readonly=True so we do not modify message flags
            client.select(folder, readonly=True)

            status, search_data = client.search(None, "UNSEEN")
            if status != "OK" or not search_data or not search_data[0]:
                return []

            msg_ids = search_data[0].split()
            # Most recent unread emails first
            recent_ids = msg_ids[-limit:]
            recent_ids.reverse()

            for mid in recent_ids:
                # Use BODY.PEEK[] so the email remains UNREAD on the server!
                res, fetch_data = client.fetch(mid, "(BODY.PEEK[])")
                if res != "OK" or not fetch_data:
                    continue

                for response_part in fetch_data:
                    if isinstance(response_part, tuple) and len(response_part) > 1:
                        raw_email = response_part[1]
                        msg = email.message_from_bytes(raw_email)

                        subject = decode_mime_words(msg.get("Subject", "No Subject"))
                        sender = decode_mime_words(msg.get("From", "Unknown Sender"))
                        date_header = msg.get("Date", "")

                        try:
                            date_tuple = email.utils.parsedate_to_datetime(date_header)
                            date_iso = date_tuple.astimezone().isoformat()
                        except Exception:
                            date_iso = datetime.now().astimezone().isoformat()

                        body = extract_plain_body(msg)
                        unique_id = f"live_{account.account_id}_{mid.decode('ascii', errors='ignore')}"

                        results.append({
                            "id": unique_id,
                            "account": account.account_id,
                            "account_label": account.label,
                            "sender": sender,
                            "subject": subject,
                            "date": date_iso,
                            "read": False,
                            "body": body,
                        })
        except Exception as e:
            logger.warning("Failed to fetch from account '%s' (%s): %s", account.label, account.username, e)
        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass
                try:
                    client.logout()
                except Exception:
                    pass

        return results

    def fetch_all_unread(
        self,
        limit_per_account: int = 10,
        account_filter: str | None = None,
        folder: str = "INBOX",
    ) -> list[dict[str, Any]]:
        """Fetch unread emails across all configured accounts or a specified account."""
        if not self.accounts:
            return []

        target_accounts = self.accounts
        if account_filter and account_filter.lower() not in ("all", "both", "any"):
            filter_clean = account_filter.strip().lower()
            target_accounts = [
                a for a in self.accounts
                if filter_clean in a.account_id.lower() or filter_clean in a.label.lower()
            ]
            # If specific filter didn't match ID, match email domain
            if not target_accounts:
                target_accounts = [a for a in self.accounts if filter_clean in a.username.lower()]

        all_emails: list[dict[str, Any]] = []
        for account in target_accounts:
            account_emails = self.fetch_unread_for_account(
                account=account,
                limit=limit_per_account,
                folder=folder,
            )
            all_emails.extend(account_emails)

        # Sort by date descending
        all_emails.sort(key=lambda x: x.get("date", ""), reverse=True)
        return all_emails

    @staticmethod
    def _archive_sent_email(
        from_addr: str,
        to: str,
        subject: str,
        body: str,
        timestamp: str,
        in_reply_to: str | None = None,
    ) -> str:
        """Archive sent email locally in data/drafts/sent/ for transparency and auditing."""
        try:
            data_dir = Path(os.environ.get("AETHER_DATA_DIR", "./data")).resolve()
            sent_dir = data_dir / "drafts" / "sent"
            sent_dir.mkdir(parents=True, exist_ok=True)
            sent_id = f"sent_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.urandom(3).hex()}"

            payload = {
                "sent_id": sent_id,
                "from": from_addr,
                "to": to,
                "subject": subject,
                "body": body,
                "in_reply_to": in_reply_to,
                "sent_at": timestamp,
            }
            with open(sent_dir / f"{sent_id}.json", "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)

            eml_path = sent_dir / f"{sent_id}.eml"
            eml_content = (
                f"From: {from_addr}\n"
                f"To: {to}\n"
                f"Subject: {subject}\n"
                f"Date: {timestamp}\n"
            )
            if in_reply_to:
                eml_content += f"In-Reply-To: {in_reply_to}\nReferences: {in_reply_to}\n"
            eml_content += f"\n{body}\n"

            with open(eml_path, "w", encoding="utf-8") as f:
                f.write(eml_content)

            return sent_id
        except Exception as e:
            logger.warning("Could not archive sent email to disk: %s", e)
            return ""

    def send_email_for_account(
        self,
        account: EmailAccountConfig,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> dict[str, Any]:
        """Send an email over SMTP for a specific configured account."""
        if not account.smtp_server:
            return {
                "status": "error",
                "message": f"Account '{account.label}' does not have an SMTP server configured.",
            }

        msg = email.message.EmailMessage()
        msg["From"] = account.username
        msg["To"] = to
        msg["Subject"] = subject
        msg["Date"] = email.utils.formatdate(localtime=True)
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        msg.set_content(body)

        try:
            if account.smtp_use_ssl or account.smtp_port == 465:
                with smtplib.SMTP_SSL(host=account.smtp_server, port=account.smtp_port, timeout=15.0) as smtp:
                    smtp.login(account.username, account.password)
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(host=account.smtp_server, port=account.smtp_port, timeout=15.0) as smtp:
                    smtp.ehlo()
                    smtp.starttls()
                    smtp.ehlo()
                    smtp.login(account.username, account.password)
                    smtp.send_message(msg)

            sent_timestamp = datetime.now().astimezone().isoformat()
            sent_id = self._archive_sent_email(
                from_addr=account.username,
                to=to,
                subject=subject,
                body=body,
                timestamp=sent_timestamp,
                in_reply_to=in_reply_to,
            )

            return {
                "status": "success",
                "sent_id": sent_id,
                "account": account.account_id,
                "from": account.username,
                "to": to,
                "subject": subject,
                "timestamp": sent_timestamp,
                "message": f"Email successfully sent to '{to}' from '{account.username}' via {account.smtp_server}.",
            }
        except Exception as e:
            logger.error("Failed to send email to '%s' via '%s': %s", to, account.smtp_server, e)
            return {
                "status": "error",
                "account": account.account_id,
                "from": account.username,
                "to": to,
                "subject": subject,
                "message": f"SMTP transmission failed: {e}",
            }

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        account_id: str | None = None,
        in_reply_to: str | None = None,
    ) -> dict[str, Any]:
        """Find matching account and dispatch email via SMTP."""
        if not self.accounts:
            return {
                "status": "error",
                "message": "No live email accounts configured with valid credentials in .env.",
            }

        target_acc = None
        if account_id and account_id.lower() not in ("all", "both", "any", "primary", "default"):
            filter_clean = account_id.strip().lower()
            target_acc = next(
                (
                    a for a in self.accounts
                    if filter_clean in a.account_id.lower()
                    or filter_clean in a.label.lower()
                    or filter_clean in a.username.lower()
                ),
                None,
            )

        if not target_acc:
            target_acc = self.accounts[0]

        return self.send_email_for_account(
            account=target_acc,
            to=to,
            subject=subject,
            body=body,
            in_reply_to=in_reply_to,
        )
