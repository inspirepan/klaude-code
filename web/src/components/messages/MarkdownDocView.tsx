import { Streamdown } from "streamdown";
import { code } from "@streamdown/code";

import { mermaid } from "../../lib/mermaid-plugin";

interface MarkdownDocUIExtra {
  type: "markdown_doc";
  file_path: string;
  content: string;
}

export function isMarkdownDocUIExtra(extra: unknown): extra is MarkdownDocUIExtra {
  return typeof extra === "object" && extra !== null && (extra as { type?: unknown }).type === "markdown_doc";
}

const plugins = { code, mermaid };

interface MarkdownDocViewProps {
  uiExtra: MarkdownDocUIExtra;
}

export function MarkdownDocView({ uiExtra }: MarkdownDocViewProps): JSX.Element {
  return (
    <div className="mt-1 rounded-lg border border-zinc-200/80 overflow-hidden">
      <div className="px-3 py-1.5 bg-zinc-50 border-b border-zinc-200/80 text-xs text-zinc-400 font-mono truncate">
        {uiExtra.file_path}
      </div>
      <div className="px-4 py-3 text-sm markdown-doc-view">
        <Streamdown isAnimating={false} plugins={plugins}>
          {uiExtra.content}
        </Streamdown>
      </div>
    </div>
  );
}
