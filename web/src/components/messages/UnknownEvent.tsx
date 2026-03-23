import { useState, useRef, useEffect } from "react";
import { ChevronRight } from "lucide-react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../ui/collapsible";
import type { UnknownEventItem } from "../../types/message";
import { useSearch } from "./search-context";

interface UnknownEventProps {
  item: UnknownEventItem;
}

export function UnknownEvent({ item }: UnknownEventProps): JSX.Element {
  const { matchItemIds } = useSearch();
  const [open, setOpen] = useState(false);
  const isSearchMatch = matchItemIds.includes(item.id);
  const wasAutoExpanded = useRef(false);

  useEffect(() => {
    if (isSearchMatch && !open) {
      setOpen(true);
      wasAutoExpanded.current = true;
    }
    if (!isSearchMatch && wasAutoExpanded.current) {
      setOpen(false);
      wasAutoExpanded.current = false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSearchMatch]);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex cursor-pointer items-center gap-1.5 text-neutral-300 transition-colors hover:text-neutral-600">
        <ChevronRight
          className={`h-3 w-3 transition-transform duration-150 ${open ? "rotate-90" : ""}`}
        />
        <span className="select-none text-sm">{item.eventType}</span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <pre className="mt-1 overflow-x-auto rounded bg-surface p-2 text-sm text-neutral-600">
          {JSON.stringify(item.rawEvent, null, 2)}
        </pre>
      </CollapsibleContent>
    </Collapsible>
  );
}
