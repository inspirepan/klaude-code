# 拆分 `PromptToolkitInput`（input_prompt_toolkit）任务上下文

Last Updated: 2025-11-29

## 1. 关键文件与模块

- 核心实现文件：
  - `src/klaude_code/ui/modes/repl/input_prompt_toolkit.py`
    - 定义 `PromptToolkitInput`，实现 REPL 输入逻辑；
    - 定义 `REPLStatusSnapshot`；
    - 内联了剪贴板图片处理、键盘绑定、补全逻辑。

- 外部使用与接口：
  - `src/klaude_code/ui/core/input.py`
    - 定义 `InputProviderABC`，`PromptToolkitInput` 实现该抽象。
  - `src/klaude_code/ui/__init__.py`
    - 对外 re-export `PromptToolkitInput`；
    - 其他 UI 模式也通过此处统一暴露。
  - `src/klaude_code/cli/runtime.py`
    - 行为：在运行时选择并实例化 `PromptToolkitInput` 作为 `input_provider`。

- 类与函数（当前集中在 `input_prompt_toolkit.py`）：
  - 状态：`REPLStatusSnapshot`
  - 输入主类：`PromptToolkitInput`
  - 剪贴板图片：`CLIPBOARD_IMAGES_DIR`、`ClipboardCaptureState`、`_clipboard_state`、`_extract_images_from_text`、`_encode_image_file`、`_copy_to_clipboard`
  - 键盘绑定：`kb = KeyBindings()` 及所有 `@kb.add(...)` handler
  - 补全：`_CmdResult`、`_SlashCommandCompleter`、`_ComboCompleter`、`_AtFilesCompleter`

## 2. 重要设计决策（现状）

1. 输入历史按项目维度存储
   - 路径：`~/.klaude/projects/{project}/input_history.txt`
   - `project` 来源：`Path.cwd()` 去掉前导 `/` 后用 `-` 连接，确保每个仓库独立历史。

2. 多行输入与鼠标控制
   - `PromptSession` 使用 `multiline=True`；
   - 通过 `_mouse_enabled` + `Condition` 控制鼠标启用：
     - 初始为 `False`，便于选择历史记录；
     - 输入内容跨行（包含 `"\n"`）时启用鼠标。

3. 底部工具栏展示信息
   - 左侧：当前工作目录（带 `~` 缩写）及 git 分支名；
   - 右侧：模型名与 context 使用百分比；
   - 当 `update_message` 存在时，工具栏仅展示更新提示。

4. 剪贴板图片处理协议
   - 键位：`Ctrl+V`（`"c-v"`）
   - 行为：
     - 从系统剪贴板抓取图片（`PIL.ImageGrab.grabclipboard()`）；
     - 将图片保存到 `CLIPBOARD_IMAGES_DIR`；
     - 在输入框中插入 tag（`[Image #N]`）；
     - 在 `iter_inputs` 中通过 `_extract_images_from_text`：
       - 使用 `_IMAGE_TAG_RE = r"\[Image #(\d+)\]"` 匹配文本中的标签；
       - 根据标签与 `_clipboard_state` 中的路径映射，生成 `ImageURLPart`（base64 PNG data URL）；
       - 将图片列表作为 `UserInputPayload.images` 传入后端。

5. 键盘绑定行为要点
   - `Enter`：
     - 若光标前文本以 `"\\"` 结尾（VS Code/Windsurf/Cursor 发送的 Shift+Enter sentinel），则删除该字符并插入换行；
     - 若整个 buffer 为空白，则插入换行而不是提交；
     - 否则调用 `buf.validate_and_handle()` 提交输入。
   - `Ctrl+J`：强制插入换行。
   - `c`：
     - 若存在选择，则复制选中文本到系统剪贴板（macOS: `pbcopy`，Windows: `clip`，Linux: `xclip`/`xsel`）；
     - 否则在 buffer 中插入字符 `'c'`。
   - `Backspace`：
     - 若有 selection，则执行 `cut_selection`；
     - 否则删除光标前字符；
     - 然后根据当前文本是否在 `@` token 或 slash 命令上下文中决定是否刷新补全（`start_completion`）。
   - `Left`/`Right`：
     - 在行首/行尾进行换行跳转（上一行末尾/下一行开头）。

6. `@` 路径补全策略
   - 触发条件：
     - 正则 `_AT_TOKEN_RE = r"(^|\s)@(?P<frag>[^\s]*)$"`，即光标前的 token 以 `@` 开头且不包含空格；
   - 行为：
     - 若 fragment 为空，仅基于当前 `cwd` 列出子目录/文件（忽略 `.git`、`.venv`、`node_modules`）；
     - 若 fragment 非空，则调用：
       - 优先 `fd`：同时搜文件和目录，区分 gitignored；
       - 其次 `rg --files`；
     - 通过打分函数（是否 ignored、basename 命中、路径命中位置、长度等）排序结果；
     - 对目录在末尾加 `/`；
     - 最终插入 `@path `（带尾随空格，结束触发）。

## 3. 已知约束与非目标

- 约束：
  - 不改变外部公开 API：`PromptToolkitInput` 的 import 路径与构造签名保持不变；
  - 不在本任务中引入新的输入模式或 UI 特性（例如主题切换、多 session 支持等）。

- 非目标：
  - 不重写现有补全算法或剪贴板协议，只进行结构性拆分；
  - 不在本轮中引入异步剪贴板/补全调用等高级改造。

## 4. 后续演进机会（供参考）

- 基于拆分后的 `repl_completers`：
  - 可以添加更多基于项目结构的智能补全（如函数名、测试文件等）；
  - 可以更方便地缓存/预热文件列表，减少实时 fd/rg 调用。

- 基于拆分后的 `repl_clipboard`：
  - 可以支持从文件拖拽或路径引用自动转为图片 input；
  - 可以增加图片缓存清理策略（按时间或大小）。

- 基于拆分后的 `repl_key_bindings`：
  - 可以做“按配置切换键位布局”或提供“vim/Emacs 风格”预设。
