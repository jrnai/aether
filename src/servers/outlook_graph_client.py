"""Microsoft Graph API client for Microsoft 365 / School Outlook with OAuth2 / Modern Auth."""
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import msal
import requests
from dotenv import load_dotenv

logger = logging.getLogger("aether.outlook_client")

DEFAULT_CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"  # Microsoft public client ID
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read"]


def get_token_cache_path() -> Path:
    """Return path to Outlook token cache file."""
    data_dir = Path(os.environ.get("AETHER_DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "token_outlook.json"


class OutlookGraphManager:
    """Manages Microsoft 365 OAuth authentication and Graph API email access."""

    def __init__(self, env_path: str | None = None) -> None:
        load_dotenv(dotenv_path=env_path, override=True)
        self.client_id = os.environ.get("OUTLOOK_CLIENT_ID", DEFAULT_CLIENT_ID).strip()
        self.username = os.environ.get("OUTLOOK_USER") or os.environ.get("SCHOOL_EMAIL")
        self.authority = os.environ.get("OUTLOOK_AUTHORITY", "https://login.microsoftonline.com/common").strip()
        self.cache_path = get_token_cache_path()
        self.token_cache = msal.SerializableTokenCache()
        self._load_cache()

        self.app = msal.PublicClientApplication(
            client_id=self.client_id,
            authority=self.authority,
            token_cache=self.token_cache,
        )

    def _load_cache(self) -> None:
        """Load token cache from disk if available."""
        if self.cache_path.exists():
            try:
                self.token_cache.deserialize(self.cache_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("Failed to deserialize Outlook token cache: %s", e)

    def _save_cache(self) -> None:
        """Save token cache to disk if modified."""
        if self.token_cache.has_state_changed:
            self.cache_path.write_text(self.token_cache.serialize(), encoding="utf-8")

    def is_configured(self) -> bool:
        """Return True if School Outlook user email is specified in environment."""
        return bool(self.username and "@" in self.username)

    def is_logged_in(self) -> bool:
        """Check if a valid cached account session exists."""
        accounts = self.app.get_accounts()
        return len(accounts) > 0

    def get_token_silent(self) -> str | None:
        """Silently acquire or refresh an access token."""
        accounts = self.app.get_accounts(username=self.username) if self.username else self.app.get_accounts()
        if not accounts:
            accounts = self.app.get_accounts()

        if not accounts:
            return None

        result = self.app.acquire_token_silent(scopes=SCOPES, account=accounts[0])
        self._save_cache()

        if result and "access_token" in result:
            return result["access_token"]
        return None

    def initiate_device_code_flow(self) -> dict[str, Any]:
        """Initiate Device Code Flow for user to authenticate on https://microsoft.com/devicelogin."""
        flow = self.app.initiate_device_flow(scopes=SCOPES)
        return flow

    def complete_device_code_flow(self, flow: dict[str, Any]) -> dict[str, Any]:
        """Wait for and complete the device code flow."""
        result = self.app.acquire_token_by_device_flow(flow)
        self._save_cache()

        if "access_token" in result:
            return {
                "status": "success",
                "message": "Successfully authenticated with Microsoft 365!",
                "username": result.get("id_token_claims", {}).get("preferred_username", self.username),
            }
        else:
            return {
                "status": "error",
                "message": result.get("error_description", result.get("error", "Authentication failed")),
            }

    def fetch_unread_emails(self, limit: int = 10) -> list[dict[str, Any]]:
        """Fetch unread emails from Microsoft Graph API."""
        token = self.get_token_silent()
        if not token:
            logger.info("No active Microsoft token. School Outlook requires login (`python -m src.tools.login_outlook`).")
            return []

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Prefer": 'outlook.body-content-type="text"',
        }

        # Query inbox unread messages
        params = {
            "$filter": "isRead eq false",
            "$top": limit,
            "$select": "id,from,sender,subject,receivedDateTime,bodyPreview,body",
        }

        url = f"{GRAPH_API_BASE}/me/mailFolders/inbox/messages"
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=12.0)
            if resp.status_code == 401:
                # Token expired or revoked
                logger.warning("Microsoft Graph returned 401 Unauthorized.")
                return []

            resp.raise_for_status()
            data = resp.json()
            messages = data.get("value", [])

            results: list[dict[str, Any]] = []
            for msg in messages:
                sender_info = msg.get("from", {}).get("emailAddress", {})
                sender_name = sender_info.get("name", "")
                sender_email = sender_info.get("address", "")
                sender_display = f"{sender_name} <{sender_email}>" if sender_name else sender_email

                body_content = msg.get("body", {}).get("content", "") or msg.get("bodyPreview", "")
                # Strip HTML tags if content is HTML
                if "<" in body_content and ">" in body_content:
                    body_content = re.sub(r"<[^<]+?>", " ", body_content)
                body_content = re.sub(r"\s+", " ", body_content).strip()

                results.append({
                    "id": f"outlook_{msg['id']}",
                    "account": "school",
                    "account_label": "School Outlook",
                    "sender": sender_display,
                    "subject": msg.get("subject", "No Subject"),
                    "date": msg.get("receivedDateTime", ""),
                    "read": False,
                    "body": body_content,
                })

            return results
        except Exception as e:
            logger.warning("Error fetching emails from Microsoft Graph: %s", e)
            return []
