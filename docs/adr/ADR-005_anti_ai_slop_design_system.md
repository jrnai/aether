# ADR-005: Anti-AI-Slop Zinc + Sky Blue UI Design System vs. Glassmorphic Glows

## Status
**Accepted** (2026-09)

## Context
Early iterations of Aether suffered from common generative AI user-interface patterns ("AI Slop"):
- Extensive use of `backdrop-filter: blur(...)` across cards, sidebars, and banners.
- Saturated rainbow linear gradients on buttons, headers, and text clips.
- Heavy neon spread glow shadows (`box-shadow: 0 0 25px rgba(139, 92, 246, 0.5)`).
- Copious unicode emoji decorations in place of vector icons.
- Fake clickable elements (`<div onclick="...">`, `<span onclick="...">`) lacking semantic HTML tags and keyboard focus outlines.

These tropes caused severe practical issues:
1. **GPU & Rendering Penalties**: Blurring dozens of active dashboard cards continuously triggered browser compositor repaints and lag during window resizing.
2. **Visual Fatigue & Illegibility**: Low contrast, hazy backgrounds, and neon glows made code editors, diff views, and logs difficult to read.
3. **Accessibility Failures**: Lack of semantic `<button>` elements prevented standard keyboard navigation (`Tab`, `Enter`) and failed automated a11y audits.

## Decision
We established a strict **Anti-AI-Slop Framework** codified in [`docs/07_frontend_and_design_system.md`](file:///C:/Users/jrrya/Projects/aether/docs/07_frontend_and_design_system.md) and automated via Python quality gates ([`tests/unit/test_design_system.py`](file:///C:/Users/jrrya/Projects/aether/tests/unit/test_design_system.py)):
- **Palette**: Strict technical dark theme using Zinc-950 (`#09090B`) base, Zinc-900 (`#18181B`) solid opaque card surfaces, Zinc-800 (`#27272A`) crisp 1px borders, and Sky-400 (`#38BDF8`) single accent.
- **Elimination of Glows & Gradients**: Purged all neon glow variables (`--primary-glow`), multi-stop saturated gradients, and text-clip gradients.
- **Zero-Emoji Compliance**: Mandated 0 unicode emojis across HTML, CSS, and JS modules, replaced entirely with clean vector SVG iconography.
- **Semantic Interactive Controls**: Every interactive target must use `<button type="button">` or `<a>` with explicit 2px focus outlines (`outline: 2px solid var(--focus-ring)`).
- **Authorized Modal Blur Exception**: Authorized `backdrop-filter: blur(28px) saturate(190%)` exclusively for the full-screen modal focus overlay (`#voice-assistant-overlay`) to create an OS-level focus environment during active voice conversations, while keeping 100% of dashboard cards solid opaque Zinc.

## Consequences
### Positive
- **High Information Density**: Data, terminal logs, diffs, and notes are the focal point without visual distraction.
- **Zero Compositor Lag**: Opaque solid cards eliminate unnecessary GPU rendering passes.
- **Keyboard-First Ergonomics**: Complete navigation via `Tab`, `Arrow`, `Enter`, and `Esc`.
- **Automated Regression Prevention**: CI tests fail automatically if banned tokens or emojis are introduced.

### Negative
- Developers cannot use quick emoji shortcuts or copy-paste visual components from generic component libraries without stripping unauthorized styling.

## Alternatives Considered
- **Maintaining Glassmorphic Dark Theme**: Rejected due to persistent text legibility complaints and rendering stutter.
- **Tailwind CSS / React SPA**: Considered rewrites. Rejected to preserve the zero-build-step, zero-npm-dependency lightweight ES6 module architecture.
