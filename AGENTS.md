# AGENTS.md — Agent & Contributor Instructions for Project Aether

This document provides strict operational rules and architectural boundaries for autonomous AI coding agents and human contributors working in the **Project Aether** codebase.

---

## 1. Architectural Philosophy

- **Offline-First & Local-First**: Zero external cloud dependencies or telemetry. Local Ollama inference, local ComfyUI diffusion, local SQLite database, and local Markdown vault.
- **Minimal Dependencies**: Prefer the Python Standard Library and native browser platform capabilities over third-party packages or npm libraries.
- **Vanilla ES6+ Frontend**: Strictly zero build steps, zero node_modules, and zero bundling. The frontend is vanilla ES modules (`type="module"`), vanilla CSS3, and semantic HTML5.

---

## 2. STRICT Anti-AI-Slop UI Invariants

Any agent touching HTML, CSS, or JavaScript files in `src/web/static/` **MUST** adhere to the **Zinc + Sky Blue** design system. You are strictly forbidden from introducing the following AI slop anti-patterns:

1. ❌ **NO Glassmorphism**: Never use `backdrop-filter` or `-webkit-backdrop-filter`. All card and panel surfaces must use solid Zinc backgrounds (`var(--card-bg)`).
2. ❌ **NO Neon Glows**: Never use spread shadows or saturated colors in `box-shadow` (e.g. `0 0 15px rgba(...)` or `--primary-glow`). Use clean 1px borders (`var(--card-border)`) or subtle neutral drop shadows.
3. ❌ **NO Multi-Stop Gradients**: Never use rainbow/linear gradients on buttons, badges, user chat bubbles, or cards. Use solid fills (`var(--primary)`, `var(--emerald)`, `var(--card-bg)`). Never use `-webkit-background-clip: text`.
4. ❌ **ZERO Unicode Emojis**: Never introduce unicode emojis (e.g. ☀️, 🌧️, 🤖, 🚀, 💡, ⚡) anywhere in HTML, CSS, or JS modules. Always use clean vector SVGs or plain technical text.
5. ❌ **NO Fake Clickables**: Never attach `onclick` handlers to `<div>` or `<span>` elements. Always use semantic `<button type="button">` or `<a href="...">` with appropriate `aria-label` or `title` attributes.
6. ❌ **NO Spinning Loader Overlays**: Never use full-screen blurs or bouncing loader balls. Use CSS skeleton placeholders (`.skeleton`, `.skeleton-line`) matching the content layout.
7. ❌ **NO Unvalidated Freeform Inputs**: For structured lookups (such as locations), provide debounced typeahead search and require selection of verified entities.

---

## 3. Mandatory Verification Checklist

Before reporting completion on any frontend or design change, you **MUST** run the automated regression tests:

```bash
# 1. Anti-Slop & Design System Test
.venv/bin/pytest tests/unit/test_design_system.py

# 2. Zero-Emoji & ES Module Verification
.venv/bin/pytest tests/unit/test_frontend_modules.py

# 3. Full Unit Test Suite
.venv/bin/pytest tests/unit/
```

All tests must pass with 0 failures before proposing or committing code changes.
