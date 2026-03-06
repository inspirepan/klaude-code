import { Streamdown } from "streamdown";
import { code } from "@streamdown/code";

import { mermaid } from "../../lib/mermaid-plugin";
import { useParsedFrontmatter, FrontmatterTable } from "./FrontmatterTable";

interface MarkdownDocUIExtra {
  type: "markdown_doc";
  file_path: string;
  content: string;
}

export function isMarkdownDocUIExtra(extra: unknown): extra is MarkdownDocUIExtra {
  return (
    typeof extra === "object" &&
    extra !== null &&
    (extra as { type?: unknown }).type === "markdown_doc"
  );
}

const plugins = { code, mermaid };

interface MarkdownDocViewProps {
  uiExtra: MarkdownDocUIExtra;
  compact?: boolean;
}

export function MarkdownDocView({ uiExtra, compact = false }: MarkdownDocViewProps): JSX.Element {
  const { entries, body } = useParsedFrontmatter(uiExtra.content);

  return (
    <div className="mt-1 overflow-hidden rounded-lg border border-neutral-200/80 font-sans">
      <div
        className={`border-b border-neutral-200/80 bg-neutral-50 px-3 py-1.5 ${compact ? "text-[11px]" : "text-xs"} truncate font-mono text-neutral-400`}
      >
        {uiExtra.file_path}
      </div>
      <div className={`px-4 py-3 ${compact ? "text-[13px]" : "text-sm"} markdown-doc-view`}>
        {entries ? <FrontmatterTable entries={entries} /> : null}
        <Streamdown isAnimating={false} plugins={plugins}>
          {body}
        </Streamdown>
      </div>
    </div>
  );
}
