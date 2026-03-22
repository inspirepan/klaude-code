import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

import { t, useT } from "@/i18n";
import type { TaskMetadataAgent, TaskMetadataItem } from "../../types/message";
import { CollapseRailPanel } from "./CollapseRail";
import { formatCompactNumber, formatElapsed } from "./message-list-ui";

interface TaskMetadataProps {
  item: TaskMetadataItem;
}

function formatCurrency(value: number, currency: string): string {
  const symbol = currency === "CNY" ? "\u00a5" : "$";
  return `${symbol}${value.toFixed(4)}`;
}

// ------------------------------------------------------------------
// Summary line (collapsed view)
// ------------------------------------------------------------------

function buildSummaryText(item: TaskMetadataItem, t: ReturnType<typeof useT>): string {
  const agent = item.mainAgent;
  const duration = agent.durationSeconds;
  const turns = agent.turnCount;

  if (duration === null && turns === 0) return agentIdentity(agent, t);

  const prefix = item.isPartial ? t("taskMeta.interruptedAfter") : t("taskMeta.workedFor");
  const parts: string[] = [prefix];

  if (duration !== null) {
    parts.push(formatElapsed(duration));
  }
  if (turns > 0) {
    parts.push(t("taskMeta.steps")(turns));
  }

  return parts.join(" ");
}

function agentIdentity(agent: TaskMetadataAgent, t: ReturnType<typeof useT>): string {
  let identity = agent.modelName;
  if (agent.provider) {
    const sub = agent.provider.includes("/") ? agent.provider.split("/").pop()! : agent.provider;
    identity += ` ${t("taskMeta.via")(sub)}`;
  }
  if (agent.subAgentName) {
    identity = `${agent.subAgentName} ${identity}`;
  }
  return identity;
}

// ------------------------------------------------------------------
// Detail rows (expanded view)
// ------------------------------------------------------------------

interface DetailRow {
  label: string;
  value: string;
}

function buildDetailRows(agent: TaskMetadataAgent, t: ReturnType<typeof useT>): DetailRow[] {
  const rows: DetailRow[] = [];
  const usage = agent.usage;

  rows.push({ label: t("taskMeta.model"), value: agent.modelName });

  if (agent.provider) {
    rows.push({ label: t("taskMeta.provider"), value: agent.provider });
  }

  if (usage) {
    const inputTokens = Math.max(
      usage.inputTokens - usage.cachedTokens - usage.cacheWriteTokens,
      0,
    );
    const outputTokens = Math.max(usage.outputTokens - usage.reasoningTokens, 0);

    rows.push({ label: t("taskMeta.inputTokens"), value: formatCompactNumber(inputTokens) });

    if (usage.cachedTokens > 0) {
      let v = formatCompactNumber(usage.cachedTokens);
      if (usage.cacheHitRate !== null) {
        v += ` ${t("taskMeta.cacheHitRate")(Math.round(usage.cacheHitRate * 100))}`;
      }
      rows.push({ label: t("taskMeta.cacheRead"), value: v });
    }
    if (usage.cacheWriteTokens > 0) {
      rows.push({ label: t("taskMeta.cacheWrite"), value: formatCompactNumber(usage.cacheWriteTokens) });
    }

    rows.push({ label: t("taskMeta.outputTokens"), value: formatCompactNumber(outputTokens) });

    if (usage.reasoningTokens > 0) {
      rows.push({ label: t("taskMeta.reasoning"), value: formatCompactNumber(usage.reasoningTokens) });
    }
    if (usage.contextPercent !== null) {
      rows.push({ label: t("taskMeta.context"), value: `${usage.contextPercent.toFixed(1)}%` });
    }
    if (usage.totalCost !== null) {
      rows.push({ label: t("taskMeta.cost"), value: formatCurrency(usage.totalCost, usage.currency) });
    }
  }

  if (agent.durationSeconds !== null) {
    rows.push({ label: t("taskMeta.duration"), value: formatElapsed(agent.durationSeconds) });
  }
  if (usage?.throughputTps !== null && usage?.throughputTps !== undefined) {
    rows.push({ label: t("taskMeta.throughput"), value: `${usage.throughputTps.toFixed(1)} tok/s` });
  }
  if (agent.turnCount > 0) {
    rows.push({ label: t("taskMeta.stepsLabel"), value: t("taskMeta.stepsValue")(agent.turnCount) });
  }

  return rows;
}

// ------------------------------------------------------------------
// Detail table
// ------------------------------------------------------------------

function DetailTable({ rows }: { rows: DetailRow[] }): JSX.Element {
  return (
    <div className="ml-5 mt-1">
      {rows.map((row, i) => (
        <div key={row.label} className="flex items-baseline gap-2 text-sm">
          <span className="w-24 shrink-0 py-1.5 text-right font-sans text-neutral-500">
            {row.label}
          </span>
          <span
            className={`flex-1 py-1.5 font-mono text-neutral-600 ${i < rows.length - 1 ? "border-b border-neutral-100" : ""}`}
          >
            {row.value}
          </span>
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------
// Export
// ------------------------------------------------------------------

export function TaskMetadata({ item }: TaskMetadataProps): JSX.Element {
  const t = useT();
  const [open, setOpen] = useState(false);
  const summaryText = buildSummaryText(item, t);

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`flex w-full cursor-pointer items-center gap-1 text-left font-mono text-base leading-relaxed transition-colors ${
          item.isPartial
            ? "text-amber-600 hover:text-amber-700"
            : "text-emerald-700 hover:text-emerald-800"
        }`}
      >
        <span className="min-w-0 truncate">{summaryText}</span>
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0" />
        )}
      </button>
      <CollapseRailPanel open={open}>
        <DetailTable rows={buildDetailRows(item.mainAgent, t)} />
      </CollapseRailPanel>
    </div>
  );
}
