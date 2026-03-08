import { Streamdown } from "streamdown";
import { code } from "@streamdown/code";
import "streamdown/styles.css";

import type { AssistantTextItem } from "../../types/message";
import { mermaid } from "../../lib/mermaid-plugin";
import { FrontmatterTable } from "./FrontmatterTable";
import { useParsedFrontmatter } from "./frontmatter";
import { useStreamThrottle } from "./useStreamThrottle";

interface AssistantTextProps {
  item: AssistantTextItem;
  compact?: boolean;
}

const plugins = { code, mermaid };

export function AssistantText({ item, compact = false }: AssistantTextProps): JSX.Element {
  const content = useStreamThrottle(item.content, item.isStreaming);
  const { entries, body } = useParsedFrontmatter(content);

  return (
    <div className={`assistant-text relative ${compact ? "assistant-text-compact" : ""}`}>
      {entries ? <FrontmatterTable entries={entries} /> : null}
      <Streamdown mode="streaming" isAnimating={item.isStreaming} plugins={plugins}>
        {body}
      </Streamdown>
    </div>
  );
}
