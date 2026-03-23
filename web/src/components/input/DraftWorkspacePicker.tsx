import {
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type RefObject,
  type SetStateAction,
} from "react";
import { ArrowDown, ArrowUp, ChevronDown, CornerDownLeft, Folder } from "lucide-react";

import { CommandListItem, CommandListPanel, CommandListScroll } from "@/components/ui/command-list";
import { useT } from "@/i18n";

interface DraftWorkspacePickerProps {
  draftWorkDir: string;
  normalizedDraftWorkDir: string;
  workspaceMenuOpen: boolean;
  filteredWorkspaceOptions: string[];
  workspacePickerRef: RefObject<HTMLDivElement>;
  inputRef?: RefObject<HTMLInputElement>;
  setDraftWorkDir: (workDir: string) => void;
  setWorkspaceMenuOpen: Dispatch<SetStateAction<boolean>>;
  onSelect?: () => void;
}

function workDirDisplay(workDir: string): { name: string; parent: string | null } {
  const stripped = workDir.endsWith("/") ? workDir.slice(0, -1) : workDir;
  const lastSlash = stripped.lastIndexOf("/");
  const name = lastSlash >= 0 ? stripped.slice(lastSlash + 1) : stripped;
  const parent = lastSlash >= 0 ? `${stripped.slice(0, lastSlash)}/` : null;
  return { name, parent };
}

export function DraftWorkspacePicker({
  draftWorkDir,
  normalizedDraftWorkDir,
  workspaceMenuOpen,
  filteredWorkspaceOptions,
  workspacePickerRef,
  inputRef,
  setDraftWorkDir,
  setWorkspaceMenuOpen,
  onSelect,
}: DraftWorkspacePickerProps): JSX.Element {
  const t = useT();
  const [highlightedWorkspace, setHighlightedWorkspace] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const highlightIndex = (() => {
    if (filteredWorkspaceOptions.length === 0 || highlightedWorkspace === null) {
      return 0;
    }
    const index = filteredWorkspaceOptions.indexOf(highlightedWorkspace);
    return index >= 0 ? index : 0;
  })();

  // Scroll highlighted item into view
  useEffect(() => {
    const workspace = filteredWorkspaceOptions[highlightIndex];
    if (!workspace || !listRef.current) return;
    const item = listRef.current.querySelector(`[data-workspace="${CSS.escape(workspace)}"]`);
    item?.scrollIntoView({ block: "nearest" });
  }, [highlightIndex, filteredWorkspaceOptions]);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>): void => {
    if (event.key === "Escape") {
      setWorkspaceMenuOpen(false);
      return;
    }
    if (!workspaceMenuOpen || filteredWorkspaceOptions.length === 0) {
      if (event.key === "Enter") {
        event.preventDefault();
        setWorkspaceMenuOpen(false);
        onSelect?.();
      }
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      const nextIndex = Math.min(highlightIndex + 1, filteredWorkspaceOptions.length - 1);
      setHighlightedWorkspace(filteredWorkspaceOptions[nextIndex] ?? null);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      const nextIndex = Math.max(highlightIndex - 1, 0);
      setHighlightedWorkspace(filteredWorkspaceOptions[nextIndex] ?? null);
    } else if (event.key === "Enter") {
      event.preventDefault();
      const workspace = filteredWorkspaceOptions[highlightIndex];
      if (workspace) {
        setDraftWorkDir(workspace);
        setWorkspaceMenuOpen(false);
        onSelect?.();
      }
    } else if (event.key === "Tab" && filteredWorkspaceOptions.length > 0) {
      event.preventDefault();
      const workspace = filteredWorkspaceOptions[highlightIndex];
      if (workspace) {
        setDraftWorkDir(workspace);
        setHighlightedWorkspace(null);
      }
    }
  };

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-3">
        <label htmlFor="draft-workspace" className="text-sm font-semibold text-neutral-600">
          {t("workspace.label")}
        </label>
        <span className="text-xs text-neutral-500">{t("workspace.hint")}</span>
      </div>
      <div ref={workspacePickerRef} className="relative">
        <div
          className={[
            "flex items-center rounded-lg bg-card shadow-sm ring-1 ring-black/5 transition-colors",
            workspaceMenuOpen ? "bg-card" : "hover:bg-card",
          ].join(" ")}
        >
          <div className="pl-3 text-neutral-500">
            <Folder className="h-4 w-4" />
          </div>
          <input
            ref={inputRef}
            id="draft-workspace"
            value={draftWorkDir}
            onFocus={() => {
              setWorkspaceMenuOpen(true);
            }}
            onChange={(event) => {
              setDraftWorkDir(event.target.value);
              setWorkspaceMenuOpen(true);
              setHighlightedWorkspace(null);
            }}
            onKeyDown={handleKeyDown}
            placeholder={t("workspace.placeholder")}
            className="w-full flex-1 border-0 bg-transparent px-2 py-2 text-base text-neutral-700 outline-none placeholder:text-neutral-400"
          />
          <button
            type="button"
            className="mr-1 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-neutral-500 transition-colors hover:bg-muted hover:text-neutral-700"
            onClick={() => {
              setWorkspaceMenuOpen((prev) => !prev);
            }}
            aria-label={t("workspace.toggle")}
          >
            <ChevronDown
              className={[
                "h-3 w-3 transition-transform duration-150",
                workspaceMenuOpen ? "rotate-180" : "rotate-0",
              ].join(" ")}
            />
          </button>
        </div>

        {workspaceMenuOpen ? (
          <CommandListPanel className="absolute left-0 right-0 z-20 mt-1.5 shadow-float">
            {filteredWorkspaceOptions.length > 0 ? (
              <CommandListScroll ref={listRef} maxHeight="max-h-64">
                {filteredWorkspaceOptions.map((workspace) => {
                  const isHighlighted = workspace === filteredWorkspaceOptions[highlightIndex];
                  const isSelected = workspace === normalizedDraftWorkDir;
                  const { name, parent } = workDirDisplay(workspace);
                  return (
                    <CommandListItem
                      key={workspace}
                      data-workspace={workspace}
                      highlighted={isHighlighted || isSelected}
                      onPointerEnter={() => {
                        setHighlightedWorkspace(workspace);
                      }}
                      onClick={() => {
                        setDraftWorkDir(workspace);
                        setWorkspaceMenuOpen(false);
                        onSelect?.();
                      }}
                    >
                      <Folder className="h-4 w-4 shrink-0 text-neutral-500" />
                      <span className="min-w-0 flex-1 truncate">
                        <span className="text-neutral-500">{parent ?? ""}</span>
                        <span className="text-neutral-700">{name}</span>
                      </span>
                    </CommandListItem>
                  );
                })}
              </CommandListScroll>
            ) : (
              <div className="px-3 py-2 text-sm text-neutral-500">{t("workspace.noMatch")}</div>
            )}
            {filteredWorkspaceOptions.length > 0 ? (
              <div className="flex items-center gap-2 border-t border-neutral-100 px-2.5 py-1.5">
                <span className="inline-flex items-center gap-1.5 text-neutral-500">
                  <span className="inline-flex items-center gap-0.5">
                    <kbd className="inline-flex items-center justify-center rounded border border-border bg-surface p-px text-neutral-500 shadow-[0_1px_0_rgba(0,0,0,0.08)]">
                      <ArrowUp className="h-2.5 w-2.5" />
                    </kbd>
                    <kbd className="inline-flex items-center justify-center rounded border border-border bg-surface p-px text-neutral-500 shadow-[0_1px_0_rgba(0,0,0,0.08)]">
                      <ArrowDown className="h-2.5 w-2.5" />
                    </kbd>
                  </span>
                  <span className="text-sm">{t("workspace.navigate")}</span>
                </span>
                <span className="text-neutral-300">·</span>
                <span className="inline-flex items-center gap-1.5 text-neutral-500">
                  <kbd className="inline-flex items-center justify-center rounded border border-border bg-surface px-1 text-[11px] font-medium leading-[18px] text-neutral-500 shadow-[0_1px_0_rgba(0,0,0,0.08)]">
                    Tab
                  </kbd>
                  <span className="text-sm">{t("workspace.fill")}</span>
                </span>
                <span className="text-neutral-300">·</span>
                <span className="inline-flex items-center gap-1.5 text-neutral-500">
                  <kbd className="inline-flex items-center justify-center rounded border border-border bg-surface p-px text-neutral-500 shadow-[0_1px_0_rgba(0,0,0,0.08)]">
                    <CornerDownLeft className="h-2.5 w-2.5" />
                  </kbd>
                  <span className="text-sm">{t("workspace.select")}</span>
                </span>
              </div>
            ) : null}
          </CommandListPanel>
        ) : null}
      </div>
    </div>
  );
}
