# Aether Specification 07: Frontend Architecture & Anti-AI-Slop Design System

## 1. Executive Summary & Design Philosophy

The Aether web dashboard and desktop app shell serve as the primary operational surface for Project Aether. The interface is engineered according to the **Zinc + Sky Blue** design system: a technical, high-density, utility-focused dark interface inspired by modern developer environments (e.g. Linear, Raycast, GitHub CLI).

### Core Design Tenets
1. **Utility & Information Density Over Decoration**: Data, terminals, files, and diffs are the heroes. Decorative visual flourishes must never compete with user content.
2. **Keyboard-First Ergonomics**: Every interactive control must be reachable and operable via keyboard navigation (`Tab`, `Enter`, `Escape`, arrow keys) with high-contrast visible focus rings.
3. **Deterministic Performance**: Zero build-step requirement, zero npm runtime dependencies, native ES modules (`import`/`export`), and zero heavy layout reflows.
4. **Anti-AI-Slop Rigor**: Strict invariants enforced via automated tests to permanently eliminate generic generative AI design tropes.

---

## 2. The Anti-AI-Slop Invariants

Generative AI models exhibit systematic biases toward over-decorated, low-contrast, unmaintainable UI patterns ("AI slop"). In Project Aether, the following seven invariants are strictly enforced:

| **Glassmorphism (`backdrop-filter`)** | Degrades GPU rendering performance, blurs legible text, creates visual haze on dark displays. | **Forbidden on Dashboard Surfaces.** All card surfaces and panels use solid opaque Zinc backgrounds (`--card-bg: #18181B`) with 1px border (`--card-border: #27272A`). Full-screen modal focus overlays (specifically `#voice-assistant-overlay`) are authorized to use backdrop blur (`backdrop-filter: blur(28px) saturate(190%)`) for OS-level voice assistant focus. |
| **Neon Spread Glows (`box-shadow: 0 0 Npx ...`)** | Reduces contrast, causes visual fatigue, and creates an unpolished "cyberpunk demo" look. | **Strictly Forbidden.** Glow variables (such as `--primary-glow`) are deleted. Elevation uses subtle neutral drop shadows or crisp 1px borders. |
| **Multi-Stop Saturated Gradients** | Rainbow linear gradients on buttons, text, and headers look generic and dated. | **Strictly Forbidden.** Buttons and badges use solid accents (`--primary: #38BDF8`, `--emerald: #10B981`). Text must use solid high-contrast foreground colors (`--text-main: #F9FAFB`). `-webkit-background-clip: text` is banned. |
| **Unicode Emoji Soup** | Unprofessional, unpredictable across operating systems, breaks technical typography, impairs screen readers. | **Strictly Forbidden.** Zero unicode emojis in frontend JS modules, CSS, or HTML. All iconography must use crisp, scalable vector SVG paths. |
| **Fake Clickables (`<div onclick>`, `<span onclick>`)** | Destroys keyboard accessibility, breaks tab ordering, and fails screen reader accessibility audits. | **Strictly Forbidden.** All interactive triggers must use semantic `<button type="button">` or `<a>` elements with explicit accessible labels (`aria-label`, `title`). |
| **Bouncing Loading Spinners** | Cause visual disruption and layout shifting during async data fetches. | **Content Shimmer.** Use CSS skeleton loaders (`.skeleton`, `.skeleton-line`, `.skeleton-block`) matching the layout geometry of incoming content. |
| **Unvalidated Freeform Inputs** | Letting users submit arbitrary strings for structured entities causes silent API failures or bad state. | **Structured Lookups.** Use debounced typeahead searches (e.g. weather geocoding) requiring selection of verified entities. |

---

## 3. Design Token Architecture (`:root`)

All styling is grounded in centralized CSS custom properties declared in `src/web/static/style.css`:

```css
:root {
  /* Surface & Background Hierarchy */
  --bg-main: #09090B;           /* Deep Zinc-950 base */
  --bg-sidebar: #18181B;        /* Zinc-900 lateral panels */
  --card-bg: #18181B;           /* Zinc-900 card surface */
  --card-border: #27272A;       /* Zinc-800 crisp surface boundary */
  --card-hover-border: #38BDF8; /* Sky-400 interactive boundary */

  /* Primary & Semantic Color Palette */
  --primary: #38BDF8;           /* Sky-400 primary accent */
  --primary-hover: #0EA5E9;     /* Sky-500 hover state */
  --emerald: #10B981;           /* Emerald-500 success & active status */
  --amber: #F59E0B;             /* Amber-500 warning & transcription */
  --rose: #F43F5E;              /* Rose-500 danger, errors & disconnect */
  --cyan: #06B6D4;              /* Cyan-500 auxiliary indicator */

  /* Typography & Text Shades */
  --text-main: #F9FAFB;         /* High-contrast body & header text */
  --text-muted: #9CA3AF;        /* Neutral secondary labels & captions */
  --text-dim: #71717A;          /* Subdued timestamps, borders, dividers */

  /* Geometry & Focus */
  --radius-sm: 4px;             /* Compact pills, tags, input fields */
  --radius-md: 8px;             /* Buttons, cards, modals */
  --radius-lg: 12px;            /* Outer containers, dialog overlays */

  /* Interactive States */
  --focus-ring: #38BDF8;        /* Sky-400 2px outline for keyboard focus */
  --skeleton-bg: #27272A;       /* Base shimmer block */
  --skeleton-shine: #3F3F46;    /* Animated highlight */

  /* Fonts & Motion */
  --font-heading: 'Outfit', -apple-system, sans-serif;
  --font-body: 'Inter', -apple-system, sans-serif;
  --transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}
```

---

## 4. Component Standards & Layout Specifications

### 4.1 Cards & Panels
- **Container**: Solid background `var(--card-bg)`, 1px border `var(--card-border)`, radius `var(--radius-md)`.
- **Card Header**: Flex row, space-between alignment, clean `h2` heading with semantically grouped action buttons.
- **Hover State**: Subtle border highlight to `var(--card-border)` or `var(--card-hover-border)`. No scale transforms or floating dropshadows.

### 4.2 Interactive Buttons & Focus Rings
- **Primary Button (`.btn-primary`, `.btn-primary-sm`)**: Solid `var(--primary)` background with `#09090B` high-contrast dark text.
- **Subtle / Secondary Button (`.btn-subtle`, `.btn-secondary`)**: Transparent or `var(--card-border)` background with `var(--text-muted)` text and hover transition to `var(--text-main)`.
- **Focus Rings**: All interactive controls must explicitly define:
  ```css
  :focus-visible {
    outline: 2px solid var(--focus-ring);
    outline-offset: 2px;
  }
  ```

### 4.3 Typography & Headers
- Headings use `'Outfit'`, with clean letter-spacing and uniform font weights (`600` or `700`).
- Text content uses `'Inter'` for maximum legibility at high data density.
- Code snippets and terminal outputs use monospace font stacks (`'Fira Code'`, `'Cascadia Code'`, `Consolas`).

### 4.4 Status Indicators & Dots
- Status dots (`.dot-green`, `.dot-yellow`, `.dot-blue`, `.coder-status-dot`) are solid colored circular spans (`width: 8px; height: 8px; border-radius: 50%`).
- Radiating pulsating animations and blurry neon glows are prohibited in default states.

### 4.5 Skeleton Loading States
- When data is asynchronously loading, render skeleton placeholder bars rather than generic spinning loaders:
  ```html
  <div class="skeleton skeleton-block"></div>
  <div class="skeleton skeleton-line short"></div>
  ```

---

## 5. Automated Quality Gates & Enforcement

To prevent regressions, the design system invariants are automated via Python tests:

1. **`tests/unit/test_frontend_modules.py`**:
   - `test_no_emojis_in_frontend_modules`: Enforces strictly zero emojis across all `.js` files using the Unicode regex range `[\U00010000-\U0010ffff]|[\u2600-\u27ff]|[\u2300-\u23ff]|[\u2b50-\u2b55]`.
   - `test_all_html_handlers_bound_to_window`: Verifies every inline event handler in `index.html` is registered on the global `window` object in `app.js`.
2. **`tests/unit/test_design_system.py`**:
   - `test_css_no_banned_slop_tokens`: Confirms `style.css` contains 0 occurrences of `primary-glow`, `text-shadow`, and `-webkit-background-clip: text`, and ensures backdrop blur is never applied to dashboard surfaces (restricted solely to the full-screen voice modal overlay).
   - `test_no_emojis_in_html_and_css`: Confirms `index.html` and `style.css` contain 0 emojis.
   - `test_semantic_buttons_for_inline_handlers`: Confirms all interactive click targets use `<button>` or `<select>` or proper ARIA roles.
   - `test_design_system_css_tokens_defined`: Confirms that all core design system tokens remain defined in `:root`.

These tests run on every pull request and build verification cycle via `pytest tests/unit/`.
