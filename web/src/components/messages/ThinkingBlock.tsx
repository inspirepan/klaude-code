import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { Streamdown } from "streamdown";
import { code } from "@streamdown/code";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../ui/collapsible";
import type { ThinkingBlockItem } from "../../types/message";

interface ThinkingBlockProps {
  item: ThinkingBlockItem;
}

const plugins = { code };

function Strong(props: React.ComponentPropsWithoutRef<"strong">): JSX.Element {
  return <strong style={{ fontWeight: 500 }} {...props} />;
}

const thinkingComponents = { strong: Strong };

export function ThinkingBlock({ item }: ThinkingBlockProps): JSX.Element {
  const isSingleLine = !item.isStreaming && !item.content.includes("\n");
  const [open, setOpen] = useState(true);

  // Single-line thinking: render inline, no collapsible
  if (isSingleLine) {
    return (
      <div className="thinking-block text-sm text-zinc-400 leading-relaxed">
        <Streamdown isAnimating={false} plugins={plugins} components={thinkingComponents}>
          {item.content}
        </Streamdown>
      </div>
    );
  }

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex items-center gap-1.5 text-zinc-400 hover:text-zinc-500 transition-colors group cursor-pointer">
        <ChevronRight
          className={`w-3.5 h-3.5 transition-transform duration-150 ${open ? "rotate-90" : ""}`}
        />
        <span className="text-sm select-none">Thinking</span>
        {item.isStreaming ? (
          <span className="relative flex h-2 w-2 ml-1">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-zinc-300 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-zinc-400" />
          </span>
        ) : null}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="thinking-block mt-1.5 pl-5 text-sm text-zinc-400 leading-relaxed">
          <Streamdown isAnimating={item.isStreaming} plugins={plugins} components={thinkingComponents}>
            {item.content}
          </Streamdown>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
