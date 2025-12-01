# Codex Prompt Sync Tasks

Last Updated: 2025-12-01

## Progress Overview

| Phase | Status | Progress |
|-------|--------|----------|
| Phase 1: Prompt 同步核心 | Not Started | 0/5 |
| Phase 2: 客户端集成 | Not Started | 0/2 |
| Phase 3: CLI 命令 | Not Started | 0/3 |

---

## Phase 1: Prompt 同步核心 (P0)

### 1.1 创建 prompt_sync 模块
- **Status**: [ ] Not Started
- **Effort**: S
- **Dependencies**: None

**File**: `src/klaude_code/auth/codex/prompt_sync.py`

**Tasks**:
- [ ] 定义常量:
  ```python
  GITHUB_API_BASE = "https://api.github.com"
  GITHUB_RAW_BASE = "https://raw.githubusercontent.com"
  CODEX_REPO = "openai/codex"
  RELEASES_URL = f"{GITHUB_API_BASE}/repos/{CODEX_REPO}/releases/latest"
  
  PROMPT_FILES = {
      "codex": "gpt_5_codex_prompt.md",
      "codex-max": "gpt-5.1-codex-max_prompt.md",
      "gpt-5.1": "gpt_5_1_prompt.md",
  }
  
  PROMPTS_CACHE_DIR = Path.home() / ".klaude" / "codex-prompts"
  ```
- [ ] 定义 Pydantic 模型:
  - `PromptFileInfo`
  - `PromptCacheMetadata`
  - `PromptSyncStatus`
- [ ] 运行 `uv run pyright` 确认无错误

---

### 1.2 实现版本检查
- **Status**: [ ] Not Started
- **Effort**: S
- **Dependencies**: 1.1

**Tasks**:
- [ ] 实现 `_get_latest_tag() -> str | None`:
  ```python
  async def _get_latest_tag(self) -> str | None:
      async with httpx.AsyncClient() as client:
          resp = await client.get(RELEASES_URL)
          if resp.status_code == 200:
              return resp.json()["tag_name"]
          return None
  ```
- [ ] 处理网络超时 (5 秒)
- [ ] 处理 rate limit (403)
- [ ] 运行 `uv run pyright` 确认无错误

---

### 1.3 实现 Prompt 下载
- **Status**: [ ] Not Started
- **Effort**: M
- **Dependencies**: 1.2

**Tasks**:
- [ ] 实现 `_get_prompt_url(tag: str, prompt_type: str) -> str`
- [ ] 实现 `_download_prompt(tag: str, prompt_type: str) -> str`:
  ```python
  async def _download_prompt(self, tag: str, prompt_type: str) -> str:
      url = self._get_prompt_url(tag, prompt_type)
      async with httpx.AsyncClient() as client:
          resp = await client.get(url)
          resp.raise_for_status()
          return resp.text
  ```
- [ ] 处理 404 (文件不存在)
- [ ] 处理网络超时
- [ ] 运行 `uv run pyright` 确认无错误

---

### 1.4 实现缓存管理
- **Status**: [ ] Not Started
- **Effort**: M
- **Dependencies**: 1.3

**Tasks**:
- [ ] 实现 `PromptCache` 类:
  - [ ] `__init__(cache_dir: Path = PROMPTS_CACHE_DIR)`
  - [ ] `get(prompt_type: str) -> str | None` - 从缓存读取
  - [ ] `save(prompt_type: str, content: str, version: str)` - 保存到缓存
  - [ ] `get_version() -> str | None` - 获取当前版本
  - [ ] `get_updated_at() -> int | None` - 获取最后更新时间
  - [ ] `_load_metadata() -> PromptCacheMetadata | None`
  - [ ] `_save_metadata(metadata: PromptCacheMetadata)`
- [ ] 确保目录创建 (`cache_dir.mkdir(parents=True, exist_ok=True)`)
- [ ] 计算文件 SHA256 用于验证
- [ ] 运行 `uv run pyright` 确认无错误

---

### 1.5 实现主同步逻辑
- **Status**: [ ] Not Started
- **Effort**: M
- **Dependencies**: 1.4

**Tasks**:
- [ ] 实现 `CodexPromptSync` 类:
  - [ ] `__init__()`
  - [ ] `get_prompt(prompt_type: str, force_update: bool = False) -> str`
    - 检查缓存
    - 如果无缓存或 force_update，下载新版本
    - 下载失败时回退到缓存
    - 无缓存且下载失败时抛出错误
  - [ ] `update_all() -> bool` - 更新所有 Prompt
  - [ ] `get_status() -> PromptSyncStatus` - 返回当前状态
- [ ] 实现 `get_prompt_type_for_model(model: str) -> str`
- [ ] 运行 `uv run pyright` 确认无错误

---

## Phase 2: 客户端集成 (P0)

### 2.1 修改 CodexClient 使用官方 Prompt
- **Status**: [ ] Not Started
- **Effort**: M
- **Dependencies**: Phase 1 Complete

**File**: `src/klaude_code/llm/codex/client.py`

**Tasks**:
- [ ] 导入 `CodexPromptSync` 和 `get_prompt_type_for_model`
- [ ] 在 `__init__` 中初始化:
  ```python
  self._prompt_sync = CodexPromptSync()
  ```
- [ ] 修改 `call()` 方法:
  ```python
  # Resolve instructions
  instructions = param.system
  if not instructions:
      prompt_type = get_prompt_type_for_model(str(param.model))
      try:
          instructions = self._prompt_sync.get_prompt(prompt_type)
      except Exception as e:
          log_debug(f"Failed to get official prompt: {e}")
          # Continue without official prompt
  ```
- [ ] 将 `instructions` 传递给 API 调用
- [ ] 运行 `uv run pyright` 确认无错误

---

### 2.2 添加同步方法包装
- **Status**: [ ] Not Started
- **Effort**: S
- **Dependencies**: 2.1

**Tasks**:
- [ ] 由于 `get_prompt` 是同步的，确保不阻塞事件循环
- [ ] 考虑使用 `asyncio.to_thread` 如果需要
- [ ] 或者保持同步（因为主要是文件读取）
- [ ] 运行 `uv run pyright` 确认无错误

---

## Phase 3: CLI 命令 (P1)

### 3.1 实现 update-prompt 命令
- **Status**: [ ] Not Started
- **Effort**: S
- **Dependencies**: Phase 1 Complete

**File**: `src/klaude_code/cli/main.py`

**Tasks**:
- [ ] 创建 `codex_app = typer.Typer(help="Codex management commands")`
- [ ] 实现命令:
  ```python
  @codex_app.command("update-prompt")
  def update_prompt() -> None:
      """Update Codex prompts from GitHub."""
      from klaude_code.auth.codex.prompt_sync import CodexPromptSync
      
      sync = CodexPromptSync()
      log("Checking for Codex prompt updates...")
      
      try:
          status_before = sync.get_status()
          updated = sync.update_all()
          status_after = sync.get_status()
          
          if updated:
              log(f"Updated: {status_before.cached_version} -> {status_after.cached_version}")
          else:
              log(f"Already up to date: {status_after.cached_version}")
      except Exception as e:
          log(f"Update failed: {e}", style="red")
          raise typer.Exit(1)
  ```
- [ ] 注册: `app.add_typer(codex_app, name="codex")`
- [ ] 运行 `uv run pyright` 确认无错误

---

### 3.2 实现 prompt-status 命令
- **Status**: [ ] Not Started
- **Effort**: S
- **Dependencies**: 3.1

**Tasks**:
- [ ] 实现命令:
  ```python
  @codex_app.command("prompt-status")
  def prompt_status() -> None:
      """Show Codex prompt cache status."""
      from klaude_code.auth.codex.prompt_sync import CodexPromptSync
      import time
      
      sync = CodexPromptSync()
      status = sync.get_status()
      
      log(f"Cached version: {status.cached_version or 'Not cached'}")
      
      if status.last_updated:
          updated_str = time.strftime("%Y-%m-%d %H:%M:%S", 
                                       time.localtime(status.last_updated))
          log(f"Last updated: {updated_str}")
      else:
          log("Last updated: Never")
      
      if status.cached_files:
          log(f"Cached prompts: {', '.join(status.cached_files)}")
      else:
          log("Cached prompts: None")
  ```
- [ ] 运行 `uv run pyright` 确认无错误

---

### 3.3 集成到 list 命令 (可选)
- **Status**: [ ] Not Started
- **Effort**: S
- **Dependencies**: 3.2

**Tasks**:
- [ ] 在 `display_models_and_providers()` 中添加 Codex Prompt 信息
- [ ] 或在 Codex provider 行显示 prompt 版本
- [ ] 运行 `uv run pyright` 确认无错误

---

## Quick Reference Commands

```bash
# 类型检查
uv run pyright

# 格式化
uv run isort . && uv run ruff format

# 运行测试
uv run pytest

# 运行 CLI (实现后)
uv run klaude codex update-prompt
uv run klaude codex prompt-status
```

---

## Notes & Blockers

### Notes
- GitHub API 未认证限制 60 requests/hour
- Prompt 文件通常几 KB，下载很快
- 缓存使用明文存储，与 token 一致

### Blockers
- (记录遇到的阻塞问题)

### Questions
- (记录需要确认的问题)
