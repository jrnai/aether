"""Automated quality gate tests for Project Aether's Zinc + Sky Blue Anti-AI-Slop Design System."""

import pathlib
import re
import pytest

WEB_DIR = pathlib.Path(__file__).parent.parent.parent / "src" / "web" / "static"
CSS_PATH = WEB_DIR / "style.css"
HTML_PATH = WEB_DIR / "index.html"

# Comprehensive emoji pattern (pictographs, emoticons, dingbats, supplemental symbols)
EMOJI_PATTERN = re.compile(
    r"[\U00010000-\U0010ffff]"
    r"|[\u2600-\u27ff]"
    r"|[\u2300-\u23ff]"
    r"|[\u2b50-\u2b55]"
    r"|[\u203c\u2049\u2122\u2139\u2194-\u2199\u21a9-\u21aa]"
)


def test_css_no_banned_slop_tokens():
    """Verify that style.css strictly contains zero banned AI-slop design tokens or properties.

    Note: The full-screen voice assistant overlay is authorized to use modal backdrop blur.
    All cards, buttons, badges, and dashboard components must never use backdrop blur.
    """
    assert CSS_PATH.is_file(), "style.css not found"
    css_text = CSS_PATH.read_text(encoding="utf-8")

    css_without_voice_overlay = re.sub(
        r"/\* --- Voice Assistant Overlay --- \*/.*?/\* --- End Voice Assistant Overlay --- \*/",
        "",
        css_text,
        flags=re.DOTALL,
    )

    banned_tokens = [
        "primary-glow",
        "text-shadow:",
        "-webkit-background-clip: text",
        "background-clip: text",
    ]

    violations = []
    for token in banned_tokens:
        if token in css_text:
            violations.append(f"Found banned slop token: '{token}'")

    for blur_token in ["backdrop-filter", "-webkit-backdrop-filter"]:
        if blur_token in css_without_voice_overlay:
            violations.append(f"Found unauthorized backdrop blur on dashboard element: '{blur_token}'")

    assert len(violations) == 0, "\n".join(violations)


def test_no_emojis_in_html_and_css():
    """Verify strictly ZERO unicode emojis in HTML templates and CSS stylesheets."""
    for path in [HTML_PATH, CSS_PATH]:
        assert path.is_file(), f"File missing: {path.name}"
        text = path.read_text(encoding="utf-8")
        matches = EMOJI_PATTERN.findall(text)
        assert len(matches) == 0, f"Found {len(matches)} emoji(s) in {path.name}: {set(matches)}"


def test_semantic_buttons_for_inline_handlers():
    """Verify that inline interactive click handlers in index.html use accessible buttons or inputs."""
    html_text = HTML_PATH.read_text(encoding="utf-8")

    # Match any <div or <span with onclick handlers
    bad_tags = re.findall(r"<(div|span)[^>]*\bonclick\s*=", html_text, re.IGNORECASE)
    assert len(bad_tags) == 0, (
        f"Found {len(bad_tags)} fake clickable elements ({set(bad_tags)}) in index.html. "
        "All interactive elements must use <button type='button'>, <a>, or have explicit accessible semantics."
    )


def test_design_system_css_tokens_defined():
    """Verify that the core Zinc + Sky Blue design system variables exist in :root."""
    css_text = CSS_PATH.read_text(encoding="utf-8")

    required_tokens = [
        "--bg-main",
        "--bg-sidebar",
        "--card-bg",
        "--card-border",
        "--card-hover-border",
        "--primary",
        "--primary-hover",
        "--emerald",
        "--amber",
        "--rose",
        "--text-main",
        "--text-muted",
        "--text-dim",
        "--radius-sm",
        "--radius-md",
        "--radius-lg",
        "--focus-ring",
        "--skeleton-bg",
        "--skeleton-shine",
    ]

    missing = [token for token in required_tokens if token not in css_text]
    assert len(missing) == 0, f"Missing design tokens in style.css: {missing}"
