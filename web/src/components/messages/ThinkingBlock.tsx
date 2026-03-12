import { Streamdown } from "streamdown";

import type { ThinkingBlockItem } from "../../types/message";
import { useStreamThrottle } from "./useStreamThrottle";

interface ThinkingBlockProps {
  item: ThinkingBlockItem;
}

function Strong(props: React.ComponentPropsWithoutRef<"strong">): JSX.Element {
  return <strong className="font-normal text-neutral-500" {...props} />;
}

function Pre({ children }: React.ComponentPropsWithoutRef<"pre">): JSX.Element {
  return <pre className="my-2 whitespace-pre-wrap font-mono text-xs not-italic">{children}</pre>;
}

const thinkingComponents = { strong: Strong, pre: Pre };

export function ThinkingBlock({ item }: ThinkingBlockProps): JSX.Element {
  const content = useStreamThrottle(item.content, item.isStreaming);

  return (
    <div className="thinking-block text-sm leading-relaxed text-neutral-400">
      <Streamdown
        mode="streaming"
        isAnimating={item.isStreaming}
        components={thinkingComponents}
      >
        {content}
      </Streamdown>
    </div>
  );
}
