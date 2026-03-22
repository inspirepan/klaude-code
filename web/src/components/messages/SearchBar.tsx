import { useState, useCallback, useRef } from "react";

import { useMountEffect } from "@/hooks/useMountEffect";
import { Search, X, ChevronUp, ChevronDown } from "lucide-react";

interface SearchBarProps {
  totalMatches: number;
  activeIndex: number;
  onQueryChange: (query: string) => void;
  onNext: () => void;
  onPrev: () => void;
  onClose: () => void;
}

export function SearchBar({
  totalMatches,
  activeIndex,
  onQueryChange,
  onNext,
  onPrev,
  onClose,
}: SearchBarProps): JSX.Element {
  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState("");

  useMountEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  });

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const v = e.target.value;
      setValue(v);
      onQueryChange(v);
    },
    [onQueryChange],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (e.shiftKey) {
          onPrev();
        } else {
          onNext();
        }
      }
    },
    [onClose, onNext, onPrev],
  );

  return (
    <div className="absolute right-4 top-2 z-30 sm:right-6">
      <div className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 shadow-sm">
        <Search className="h-3.5 w-3.5 shrink-0 text-neutral-500" />
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder="Search…"
          className="w-48 bg-transparent text-sm text-neutral-700 outline-none placeholder:text-neutral-300"
        />
        {value ? (
          <span className="whitespace-nowrap text-sm tabular-nums text-neutral-500">
            {totalMatches > 0 ? `${activeIndex + 1} / ${totalMatches}` : "0 / 0"}
          </span>
        ) : null}
        <div className="ml-1 flex items-center gap-0.5">
          <button
            type="button"
            onClick={onPrev}
            disabled={totalMatches === 0}
            className="cursor-pointer p-0.5 text-neutral-500 hover:text-neutral-700 disabled:cursor-default disabled:opacity-30"
          >
            <ChevronUp className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={onNext}
            disabled={totalMatches === 0}
            className="cursor-pointer p-0.5 text-neutral-500 hover:text-neutral-700 disabled:cursor-default disabled:opacity-30"
          >
            <ChevronDown className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={onClose}
            className="ml-0.5 cursor-pointer p-0.5 text-neutral-500 hover:text-neutral-700"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
