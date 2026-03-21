import type { TaskMetadataAgent, TaskMetadataItem } from "../../types/message";
import { formatCompactNumber, formatElapsed } from "./message-list-ui";

interface TaskMetadataProps {
  item: TaskMetadataItem;
}

function formatCurrency(value: number, currency: string): string {
  const symbol = currency === "CNY" ? "\u00a5" : "$";
  return `${symbol}${value.toFixed(4)}`;
}

function buildAgentParts(agent: TaskMetadataAgent): string[] {
  const parts: string[] = [];
  const usage = agent.usage;

  if (usage) {
    const inputTokens = Math.max(
      usage.inputTokens - usage.cachedTokens - usage.cacheWriteTokens,
      0,
    );
    const outputTokens = Math.max(usage.outputTokens - usage.reasoningTokens, 0);

    parts.push(`in ${formatCompactNumber(inputTokens)}`);
    if (usage.cachedTokens > 0) {
      let cacheText = `cache ${formatCompactNumber(usage.cachedTokens)}`;
      if (usage.cacheHitRate !== null) {
        cacheText += ` (${Math.round(usage.cacheHitRate * 100)}%)`;
      }
      parts.push(cacheText);
    }
    if (usage.cacheWriteTokens > 0) {
      parts.push(`cache write ${formatCompactNumber(usage.cacheWriteTokens)}`);
    }
    parts.push(`out ${formatCompactNumber(outputTokens)}`);
    if (usage.reasoningTokens > 0) {
      parts.push(`thought ${formatCompactNumber(usage.reasoningTokens)}`);
    }
    if (usage.contextPercent !== null) {
      parts.push(`ctx ${usage.contextPercent.toFixed(1)}%`);
    }
    if (usage.totalCost !== null) {
      parts.push(`cost ${formatCurrency(usage.totalCost, usage.currency)}`);
    }
  }

  if (agent.durationSeconds !== null) {
    parts.push(formatElapsed(agent.durationSeconds));
  }
  if (usage?.throughputTps !== null && usage?.throughputTps !== undefined) {
    parts.push(`${usage.throughputTps.toFixed(1)} tok/s`);
  }
  if (agent.turnCount > 0) {
    const suffix = agent.turnCount === 1 ? "step" : "steps";
    parts.push(`${agent.turnCount} ${suffix}`);
  }

  return parts;
}

function AgentLine({ agent }: { agent: TaskMetadataAgent }): JSX.Element {
  let identity = agent.modelName;
  if (agent.provider) {
    const subProvider = agent.provider.includes("/")
      ? agent.provider.split("/").pop()!
      : agent.provider;
    identity += ` via ${subProvider}`;
  }
  if (agent.subAgentName) {
    identity = `${agent.subAgentName} ${identity}`;
  }

  const parts = buildAgentParts(agent);

  return (
    <div className="font-mono text-sm leading-relaxed text-neutral-400">
      <span>{identity}</span>
      {parts.length > 0 ? (
        <>
          <br />
          <span>{parts.join(" \u00b7 ")}</span>
        </>
      ) : null}
    </div>
  );
}

export function TaskMetadata({ item }: TaskMetadataProps): JSX.Element {
  return (
    <div className="space-y-1">
      <AgentLine agent={item.mainAgent} />
      {item.subAgents.map((agent, i) => (
        <div key={agent.subAgentName ?? i} className="ml-4 border-l border-neutral-200 pl-3">
          <AgentLine agent={agent} />
        </div>
      ))}
    </div>
  );
}
