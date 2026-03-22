import { TriangleAlert } from "lucide-react";

import type { ErrorItem } from "../../types/message";

interface ErrorMessageProps {
  item: ErrorItem;
}

export function ErrorMessage({ item }: ErrorMessageProps): JSX.Element {
  return (
    <div className="rounded-lg border border-red-200/80 bg-red-50/70 px-3 py-2.5 text-base">
      <div className="flex items-start gap-2 text-red-700">
        <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={2.25} />
        <div className="min-w-0 space-y-0.5">
          <div className="font-medium">Error</div>
          <div className="break-words text-red-800">{item.message}</div>
          {item.canRetry ? <div className="text-red-600/80">Retry available</div> : null}
        </div>
      </div>
    </div>
  );
}
