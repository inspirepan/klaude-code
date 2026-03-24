import { useMemo, useRef, useEffect, useState } from "react";
import { PatchDiff } from "@pierre/diffs/react";
import { DEFAULT_THEMES, preloadHighlighter } from "@pierre/diffs";

import { useT } from "@/i18n";
import type { ToolBlockItem } from "../../types/message";
import { isDiffUIExtra, type DiffUIExtra } from "./message-ui-extra";

const SHADOW_ICON_CSS = `
[data-diffs-header],
[data-header-content],
[data-diffs-header] [data-metadata] {
  font-family: var(--diffs-font-family, "Geist Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace) !important;
}

[data-header-content] [data-prev-name],
[data-header-content] [data-title] {
  font-family: var(--diffs-header-font-family, "Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Noto Sans CJK SC", "Helvetica Neue", Arial, sans-serif) !important;
}

[data-diffs-header] {
  min-height: 32px !important;
  padding-inline: 12px !important;
  background-color: hsl(var(--surface)) !important;
}

[data-diffs] {
  --diffs-bg: hsl(var(--surface)) !important;
}

[data-code] {
  background-color: hsl(var(--surface)) !important;
  padding-bottom: 0 !important;
}

[data-change-icon] { display: none !important; }
[data-header-content]::before {
  content: "";
  display: inline-block;
  width: 12px;
  height: 12px;
  flex-shrink: 0;
  background: color-mix(in lab, var(--diffs-fg) 45%, var(--diffs-bg));
  -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 3v14'/%3E%3Cpath d='M5 10h14'/%3E%3Cpath d='M5 21h14'/%3E%3C/svg%3E");
  mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 3v14'/%3E%3Cpath d='M5 10h14'/%3E%3Cpath d='M5 21h14'/%3E%3C/svg%3E");
  -webkit-mask-size: contain;
  mask-size: contain;
}
`;

// Eagerly start loading the highlighter
void preloadHighlighter({
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
const DIFF_BACKGROUND = "hsl(var(--surface))";
const DIFF_HEADER_SANS =
  '"Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Noto Sans CJK SC", "Helvetica Neue", Arial, sans-serif';

export function DiffView({ item, uiExtra }: DiffViewProps): React.JSX.Element | null {
  const t = useT();
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

    const diffs = el.querySelectorAll<HTMLElement>("[data-diffs]");
    for (const diff of diffs) {
      diff.style.setProperty("--diffs-bg", DIFF_BACKGROUND);
      diff.style.backgroundColor = DIFF_BACKGROUND;
    }

    const codeBlocks = el.querySelectorAll<HTMLElement>("[data-code]");
    for (const codeBlock of codeBlocks) {
      codeBlock.style.backgroundColor = DIFF_BACKGROUND;
      codeBlock.style.paddingBottom = "0px";
    }

    const headers = el.querySelectorAll<HTMLElement>("[data-diffs-header]");
    for (const header of headers) {
      header.style.backgroundColor = DIFF_BACKGROUND;
      header.style.setProperty("--diffs-bg", DIFF_BACKGROUND);
    }

    const headerTitles = el.querySelectorAll<HTMLElement>(
      "[data-diffs-header] [data-title], [data-diffs-header] [data-prev-name]",
    );
    for (const headerTitle of headerTitles) {
      headerTitle.style.fontFamily = DIFF_HEADER_SANS;
    }

    // @pierre/diffs uses Shadow DOM for part of its rendering; inject CSS there for icon/font tweaks
    const shadowRoots = el.querySelectorAll("*");
    for (const node of shadowRoots) {
      const sr = node.shadowRoot;
      if (!sr || sr.querySelector("style[data-icon-override]")) continue;
      const style = document.createElement("style");
      style.setAttribute("data-icon-override", "");
      style.textContent = SHADOW_ICON_CSS;
      sr.appendChild(style);
    }
  }, [patches]);

  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;

    const updateOverflow = (): void => {
      setIsOverflowing(el.scrollHeight > COLLAPSED_DIFF_MAX_HEIGHT);
    };

    updateOverflow();
    const observer = new ResizeObserver(updateOverflow);
    observer.observe(el);
    return () => {
      observer.disconnect();
    };
  }, [patches]);

  if (!extra || patches === null) return null;

  return (
    <div
      className="diff-view rounded-lg bg-surface [--diffs-font-size:0.875rem]"
      ref={containerRef}
    >
      <div className="flex flex-col">
        <div
          className={`relative ${!expanded && isOverflowing ? "max-h-[420px] overflow-hidden" : ""}`}
        >
          <div ref={contentRef} className="flex flex-col bg-surface">
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
            <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-16 bg-gradient-to-t from-surface/80 via-surface/35 to-transparent" />
          ) : null}
        </div>
        {isOverflowing ? (
          <div className="bg-surface pt-1">
            <button
              type="button"
              className="self-start pb-1 pl-2 text-sm text-neutral-500 transition-colors hover:text-neutral-700"
              onClick={() => {
                setExpanded((value) => !value);
              }}
            >
              {expanded ? t("diff.showLess") : t("diff.showMore")}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
