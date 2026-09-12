"""Tech News Service for Project Aether (Hacker News & Google News RSS)."""
import email.utils
import hashlib
import json
import logging
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from src.storage.db import DatabaseManager

logger = logging.getLogger("aether.news")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, application/xml, text/xml, */*",
}


def parse_rfc822_date(date_str: str | None) -> str:
    """Parse RFC 822 / 2822 date string to ISO format, fallback to current UTC time."""
    if not date_str:
        return datetime.now(timezone.utc).isoformat()
    try:
        dt = email.utils.parsedate_to_datetime(date_str)
        return dt.isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def extract_domain(url: str) -> str:
    """Extract clean domain for icon resolution."""
    try:
        parsed = urllib.parse.urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def get_fallback_favicon(domain: str) -> str:
    """Get high-res source favicon from Google favicon service."""
    if not domain:
        return ""
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=128"


def clean_html_snippet(raw_html: str, max_chars: int = 240) -> str:
    """Strip HTML tags and unescape text to extract a clean, concise snippet."""
    if not raw_html:
        return ""
    import html
    import re
    # Strip HTML tags
    clean = re.sub(r"<[^>]+>", " ", raw_html)
    # Unescape HTML entities
    clean = html.unescape(clean)
    # Normalize whitespaces
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) > max_chars:
        cutoff = clean[:max_chars].rsplit(" ", 1)[0]
        return f"{cutoff}..."
    return clean


def classify_news_topic(title: str, summary: str = "") -> str:
    """Classify news story into 'ai_ml', 'dev_tools', 'research', or 'tech'."""
    text = f"{title} {summary}".lower()

    ai_keywords = (
        "ai", "llm", "gpt", "claude", "gemini", "deepseek", "mistral", "qwen", "llama",
        "openai", "anthropic", "machine learning", "neural", "deep learning", "transformer",
        "diffusion", "weights", "agent", "prompt", "fine-tuning", "rag", "embedding",
        "vision-language", "reasoning model", "reinforcement learning", "vllm", "ollama",
        "pytorch", "hugging face", "huggingface", "artificial intelligence", "open-weight",
    )
    tools_keywords = (
        "tool", "cli", "sdk", "library", "framework", "open-source", "github",
        "compiler", "debugger", "ide", "editor", "terminal", "api", "docker",
        "kubernetes", "rust", "python", "typescript", "golang", "sqlite", "database",
        "linux", "package manager", "devtools", "release", "v1.", "v2.", "v0.", "stack"
    )
    research_keywords = (
        "paper", "arxiv", "study", "research", "benchmark", "algorithm", "breakthrough",
        "scientists", "stanford", "mit", "berkeley", "deepmind"
    )

    if any(k in text for k in ai_keywords):
        return "ai_ml"
    if any(k in text for k in tools_keywords):
        return "dev_tools"
    if any(k in text for k in research_keywords):
        return "research"
    return "tech"


def fetch_hacker_news(limit: int = 25, timeout: float = 8.0) -> list[dict[str, Any]]:
    """Fetch top front-page stories from Hacker News via Algolia API."""
    url = f"https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage={limit}"
    req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
    news_items: list[dict[str, Any]] = []

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            hits = data.get("hits", [])
            for hit in hits:
                story_id = str(hit.get("objectID") or "")
                title = (hit.get("title") or hit.get("story_title") or "").strip()
                if not title or not story_id:
                    continue

                story_url = hit.get("url")
                if not story_url or not str(story_url).startswith(("http://", "https://")):
                    story_url = f"https://news.ycombinator.com/item?id={story_id}"

                created_at = hit.get("created_at") or datetime.now(timezone.utc).isoformat()
                domain = extract_domain(story_url)

                raw_text = hit.get("story_text") or ""
                summary = clean_html_snippet(raw_text, max_chars=220)
                if not summary:
                    if "show hn" in title.lower():
                        summary = f"Community showcase: {title.replace('Show HN:', '').strip()}"
                    elif "ask hn" in title.lower():
                        summary = f"Discussion thread: {title.replace('Ask HN:', '').strip()}"
                    elif domain:
                        summary = f"Trending engineering discussion on Hacker News from {domain}."

                category = classify_news_topic(title, summary)
                image_url = ""

                news_items.append({
                    "id": f"hn_{story_id}",
                    "title": title,
                    "url": story_url,
                    "source": "Hacker News",
                    "score": int(hit.get("points") or 0),
                    "comments_count": int(hit.get("num_comments") or 0),
                    "author": hit.get("author") or "",
                    "published_at": created_at,
                    "summary": summary,
                    "image_url": image_url,
                    "category": category,
                })
    except Exception as ex:
        logger.warning("Failed to fetch Hacker News: %s", ex)

    return news_items


def fetch_google_news(limit: int = 25, timeout: float = 8.0) -> list[dict[str, Any]]:
    """Fetch top technology stories from Google News RSS feed."""
    url = "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
    news_items: list[dict[str, Any]] = []

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            xml_content = resp.read()
            root = ET.fromstring(xml_content)
            channel = root.find("channel")
            if channel is None:
                return []

            items = channel.findall("item")
            for item in items[:limit]:
                raw_title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub_date = item.findtext("pubDate")
                source_el = item.find("source")
                raw_desc = item.findtext("description") or ""

                if not raw_title or not link or not link.startswith(("http://", "https://")):
                    continue

                publisher = ""
                source_url = ""
                if source_el is not None:
                    if source_el.text:
                        publisher = source_el.text.strip()
                    source_url = source_el.get("url") or ""

                title = raw_title
                if publisher and title.endswith(f" - {publisher}"):
                    title = title[: -len(f" - {publisher}")].strip()
                elif " - " in title:
                    parts = title.rsplit(" - ", 1)
                    if len(parts[1]) < 30:
                        if not publisher:
                            publisher = parts[1].strip()
                        title = parts[0].strip()

                id_hash = hashlib.md5(link.encode("utf-8")).hexdigest()[:12]
                domain = extract_domain(source_url or link)
                summary = clean_html_snippet(raw_desc, max_chars=220)
                if not summary or "view full coverage" in summary.lower():
                    summary = f"Latest technology reporting and analysis via {publisher or 'Google News'}."

                category = classify_news_topic(title, summary)
                image_url = ""

                news_items.append({
                    "id": f"gn_{id_hash}",
                    "title": title,
                    "url": link,
                    "source": "Google News",
                    "score": 0,
                    "comments_count": 0,
                    "author": publisher or "Google News",
                    "published_at": parse_rfc822_date(pub_date),
                    "summary": summary,
                    "image_url": image_url,
                    "category": category,
                })
    except Exception as ex:
        logger.warning("Failed to fetch Google News RSS: %s", ex)

    return news_items


def fetch_google_ai_news(limit: int = 20, timeout: float = 8.0) -> list[dict[str, Any]]:
    """Fetch dedicated AI, LLM, and Machine Learning stories from Google News search feed."""
    query = urllib.parse.quote('artificial intelligence OR machine learning OR LLM OR "open weights" OR "AI model"')
    url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
    news_items: list[dict[str, Any]] = []

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            xml_content = resp.read()
            root = ET.fromstring(xml_content)
            channel = root.find("channel")
            if channel is None:
                return []

            for item in channel.findall("item")[:limit]:
                raw_title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub_date = item.findtext("pubDate")
                source_el = item.find("source")
                raw_desc = item.findtext("description") or ""

                if not raw_title or not link or not link.startswith(("http://", "https://")):
                    continue

                publisher = source_el.text.strip() if source_el is not None and source_el.text else ""
                source_url = source_el.get("url") if source_el is not None else ""

                title = raw_title
                if publisher and title.endswith(f" - {publisher}"):
                    title = title[: -len(f" - {publisher}")].strip()
                elif " - " in title:
                    parts = title.rsplit(" - ", 1)
                    if len(parts[1]) < 30:
                        if not publisher:
                            publisher = parts[1].strip()
                        title = parts[0].strip()

                id_hash = hashlib.md5(link.encode("utf-8")).hexdigest()[:12]
                domain = extract_domain(source_url or link)
                summary = clean_html_snippet(raw_desc, max_chars=220)
                if not summary or "view full coverage" in summary.lower():
                    summary = f"Artificial intelligence reporting and industry coverage from {publisher or 'tech media'}."

                news_items.append({
                    "id": f"ai_{id_hash}",
                    "title": title,
                    "url": link,
                    "source": publisher or "Google News AI",
                    "score": 0,
                    "comments_count": 0,
                    "author": publisher or "AI News",
                    "published_at": parse_rfc822_date(pub_date),
                    "summary": summary,
                    "image_url": "",
                    "category": "ai_ml",
                })
    except Exception as ex:
        logger.warning("Failed to fetch Google AI News RSS: %s", ex)

    return news_items


def fetch_techcrunch_ai(limit: int = 15, timeout: float = 8.0) -> list[dict[str, Any]]:
    """Fetch dedicated AI and startup tool coverage from TechCrunch AI RSS feed."""
    url = "https://techcrunch.com/category/artificial-intelligence/feed/"
    req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
    news_items: list[dict[str, Any]] = []

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            xml_content = resp.read()
            root = ET.fromstring(xml_content)
            channel = root.find("channel")
            if channel is None:
                return []

            for item in channel.findall("item")[:limit]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub_date = item.findtext("pubDate")
                raw_desc = item.findtext("description") or ""
                creator = item.findtext("{http://purl.org/dc/elements/1.1/}creator") or "TechCrunch"

                if not title or not link or not link.startswith(("http://", "https://")):
                    continue

                image_url = ""
                img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw_desc)
                if img_match:
                    image_url = img_match.group(1)
                else:
                    content_encoded = item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or ""
                    c_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', content_encoded)
                    if c_match:
                        image_url = c_match.group(1)

                summary = clean_html_snippet(raw_desc, max_chars=220)
                id_hash = hashlib.md5(link.encode("utf-8")).hexdigest()[:12]

                news_items.append({
                    "id": f"tc_{id_hash}",
                    "title": title,
                    "url": link,
                    "source": "TechCrunch AI",
                    "score": 0,
                    "comments_count": 0,
                    "author": creator,
                    "published_at": parse_rfc822_date(pub_date),
                    "summary": summary,
                    "image_url": image_url,
                    "category": "ai_ml",
                })
    except Exception as ex:
        logger.warning("Failed to fetch TechCrunch AI RSS: %s", ex)

    return news_items


def fetch_and_cache_news(
    db: DatabaseManager | None = None,
    limit_per_source: int = 25,
) -> list[dict[str, Any]]:
    """Fetch live news from Hacker News, Google News, and AI feeds in parallel, deduplicate and cache."""
    import concurrent.futures

    database = db or DatabaseManager()

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        f_hn = executor.submit(fetch_hacker_news, limit_per_source)
        f_gn = executor.submit(fetch_google_news, limit_per_source)
        f_ai = executor.submit(fetch_google_ai_news, limit_per_source)
        f_tc = executor.submit(fetch_techcrunch_ai, 15)

        hn_items = f_hn.result()
        gn_items = f_gn.result()
        ai_items = f_ai.result()
        tc_items = f_tc.result()

    combined = hn_items + ai_items + tc_items + gn_items
    if not combined:
        logger.info("No news items retrieved from external sources.")
        return database.get_cached_news(limit=limit_per_source * 2)

    # Deduplicate by lowercase title
    seen_titles: set[str] = set()
    deduped: list[dict[str, Any]] = []

    for item in combined:
        norm_title = "".join(c for c in item["title"].lower() if c.isalnum()) or item["title"].strip().lower()
        if norm_title in seen_titles:
            continue
        seen_titles.add(norm_title)
        deduped.append(item)

    # Cache into SQLite
    database.cache_news_items(deduped)

    # Prune news older than 72 hours
    try:
        database.prune_old_news(max_age_hours=72)
    except Exception as ex:
        logger.debug("Pruning news failed: %s", ex)

    return database.get_cached_news(limit=limit_per_source * 2)


def get_news(
    db: DatabaseManager | None = None,
    limit: int = 30,
    source: str | None = None,
    category: str | None = None,
    force_refresh: bool = False,
    max_cache_age_seconds: int = 1800,
) -> list[dict[str, Any]]:
    """
    Retrieve tech news. Returns instantly from SQLite cache if fresh (< 30-60m).
    Fetches fresh news if cache is empty, expired, or force_refresh is True.
    """
    database = db or DatabaseManager()
    cached = database.get_cached_news(limit=limit, source=source, category=category)

    if not force_refresh and cached:
        try:
            latest_fetched_at = cached[0].get("fetched_at")
            if latest_fetched_at:
                fetched_dt = datetime.fromisoformat(latest_fetched_at)
                age_seconds = (datetime.now().astimezone() - fetched_dt.astimezone()).total_seconds()
                if age_seconds < max_cache_age_seconds:
                    return cached
        except Exception:
            return cached

    # Stale or empty: fetch and refresh cache
    try:
        fresh = fetch_and_cache_news(db=database, limit_per_source=max(15, limit // 2))
        res = fresh
        if source and source.lower() not in ("all", "*"):
            res = [n for n in res if n["source"].lower() == source.lower()]
        if category and category.lower() not in ("all", "*"):
            res = [n for n in res if n.get("category", "").lower() == category.lower()]
        return res[:limit]
    except Exception as ex:
        logger.warning("Error refreshing news cache, returning existing cache: %s", ex)
        return cached


# =============================================================================
# AI Student & Developer Briefing Generator
# =============================================================================

def generate_ai_student_digest(
    items: list[dict[str, Any]],
    client: Any = None,
    ollama_client: Any = None,
) -> dict[str, Any]:
    """
    Synthesize the latest news items into an actionable briefing for an AI student
    and tool developer, using local Ollama with a robust extractive fallback.
    """
    ollama = client or ollama_client

    # Select top AI & tool candidates
    ai_candidates = [
        item for item in items
        if item.get("category") in ("ai_ml", "dev_tools", "research")
    ]
    if not ai_candidates:
        ai_candidates = items[:12]

    candidates_text = "\n".join(
        f"- [{item.get('source', 'Tech')}] {item['title']}: {item.get('summary', '')}"
        for item in ai_candidates[:12]
    )

    now_str = datetime.now().strftime("%B %d, %Y")

    # Try local Ollama if available
    if ollama is not None and getattr(ollama, "is_connected", lambda: False)():
        try:
            prompt = (
                f"You are Aether's AI Intelligence Analyst. The user is an ambitious Computer Science & AI student "
                f"who develops AI tools, works with local LLMs, and studies machine learning architectures.\n"
                f"Date: {now_str}\n\n"
                f"Here are the top tech & AI stories from today:\n{candidates_text}\n\n"
                f"Generate a concise, insightful briefing for this student. Respond with ONLY a valid JSON object matching this schema:\n"
                f"{{\n"
                f'  "headline": "Punchy 1-line overview of today\'s AI landscape",\n'
                f'  "executive_takeaway": "2 sentences summarizing the biggest theme in AI/tools and why it matters for an AI student.",\n'
                f'  "models_and_research": [\n'
                f'    {{"title": "Story/Model Name", "takeaway": "Key insight on weights, architectures, or benchmarks"}}\n'
                f'  ],\n'
                f'  "developer_tools": [\n'
                f'    {{"tool": "Tool/Library Name", "description": "How a developer or student can use it to build things"}}\n'
                f'  ],\n'
                f'  "student_project_idea": "A concrete, exciting hands-on project idea that an AI student can build locally using today\'s tools or models."\n'
                f"}}\n"
                f"Do NOT include any text outside the JSON block."
            )

            raw_resp = ollama.chat(
                messages=[
                    {"role": "system", "content": "You are a concise tech analyst specialized in AI models and developer tooling."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
            )

            raw_text = raw_resp.get("content") if isinstance(raw_resp, dict) else str(raw_resp or "")
            clean_text = raw_text.strip()
            if "```json" in clean_text:
                clean_text = clean_text.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in clean_text:
                clean_text = clean_text.split("```", 1)[1].split("```", 1)[0].strip()

            parsed = json.loads(clean_text)
            if isinstance(parsed, dict) and "executive_takeaway" in parsed:
                parsed["generated_at"] = datetime.now().isoformat()
                parsed["method"] = "ollama_llm"
                parsed["model"] = getattr(ollama, "default_model", None) or "local LLM"
                if "models_and_research" in parsed and isinstance(parsed["models_and_research"], list):
                    for m in parsed["models_and_research"]:
                        if isinstance(m, dict):
                            m.setdefault("name", m.get("title", "Model Release"))
                            m.setdefault("insight", m.get("takeaway", ""))
                if "developer_tools" in parsed and isinstance(parsed["developer_tools"], list):
                    for t in parsed["developer_tools"]:
                        if isinstance(t, dict):
                            t.setdefault("name", t.get("tool", "Developer Tool"))
                            t.setdefault("insight", t.get("description", ""))
                if "student_project_idea" in parsed and "student_project_takeaway" not in parsed:
                    idea = parsed["student_project_idea"]
                    if isinstance(idea, dict):
                        parsed["student_project_takeaway"] = idea
                    else:
                        parsed["student_project_takeaway"] = {
                            "title": "Local AI Hands-On Project",
                            "description": str(idea),
                            "tech_stack": "Python, Ollama, LangChain, SQLite",
                        }
                return parsed
        except Exception as ex:
            logger.debug("Ollama briefing generation fallback: %s", ex)

    # Fallback: Deterministic extractive briefing
    top_models = []
    top_tools = []
    for item in ai_candidates:
        if item.get("category") == "ai_ml" and len(top_models) < 3:
            top_models.append({
                "name": item["title"],
                "title": item["title"],
                "insight": item.get("summary") or "New development in models, open weights, and neural architectures.",
                "takeaway": item.get("summary") or "New development in models, open weights, and neural architectures.",
                "url": item.get("url"),
            })
        elif item.get("category") == "dev_tools" and len(top_tools) < 3:
            top_tools.append({
                "name": item["title"],
                "tool": item["title"],
                "insight": item.get("summary") or "Developer tool release enhancing local software engineering workflows.",
                "description": item.get("summary") or "Developer tool release enhancing local software engineering workflows.",
                "url": item.get("url"),
            })

    if not top_models and ai_candidates:
        top_models.append({
            "name": ai_candidates[0]["title"],
            "title": ai_candidates[0]["title"],
            "insight": ai_candidates[0].get("summary", ""),
            "takeaway": ai_candidates[0].get("summary", ""),
            "url": ai_candidates[0].get("url"),
        })

    lead_title = ai_candidates[0]["title"] if ai_candidates else "Frontier AI & Local Model Development"

    return {
        "headline": f"AI Intelligence & Open Tooling Digest — {now_str}",
        "executive_takeaway": (
            f"The pace of open-weight models and developer tooling is accelerating rapidly. "
            f"Key focus today centers on '{lead_title}', creating new opportunities to build autonomous local AI workflows."
        ),
        "models_and_research": top_models or [
            {
                "name": "Open-Weights Reasoning & Inference",
                "title": "Open-Weights Reasoning & Inference",
                "insight": "Growing focus on efficient local model serving, reasoning tokens, and compact quantized architectures.",
                "takeaway": "Growing focus on efficient local model serving, reasoning tokens, and compact quantized architectures.",
            }
        ],
        "developer_tools": top_tools or [
            {
                "name": "Local Agent SDKs & Tool-Calling",
                "tool": "Local Agent SDKs & Tool-Calling",
                "insight": "Integration of native tool schemas and sandboxed terminal execution into agentic pair-programming workflows.",
                "description": "Integration of native tool schemas and sandboxed terminal execution into agentic pair-programming workflows.",
            }
        ],
        "student_project_takeaway": {
            "title": "Local Research & Knowledge Synthesizer Agent",
            "description": "Index the latest arXiv AI papers and test automated local tool-calling for technical synthesis.",
            "tech_stack": "Python, Ollama (qwen2.5-coder / llama3.2), SQLite-FTS5, Streamlit or FastAPI",
        },
        "student_project_idea": (
            "Build a local knowledge agent using Ollama, LangChain/LlamaIndex, and SQLite-FTS5: "
            "index the latest arXiv AI papers and test automated tool-calling for literature review."
        ),
        "generated_at": datetime.now().isoformat(),
        "method": "extractive_curated",
    }


_SYNTHESIS_LOCK = threading.Lock()
_IS_SYNTHESIZING = False


def _run_background_ollama_digest(
    database: DatabaseManager,
    items: list[dict[str, Any]],
    ollama: Any,
    state_key: str,
) -> None:
    """Run deeper Ollama LLM synthesis in background thread and update SQLite cache upon completion."""
    global _IS_SYNTHESIZING
    with _SYNTHESIS_LOCK:
        if _IS_SYNTHESIZING:
            return
        _IS_SYNTHESIZING = True

    try:
        if ollama is not None and getattr(ollama, "is_connected", lambda: False)():
            logger.info("Starting background Ollama AI student digest synthesis...")
            rich_digest = generate_ai_student_digest(items, client=ollama)
            if rich_digest and rich_digest.get("method") == "ollama_llm":
                database.set_state(state_key, json.dumps(rich_digest))
                logger.info("Background Ollama AI student digest synthesis completed and cached.")
    except Exception as ex:
        logger.debug("Background Ollama digest synthesis error: %s", ex)
    finally:
        with _SYNTHESIS_LOCK:
            _IS_SYNTHESIZING = False


def get_ai_student_digest(
    db: DatabaseManager | None = None,
    client: Any = None,
    ollama_client: Any = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Retrieve cached AI student digest from system_state, or generate and cache it.
    
    Returns in < 5ms by serving cached content or an instant extractive briefing immediately,
    while queueing deeper local Ollama LLM synthesis in the background.
    """
    database = db or DatabaseManager()
    ollama = client or ollama_client
    state_key = "ai_student_news_digest"

    if not force_refresh:
        stored_json = database.get_state(state_key)
        if stored_json:
            try:
                data = json.loads(stored_json)
                gen_at = data.get("generated_at")
                if gen_at:
                    gen_dt = datetime.fromisoformat(gen_at)
                    age_seconds = (datetime.now().astimezone() - gen_dt.astimezone()).total_seconds()
                    if age_seconds < 7200:  # Fresh for 2 hours
                        return data
            except Exception:
                pass

    items = get_news(db=database, limit=40)

    if force_refresh:
        # Explicit user-triggered refresh
        digest = generate_ai_student_digest(items, client=ollama)
        try:
            database.set_state(state_key, json.dumps(digest))
        except Exception as ex:
            logger.debug("Failed to cache AI news digest in state: %s", ex)
        return digest

    # Cold start / cache miss: generate instant extractive briefing immediately (< 5ms)
    instant_digest = generate_ai_student_digest(items, client=None)
    try:
        database.set_state(state_key, json.dumps(instant_digest))
    except Exception:
        pass

    # Launch background Ollama synthesis without blocking the response
    if ollama is not None:
        t = threading.Thread(
            target=_run_background_ollama_digest,
            args=(database, items, ollama, state_key),
            daemon=True,
        )
        t.start()

    return instant_digest
