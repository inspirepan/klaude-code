import { useState } from "react";
import { ChevronRight } from "lucide-react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../ui/collapsible";
import type { UnknownEventItem } from "../../types/message";

interface UnknownEventProps {
  item: UnknownEventItem;
}

export function UnknownEvent({ item }: UnknownEventProps): JSX.Element {
  const [open, setOpen] = useState(false);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex items-center gap-1.5 text-neutral-300 hover:text-neutral-400 transition-colors cursor-pointer">
        <ChevronRight
          className={`w-3 h-3 transition-transform duration-150 ${open ? "rotate-90" : ""}`}
        />
        <span className="text-xs select-none">{item.eventType}</span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <pre className="mt-1 text-xs text-neutral-400 bg-neutral-50 rounded p-2 overflow-x-auto">
          {JSON.stringify(item.rawEvent, null, 2)}
        </pre>
      </CollapsibleContent>
    </Collapsible>
  );
}
