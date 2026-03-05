import { useState, useCallback, useRef, useEffect } from "react";
import { Copy, Check } from "lucide-react";
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
  const [copied, setCopied] = useState(false);
  const timerRef = useRef(0);
  const { entries, body } = useParsedFrontmatter(item.content);

  useEffect(() => () => window.clearTimeout(timerRef.current), []);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(item.content);
      setCopied(true);
      timerRef.current = window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  }, [item.content]);

  return (
    <div className="assistant-text group/assistant relative">
      {entries ? <FrontmatterTable entries={entries} /> : null}
      <Streamdown isAnimating={item.isStreaming} plugins={plugins}>
        {body}
      </Streamdown>
      {!item.isStreaming && item.content.split("\n").length > 5 ? (
        <button
          type="button"
          onClick={handleCopy}
          className="mt-3 text-neutral-300 hover:text-neutral-500 opacity-0 group-hover/assistant:opacity-100 transition-opacity duration-150 cursor-pointer"
          title={copied ? "Copied" : "Copy"}
        >
          {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
        </button>
      ) : null}
    </div>
  );
}
