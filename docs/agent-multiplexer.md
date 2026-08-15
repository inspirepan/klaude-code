# klaude Agent Multiplexer 设计

状态：Phase 1–4 已实现；Phase 5 进行中（2026-08，决策见 §8.4）
决策：移除 web 模块；klaude 变成 agent multiplexer —— 唯一的本地 server 持有全部 agent 执行，TUI 与 CLI 都是客户端。目标使用者有两类：人类（TUI attach）和其他 Agent（如 Claude Code 通过 Bash 调用 CLI）。

已确认的关键决策（2026-08-03）：

- TUI 仅作为 server 客户端（tmux 模型），**不保留**本地直连 runtime 的双模式；调试用 `klaude server run` 前台兜底。
- `run --approval` 默认 `hold`。
- server 常驻，直到 `server stop` / `server reload`；`reload` 为优雅重启（拾取本地代码改动），非热重载。
- web 前端、`klaude web` 命令和旧浏览器 REST/SSE session 路由已删除。server 仅保留当前
  CLI/TUI 使用的 session 创建、resume model 配置和每会话 WS 接口。

本文档以 `--help` 文本作为产品定义：每个命令的 help 就是它的功能规格。help 文本用英文（产品产物），说明性文字用中文。

---

## 1. 目标拓扑

```
klaude server（唯一进程，Unix socket ~/.klaude/run/server.sock）
│   持有唯一 RuntimeFacade；所有模型执行、会话 actor、事件流都在这里
│
├── klaude                  人类：自动拉起 server + attach 新会话（tmux 语义）
├── klaude attach <target>  人类：附着到已有会话（回放 + 实时；detach 不杀 agent）
├── klaude --resume         变为「选择器 + attach」
│
└── headless 命令面（Agent 通过 Bash 调用）
    run / ps / brief / wait / output / send / respond / kill
    agents（发现与集成：--json / --prime）
```

核心不变量：

- **纯本地**。数据在 `~/.klaude/` 下，server 监听 Unix domain socket，不开 TCP 端口。
- **单 server**。socket 文件 + flock 做单例；客户端命令在 server 不在时自动拉起（`server` 子命令除外）。
- **执行只属于 server**。TUI 不再内嵌 runtime；两个终端 attach 同一会话看到同一事件流，消灭双开 `--resume` 写坏 `events.jsonl` 的问题。
- **detach 不杀任务**。关掉终端，agent 继续跑。

---

## 2. 顶层 `klaude --help`

```text
Usage: klaude [OPTIONS] [COMMAND]

klaude — an agent multiplexer.

Run coding agents interactively, in the background, or from other
agents. A single local server owns all execution; the TUI and every
CLI command below are clients of it. Running klaude with no command
opens an interactive session in the current directory (the server is
auto-started when needed).

Options:
  -c, --continue       Attach to the latest session in this directory
  -r, --resume [ID]    Pick a session and attach; if it is running,
                       attach live instead of forking
  -m, --model TEXT     Select model (see `klaude agents`)
      --vanilla        Minimal mode: basic tools, no system prompts
  -d, --debug          Enable debug logging
  -V, --version        Show version and exit
  -h, --help           Show this message and exit

Background agents:
  run        Spawn a background agent, print its id, return at once
  ps         List sessions and their runtime states
  brief      Compact status of one session (agent-friendly, bounded)
  wait       Block until agents finish; print their results
  output     Print a session's output (last reply / transcript)
  send       Send a follow-up message (queued by default)
  respond    Answer a pending approval/question of a session
  kill       Interrupt a running agent (session stays resumable)

Attach:
  attach     Open the TUI on a session: replay, then follow live

Discovery:
  agents     Show agent types and models; --json for machines,
             --prime for an AI-agent integration guide

Server:
  server     Manage the local server (status / stop / reload / logs / run)

Setup:
  conf       Edit config file
  auth       Login/logout
  cost       Show usage stats
  upgrade    Upgrade to latest version

TARGET accepts a session id (unique prefix is enough) or a --name
given at `klaude run`. Pass --json to any background-agent or
discovery command for machine-readable output.

Orchestration is plain bash: `run` returns immediately, multi-target
`wait` is a barrier, `--group` names a fan-out. For the playbook
(parallel fan-out, barriers, loops, synthesis pipelines) and the
current model/agent inventory, run: klaude agents --prime
```

与现状的差异：删除 `web` 命令；`--continue/--resume` 语义从「本进程加载执行」改为「attach 到 server」；新增 Background agents / Attach / Discovery / Server 四组；**原 `list`（模型清单）命令移除，内容并入 `agents`**——`list` 这个名字的直觉语义是「列会话」，容易和 `ps` 混淆，会话列表统一归 `ps`（单人项目，不留兼容别名）。

---

## 3. 共享约定

### 3.1 TARGET 解析

`TARGET` = 会话 id 的唯一前缀，或 `run --name` 起的名字。歧义时报错并列出候选。名字在活跃（未 archived）会话内唯一，重名时拒绝创建。接受多个 TARGET 的命令（`ps` / `wait` / `kill`）同时支持空格与逗号分隔。

### 3.2 状态模型

| state | 含义 |
|---|---|
| `queued` | 已创建，等待 server 并发槽位（全局并发上限，见 §9.1） |
| `running` | 有活跃 task 在执行 |
| `waiting_input` | 卡在交互请求（审批 / 提问 / 模型选择）上 |
| `idle` | 无任务，但有可输入的 TUI attach 着（人在提示符前待命） |
| `completed` | 回合结束且无人 attach（headless 跑完、TUI 退出、历史会话），可 send / attach 继续 |
| `failed` | 上一回合以错误结束（仍可 send 重试） |

`wait` 对 `queued` 视同 `running`，继续阻塞。

单 server 模型不再用 meta.json 心跳推断运行状态。`server/routes/headless.py::_headless_state` 是 headless API 的单一状态投影入口：actor snapshot 经 `server/session_state.py` 统一映射 `running` / `waiting_input`，headless coordinator 补充 `queued` / `failed`，其余按是否有可输入的 WS attach（`routes/ws.py::input_attached_session_ids`，peek 只读连接不算）分为 `idle` / `completed`。这里的“单一状态源”指 server 内的实时投影，不是把全部状态压进一个持久字段。

`queued` turn、follow-up queue 和 `failed` 标记已持久化到 session meta，并在 server 启动时由 `server/headless.py::restore` 恢复。它们不是旧式 heartbeat；持久化只用于跨重启恢复，在线查询仍以 server 的状态投影为准。

`completed` 不是终态、没有生存期：server 会空闲回收内存 actor（沿用现有 30min TTL，`app/runtime.py:33`），但会话本体在磁盘上永存，`send` / `attach` 时按需从 `events.jsonl` 重建，跨 server 重启依然可续。对调用方来说「同一个 id 继续对话」永远可用。

### 3.3 退出码（脚本 / Agent 依赖）

| code | 含义 |
|---|---|
| 0 | 成功（`wait`：全部 completed 结束） |
| 1 | 用法错误 / target 不存在 / 歧义 |
| 2 | `wait`：有会话停在 `waiting_input` |
| 3 | `wait`：有会话 `failed` |
| 124 | `--timeout` 超时（同 `timeout(1)` 惯例） |

### 3.4 thin client

headless 子命令走轻量入口：只 import UDS HTTP 客户端，不 import agent/TUI 栈。Agent 每次调用都是新进程，启动延迟直接决定体验，目标 <150ms。

### 3.5 help 输出格式：纯文本

所有 `--help` 输出使用 git 风格纯文本（两空格缩进、对齐列），**不使用 rich panel**。理由：help 是 Agent 的高频读物，框线字符对 LLM 是噪音且浪费 token；纯文本对人类同样可读（git / tmux / ripgrep 惯例）。实现上关闭 typer 的 rich help 渲染，分组用自定义 help formatter。

rich 保留给真正的人类交互界面：TUI、`klaude agents` 默认视图、`ps --watch`。

---

## 4. 各命令 help（产品规格）

### 4.1 `klaude run`

```text
Usage: klaude run [OPTIONS] [PROMPT]

Spawn a background agent on the server and print its session id, then
return immediately. The agent keeps running after this command exits.
PROMPT is read from the argument, or from stdin when piped. When
both are given, stdin is appended to PROMPT — but only if pipe data
arrives within 1s, so an inherited pipe that never closes cannot
hang the command.

Examples:
  klaude run "fix the failing tests under tests/server/"
  klaude run -C ~/code/proj -m sonnet --name fix-tests "..."
  git diff | klaude run --agent code-reviewer "review this diff"
  klaude run --wait "one-shot question, print answer when done"

Options:
  -C, --dir PATH       Working directory (default: cwd)
  -m, --model ALIAS    Model alias (see `klaude agents`); defaults to
                       the agent type's bound model
      --agent TYPE     Agent type (see `klaude agents`). Default: main
                       — the full agent with all tools. Other types
                       (finder, code-reviewer, ...) run with their
                       own prompt, tool set, and bound model
      --name NAME      Addressable name for ps/brief/wait/send
      --group NAME     Tag this session for `ps --group NAME`. Lets
                       a calling agent find everything it spawned
                       even after it lost the ids
      --session ID     Send into an existing session instead of
                       creating a new one (same as `klaude send`)
      --approval MODE  What to do on permission requests when no
                       human is attached:
                         hold  park request, state=waiting_input
                               (default)
                         auto  approve permission requests;
                               questions still park as
                               waiting_input; trusted dirs only
                         deny  reject; agent must work around
      --wait           Block until finished, print final output
      --timeout SECS   With --wait: exit 124 on timeout
      --json           Print {"session_id": ..., "name": ...}
```

`--agent` 的实现注意点（对照现有 sub-agent 机制）：

1. **不要标记 `sub_agent_state`**。sub-agent 会话的 meta 带 `sub_agent_state`，且被会话索引过滤（`server/session_index.py`）。`run --agent` 创建的是**顶层会话**，使用 `agent_type` 供 `ps` 展示，而不是复用 `sub_agent_state`。
2. **模型绑定**。默认模型取 profile 的绑定（`config/sub_agent_model.py` 的 `SubAgentModelResolver`，即 `klaude agents` 中 `gpt-5.6-luna (finder)` 这类标注），`-m` 可覆盖。
3. **`fork_context` 型 profile**（继承父会话上下文的类型）standalone 运行时没有父会话可 fork，按空上下文启动；stdin 管道（如 `git diff |`）是它们获得输入材料的方式。

### 4.2 `klaude ps`

```text
Usage: klaude ps [OPTIONS] [TARGET...]

List sessions known to the server. Active sessions (queued, running,
waiting_input) always sort first, then idle (attached) ones, then
history — each group by most recently updated.

With TARGETs — ids, unique prefixes, or names; space- or comma-
separated — show only those sessions. This is the usual form for a
calling agent: check exactly the agents it spawned, nothing else.

  klaude ps a3f2c1,9b01d4,fix-tests --json

  ID       NAME       TITLE            STATE          LAST     MODEL   DIR          ACTIVITY
  a3f2c1   fix-tests  修复失败的测试     running        3s ago   sonnet  ~/code/proj  Bash: uv run pytest ...
  9b01d4   -          调整登录流程       waiting_input  2m ago   fable   ~/code/x     approval: Edit main.py
  77e0aa   -          -                completed      12m ago  opus    ~/code/y     -

STATE is completed once a session's last turn is over and no client is
attached; idle means a TUI is attached and waiting at the prompt. LAST
is the relative time of the session's most recent activity. ACTIVITY is
the current tool call when running and the pending request when
waiting_input.

Options:
      --group NAME    Only sessions spawned with `run --group NAME`
      --dir PATH      Only sessions under PATH
      --state STATE   Filter by state (repeatable)
  -n, --limit N       Max rows (default 20)
      --all           Include archived sessions
      --tree          Include sub-agent sessions nested under their
                      parents (the limit counts top-level rows)
      --watch         Live-refreshing table (human view)
      --json          Machine-readable
```

子会话（Agent 工具派生，`spawn_kind: subagent`）默认隐藏；`--tree` 展开时 NAME 列显示 `└─ <agent_type>`。TARGET 解析对子会话始终可用——`brief` / `output` / `kill` / `respond` / `attach` 都能用子会话 id 前缀直达。

`--watch` 持续刷新直到 Ctrl-C，仅用于人类表格，不能与 `--json` 组合。

作用域的三层设计（回答「已完成的会话会不会淹没列表 / 多个调用方会不会互相干扰」）：

1. **TARGET 列表**（Agent 主用）：调用方从 `run` 拿到 id，之后 `ps id1,id2,...` 只看自己那几个。`brief` 看单个细节，`ps` 看多个概览，对应关系类似 TaskGet 与 TaskList。
2. **`--group`**（Agent 兜底）：TARGET 方案的弱点是 id 只存在于调用方的对话上下文里，上下文压缩后可能丢失。调用方给自己起一个稳定的组名（如自己的 session id 或「项目+目的」），每次 `run --group X`，随时 `ps --group X` 全量找回。一个 meta 字段 + 一个过滤器，成本极低。
3. **默认视图**（人类主用）：不加参数时全局展示，但 active 永远排最前 + 默认只取最近 20 行——旧的 completed 会话天然沉底出屏。想翻全部历史用 `--all` 或 `--resume` 选择器。

`wait` / `kill` 的多 TARGET 参数同样接受逗号分隔。

### 4.3 `klaude brief`

```text
Usage: klaude brief [OPTIONS] TARGET

Print a compact, bounded summary of one session — sized to fit in a
calling agent's context. Never dumps the full transcript.

Sections: state, title, model, dir, todos, current/last tool call,
pending request (when waiting_input), last assistant message
(truncated), token usage, changed-files summary.

Options:
      --max-chars N   Output budget (default 2000)
      --full-last     Do not truncate the last assistant message
      --json          Machine-readable
```

数据源：`meta.json` 现有字段（title / todos / file_change_summary / model / updated_at）+ server 内活跃 actor 的 snapshot（当前工具调用、pending 交互请求）。零新增持久化。

### 4.4 `klaude wait`

```text
Usage: klaude wait [OPTIONS] [TARGET...]

Block until the given agents leave the queued/running states, then
print each one's final output, or its pending question when it
stopped at waiting_input. Give TARGETs, --group, or both.

Exit codes: 0 all completed · 2 some waiting_input · 3 some failed ·
124 timeout.

Examples:
  klaude wait a3f2,9b01                    # barrier over two agents
  klaude wait --group review --timeout 900 # barrier over a fan-out
  klaude wait --group review --any         # first finisher wins

Options:
      --group NAME     Wait for every session spawned with this group
      --timeout SECS   Give up after SECS (exit 124)
      --any            Return when the first target finishes
      --quiet          Exit code only, print nothing
      --json           Machine-readable
```

### 4.5 `klaude output`

```text
Usage: klaude output [OPTIONS] [TARGET...]

Print sessions' output. Default: the last assistant message only.
With multiple TARGETs or --group, each output is printed under a
`== <id> <name>` header — pipe the lot into a synthesis agent:

  klaude output --group review | klaude run --wait "dedupe and rank"

When a session is waiting_input, its pending request (type, prompt,
options) is appended after the output.

Options:
      --group NAME    All sessions spawned with this group
      --turns N       Last N user+assistant turns
      --transcript    Full transcript rendered as plain text
      --follow        Stream live output until the turn finishes (single target)
      --json          Machine-readable
```

`--follow` 仅接受单个 TARGET，不能与 `--group`、`--json`、`--turns` 或 `--transcript` 组合。

### 4.6 `klaude send`

```text
Usage: klaude send [OPTIONS] TARGET TEXT...

Send a message to a session.

  completed session: starts a new turn immediately — the follow-up
                    keeps the full conversation context
  running session:  queued by default; delivered when the current
                    turn finishes (like typing while klaude works)
  --steer:          interrupt the running turn and start a new turn
                    with the message now (course-correction)

Sessions never expire: send works minutes or days after the last
turn, and across server restarts — the conversation is reloaded
from disk on demand. This is how a calling agent iterates with the
same klaude agent over many rounds:

  id=$(klaude run "read the codebase, summarize the auth flow")
  klaude wait "$id"
  klaude send "$id" --wait "now write tests for the edge cases you found"
  klaude send "$id" --wait "one of them fails, here is the log: ..."

Note: send does NOT answer a pending interaction — a session parked
at waiting_input needs `klaude respond`.

Options:
      --steer          Deliver immediately, interrupting work
      --wait           Block until the resulting turn finishes
      --timeout SECS   With --wait
      --json           Machine-readable
```

### 4.7 `klaude respond`

```text
Usage: klaude respond [OPTIONS] TARGET

Answer a session's pending interaction (approval, choice, or text).
Run `klaude brief TARGET` first to see the request and its options.

Options:
      --approve / --deny   For permission requests
      --option N           Pick option N of a choice request
      --text TEXT          Free-text answer
      --json               Machine-readable
```

### 4.8 `klaude kill`

```text
Usage: klaude kill [OPTIONS] [TARGET...]

Interrupt a running agent — same as pressing Esc in the TUI. The
session is kept and stays resumable via `send` or `attach`.

Options:
      --group NAME    Interrupt every session in this group
      --all           Interrupt every running session
```

### 4.9 `klaude attach`

```text
Usage: klaude attach [OPTIONS] [TARGET]

Open the TUI on a session: replay the conversation so far, then
follow live. Multiple clients may attach to the same session and all
may type; execution is serialized by the server. Detach by exiting
(type `exit`, Ctrl+D, or close the terminal) — the agent keeps
running.

With no TARGET, opens the interactive session picker (same as -r).

Options:
      --peek          Read-only: follow without input
  -d, --debug         Enable debug logging
```

### 4.10 `klaude agents`（合并 agent types + models + prime）

```text
Usage: klaude agents [OPTIONS]

Show what this klaude can run:

  agent types  values for `klaude run --agent`, with purpose, tool
               access, and bound model
  models       configured model aliases grouped by provider, with
               upstream id and thinking/effort variants

The default output is a rich view for humans. Use --json or --prime
when the reader is a program or an AI agent.

Options:
      --json     Machine-readable inventory: agent types, models,
                 defaults
      --prime    Markdown integration guide for AI agents that drive
                 klaude through a shell tool: command cheatsheet
                 (run → ps/brief → wait/send → output), TARGET rules,
                 exit codes, and the current model/agent inventory.
                 Paste into CLAUDE.md / AGENTS.md, or have the agent
                 run `klaude agents --prime` once before using klaude.
```

数据源：模型部分复用现有 `klaude list` 的实现（`cli/list_model.py`，原命令名移除）；agent types 来自 `protocol/sub_agent/` 的 profile 注册表（`name` + `invoker_summary` + `tool_set`）+ `config/sub_agent_model.py` 的模型绑定。三种视图共享同一份数据组装，只是渲染不同。

### 4.11 `klaude server`

```text
Usage: klaude server [OPTIONS] COMMAND

Manage the local klaude server. One server per user; every other
command auto-starts it on demand, so you rarely need these.

Commands:
  status     Pid, socket path, uptime, version, session counts
  stop       Graceful shutdown (interrupts running agents!)
  reload     Restart the server on the current code — picks up local
             changes to the klaude installation. Refuses when
             sessions are running/queued (lists them); --force
             interrupts them first. Idle sessions are unaffected:
             they live on disk and rehydrate on demand
  logs       Tail server logs
  run        Run the server in the foreground (debugging)
```

---

## 5. 设计问题一：模型 / agent 类型的动态暴露

问题：调用方 Agent 事先不知道本机配置了哪些模型别名、哪些 agent 类型，也不知道调用惯例。这些动态信息放哪？

结论：**合并为一个 `klaude agents`，三种视图；`--help` 保持静态纯文本。**

| 视图 | 内容 | 消费者 |
|---|---|---|
| `klaude agents`（默认，rich） | agent 类型 + 模型清单 | 人类浏览 |
| `klaude agents --json` | 结构化 inventory | 程序 / Agent 运行时查询 |
| `klaude agents --prime` | 动态组装的 Markdown「使用说明书」（命令速查 + 惯例 + inventory） | 贴进 CLAUDE.md，或让 Agent 开工前跑一次 |

命名：不用 `list`——它的直觉语义是「列会话」，与 `ps` 撞车；会话列表统一归 `ps`，能力清单归 `agents`（单人项目，不留兼容别名）。

理由：

1. `--help` 是形状（shape）的规格：参数、语义、退出码，应当稳定、可离线、瞬时返回。配置清单会随环境漂移，放进 help 会让「help 即产品文档」失去确定性。动态组装的诉求由 `--prime` 承接——它就是给 Agent 看的、每次现场生成的产品文档，相当于把 Claude Code 系统提示里 Task 工具那段说明变成 klaude 自己能打印的东西。
2. 一个发现命令比三个（list / agents / prime）发现成本低：Agent 只需要记住「不知道什么就 `klaude agents`」。models 和 agent types 本来就交织在一起（模型别名上标着 agent 绑定，如 `gpt-5.6-luna (finder)`），拆成两个命令反而要交叉引用。
3. 折中保留：`run --help` 的 epilog 可以追加一行 `Currently configured: 23 model aliases, 5 agent types — see 'klaude agents'`（读本地配置，便宜且不破坏稳定性）。

---

## 6. 设计问题二：steer 还是排队？

问题：主 Agent 调用时，实时 steer（及时纠偏）用得多，还是排队 / 事后追问用得多？

判断：**排队与事后追问远多于实时 steer**，依据是 Claude Code 自身 Task 工具的实际使用模式：

1. 调用方 Agent 不是流式观察者，而是轮询者。它按事件（完成通知）或间隔（ps/brief）感知子 agent，等它发现跑偏时，「打断 + 重新下达更好的 prompt」（`kill` + `run`）几乎总是比中途注入一句纠偏更干净——steer 的价值窗口要求实时盯着看，而那是人类 attach TUI 的使用方式。
2. 最高频、最有价值的原语是**对已完成会话的追问**（对应 Claude Code 的 SendMessage：agent 保留全部上下文继续下一轮）。这在本设计里就是 `send` 到 completed 会话，成本最低、收益最大。
3. 次高频是**排队**：任务还在跑，把下一步指示排上（对应人类在 TUI 里边跑边打字）。klaude 已有 `follow_up_queue` 基础设施，接近免费。

因此 `send` 的语义分层如上文 4.6：默认排队 / completed 即发，`--steer` 作为显式旗标。实现顺序：**queue 语义先做（Phase 2），`--steer` 后做（Phase 3+）**——steer 需要打断当前 step 并注入消息的运行时支持，成本高而预期使用频率低；人类用户在 attach 的 TUI 里已经有 Esc 打断这条路。

---

## 7. 设计问题三：waiting_input 的闭环

问题：subagent 卡在 `waiting_input` 怎么办？主 Agent 怎么回答？`wait` 要不要解除阻塞？`brief` / `output` 要不要特殊处理？要不要在对话开始注入"自主模式"提醒？

答案是四层防线，从源头减少卡点，到卡住后可发现、可解除：

### 7.1 预防：autonomy attachment（新增 `agent/attachments/autonomy.py`）

headless 会话（由 `run` 创建、无人 attach）在对话开始注入一条 developer reminder，大意：

> You are running unattended, dispatched by another agent. Do not ask
> clarifying questions — make reasonable assumptions and state them in
> your final report. Interactive requests reach a queue nobody may be
> watching; use them only when truly blocked.

这正是 Claude Code 对自己的 subagent 的做法（其 harness 在自主模式下注入同款提醒）。实现贴合现有机制：attachment 就是 `(Session) -> DeveloperMessage | None`，按 session 标志（如 `spawn_kind: headless`）决定是否发射；参考 `reset_attachment_loaded_flags` 的 transient 模式，上下文压缩后可重注入。

可选细化：人类 `attach` 并发言后，下一回合注入一条状态翻转提醒（"a human is now attached; asking is OK when genuinely blocked"）。

### 7.2 策略：`--approval`

模型层的提问被 7.1 压到最少之后，剩余的 `waiting_input` 主要来自 harness 层的权限门（工具审批）。`run --approval` 决定无人值守时的处理：`hold`（默认）落为 `waiting_input` 等人处理；`auto` 自动批准**权限请求**（`source == "approval"`），但 `AskUserQuestion` 类提问仍会停靠为 `waiting_input`——只有 `deny` 做到零卡点（拒绝权限、给提问合成 "no human available" 答复）。`auto` **不会**自动检查目录是否可信，只能在 trusted dir 中使用。

### 7.3 暴露：wait / brief / output 都把 pending request 当一等公民

- **`wait`**：`waiting_input` 视为"到站"——解除阻塞、exit 2、打印完整 pending request（类型、问题文本、选项列表、respond 用法提示）。`wait` 绝不在卡点上无限阻塞，否则调用方跟着死锁。多目标混合结果时退出码取最严重（3 > 2 > 0）。
- **`brief`**：`waiting_input` 时 pending request 是输出的重点区块。
- **`output`**：`waiting_input` 时在正文末尾追加 pending request 区块；`--json` 带结构化 `pending_request`（request_id / type / prompt / options）。

### 7.4 解除：用 `respond`，不是 `send`

结构化交互（审批 / 选择 / 文本问答）用 `respond` 回答——它对应协议里的 `UserInteractionResponse`，直接解除卡点、继续执行。`send` 是对话消息，**不**解除交互卡点；两者语义刻意分开。要改方向而不是回答问题时，组合使用：`respond --deny` + `send "换个方式：..."`。

主 Agent 的标准闭环：

```bash
id=$(klaude run --group me "task...")
klaude wait "$id" --timeout 600
case $? in
  0) klaude output "$id" ;;             # 完成，取结果
  2) klaude brief "$id"                 # 看它在问什么
     klaude respond "$id" --approve     # 或 --deny / --option N / --text
     klaude wait "$id" ;;               # 继续等
  3) klaude output "$id" ;;             # 看失败原因，决定 send 重试或 kill 重跑
esac
```

---

## 8. 设计问题四：内部 sub-agent 机制的 server 化

问题：klaude 内部「主 Agent + 一层 subagent」机制能不能也改成 server 形态——subagent 成为 server 管理的一等会话，与 `klaude run` 走同一条路径？这是不是大重构？

结论：**能改，方向正确，但属于中大型重构，定为 Phase 5，等 Phase 1–4 稳定后做。** 概念上这就是 Claude Code 的架构：Agent 工具和 Task 管理（TaskList/TaskGet/TaskStop）是同一个任务子系统的两个暴露面。

### 8.1 现状耦合点（重构的真实工作量所在）

现状（`agent/runtime/sub_agent.py`，233 行）：父 agent 的工具调用在进程内直接构造子 `Session` + `Agent`，同步 `async for` 消费子 agent 的事件流。三处深耦合：

1. **事件归属**：子事件内联转发进父会话的事件管道（`sub_agent.py:190-204`，`TaskStartEvent` 上打 `parent_session_id`），TUI 靠这一条流渲染嵌套进度。server 化后子 actor 有自己的事件流，需要 server 侧把子流镜像回父流（保留 task 分组契约）——**这是最大的一块**。
2. **进度/元数据闭包**：`register_progress_getter` / `register_metadata_getter` 是函数闭包直连 dispatcher（`sub_agent.py:138-163`），要改成基于子 actor snapshot / 事件的等价物。
3. **交互请求**：子 agent 直接借用父的 `request_user_interaction` 闭包（`sub_agent.py:129`），请求因此挂在父会话名下——这是闭包副作用而非设计。改为：**请求挂子会话自己名下（park 在子 actor），仅显示层上浮**——TUI attach 父会话时由 server 把子会话的 pending 请求转发归并（见 §8.4 决策 1）。

次要工作：级联取消从 asyncio 原生 cancel 改为注册表级 parent-child 链（`mark_child_task_state` 已有雏形）；`SubAgentResult` 改为读子会话的 `TaskFinishEvent`；file-change 合并改为显式钩子；meta 的 `sub_agent_state` 换成 `parent_session_id` + `agent_type`。`fork_context` 不受影响（同进程，`Session.fork()` 照用）。

### 8.2 统一后的收益

1. **一条执行路径**：Agent 工具变成 `klaude run --agent` 同款操作的薄封装，删掉特例化的 sub-agent runtime。
2. **subagent 可观测可操作**：出现在 `ps`（默认折叠子会话，`--tree` 展开）；人类可以 `attach` 旁观一个正在跑的 subagent（现在做不到）；可以单独 `kill` 某个 subagent。
3. **异步 subagent 几乎免费**：父 agent 发起后不阻塞等待，靠完成通知收结果（对应 Claude Code Agent 工具的 `run_in_background`）。
4. **嵌套深度受控开放**：现在硬性一层；统一后深度只是注册表里的一个上限参数。

### 8.3 为什么不现在做

现有机制在新架构下**本来就跑在 server 进程里**，功能上没有任何问题——不统一的只是管理面。multiplexer 的全部价值（Phase 1–3）不依赖这次统一；而这次统一依赖 Phase 2 建好的 profile 实例化路径和 Phase 1 的 server 操作原语。顺序不能倒。

### 8.4 已拍板的实现决策（2026-08-04）

对照调研了 grok-build（xai-org-grok-build，Rust，ACP 协议 + leader server 多路复用，架构同构）后确认三项：

1. **交互请求挂子会话名下，显示层归并到父。** 子 agent 的 AskUserQuestion（及未来的权限审批）park 在子会话自己的 actor：状态投影天然正确（子 = `waiting_input`）、`respond`/`kill`/`attach` 目标精确；TUI attach 父会话时由 server 把 tracked 子会话的 pending 请求转发过去，界面上照常弹窗并标注来源。grok-build 的对照实验佐证了这个选择：它审批挂父/根会话、提问挂子会话，两种归属并存导致 UI 双套路由 + 「父会话被回收后无主请求」的兜底分支，属历史包袱；其提问路径（挂子 + UI 归并到父视图）是被验证的干净做法。
2. **子会话不占 headless 并发槽位。** 父占槽等子、子排队等槽会直接死锁；子会话绕过 headless 队列直跑，未来如需限流单独加 child cap。
3. **approval policy 沿 parent 链继承。** `_headless_auto_interaction_response` 目前只认 `spawn_kind == "headless"`；子会话按 `parent_session_id` 上溯取根会话的 policy。

从 grok-build 另外记录三条经验：

- **订阅继承**：其 leader 在「子 agent 已派生」时把父会话的订阅者集合复制给子 session id，并按 `(sessionId, toolCallId)` 缓存交互请求、attach 时 replay、多客户端 first-answer-wins。对应我们 WS `_forward_events` 的 live child tracking（看到 `TaskStartEvent.parent_session_id` 匹配即加入 tracked 集合）。
- **headless 反面教材**：grok-build 的 headless 路径漏处理提问类交互（drop 掉 response 通道），子 agent 静默挂 30 分钟超时。无人值守路径必须给**每一类**交互显式自动答复，不能靠 drop。
- **嵌套深度**：默认 max_depth=1 与我们一致，但超限时它从子 agent 的工具集里**删掉派生工具**，而不是运行时抛错——统一后照此办理（深度成为注册表上限参数）。

实施顺序：Step 0 meta 加 `parent_session_id`（无行为变化）→ Step 1a Agent 工具换轨子 actor（spawn/结果/级联取消 + WS live child tracking）→ 1b 交互路由 → 1c 进度/metadata 事件化 → Step 2 `ps --tree`/attach/kill 子会话 → Step 3 异步 subagent + 嵌套深度参数化 → Step 4 meta 停写 `sub_agent_state`（内存中的 `session.sub_agent_state` 保留：TUI 渲染与 task.py 行为门——compaction/rewind/handoff——都依赖它，Phase 5 只换 meta 持久化与索引过滤）。

---

## 9. 设计问题五：bash 作为 workflow 脚本语言

问题：对比 Claude Code 的 Dynamic Workflow 工具（JS 脚本里的 `agent()` / `parallel()` / `pipeline()` / loop），klaude 用 CLI 就是想把 workflow 脚本语言的实现成本转嫁给 bash。`parallel`、loop 这些语义需要辅助子命令包装吗？

结论：**不需要包装子命令。** Workflow 脚本语言存在的理由是让控制流确定化（不烧主 Agent 的 token 做每个分支决策）——bash 天然就是这个角色。逐原语映射后，绝大部分语义已被现有设计覆盖：

| Workflow 原语 | bash + klaude 等价物 | 状态 |
|---|---|---|
| `agent(prompt)`（同步） | `klaude run --wait "..."` | 已有 |
| `agent(prompt)`（异步） | `id=$(klaude run "...")` | 已有——`run` 本来就异步返回 |
| `parallel([...])` barrier | 连续多次 `run` + `klaude wait id1,id2,id3` | 已有——多目标 `wait` 就是 barrier |
| race / 首个完成 | `klaude wait --any` | 已有 |
| fan-out over 列表 | `for` / `xargs -I{} klaude run "... {}"` | bash 免费 |
| `while` loop（until-dry / until-count） | bash `while` + `run --wait` + 退出码 | bash 免费 |
| `pipeline()`（逐项链式、无全局 barrier） | 每项一个 `( run; wait; run ) &` 子 shell + bash `wait` | bash 可表达，文档化模式即可，不做包装 |
| `phase()` / `log()` 进度展示 | `--group` + `klaude ps --watch --group X` | 已有 |
| journal / resume | 会话本来持久化；脚本死了 `ps --group X` 找回、跳过已完成 | group 机制附带解决 |
| structured output（schema 强制） | 无对等物 | 可选后置（见下） |
| **并发上限**（cap + 排队） | **bash 做不到** | **必须 server 侧做（见下）** |

### 9.1 需要补的四个启用项

1. **`--group` 升级为 workflow 句柄**：`wait --group X`、`kill --group X`、`output --group X`（`ps --group` 已有）。fan-out 场景下逐个收集 id 是最大的记账负担，group 一次消灭，且天然抗调用方上下文丢失。
2. **`output` 支持多 TARGET / `--group`**：综合（synthesis）阶段的管道基础——把 N 个 finder 的报告一次倒给下一个 agent。
3. **server 全局并发上限 + `queued` 状态**：`xargs` 一次拉起 50 个 `run`，没有上限就是 50 路并发 LLM 流。Workflow 工具有 `min(16, cores-2)` 的槽位制，klaude 的对等物必须在 server 侧：超出上限的会话进 `queued`，有槽位再跑；`wait` 把 `queued` 视同 running 继续阻塞。这是唯一 bash 无法自行提供的语义。
4. **（可选后置）`run --output-schema`**：强制子 agent 以合法 JSON 收尾，让 `output --json | jq` 管道可靠。没有它时靠 prompt 约定，够用但不保证。

### 9.2 示例：fan-out review → barrier → synthesis

```bash
G="review-$(git rev-parse --short HEAD)"
git diff --name-only main | \
  xargs -I{} klaude run --group "$G" --agent code-reviewer "review the changes in {}"

klaude wait --group "$G" --timeout 900
klaude output --group "$G" | \
  klaude run --wait "dedupe these findings, verify each against the code, rank by severity"
```

loop-until-dry 同理是纯 bash：`while` 里 `run --wait` 一轮 finder，输出为空两轮即 break。这些模式写进 `agents --prime` 的说明书，而不是做成子命令。

**说明书的可发现性**：完整 playbook 只在 `--prime` 里，但 help 负责让冷启动的 Agent 找到它——两层面包屑：

1. 顶层 `--help` 的 epilog 用一句话点出编排模型的关键词（run 异步返回 / 多目标 wait 是 barrier / --group 命名 fan-out），并明确指路 `klaude agents --prime`。关键词很重要：Agent 靠模式匹配决定要不要跟进。
2. 子命令 help 的 **Examples 就地演示模式**（对 LLM 是 few-shot）：`run --help` 演示异步 spawn 与管道输入，`wait --help` 演示 barrier 与 race，`output --help` 演示 synthesis 管道，`send --help` 演示多轮续跑。Agent 逐个看 help 时，编排模式已经学完一遍。

这样 help 仍然是稳定的形状规格（例子不随配置漂移），说明书的动态部分（模型清单、agent 类型）留在 prime。

另一个对应关系值得记录：Workflow 的「脚本确定控制流 vs 主 Agent 逐步决策」两种模式，在 klaude 里同样都成立——调用方可以一条条发命令（灵活、烧 token），也可以写好 bash 脚本一次执行（确定、便宜），原语是同一套。

---

## 10. Server 与协议概要

- **传输**：uvicorn `--uds ~/.klaude/run/server.sock`；socket + flock 保证单例，实现在 `server/server.py`。
- **attach 协议**：`server/routes/ws.py` 提供操作帧和事件流；TUI 的 UDS 客户端实现在 `tui/client/socket_client.py`。
- **回放**：三段拼接，无缝隙无竞态：
  1. `Session.get_history_item()` 从落盘 parts 合成流式边界事件；
  2. `server/session_tape.py` 的 per-session tape 补上进行中未落盘回合；
  3. 接实时事件流。
- **TUI 改造**：TUI 与 runtime 之间抽 `RuntimeClient` 接口，但**只做 UDS 一个实现**（已决策：不保留本地直连双模式）。接口仍然值得抽——单测可以注入内存实现，且隔离 wire 细节。
- **server 生命周期**：常驻（tmux 语义），退出只经 `server stop` / `server reload`。`reload` = 优雅重启：默认有 running/waiting_input/queued 会话时拒绝并列出，`--force` 直接停机再 re-exec 新代码、重新 bind socket。被打断的 headless turn 在新 server `restore()` 时**从头重跑**（同一条输入重新执行一遍，靠 turn id 去重避免重复入历史）；交互会话不重跑，attach 后从磁盘续。与版本握手互补：CLI 握手发现 server 版本/代码指纹过旧且 server 空闲时，自动触发同样的重启路径（代码指纹可复用现有 git checkout 更新追踪）。
- **headless 交互**：`--approval hold` 时交互请求落为 `waiting_input` 状态，人类 `attach` 或任一客户端 `respond` 均可解锁（完整闭环见 §7）。
- **并发上限**：server 维护全局 headless 运行槽位（可配置，默认 ~8），超出的 `run` 进 `queued` 排队（见 §9.1）；交互式 attach 会话不占用该配额。
- **版本握手**：server status 与 WS `connection_info` 同时返回独立 protocol version 和 code fingerprint。HTTP CLI 遇到任一不匹配时走 stale-server 路径：空闲时自动 reload，busy 时警告；TUI 显示错误 notice。

### 删除清单（单 server 带来的简化）

| 删除项 | 原因 |
|---|---|
| `web/dist` + `web/src` 前端 | 无浏览器 UI |
| `control/event_relay.py`、`control/session_meta_relay.py` | 无跨进程事件转发 |
| `runtime_owner` / heartbeat 循环 / 15s 过期判定 | 所有权问题结构性消失 |
| `web/session_access.py` read_only 全套 | 同上 |
| meta.json 的 `runtime_owner` 键回填 | 只有一个写入者。注：回填机制本身保留（`store.py` 的 `_RUNTIME_META_KEYS`），键集换成 `follow_up_queue` / `headless_*` —— 直接 `update_meta` 的写入优先于滞后的批量快照，这在单 server 下仍然必要 |
| holder 跨连接仲裁 | 多客户端皆可输入，actor 串行化执行 |

---

## 11. 阶段计划

| 阶段 | 状态 | 内容 | 交付 |
|---|---|---|---|
| 1 | **已实现** | server 化：UDS + 单例锁 + `klaude server` 子命令（含 reload）；删除 web 前端、浏览器路由与 `klaude web` 命令 | server 可独立起停，web UI 退役 |
| 2 | **已实现** | headless 命令面：`run/ps/brief/wait/output/send(queue)/respond/kill` + `--group` 全套 + server 并发上限 + thin client + `--approval` 策略 + autonomy attachment + `agents --json/--prime` + 纯文本 help | **Claude Code 的异步子 Agent 可用** |
| 3 | **已实现** | TUI attach：`RuntimeClient`（仅 UDS 实现）、attach + 回放 + detach、`--resume/-c` 切 attach 语义、无 server 自动拉起、`send --steer` | 人类工作流完整切换 |
| 4 | **已实现** | 大扫除：删除跨进程机制（event/meta relay、runtime_owner/心跳、read_only、holder 仲裁、meta 运行时键回填） | 工程收敛 |
| 5 | **已实现**（增量项除外） | 内部 sub-agent 的 server 化（见 §8）：Agent 工具改走子 actor、子会话入 `ps --tree`、可 attach/kill 单个 subagent、meta 停写 `sub_agent_state`（读兼容保留，回放从 SpawnSubAgentEntry 重建显示状态） | 内外一套任务机制 |

Phase 5 已交付（2026-08-04）。刻意排除的增量项：异步 subagent（父发起后不阻塞、靠完成通知收结果）与嵌套深度参数化（现仍硬性一层），留待后续按需求开启。
