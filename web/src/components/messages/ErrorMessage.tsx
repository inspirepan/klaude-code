import { TriangleAlert } from "lucide-react";

import { useT } from "@/i18n";
import type { ErrorItem } from "@/types/message";
import { COLLAPSE_RAIL_GRID_CLASS_NAME } from "./CollapseRail";

interface ErrorMessageProps {
  item: ErrorItem;
}

export function ErrorMessage({ item }: ErrorMessageProps): React.JSX.Element {
  const t = useT();
  return (
    <div className={`grid items-start ${COLLAPSE_RAIL_GRID_CLASS_NAME} py-1 text-sm text-red-700`}>
      <span className="flex h-[1lh] items-center justify-center">
        <TriangleAlert className="h-3.5 w-3.5 shrink-0" strokeWidth={2.25} />
      </span>
      <div className="min-w-0">
        <div className="break-words">{item.message}</div>
        {item.canRetry ? <div className="text-red-500/80">{t("error.retryAvailable")}</div> : null}
      </div>
    </div>
  );
}
