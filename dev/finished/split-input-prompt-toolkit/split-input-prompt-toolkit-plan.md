# 拆分 `PromptToolkitInput`（input_prompt_toolkit）规划

Last Updated: 2025-11-29

## 一、Executive Summary

- 目标：将当前 `src/klaude_code/ui/modes/repl/input_prompt_toolkit.py` 中高度耦合的输入、补全、键盘绑定、剪贴板图片逻辑拆分为职责清晰、可测试、可扩展的若干模块，同时保证对现有 CLI 行为零回归。
- 业务价值：
  - 降低修改 REPL 行为（例如新增补全、改键位、改图片处理）的风险和成本；
  - 为后续支持多种输入模式/主题/平台（比如不同终端、Headless 模式）打好基础；
  - 提升代码可维护性，使新同事更容易理解 REPL 输入管线。
- 技术路线：围绕“职责分离 + 明确契约”拆分为：输入会话组装（主入口）、补全模块、键盘绑定模块、剪贴板图片模块，并增加必要的抽象以消除当前模块间的隐式耦合。

## 二、Current State Analysis

文件：`src/klaude_code/ui/modes/repl/input_prompt_toolkit.py`

1. 职责混杂
   - REPL 状态定义：`REPLStatusSnapshot`（用于底部工具栏展示模型与上下文信息）。
   - 主输入提供器：`PromptToolkitInput`（创建 `PromptSession`、管理 history、底部工具栏、鼠标开关、图片提取等）。
   - 剪贴板与图片处理：
     - 全局常量 `CLIPBOARD_IMAGES_DIR`；
     - `ClipboardCaptureState` 负责从系统剪贴板抓取图片、生成 `[Image #N]` 标记并持久化到本地；
     - `_clipboard_state` 单例；
     - `_extract_images_from_text` 与 `_encode_image_file` 以方法 / 静态方法的形式挂在 `PromptToolkitInput` 上。
   - 键盘绑定：
     - 全局 `kb = KeyBindings()`；
     - 若干 `@kb.add(...)` handler：`"c-v"`（粘贴图片标签）、`"enter"`（处理 VS Code 的反斜杠 sentinel + 空行逻辑）、`"c-j"`（插入换行）、`"c"`（复制选中文本）、`"backspace"`、`"left"`、`"right"` 等。
   - 补全逻辑：
     - `_CmdResult` 辅助封装子进程调用结果；
     - `_SlashCommandCompleter`：首行 `/` 命令补全；
     - `_AtFilesCompleter`：`@` 路径补全，内部包含 fd/rg 调用、去抖动、缓存，以及 gitignored 排序逻辑；
     - `_ComboCompleter`：组合 `@` 和 `/` 的逻辑，优先 slash，再 fallback 到 `@`。

2. 耦合点与隐含依赖
   - 键盘绑定对补全模块的隐式依赖：
     - `backspace` handler 直接访问 `_AtFilesCompleter._AT_TOKEN_RE`，打破模块边界；
   - 键盘绑定对剪贴板单例的隐式依赖：
     - `c-v` handler 直接操作 `_clipboard_state`；
   - 图片提取逻辑与 `PromptToolkitInput` 强耦合：
     - `_extract_images_from_text` 在类内实现但实质上只依赖 `_clipboard_state` 和输入文本；
   - 主入口文件承担过多职责：
     - 同时包含 UI 装配、系统交互（subprocess 复制/粘贴）、文件系统访问（fd/rg、路径缓存）、业务协议构造（`UserInputPayload`）。

3. 现有对外依赖
   - 外部使用点：
     - `src/klaude_code/ui/__init__.py:30` 暴露 `PromptToolkitInput`；
     - `src/klaude_code/cli/runtime.py:254` 在运行时创建 `PromptToolkitInput` 作为 `input_provider`；
     - `src/klaude_code/ui/core/input.py` 中的 `InputProviderABC` 是接口约束。
   - 因此：对外只需要保证 `PromptToolkitInput` 的构造方式和 `iter_inputs()` 行为不变即可。

## 三、Proposed Future State

目标架构是在 `ui/modes/repl` 下形成一组关注点分离的模块：

1. 主入口模块：`input_prompt_toolkit.py`
   - 只保留：
     - `REPLStatusSnapshot` 定义；
     - `PromptToolkitInput`，作为 REPL 输入的“装配者”：
       - 创建 `PromptSession`；
       - 绑定 history、底部工具栏、样式；
       - 注入补全器与键盘绑定；
       - 在 `iter_inputs` 中调用“图片提取”服务。
   - 不再包含：fd/rg 细节、subprocess 实现、图片编码细节、复杂正则。

2. 补全模块：`repl_completers.py`
   - 负责所有基于 prompt_toolkit 的补全逻辑：
     - `_SlashCommandCompleter`、`_AtFilesCompleter`、`_ComboCompleter`；
     - `_CmdResult` 及 fd/rg 调用、缓存、排序逻辑。
   - 对外暴露：
     - `def create_repl_completer() -> Completer`：返回组合好的补全器实例；
     - `AT_TOKEN_PATTERN: Pattern[str]`：公开 `@` token 的正则，用于按需刷新补全（键盘绑定使用）。

3. 剪贴板与图片模块：`repl_clipboard.py`
   - 负责所有与图片和文本剪贴板相关的行为：
     - `CLIPBOARD_IMAGES_DIR`、`ClipboardCaptureState`；
     - `clipboard_state` 单例或工厂方法；
     - `capture_clipboard_tag(...)`：从系统剪贴板抓图，返回 `[Image #N]` 文本标签；
     - `extract_images_from_text(text: str, state: ClipboardCaptureState = clipboard_state) -> list[ImageURLPart]`；
     - `copy_to_clipboard(text: str) -> None`：封装当前 `_copy_to_clipboard` 逻辑。
   - 提供清晰的、与 prompt_toolkit 无关的纯 Python API，便于测试和复用。

4. 键盘绑定模块：`repl_key_bindings.py`
   - 集中定义所有 `KeyBindings`：
     - 通过工厂函数 `create_key_bindings(...) -> KeyBindings` 对外暴露。
   - 工厂函数显式接收依赖：
     - `capture_clipboard_tag: Callable[[], str | None]`；
     - `copy_to_clipboard: Callable[[str], None]`；
     - `at_token_pattern: Pattern[str]`；
   - 内部通过闭包捕获这些依赖，为各个 handler 提供所需能力，消除对具体模块/类的硬编码引用。

5. 对外接口保持不变
   - `PromptToolkitInput` 的构造签名保持现状（`prompt: str = "❯ "`, `status_provider: Callable[...] | None = None`）。
   - `iter_inputs` 继续产出 `UserInputPayload(text=..., images=...)`，图片来源与行为对用户透明。
   - 运行 CLI 的外部调用端无需修改。

## 四、Implementation Phases

### Phase 1：设计与拆分边界（S）

1. 明确模块职责与公共 API
   - 输出：
     - `repl_completers.py` 需要暴露的函数与常量列表；
     - `repl_clipboard.py` 的状态对象与纯函数接口；
     - `repl_key_bindings.py` 的工厂函数签名。
   - 接受标准：
     - 上述 API 能覆盖当前 `input_prompt_toolkit.py` 的全部使用场景；
     - 任何跨模块访问都走公共 API，而不是访问内部私有成员。

2. 识别循环依赖与解耦策略
   - 重点：
     - `backspace` handler 对 `_AtFilesCompleter._AT_TOKEN_RE` 的引用；
     - `c-v` handler 对 `_clipboard_state` 的引用；
   - 解耦方式：
     - 将正则实例和剪贴板操作通过参数传入 `repl_key_bindings.create_key_bindings`；
     - 保证 `repl_key_bindings` 不直接 import 其他实现模块。

### Phase 2：抽离补全模块 `repl_completers.py`（M）

1. 创建新文件并迁移补全相关代码
   - 任务：
     - 新建 `src/klaude_code/ui/modes/repl/repl_completers.py`；
     - 迁移 `_CmdResult`、`_SlashCommandCompleter`、`_AtFilesCompleter`、`_ComboCompleter` 以及相关 import；
     - 在新文件中实现 `create_repl_completer()` 和 `AT_TOKEN_PATTERN`。
   - 接受标准：
     - `input_prompt_toolkit.py` 中不再包含上述类定义；
     - 使用 `ThreadedCompleter(create_repl_completer())` 后 REPL 补全行为与现有一致。

2. 调整主入口文件引用
   - 任务：
     - 在 `input_prompt_toolkit.py` 中用 `from .repl_completers import create_repl_completer, AT_TOKEN_PATTERN` 替代原来内部类引用；
     - 修正 `_AtFilesCompleter._AT_TOKEN_RE` 的使用点，为后续键盘绑定解耦做准备。
   - 接受标准：
     - 代码通过 pyright/ruff 检查；
     - 单独测试 `/` 及 `@` 补全无回归。

### Phase 3：抽离剪贴板与图片模块 `repl_clipboard.py`（M）

1. 提炼剪贴板与图片逻辑
   - 任务：
     - 新建 `repl_clipboard.py`；
     - 迁移 `CLIPBOARD_IMAGES_DIR`、`ClipboardCaptureState`、`_IMAGE_TAG_RE`、`_copy_to_clipboard`、`_encode_image_file`、`_clipboard_state`；
     - 将 `_extract_images_from_text` 从 `PromptToolkitInput` 中抽到 `repl_clipboard.py`，并设计为纯函数：
       - `def extract_images_from_text(text: str, state: ClipboardCaptureState = clipboard_state) -> list[ImageURLPart]`；
       - `def capture_clipboard_tag(state: ClipboardCaptureState = clipboard_state) -> str | None`。
   - 接受标准：
     - `PromptToolkitInput` 中不再访问 `_clipboard_state`，而是使用新模块提供的函数；
     - 图片编码行为保持不变（依然是 PNG + base64 data URL）。

2. 在主入口中切换到新模块
   - 任务：
     - 在 `iter_inputs` 中使用 `extract_images_from_text(line)`；
     - 删除 `PromptToolkitInput` 内部与图片编码相关的静态方法；
     - 确保 `PromptToolkitInput` 的职责更聚焦于“驱动输入与调用服务”。
   - 接受标准：
     - 手动验证：复制图片 ➜ `Ctrl+V` ➜ 输入 `[Image #N]` 标签 ➜ 发送后图片仍能如之前一样被附带到请求。

### Phase 4：抽离键盘绑定模块 `repl_key_bindings.py`（L）

1. 设计键盘绑定工厂函数
   - 任务：
     - 新建 `repl_key_bindings.py` 并定义：
       - `def create_key_bindings(
             capture_clipboard_tag: Callable[[], str | None],
             copy_to_clipboard: Callable[[str], None],
             at_token_pattern: Pattern[str],
         ) -> KeyBindings:`；
     - 在函数内部创建 `kb = KeyBindings()` 并定义所有 handler。
   - 接受标准：
     - `repl_key_bindings.py` 无循环依赖；
     - 不直接 import `repl_completers` 或 `repl_clipboard`，仅依赖抽象函数/正则参数。

2. 迁移现有 handler 到新模块
   - 任务：
     - 将原文件中所有 `@kb.add(...)` 函数整体移动到 `create_key_bindings` 内部；
     - 使用闭包参数替换对 `_clipboard_state`、`_AtFilesCompleter._AT_TOKEN_RE` 等全局对象的直接访问；
     - 保留现有行为逻辑（包括 VS Code sentinel 处理、多行输入、左右换行、selection 复制等）。
   - 接受标准：
     - 主文件中只剩下 `kb = create_key_bindings(...)` 的调用；
     - 手动测试所有快捷键行为与现有一致。

3. 在主入口中组装依赖
   - 任务：
     - 在 `PromptToolkitInput.__init__` 中创建：
       - `completer = ThreadedCompleter(create_repl_completer())`；
       - 基于 `capture_clipboard_tag` / `copy_to_clipboard` / `AT_TOKEN_PATTERN` 调用 `create_key_bindings(...)`；
     - 确保鼠标状态 `_mouse_enabled` 的改变逻辑仍然通过 buffer events 保持原行为。
   - 接受标准：
     - `PromptSession` 构造函数参数集保持语义不变，仅来源模块改变；
     - REPL 启动后，所有键位和补全行为回归正常。

### Phase 5：清理与回归验证（M）

1. 清理无用 import 与死代码
   - 任务：
     - 确认拆分后没有残留未使用的 import、变量、函数；
     - 运行 `uv run ruff format`、`uv run isort .`。
   - 接受标准：
     - 代码风格/静态检查通过；
     - 被拆分的模块中无明显“悬空”代码。

2. 自动化与手动回归
   - 任务：
     - 运行 `uv run pytest`（至少覆盖 UI 相关或集成测试，如有）；
     - 手动执行 REPL：
       - 验证：输入历史、多行行为、slash 命令补全、`@` 路径补全、图片粘贴、左右移动、删除行为。
   - 接受标准：
     - 测试通过；
     - 关键交互路径无回归或卡顿。

## 五、Detailed Tasks（含验收标准与依赖）

下面按 Phase 列出具体任务，标明 Effort（S/M/L/XL）与依赖：

### Phase 1：边界设计

1. 任务 P1-1：梳理公共 API 列表（S）
   - 内容：在 `dev/active/split-input-prompt-toolkit` 目录下（或本文件）列出各子模块预期对外暴露的函数、类与常量。
   - 验收：
     - 所有后续实现的新增函数/类都能映射到该列表；
     - 不额外暴露“仅供内部使用”的实现细节。
   - 依赖：无。

2. 任务 P1-2：识别循环依赖并确定参数注入点（S）
   - 内容：确认需要通过参数注入（而不是 import）的依赖项（`capture_clipboard_tag`、`copy_to_clipboard`、`AT_TOKEN_PATTERN`）。
   - 验收：
     - `repl_key_bindings.py` 无直接 import `repl_clipboard` / `repl_completers`；
     - 依赖注入列表稳定，不再频繁变更。
   - 依赖：P1-1。

### Phase 2：补全模块

3. 任务 P2-1：创建 `repl_completers.py` 并迁移类定义（M）
   - 验收：
     - 迁移后能在新模块内通过 pytest 或简单脚本构造对象而不报 import 错误；
     - 新模块内的类型注解完整，符合项目风格。
   - 依赖：P1-1。

4. 任务 P2-2：实现 `create_repl_completer` 与 `AT_TOKEN_PATTERN`（S）
   - 验收：
     - 通过小型手动测试，使用 `PromptSession` + `create_repl_completer()` 能正常出现补全列表；
     - `AT_TOKEN_PATTERN` 与原 `_AT_TOKEN_RE` 匹配行为一致。
   - 依赖：P2-1。

5. 任务 P2-3：在 `input_prompt_toolkit.py` 中替换补全引用（S）
   - 验收：
     - 原 `_ComboCompleter()` 替换为 `create_repl_completer()`；
     - 没有对 `_AtFilesCompleter` 的残余直接引用。
   - 依赖：P2-2。

### Phase 3：剪贴板与图片

6. 任务 P3-1：创建 `repl_clipboard.py`，迁移状态类与 encode 逻辑（M）
   - 验收：
     - 新模块内可独立构造 `ClipboardCaptureState` 并调用 `capture_from_clipboard()`（在有剪贴板图片时）；
     - `_encode_image_file` 仍然生成 `ImageURLPart`，字段结构不变。
   - 依赖：P1-1。

7. 任务 P3-2：实现 `capture_clipboard_tag` / `extract_images_from_text` / `copy_to_clipboard`（M）
   - 验收：
     - 用简单脚本调用这些函数，不依赖 prompt_toolkit 也能工作；
     - `_clipboard_state` 不再在主文件中暴露为全局，而是集中在 `repl_clipboard.py` 中管理。
   - 依赖：P3-1。

8. 任务 P3-3：在 `PromptToolkitInput` 内部切换图片提取逻辑（S）
   - 验收：
     - `iter_inputs` 改为调用 `extract_images_from_text`；
     - `PromptToolkitInput` 中删除 `_encode_image_file` 和 `_extract_images_from_text` 等旧实现。
   - 依赖：P3-2。

### Phase 4：键盘绑定

9. 任务 P4-1：实现 `create_key_bindings` 工厂函数（M）
   - 验收：
     - 工厂函数签名稳定，参数均为抽象 callable / pattern；
     - 工厂内部不访问全局状态（除 prompt_toolkit 自身）。
   - 依赖：P1-2、P2-2、P3-2。

10. 任务 P4-2：迁移所有 handler 并替换主文件中的 `kb` 定义（L）
    - 验收：
      - `input_prompt_toolkit.py` 中不再定义 `kb = KeyBindings()` 与 `@kb.add(...)` 函数；
      - REPL 中手动验证 `Ctrl+V / Enter / Ctrl+J / c / Backspace / Left / Right` 行为与现有一致。
    - 依赖：P4-1。

11. 任务 P4-3：在主入口中注入依赖并连接补全（S）
    - 验收：
      - `PromptToolkitInput.__init__` 中同时使用 `create_repl_completer` 和 `create_key_bindings` 构造 session；
      - 类型检查通过（函数签名一致）。
    - 依赖：P4-2。

### Phase 5：清理与验证

12. 任务 P5-1：清理 import 与运行格式化（S）
    - 验收：
      - `uv run isort . && uv run ruff format` 无报错；
      - 无未使用符号告警。
    - 依赖：P2-3、P3-3、P4-3。

13. 任务 P5-2：自动化测试 & 手动回归验证（M）
    - 验收：
      - `uv run pytest` 通过（或至少与基线一致）；
      - 关键 REPL 使用路径（单行、多行、命令补全、路径补全、图片粘贴）全部测试通过。
    - 依赖：P5-1。

## 六、Risk Assessment and Mitigation

1. 风险：行为微回归（补全/键位细节）
   - 说明：拆分过程中稍有不慎可能改变 prompt_toolkit 的行为顺序或触发条件。
   - 缓解：
     - 分阶段迁移，每次只改动一个模块，完成后立即手动验证；
     - 对关键 handler（Enter、Backspace、路径补全）做好行为清单并逐项对照测试。

2. 风险：循环依赖或 import 结构过于复杂
   - 说明：不当的模块引用可能导致 import 死循环或初始化顺序问题。
   - 缓解：
     - 严格限制 `repl_key_bindings.py` 只依赖抽象 callable 和 pattern；
     - 在设计阶段（Phase 1）先确定依赖注入方式，编码时避免临时 import 其他子模块。

3. 风险：剪贴板与图片在不同平台行为差异
   - 说明：macOS / Windows / Linux 对剪贴板命令支持差异较大，拆分时容易引入异常处理缺失。
   - 缓解：
     - 保留当前 try/except 防御性代码；
     - 在 Linux + macOS 环境各做一次手动验证。

4. 风险：任务中途需求变更（例如增加新的输入模式）
   - 说明：拆分过程中，若同时引入新特性，可能干扰拆分节奏。
   - 缓解：
     - 本轮工作只做架构拆分，不引入新功能；
     - 对需求变更单独建立任务，基于拆分后的结构再迭代。

## 七、Success Metrics

- 代码结构层面：
  - `input_prompt_toolkit.py` 行数显著下降（例如从当前 ~800 行降到 ~300 行以内）；
  - 新增 3 个子模块，各自职责单一，循环依赖为 0。
- 维护成本层面：
  - 修改补全逻辑或键位绑定时，只需改动对应模块（单文件修改即可完成）；
  - 新人阅读 REPL 输入代码的时间缩短（主文件结构清晰）。
- 质量层面：
  - 自动化测试与手动回归通过；
  - 发布后无用户报告的 REPL 行为异常。

## 八、Required Resources and Dependencies

- 人力：
  - 1 名熟悉 prompt_toolkit 与本项目 UI 结构的开发者主导；
  - 如有需要，1 名熟悉 CLI 使用场景的开发者协助验证。
- 技术依赖：
  - 可运行现有测试与 REPL 的开发环境；
  - 多平台验证（至少 macOS + Linux）。
- 组织依赖：
  - 对拆分后模块命名/位置无额外跨团队约束。

## 九、Timeline Estimates

- Phase 1（边界设计）：0.5 天（S）
- Phase 2（补全模块拆分）：0.5–1 天（M）
- Phase 3（剪贴板与图片模块拆分）：0.5 天（M）
- Phase 4（键盘绑定模块拆分）：1–1.5 天（L）
- Phase 5（清理与回归验证）：0.5–1 天（M）

整体预估：约 3–4 个工作日，可视实际验证复杂度做微调。
