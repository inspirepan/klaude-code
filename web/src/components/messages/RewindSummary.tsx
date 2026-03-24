import { useRef } from "react";
import { RotateCcw } from "lucide-react";

import { useT } from "@/i18n";
import type { RewindSummaryItem } from "../../types/message";
import { useSearchHighlight } from "./useSearchHighlight";

interface RewindSummaryProps {
  item: RewindSummaryItem;
}

export function RewindSummary({ item }: RewindSummaryProps): React.JSX.Element {
  const t = useT();
  const contentRef = useRef<HTMLDivElement>(null);
  useSearchHighlight(contentRef, `${item.rationale}\n${item.note}`);
  return (
    <div className="relative mt-4 pt-5">
      <div className="pointer-events-none absolute left-1/2 top-0 w-[200vw] -translate-x-1/2 border-t border-border/80" />
      <div className="rounded-lg bg-amber-50/55 px-5 py-5">
        <div className="mb-2 flex items-center gap-2 text-base font-semibold text-rewind-label">
          <RotateCcw className="h-4 w-4 shrink-0" />
          {t("rewind.label")(item.checkpointId)}
        </div>
        <div ref={contentRef} className="space-y-2 text-sm text-rewind-text">
          {item.rationale && (
            <p>
              <span className="font-medium text-rewind-label">{t("rewind.rationale")}</span>{" "}
              {item.rationale}
            </p>
          )}
          {item.note && (
            <p>
              <span className="font-medium text-rewind-label">{t("rewind.note")}</span> {item.note}
            </p>
          )}
          {item.originalUserMessage && (
            <p className="rounded bg-white/60 px-3 py-2 text-xs italic text-rewind-label">
              {item.originalUserMessage}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
