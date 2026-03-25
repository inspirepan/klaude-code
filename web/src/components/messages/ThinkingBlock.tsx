import { useEffect, useRef, useState } from "react";
import { Streamdown } from "streamdown";

import { useT } from "@/i18n";
import type { ThinkingBlockItem } from "@/types/message";
import {
  COLLAPSE_RAIL_GRID_CLASS_NAME,
  CollapseRailMarker,
  CollapseRailPanel,
} from "./CollapseRail";
import { useCollapseAll } from "./collapse-all-context";
import { useSearch } from "./search-context";
import { useSearchHighlight } from "./useSearchHighlight";
import { useStreamThrottle } from "./useStreamThrottle";

interface ThinkingBlockProps {
  item: ThinkingBlockItem;
}

function Strong(props: React.ComponentPropsWithoutRef<"strong">): React.JSX.Element {
  return <strong className="font-normal text-neutral-500" {...props} />;
}

function Pre({ children }: React.ComponentPropsWithoutRef<"pre">): React.JSX.Element {
  return (
    <span className="block whitespace-pre-wrap font-mono" style={{ fontSize: "0.9em" }}>
      {children}
    </span>
  );
}

function Code({ children }: React.ComponentPropsWithoutRef<"code">): React.JSX.Element {
  return (
    <span className="font-mono" style={{ fontSize: "0.9em" }}>
      {children}
    </span>
  );
}

const thinkingComponents = { strong: Strong, pre: Pre, code: Code };

export function ThinkingBlock({ item }: ThinkingBlockProps): React.JSX.Element {
  const t = useT();
  const { matchItemIds } = useSearch();
  const { collapseGen, expandGen } = useCollapseAll();
  const throttledContent = useStreamThrottle(item.content, item.isStreaming);
  const defaultExpanded = item.isStreaming;
  const [open, setOpen] = useState(defaultExpanded);
  const isSearchMatch = matchItemIds.includes(item.id);
  const wasAutoExpanded = useRef(false);
  const contentRef = useRef<HTMLDivElement>(null);
  useSearchHighlight(contentRef, throttledContent);

  useEffect(() => {
    if (isSearchMatch && !open) {
      setOpen(true);
      wasAutoExpanded.current = true;
    }
    if (!isSearchMatch && wasAutoExpanded.current) {
      setOpen(defaultExpanded);
      wasAutoExpanded.current = false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSearchMatch]);

  useEffect(() => {
    if (collapseGen > 0) setOpen(false);
  }, [collapseGen]);

  useEffect(() => {
    if (expandGen > 0) setOpen(true);
  }, [expandGen]);

  useEffect(() => {
    if (item.isStreaming && throttledContent.length > 0 && !open) {
      setOpen(true);
    }
  }, [item.isStreaming, open, throttledContent]);

  return (
    <div
      className={`grid items-start ${COLLAPSE_RAIL_GRID_CLASS_NAME} text-sm ${item.isStreaming ? "" : "cursor-pointer"}`}
      onClick={() => {
        if (!item.isStreaming) setOpen((value) => !value);
      }}
    >
      <CollapseRailMarker open={open} className="row-span-2" />
      <span className="whitespace-nowrap font-normal text-neutral-500">{t("thinking.label")}</span>

      <CollapseRailPanel open={open}>
        <div
          ref={contentRef}
          className="thinking-block mt-2 min-w-0 font-sans text-sm leading-relaxed text-neutral-500"
          onClick={(event) => {
            event.stopPropagation();
          }}
        >
          <Streamdown mode="static" isAnimating={item.isStreaming} components={thinkingComponents}>
            {throttledContent}
          </Streamdown>
        </div>
      </CollapseRailPanel>
    </div>
  );
}
