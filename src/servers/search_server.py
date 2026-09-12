"""FastMCP server and standalone client for DuckDuckGo web search and web page extraction.

Adheres to Project Aether Threat Model:
- Zero external API keys or credentials required (free, privacy-preserving).
- Automatic quarantine of all external text inside <untrusted_content> tags.
- SSRF defenses blocking private/loopback IP address access in fetch_web_page.
"""
import html as html_lib
import ipaddress
import logging
import re
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from fastmcp import FastMCP

logger = logging.getLogger("aether.search")

mcp = FastMCP("WebSearch")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# SSRF disallowed hosts/IPs
BLOCKED_HOSTNAMES = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "metadata.google.internal",
    "169.254.169.254",
}


def _is_safe_url(url: str) -> tuple[bool, str]:
    """Validate that URL uses http/https and does not target internal or link-local addresses."""
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            return False, f"Unsupported URL scheme '{parsed.scheme}'. Only http and https are allowed."

        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False, "Invalid URL: missing hostname."

        if hostname in BLOCKED_HOSTNAMES:
            return False, f"Access to private/local destination '{hostname}' is blocked for security."

        # Check for numeric IP addresses in private/loopback ranges
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False, f"Access to private IP address '{hostname}' is blocked."
        except ValueError:
            # Not an IP address (regular domain name)
            pass

        return True, ""
    except Exception as e:
        return False, f"Invalid URL: {e}"


def _wrap_untrusted(content: str, source: str = "web_search", **attributes: Any) -> str:
    """Quarantine external web content inside defensive XML-style demarcation tags."""
    attrs = f' source="{source}"'
    for k, v in attributes.items():
        if v is not None:
            clean_v = str(v).replace('"', "'").strip()
            attrs += f' {k}="{clean_v}"'
    return f"<untrusted_content{attrs}>\n{content.strip()}\n</untrusted_content>"


def _clean_html_text(html_content: str) -> str:
    """Extract readable text from HTML, removing script, style, and navigation noise."""
    # Remove script, style, and noscript tags
    text = re.sub(r"<(script|style|noscript|svg|canvas)[^>]*>.*?</\1>", " ", html_content, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML comments
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    # Replace block-level tags with newlines
    text = re.sub(r"<(?:p|div|h[1-6]|li|tr|br|hr)[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Strip remaining HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Unescape HTML entities (&amp;, &lt;, etc.)
    text = html_lib.unescape(text)
    # Normalize multiple whitespaces and excessive blank lines
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    clean_lines = [line for line in lines if line]
    return "\n".join(clean_lines)


@mcp.tool()
def search_web(query: str, max_results: int = 5) -> str:
    """Search the internet using DuckDuckGo (free, zero-API-key, privacy-focused).

    Returns ranked search results including titles, destination URLs, and text snippets,
    quarantined inside defensive <untrusted_content> tags.

    Args:
        query: The search keywords or question.
        max_results: Maximum number of results to return (default: 5, max: 10).
    """
    clean_query = query.strip()
    if not clean_query:
        return "Error: Search query cannot be empty."

    limit = max(1, min(max_results, 10))
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        with httpx.Client(headers=headers, follow_redirects=True, timeout=12.0) as client:
            resp = client.post("https://html.duckduckgo.com/html/", data={"q": clean_query})
            if resp.status_code != 200:
                # Fallback to GET endpoint
                resp = client.get("https://html.duckduckgo.com/html/", params={"q": clean_query})

            if resp.status_code != 200:
                return f"DuckDuckGo search error: received HTTP {resp.status_code}."

            html = resp.text
    except httpx.TimeoutException:
        return "Error: DuckDuckGo search request timed out. Please verify your internet connection."
    except Exception as e:
        logger.error("Web search failed for query '%s': %s", clean_query, e)
        return f"Error executing web search: {e}"

    # Parse search results
    results: list[dict[str, str]] = []
    # Split by result container
    blocks = html.split('class="result results_links results_links_deep web-result "')

    for block in blocks[1:]:
        title_match = re.search(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
        snippet_match = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', block, re.DOTALL)

        if not title_match:
            continue

        raw_url = title_match.group(1)
        # DuckDuckGo wraps URLs in //duckduckgo.com/l/?uddg=<url>&rut=...
        if "uddg=" in raw_url:
            uddg_encoded = raw_url.split("uddg=")[1].split("&")[0]
            target_url = unquote(uddg_encoded)
        elif raw_url.startswith("//"):
            target_url = "https:" + raw_url
        else:
            target_url = raw_url

        raw_title = re.sub(r"<[^>]+>", "", title_match.group(2)).strip()
        title = html_lib.unescape(raw_title)

        snippet = ""
        if snippet_match:
            raw_snippet = re.sub(r"<[^>]+>", "", snippet_match.group(1)).strip()
            snippet = html_lib.unescape(raw_snippet)

        results.append({
            "title": title,
            "url": target_url,
            "snippet": snippet,
        })

        if len(results) >= limit:
            break

    if not results:
        return f"No web search results found for query: '{clean_query}'."

    # Format into markdown output
    formatted_entries: list[str] = [f'### Web Search Results for "{clean_query}":\n']
    for idx, r in enumerate(results, 1):
        formatted_entries.append(
            f"{idx}. [{r['title']}]({r['url']})\n"
            f"   **URL**: {r['url']}\n"
            f"   **Snippet**: {r['snippet']}\n"
        )

    raw_output = "\n".join(formatted_entries)
    return _wrap_untrusted(raw_output, source="web_search", query=clean_query, count=len(results))


@mcp.tool()
def fetch_web_page(url: str, max_chars: int = 4000) -> str:
    """Fetch the text content of a web page by URL for reading or summarization.

    Cleans HTML to extract plain readable text while stripping advertising,
    scripts, and styles. Results are quarantined inside <untrusted_content> tags.

    Args:
        url: The web page address (must begin with http:// or https://).
        max_chars: Maximum characters of text to return (default: 4000).
    """
    clean_url = url.strip()
    safe, err_msg = _is_safe_url(clean_url)
    if not safe:
        return f"Error: {err_msg}"

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        with httpx.Client(headers=headers, follow_redirects=True, timeout=15.0) as client:
            resp = client.get(clean_url)
            if resp.status_code != 200:
                return f"Error fetching URL '{clean_url}': HTTP status {resp.status_code}."

            content_type = resp.headers.get("content-type", "").lower()
            if "text/html" not in content_type and "text/plain" not in content_type and "application/json" not in content_type:
                return f"Cannot read URL '{clean_url}': unsupported content type '{content_type}'."

            raw_html = resp.text
    except httpx.TimeoutException:
        return f"Error: Request to '{clean_url}' timed out."
    except Exception as e:
        logger.error("Failed to fetch web page '%s': %s", clean_url, e)
        return f"Error fetching web page: {e}"

    # Extract page title
    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
    page_title = html_lib.unescape(title_match.group(1).strip()) if title_match else clean_url

    # Clean text content
    clean_text = _clean_html_text(raw_html)

    # Budget truncation
    char_limit = max(500, min(max_chars, 12000))
    if len(clean_text) > char_limit:
        clean_text = clean_text[:char_limit] + f"\n\n[... Truncated {len(clean_text) - char_limit} characters to fit context window ...]"

    output = f"Title: {page_title}\nURL: {clean_url}\n\nContent:\n{clean_text}"
    return _wrap_untrusted(output, source="web_page", url=clean_url)


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
