import { Streamdown } from "streamdown";
import { code } from "@streamdown/code";

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
  return (
    <div className="thinking-block text-sm leading-relaxed text-neutral-400">
      <Streamdown isAnimating={item.isStreaming} plugins={plugins} components={thinkingComponents}>
        {item.content}
      </Streamdown>
    </div>
  );
}
