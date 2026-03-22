import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

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

function buildSummaryText(item: TaskMetadataItem): string {
  const agent = item.mainAgent;
  const duration = agent.durationSeconds;
  const turns = agent.turnCount;

  if (duration === null && turns === 0) return agentIdentity(agent);

  const prefix = item.isPartial ? "Interrupted after" : "Worked for";
  const parts: string[] = [prefix];

  if (duration !== null) {
    parts.push(formatElapsed(duration));
  }
  if (turns > 0) {
    const suffix = turns === 1 ? "step" : "steps";
    parts.push(`in ${turns} ${suffix}`);
  }

  return parts.join(" ");
}

function agentIdentity(agent: TaskMetadataAgent): string {
  let identity = agent.modelName;
  if (agent.provider) {
    const sub = agent.provider.includes("/") ? agent.provider.split("/").pop()! : agent.provider;
    identity += ` via ${sub}`;
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

function buildDetailRows(agent: TaskMetadataAgent): DetailRow[] {
  const rows: DetailRow[] = [];
  const usage = agent.usage;

  rows.push({ label: "Model", value: agent.modelName });

  if (agent.provider) {
    rows.push({ label: "Provider", value: agent.provider });
  }

  if (usage) {
    const inputTokens = Math.max(
      usage.inputTokens - usage.cachedTokens - usage.cacheWriteTokens,
      0,
    );
    const outputTokens = Math.max(usage.outputTokens - usage.reasoningTokens, 0);

    rows.push({ label: "Input tokens", value: formatCompactNumber(inputTokens) });

    if (usage.cachedTokens > 0) {
      let v = formatCompactNumber(usage.cachedTokens);
      if (usage.cacheHitRate !== null) {
        v += ` (${Math.round(usage.cacheHitRate * 100)}% hit)`;
      }
      rows.push({ label: "Cache read", value: v });
    }
    if (usage.cacheWriteTokens > 0) {
      rows.push({ label: "Cache write", value: formatCompactNumber(usage.cacheWriteTokens) });
    }

    rows.push({ label: "Output tokens", value: formatCompactNumber(outputTokens) });

    if (usage.reasoningTokens > 0) {
      rows.push({ label: "Reasoning", value: formatCompactNumber(usage.reasoningTokens) });
    }
    if (usage.contextPercent !== null) {
      rows.push({ label: "Context", value: `${usage.contextPercent.toFixed(1)}%` });
    }
    if (usage.totalCost !== null) {
      rows.push({ label: "Cost", value: formatCurrency(usage.totalCost, usage.currency) });
    }
  }

  if (agent.durationSeconds !== null) {
    rows.push({ label: "Duration", value: formatElapsed(agent.durationSeconds) });
  }
  if (usage?.throughputTps !== null && usage?.throughputTps !== undefined) {
    rows.push({ label: "Throughput", value: `${usage.throughputTps.toFixed(1)} tok/s` });
  }
  if (agent.turnCount > 0) {
    const suffix = agent.turnCount === 1 ? "step" : "steps";
    rows.push({ label: "Steps", value: `${agent.turnCount} ${suffix}` });
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
  const [open, setOpen] = useState(false);
  const summaryText = buildSummaryText(item);

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
        <DetailTable rows={buildDetailRows(item.mainAgent)} />
      </CollapseRailPanel>
    </div>
  );
}
