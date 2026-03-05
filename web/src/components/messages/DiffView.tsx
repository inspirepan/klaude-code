import { useMemo, useRef, useEffect } from "react";
import { PatchDiff } from "@pierre/diffs/react";
import { preloadHighlighter } from "@pierre/diffs";

import type { ToolBlockItem } from "../../types/message";

const SHADOW_ICON_CSS = `
[data-diffs-header],
[data-header-content],
[data-header-content] [data-prev-name],
[data-header-content] [data-title],
[data-diffs-header] [data-metadata] {
  font-family: var(--diffs-font-family, "TX-02", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace) !important;
}

[data-diffs-header] {
  min-height: 24px !important;
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
preloadHighlighter();

interface DiffUIExtra {
  type: "diff";
  files: Array<{
    file_path: string;
    lines: Array<{
      kind: "ctx" | "add" | "remove" | "gap";
      new_line_no: number | null;
      spans: Array<{ op: "equal" | "insert" | "delete"; text: string }>;
    }>;
    stats_add: number;
    stats_remove: number;
  }>;
  raw_unified_diff: string | null;
}

export function isDiffUIExtra(extra: Record<string, unknown>): extra is DiffUIExtra {
  return extra.type === "diff";
}

/**
 * Reconstruct a unified diff string from structured DiffUIExtra data.
 * Used as fallback when raw_unified_diff is not available.
 */
function rebuildUnifiedDiff(data: DiffUIExtra): string {
  const parts: string[] = [];
  for (const file of data.files) {
    parts.push(`--- a/${file.file_path}`);
    parts.push(`+++ b/${file.file_path}`);
    // Emit a single hunk header covering all lines
    parts.push(`@@ -1 +1 @@`);
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
          // Skip gap markers
          break;
      }
    }
  }
  return parts.join("\n");
}

interface DiffViewProps {
  item: ToolBlockItem;
  uiExtra?: DiffUIExtra;
}

export function DiffView({ item, uiExtra }: DiffViewProps): JSX.Element | null {
  const extra = uiExtra ?? (item.uiExtra && isDiffUIExtra(item.uiExtra) ? item.uiExtra : null);
  const containerRef = useRef<HTMLDivElement>(null);

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

  if (!extra) return null;

  const patch = useMemo(() => {
    if (extra.raw_unified_diff) return extra.raw_unified_diff;
    return rebuildUnifiedDiff(extra);
  }, [extra]);

  return (
    <div className="diff-view" ref={containerRef}>
      <PatchDiff
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
    </div>
  );
}
