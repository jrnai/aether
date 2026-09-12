"""Unit tests for Native ES Modules frontend architecture and zero-emoji compliance."""

import pathlib
import re
import pytest

JS_DIR = pathlib.Path(__file__).parent.parent.parent / "src" / "web" / "static" / "js"
HTML_PATH = pathlib.Path(__file__).parent.parent.parent / "src" / "web" / "static" / "index.html"

# Comprehensive emoji pattern (pictographs, emoticons, dingbats, supplemental symbols)
EMOJI_PATTERN = re.compile(
    r"[\U00010000-\U0010ffff]"
    r"|[\u2600-\u27ff]"
    r"|[\u2300-\u23ff]"
    r"|[\u2b50-\u2b55]"
    r"|[\u203c\u2049\u2122\u2139\u2194-\u2199\u21a9-\u21aa]"
)


def test_all_modules_exist_and_non_empty():
    """Verify that all core frontend ES modules are present and non-empty."""
    expected_files = [
        "app.js",
        "store.js",
        "modules/overview.js",
        "modules/news.js",
        "modules/calendar.js",
        "modules/mail.js",
        "modules/tasks.js",
        "modules/models.js",
        "modules/chat.js",
        "modules/editor.js",
        "modules/terminal.js",
        "modules/coder.js",
    ]
    for rel_path in expected_files:
        full_path = JS_DIR / rel_path
        assert full_path.is_file(), f"Expected module missing: {rel_path}"
        assert full_path.stat().st_size > 100, f"Module is too small or empty: {rel_path}"


def test_no_emojis_in_frontend_modules():
    """Verify strictly ZERO emojis across all frontend ES modules."""
    js_files = list(JS_DIR.rglob("*.js"))
    assert len(js_files) >= 12

    for js_file in js_files:
        content = js_file.read_text(encoding="utf-8")
        matches = EMOJI_PATTERN.findall(content)
        assert len(matches) == 0, f"Found {len(matches)} emojis/symbols in {js_file.name}: {set(matches)}"


def test_all_imports_match_exports():
    """Verify that all symbols imported in any ES module are explicitly exported by the target."""
    all_js = list(JS_DIR.rglob("*.js"))

    # Extract exports
    exports = {}
    for f in all_js:
        content = f.read_text(encoding="utf-8")
        exported_names = set()
        for m in re.finditer(r"export\s+(?:let|const|var|function|async\s+function)\s+([a-zA-Z0-9_$]+)", content):
            exported_names.add(m.group(1))
        for m in re.finditer(r"export\s*\{\s*([^}]+)\s*\}", content):
            for item in m.group(1).split(","):
                parts = item.strip().split()
                if len(parts) == 1 and parts[0]:
                    exported_names.add(parts[0])
                elif len(parts) == 3 and parts[1] == "as":
                    exported_names.add(parts[2])
        exports[f.name] = exported_names

    # Verify imports
    mismatches = []
    for f in all_js:
        content = f.read_text(encoding="utf-8")
        for m in re.finditer(r"import\s*\{([^}]+)\}\s*from\s*['\"]([^'\"]+)['\"]", content):
            imported_names = [x.strip().split()[0] for x in m.group(1).split(",") if x.strip()]
            from_path = m.group(2)
            target_file = (f.parent / from_path).resolve()
            assert target_file.exists(), f"{f.name} imports from non-existent {from_path}"
            target_exports = exports.get(target_file.name, set())
            for name in imported_names:
                if name not in target_exports:
                    mismatches.append(f"{f.name} imports '{name}' from {target_file.name}, but it is not exported")

    assert len(mismatches) == 0, f"Import/Export mismatches found:\n" + "\n".join(mismatches)


def test_all_html_handlers_bound_to_window():
    """Verify that every inline event handler in index.html is bound to window in app.js."""
    html = HTML_PATH.read_text(encoding="utf-8")
    app_js = (JS_DIR / "app.js").read_text(encoding="utf-8")

    pattern = re.compile(r'on(?:click|change|keydown|keyup|input|submit)\s*=\s*["\']([^"\']+)["\']')
    inline_calls = set()
    for m in pattern.finditer(html):
        expr = m.group(1).strip()
        fn_matches = re.findall(r"([a-zA-Z0-9_$]+)\s*\(", expr)
        for fn in fn_matches:
            if fn not in ("if", "event", "stopPropagation", "preventDefault", "confirm"):
                inline_calls.add(fn)

    missing = []
    for fn in inline_calls:
        if f"window.{fn} =" not in app_js and f"window.{fn}=" not in app_js:
            missing.append(fn)

    assert len(missing) == 0, f"Missing window bindings for inline HTML handlers: {missing}"


def test_index_html_loads_module():
    """Verify that index.html loads js/app.js with type='module'."""
    html = HTML_PATH.read_text(encoding="utf-8")
    assert '<script type="module" src="/static/js/app.js' in html
