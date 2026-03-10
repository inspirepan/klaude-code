import { Lock, PanelLeftOpen, PanelRightOpen } from "lucide-react";

interface MessageListHeaderProps {
  primaryTitle: string;
  secondaryTitle: string | null;
  workspacePath: string;
  sessionReadOnly: boolean;
  sidebarOpen: boolean;
  rightSidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  setRightSidebarOpen: (open: boolean) => void;
}

export function MessageListHeader({
  primaryTitle,
  secondaryTitle,
  workspacePath,
  sessionReadOnly,
  sidebarOpen,
  rightSidebarOpen,
  setSidebarOpen,
  setRightSidebarOpen,
}: MessageListHeaderProps): JSX.Element {
  return (
    <div className="relative z-20 flex shrink-0 flex-wrap items-center gap-3 border-b border-neutral-200/80 bg-white/95 px-4 py-2 backdrop-blur sm:px-6">
      {!sidebarOpen ? (
        <button
          type="button"
          className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
          onClick={() => {
            setSidebarOpen(true);
          }}
          title="Expand sidebar"
          aria-label="Expand sidebar"
        >
          <PanelLeftOpen className="h-4 w-4" />
        </button>
      ) : null}
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-baseline gap-2 text-sm leading-5">
          <span className="truncate font-semibold text-neutral-800" title={primaryTitle}>
            {primaryTitle}
          </span>
          {secondaryTitle ? (
            <span className="truncate text-neutral-500" title={secondaryTitle}>
              {secondaryTitle}
            </span>
          ) : null}
          {sessionReadOnly ? (
            <span className="group/readonly relative inline-flex shrink-0 cursor-help items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-2xs font-medium text-amber-700">
              <Lock className="h-3 w-3" />
              <span>Read-only</span>
              <span className="pointer-events-none absolute left-1/2 top-full z-30 mt-1 hidden w-max max-w-[30rem] -translate-x-1/2 rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] leading-4 text-amber-800 shadow-sm group-hover/readonly:block">
                This session is owned by another live runtime. Web can observe it, but cannot send
                control actions.
              </span>
            </span>
          ) : null}
          {workspacePath ? (
            <span
              className="truncate font-sans text-sm leading-5 text-neutral-400"
              title={workspacePath}
            >
              {workspacePath}
            </span>
          ) : null}
        </div>
      </div>
      <div className="h-8 w-8 shrink-0" aria-hidden="true" />
      {!rightSidebarOpen ? (
        <button
          type="button"
          className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
          onClick={() => {
            setRightSidebarOpen(true);
          }}
          title="Expand right sidebar"
          aria-label="Expand right sidebar"
        >
          <PanelRightOpen className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  );
}
