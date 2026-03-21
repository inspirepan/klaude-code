import { Streamdown } from "streamdown";
import { code } from "@streamdown/code";

import { mermaid } from "../../lib/mermaid-plugin";
import { FrontmatterTable } from "./FrontmatterTable";
import { useParsedFrontmatter } from "./frontmatter";
import type { MarkdownDocUIExtra } from "./message-ui-extra";

const plugins = { code, mermaid };

interface MarkdownDocViewProps {
  uiExtra: MarkdownDocUIExtra;
}

export function MarkdownDocView({ uiExtra }: MarkdownDocViewProps): JSX.Element {
  const { entries, body } = useParsedFrontmatter(uiExtra.content);

  return (
    <div className="mt-1 overflow-hidden rounded-lg border border-neutral-200/80 font-sans">
      <div className="truncate border-b border-neutral-200/80 bg-surface px-3 py-1.5 font-mono text-sm text-neutral-500">
        {uiExtra.file_path}
      </div>
      <div className="markdown-doc-view px-4 py-3 text-base">
        {entries ? <FrontmatterTable entries={entries} /> : null}
        <Streamdown isAnimating={false} plugins={plugins}>
          {body}
        </Streamdown>
      </div>
    </div>
  );
}
