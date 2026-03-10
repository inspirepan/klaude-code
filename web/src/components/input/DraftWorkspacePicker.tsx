import type { Dispatch, RefObject, SetStateAction } from "react";
import { ChevronDown, Folder } from "lucide-react";

interface DraftWorkspacePickerProps {
  draftWorkDir: string;
  normalizedDraftWorkDir: string;
  workspaceMenuOpen: boolean;
  filteredWorkspaceOptions: string[];
  workspacePickerRef: RefObject<HTMLDivElement>;
  setDraftWorkDir: (workDir: string) => void;
  setWorkspaceMenuOpen: Dispatch<SetStateAction<boolean>>;
}

function workDirLabel(workDir: string): string {
  const parts = workDir.split("/").filter((segment) => segment.length > 0);
  return parts[parts.length - 1] ?? workDir;
}

export function DraftWorkspacePicker({
  draftWorkDir,
  normalizedDraftWorkDir,
  workspaceMenuOpen,
  filteredWorkspaceOptions,
  workspacePickerRef,
  setDraftWorkDir,
  setWorkspaceMenuOpen,
}: DraftWorkspacePickerProps): JSX.Element {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-3">
        <label htmlFor="draft-workspace" className="text-xs font-semibold text-neutral-600">
          Workspace
        </label>
        <span className="text-2xs text-neutral-400">Choose or type a local path</span>
      </div>
      <div ref={workspacePickerRef} className="relative">
        <div
          className={[
            "flex items-center rounded-2xl border bg-white/95 shadow-sm transition-all",
            workspaceMenuOpen
              ? "border-neutral-300 shadow-[0_10px_30px_rgba(0,0,0,0.08)]"
              : "border-neutral-200 hover:border-neutral-300 hover:bg-white",
          ].join(" ")}
        >
          <div className="pl-3 text-neutral-400">
            <Folder className="h-4 w-4" />
          </div>
          <input
            id="draft-workspace"
            value={draftWorkDir}
            onFocus={() => {
              setWorkspaceMenuOpen(true);
            }}
            onChange={(event) => {
              setDraftWorkDir(event.target.value);
              setWorkspaceMenuOpen(true);
            }}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setWorkspaceMenuOpen(false);
              }
            }}
            placeholder="/path/to/workspace"
            className="w-full flex-1 border-0 bg-transparent px-2 py-3 text-[13px] text-neutral-700 outline-none placeholder:text-neutral-400"
          />
          <button
            type="button"
            className="mr-1 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-700"
            onClick={() => {
              setWorkspaceMenuOpen((prev) => !prev);
            }}
            aria-label="Toggle workspace suggestions"
          >
            <ChevronDown
              className={[
                "h-4 w-4 transition-transform duration-150",
                workspaceMenuOpen ? "rotate-180" : "rotate-0",
              ].join(" ")}
            />
          </button>
        </div>

        {workspaceMenuOpen ? (
          <div className="absolute left-0 right-0 z-20 mt-2 overflow-hidden rounded-2xl border border-neutral-200 bg-white/95 p-1.5 shadow-[0_16px_40px_rgba(0,0,0,0.12)] backdrop-blur">
            <div className="px-2.5 pb-1 pt-1 text-2xs font-medium uppercase tracking-[0.08em] text-neutral-400">
              Recent workspaces
            </div>
            {filteredWorkspaceOptions.length > 0 ? (
              <div className="max-h-64 space-y-0.5 overflow-y-auto">
                {filteredWorkspaceOptions.map((workspace) => {
                  const isSelected = workspace === normalizedDraftWorkDir;
                  return (
                    <button
                      key={workspace}
                      type="button"
                      className={[
                        "flex w-full items-start gap-3 rounded-xl px-3 py-2.5 text-left transition-colors",
                        isSelected
                          ? "bg-neutral-100 text-neutral-900"
                          : "text-neutral-700 hover:bg-neutral-50",
                      ].join(" ")}
                      onMouseDown={(event) => {
                        event.preventDefault();
                      }}
                      onClick={() => {
                        setDraftWorkDir(workspace);
                        setWorkspaceMenuOpen(false);
                      }}
                    >
                      <Folder className="mt-0.5 h-4 w-4 shrink-0 text-neutral-400" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[13px] font-medium leading-5 text-neutral-800">
                          {workDirLabel(workspace)}
                        </div>
                        <div className="truncate text-2xs leading-4 text-neutral-400">
                          {workspace}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="px-3 py-3 text-xs text-neutral-400">
                No matching workspace. You can still type any local path.
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
