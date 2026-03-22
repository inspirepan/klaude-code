import { useEffect, useRef, useState } from "react";
import { Streamdown } from "streamdown";

import { useT } from "@/i18n";
import type { ThinkingBlockItem } from "../../types/message";
import {
  CollapseRailConnector,
  COLLAPSE_RAIL_GRID_CLASS_NAME,
  CollapseRailMarker,
  CollapseRailPanel,
} from "./CollapseRail";
import { useCollapseAll } from "./collapse-all-context";
import { useSearch } from "./search-context";

interface ThinkingBlockProps {
  item: ThinkingBlockItem;
}

function Strong(props: React.ComponentPropsWithoutRef<"strong">): JSX.Element {
  return <strong className="font-normal text-neutral-700" {...props} />;
}

function Pre({ children }: React.ComponentPropsWithoutRef<"pre">): JSX.Element {
  return (
    <span className="block font-mono" style={{ fontSize: "0.95em" }}>
      {children}
    </span>
  );
}

function Code({ children }: React.ComponentPropsWithoutRef<"code">): JSX.Element {
  return (
    <span className="font-mono" style={{ fontSize: "0.95em" }}>
      {children}
    </span>
  );
}

const thinkingComponents = { strong: Strong, pre: Pre, code: Code };

export function ThinkingBlock({ item }: ThinkingBlockProps): JSX.Element {
  const t = useT();
  const { matchItemIds } = useSearch();
  const { collapseGen, expandGen } = useCollapseAll();
  const defaultExpanded = item.isStreaming;
  const [open, setOpen] = useState(defaultExpanded);
  const isSearchMatch = matchItemIds.includes(item.id);
  const wasAutoExpanded = useRef(false);

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
    if (item.isStreaming && item.content.length > 0 && !open) {
      setOpen(true);
    }
  }, [item.isStreaming, item.content, open]);

  return (
    <div
      className={`-my-1 grid items-start ${COLLAPSE_RAIL_GRID_CLASS_NAME} cursor-pointer font-mono text-base`}
      onClick={() => setOpen((value) => !value)}
    >
      <CollapseRailMarker open={open} />
      <span className="whitespace-nowrap font-mono font-normal text-neutral-600">{t("thinking.label")}</span>

      <CollapseRailPanel open={open} className="col-span-2">
        <div className={`mt-2 grid min-w-0 items-start ${COLLAPSE_RAIL_GRID_CLASS_NAME}`}>
          <CollapseRailConnector />
          <div
            className="thinking-block min-w-0 font-sans text-base leading-relaxed text-neutral-600"
            onClick={(event) => {
              event.stopPropagation();
            }}
          >
            <Streamdown
              mode={item.isStreaming ? "static" : "streaming"}
              isAnimating={item.isStreaming}
              components={thinkingComponents}
            >
              {item.content}
            </Streamdown>
          </div>
        </div>
      </CollapseRailPanel>
    </div>
  );
}
