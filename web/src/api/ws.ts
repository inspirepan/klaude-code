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

export interface SessionListWsEvent {
  type: "session.upsert" | "session.deleted";
  session_id: string;
  session?: Record<string, unknown> | null;
}

export interface SessionListWsHandlers {
  onOpen?: () => void;
  onClose?: () => void;
  onEvent?: (event: SessionListWsEvent) => void;
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

function isSessionListEvent(payload: unknown): payload is SessionListWsEvent {
  if (typeof payload !== "object" || payload === null) {
    return false;
  }
  const record = payload as Record<string, unknown>;
  return (
    (record.type === "session.upsert" || record.type === "session.deleted") &&
    typeof record.session_id === "string"
  );
}

export function connectSessionWs(
  sessionId: string,
  handlers: SessionWsHandlers,
): SessionWsConnection {
  const wsUrl = `${resolveWsBaseUrl()}/api/sessions/${encodeURIComponent(sessionId)}/ws`;
  const socket = new WebSocket(wsUrl);
  const pendingFrames: string[] = [];

  function flushPendingFrames(): void {
    if (socket.readyState !== WebSocket.OPEN || pendingFrames.length === 0) {
      return;
    }
    for (const frame of pendingFrames) {
      socket.send(frame);
    }
    pendingFrames.length = 0;
  }

  socket.addEventListener("open", () => {
    flushPendingFrames();
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
      const frame = JSON.stringify(payload);
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(frame);
        return;
      }
      if (socket.readyState === WebSocket.CONNECTING) {
        pendingFrames.push(frame);
      }
    },
    close: () => {
      pendingFrames.length = 0;
      socket.close();
    },
  };
}

export function connectSessionListWs(handlers: SessionListWsHandlers): SessionWsConnection {
  const wsUrl = `${resolveWsBaseUrl()}/api/sessions/ws`;
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
      if (isSessionListEvent(payload)) {
        handlers.onEvent?.(payload);
      }
    } catch {
      // Ignore malformed frames.
    }
  });

  return {
    send: () => {},
    close: () => {
      socket.close();
    },
  };
}
