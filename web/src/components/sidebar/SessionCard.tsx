import { Loader2 } from "lucide-react";
import type { SessionRuntimeState, SessionSummary } from "../../types/session";

interface SessionCardProps {
  session: SessionSummary;
  active: boolean;
  runtime: SessionRuntimeState;
  onClick: () => void;
}

function getSessionTitle(session: SessionSummary): string {
  const firstMessage = session.user_messages[0]?.trim();
  if (firstMessage !== undefined && firstMessage.length > 0) {
    return firstMessage;
  }
  return "新会话";
}

function getSessionExcerpt(session: SessionSummary): string {
  if (session.user_messages.length > 1) {
    return session.user_messages[session.user_messages.length - 1] ?? "已恢复会话";
  }
  if (session.messages_count > 1) {
    return `包含 ${session.messages_count} 条消息`;
  }
  return session.model_name ? `模型: ${session.model_name}` : "草稿会话";
}

function formatRelativeTime(timestampSeconds: number): string {
  const deltaSeconds = Math.max(0, Math.floor(Date.now() / 1000 - timestampSeconds));
  if (deltaSeconds < 60) {
    return "刚刚";
  }
  if (deltaSeconds < 3600) {
    return `${Math.floor(deltaSeconds / 60)} 分钟`;
  }
  if (deltaSeconds < 86400) {
    return `${Math.floor(deltaSeconds / 3600)} 小时`;
  }
  if (deltaSeconds < 604800) {
    return `${Math.floor(deltaSeconds / 86400)} 天`;
  }
  if (deltaSeconds < 2592000) {
    return `${Math.floor(deltaSeconds / 604800)} 周`;
  }
  return `${Math.floor(deltaSeconds / 2592000)} 个月`;
}

export function SessionCard({ session, active, runtime, onClick }: SessionCardProps): JSX.Element {
  const title = getSessionTitle(session);
  const updatedAt = formatRelativeTime(session.updated_at);

  return (
    <button
      className={`w-full flex items-center justify-between gap-3 px-2 py-[6px] rounded-md text-left transition-colors ${
        active ? "bg-zinc-200/60" : "hover:bg-zinc-100/80"
      }`}
      type="button"
      onClick={onClick}
      title={title}
    >
      <span className="text-[14px] text-zinc-700 font-normal truncate flex-1 pl-6">
        {title}
      </span>
      <span className="text-[13px] text-zinc-400 flex items-center gap-1.5 shrink-0">
        {runtime.sessionState !== "idle" && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
        {updatedAt}
      </span>
    </button>
  );
}
