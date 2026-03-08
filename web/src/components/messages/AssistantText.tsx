import { useEffect, useRef, useState } from "react";
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
const STREAM_REFRESH_INTERVAL_MS = 280;

export function AssistantText({ item, compact = false }: AssistantTextProps): JSX.Element {
  const [displayContent, setDisplayContent] = useState(item.content);
  const pendingContentRef = useRef(item.content);

  useEffect(() => {
    pendingContentRef.current = item.content;
  }, [item.content]);

  useEffect(() => {
    if (!item.isStreaming) {
      return;
    }
    const timer = window.setInterval(() => {
      setDisplayContent((current) =>
        current === pendingContentRef.current ? current : pendingContentRef.current,
      );
    }, STREAM_REFRESH_INTERVAL_MS);

    return () => {
      window.clearInterval(timer);
    };
  }, [item.isStreaming]);

  const content = item.isStreaming ? displayContent : item.content;
  const { entries, body } = useParsedFrontmatter(content);

  return (
    <div className={`assistant-text relative ${compact ? "assistant-text-compact" : ""}`}>
      {entries ? <FrontmatterTable entries={entries} /> : null}
      <Streamdown
        mode="streaming"
        isAnimating={item.isStreaming}
        animated={{ animation: "fadeIn", duration: 220, sep: "word" }}
        plugins={plugins}
      >
        {body}
      </Streamdown>
    </div>
  );
}
