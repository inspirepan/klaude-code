import { OctagonX } from "lucide-react";

import type { InterruptItem } from "../../types/message";

interface InterruptMessageProps {
  item: InterruptItem;
  compact?: boolean;
}

export function InterruptMessage(props: InterruptMessageProps): JSX.Element {
  void props;
  return (
    <div className="inline-flex items-center gap-1.5 text-base text-amber-700">
      <OctagonX className="h-3.5 w-3.5" strokeWidth={2.25} />
      <span>Interrupted by user</span>
    </div>
  );
}
