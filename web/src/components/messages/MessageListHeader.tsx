import { ChevronsDownUp, ChevronsUpDown, Lock, PanelLeftOpen, Search } from "lucide-react";
import { SessionTitleText } from "@/components/SessionTitleText";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";

interface MessageListHeaderProps {
  primaryTitle: string;
  secondaryTitle: string | null;
  workspacePath: string;
  sessionReadOnly: boolean;
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  onSearchOpen: () => void;
  onCollapseAll: () => void;
  onExpandAll: () => void;
}

export function MessageListHeader({
  primaryTitle,
  secondaryTitle,
  workspacePath,
  sessionReadOnly,
  sidebarOpen,
  setSidebarOpen,
  onSearchOpen,
  onCollapseAll,
  onExpandAll,
}: MessageListHeaderProps): JSX.Element {
  return (
    <div className="sticky top-0 z-20 flex shrink-0 flex-wrap items-center gap-3 border-b border-neutral-200/80 bg-[#f9f9f8]/80 px-4 py-2 backdrop-blur sm:px-6">
      {!sidebarOpen ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-muted hover:text-neutral-600"
              onClick={() => {
                setSidebarOpen(true);
              }}
              aria-label="Expand sidebar"
            >
              <PanelLeftOpen className="h-4 w-4" />
            </button>
          </TooltipTrigger>
          <TooltipContent className="flex items-center gap-1.5">
            <span>Expand sidebar</span>
            <span className="inline-flex items-center text-neutral-400" aria-hidden="true">
              <span className="inline-flex whitespace-pre text-sm leading-none">
                <kbd className="inline-flex font-sans">
                  <span className="min-w-[1em] text-center">⌘</span>
                </kbd>
                <kbd className="inline-flex font-sans">
                  <span className="min-w-[1em] text-center">B</span>
                </kbd>
              </span>
            </span>
          </TooltipContent>
        </Tooltip>
      ) : null}
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2 text-base leading-5">
          <SessionTitleText
            title={secondaryTitle ? `${primaryTitle} — ${secondaryTitle}` : primaryTitle}
            as="div"
            className="flex min-w-0 items-baseline"
            primaryClassName="font-semibold"
          />
          {sessionReadOnly ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex shrink-0 cursor-help items-center self-center rounded-full border border-amber-200/70 bg-amber-50 p-1 text-amber-700">
                  <Lock className="h-3 w-3" />
                </span>
              </TooltipTrigger>
              <TooltipContent>
                Read-only — this session is owned by another live runtime
              </TooltipContent>
            </Tooltip>
          ) : null}
          {workspacePath ? (
            <span
              className="hidden truncate font-sans text-base leading-5 text-neutral-500 sm:inline"
              title={workspacePath}
            >
              {workspacePath}
            </span>
          ) : null}
        </div>
      </div>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-muted hover:text-neutral-600"
            onClick={onCollapseAll}
            aria-label="Collapse all"
          >
            <ChevronsDownUp className="h-4 w-4" />
          </button>
        </TooltipTrigger>
        <TooltipContent className="flex items-center gap-1.5">
          <span>Collapse all</span>
          <span className="inline-flex items-center text-neutral-400" aria-hidden="true">
            <span className="inline-flex whitespace-pre text-sm leading-none">
              <kbd className="inline-flex font-sans">
                <span className="min-w-[1em] text-center">⌘</span>
              </kbd>
              <kbd className="inline-flex font-sans">
                <span className="min-w-[1em] text-center">⇧</span>
              </kbd>
              <kbd className="inline-flex font-sans">
                <span className="min-w-[1em] text-center">,</span>
              </kbd>
            </span>
          </span>
        </TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-muted hover:text-neutral-600"
            onClick={onExpandAll}
            aria-label="Expand all"
          >
            <ChevronsUpDown className="h-4 w-4" />
          </button>
        </TooltipTrigger>
        <TooltipContent className="flex items-center gap-1.5">
          <span>Expand all</span>
          <span className="inline-flex items-center text-neutral-400" aria-hidden="true">
            <span className="inline-flex whitespace-pre text-sm leading-none">
              <kbd className="inline-flex font-sans">
                <span className="min-w-[1em] text-center">⌘</span>
              </kbd>
              <kbd className="inline-flex font-sans">
                <span className="min-w-[1em] text-center">⇧</span>
              </kbd>
              <kbd className="inline-flex font-sans">
                <span className="min-w-[1em] text-center">.</span>
              </kbd>
            </span>
          </span>
        </TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-muted hover:text-neutral-600"
            onClick={onSearchOpen}
            aria-label="Search messages"
          >
            <Search className="h-4 w-4" />
          </button>
        </TooltipTrigger>
        <TooltipContent className="flex items-center gap-1.5">
          <span>Search</span>
          <span className="inline-flex items-center text-neutral-400" aria-hidden="true">
            <span className="inline-flex whitespace-pre text-sm leading-none">
              <kbd className="inline-flex font-sans">
                <span className="min-w-[1em] text-center">⌘</span>
              </kbd>
              <kbd className="inline-flex font-sans">
                <span className="min-w-[1em] text-center">F</span>
              </kbd>
            </span>
          </span>
        </TooltipContent>
      </Tooltip>
    </div>
  );
}
