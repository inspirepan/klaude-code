import {
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type RefObject,
  type SetStateAction,
} from "react";
import { ArrowDown, ArrowUp, ChevronDown, CornerDownLeft, Folder } from "lucide-react";

import { ScrollArea } from "@/components/ui/scroll-area";

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
    if (!workspaceMenuOpen || filteredWorkspaceOptions.length === 0) {
      if (event.key === "Escape") setWorkspaceMenuOpen(false);
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
    } else if (event.key === "Escape") {
      setWorkspaceMenuOpen(false);
    }
  };

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-3">
        <label htmlFor="draft-workspace" className="text-sm font-semibold text-neutral-600">
          Workspace
        </label>
        <span className="text-xs text-neutral-500">Choose or type a local path</span>
      </div>
      <div ref={workspacePickerRef} className="relative">
        <div
          className={[
            "flex items-center rounded-lg bg-white shadow-sm ring-1 ring-black/5 transition-colors",
            workspaceMenuOpen ? "bg-white" : "hover:bg-white",
          ].join(" ")}
        >
          <div className="pl-3 text-neutral-400">
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
            placeholder="/path/to/workspace"
            className="w-full flex-1 border-0 bg-transparent px-2 py-2 text-base text-neutral-700 outline-none placeholder:text-neutral-400"
          />
          <button
            type="button"
            className="mr-1 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-neutral-400 transition-colors hover:bg-muted hover:text-neutral-700"
            onClick={() => {
              setWorkspaceMenuOpen((prev) => !prev);
            }}
            aria-label="Toggle workspace suggestions"
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
          <div className="absolute left-0 right-0 z-20 mt-1.5 overflow-hidden rounded-lg border border-neutral-200/80 bg-white pb-1.5 pt-2 shadow-[0_4px_16px_rgba(0,0,0,0.08)]">
            {filteredWorkspaceOptions.length > 0 ? (
              <ScrollArea
                ref={listRef}
                className="w-full"
                viewportClassName="max-h-64"
                type="hover"
              >
                {filteredWorkspaceOptions.map((workspace) => {
                  const isHighlighted = workspace === filteredWorkspaceOptions[highlightIndex];
                  const isSelected = workspace === normalizedDraftWorkDir;
                  const { name, parent } = workDirDisplay(workspace);
                  return (
                    <button
                      key={workspace}
                      data-workspace={workspace}
                      type="button"
                      className={[
                        "ml-2 mr-2.5 flex w-[calc(100%-1.125rem)] items-center gap-2 rounded-md px-2 py-1 text-left transition-colors",
                        isHighlighted || isSelected
                          ? "bg-muted text-neutral-900"
                          : "text-neutral-600 hover:bg-surface",
                      ].join(" ")}
                      onMouseDown={(event) => {
                        event.preventDefault();
                      }}
                      onPointerEnter={() => {
                        setHighlightedWorkspace(workspace);
                      }}
                      onClick={() => {
                        setDraftWorkDir(workspace);
                        setWorkspaceMenuOpen(false);
                        onSelect?.();
                      }}
                    >
                      <Folder className="h-4 w-4 shrink-0 text-neutral-400" />
                      <span className="min-w-0 flex-1 truncate text-base leading-6">
                        <span className="text-neutral-500">{parent ?? ""}</span>
                        <span className="text-neutral-700">{name}</span>
                      </span>
                    </button>
                  );
                })}
              </ScrollArea>
            ) : (
              <div className="px-2.5 py-1.5 text-base text-neutral-500">
                No matching workspace. You can still type any local path.
              </div>
            )}
            {filteredWorkspaceOptions.length > 0 ? (
              <div className="flex items-center gap-2 border-t border-neutral-100 px-2.5 py-1.5">
                <span className="inline-flex items-center gap-1.5 text-neutral-400">
                  <span className="inline-flex items-center gap-0.5">
                    <kbd className="inline-flex items-center justify-center rounded border border-neutral-200 bg-surface p-px text-neutral-500 shadow-[0_1px_0_rgba(0,0,0,0.08)]">
                      <ArrowUp className="h-2.5 w-2.5" />
                    </kbd>
                    <kbd className="inline-flex items-center justify-center rounded border border-neutral-200 bg-surface p-px text-neutral-500 shadow-[0_1px_0_rgba(0,0,0,0.08)]">
                      <ArrowDown className="h-2.5 w-2.5" />
                    </kbd>
                  </span>
                  <span className="text-sm">navigate</span>
                </span>
                <span className="text-neutral-300">·</span>
                <span className="inline-flex items-center gap-1.5 text-neutral-400">
                  <kbd className="inline-flex items-center justify-center rounded border border-neutral-200 bg-surface p-px text-neutral-500 shadow-[0_1px_0_rgba(0,0,0,0.08)]">
                    <CornerDownLeft className="h-2.5 w-2.5" />
                  </kbd>
                  <span className="text-sm">select</span>
                </span>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
