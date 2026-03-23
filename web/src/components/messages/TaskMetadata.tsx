import { useState } from "react";

import { useT } from "@/i18n";
import type { TaskMetadataAgent, TaskMetadataItem } from "../../types/message";
import {
  COLLAPSE_RAIL_GRID_CLASS_NAME,
  CollapseRailMarker,
  CollapseRailPanel,
} from "./CollapseRail";
import { formatCompactNumber, formatElapsed } from "./message-list-ui";

interface TaskMetadataProps {
  item: TaskMetadataItem;
}

function formatCurrency(value: number, currency: string): string {
  const symbol = currency === "CNY" ? "\u00a5" : "$";
  return `${symbol}${value.toFixed(4)}`;
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
      rows.push({
        label: t("taskMeta.cacheWrite"),
        value: formatCompactNumber(usage.cacheWriteTokens),
      });
    }

    rows.push({ label: t("taskMeta.outputTokens"), value: formatCompactNumber(outputTokens) });

    if (usage.reasoningTokens > 0) {
      rows.push({
        label: t("taskMeta.reasoning"),
        value: formatCompactNumber(usage.reasoningTokens),
      });
    }
    if (usage.contextPercent !== null) {
      let ctx = `${usage.contextPercent.toFixed(1)}%`;
      if (usage.contextSize !== null && usage.contextEffectiveLimit !== null) {
        ctx = `${formatCompactNumber(usage.contextSize)}/${formatCompactNumber(usage.contextEffectiveLimit)} (${usage.contextPercent.toFixed(1)}%)`;
      }
      rows.push({ label: t("taskMeta.context"), value: ctx });
    }
    if (usage.totalCost !== null) {
      rows.push({
        label: t("taskMeta.cost"),
        value: formatCurrency(usage.totalCost, usage.currency),
      });
    }
  }

  if (agent.durationSeconds !== null) {
    rows.push({ label: t("taskMeta.duration"), value: formatElapsed(agent.durationSeconds) });
  }
  if (usage?.throughputTps !== null && usage?.throughputTps !== undefined) {
    rows.push({
      label: t("taskMeta.throughput"),
      value: `${usage.throughputTps.toFixed(1)} tok/s`,
    });
  }
  if (agent.turnCount > 0) {
    rows.push({
      label: t("taskMeta.stepsLabel"),
      value: t("taskMeta.stepsValue")(agent.turnCount),
    });
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
          <span className="w-28 shrink-0 py-1.5 text-right font-sans text-neutral-500">
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
  const agent = item.mainAgent;
  const modelLabel = agent.subAgentName
    ? `${agent.subAgentName} ${agent.modelName}`
    : agent.modelName;

  return (
    <div
      className={`transition-opacity duration-200 ${open ? "opacity-100" : "opacity-0 group-hover/section:opacity-100"}`}
    >
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v);
        }}
        className={`grid w-full cursor-pointer ${COLLAPSE_RAIL_GRID_CLASS_NAME} items-start text-left text-sm leading-relaxed text-neutral-500 transition-colors hover:text-neutral-600`}
      >
        <CollapseRailMarker open={open} />
        <span className="min-w-0 truncate">
          {modelLabel}
          {agent.durationSeconds !== null && (
            <>
              <span className="mx-1.5 text-neutral-400">{"\u00b7"}</span>
              {formatElapsed(agent.durationSeconds)}
            </>
          )}
        </span>
      </button>
      <CollapseRailPanel open={open}>
        <DetailTable rows={buildDetailRows(item.mainAgent, t)} />
      </CollapseRailPanel>
    </div>
  );
}
