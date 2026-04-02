import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, ChevronRight, Search } from "lucide-react";

import type { ConfigModelSummary } from "@/api/client";
import { useT } from "@/i18n";
import { ScrollArea } from "@/components/ui/scroll-area";
import { CommandListItem } from "@/components/ui/command-list";

interface ModelSelectorProps {
  options: ConfigModelSummary[];
  value: string;
  loading?: boolean;
  disabled?: boolean;
  placeholder?: string;
  onSelect: (modelName: string) => void;
  triggerClassName?: string;
  panelClassName?: string;
  /** Open the dropdown above the trigger (default) or below. */
  dropUp?: boolean;
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
  placeholder,
  onSelect,
  triggerClassName,
  panelClassName,
  dropUp = true,
}: ModelSelectorProps): React.JSX.Element {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlightIndex, setHighlightIndex] = useState(0);
  const [collapsedProviders, setCollapsedProviders] = useState<Record<string, boolean>>({});
  const rootRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const current = options.find((option) => option.name === value) ?? null;
  const groups = useMemo(() => {
    const q = query.toLowerCase();
    const filtered = q
      ? options.filter(
          (o) =>
            o.model_id.toLowerCase().includes(q) ||
            o.model_name.toLowerCase().includes(q) ||
            o.provider.toLowerCase().includes(q),
        )
      : options;
    const grouped = new Map<string, ConfigModelSummary[]>();
    for (const option of filtered) {
      const provider = normalizeProvider(option.provider);
      const existing = grouped.get(provider);
      if (existing) {
        existing.push(option);
      } else {
        grouped.set(provider, [option]);
      }
    }
    return [...grouped.entries()].map(([provider, models]) => ({ provider, models }));
  }, [options, query]);

  // Flat list of visible model names (respects collapsed providers)
  const visibleModels = useMemo(
    () =>
      groups.flatMap((g) => (collapsedProviders[g.provider] ? [] : g.models.map((m) => m.name))),
    [groups, collapsedProviders],
  );

  // Scroll highlighted item into view
  useEffect(() => {
    const name = visibleModels[highlightIndex];
    if (!name || !listRef.current) return;
    const el = listRef.current.querySelector(`[data-model-name="${CSS.escape(name)}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [highlightIndex, visibleModels]);

  useEffect(() => {
    if (!open) {
      return;
    }

    // Focus search input on open
    requestAnimationFrame(() => searchRef.current?.focus());

    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        setQuery("");
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
    current?.model_id ??
    (value.trim().length > 0
      ? value
      : loading
        ? t("model.loading")
        : (placeholder ?? t("model.selectModel")));

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        disabled={disabled || options.length === 0}
        onClick={() => {
          setOpen((prev) => {
            if (prev) setQuery("");
            return !prev;
          });
        }}
        className={
          triggerClassName ??
          "inline-flex h-7 items-center gap-1 rounded-md px-1.5 text-sm text-neutral-500 transition-colors hover:text-neutral-700 disabled:cursor-not-allowed disabled:text-neutral-300"
        }
      >
        <span className="max-w-44 truncate">{triggerLabel}</span>
        <ChevronDown
          className={`mt-px h-3.5 w-3.5 text-neutral-500 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open ? (
        <div
          className={
            panelClassName ??
            `absolute left-0 z-30 w-[360px] overflow-hidden rounded-xl bg-card pt-1 shadow-float-lg ring-1 ring-black/[0.06] ${dropUp ? "bottom-full mb-2" : "top-full mt-2"}`
          }
        >
          <div className="flex items-center gap-1.5 border-b border-neutral-100 px-2 pb-1.5 pt-1">
            <Search className="h-3.5 w-3.5 shrink-0 text-neutral-500" />
            <input
              ref={searchRef}
              type="text"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setHighlightIndex(0);
              }}
              onKeyDown={(event) => {
                if (event.key === "ArrowDown") {
                  event.preventDefault();
                  setHighlightIndex((i) => Math.min(i + 1, visibleModels.length - 1));
                } else if (event.key === "ArrowUp") {
                  event.preventDefault();
                  setHighlightIndex((i) => Math.max(i - 1, 0));
                } else if (event.key === "Enter") {
                  event.preventDefault();
                  const name = visibleModels[highlightIndex];
                  if (name) {
                    onSelect(name);
                    setOpen(false);
                    setQuery("");
                  }
                }
              }}
              placeholder={t("model.filterPlaceholder")}
              className="h-6 w-full bg-transparent text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
            />
          </div>
          <ScrollArea
            ref={listRef}
            className="w-full py-1"
            viewportClassName="max-h-96"
            type="auto"
          >
            {groups.map((group) => {
              const collapsed = collapsedProviders[group.provider];
              return (
                <div key={group.provider}>
                  <button
                    type="button"
                    className="mx-1.5 flex w-[calc(100%-0.75rem)] items-center gap-1 rounded-md px-2 pb-0.5 pt-1.5 text-xs tracking-wide text-emerald-700 transition-colors hover:bg-surface"
                    onMouseDown={(event) => {
                      event.preventDefault();
                    }}
                    onClick={() => {
                      setCollapsedProviders((prev) => ({
                        ...prev,
                        [group.provider]: !prev[group.provider],
                      }));
                      setHighlightIndex(0);
                    }}
                  >
                    {collapsed ? (
                      <ChevronRight className="h-3 w-3 shrink-0" />
                    ) : (
                      <ChevronDown className="h-3 w-3 shrink-0" />
                    )}
                    <span>
                      {group.provider} ({group.models.length})
                    </span>
                  </button>
                  {collapsed
                    ? null
                    : group.models.map((model) => {
                        const selected = model.name === value;
                        const highlighted = visibleModels[highlightIndex] === model.name;
                        const rawParam = model.params.find(
                          (p) =>
                            p.startsWith("reasoning") ||
                            p.startsWith("adaptive") ||
                            p.startsWith("thinking budget"),
                        );
                        const reasoningParam = rawParam?.startsWith("reasoning ")
                          ? rawParam.slice("reasoning ".length)
                          : rawParam;
                        return (
                          <CommandListItem
                            key={model.name}
                            data-model-name={model.name}
                            highlighted={highlighted || selected}
                            className={`justify-between pl-6 ${!highlighted && selected ? "bg-surface" : ""}`}
                            onPointerEnter={() => {
                              const idx = visibleModels.indexOf(model.name);
                              if (idx >= 0) setHighlightIndex(idx);
                            }}
                            onClick={() => {
                              onSelect(model.name);
                              setOpen(false);
                              setQuery("");
                            }}
                          >
                            <span className="min-w-0 flex-1 truncate">
                              {model.model_id}
                              {reasoningParam ? (
                                <span className="text-neutral-500">
                                  {" · "}
                                  {reasoningParam}
                                </span>
                              ) : null}
                            </span>
                            <span className="inline-flex shrink-0 items-center gap-1 text-xs text-neutral-500">
                              {model.is_default ? t("model.default") : null}
                              {selected ? <Check className="h-3 w-3" /> : null}
                            </span>
                          </CommandListItem>
                        );
                      })}
                </div>
              );
            })}
          </ScrollArea>
        </div>
      ) : null}
    </div>
  );
}
