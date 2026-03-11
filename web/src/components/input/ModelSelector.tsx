import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";

import type { ConfigModelSummary } from "../../api/client";

interface ModelSelectorProps {
  options: ConfigModelSummary[];
  value: string;
  loading?: boolean;
  disabled?: boolean;
  placeholder?: string;
  onSelect: (modelName: string) => void;
  triggerClassName?: string;
  panelClassName?: string;
}

function normalizeProvider(provider: string): string {
  const trimmed = provider.trim();
  return trimmed.length > 0 ? trimmed : "other";
}

export function ModelSelector({
  options,
  value,
  loading = false,
  disabled = false,
  placeholder = "Select model",
  onSelect,
  triggerClassName,
  panelClassName,
}: ModelSelectorProps): JSX.Element {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const current = options.find((option) => option.name === value) ?? null;
  const groups = useMemo(() => {
    const grouped = new Map<string, ConfigModelSummary[]>();
    for (const option of options) {
      const provider = normalizeProvider(option.provider);
      const existing = grouped.get(provider);
      if (existing) {
        existing.push(option);
      } else {
        grouped.set(provider, [option]);
      }
    }
    return [...grouped.entries()].map(([provider, models]) => ({ provider, models }));
  }, [options]);

  useEffect(() => {
    if (!open) {
      return;
    }

    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  const triggerLabel =
    current?.model_name ??
    (value.trim().length > 0 ? value : loading ? "Loading models..." : placeholder);

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        disabled={disabled || options.length === 0}
        onClick={() => {
          setOpen((prev) => !prev);
        }}
        className={
          triggerClassName ??
          "inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-sm text-neutral-700 transition-colors hover:bg-neutral-100 disabled:cursor-not-allowed disabled:text-neutral-400"
        }
      >
        <span className="max-w-44 truncate">{triggerLabel}</span>
        <ChevronDown
          className={`h-3.5 w-3.5 text-neutral-400 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open ? (
        <div
          className={
            panelClassName ??
            "absolute bottom-full left-0 z-30 mb-2 w-[320px] overflow-hidden rounded-xl border border-neutral-200 bg-white/95 p-1.5 shadow-[0_16px_40px_rgba(0,0,0,0.12)] backdrop-blur"
          }
        >
          <div className="max-h-72 overflow-y-auto">
            {groups.map((group) => (
              <div key={group.provider} className="mb-1 last:mb-0">
                <div className="px-2.5 pb-1 pt-2 text-[11px] uppercase tracking-[0.08em] text-neutral-400">
                  {group.provider}
                </div>
                <div className="space-y-0.5">
                  {group.models.map((model) => {
                    const selected = model.name === value;
                    return (
                      <button
                        key={model.name}
                        type="button"
                        className={[
                          "flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors",
                          selected
                            ? "bg-neutral-100 text-neutral-900"
                            : "text-neutral-700 hover:bg-neutral-50",
                        ].join(" ")}
                        onMouseDown={(event) => {
                          event.preventDefault();
                        }}
                        onClick={() => {
                          onSelect(model.name);
                          setOpen(false);
                        }}
                      >
                        <span className="truncate">{model.model_name}</span>
                        <span className="ml-2 inline-flex items-center gap-1.5 text-xs text-neutral-400">
                          {model.is_default ? "default" : null}
                          {selected ? <Check className="h-3.5 w-3.5" /> : null}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
