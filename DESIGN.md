---
name: ConnectSphere
description: Restrained neutral-gray Operate-mode UI for event/venue booking workflows, one indigo accent, built to the craft level of Linear, Notion, and Luma.
colors:
  primary: "#3730a3"
  primary-dark: "#292367"
  primary-soft: "#eef0fd"
  accent: "#4f46e5"
  secondary: "#eef0fd"
  ink: "#17181c"
  muted: "#6b6f7b"
  faint: "#9497a3"
  border: "#e4e4e9"
  border-strong: "#d3d4db"
  surface: "#ffffff"
  background: "#f7f7f9"
  sidebar: "#fbfbfc"
  success: "#0f7a4d"
  success-soft: "#e7f6ee"
  warning: "#92600a"
  warning-soft: "#fdf1dc"
  error: "#b3261e"
  error-soft: "#fbe9e8"
typography:
  headline:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.015em"
  title:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "18px"
    fontWeight: 600
    letterSpacing: "-0.01em"
  subtitle:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "14.5px"
    fontWeight: 600
  body:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "13.5px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "10.5px"
    fontWeight: 600
    letterSpacing: "0.06em"
rounded:
  sm: "6px"
  md: "8px"
  lg: "12px"
  pill: "999px"
spacing:
  1: "4px"
  2: "8px"
  3: "12px"
  4: "16px"
  5: "24px"
  6: "32px"
  7: "40px"
  8: "56px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
    padding: "9px 15px"
  button-primary-hover:
    backgroundColor: "{colors.primary}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "9px 15px"
  button-approve:
    backgroundColor: "{colors.success-soft}"
    textColor: "{colors.success}"
    rounded: "{rounded.sm}"
    padding: "9px 15px"
  button-reject:
    backgroundColor: "{colors.error-soft}"
    textColor: "{colors.error}"
    rounded: "{rounded.sm}"
    padding: "9px 15px"
  card-panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "24px"
  input-field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "9px 11px"
---

# Design System: ConnectSphere

## Overview

**Creative North Star: "The Operate-Mode Console"**

ConnectSphere is a neutral, functional console for a multi-role approval workflow, not a marketing surface. The palette stays almost entirely gray — near-black ink on an off-white canvas, white cards — with a single indigo accent reserved for brand marks, active navigation state, primary actions, and the dashboard welcome panel. Density is tight (13-13.5px body text, 8px/16px/24px spacing steps) and every visual signal (status badge, venue availability, impact row) resolves through a colored dot plus a soft tint background rather than borders or iconography alone. The explicit anti-references, confirmed by the brief and matched by the shipped CSS, are gradient text, hard offset shadows, and any kicker/eyebrow label above headings — none of these appear anywhere in `App.css` or `index.css`.

The system borrows its restraint from Linear, Notion, and Luma: chrome recedes, content and state carry the visual weight, and the one accent color is spent sparingly enough that its appearances (active nav item, primary button, focus ring, welcome panel) read as deliberate rather than decorative.

**Key Characteristics:**
- Near-monochrome neutral gray scale with exactly one indigo accent pair (`--color-accent` / `--color-primary`)
- Dot-indicator badges for all status/availability states (never color-only, never icon-only)
- Hand-authored outline SVG icon set (1.75px stroke, 24×24 viewBox) — no glyph/emoji icons anywhere
- Flat cards with a single soft ambient shadow, 8-12px radii, no hard offset shadows
- No kickers or eyebrow labels above any heading, anywhere in the shipped UI

## Colors

The palette is a tight neutral-gray scale carrying nearly all UI weight, with one indigo accent pair spent on brand and primary-action moments only.

### Primary
- **Deep Indigo** (`#3730a3`, token `primary`): brand mark background, active nav background is a soft tint of this but the active nav *text* and icon use `accent`; the dashboard welcome panel background; role pill text; hover state for primary buttons (darkens from `accent`).
- **Indigo Accent** (`#4f46e5`, token `accent`): primary button background, focus ring/border color on inputs, `:focus-visible` outline, active nav icon/text color, links (venue card link, text-button).

### Neutral
- **Ink** (`#17181c`, token `ink`): primary text color, default button text, table row text.
- **Muted** (`#6b6f7b`, token `muted`): secondary text, hints, table headers, meta labels, role switcher.
- **Faint** (`#9497a3`, token `faint`): tertiary text, inactive nav icons, scrollbar thumb hover.
- **Border** (`#e4e4e9`, token `border`): default hairline dividers between panels, table rows, sidebar edge.
- **Border Strong** (`#d3d4db`, token `border-strong`): input borders, secondary button borders, hover state on card borders.
- **Surface** (`#ffffff`, token `surface`): card/panel/dialog background.
- **Background** (`#f7f7f9`, token `background`): page canvas, table header row, hover row tint.
- **Sidebar** (`#fbfbfc`, token `sidebar`): sidebar background, one step lighter-warm than the page canvas.
- **Primary Soft** (`#eef0fd`, token `primary-soft`): active nav background, action-card icon chip background, focus-ring glow (`box-shadow` halo), "submitted" status badge background.

### Status colors
- **Success** (`#0f7a4d` on `#e7f6ee`): approved status, "available" venue status, success impact rows.
- **Warning** (`#92600a` on `#fdf1dc`): pending status, "booked"/maintenance-adjacent venue status, role warnings, notices.
- **Error** (`#b3261e` on `#fbe9e8`): rejected status, unavailable/closed venue status, required-field marker, rejection dialog.

### Named Rules
**The One Accent Rule.** `accent`/`primary` indigo appears only on: the brand mark, active navigation state, primary buttons, focus rings, links, and the dashboard welcome panel. Every other surface stays neutral gray; status and severity are carried by the success/warning/error trio, never by the brand accent.

**The Dot-Before-Color Rule.** Every status or availability indicator (`.status-badge`, `.venue-status`) pairs a small `currentColor` dot (`::before`, 6px circle) with a soft tint background. Color alone never carries the state.

## Typography

**Body Font:** Inter (with `-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`)

**Character:** A single, tightly-tracked Inter family for the entire interface — no serif or display face, no mono face for labels. Weight (400/500/600) and size (10.5px–22px) do the differentiating work, not font-family switching.

### Hierarchy
- **Headline** (600, 20px, tight `-0.015em` tracking): page `h1` in the topbar.
- **Title** (600, 18px, `-0.01em` tracking): section/card `h2` (event card titles, welcome panel heading, dialog headings — the welcome `h2` steps up to 22px as its one exception).
- **Subtitle** (600, 14.5px): `h3` form-section headings, venue card names, event-meta strong labels.
- **Body** (400, 13-13.5px, 1.5-1.6 line-height): form field values, muted descriptive copy, dialog copy.
- **Label** (600, 10.5-12px, uppercase or `0.04-0.06em` tracking): table headers, `nav-label` ("Workspace"), `event-detail dt`, rejection-field required marker. These are structural table/field labels, not decorative kickers — none sit above a heading as a standalone eyebrow.

### Named Rules
**The No-Kicker Rule.** No uppercase label token is ever placed directly above a heading as a standalone eyebrow/kicker element. Uppercase micro-labels exist only as functional annotations (table column headers, form field group labels, `dt` terms) that are never paired with a heading immediately below them.

## Layout

Single fixed left sidebar (240px, collapsing to a 64px icon rail under 850px) plus a fluid main column; there is no top-level grid system beyond this two-pane shell. Page content centers in a `max-width: 1180px` column with `6%` horizontal padding (narrowing to `5%` under 600px) and a consistent `24px` (`--space-5`) vertical stack gap. The spacing rhythm is an 8-step scale (4/8/12/16/24/32/40/56px) used consistently for padding and gaps; two-column form rows (`.field-row`, `.two-column`) collapse to one column under 600px, and card grids (`.card-grid`, `.venue-card-grid`) collapse to one column under 850px. The topbar is a fixed-height (76px) horizontal bar separating navigation from page title and the role switcher.

## Elevation & Depth

Elevation is a flat-plus-single-shadow system: surfaces sit at rest with a low-diffusion ambient shadow (`--shadow-sm`) or no shadow at all, and only step up in weight on hover/interactive states or for overlays. There are no hard offset ("brutalist") shadows anywhere in the build.

### Shadow Vocabulary
- **Resting card** (`box-shadow: 0 1px 2px rgba(23,24,28,0.05)`, token `shadow-sm`): default panel/action-card elevation.
- **Hover lift** (`box-shadow: 0 2px 8px rgba(23,24,28,0.06), 0 1px 2px rgba(23,24,28,0.05)`, token `shadow`): action-card and venue-card hover/focus-visible state, paired with a 1-2px `translateY` lift.
- **Overlay** (`box-shadow: 0 16px 40px rgba(23,24,28,0.12), 0 4px 12px rgba(23,24,28,0.06)`, token `shadow-lg`): submission and rejection `<dialog>` elements.

### Named Rules
**The Ambient-Only Rule.** Shadows are always soft, multi-stop, and diffuse (`rgba(23,24,28,...)` at low opacity); no shadow in the codebase uses a hard, non-blurred offset. This is a build invariant, not a stylistic preference to relax.

## Shapes

Radii scale in three steps: 6px (`--radius-sm`, buttons, nav buttons, inputs), 8px (`--radius`, action-card icon chips, reject-box), and 12px (`--radius-lg`, panels, cards, dialogs, welcome panel). Pills (`999px`) are reserved for status badges, chips, and the role pill. Borders are single 1px hairlines in `border` or `border-strong`; there is no double-border or outline-plus-fill treatment. Icons follow a matching form language: 1.75px stroke weight, rounded caps/joins, 24×24 viewBox, hand-authored outline paths (see `src/components/Icon.tsx`) — no filled glyphs, no emoji, no third-party icon font.

## Components

### Buttons
- **Shape:** 6px radius (`--radius-sm`), 1px transparent border that colors only on the secondary variant.
- **Primary:** `accent` (#4f46e5) background, white text, 9px 15px padding; hover darkens to `primary` (#3730a3).
- **Secondary:** white surface background, `border-strong` (#d3d4db) border, `ink` text; hover moves border to `faint` and background to `background`.
- **Approve / Reject:** semantic soft-tint variants — approve uses `success-soft`/`success`, reject uses `error-soft`/`error` — for row-level and dialog approval actions.
- **Small:** same variants at 6px 10px padding, 11.5px type, used inline in tables.
- **Disabled:** 0.55 opacity, `not-allowed` cursor, no color change otherwise.

### Chips
- **Style:** `background` (#f7f7f9) fill, `ink` text, pill radius, 11px/500 weight; used for venue facility tags (`.chip`) and a transparent "+N more" overflow variant (`.chip-more`).

### Cards / Containers
- **Corner Style:** 12px radius (`--radius-lg`) on panels, event cards, action cards, venue cards.
- **Background:** white surface on the page's off-white canvas.
- **Shadow Strategy:** resting `shadow-sm`, hover lift to `shadow` with a 1-2px translateY (see Elevation & Depth).
- **Border:** 1px `border`, strengthening to `border-strong` on hover.
- **Internal Padding:** 24px (`--space-5`) standard panel padding; event/venue cards use zero outer padding with internal section padding instead, to support divided header/body/footer zones.

### Inputs / Fields
- **Style:** 1px `border-strong` stroke, white background, 6px radius, 9px 11px padding (13.5px text).
- **Focus:** border shifts to `accent` plus a 3px `primary-soft` glow ring (`box-shadow: 0 0 0 3px var(--color-primary-soft)`); `:focus-visible` elsewhere uses a solid 2px `accent` outline with 2px offset.
- **Error / Disabled:** required-field markers render in `error` red inline next to the label; no dedicated visual error state on the input border itself is present in the build.

### Navigation
- Fixed left sidebar, 13.5px/500-weight nav labels with a 17px outline icon at 10px gap. Default state: `muted` text and `faint` icon on transparent background. Hover: `border`-tinted background, `ink` text. Active: `primary-soft` background, `primary` text and icon (accent family, not a border or underline indicator). Below 850px the sidebar collapses to a 64px icon-only rail (labels and the "Workspace" section label hide); nav items stay center-aligned icon buttons.

### Status Badge (signature component)
Every status or availability state in the product (request status, venue availability) renders as a pill: soft tint background, semantic text color, small `currentColor` dot before the label, 11px/600 weight. This one pattern (`.status-badge`, `.venue-status`) is reused verbatim across the dashboard, request tables, event detail, and venue catalogue rather than each surface inventing its own indicator.

## Do's and Don'ts

### Do:
- **Do** confine the indigo accent (`#4f46e5`/`#3730a3`) to brand mark, active nav, primary buttons, focus rings, links, and the welcome panel — see The One Accent Rule.
- **Do** pair every status/availability indicator with a `currentColor` dot plus a soft tint background (`.status-badge`, `.venue-status`), never color alone.
- **Do** use the hand-authored 1.75px-stroke outline icon set (`src/components/Icon.tsx`) for all iconography; extend it in the same style rather than pulling in an icon font or filled glyphs.
- **Do** keep shadows soft and diffuse (`rgba(23,24,28,...)`, multi-stop, no hard offset) per The Ambient-Only Rule.
- **Do** use the three-step radius scale (6px controls / 8px chips / 12px cards-dialogs) and pill (999px) only for badges, chips, and pills.

### Don't:
- **Don't** introduce a kicker or eyebrow label above any heading — the build contains none, and none should be added (The No-Kicker Rule).
- **Don't** use hard offset ("brutalist") shadows; every shadow in the shipped system is soft and ambient.
- **Don't** introduce a second accent hue; the system is neutral gray plus one indigo pair, with success/warning/error reserved strictly for status semantics.
- **Don't** use emoji, unicode symbols, or a system display face for icons or headings; the outline SVG set and Inter are the only vocabulary.
- **Don't** reintroduce gradient text or gradient fills; none exist in the build and none are part of this system.
