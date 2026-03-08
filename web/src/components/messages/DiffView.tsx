import { useMemo, useRef, useEffect, useState } from "react";
import { PatchDiff } from "@pierre/diffs/react";
import { DEFAULT_THEMES, preloadHighlighter } from "@pierre/diffs";

import type { ToolBlockItem } from "../../types/message";
import { isDiffUIExtra, type DiffUIExtra } from "./message-ui-extra";

const SHADOW_ICON_CSS = `
[data-diffs-header],
[data-header-content],
[data-header-content] [data-prev-name],
[data-header-content] [data-title],
[data-diffs-header] [data-metadata] {
  font-family: var(--diffs-font-family, "TX-02", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace) !important;
}

[data-diffs-header] {
  min-height: 32px !important;
  padding-inline: 12px !important;
}

[data-change-icon] { display: none !important; }
[data-header-content]::before {
  content: "";
  display: inline-block;
  width: 12px;
  height: 12px;
  flex-shrink: 0;
  background: color-mix(in lab, var(--diffs-fg) 45%, var(--diffs-bg));
  -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z'/%3E%3Cpath d='m15 5 4 4'/%3E%3C/svg%3E");
  mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z'/%3E%3Cpath d='m15 5 4 4'/%3E%3C/svg%3E");
  -webkit-mask-size: contain;
  mask-size: contain;
}
`;

// Eagerly start loading the highlighter
preloadHighlighter({
  themes: [DEFAULT_THEMES.light, DEFAULT_THEMES.dark],
  langs: ["text", "ansi"],
});

/**
 * Reconstruct a unified diff string from structured DiffUIExtra data.
 * Used as fallback when raw_unified_diff is not available.
 */
function rebuildSingleFileUnifiedDiff(file: DiffUIExtra["files"][number]): string {
  const parts = [`--- a/${file.file_path}`, `+++ b/${file.file_path}`, "@@ -1 +1 @@"];
  for (const line of file.lines) {
    const text = line.spans.map((s) => s.text).join("");
    switch (line.kind) {
      case "ctx":
        parts.push(` ${text}`);
        break;
      case "add":
        parts.push(`+${text}`);
        break;
      case "remove":
        parts.push(`-${text}`);
        break;
      case "gap":
        break;
    }
  }
  return parts.join("\n");
}

interface DiffViewProps {
  item: ToolBlockItem;
  uiExtra?: DiffUIExtra;
}

const COLLAPSED_DIFF_MAX_HEIGHT = 420;

export function DiffView({ item, uiExtra }: DiffViewProps): JSX.Element | null {
  const extra = uiExtra ?? (item.uiExtra && isDiffUIExtra(item.uiExtra) ? item.uiExtra : null);
  const containerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [isOverflowing, setIsOverflowing] = useState(false);

  const patches = useMemo(() => {
    if (!extra) return null;
    if (extra.files.length > 0) {
      if (extra.files.length === 1 && extra.raw_unified_diff) {
        return [extra.raw_unified_diff];
      }
      return extra.files.map(rebuildSingleFileUnifiedDiff);
    }
    if (extra.raw_unified_diff) {
      return [extra.raw_unified_diff];
    }
    return null;
  }, [extra]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    // @pierre/diffs renders inside Shadow DOM; inject CSS to replace the file-header icon
    const shadowRoots = el.querySelectorAll("*");
    for (const node of shadowRoots) {
      const sr = node.shadowRoot;
      if (!sr || sr.querySelector("style[data-icon-override]")) continue;
      const style = document.createElement("style");
      style.setAttribute("data-icon-override", "");
      style.textContent = SHADOW_ICON_CSS;
      sr.appendChild(style);
    }
  });

  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;

    const updateOverflow = (): void => {
      setIsOverflowing(el.scrollHeight > COLLAPSED_DIFF_MAX_HEIGHT);
    };

    updateOverflow();
    const observer = new ResizeObserver(updateOverflow);
    observer.observe(el);
    return () => observer.disconnect();
  }, [patches]);

  if (!extra || patches === null) return null;

  return (
    <div className="diff-view" ref={containerRef}>
      <div className="flex flex-col gap-1">
        <div
          className={`relative ${!expanded && isOverflowing ? "max-h-[420px] overflow-hidden" : ""}`}
        >
          <div ref={contentRef} className="flex flex-col">
            {patches.map((patch, index) => (
              <PatchDiff
                key={`${item.id}-${index}`}
                patch={patch}
                options={{
                  theme: "github-light",
                  themeType: "light",
                  overflow: "wrap",
                  diffStyle: "unified",
                  diffIndicators: "bars",
                  lineDiffType: "word",
                  hunkSeparators: "simple",
                }}
              />
            ))}
          </div>
          {!expanded && isOverflowing ? (
            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-white via-white/95 to-transparent" />
          ) : null}
        </div>
        {isOverflowing ? (
          <button
            type="button"
            className="self-start pb-1 pl-2 text-xs text-neutral-400 transition-colors hover:text-neutral-600"
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? "Show less" : "Show more"}
          </button>
        ) : null}
      </div>
    </div>
  );
}
