# 拆分 `PromptToolkitInput`（input_prompt_toolkit）任务清单

Last Updated: 2025-11-29

> 建议按 Phase 顺序推进，每个子任务完成后在此文件勾选。

## Phase 1：边界设计

- [x] P1-1（S）：梳理子模块公共 API
  - 接受标准：有一份清单，列出 `repl_completers.py`、`repl_clipboard.py`、`repl_key_bindings.py` 对外暴露的函数/类/常量，并得到认同。
  - 完成时间：2025-11-29
  - 详见下方 [子模块公共 API 清单](#子模块公共-api-清单)

- [x] P1-2（S）：确定依赖注入点，避免循环依赖
  - 接受标准：确认键盘绑定仅依赖 `capture_clipboard_tag`、`copy_to_clipboard`、`AT_TOKEN_PATTERN` 等抽象，不直接 import 其他子模块。
  - 完成时间：2025-11-29
  - 详见下方 [依赖注入点分析](#依赖注入点分析)

---

## 子模块公共 API 清单

### 1. `repl_completers.py` - 补全模块

**对外暴露：**

| 名称 | 类型 | 说明 |
|------|------|------|
| `create_repl_completer()` | `Callable[[], Completer]` | 工厂函数，返回组合好的补全器实例（内部组合 `_SlashCommandCompleter` 和 `_AtFilesCompleter`） |
| `AT_TOKEN_PATTERN` | `re.Pattern[str]` | `@` token 的匹配正则，供键盘绑定在 backspace 时判断是否需要刷新补全 |

**内部私有（不对外暴露）：**

| 名称 | 类型 | 说明 |
|------|------|------|
| `_CmdResult` | `NamedTuple` | 封装子进程调用结果 |
| `_SlashCommandCompleter` | `Completer` | 首行 `/` 命令补全 |
| `_AtFilesCompleter` | `Completer` | `@` 路径补全，包含 fd/rg 调用、去抖动、缓存、gitignored 排序 |
| `_ComboCompleter` | `Completer` | 组合补全器，优先 slash，再 fallback 到 `@` |

---

### 2. `repl_clipboard.py` - 剪贴板与图片模块

**对外暴露：**

| 名称 | 类型 | 说明 |
|------|------|------|
| `CLIPBOARD_IMAGES_DIR` | `Path` | 剪贴板图片存储目录（`~/.klaude/clipboard/images`） |
| `ClipboardCaptureState` | `class` | 剪贴板图片捕获状态管理类 |
| `clipboard_state` | `ClipboardCaptureState` | 模块级单例实例 |
| `capture_clipboard_tag()` | `Callable[[], str \| None]` | 从系统剪贴板抓取图片，保存并返回 `[Image #N]` 标签 |
| `extract_images_from_text(text: str)` | `Callable[[str], list[ImageURLPart]]` | 解析文本中的 `[Image #N]` 标签，返回对应的 `ImageURLPart` 列表 |
| `copy_to_clipboard(text: str)` | `Callable[[str], None]` | 将文本复制到系统剪贴板 |

**内部私有（不对外暴露）：**

| 名称 | 类型 | 说明 |
|------|------|------|
| `_IMAGE_TAG_RE` | `re.Pattern[str]` | 匹配 `[Image #N]` 的正则 |
| `_encode_image_file(file_path: str)` | 函数 | 将图片文件编码为 base64 data URL |

---

### 3. `repl_key_bindings.py` - 键盘绑定模块

**对外暴露：**

| 名称 | 类型 | 说明 |
|------|------|------|
| `create_key_bindings(...)` | 工厂函数 | 创建并返回 `KeyBindings` 实例 |

**工厂函数签名：**

```python
def create_key_bindings(
    capture_clipboard_tag: Callable[[], str | None],
    copy_to_clipboard: Callable[[str], None],
    at_token_pattern: re.Pattern[str],
) -> KeyBindings:
    """Create REPL key bindings with injected dependencies.
    
    Args:
        capture_clipboard_tag: Callable to capture clipboard image and return tag
        copy_to_clipboard: Callable to copy text to system clipboard
        at_token_pattern: Pattern to match @token for completion refresh
    
    Returns:
        KeyBindings instance with all REPL handlers configured
    """
```

**内部 handler（不对外暴露，在工厂函数内定义）：**

| 键位 | 功能 |
|------|------|
| `c-v` | 粘贴剪贴板图片为 `[Image #N]` 标签 |
| `enter` | 处理 VS Code sentinel + 空行逻辑 / 提交输入 |
| `c-j` | 插入换行 |
| `c` | 复制选中文本 / 插入字符 'c' |
| `backspace` | 删除 + 刷新补全 |
| `left` | 跨行左移 |
| `right` | 跨行右移 |

---

### 4. `input_prompt_toolkit.py` - 主入口模块（重构后）

**保留对外暴露：**

| 名称 | 类型 | 说明 |
|------|------|------|
| `REPLStatusSnapshot` | `NamedTuple` | REPL 状态快照（模型名、context 使用率等） |
| `PromptToolkitInput` | `class` | REPL 输入提供器，实现 `InputProviderABC` |
| `COMPLETION_SELECTED` | `str` | 补全菜单选中项颜色常量 |
| `COMPLETION_MENU` | `str` | 补全菜单颜色常量 |
| `INPUT_PROMPT_STYLE` | `str` | 输入提示符样式常量 |

**重构后职责：**

- 作为"装配者"角色
- 创建 `PromptSession`
- 调用 `create_repl_completer()` 获取补全器
- 调用 `create_key_bindings(...)` 获取键盘绑定
- 在 `iter_inputs` 中调用 `extract_images_from_text()` 提取图片
- 管理 history、底部工具栏、鼠标状态等

---

### 模块依赖关系图

```
input_prompt_toolkit.py
    ├── imports from repl_completers.py
    │       └── create_repl_completer()
    │       └── AT_TOKEN_PATTERN
    │
    ├── imports from repl_clipboard.py
    │       └── capture_clipboard_tag()
    │       └── copy_to_clipboard()
    │       └── extract_images_from_text()
    │
    └── imports from repl_key_bindings.py
            └── create_key_bindings(
                    capture_clipboard_tag,  # from repl_clipboard
                    copy_to_clipboard,      # from repl_clipboard
                    AT_TOKEN_PATTERN        # from repl_completers
                )

repl_key_bindings.py
    └── NO direct imports from repl_completers or repl_clipboard
    └── Dependencies injected via function parameters

repl_completers.py
    └── NO imports from other repl_* modules
    └── Only depends on: prompt_toolkit, klaude_code.command

repl_clipboard.py
    └── NO imports from other repl_* modules
    └── Only depends on: PIL, subprocess, pathlib, klaude_code.protocol.model
```

---

## 依赖注入点分析

### 当前问题：隐式/硬编码依赖

在现有代码中，键盘绑定模块存在以下隐式依赖：

| Handler | 依赖对象 | 依赖方式 | 问题 |
|---------|---------|---------|------|
| `c-v` | `_clipboard_state` | 直接访问全局单例 | 硬编码依赖剪贴板模块 |
| `c` | `_copy_to_clipboard()` | 直接调用模块级函数 | 硬编码依赖剪贴板模块 |
| `backspace` | `_AtFilesCompleter._AT_TOKEN_RE` | 访问类的私有属性 | 打破模块边界，硬编码依赖补全模块 |

### 解耦策略：依赖注入

将上述依赖改为通过 `create_key_bindings()` 工厂函数的参数注入：

```python
def create_key_bindings(
    capture_clipboard_tag: Callable[[], str | None],
    copy_to_clipboard: Callable[[str], None],
    at_token_pattern: re.Pattern[str],
) -> KeyBindings:
```

**注入点详解：**

| 参数 | 类型 | 来源 | Handler 使用场景 |
|------|------|------|-----------------|
| `capture_clipboard_tag` | `Callable[[], str \| None]` | `repl_clipboard.capture_clipboard_tag` | `c-v` handler 调用获取图片标签 |
| `copy_to_clipboard` | `Callable[[str], None]` | `repl_clipboard.copy_to_clipboard` | `c` handler 调用复制选中文本 |
| `at_token_pattern` | `re.Pattern[str]` | `repl_completers.AT_TOKEN_PATTERN` | `backspace` handler 判断是否刷新补全 |

### 装配流程（在 `input_prompt_toolkit.py` 中）

```python
from .repl_clipboard import capture_clipboard_tag, copy_to_clipboard, extract_images_from_text
from .repl_completers import create_repl_completer, AT_TOKEN_PATTERN
from .repl_key_bindings import create_key_bindings

class PromptToolkitInput(InputProviderABC):
    def __init__(self, ...):
        # Create key bindings with injected dependencies
        kb = create_key_bindings(
            capture_clipboard_tag=capture_clipboard_tag,
            copy_to_clipboard=copy_to_clipboard,
            at_token_pattern=AT_TOKEN_PATTERN,
        )
        
        # Create completer
        completer = ThreadedCompleter(create_repl_completer())
        
        # Create session with assembled components
        self._session = PromptSession(
            ...,
            key_bindings=kb,
            completer=completer,
            ...
        )
```

### 验证：无循环依赖

**模块 import 关系（单向）：**

```
input_prompt_toolkit.py
    ↓ imports
repl_clipboard.py ←── NO cross imports ──→ repl_completers.py
                          ↑
                    repl_key_bindings.py
                    (no imports from sibling modules)
```

**关键约束：**

1. `repl_key_bindings.py` 仅 import `prompt_toolkit` 相关类型，不 import 任何 `repl_*` 兄弟模块
2. `repl_completers.py` 仅依赖 `klaude_code.command`（获取命令列表），不依赖 `repl_*` 模块
3. `repl_clipboard.py` 仅依赖 `klaude_code.protocol.model`（`ImageURLPart` 类型），不依赖 `repl_*` 模块
4. `input_prompt_toolkit.py` 作为装配者，统一 import 三个子模块并组装

---

## Phase 2：补全模块 `repl_completers.py`

- [x] P2-1（M）：创建文件并迁移 `_CmdResult`、`_SlashCommandCompleter`、`_AtFilesCompleter`、`_ComboCompleter`
  - 接受标准：新文件可被导入，类型检查通过，无循环依赖。
  - 完成时间：2025-11-29

- [x] P2-2（S）：实现 `create_repl_completer()` 与 `AT_TOKEN_PATTERN`
  - 接受标准：使用 `PromptSession`+`create_repl_completer()` 手动测试能出现与当前一致的补全行为。
  - 完成时间：2025-11-29

- [x] P2-3（S）：更新 `input_prompt_toolkit.py` 使用新补全工厂
  - 接受标准：`input_prompt_toolkit.py` 不再包含上述类定义，对 `_AtFilesCompleter` 无直接引用。
  - 完成时间：2025-11-29

## Phase 3：剪贴板与图片模块 `repl_clipboard.py`

- [x] P3-1（M）：创建文件并迁移剪贴板状态类与常量
  - 接受标准：`ClipboardCaptureState`、`CLIPBOARD_IMAGES_DIR`、`_IMAGE_TAG_RE`、图片保存逻辑全部在新模块中集中管理。
  - 完成时间：2025-11-29

- [x] P3-2（M）：实现 `capture_clipboard_tag` / `extract_images_from_text` / `copy_to_clipboard`
  - 接受标准：小脚本调用这些函数能工作（在平台支持下），对 prompt_toolkit 无依赖。
  - 完成时间：2025-11-29

- [x] P3-3（S）：切换 `PromptToolkitInput` 中的图片提取逻辑
  - 接受标准：`iter_inputs` 使用 `extract_images_from_text`；类内不再有 `_encode_image_file` 与 `_extract_images_from_text`。
  - 完成时间：2025-11-29

## Phase 4：键盘绑定模块 `repl_key_bindings.py`

- [x] P4-1（M）：设计并实现 `create_key_bindings(...)`
  - 接受标准：工厂函数签名固定且只依赖抽象 callable / pattern，无项目内部模块直接 import。
  - 完成时间：2025-11-29

- [x] P4-2（L）：迁移所有 `@kb.add(...)` handler 到新模块
  - 接受标准：`input_prompt_toolkit.py` 中不再定义 `kb` 和 handler；REPL 中所有快捷键行为通过手动测试与当前版本一致。
  - 完成时间：2025-11-29

- [x] P4-3（S）：在 `PromptToolkitInput` 中组装补全与键盘绑定
  - 接受标准：`PromptSession` 构造使用 `ThreadedCompleter(create_repl_completer())` 和 `create_key_bindings(...)`，类型检查无误。
  - 完成时间：2025-11-29

## Phase 5：清理与验证

- [ ] P5-1（S）：清理 import 并运行格式化
  - 接受标准：`uv run isort . && uv run ruff format` 成功，无未使用 import 警告。

- [ ] P5-2（M）：自动化测试与手动回归
  - 接受标准：`uv run pytest` 通过（或至少与基线一致）；手动验证：
    - [ ] 单行输入提交；
    - [ ] 多行输入（含 VS Code Shift+Enter sentinel）；
    - [ ] `/` 命令补全；
    - [ ] `@` 路径补全；
    - [ ] 图片复制 + `Ctrl+V` 插入 `[Image #N]`；
    - [ ] `c` 复制和字符输入行为；
    - [ ] `Backspace` 删除 + 补全刷新；
    - [ ] 左右方向键跨行移动。
