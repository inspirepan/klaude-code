export interface WsEventEnvelope {
  event_type: string;
  session_id: string;
  event?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface WsErrorFrame {
  type: "error";
  code: string;
  message: string;
  detail?: unknown;
}

export interface SessionWsHandlers {
  onOpen?: () => void;
  onClose?: () => void;
  onEvent?: (event: WsEventEnvelope) => void;
  onErrorFrame?: (errorFrame: WsErrorFrame) => void;
}

export interface SessionWsConnection {
  send: (payload: unknown) => void;
  close: () => void;
}

function resolveWsBaseUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}`;
}

function isErrorFrame(payload: unknown): payload is WsErrorFrame {
  if (typeof payload !== "object" || payload === null) {
    return false;
  }
  const record = payload as Record<string, unknown>;
  return (
    record.type === "error" && typeof record.code === "string" && typeof record.message === "string"
  );
}

function isEventEnvelope(payload: unknown): payload is WsEventEnvelope {
  if (typeof payload !== "object" || payload === null) {
    return false;
  }
  const record = payload as Record<string, unknown>;
  return typeof record.event_type === "string" && typeof record.session_id === "string";
}

export function connectSessionWs(
  sessionId: string,
  handlers: SessionWsHandlers,
): SessionWsConnection {
  const wsUrl = `${resolveWsBaseUrl()}/api/sessions/${encodeURIComponent(sessionId)}/ws`;
  const socket = new WebSocket(wsUrl);

  socket.addEventListener("open", () => {
    handlers.onOpen?.();
  });

  socket.addEventListener("close", () => {
    handlers.onClose?.();
  });

  socket.addEventListener("message", (messageEvent) => {
    try {
      const payload = JSON.parse(messageEvent.data as string) as unknown;
      if (isErrorFrame(payload)) {
        handlers.onErrorFrame?.(payload);
        return;
      }
      if (isEventEnvelope(payload)) {
        handlers.onEvent?.(payload);
      }
    } catch {
      // Ignore malformed frames, backend already reports invalid JSON via error frames.
    }
  });

  return {
    send: (payload: unknown) => {
      socket.send(JSON.stringify(payload));
    },
    close: () => {
      socket.close();
    },
  };
}
