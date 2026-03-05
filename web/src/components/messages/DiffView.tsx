import { useMemo } from "react";
import { PatchDiff } from "@pierre/diffs/react";
import { preloadHighlighter } from "@pierre/diffs";

import type { ToolBlockItem } from "../../types/message";

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

function isDiffUIExtra(extra: Record<string, unknown>): extra is DiffUIExtra {
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

// Single-file tools already show path in the ToolBlock header
const SINGLE_FILE_TOOLS = new Set(["Edit", "Write"]);

interface DiffViewProps {
  item: ToolBlockItem;
}

export function DiffView({ item }: DiffViewProps): JSX.Element | null {
  if (!item.uiExtra || !isDiffUIExtra(item.uiExtra)) return null;

  const hideFileHeader = SINGLE_FILE_TOOLS.has(item.toolName);

  const patch = useMemo(() => {
    const extra = item.uiExtra as DiffUIExtra;
    if (extra.raw_unified_diff) return extra.raw_unified_diff;
    return rebuildUnifiedDiff(extra);
  }, [item.uiExtra]);

  return (
    <div className="diff-view">
      <PatchDiff
        patch={patch}
        options={{
          theme: "github-light",
          themeType: "light",
          overflow: "wrap",
          disableFileHeader: hideFileHeader,
          diffStyle: "unified",
          diffIndicators: "bars",
          lineDiffType: "word",
          hunkSeparators: "simple",
        }}
      />
    </div>
  );
}
