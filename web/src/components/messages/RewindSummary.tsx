import { useEffect, useRef, useState } from "react";
import { RotateCcw } from "lucide-react";

import { useT } from "@/i18n";
import type { RewindSummaryItem } from "../../types/message";
import { useSearchHighlight } from "./useSearchHighlight";

interface RewindSummaryProps {
  item: RewindSummaryItem;
}

const COLLAPSED_MAX_HEIGHT = 320;

export function RewindSummary({ item }: RewindSummaryProps): React.JSX.Element {
  const t = useT();
  const contentRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [isOverflowing, setIsOverflowing] = useState(false);

  useSearchHighlight(contentRef, `${item.rationale}\n${item.note}`);

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
  }, [item.rationale, item.note]);

  return (
    <div className="relative mt-4 pt-5">
      <div className="pointer-events-none absolute left-1/2 top-0 w-[200vw] -translate-x-1/2 border-t border-border/80" />
      <div className="rounded-lg bg-amber-50/55 px-5 py-5">
        <div className="mb-2 flex items-center gap-2 text-base font-semibold text-rewind-label">
          <RotateCcw className="h-4 w-4 shrink-0" />
          {t("rewind.label")(item.checkpointId)}
        </div>
        <div
          className="relative"
          style={
            !expanded && isOverflowing
              ? { maxHeight: COLLAPSED_MAX_HEIGHT, overflow: "hidden" }
              : undefined
          }
        >
          <div ref={contentRef} className="space-y-2 text-sm text-rewind-text">
            {item.rationale && (
              <p>
                <span className="font-medium text-rewind-label">{t("rewind.rationale")}</span>{" "}
                {item.rationale}
              </p>
            )}
            {item.note && (
              <p>
                <span className="font-medium text-rewind-label">{t("rewind.note")}</span>{" "}
                {item.note}
              </p>
            )}
            {item.originalUserMessage && (
              <p className="rounded bg-white/60 px-3 py-2 text-xs italic text-rewind-label">
                {item.originalUserMessage}
              </p>
            )}
          </div>
          {!expanded && isOverflowing ? (
            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-amber-50/90 to-transparent" />
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
            {expanded ? t("rewind.showLess") : t("rewind.showMore")}
          </button>
        ) : null}
      </div>
    </div>
  );
}
