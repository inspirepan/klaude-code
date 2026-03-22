import {
  ArrowLeft,
  ChevronsDownUp,
  ChevronsUpDown,
  Lock,
  PanelLeftOpen,
  Search,
} from "lucide-react";
import { SessionTitleText } from "@/components/SessionTitleText";
import { useT } from "@/i18n";
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
  onBack?: () => void;
  subAgentLabel?: string | null;
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
  onBack,
  subAgentLabel,
}: MessageListHeaderProps): JSX.Element {
  const t = useT();
  const isSubAgentView = onBack !== undefined;

  return (
    <div className="relative z-20 shrink-0">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-full h-3 bg-gradient-to-b from-background to-transparent"
      />
      <div className="bg-background backdrop-blur-sm">
        <div className="flex flex-wrap items-center gap-1.5 px-3 pb-1 pt-2.5 sm:px-4">
          {isSubAgentView ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className="inline-flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-md text-neutral-500 transition-colors hover:bg-muted hover:text-neutral-700"
                  onClick={onBack}
                  aria-label={t("header.backToMain")}
                >
                  <ArrowLeft className="h-4 w-4" />
                </button>
              </TooltipTrigger>
              <TooltipContent>{t("header.backToMain")}</TooltipContent>
            </Tooltip>
          ) : !sidebarOpen ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className="inline-flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-md text-neutral-500 transition-colors hover:bg-muted hover:text-neutral-700"
                  onClick={() => {
                    setSidebarOpen(true);
                  }}
                  aria-label={t("sidebar.expandSidebar")}
                >
                  <PanelLeftOpen className="h-4 w-4" />
                </button>
              </TooltipTrigger>
              <TooltipContent className="flex items-center gap-1.5">
                <span>{t("sidebar.expandSidebar")}</span>
                <span className="inline-flex items-center text-neutral-500" aria-hidden="true">
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
            <div className="flex min-w-0 items-center gap-1.5 text-base leading-5">
              {isSubAgentView ? (
                <span className="truncate font-semibold">
                  {subAgentLabel ?? t("header.subAgent")}
                </span>
              ) : (
                <>
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
                      <TooltipContent>{t("header.readOnly")}</TooltipContent>
                    </Tooltip>
                  ) : null}
                  {workspacePath ? (
                    <span
                      className="hidden truncate font-sans text-sm leading-5 text-neutral-500 sm:inline"
                      title={workspacePath}
                    >
                      {workspacePath}
                    </span>
                  ) : null}
                </>
              )}
            </div>
          </div>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="inline-flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-md text-neutral-500 transition-colors hover:bg-muted hover:text-neutral-700"
                onClick={onCollapseAll}
                aria-label={t("header.collapseAll")}
              >
                <ChevronsDownUp className="h-4 w-4" />
              </button>
            </TooltipTrigger>
            <TooltipContent className="flex items-center gap-1.5">
              <span>{t("header.collapseAll")}</span>
              <span className="inline-flex items-center text-neutral-500" aria-hidden="true">
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
                className="inline-flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-md text-neutral-500 transition-colors hover:bg-muted hover:text-neutral-700"
                onClick={onExpandAll}
                aria-label={t("header.expandAll")}
              >
                <ChevronsUpDown className="h-4 w-4" />
              </button>
            </TooltipTrigger>
            <TooltipContent className="flex items-center gap-1.5">
              <span>{t("header.expandAll")}</span>
              <span className="inline-flex items-center text-neutral-500" aria-hidden="true">
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
                className="inline-flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-md text-neutral-500 transition-colors hover:bg-muted hover:text-neutral-700"
                onClick={onSearchOpen}
                aria-label={t("header.searchMessages")}
              >
                <Search className="h-4 w-4" />
              </button>
            </TooltipTrigger>
            <TooltipContent className="flex items-center gap-1.5">
              <span>{t("header.search")}</span>
              <span className="inline-flex items-center text-neutral-500" aria-hidden="true">
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
      </div>
    </div>
  );
}
