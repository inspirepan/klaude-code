import { useState, useCallback, useRef, useEffect } from "react";
import { Search, X, ChevronUp, ChevronDown } from "lucide-react";

interface SearchBarProps {
  totalMatches: number;
  activeIndex: number;
  onQueryChange: (query: string) => void;
  onNext: () => void;
  onPrev: () => void;
  onClose: () => void;
}

export function SearchBar({ totalMatches, activeIndex, onQueryChange, onNext, onPrev, onClose }: SearchBarProps): JSX.Element {
  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState("");

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

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
    <div className="absolute top-2 right-4 sm:right-6 z-20">
      <div className="flex items-center gap-1.5 bg-white border border-neutral-200 rounded-lg shadow-sm px-3 py-1.5">
        <Search className="w-3.5 h-3.5 text-neutral-400 shrink-0" />
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder="Search..."
          className="text-sm text-neutral-700 placeholder:text-neutral-300 outline-none bg-transparent w-48"
        />
        {value ? (
          <span className="text-xs text-neutral-400 tabular-nums whitespace-nowrap">
            {totalMatches > 0 ? `${activeIndex + 1} / ${totalMatches}` : "0 / 0"}
          </span>
        ) : null}
        <div className="flex items-center gap-0.5 ml-1">
          <button
            type="button"
            onClick={onPrev}
            disabled={totalMatches === 0}
            className="p-0.5 text-neutral-400 hover:text-neutral-600 disabled:opacity-30 cursor-pointer disabled:cursor-default"
          >
            <ChevronUp className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={onNext}
            disabled={totalMatches === 0}
            className="p-0.5 text-neutral-400 hover:text-neutral-600 disabled:opacity-30 cursor-pointer disabled:cursor-default"
          >
            <ChevronDown className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={onClose}
            className="p-0.5 text-neutral-400 hover:text-neutral-600 cursor-pointer ml-0.5"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
