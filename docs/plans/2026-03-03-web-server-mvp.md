# Web Server MVP Implementation Plan

> **For Claude:** Use the executing-plans skill to implement this plan task-by-task.

**Goal:** Add a `klaude web` command that starts a FastAPI server exposing the core runtime via REST + SSE, with a React frontend for multi-session chat.

**Architecture:** Reuse the existing port-and-adapter architecture. Create `WebDisplay(DisplayABC)` and `WebInteractionHandler(InteractionHandlerABC)` adapters that bridge events to SSE streams and HTTP responses. The frontend is a Vite + React SPA in `web/`, proxied during dev and embedded via StaticFiles in production.

**Tech Stack:** Python: FastAPI, uvicorn, sse-starlette. Frontend: React, TypeScript, Vite, Tailwind CSS, shadcn/ui, Zustand, streamdown, @pierre/diffs, @uiw/react-json-view. Fonts: Inter, TX-02.

**Design Docs:**
- `docs/web/1-execution-architecture.md`
- `docs/web/2-frontend-and-api-design.md`
- `docs/web/3-style-guide.md`

---

## Phase 1: Backend Foundation

### Task 1: Add web dependencies to pyproject.toml

**Files:**
- Modify: `pyproject.toml`

**Intent:** Add FastAPI, uvicorn, and sse-starlette as optional dependencies under a `[project.optional-dependencies] web` group, so they don't bloat the base CLI install.

**Steps:**
1. Add `[project.optional-dependencies]` section with `web = ["fastapi>=0.115", "uvicorn[standard]>=0.34", "sse-starlette>=2.0"]`
2. Verify: `uv sync --extra web`
3. Commit: `feat(web): add optional web dependencies`

**Acceptance criteria:**
- `uv sync --extra web` installs fastapi, uvicorn, sse-starlette without errors
- `uv sync` (without extra) does NOT install them
- Existing `klaude` command still works

---

### Task 2: Create web module skeleton with WebDisplay and WebInteractionHandler

**Files:**
- Create: `src/klaude_code/web/__init__.py`
- Create: `src/klaude_code/web/display.py`
- Create: `src/klaude_code/web/interaction.py`
- Test: `tests/test_web_display.py`

**Intent:** Implement the two port adapters that bridge the core runtime to the web layer. `WebDisplay` collects event envelopes and fans them out to SSE subscribers. `WebInteractionHandler` uses asyncio Futures to bridge interaction requests from the core to HTTP POST responses.

**Steps:**
1. Write a test for `WebDisplay`: construct it, call `consume_envelope` with a few events, verify they appear in a subscriber queue.
2. Implement `WebDisplay(DisplayABC)`:
   - `start()` / `stop()`: no-ops (web server lifecycle is managed externally)
   - `consume_envelope()`: serialize the event envelope to JSON and push to all registered SSE subscriber queues
   - `subscribe(session_id) -> AsyncIterator`: create a per-client asyncio.Queue, yield serialized events, filtered by session_id
   - Track a monotonic `event_seq` counter for SSE `id` field
3. Write a test for `WebInteractionHandler`: post a request event, verify it's held in a pending dict, resolve it via `resolve_interaction()`, verify `collect_response` returns.
4. Implement `WebInteractionHandler(InteractionHandlerABC)`:
   - `collect_response(event)`: store an `asyncio.Future` keyed by `request_id`, await it
   - `resolve_interaction(request_id, response)`: resolve the corresponding Future
   - `get_pending_interactions()`: return list of pending request_ids (for the REST endpoint)
5. Verify: `pytest tests/test_web_display.py tests/test_web_interaction.py -v`
6. Commit: `feat(web): add WebDisplay and WebInteractionHandler adapters`

**Acceptance criteria:**
- WebDisplay fans out events to multiple subscribers concurrently
- WebDisplay filters events by session_id when requested
- WebInteractionHandler correctly bridges async request/response across coroutines
- Subscriber cleanup on disconnect (queue removed from set)

**Notes:**
- Reference `src/klaude_code/app/ports/display.py` for `DisplayABC` interface
- Reference `src/klaude_code/app/ports/interaction.py` for `InteractionHandlerABC` interface
- Event serialization: use Pydantic's `.model_dump(mode="json")` on the event, wrap in `{"type": event.type, "session_id": envelope.session_id, "seq": N, "data": ...}`

---

### Task 3: Create the FastAPI application with core endpoints

**Files:**
- Create: `src/klaude_code/web/app.py`
- Create: `src/klaude_code/web/routes/__init__.py`
- Create: `src/klaude_code/web/routes/sessions.py`
- Create: `src/klaude_code/web/routes/events.py`
- Create: `src/klaude_code/web/routes/files.py`
- Test: `tests/test_web_app.py`

**Intent:** Wire up the FastAPI app with the MVP API endpoints defined in the design doc (section 2). The app holds references to `RuntimeFacade`, `WebDisplay`, and `WebInteractionHandler`.

**Steps:**
1. Write integration tests using `httpx.AsyncClient` + FastAPI's `TestClient` for:
   - `GET /api/sessions` returns a session list
   - `POST /api/sessions` creates a session
   - `POST /api/sessions/{id}/message` submits a message
   - `POST /api/sessions/{id}/interrupt` submits an interrupt
   - `GET /api/files?path=...` returns file contents with correct Content-Type, rejects paths outside whitelist
2. Implement `app.py`:
   - Create FastAPI app instance
   - Accept `RuntimeFacade`, `WebDisplay`, `WebInteractionHandler` in a factory function `create_app(runtime, display, interaction_handler, work_dir) -> FastAPI`
   - Mount route modules
3. Implement `routes/sessions.py`:
   - `GET /api/sessions` — call `Session.list_sessions()`, group by work_dir, filter sub-agents
   - `POST /api/sessions` — call `initialize_session()` with the runtime
   - `POST /api/sessions/{id}/message` — build `RunAgentOperation`, submit to runtime
   - `POST /api/sessions/{id}/interrupt` — submit `InterruptOperation`
   - `POST /api/sessions/{id}/respond` — call `WebInteractionHandler.resolve_interaction()`
   - `POST /api/sessions/{id}/model` — submit `ChangeModelOperation`
   - `GET /api/sessions/{id}/history` — call `Session.get_history_item()`, serialize as JSON array
4. Implement `routes/events.py`:
   - `GET /api/sessions/{id}/events` — SSE endpoint using `sse-starlette`'s `EventSourceResponse`, consuming from `WebDisplay.subscribe(session_id)`
5. Implement `routes/files.py`:
   - `GET /api/files` — validate path against whitelist (session dirs, work_dir, /tmp), return `FileResponse` with inferred Content-Type
6. Verify: `pytest tests/test_web_app.py -v`
7. Commit: `feat(web): add FastAPI app with MVP API endpoints`

**Acceptance criteria:**
- All MVP endpoints respond with correct status codes and shapes
- SSE endpoint streams events filtered by session_id
- File endpoint blocks path traversal and paths outside whitelist
- Tests mock RuntimeFacade/Session to avoid needing real LLM clients

**Notes:**
- `Session.list_sessions()` already filters sub-agents. For cross-project listing, will need to iterate `~/.klaude/projects/*/sessions/` — can defer to a helper.
- `GET /api/sessions/{id}/history` returns `ReplayEventUnion` sequence — same shape as SSE events, so frontend uses the same rendering code.

---

### Task 4: Create the `klaude web` CLI command and server startup

**Files:**
- Create: `src/klaude_code/web/server.py`
- Modify: `src/klaude_code/cli/main.py`
- Test: `tests/test_web_server_startup.py`

**Intent:** Wire the web server into the CLI. `klaude web` starts uvicorn with the FastAPI app, initializing the core runtime with WebDisplay/WebInteractionHandler. The server runs in the same asyncio event loop as the runtime.

**Steps:**
1. Implement `server.py`:
   - `async def run_web_server(host, port, init_config)` — initialize app components with WebDisplay + WebInteractionHandler, create FastAPI app, run uvicorn programmatically via `uvicorn.Server(config).serve()`
   - Handle graceful shutdown (SIGINT/SIGTERM → cleanup_app_components)
2. Register `web` command in CLI:
   - Add `@app.command("web")` in `main.py` (or create `web_cmd.py` and `register_web_commands(app)`)
   - Options: `--host` (default `127.0.0.1`), `--port` (default `8765`), `--dev` (skip static file serving), `--debug`
3. Write a basic test that the server starts and responds to `GET /api/sessions`
4. Verify: `klaude web --help` shows the command. Manual test: `klaude web` starts and `curl http://localhost:8765/api/sessions` returns JSON.
5. Commit: `feat(web): add klaude web CLI command`

**Acceptance criteria:**
- `klaude web` starts a server on localhost:8765
- `GET /api/sessions` returns valid JSON
- Ctrl+C gracefully shuts down runtime and server
- `--dev` flag skips static file mounting (for vite dev proxy)

**Notes:**
- Follow the pattern in `main.py` where commands are registered via `register_*_commands(app)`.
- The `typer.Exit(2)` pattern from `initialize_app_components` for missing model config should be handled gracefully (return HTTP error, not crash server).
- Consider guarding the import of fastapi/uvicorn behind a try/except with a helpful error message if the `web` extra isn't installed.

---

## Phase 2: Frontend Foundation

### Task 5: Scaffold the frontend project

**Files:**
- Create: `web/` directory (Vite + React + TypeScript + Tailwind + shadcn/ui)
- Create: `web/public/fonts/tx-02.woff2` (copy from `~/Downloads/TX-02-OpenCode/`)
- Create: `web/public/fonts/tx-02-bold.otf`, `tx-02-italic.otf`, `tx-02-bold-italic.otf`

**Intent:** Set up the frontend project with all tooling configured: Vite dev server with API proxy, Tailwind with the Claude-inspired color palette, TX-02 font faces, shadcn/ui initialized.

**Steps:**
1. Run `pnpm create vite web --template react-ts` from project root
2. `cd web && pnpm install`
3. Initialize Tailwind: `pnpm add -D tailwindcss @tailwindcss/vite` and configure
4. Initialize shadcn/ui: `pnpm dlx shadcn@latest init`
5. Configure `vite.config.ts` with proxy: `/api` → `http://localhost:8765`
6. Copy TX-02 font files to `web/public/fonts/`
7. Set up `@font-face` declarations and CSS variables from `docs/web/3-style-guide.md` in the global CSS
8. Configure Tailwind theme extensions (colors, fonts) matching the style guide
9. Install core dependencies: `pnpm add zustand streamdown @streamdown/code @streamdown/mermaid @uiw/react-json-view @pierre/diffs`
10. Verify: `cd web && pnpm dev` starts without errors, shows default Vite page with correct fonts
11. Commit: `feat(web): scaffold frontend with Vite, React, Tailwind, shadcn/ui`

**Acceptance criteria:**
- `pnpm dev` starts on :5173
- Proxy to :8765 works (when backend is running, `/api/sessions` proxied correctly)
- TX-02 font renders in a test `<code>` block
- Tailwind classes using custom colors work (`bg-background`, `text-primary`, etc.)

**Notes:**
- Add `web/node_modules/` and `web/dist/` to the project `.gitignore`
- Don't add `@fontsource/inter` — use the Google Fonts CDN link in `index.html` for simplicity

---

### Task 6: Implement the base layout (Sidebar + Main area)

**Files:**
- Create: `web/src/App.tsx`
- Create: `web/src/components/sidebar/Sidebar.tsx`
- Create: `web/src/components/sidebar/SessionCard.tsx`
- Create: `web/src/components/layout/MainPanel.tsx`
- Add shadcn/ui components: Sidebar, ScrollArea, Sheet (for mobile)

**Intent:** Build the two-column layout: left sidebar with session list, right main area. Mobile: sidebar as Sheet drawer. This is the shell that all other components will be placed into.

**Steps:**
1. Add shadcn/ui Sidebar component: `pnpm dlx shadcn@latest add sidebar scroll-area sheet`
2. Build `App.tsx` with SidebarProvider + Sidebar + main content area
3. Build `Sidebar.tsx`: project groups → session cards, search input at top
4. Build `SessionCard.tsx`: shows first user message as title, time ago, message count
5. Build `MainPanel.tsx`: empty state ("Select or create a session"), will host MessageList and InputArea
6. Wire up mobile responsive behavior (sidebar as Sheet below md breakpoint)
7. Verify: `pnpm dev` shows the two-column layout with placeholder content
8. Commit: `feat(web): add base layout with sidebar and main panel`

**Acceptance criteria:**
- Desktop: fixed sidebar (260px) + scrollable main area
- Mobile (<768px): hamburger button → Sheet drawer for sidebar
- Session cards show placeholder data (hardcoded for now)
- Empty state shown when no session selected

---

### Task 7: Implement Zustand stores and API client

**Files:**
- Create: `web/src/stores/app-store.ts`
- Create: `web/src/stores/session-store.ts`
- Create: `web/src/api/client.ts`
- Create: `web/src/api/sse.ts`
- Create: `web/src/types/events.ts`
- Create: `web/src/types/session.ts`

**Intent:** Set up the state management layer and API client. The app store holds the session list and current selection. The session store holds messages/events for the active session. The SSE client connects to the event stream and dispatches events into the store.

**Steps:**
1. Define TypeScript types for session metadata, event envelopes, and API responses (matching the Pydantic models)
2. Implement `client.ts`: thin wrappers around `fetch()` for each REST endpoint (`listSessions`, `createSession`, `sendMessage`, `interrupt`, `respond`, `getHistory`)
3. Implement `sse.ts`: `connectSSE(sessionId) -> EventSource` wrapper that parses SSE events and calls a dispatch callback. Handles reconnection.
4. Implement `app-store.ts` (Zustand):
   - State: `sessions`, `currentSessionId`, `loading`
   - Actions: `fetchSessions`, `selectSession`, `createSession`
5. Implement `session-store.ts` (Zustand):
   - State: `events[]` (the message/event list for current session), `isStreaming`, `pendingInteraction`
   - Actions: `loadHistory`, `appendEvent`, `sendMessage`, `interrupt`
   - SSE connection management: connect on session select, disconnect on deselect
6. Verify: connect stores to sidebar, selecting a session triggers history fetch (visible in devtools/console)
7. Commit: `feat(web): add Zustand stores, API client, and SSE connection`

**Acceptance criteria:**
- Sidebar loads real session list from `GET /api/sessions` (requires backend running)
- Selecting a session fetches history and connects SSE
- Console logs show events arriving from SSE stream
- SSE reconnects on disconnect

---

## Phase 3: Message Rendering

### Task 8: Implement MessageList and core message components

**Files:**
- Create: `web/src/components/messages/MessageList.tsx`
- Create: `web/src/components/messages/UserMessage.tsx`
- Create: `web/src/components/messages/AssistantText.tsx`
- Create: `web/src/components/messages/ThinkingBlock.tsx`

**Intent:** Render the core message types: user messages, assistant streaming markdown text, and thinking blocks. This is the most important visual component — the conversation flow.

**Steps:**
1. Build `MessageList.tsx`: reads from session store, maps events to components by event type, auto-scrolls to bottom on new events
2. Build `UserMessage.tsx`: renders user text in a bubble with `--user-bubble` background
3. Build `AssistantText.tsx`: uses `<Streamdown>` with `@streamdown/code` and `@streamdown/mermaid` plugins for streaming markdown rendering. Includes [Raw] toggle (shows raw markdown source) and [Copy] button.
4. Build `ThinkingBlock.tsx`: collapsible block, aggregates thinking deltas, shows "Thinking..." label while streaming. [Copy] button.
5. Verify: start backend, create session, send a message, see assistant response render with markdown formatting and syntax highlighting
6. Commit: `feat(web): add message rendering with streaming markdown`

**Acceptance criteria:**
- User messages render with warm bubble background
- Assistant text streams in real-time with proper markdown formatting
- Code blocks have Shiki syntax highlighting via streamdown
- Thinking blocks are collapsible, default collapsed after completion
- [Raw] and [Copy] buttons work on AssistantText

---

### Task 9: Implement ToolCall and ToolResult components

**Files:**
- Create: `web/src/components/messages/ToolCall.tsx`
- Create: `web/src/components/messages/ToolResult.tsx`
- Create: `web/src/components/messages/tool-renderers/DiffView.tsx`
- Create: `web/src/components/messages/tool-renderers/ReadPreview.tsx`
- Create: `web/src/components/messages/tool-renderers/TodoListView.tsx`
- Create: `web/src/components/messages/tool-renderers/ImageView.tsx`
- Create: `web/src/components/messages/tool-renderers/PlainText.tsx`

**Intent:** Render tool calls and tool results according to the rendering rules in the design doc (sections 4 & 5). Each tool call shows `[mark] Name details` with [Raw JSON] and [Copy] buttons. Tool results dispatch to specialized renderers based on `ui_extra.type`.

**Steps:**
1. Build `ToolCall.tsx`: dispatch by `tool_name` to extract mark/name/details per design doc section 4.2. Raw mode shows `<JsonView>` from `@uiw/react-json-view`.
2. Build `ToolResult.tsx`: dispatch by `ui_extra.type` to sub-components. Error results render with error styling. Raw mode shows `<JsonView>`.
3. Build `DiffView.tsx`: uses `<PatchDiff>` from `@pierre/diffs/react` when `raw_unified_diff` available, otherwise reconstruct from `files[].lines[]`. Mobile: `diffStyle: 'unified'`.
4. Build `ReadPreview.tsx`: code block with line numbers, "more N lines" truncation indicator
5. Build `TodoListView.tsx`: checkbox list, completed items with checkmark styling
6. Build `ImageView.tsx`: `<img src={/api/files?path=...}>` with loading state
7. Build `PlainText.tsx`: truncated text with expand/collapse for long output (e.g., Bash)
8. Verify: trigger various tools (Read, Edit, Bash, WebSearch, TodoWrite) and verify rendering
9. Commit: `feat(web): add ToolCall and ToolResult rendering`

**Acceptance criteria:**
- Each tool type renders with correct mark icon and details extraction
- Diff views show syntax-highlighted split view (desktop) / unified (mobile)
- [Raw JSON] toggle works on all tool calls and results
- [Copy] works on all components
- Error tool results show red error styling

**Notes:**
- Refer to design doc section 4.2 for the complete tool-name-to-renderer mapping
- Refer to design doc section 5.3 for UIExtra type dispatch table

---

### Task 10: Implement SubAgentCard

**Files:**
- Create: `web/src/components/messages/SubAgentCard.tsx`

**Intent:** Render sub-agent execution as independent collapsible cards with colored left border. Each card contains a full message flow (reusing the same rendering components). See design doc section 3.3.

**Steps:**
1. Build `SubAgentCard.tsx`:
   - Colored left border (rotate through preset colors by sub-agent index)
   - Header: agent type + description
   - Body: reuse MessageList-like rendering for the sub-agent's events (filtered by session_id)
   - Footer: completion status + token stats
   - Collapse/expand toggle
2. Update `MessageList.tsx` to detect sub-agent events (by `session_id` differing from main) and route them into SubAgentCard instances
3. Handle recursive nesting (sub-agent's sub-agent → nested SubAgentCard)
4. Verify: trigger a sub-agent tool call, see it render as an independent card
5. Commit: `feat(web): add sub-agent card rendering`

**Acceptance criteria:**
- Sub-agent renders as independent card, not interleaved with parent messages
- Left border color distinguishes parallel sub-agents
- Card is collapsible; collapsed shows title + status summary
- Internal tool calls/results render correctly within the card
- Recursive nesting works (at least 2 levels)

---

## Phase 4: Input & Interaction

### Task 11: Implement InputArea with send/stop/model selector

**Files:**
- Create: `web/src/components/input/InputArea.tsx`
- Create: `web/src/components/input/ModelSelector.tsx`
- Add shadcn/ui components: Textarea, Button, DropdownMenu

**Intent:** Build the input area at the bottom: text input with send button (or stop button when streaming), model selector dropdown.

**Steps:**
1. Add shadcn/ui: `pnpm dlx shadcn@latest add textarea button dropdown-menu`
2. Build `InputArea.tsx`:
   - Auto-resizing textarea (shift+enter for newline, enter to send)
   - Send button: calls `sendMessage` store action → `POST /api/sessions/{id}/message`
   - Stop button (shown during streaming): calls `interrupt` → `POST /api/sessions/{id}/interrupt`
   - Sticky bottom positioning
3. Build `ModelSelector.tsx`: dropdown showing available models, calls `POST /api/sessions/{id}/model`
4. Handle disabled state when no session selected or session is busy (MVP: reject during agent execution)
5. Verify: send messages and see them appear in the conversation, stop button interrupts generation
6. Commit: `feat(web): add input area with send, stop, and model selector`

**Acceptance criteria:**
- Enter sends message, shift+enter inserts newline
- Input disabled while agent is executing (MVP behavior)
- Stop button appears during streaming and interrupts execution
- Model selector switches model for current session

---

### Task 12: Implement user interaction UI (AskUserQuestion, tool approval)

**Files:**
- Create: `web/src/components/messages/InteractionRequest.tsx`

**Intent:** When the agent asks the user a question (AskUserQuestion tool) or requests approval for a dangerous operation, render an interactive UI inline in the message flow. The user's response is posted back via `POST /api/sessions/{id}/respond`.

**Steps:**
1. Build `InteractionRequest.tsx`:
   - For `ask_user_question` kind: render question text + option buttons (single/multi select) + free-text input
   - For `operation_select` kind: render option list
   - Submit button calls store action → `POST /respond`
   - Show "cancelled" state if interaction is cancelled by the system
2. Wire into `MessageList.tsx`: render `InteractionRequest` when `user.interaction.request` event arrives
3. Handle interaction resolution: `user.interaction.resolved` event removes the interactive UI
4. Verify: trigger AskUserQuestion tool (e.g., via a skill that uses it), respond via the web UI
5. Commit: `feat(web): add user interaction request handling`

**Acceptance criteria:**
- Question with options renders selectable buttons
- Free-text input available for custom responses
- Response is sent to backend and the agent continues
- Resolved/cancelled states display correctly

---

## Phase 5: StatusBar & Polish

### Task 13: Implement StatusBar

**Files:**
- Create: `web/src/components/status/StatusBar.tsx`

**Intent:** Bottom status bar showing context usage, token count, model name, and elapsed time for the current operation.

**Steps:**
1. Build `StatusBar.tsx`:
   - Context usage: percentage bar from `UsageEvent` data
   - Model name from session metadata
   - Cost/token summary when available
   - Elapsed time during active operations
2. Wire into layout (fixed bottom, below InputArea)
3. Responsive: full info on desktop, abbreviated on mobile
4. Verify: run a session, see status bar update in real-time
5. Commit: `feat(web): add status bar`

**Acceptance criteria:**
- Context percentage updates as the conversation grows
- Model name displayed
- Mobile shows abbreviated version

---

### Task 14: Static file serving for production builds

**Files:**
- Modify: `src/klaude_code/web/app.py`
- Modify: `web/package.json` (add build script)

**Intent:** In non-dev mode, the FastAPI app serves the frontend build output from `web/dist/` via Starlette's StaticFiles. SPA fallback returns `index.html` for all non-API routes.

**Steps:**
1. Add `pnpm build` script in `web/package.json` (already default from Vite)
2. In `app.py`, when `--dev` is NOT set, mount `StaticFiles(directory=web_dist_path, html=True)` as a catch-all after API routes
3. Determine `web_dist_path` relative to the package install location (use `importlib.resources` or `Path(__file__).parent`)
4. Verify: `cd web && pnpm build`, then `klaude web` (without `--dev`) serves the built frontend at `http://localhost:8765/`
5. Commit: `feat(web): serve frontend build in production mode`

**Acceptance criteria:**
- `klaude web` serves the SPA at root `/`
- `/api/*` routes still work
- SPA client-side routing works (any non-API path returns index.html)
- `klaude web --dev` does NOT mount static files

---

### Task 15: End-to-end smoke test

**Files:**
- Modify: (no new files, manual verification)

**Intent:** Full end-to-end verification of the complete flow.

**Steps:**
1. `klaude web` — server starts
2. Open `http://localhost:8765` in browser
3. Verify sidebar loads existing sessions
4. Create a new session
5. Send a message, verify streaming response renders
6. Verify tool calls render (Read, Edit, Bash)
7. Verify thinking block collapses
8. Verify [Raw] and [Copy] buttons work
9. Verify mobile layout (responsive dev tools)
10. Verify stop button interrupts
11. Verify page reload reconnects SSE
12. Commit: `feat(web): web server MVP complete`

**Acceptance criteria:**
- All the above manual checks pass
- No console errors in browser
- No Python tracebacks in server logs
