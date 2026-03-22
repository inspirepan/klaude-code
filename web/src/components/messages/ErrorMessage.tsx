import { TriangleAlert } from "lucide-react";

import type { ErrorItem } from "../../types/message";

interface ErrorMessageProps {
  item: ErrorItem;
}

export function ErrorMessage({ item }: ErrorMessageProps): JSX.Element {
  return (
    <div className="flex items-start gap-1.5 text-base text-red-700">
      <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={2.25} />
      <div className="min-w-0">
        <div className="break-words">{item.message}</div>
        {item.canRetry ? <div className="text-red-500/80">Retry available</div> : null}
      </div>
    </div>
  );
}
