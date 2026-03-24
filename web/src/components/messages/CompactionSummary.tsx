import {
  Children,
  isValidElement,
  useEffect,
  useRef,
  useState,
  type ComponentPropsWithoutRef,
  type ReactElement,
  type ReactNode,
} from "react";
import { Streamdown } from "streamdown";
import { code } from "@streamdown/code";
import { CheckCircle2, Circle } from "lucide-react";

import { useT } from "@/i18n";
import type { CompactionSummaryItem } from "@/types/message";
import { mermaid } from "@/lib/mermaid-plugin";
import { useSearchHighlight } from "./useSearchHighlight";

interface CompactionSummaryProps {
  item: CompactionSummaryItem;
}

const plugins = { code, mermaid };

function isTaskCheckboxNode(
  node: ReactNode,
): node is ReactElement<{ type?: string; checked?: boolean }> {
  if (!isValidElement(node) || node.type !== "input") return false;
  const props = node.props as Record<string, unknown>;
  return props.type === "checkbox";
}

function CompactionListItem(props: ComponentPropsWithoutRef<"li">): React.JSX.Element {
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

const COLLAPSED_MAX_HEIGHT = 320;

export function CompactionSummary({ item }: CompactionSummaryProps): React.JSX.Element {
  const t = useT();
  const contentRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [isOverflowing, setIsOverflowing] = useState(false);

  useSearchHighlight(contentRef, item.content);

  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    const check = (): void => {
      setIsOverflowing(el.scrollHeight > COLLAPSED_MAX_HEIGHT);
    };
    check();
    const observer = new ResizeObserver(check);
    observer.observe(el);
    return () => {
      observer.disconnect();
    };
  }, [item.content]);

  return (
    <div className="relative mt-4 pt-5">
      <div className="pointer-events-none absolute left-1/2 top-0 w-[200vw] -translate-x-1/2 border-t border-border/80" />
      <div className="rounded-lg bg-sky-50/55 px-5 py-5">
        <div className="mb-2 text-base font-semibold text-compaction-label">
          {t("compaction.label")}
        </div>
        <div
          className="relative"
          style={
            !expanded && isOverflowing
              ? { maxHeight: COLLAPSED_MAX_HEIGHT, overflow: "hidden" }
              : undefined
          }
        >
          <div ref={contentRef} className="compaction-summary-md text-compaction-text">
            <Streamdown plugins={plugins} components={compactionComponents}>
              {item.content}
            </Streamdown>
          </div>
          {!expanded && isOverflowing ? (
            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-sky-50/90 to-transparent" />
          ) : null}
        </div>
        {isOverflowing ? (
          <button
            type="button"
            className="mt-2 text-sm text-neutral-500 transition-colors hover:text-neutral-700"
            onClick={() => {
              setExpanded((v) => !v);
            }}
          >
            {expanded ? t("compaction.showLess") : t("compaction.showMore")}
          </button>
        ) : null}
      </div>
    </div>
  );
}
