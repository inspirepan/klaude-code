import { Streamdown } from "streamdown";
import { code } from "@streamdown/code";

import type { AssistantTextItem } from "../../types/message";
import { mermaid } from "../../lib/mermaid-plugin";
import { useParsedFrontmatter, FrontmatterTable } from "./FrontmatterTable";

interface AssistantTextProps {
  item: AssistantTextItem;
}

const plugins = { code, mermaid };

export function AssistantText({ item }: AssistantTextProps): JSX.Element {
  const { entries, body } = useParsedFrontmatter(item.content);

  return (
    <div className="assistant-text relative">
      {entries ? <FrontmatterTable entries={entries} /> : null}
      <Streamdown isAnimating={item.isStreaming} plugins={plugins}>
        {body}
      </Streamdown>
    </div>
  );
}
