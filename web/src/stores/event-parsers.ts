import type {
  DeveloperUIItem,
  MessageImagePart,
  TaskMetadataAgent,
  TaskMetadataUsage,
} from "../types/message";

const DEFAULT_MAX_TOKENS = 32000;

export function parseFiniteNumber(raw: unknown): number | null {
  return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
}

export function parseUserMessageImages(raw: unknown): MessageImagePart[] {
  if (!Array.isArray(raw)) return [];
  const images: MessageImagePart[] = [];
  for (const item of raw) {
    if (typeof item !== "object" || item === null) continue;
    const part = item as Record<string, unknown>;
    if (part.type === "image_url" && typeof part.url === "string") {
      images.push({ type: "image_url", url: part.url });
      continue;
    }
    if (part.type === "image_file" && typeof part.file_path === "string") {
      images.push({ type: "image_file", file_path: part.file_path });
    }
  }
  return images;
}

export function parseTaskMetadataUsage(raw: unknown): TaskMetadataUsage | null {
  if (raw === null || typeof raw !== "object") return null;
  const u = raw as Record<string, unknown>;
  const inputTokens = parseFiniteNumber(u.input_tokens) ?? 0;
  const cachedTokens = parseFiniteNumber(u.cached_tokens) ?? 0;
  const cacheWriteTokens = parseFiniteNumber(u.cache_write_tokens) ?? 0;
  const outputTokens = parseFiniteNumber(u.output_tokens) ?? 0;
  const reasoningTokens = parseFiniteNumber(u.reasoning_tokens) ?? 0;
  const inputCost = parseFiniteNumber(u.input_cost);
  const outputCost = parseFiniteNumber(u.output_cost);
  const cacheReadCost = parseFiniteNumber(u.cache_read_cost);
  const costs = [inputCost, outputCost, cacheReadCost].filter((c) => c !== null) as number[];
  const totalCost = costs.length > 0 ? costs.reduce((a, b) => a + b, 0) : null;
  return {
    inputTokens,
    cachedTokens,
    cacheWriteTokens,
    outputTokens,
    reasoningTokens,
    totalCost,
    currency: typeof u.currency === "string" ? u.currency : "USD",
    contextPercent: parseFiniteNumber(u.context_usage_percent),
    throughputTps: parseFiniteNumber(u.throughput_tps),
    cacheHitRate: parseFiniteNumber(u.cache_hit_rate),
  };
}

export function parseTaskMetadataAgent(raw: Record<string, unknown>): TaskMetadataAgent {
  return {
    modelName: typeof raw.model_name === "string" ? raw.model_name : "",
    provider: typeof raw.provider === "string" ? raw.provider : null,
    subAgentName: typeof raw.sub_agent_name === "string" ? raw.sub_agent_name : null,
    usage: parseTaskMetadataUsage(raw.usage),
    durationSeconds: parseFiniteNumber(raw.task_duration_s),
    turnCount: Math.max(0, Math.floor(parseFiniteNumber(raw.turn_count) ?? 0)),
  };
}

export function parseSubAgents(raw: unknown): TaskMetadataAgent[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((item) => item !== null && typeof item === "object")
    .map((item) => parseTaskMetadataAgent(item as Record<string, unknown>));
}

function parseStringArray(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter((v): v is string => typeof v === "string");
}

export function parseDeveloperUIItems(raw: unknown): DeveloperUIItem[] {
  if (raw === null || typeof raw !== "object") return [];
  const extra = raw as Record<string, unknown>;
  if (!Array.isArray(extra.items)) return [];

  const out: DeveloperUIItem[] = [];
  for (const item of extra.items) {
    if (item === null || typeof item !== "object") continue;
    const ui = item as Record<string, unknown>;
    const t = ui.type;
    if (typeof t !== "string") continue;

    switch (t) {
      case "memory_loaded": {
        if (!Array.isArray(ui.files)) break;
        const files = ui.files
          .filter((f): f is Record<string, unknown> => f !== null && typeof f === "object")
          .map((f) => ({
            path: typeof f.path === "string" ? f.path : "",
            mentioned_patterns: parseStringArray(f.mentioned_patterns),
          }))
          .filter((f) => f.path.length > 0);
        if (files.length === 0) break;
        out.push({ type: "memory_loaded", files });
        break;
      }
      case "external_file_changes": {
        const paths = parseStringArray(ui.paths).filter((p) => p.length > 0);
        if (paths.length === 0) break;
        out.push({ type: "external_file_changes", paths });
        break;
      }
      case "todo_reminder": {
        const reason = ui.reason;
        if (reason !== "empty" && reason !== "not_used_recently") break;
        out.push({ type: "todo_reminder", reason });
        break;
      }
      case "at_file_ops": {
        if (!Array.isArray(ui.ops)) break;
        const ops = ui.ops
          .filter((o): o is Record<string, unknown> => o !== null && typeof o === "object")
          .map((o) => ({
            operation: o.operation === "Read" || o.operation === "List" ? o.operation : null,
            path: typeof o.path === "string" ? o.path : "",
            mentioned_in: typeof o.mentioned_in === "string" ? o.mentioned_in : null,
          }))
          .filter(
            (o): o is { operation: "Read" | "List"; path: string; mentioned_in: string | null } =>
              o.operation !== null && o.path.length > 0,
          );
        if (ops.length === 0) break;
        out.push({ type: "at_file_ops", ops });
        break;
      }
      case "user_images": {
        const count = typeof ui.count === "number" ? ui.count : 0;
        const paths = parseStringArray(ui.paths).filter((p) => p.length > 0);
        out.push({ type: "user_images", count, paths });
        break;
      }
      case "skill_activated": {
        const name = typeof ui.name === "string" ? ui.name : "";
        if (name.length === 0) break;
        out.push({ type: "skill_activated", name });
        break;
      }
      case "at_file_images": {
        const paths = parseStringArray(ui.paths).filter((p) => p.length > 0);
        if (paths.length === 0) break;
        out.push({ type: "at_file_images", paths });
        break;
      }
      default:
        break;
    }
  }

  return out;
}

export function parseCompactionSummary(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const text = raw.trim();
  if (text.length === 0) return null;
  const match = text.match(/<summary>([\s\S]*?)<\/summary>/);
  if (!match) return text;
  const inner = match[1]?.trim() ?? "";
  return inner.length > 0 ? inner : text;
}

export { DEFAULT_MAX_TOKENS };
