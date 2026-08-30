# timeline — the D1 scroller scale model

klaude's deliberate deviation **D1** from
[`docs/web-viewer-ux-spec.md`](../../../docs/web-viewer-ux-spec.md) §1. Upstream
fits the whole domain into the container and zooms/pans a *domain window*
(`--trajectory-domain-left/width`, `viewport` state). The fork keeps a
**px-per-domain-unit scale**, lays the content out at its natural width and moves
the viewport with `scrollLeft`. Everything else in §1 — lanes, span colours, idle
compression, drag-select, hover, tooltips, turn boundaries, the earlier-history
control — is unchanged.

The math lives in `timeline.ts` as pure functions (tested in
`timeline-scale.test.ts`); `TrajectoryTimeline.tsx` only wires them to the DOM
(`timeline-scroller.test.tsx` pins the rendered contract).

## Domain unit

| mode | unit | domain |
|---|---|---|
| `sequence` (default) | one record | `[0, N]`, each span `[i, i+1]` |
| `duration` | one millisecond | idle-compressed wall clock |
| `time` / `actual` (hidden controls) | one millisecond | as upstream; they ride the same scale, untuned |

`fullDuration = max(1, model.end - model.start)`.

## Constants

| Constant (`timeline.ts`) | Value | Meaning |
|---|---|---|
| `TIMELINE_PX_PER_RECORD` | `6` | default `sequence` scale, gap included (bar ≈ 5px wide × 8px tall) |
| `TIMELINE_PX_PER_MS` | `0.004` | default timed scale = 240 px/minute; a 10-minute session opens ≈ 2 × 1200px screens |
| `TIMELINE_MINIMUM_ZOOM_RECORDS` | `4` | zoom-in stop, `sequence` (upstream's `MINIMUM_ZOOM_OPERATIONS`) |
| `TIMELINE_MINIMUM_ZOOM_MS` | `20` | zoom-in stop, timed modes (upstream's 20 ms) |
| `TIMELINE_ZOOM_EXPONENT` | `0.0015` | wheel factor, unchanged from upstream |
| `TIMELINE_TAIL_FOLLOW_PX` | `2` | still "at the tail" within this distance (same value the ledger uses) |
| `TIMELINE_REVEAL_MS` | `180` | reveal animation, matching upstream's viewport transition |

Component-local (`TrajectoryTimeline.tsx`), unchanged from upstream unless noted:
`MINIMUM_DRAG_PX 3` · `EDGE_PAN_ZONE_FRACTION 0.08` · `EDGE_PAN_STEP_FRACTION
0.025` · `MAXIMUM_EDGE_PAN_PX 32` · `TIMELINE_TOOLTIP_DELAY_MS 500` · **new:**
`SPAN_WINDOW_MARGIN_PX 480` / `SPAN_WINDOW_STEP_PX 160` (span culling, below).

## Formulas

With `W` the measured track width (`clientWidth`) and `p` the px per domain unit:

```
minimumPxPerUnit = W / fullDuration                                  # "fits the container"
maximumPxPerUnit = W / min(zoomFloorUnits, fullDuration)             # 4 records | 20 ms fill the container
p                = clamp(held ?? default, minimum, maximum)
contentWidth     = max(W, fullDuration * p)                          # equal to fullDuration * p after the clamp
maxScrollLeft    = max(0, contentWidth - W)
visibleDuration  = min(fullDuration, W / p)                          # replaces upstream's domainDuration
x(unit)          = (unit - model.start) * p                          # content px
unit(x)          = model.start + x / p
```

`W = 0` (before the first measurement) disables both bounds: the scale is the raw
default and the content layer's `min-width: 100%` keeps it covering the track.

**Zoom** (wheel, `{passive:false}` + `preventDefault`, cursor-anchored):

```
p'          = clamp(p * exp(-deltaY * 0.0015), minimum, maximum)     # negated: upstream grew the *duration*
anchorUnits = (scrollLeft + cursorOffset) / p                        # cursorOffset = clientX - trackRect.left
scrollLeft' = clamp(anchorUnits * p' - cursorOffset, 0, maxScrollLeft')
```

`scrollLeft'` is applied in the layout effect *after* the content layer has its
new width, otherwise the browser clamps it against the old one. A wheel event
with `|deltaX| > |deltaY|` (trackpad) scrolls by `deltaX` instead of zooming.

**Reveal** a span that a new `selectedIndex` points at — upstream's rule, in px:

```
already intersecting (spanRight > scrollLeft && spanLeft < scrollLeft + W) → no move
entirely left  → scrollLeft' = spanLeft
entirely right → scrollLeft' = spanRight - W
```

clamped to `[0, maxScrollLeft]` and animated over 180 ms with an ease-out cubic
(`requestAnimationFrame`), or applied instantly under
`prefers-reduced-motion: reduce`. Only a *changed* selection reveals; re-running
on model growth would fight tail follow.

**Tail follow**: `maxScrollLeft - scrollLeft <= 2` marks the viewport as pinned
(recomputed on every scroll, including native scrollbar drags). A pinned track is
re-pinned to `maxScrollLeft` whenever the model or the content width changes. A
fresh mount starts pinned, so a session opens on its newest records — the same
place `TrajectoryTable` opens.

**Earlier history**: the `…` control shows only while `scrollLeft <= 0.5`. Before
loading, the click records `{contentWidth, scrollLeft}`; when the model comes
back, `scrollLeft' = clamp(scrollLeft + (contentWidth' - contentWidth), 0,
maxScrollLeft')`. Prepended rows only ever land left of what is loaded, and idle
compression shifts every existing span by the same constant, so the width delta
*is* the shift. (Record indexes are renumbered by a prepend, so anchoring on one
would not work.)

## DOM / CSS contract

`.track` is the scroll container: `overflow-x: auto; overflow-y: hidden;
overscroll-behavior-x: contain`, marked `data-timeline-scroller`, carrying
`--trajectory-content-width` for its descendants. Its 6px scrollbar rides the
7px gutter below the Tools lane and rebinds `--dsh-scrollbar-thumb{,-hover}` to
the `--dsw-alias-scrollbar-*-l2` pair (`theme/scrollbar.css` owns the rest).

`.lanes` and `.turnBoundaries` are the content layers: `left: 0; width:
var(--trajectory-content-width); min-width: 100%`. Spans keep upstream's
percentage geometry (`--trajectory-span-left/width/gap` as a fraction of the full
domain), so a span is never thinner than the 2px `min-width` the CSS already
enforced — the only case where a bar would want to be thinner is a domain zoomed
out to the "fits the container" minimum, which is exactly upstream's baseline.

Overlays (`.selection`, `.selectionEdges`, `.hoverLine`) now position in **content
px** instead of viewport percentages, because absolutely positioned children of a
scroll container scroll with its content.

Spans and turn boundaries outside `[scrollLeft - 480, scrollLeft + W + 480]` are
not rendered; the committed scroll offset only advances in 160px steps, so
scrolling inside the margin costs no re-render. Upstream culled to the domain
window for the same reason.

## Known gaps

- `touch-action: none` is kept from upstream, so a touch drag selects a range and
  never scrolls the strip; touch users have no gesture to pan it.
- The `time` / `actual` modes ride the timed scale untouched. Their controls are
  `hidden` upstream and in the fork.
- `data-equal-duration` (8px fixed spans in `time` mode) is unchanged and ignores
  the scale.
