import { useMemo } from "react";

import { useSearch } from "./search-context";

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function HighlightText({ children }: { children: string }): JSX.Element {
  const { query } = useSearch();

  const parts = useMemo(() => {
    if (!query) return null;
    return children.split(new RegExp(`(${escapeRegExp(query)})`, "gi"));
  }, [children, query]);

  if (!parts) return <>{children}</>;

  const lower = query.toLowerCase();
  return (
    <>
      {parts.map((part, i) =>
        part.toLowerCase() === lower ? (
          <mark key={i} className="rounded-[2px] bg-amber-200/80 text-inherit">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}
