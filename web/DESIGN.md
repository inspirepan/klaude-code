# Design System: Klaude Web

## 1. Visual Theme & Atmosphere

A **quiet, utilitarian, information-dense** terminal companion. The interface feels like a professional IDE sidebar merged with a chat client -- the visual weight sits almost entirely on the content, not on the chrome. Every surface is low-saturation neutral; color appears only to communicate state (running, success, error, warning). The overall mood is calm, tool-like, and engineer-facing. Think "Linear meets a terminal" rather than "ChatGPT."

The design philosophy is **disappearing UI**: controls hide until hovered, borders are barely visible, shadows are whisper-light, and the user's attention is guided purely by typographic hierarchy and the content stream. The interface should feel as if it was built by someone who thinks decoration is a bug.

## 2. Color Palette & Roles

All colors are delivered via HSL CSS custom properties in `:root` / `.dark`, consumed through Tailwind's `hsl(var(--token))` pattern. This section documents the **light theme** (primary target) with dark-theme overrides noted where they diverge meaningfully.

### Neutral Foundation

| Token | HSL | Hex (approx.) | Role |
|-------|-----|---------------|------|
| `--background` | `0 0% 98%` | `#fafafa` | Main content area -- barely-warm off-white |
| `--foreground` | `0 0% 3.9%` | `#0a0a0a` | Primary text -- near-black for maximum readability |
| `--surface` | `0 0% 96.1%` | `#f5f5f5` | Code blocks, thinking blocks, recessed containers |
| `--muted` | `0 0% 89.8%` | `#e5e5e5` | Sidebar background, secondary fills, badges |
| `--muted-foreground` | `0 0% 45.1%` | `#737373` | De-emphasized text -- timestamps, metadata, placeholders |
| `--border` | `0 0% 83.1%` | `#d4d4d4` | Hairline dividers, card edges (always 1px) |
| `--sidebar` | `0 0% 96.1%` | `#f5f5f5` | Left sidebar fill |
| `--card` | `0 0% 100%` | `#ffffff` | Cards, popovers, composer -- pure white for lift |

### Semantic Colors

| Name | Value | Role |
|------|-------|------|
| Blue-500 | `#3b82f6` | Primary interactive accent -- submit buttons, selected options, question icons, focused inputs |
| Blue-50/80 | `#eff6ff` | Selected pill backgrounds, focus rings |
| Amber-600 | `#d97706` | Active/running state -- interrupt button, active ring |
| Amber-300/70 | `#fcd34d` | Active message highlight ring |
| Green-700 | `#166534` | Success settle animation start color |
| Red-500 | `#ef4444` | Error text, destructive actions |
| Neutral-800 | `#262626` | Default send button, primary dark elements |
| Neutral-400/500 | `#a3a3a3` / `#737373` | Icons at rest, secondary text, placeholder text |

### Fixed-Purpose Colors

| Name | Value | Role |
|------|-------|------|
| `user-bubble` | `rgb(229, 243, 255)` | User message background -- pale blue tint |
| `user-bubble-hover` | `rgb(219, 238, 255)` | User message hover |
| `user-bubble-text` | `rgb(0, 40, 77)` | User message text -- deep navy |
| `compaction-label` | `#5b6f92` | Compaction summary label text |
| `compaction-text` | `#2f3f5f` | Compaction summary body text |

### Dark Theme Shift

Dark mode inverts the neutral scale but keeps the same semantic color mapping. `--background` becomes `0 0% 3.9%` (near-black), `--surface` becomes `0 0% 7%`, borders drop to `0 0% 14.9%`. The palette remains achromatic -- no blue/purple tint in dark backgrounds.

## 3. Typography Rules

### Font Stack

| Role | Family | Fallback Chain |
|------|--------|----------------|
| **UI / Body** | `IBM Plex Sans Variable` | system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Noto Sans CJK SC", sans-serif |
| **Code / Monospace** | `Lilex Variable` | ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace |
| **Display (reserved)** | `TX-02` | Loaded as @font-face (400/700, normal/italic); not yet actively used in the UI |

### Scale (overridden from Tailwind defaults)

The entire type scale is shifted one notch smaller than Tailwind's defaults to achieve information density without feeling cramped:

| Tailwind Class | Actual Size | Line Height | Usage |
|----------------|-------------|-------------|-------|
| `text-xs` | 11px (0.6875rem) | 16px | Timestamps, metadata chips, keyboard hints |
| `text-sm` | 12px (0.75rem) | 16px | Secondary labels, sidebar text, tool headers |
| `text-base` | 14px (0.875rem) | 20px | Body text, assistant messages, input fields |

### Weight & Style Conventions

- **Regular (400)**: All body text, assistant responses, input
- **Medium (500)**: Frontmatter keys, section headers, active sidebar items
- **Semibold (600)**: Buttons, tool names in monospace, group collapse labels
- **Bold (700)**: Reserved for display `TX-02` usage only
- **Italic**: Thinking blocks are rendered entirely in italic to distinguish internal reasoning from output

### Character

Anti-aliased rendering (`-webkit-font-smoothing: antialiased`). The assistant text area uses generous `line-height: 1.7` for comfortable reading of long-form markdown. Code blocks and tool output use the monospace stack at `0.95em` relative size. The overall typographic feel is **compact but breathable** -- high information density with enough vertical rhythm to avoid fatigue.

## 4. Component Stylings

### Buttons

- **Shape**: `rounded-md` (6px effective radius). Full-round (`rounded-full`) for icon-only circular actions (send, add image, close).
- **Height scale**: `h-7` (28px) for inline/compact, `h-8` (32px) for standard, `h-9`/`h-10` for emphasized.
- **Shadow**: `shadow-sm` on default/destructive/outline variants. Ghost and link variants have no shadow.
- **Hover**: Color shift only (`bg-primary/90`, `bg-accent`). No scale, no translate.
- **Active/Press**: No `:active` scale transform currently applied. **Opportunity**: add `transform: scale(0.97)` on `:active` for tactile press feedback per Emil Kowalski's principle.
- **Disabled**: `opacity-50` + `pointer-events-none`. Clean, no grayed-out background trick.
- **Focus**: `focus-visible:ring-1 focus-visible:ring-ring` -- thin ring, only on keyboard focus.
- **Transition**: `transition-colors` only. No duration specified (Tailwind default 150ms).

### Cards & Containers

- **Composer card**: `rounded-lg` (8px), `bg-white`, `shadow-sm`, `ring-1 ring-black/[0.06]`. The ring is almost invisible -- just enough to define the card edge against the off-white background. This is the signature "barely-there border" pattern.
- **User interaction card**: `rounded-2xl` (16px), `border border-neutral-200/80`, `bg-white`, `shadow-sm shadow-neutral-200/40`. Slightly more elevated than the composer -- rounder corners signal "this needs your attention."
- **Sidebar**: Flat `bg-sidebar` with a single `border-r border-neutral-200` divider. No shadow. The sidebar should feel like part of the page, not floating above it.
- **Popovers/Dropdowns**: `bg-white`, `border border-neutral-200/80`, `shadow-[0_8px_30px_rgba(0,0,0,0.08)]`. Stronger shadow than cards to establish elevation hierarchy.
- **Tooltips**: `rounded-md`, `border border-neutral-200`, `bg-white`, `shadow-sm`, `text-xs`. Minimal and precise.

### Inputs & Forms

- **Composer textarea**: Borderless, transparent background (`border-0 bg-transparent`). The card itself provides the visual container.
- **Search/filter inputs**: `rounded-lg`, `border border-neutral-200`, `bg-surface/50`. On focus: `border-blue-300 bg-white ring-2 ring-blue-100`.
- **Selection pills (radio/checkbox)**: `rounded-lg`, `border px-3 py-2`. Selected state uses `border-blue-200 bg-blue-50/80 ring-1 ring-blue-200/60`. Unselected: `border-neutral-200 bg-white hover:border-neutral-300 hover:bg-surface`. The selection indicator is a small `rounded-full` circle with inner dot.

### Collapse & Expand Groups

- **Rail marker**: Monospace `text-sm text-neutral-500` label (`[-]`/`[+]`) with a vertical `w-px bg-neutral-200` connecting line.
- **Panel animation**: `transition-[height] duration-200 ease-out` with imperative DOM height measurement (`useLayoutEffect`). Inner content uses `backface-visibility: hidden` for GPU compositing during height transitions.
- **No conditional rendering**: Collapsed content stays in DOM with `overflow: hidden` and `height: 0`. This prevents layout recalculation mid-animation.

### Diff View

- Uses `@pierre/diffs` with the project's mono font stack injected via `--diffs-font-family`. Tall diffs get a gradient fade mask at the bottom with a "Show more/less" toggle.

### Status Indicators

- **Running**: `animate-spin` loader icon (Lucide `Loader`), `text-neutral-500`
- **Success settle**: Custom keyframe animation -- starts at green `#166534` with `scale(0.9)`, settles to `#a3a3a3` at `opacity: 0.82` over 1.6s `ease-out`. The card background simultaneously fades from green-100 to transparent.
- **Unread dot**: Small `rounded-full` green circle in the sidebar.
- **Error**: Red text, dashed border container for retry states.

## 5. Layout Principles

### Overall Structure

A two-column layout: **sidebar + main panel**. The sidebar is resizable via drag (width persisted to `localStorage`). The main panel fills remaining space (`flex: 1; min-width: 0`). Both columns are `overflow: hidden` -- all scrolling happens inside dedicated `ScrollArea` (Radix) containers.

### Spacing Strategy

- **Macro spacing**: The main content area uses `px-4 sm:px-6` horizontal padding. The sidebar uses `px-2` to `px-3`.
- **Message list bottom padding**: Dynamically calculated via CSS variable `--composer-h` (set by `ResizeObserver` on the composer). This ensures messages are never hidden behind the fixed-position composer.
- **Vertical rhythm in messages**: Minimal gaps between items in the same "turn." Larger visual breaks between user message sections. The overall density is high -- no excessive whitespace between tool blocks and assistant text.

### Width Constraints

- **Message content**: No explicit `max-width` on the content column. The content stretches to fill the main panel. Very wide screens will produce long lines -- this is intentional for code-heavy output. Markdown prose uses `line-height: 1.7` to maintain readability at width.
- **Sidebar**: Default width stored in `localStorage`, resizable. Minimum and maximum bounds enforced during drag.

### Scroll Behavior

- **Never use native `overflow-y-auto`**. All scrollable regions use the shared `ScrollArea` component (Radix). The thin scrollbar style: 6px wide, `rgba(163,163,163,0.3)` thumb, transparent track.
- **Auto-scroll to bottom**: During streaming, the message list pins to the bottom. A "scroll to bottom" button appears when the user scrolls up.
- **Scroll position restoration**: When navigating between sessions, the previous scroll position is restored.

### Responsive Behavior

- Narrow viewports auto-collapse the sidebar.
- The composer and message list share a single column -- no multi-pane layouts on mobile.

## 6. Interaction & Animation Principles

Guided by the principle that **animation frequency determines animation presence**: high-frequency actions get zero animation; rare actions get standard transitions.

### Animation Decision Matrix

| Element | Frequency | Animation |
|---------|-----------|-----------|
| Keyboard shortcuts (Cmd+B, Cmd+Shift+O) | 100+/day | **None** -- instant state change |
| Tooltip appearance | Tens/day | 125ms fade + zoom + directional slide (on `delayed-open` only) |
| Collapse/expand groups | Tens/day | 200ms `ease-out` height transition |
| Sidebar show/hide | Occasional | 200ms `ease-in-out` grid-template-columns transition |
| Streaming text | Continuous | `stream-fade-in`: 120ms `ease-out` opacity (near-instantaneous) |
| Success settle | Rare | 1.6s multi-stage keyframe (green flash -> neutral fade) |
| Todo shimmer | Continuous | 3.6s linear gradient sweep (subtle, background) |

### Easing

- **Entering/exiting elements**: `ease-out` -- starts fast, decelerates. The default for 90% of transitions.
- **Bidirectional movement** (sidebar resize): `ease-in-out`.
- **Constant motion** (shimmer, spinner): `linear`.
- **Never use `ease-in`** for UI transitions. It makes the interface feel sluggish because it delays the initial movement -- the exact moment the user is watching.

### Hover Patterns

- **Hide-until-hover**: Controls like copy buttons, archive buttons, and attachment delete buttons are `opacity-0` by default, revealed via `group-hover:opacity-100` with `transition-opacity duration-150`. This keeps the interface clean when scanning, interactive when engaging.
- **Color-only hover**: Buttons and sidebar items change background/text color on hover. No scale, no translate, no shadow change.
- **Tooltip delay strategy**: Standard delay before first tooltip. Once one tooltip is open, subsequent tooltips should open instantly with no animation (`data-instant` pattern). Currently uses Radix's default timing -- can be optimized.

### What NOT to Animate

- Command palette / keyboard-triggered overlays: instant open/close.
- Message list scroll: native momentum, no smooth-scroll override.
- Text content changes: no fade/slide on text updates during streaming.

## 7. Iconography

All icons from **Lucide React**. Sizing follows these conventions:

| Context | Size | Additional Classes |
|---------|------|--------------------|
| Inline with text | `h-3.5 w-3.5` or `h-4 w-4` | `shrink-0` |
| Toolbar / action buttons | `h-4 w-4` | `shrink-0` |
| Sidebar navigation | `h-4 w-4` | `shrink-0` |
| Status indicators | `h-3 w-3` | `shrink-0`, sometimes `animate-spin` |

Alignment rule: Icons in flex rows use `items-center` for single-line layouts, `items-start` + `mt-*` for multi-line. Never use `items-baseline` with icons. Never use `vertical-align` hacks.

## 8. Shadows & Depth

The elevation system is extremely flat -- three levels total:

| Level | Shadow | Usage |
|-------|--------|-------|
| **Ground** | None | Sidebar, message list, backgrounds |
| **Card** | `shadow-sm` or `ring-1 ring-black/[0.06]` | Composer, tool result cards, session cards |
| **Floating** | `shadow-[0_8px_30px_rgba(0,0,0,0.08)]` | Dropdowns, archived menu, model selector |
| **Toast** | `shadow-[0_8px_24px_-16px_rgba(15,15,15,0.35)]` + `backdrop-blur` | Undo toasts, transient notifications |

No heavy drop shadows anywhere. The depth hierarchy is communicated primarily through **background color contrast** (white card on off-white background) rather than shadow.

## 9. Dark Mode Strategy

Dark mode uses a pure achromatic palette -- no blue, purple, or warm tint in backgrounds. The `--background` inverts to near-black (`0 0% 3.9%`), surfaces go to `0 0% 7%`. Semantic accent colors (blue, amber, green, red) retain their hue but may shift lightness for contrast.

The `darkMode: ["class"]` approach means dark mode is toggled by adding `.dark` to the root element, not by `prefers-color-scheme`. This allows explicit user control.

## 10. Design Opportunities & Gaps

Areas where the current implementation can be improved, informed by the Emil Kowalski design engineering philosophy:

### Missing Tactile Feedback
- Buttons lack `:active` scale. Add `transform: scale(0.97)` with `transition: transform 160ms ease-out` to all pressable elements. This single change makes the entire interface feel more responsive.
- Send button (the most-pressed element) should have the most satisfying press response.

### Animation Refinements
- Tooltip `transform-origin` should use `var(--radix-tooltip-content-transform-origin)` to scale from the trigger point, not center. Currently using default.
- Popover/dropdown `transform-origin` should similarly use Radix's `--radix-popover-content-transform-origin`.
- The success settle animation starts from `scale(0.9)` -- acceptable, but `scale(0.95)` would feel more natural per the "never animate from scale(0)" principle.

### Hover State Gaps
- Hover animations should be gated behind `@media (hover: hover) and (pointer: fine)` to prevent false positives on touch devices.

### Custom Easing Curves
- Current transitions use Tailwind defaults (`ease-out`, `ease-in-out`). These are too gentle. Consider custom curves:
  - `cubic-bezier(0.23, 1, 0.32, 1)` for a punchier ease-out
  - `cubic-bezier(0.77, 0, 0.175, 1)` for smoother ease-in-out

### Performance
- Height-based collapse animations are correctly using `transition-[height]` with `backface-visibility: hidden` -- this is the right approach.
- `transition: all` should be audited and replaced with specific property transitions wherever found.
- CSS animations (spinners, shimmer) are already off-main-thread. Good.

### Accessibility
- `prefers-reduced-motion` is not yet implemented. Add a media query to reduce or eliminate transform/position animations while keeping opacity/color transitions for state indication.

### Perceived Speed
- Streaming text uses a 120ms fade-in -- good, nearly instant.
- Consider making the loading spinner slightly faster to improve perceived load times.
- The `useStreamThrottle` hook (80ms minimum update interval) is a good balance between smoothness and performance.
