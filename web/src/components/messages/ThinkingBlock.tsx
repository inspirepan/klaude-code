import { Streamdown } from "streamdown";

import type { ThinkingBlockItem } from "../../types/message";

interface ThinkingBlockProps {
  item: ThinkingBlockItem;
}

const streamAnimation = { animation: "fadeIn" as const, duration: 120, sep: "char" as const };

function Strong(props: React.ComponentPropsWithoutRef<"strong">): JSX.Element {
  return <strong className="font-normal text-neutral-700" {...props} />;
}

function Pre({ children }: React.ComponentPropsWithoutRef<"pre">): JSX.Element {
  return <pre className="my-2 whitespace-pre-wrap font-mono text-xs not-italic">{children}</pre>;
}

const thinkingComponents = { strong: Strong, pre: Pre };

export function ThinkingBlock({ item }: ThinkingBlockProps): JSX.Element {
  return (
    <div className="thinking-block text-sm leading-relaxed text-neutral-500">
      <Streamdown
        mode="streaming"
        isAnimating={item.isStreaming}
        animated={streamAnimation}
        components={thinkingComponents}
      >
        {item.content}
      </Streamdown>
    </div>
  );
}
