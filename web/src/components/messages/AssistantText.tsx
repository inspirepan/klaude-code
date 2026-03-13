import { Streamdown } from "streamdown";
import { code } from "@streamdown/code";
import "streamdown/styles.css";

import type { AssistantTextItem } from "../../types/message";
import { mermaid } from "../../lib/mermaid-plugin";
import { FrontmatterTable } from "./FrontmatterTable";
import { useParsedFrontmatter } from "./frontmatter";

interface AssistantTextProps {
  item: AssistantTextItem;
  compact?: boolean;
}

const plugins = { code, mermaid };
const streamAnimation = { animation: "fadeIn" as const, duration: 120, sep: "char" as const };

export function AssistantText({ item, compact = false }: AssistantTextProps): JSX.Element {
  const { entries, body } = useParsedFrontmatter(item.content);

  return (
    <div className={`assistant-text relative ${compact ? "assistant-text-compact" : ""}`}>
      {entries ? <FrontmatterTable entries={entries} /> : null}
      <Streamdown
        mode="streaming"
        isAnimating={item.isStreaming}
        animated={streamAnimation}
        plugins={plugins}
      >
        {body}
      </Streamdown>
    </div>
  );
}
