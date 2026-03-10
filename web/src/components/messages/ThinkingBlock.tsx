import { Streamdown } from "streamdown";
import { code } from "@streamdown/code";

import type { ThinkingBlockItem } from "../../types/message";
import { useStreamThrottle } from "./useStreamThrottle";

interface ThinkingBlockProps {
  item: ThinkingBlockItem;
}

const plugins = { code };

function Strong(props: React.ComponentPropsWithoutRef<"strong">): JSX.Element {
  return <strong className="font-normal text-neutral-500" {...props} />;
}

const thinkingComponents = { strong: Strong };

export function ThinkingBlock({ item }: ThinkingBlockProps): JSX.Element {
  const content = useStreamThrottle(item.content, item.isStreaming);

  return (
    <div className="thinking-block text-sm leading-relaxed text-neutral-400">
      <Streamdown
        mode="streaming"
        isAnimating={item.isStreaming}
        plugins={plugins}
        components={thinkingComponents}
      >
        {content}
      </Streamdown>
    </div>
  );
}
