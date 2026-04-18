# Design System: Klaude Web

## 1. Visual Theme & Atmosphere

A **quiet, utilitarian, information-dense** terminal companion. The interface feels like a professional IDE sidebar merged with a chat client -- the visual weight sits almost entirely on the content, not on the chrome. Every surface is low-saturation neutral; color appears only to communicate state (running, success, error, warning). The overall mood is calm, tool-like, and engineer-facing. Think "Linear meets a terminal" rather than "ChatGPT."

The design philosophy is **disappearing UI**: controls hide until hovered, borders are barely visible, shadows are whisper-light, and the user's attention is guided purely by typographic hierarchy and the content stream. The interface should feel as if it was built by someone who thinks decoration is a bug.

## 2. Color Palette & Roles

All colors are delivered via HSL CSS custom properties in `:root` / `.dark`, consumed through Tailwind's `hsl(var(--token))` pattern. This section documents the **light theme** (primary target) with dark-theme overrides noted where they diverge meaningfully.

### Neutral Foundation

| Token                | HSL          | Hex (approx.) | Role                                                      |
| -------------------- | ------------ | ------------- | --------------------------------------------------------- |
| `--background`       | `60 14% 97%` | `#f8f8f6`     | Main content area -- warm off-white (cream)               |
| `--foreground`       | `0 0% 3.9%`  | `#0a0a0a`     | Primary text -- near-black for maximum readability        |
| `--surface`          | `0 0% 96.1%` | `#f5f5f5`     | Code blocks, thinking blocks, recessed containers         |
| `--muted`            | `0 0% 89.8%` | `#e5e5e5`     | Sidebar background, secondary fills, badges               |
| `--muted-foreground` | `0 0% 40%`   | `#666666`     | De-emphasized text -- timestamps, metadata                |
| `--border`           | `0 0% 89.8%` | `#e5e5e5`     | Hairline dividers, card edges (always 1px, = neutral-200) |
| `--input`            | `0 0% 89.8%` | `#e5e5e5`     | Input borders                                             |
| `--sidebar`          | `0 0% 96.1%` | `#f5f5f5`     | Left sidebar fill                                         |
| `--sidebar-border`   | `0 0% 89.8%` | `#e5e5e5`     | Sidebar divider                                           |
| `--card`             | `0 0% 100%`  | `#ffffff`     | Cards, popovers, composer -- pure white for lift          |

### Semantic Colors

Unified color families: **emerald** for success, **red** for error, **amber** for warning/interrupt, **sky** for interactive accent and active/running state.

| Name            | Value                             | Role                                                                                                          |
| --------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Emerald-600/700 | `#059669` / `#047857`             | Success states, completion indicators (todo completed icons/text), unread dots                                |
| Red-500/700     | `#ef4444` / `#b91c1c`             | Error text, destructive actions, error tool results                                                           |
| Amber-500/600   | `#f59e0b` / `#d97706`             | Interrupt button, active ring, validation hints                                                               |
| Sky-500/600/700 | `#0ea5e9` / `#0284c7` / `#0369a1` | Primary interactive accent -- submit buttons, selected options, focused inputs, in-progress todos, @ mentions |
| Sky-50/100/200  | `#f0f9ff` / `#e0f2fe` / `#bae6fd` | Selected pill backgrounds, focus rings, active tab backgrounds                                                |
| Neutral-800     | `#262626`                         | Default send button, primary dark elements                                                                    |

### Fixed-Purpose Colors

| Name                | Value                | Role                                      |
| ------------------- | -------------------- | ----------------------------------------- |
| `user-bubble`       | `rgb(229, 243, 255)` | User message background -- pale blue tint |
| `user-bubble-hover` | `rgb(219, 238, 255)` | User message hover                        |
| `user-bubble-text`  | `rgb(0, 40, 77)`     | User message text -- deep navy            |
| `compaction-label`  | `#5b6f92`            | Compaction summary label text             |
| `compaction-text`   | `#2f3f5f`            | Compaction summary body text              |

### Assistant / Tool Card Tint

Message-level content containers use subtle tinted fills instead of the neutral card surface. The assistant-card border is nearly invisible (`border-stone-200/50`); separation is carried by the tinted shadow rather than the stroke.

| Surface                  | Value                          | Role                                                  |
| ------------------------ | ------------------------------ | ----------------------------------------------------- |
| Assistant-card fill      | `#f8f8f6` (same as background) | Assistant text container — continuous with page       |
| Assistant-card dot/text  | `#2e140c`                      | Leading dot marker + default assistant prose color    |
| Assistant-card shadow    | `rgba(107,76,44, 0.07 / 0.05)` | Warm brown-tinted card shadow (two-stop)              |
| Tool-group fill          | `#e6eee2 /40`                  | Very light green-gray tint for stacked tool-use block |
| Tool-group shadow        | `rgba(70,100,60, 0.07 / 0.05)` | Sage-tinted card shadow (two-stop)                    |
| Card border (both cards) | `border-stone-200/50`          | Hairline stroke at 50% opacity — shadow carries depth |

### Dark Theme Shift

Dark mode inverts the neutral scale but keeps the same semantic color mapping. `--background` becomes `0 0% 3.9%` (near-black), `--surface` becomes `0 0% 7%`, borders drop to `0 0% 14.9%`. The palette remains achromatic -- no blue/purple tint in dark backgrounds.

### Color Rules

- **Never mix green families**: use `emerald-*` exclusively. Never `green-*`.
- **Never mix red families**: use `red-*` exclusively. Never `rose-*`.
- **Never hardcode `bg-white`**: use `bg-card` (adapts to dark mode).
- **Body text uses `--foreground`**: never hardcode `#171717` or other hex values for body text.

## 3. Typography Rules

### Font Stack

| Role                 | Family                  | Source                                                                       | Fallback Chain                                                                                                                |
| -------------------- | ----------------------- | ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| **UI / Body**        | `InterVariable` (Inter) | Self-hosted woff2 from rsms.me, preloaded from `/fonts/InterVariable*.woff2` | -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Noto Sans CJK SC", "Helvetica Neue", Arial, sans-serif |
| **Code / Monospace** | `Geist Mono`            | Google Fonts (`Geist+Mono:wght@100..900`)                                    | ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace                                                              |

**OpenType features**:

- `font-feature-settings: "tnum", "ss02" 0` — tabular numerics on; Inter's tailed-lowercase-`l` (ss02) explicitly off because the variant looks off in mixed contexts.
- `font-variation-settings: "opsz" 28` — forces Inter Variable's Display optical size globally for slightly tighter, more display-like letterforms (Inter ships `opsz` 14–32 on this axis).

**Mono size normalization**: Geist Mono renders ~10% larger visually than Inter at the same pixel size. All native mono elements (`code:not(pre code), pre, kbd, samp`) plus the Tailwind `.font-mono` utility are scaled by `font-size: 0.9em` globally. The `:not(pre code)` guard prevents nested `pre > code` from double-applying the factor. The diff view mirrors this by setting `--diffs-font-size: 0.73rem` and `--diffs-line-height: 1.575rem` (0.8125rem × 0.9, 1.75rem × 0.9).

### Scale & Font Size Zones

Three font sizes, each with a clear domain:

| Tailwind Class | Actual Size      | Line Height | Zone                                    |
| -------------- | ---------------- | ----------- | --------------------------------------- |
| `text-base`    | 16px (1rem)      | 24px        | **Message content** -- the reading zone |
| `text-sm`      | 14px (0.875rem)  | 20px        | **UI chrome** -- everything else        |
| `text-xs`      | 13px (0.8125rem) | 18px        | **Metadata** -- rarely used             |

**`text-base` (16px) -- message content zone only:**
Assistant text, user messages, composer textarea, tool block content (plan explanations, streaming labels), thinking blocks, developer messages, collapse group summaries, compaction summaries, error/interrupt messages, todo lists, question summaries, user interaction card question text and options, sub-agent card type label and description, session title in MessageListHeader, new session overlay title/description.

**`text-sm` (14px) -- all UI chrome:**
All buttons (default base class), sidebar text (session cards, project groups, archive panels), toolbar icons, status bars, search inputs, completion/dropdown list items (file/slash/model/workspace), tool block header detail chips, file path labels, sub-agent metadata (elapsed/tool count), diff view toggles, task metadata table, copy buttons, tooltip content (unless overridden by text-xs).

**`text-xs` (13px) -- sparingly:**
SessionCard timestamps and diff stats, ProjectGroup counts and "Load more", ModelSelector provider category labels, UserInteractionCard small descriptions, archive panel uppercase labels.

**Rule**: Never use `text-base` for UI chrome. Never use `text-xs` where `text-sm` would work. When in doubt, use `text-sm`.

### Weight & Style Conventions

- **Regular (400)**: All body text, assistant responses, input
- **Medium (500)**: Frontmatter keys, section headers, active sidebar items, NewSessionButton label
- **Semibold (600)**: Buttons (base class), tool names in monospace, group collapse labels
- **Bold (700)**: Reserved for display `Geist Mono` usage only
- **Italic**: Thinking blocks are rendered entirely in italic to distinguish internal reasoning from output

### Text Color Hierarchy

A strict neutral scale for text, from strongest to weakest:

| Level            | Class              | Hex       | Usage                                                                                |
| ---------------- | ------------------ | --------- | ------------------------------------------------------------------------------------ |
| Primary          | `text-foreground`  | `#0a0a0a` | Body text, assistant responses                                                       |
| Strong secondary | `text-neutral-800` | `#262626` | Session titles, composer text, card headings                                         |
| Secondary        | `text-neutral-700` | `#404040` | Tool names, file names, input text, question text, tooltips                          |
| Tertiary         | `text-neutral-600` | `#525252` | Thinking content, developer messages, collapse summaries, tool detail text           |
| Quaternary       | `text-neutral-500` | `#737373` | Icon buttons at rest, copy buttons, metadata, completion list parents, spinner icons |
| Placeholder      | `text-neutral-400` | `#a3a3a3` | Placeholder text only (via `placeholder:text-neutral-400`)                           |
| Decorative       | `text-neutral-300` | `#d4d4d4` | Separators, dots, disabled states, pending todo icons                                |

**Rule**: When a text-neutral-500 element has a hover state, use `hover:text-neutral-700`. When a text-neutral-600 element has a hover state, use `hover:text-neutral-800`.

**Assistant prose override**: Inside `.assistant-text`, body copy is rendered in `#2e140c` (deep brown-red) rather than `--foreground`. This is the sole sanctioned text-color deviation from the neutral scale — motivated by pairing with the cream card fill and the matching leading-dot marker. The inline-code color inside `.assistant-text` is `#5f5fb7`. Do not extend brown text to any other surface.

### Eyebrow Text

Section labels, category tags, and header chips use a consistent formula: `font-mono text-xs font-medium uppercase tracking-wider text-neutral-500`. The monospace font gives short labels a technical, precise appearance. Examples: question header chips in UserInteractionCard, workspace picker label, operation headers.

### Text Wrapping

- **`text-pretty`**: Applied to paragraph text (question text, descriptions, assistant prose) to prevent orphan words at the end of lines.
- **`text-balance`**: Applied to short headings (overlay titles) to distribute text evenly across lines.
- Rule: multi-line body text gets `text-pretty`; short display headings get `text-balance`.

### Character

Anti-aliased rendering (`-webkit-font-smoothing: antialiased`). The assistant text area uses `line-height: 1.75` with `text-wrap: pretty` for compact but comfortable reading of long-form markdown, and renders in a warm `#2e140c` (deep brown) rather than pure `--foreground` to pair with the cream card fill. Inline code inside `.assistant-text` uses `#5f5fb7`. Code blocks and tool output use the monospace stack at `0.9em` relative size. The overall typographic feel is **compact but breathable** -- high information density with enough vertical rhythm to avoid fatigue.

## 4. Component Stylings

### Edge Definition Strategy

Two parallel edge strategies coexist, picked by whether the container sits in **chrome** or in the **message stream**.

**Chrome / chat-surface elements (ring-first)**: the composer, interaction card, tooltips, popovers, overlays, outline buttons. Shadow is carried by a named token; the edge is a ring so shadow and edge don't "muddy." `ring-1 ring-black/[0.06]` outer; `ring-1 ring-inset ring-black/[0.05]` inset.

**Message-stream cards (border-first, with tinted shadow)**: assistant-text rows and the tool-collapse group. These cards need both (a) an edge that reads against a warm `#f8f8f6` page, and (b) a shadow that matches the card fill rather than the default neutral gray. The chosen recipe is a hairline `border-stone-200/50` plus a **tinted two-stop arbitrary shadow** that matches the card's fill family. See **Message Cards** below and the **Shadows & Depth** table for the sanctioned shadow recipes.

**Tinted inset ring** (colored summary containers): `ring-1 ring-inset ring-{color}-500/[0.06]` for containers with semantic background colors. Applied to: compaction summary (`ring-sky-500/[0.06]`), rewind summary (`ring-amber-500/[0.06]`).

**Border is still used for**: message-stream cards (see above), sidebar divider (`border-r`), structural separators, form input borders, selection pill borders, and recessed diff containers (`border border-neutral-200`).

### Buttons

- **Shape**: `rounded-md` (6px effective radius) for standard buttons. `rounded-full` for icon-only circular actions (send, add image, close) and pill-shaped action buttons (submit, cancel, next in interaction cards).
- **Height scale**: `h-7` (28px) for inline/compact, `h-8` (32px) for standard, `h-9`/`h-10` for emphasized.
- **Shadow**: `shadow-sm` on default/destructive/outline variants. Ghost and link variants have no shadow.
- **Outline variant**: Uses `ring-1 ring-black/[0.06]` instead of `border` for cleaner shadow interaction.
- **Hover**: Color shift only (`bg-primary/90`, `bg-accent`). No scale, no translate.
- **Active/Press**: No `:active` scale transform currently applied. **Opportunity**: add `transform: scale(0.97)` on `:active` for tactile press feedback per Emil Kowalski's principle.
- **Disabled**: `opacity-50` + `pointer-events-none`. Clean, no grayed-out background trick.
- **Focus**: `focus-visible:ring-1 focus-visible:ring-ring` -- thin ring, only on keyboard focus.
- **Transition**: `transition-colors` only. No duration specified (Tailwind default 150ms).

### Cards & Containers

- **Composer card**: `rounded-lg` (8px), `bg-card`, `shadow-sm`, `ring-1 ring-black/[0.06]`. The ring is almost invisible -- just enough to define the card edge against the off-white background. This is the signature "barely-there edge" pattern.
- **User interaction card**: `rounded-2xl` (16px), `bg-card`, `shadow-sm`, `ring-1 ring-black/[0.06]`. Rounder corners signal "this needs your attention."
- **Sidebar**: Flat `bg-sidebar` with a single `border-r border-border` divider. No shadow. The sidebar should feel like part of the page, not floating above it.
- **Popovers/Dropdowns**: `bg-background`, `ring-1 ring-black/[0.06]`, with `shadow-float` or `shadow-float-lg`. Stronger shadow than cards to establish elevation hierarchy.
- **Tooltips**: `rounded-md`, `bg-card`, `shadow-sm`, `ring-1 ring-black/[0.06]`, `text-xs`. Minimal and precise.
- **Recessed containers** (tool blocks, plan/question blocks): `bg-surface/50`, `ring-1 ring-inset ring-black/[0.05]`. The inset ring is nearly invisible -- just enough edge definition to separate the container from surrounding content.

### Message Cards

The message stream uses two card variants with a shared recipe: hairline `border-stone-200/50`, small `rounded-lg` radius, generous horizontal padding, and a **tinted two-stop shadow** matched to the card's fill family. Borders are near-invisible on purpose; depth is carried by the shadow, not the stroke. Neither card uses a ring.

- **Assistant-text card** (`MessageRow.tsx`): `rounded-lg border border-stone-200/50 bg-[#f8f8f6] px-4 py-2 shadow-[0_1px_3px_0_rgba(107,76,44,0.07),_0_1px_2px_-1px_rgba(107,76,44,0.05)]`. The fill matches `--background` exactly, so the card is felt as a shadow + a dot, not as a floating block. A single leading `h-2 w-2 rounded-full bg-[#2e140c]` dot marks the row; on hover it swaps to the copy button. Active selection adds `ring-2 ring-amber-300/70 ring-offset-1` — the one place a ring is permitted on a message card, and only as a transient focus treatment.
- **Tool-collapse group card** (`CollapseGroupBlock.tsx`): `rounded-lg border border-stone-200/50 bg-[#e6eee2]/40 px-4 py-1 shadow-[0_1px_3px_0_rgba(70,100,60,0.07),_0_1px_2px_-1px_rgba(70,100,60,0.05)]`. A faint sage tint signals "grouped tool activity." Internal padding is `px-4` on the button row; expanded content sits inside the padded body with `pl-[22px]` to align with the rail grid (no vertical rail connector — the group is defined by the card, not a rail).
- **Radius policy for message cards**: both cards use `rounded-lg` (8px). Do not mix `rounded-xl`/`2xl` here — the stream relies on a consistent, small radius so successive cards align visually.

### Inputs & Forms

- **Composer textarea**: Borderless, transparent background (`border-0 bg-transparent`). The card itself provides the visual container.
- **Search/filter inputs**: `rounded-lg`, `border border-border`, `bg-surface/50`. On focus: `border-sky-300 bg-card ring-2 ring-sky-100`.
- **Selection pills (radio/checkbox)**: `rounded-lg`, `border px-3 py-2`. Selected state uses `border-sky-200 bg-sky-50/80 ring-1 ring-sky-200/60`. Unselected: `border-border bg-card hover:border-neutral-300 hover:bg-surface`. The selection indicator is a small `rounded-full` circle with inner dot.

### Collapse & Expand Groups

- **Marker**: An inline Lucide `ChevronRight` (`h-3.5 w-3.5 text-neutral-400`) that rotates 90° when open via `transition-transform duration-150 ease-out-strong`. Centered inside a `flex h-[1lh] items-center justify-center` span so the grid's `items-center` vertically aligns it with the header label. The former `[-]`/`[+]` rail marker and its vertical `w-px` connecting line were removed — the tinted card body now carries grouping, so no rail is drawn.
- **Grid**: The header button uses `COLLAPSE_RAIL_GRID_CLASS_NAME` for a two-column layout (16px chevron column + 6px gap); expanded content sits inside the card body at `pl-[22px]` to align content with the label.
- **Panel animation**: `transition-[height] duration-200 ease-out` with imperative DOM height measurement (`useLayoutEffect`). Inner content uses `backface-visibility: hidden` for GPU compositing during height transitions.
- **No conditional rendering**: Collapsed content stays in DOM with `overflow: hidden` and `height: 0`. This prevents layout recalculation mid-animation.
- **Label**: `t("collapse.toolsUsed")(totalCount)` — e.g. "使用了 N 个工具" / "N tools used". Empty groups fall back to `t("collapse.thoughts")`.

### Diff View

- Uses `@pierre/diffs` with the project's mono font stack injected via `--diffs-font-family`. Tall diffs get a gradient fade mask at the bottom with a "Show more/less" toggle.
- Container: `diff-view overflow-hidden rounded-lg border border-neutral-200 bg-surface shadow-sm`. Radius is aligned with the message-card policy (`rounded-lg`).
- Scales the library's internal type down to match the global mono normalization via `[--diffs-font-size:0.73rem] [--diffs-line-height:1.575rem]` (0.8125rem × 0.9, 1.75rem × 0.9). Font stacks — including those that render inside `@pierre/diffs`' shadow DOM — are injected with `Geist Mono` for code and `InterVariable` for the header title/filename slots.

### Status Indicators

- **Running**: `animate-spin` loader icon (Lucide `Loader`), `text-neutral-500`
- **Success settle**: Custom keyframe animation -- starts at emerald-800 `#065f46` with `scale(0.95)`, settles to `#a3a3a3` at `opacity: 0.82` over 1.6s `ease-out`. The card background simultaneously fades from emerald-100 to transparent.
- **Unread dot**: Small `rounded-full` emerald circle in the sidebar.
- **Error**: Red text, dashed border container for retry states.

## 5. Layout Principles

### Overall Structure

A two-column layout: **sidebar + main panel**. The sidebar is resizable via drag (width persisted to `localStorage`). The main panel fills remaining space (`flex: 1; min-width: 0`). Both columns are `overflow: hidden` -- all scrolling happens inside dedicated `ScrollArea` (Radix) containers.

### Spacing Strategy

- **Main content horizontal**: `px-4 sm:px-6` on the `max-w-4xl` centered column.
- **Sidebar horizontal**: `px-3` for header/footer bars, `px-2.5` for scroll content.
- **Message section rhythm**: `space-y-5` between message sections (user turns).
- **Project group rhythm**: `space-y-3` between sidebar project groups.
- **Message list bottom padding**: Dynamically calculated via CSS variable `--composer-h` (set by `ResizeObserver` on the composer). This ensures messages are never hidden behind the fixed-position composer.

### Width Constraints

- **Message content**: `max-w-4xl` (896px) centered with `mx-auto`. Markdown prose uses `line-height: 1.6` to maintain readability at width.
- **Sidebar**: Default 340px, stored in `localStorage`, resizable via drag. Minimum 256px, maximum 512px (clamped by available viewport).

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

| Element                                 | Frequency  | Animation                                                       |
| --------------------------------------- | ---------- | --------------------------------------------------------------- |
| Keyboard shortcuts (Cmd+B, Cmd+Shift+O) | 100+/day   | **None** -- instant state change                                |
| Tooltip appearance                      | Tens/day   | 125ms fade + zoom + directional slide (on `delayed-open` only)  |
| Collapse/expand groups                  | Tens/day   | 200ms `ease-out` height transition                              |
| Sidebar show/hide                       | Occasional | 200ms `ease-in-out` grid-template-columns transition            |
| Streaming text                          | Continuous | `stream-fade-in`: 120ms `ease-out` opacity (near-instantaneous) |
| Success settle                          | Rare       | 1.6s multi-stage keyframe (emerald flash -> neutral fade)       |
| Todo shimmer                            | Continuous | 3.6s linear gradient sweep (subtle, background)                 |

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

| Context                  | Size                       | Additional Classes                   |
| ------------------------ | -------------------------- | ------------------------------------ |
| Inline with text         | `h-3.5 w-3.5` or `h-4 w-4` | `shrink-0`                           |
| Toolbar / action buttons | `h-4 w-4`                  | `shrink-0`                           |
| Sidebar navigation       | `h-4 w-4`                  | `shrink-0`                           |
| Status indicators        | `h-3 w-3`                  | `shrink-0`, sometimes `animate-spin` |

Alignment rule: Icons in flex rows use `items-center` for single-line layouts, `items-start` + `mt-*` for multi-line. Never use `items-baseline` with icons. Never use `vertical-align` hacks.

## 8. Shadows & Depth

The elevation system is extremely flat. Named shadow tokens are defined in `tailwind.config.js`:

| Level        | Token             | Value                                  | Usage                                          |
| ------------ | ----------------- | -------------------------------------- | ---------------------------------------------- |
| **Ground**   | (none)            | No shadow                              | Sidebar, message list, backgrounds             |
| **Card**     | `shadow-sm`       | Tailwind default                       | Composer, tool result cards, session cards     |
| **Dropdown** | `shadow-float`    | `0 4px 16px rgba(0,0,0,0.08)`          | Small dropdowns, completion lists              |
| **Panel**    | `shadow-float-lg` | `0 8px 30px rgba(0,0,0,0.08)`          | Large dropdowns, archived menu, model selector |
| **Toast**    | `shadow-toast`    | `0 8px 24px -16px rgba(15,15,15,0.35)` | Undo toasts (+ `backdrop-blur`)                |
| **Overlay**  | `shadow-overlay`  | `0 24px 80px rgba(0,0,0,0.14)`         | New session overlay                            |

No heavy drop shadows anywhere. The depth hierarchy is communicated primarily through **background color contrast** (white card on off-white background) rather than shadow. Prefer the named tokens above.

### Sanctioned Arbitrary Shadows (message cards only)

Because the two message-card fills are tinted (cream and sage) against a warm page, a neutral-gray drop shadow reads as a dark smudge. These cards use an **arbitrary two-stop shadow whose RGB matches the fill family**. These are the only places arbitrary `shadow-[...]` values are allowed; anywhere else, use the named tokens.

| Card           | Class                                                                            | Note                                                   |
| -------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------ |
| Assistant-text | `shadow-[0_1px_3px_0_rgba(107,76,44,0.07),_0_1px_2px_-1px_rgba(107,76,44,0.05)]` | Warm brown, pairs with `#f8f8f6` fill + `#2e140c` text |
| Tool-group     | `shadow-[0_1px_3px_0_rgba(70,100,60,0.07),_0_1px_2px_-1px_rgba(70,100,60,0.05)]` | Sage, pairs with `#e6eee2/40` fill                     |

The shape (`0_1px_3px` / `0_1px_2px -1px`) mirrors Tailwind `shadow-sm` at reduced opacity. If a new tinted card is introduced, keep the same geometry and only adjust the tint RGB — do not invent new shadow shapes.

### Shadow-clipping pitfall

`content-visibility: auto` and `contain: paint` both clip descendant box-shadow at the element's padding box. Containers that wrap shadowed message cards must not set either property — this was previously hiding most of the message-card shadow and has been removed from `MessageList.tsx` (`OFFSCREEN_BLOCK_STYLE` is intentionally `undefined`, and no section-level `contentVisibility` wrapper exists). If reintroducing virtualization, do it at a layer that does not contain the shadow (e.g. only on purely offscreen slices), not on the visible card's direct parent.

## 9. Dark Mode Strategy

Dark mode uses a pure achromatic palette -- no blue, purple, or warm tint in backgrounds. The `--background` inverts to near-black (`0 0% 3.9%`), surfaces go to `0 0% 7%`. Semantic accent colors (sky, amber, emerald, red) retain their hue but may shift lightness for contrast.

The `darkMode: ["class"]` approach means dark mode is toggled by adding `.dark` to the root element, not by `prefers-color-scheme`. This allows explicit user control.

## 10. Design Opportunities & Gaps

### Missing Tactile Feedback

- Buttons lack `:active` scale. Add `transform: scale(0.97)` with `transition: transform 160ms ease-out` to all pressable elements. This single change makes the entire interface feel more responsive.
- Send button (the most-pressed element) should have the most satisfying press response.

### Animation Refinements

- Tooltip `transform-origin` should use `var(--radix-tooltip-content-transform-origin)` to scale from the trigger point, not center. Currently using default.
- Popover/dropdown `transform-origin` should similarly use Radix's `--radix-popover-content-transform-origin`.

### Hover State Gaps

- Hover animations should be gated behind `@media (hover: hover) and (pointer: fine)` to prevent false positives on touch devices.

### Custom Easing Curves

- The `ease-out-strong` curve (`cubic-bezier(0.23, 1, 0.32, 1)`) is defined in `tailwind.config.js` but not yet widely used. Consider adopting it for collapse/expand and popover transitions where the default `ease-out` feels too gentle.

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

### Concentric Radius

When a rounded container holds another rounded element near its edges, the inner element's `border-radius` should equal `outer_radius - gap` (where gap is the distance from outer edge to inner edge). This creates concentric arcs that look harmonious. When inner and outer use the same radius but the gap is small, the spacing between curves looks pinched.

**Formula**: `inner_radius = max(0, outer_radius - gap_to_inner_edge)`

Current concentric relationships:

| Container                           | Outer                | Gap        | Inner              | Formula check           |
| ----------------------------------- | -------------------- | ---------- | ------------------ | ----------------------- |
| CommandListPanel -> CommandListItem | `rounded-xl` (12px)  | ~8px       | `rounded-md` (6px) | 12-8=4, 6 is close      |
| NewSessionOverlay -> inner cards    | `rounded-[20px]`     | 12px (p-3) | `rounded-lg` (8px) | 20-12=8, exact match    |
| UserMessage bubble -> images        | `rounded-2xl` (16px) | 10px       | `rounded-md` (6px) | 16-10=6, exact match    |
| UserInteractionCard -> pills        | `rounded-2xl` (16px) | 20px       | `rounded-lg` (8px) | gap > radius, any works |

**Rule**: When adding new card-in-card or panel-in-panel layouts, check the formula. If the gap is larger than the outer radius, any inner radius works. If the gap is small (< outer radius), apply the formula.
