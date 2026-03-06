import {
  Children,
  isValidElement,
  type ComponentPropsWithoutRef,
  type ReactElement,
  type ReactNode,
} from "react";
import { Streamdown } from "streamdown";
import { code } from "@streamdown/code";
import { CheckCircle2, Circle } from "lucide-react";

import type { CompactionSummaryItem } from "../../types/message";
import { mermaid } from "../../lib/mermaid-plugin";

interface CompactionSummaryProps {
  item: CompactionSummaryItem;
}

const plugins = { code, mermaid };

function isTaskCheckboxNode(
  node: ReactNode,
): node is ReactElement<{ type?: string; checked?: boolean }> {
  return isValidElement(node) && node.type === "input" && node.props.type === "checkbox";
}

function CompactionListItem(props: ComponentPropsWithoutRef<"li">): JSX.Element {
  const childNodes = Children.toArray(props.children);
  const checkboxIndex = childNodes.findIndex((node) => isTaskCheckboxNode(node));
  if (checkboxIndex < 0) {
    return <li {...props} />;
  }

  const checkboxNode = childNodes[checkboxIndex];
  if (!isTaskCheckboxNode(checkboxNode)) {
    return <li {...props} />;
  }

  const checked = checkboxNode.props.checked === true;
  const contentNodes = childNodes.filter((_, index) => index !== checkboxIndex);
  const { className, children: _children, ...rest } = props;

  return (
    <li {...rest} className={["compaction-task-item", className].filter(Boolean).join(" ")}>
      <span className={`compaction-task-icon ${checked ? "is-checked" : ""}`} aria-hidden>
        {checked ? <CheckCircle2 className="h-4 w-4" /> : <Circle className="h-4 w-4" />}
      </span>
      <span className={`compaction-task-text ${checked ? "is-checked" : ""}`}>{contentNodes}</span>
    </li>
  );
}

const compactionComponents = { li: CompactionListItem };

export function CompactionSummary({ item }: CompactionSummaryProps): JSX.Element {
  return (
    <div className="relative mt-4 pt-5">
      <div className="pointer-events-none absolute left-1/2 top-0 w-[200vw] -translate-x-1/2 border-t border-neutral-200/80" />
      <div className="rounded-xl bg-blue-50/55 px-5 py-5">
        <div className="mb-2 text-sm font-semibold tracking-[0.01em] text-[#5b6f92]">Compacted</div>
        <div className="compaction-summary-md text-[#2f3f5f]">
          <Streamdown plugins={plugins} components={compactionComponents}>
            {item.content}
          </Streamdown>
        </div>
      </div>
    </div>
  );
}
