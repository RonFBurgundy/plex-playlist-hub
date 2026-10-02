---
name: trackseerr_frontend_practices
description: Enforces TrackSeerr Web UI architecture, tactile tape deck/Walkman navigation, minimalist obsidian/carbon styling, sharp 4px fillets, full-width mobile layouts, and zero-AI-slop design standards.
version: 1.0.0
---

# TrackSeerr Web UI Frontend Practices & Design System

You are an expert frontend systems architect enforcing TrackSeerr's Web UI design philosophy and architecture.
Use this skill when making any changes to the HTML, CSS, JavaScript, icons, or component templates in TrackSeerr (`plex_playlist_sync/static/`).

---

## Phase 1: Context & Core Architectural Invariants

Before touching any frontend code:
1. **Repository Context:** Check `README.md`, `CLAUDE.md`, and `.opencode/ORCHESTRATOR.md` to understand TrackSeerr's architecture (FastAPI backend + static Alpine.js/Tailwind SPA with zero build step, pure browser-native execution).
2. **Strict Division of Labor:**
   - The Orchestrator delegates all production code modifications to the **AGY Execution Engine**.
   - All proposed UI features must be specified via structured handoffs and verified through autonomous gates.
3. **No AI-Slop Dark Mode:**
   - NEVER use generic slate/indigo/deep-navy backgrounds (`#020617`, `#0f172a`, `bg-slate-950`).
   - All surfaces must follow the **Obsidian & Matte Carbon** palette.
4. **No Emojis:**
   - Never use emojis anywhere in the UI. Always use custom inline SVG icons with clean geometry.
5. **DOM Hierarchy & Alpine Integrity:**
   - Preserve all existing Alpine.js bindings (`x-data="plexHubApp()"`, `@click`, `x-show`, `x-model`).
   - Every opening HTML tag must be strictly balanced. Settings subtabs must remain at identical DOM depth under the Settings tab container.

---

## Phase 2: Tactile Tape Deck & Walkman Design System

TrackSeerr's visual and tactile identity is modeled after classic high-end portable cassette players (Sony Walkman TPS-L2 / WM series) and precision studio tape decks. Navigation and controls must evoke physical mechanical equipment.

### 1. Recessed Transport Bays (`.tape-transport-bay`)
- Navigation bars, tab strips, and grouped action bars sit inside a recessed deck chassis slot:
  ```css
  background: #0d0d0d;
  border: 1px solid #1f1f1f;
  box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.8), 0 1px 0 rgba(255, 255, 255, 0.04);
  border-radius: 4px;
  padding: 3px;
  ```

### 2. Physical Transport Keys (`.tape-deck-btn`)
- Buttons are tactile, beveled mechanical keys:
  - **Idle State:** Raised appearance with top highlight and bottom shadow:
    `background: linear-gradient(180deg, #1f1f1f 0%, #151515 100%);`
    `border: 1px solid #2a2a2a; border-top-color: #383838; border-bottom-color: #111111;`
    `box-shadow: 0 2px 0 #050505, inset 0 1px 0 rgba(255, 255, 255, 0.08);`
    `border-radius: 3px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;`
  - **Hover State:** Crisp metallic sheen:
    `background: linear-gradient(180deg, #262626 0%, #1a1a1a 100%); color: #ffffff;`
  - **Active / Engaged State (Physically Locked Down):**
    `transform: translateY(2px);`
    `background: #0f0f0f;`
    `box-shadow: inset 0 2px 5px rgba(0, 0, 0, 0.9), inset 0 0 0 1px rgba(255, 255, 255, 0.04);`
    `color: #ffffff;`
  - **Active Indicator LED (`.tape-deck-indicator`):**
    A 2px high amber illuminated jewel (`background: #e5a00d; box-shadow: 0 0 6px rgba(229, 160, 13, 0.8);`) at the top edge of an engaged key, mimicking vintage tape-run indicators.
  - **Interaction Timing:** Rapid, spring-loaded tactile transition (`transition: all 0.08s ease-out`).

### 3. Tactile Mechanical Switches (`.tactile-switch`)
- Mobile drawer toggles and slider controls feature embossed mechanical grip ribs and tactile click states.

---

## Phase 3: Minimalist Obsidian Palette & Industrial Fillets

### 1. Palette Tokens (CSS Custom Properties)
```css
--bg-canvas: #0a0a0a;              /* Pure obsidian dark canvas */
--bg-surface: #121212;             /* Machined deck chassis */
--bg-surface-elevated: #181818;    /* Elevated modules & controls */
--bg-card: #141414;                /* Base card well */
--bg-card-hover: #1c1c1c;          /* Card interaction */
--border-subtle: #222222;          /* Subtle chassis seam */
--border-default: #2a2a2a;         /* Hairline structural border */
--border-hover: rgba(229, 160, 13, 0.45);
--text-primary: #ffffff;           /* Brilliant crisp white */
--text-secondary: #a3a3a3;         /* Clean neutral silver-grey */
--text-muted: #666666;             /* Clean muted grey */
--accent-amber: #e5a00d;           /* Analog VU-meter / Walkman cue amber */
--accent-amber-glow: rgba(229, 160, 13, 0.25);
--status-success: #22c55e;         /* Analog phosphor green */
--status-error: #ef4444;           /* Alert red */
```

### 2. Sharp Industrial Fillet Invariant
- **No generic bubbly corners:** NEVER use `rounded-2xl`, `rounded-3xl`, or large 16px/24px bubble radii.
- **Precision Machined Radii:**
  - Modals: 4px (`rounded-[4px]`) on desktop, 0px (`rounded-none`) on mobile.
  - Cards: 4px (`rounded-[4px]`).
  - Buttons / Controls: 3px (`rounded-[3px]`).
  - Hairline 1px borders with subtle metallic highlights.

---

## Phase 4: Mobile-First Full-Width Architecture

On mobile viewports (`< 640px` / `sm`):
1. **Full-Width Modals:**
   - Modals MUST span 100% full width (`w-full max-w-none m-0 rounded-none sm:rounded-[4px] sm:max-w-2xl sm:m-auto`).
   - Zero pinched side margins on mobile. Content bleeds cleanly edge-to-edge.
   - Modals take full viewport height on mobile (`h-full sm:h-auto sm:max-h-[90dvh]`) with internal scrolling via `.modal-body-scroll`.
2. **Full-Width Cards & Grids:**
   - Cards span full width on small screens (`w-full`).
   - Use `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4` for album/artist lists.
3. **Full-Width Navigation Drawer:**
   - Mobile navigation menu spans 100% width with large, thumb-friendly tactile tape deck keys (min 44px height).
4. **Safe Area Insets:**
   - Always apply `pt-safe` and `pb-safe` to fixed headers and bottom drawers to respect notches and home indicators.

---

## Phase 5: PWA & Installed Mobile App Assets

1. **Manifest Configuration:**
   - Maintain `plex_playlist_sync/static/manifest.json` with `display: "standalone"`, `theme_color: "#0a0a0a"`, and `background_color: "#0a0a0a"`.
   - Provide high-resolution vector and raster icons: `favicon.svg`, `favicon.png`, `icon-192.png`, and `icon-512.png`.
2. **Mobile Meta Tags in `index.html`:**
   - `<link rel="manifest" href="/static/manifest.json">`
   - `<link rel="apple-touch-icon" href="/static/apple-touch-icon.png">`
   - `<meta name="mobile-web-app-capable" content="yes">`
   - `<meta name="apple-mobile-web-app-capable" content="yes">`
   - `<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">`
   - `<meta name="apple-mobile-web-app-title" content="TrackSeerr">`
   - `<meta name="theme-color" content="#0a0a0a">`

---

## Phase 6: Autonomous Validation & Anti-Stub Gates

Every frontend change MUST pass these gates before being committed:
1. **Python Syntax Check:**
   `python3 -m py_compile plex_playlist_sync/**/*.py tests/**/*.py`
2. **Full Pytest Suite via Docker:**
   `docker run --rm -v "$PWD":/app -w /app -e PYTHONPATH=/app trackseerr:test pytest tests/test_frontend.py tests/test_branding_assets.py -v --tb=short`
3. **HTML DOM Integrity:**
   Ensure zero unclosed tags and zero tag mismatches via `TestDOMIntegrity` in `tests/test_frontend.py`.
4. **Skeptical Anti-Stub Audit:**
   Verify no temporary mocks, no hardcoded blue AI-slop colors, and no broken responsive layouts.
