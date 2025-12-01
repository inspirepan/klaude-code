# Codex Prompt Sync Context

Last Updated: 2025-12-01

## Key Files Reference

### 需要新增的文件

| 文件路径 | 用途 | 依赖 |
|---------|------|------|
| `src/klaude_code/auth/codex/prompt_sync.py` | Prompt 同步逻辑 | httpx |

### 需要修改的文件

| 文件路径 | 修改内容 |
|---------|---------|
| `src/klaude_code/llm/codex/client.py` | 集成官方 Prompt 获取 |
| `src/klaude_code/cli/main.py` | 新增 update-prompt 命令 |

### 关键参考文件

| 文件路径 | 参考用途 |
|---------|---------|
| `src/klaude_code/auth/codex/token_manager.py` | 参考文件存储模式 |
| `src/klaude_code/llm/codex/client.py` | 理解当前 Prompt 使用方式 |

---

## GitHub API Constants

```python
# GitHub API 端点
GITHUB_API_BASE = "https://api.github.com"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com"

# 仓库信息
CODEX_REPO_OWNER = "openai"
CODEX_REPO_NAME = "codex"

# API 端点
RELEASES_LATEST_URL = f"{GITHUB_API_BASE}/repos/{CODEX_REPO_OWNER}/{CODEX_REPO_NAME}/releases/latest"

# Prompt 文件映射
PROMPT_FILES = {
    "codex": "gpt_5_codex_prompt.md",
    "codex-max": "gpt-5.1-codex-max_prompt.md",
    "gpt-5.1": "gpt_5_1_prompt.md",
}

# Prompt 文件在仓库中的路径
PROMPT_PATH_TEMPLATE = "codex-rs/core/{filename}"

def get_prompt_url(tag: str, prompt_type: str) -> str:
    """Get raw GitHub URL for a prompt file."""
    filename = PROMPT_FILES.get(prompt_type, PROMPT_FILES["codex"])
    path = PROMPT_PATH_TEMPLATE.format(filename=filename)
    return f"{GITHUB_RAW_BASE}/{CODEX_REPO_OWNER}/{CODEX_REPO_NAME}/{tag}/{path}"
```

---

## Model to Prompt Type Mapping

```python
def get_prompt_type_for_model(model: str) -> str:
    """Map model name to prompt type."""
    model_lower = model.lower()
    
    if "codex-max" in model_lower:
        return "codex-max"
    elif "codex-mini" in model_lower:
        return "codex"  # mini uses same prompt as codex
    elif "codex" in model_lower:
        return "codex"
    elif "gpt-5.1" in model_lower:
        return "gpt-5.1"
    else:
        return "codex"  # default
```

---

## Data Models

### 缓存元数据 (`~/.klaude/codex-prompts/metadata.json`)

```json
{
  "version": "v0.1.2025052900",
  "updated_at": 1701432000,
  "files": {
    "codex": {
      "filename": "gpt_5_codex_prompt.md",
      "sha256": "abc123..."
    },
    "codex-max": {
      "filename": "gpt-5.1-codex-max_prompt.md",
      "sha256": "def456..."
    },
    "gpt-5.1": {
      "filename": "gpt_5_1_prompt.md",
      "sha256": "ghi789..."
    }
  }
}
```

### Pydantic Models

```python
from pathlib import Path
from pydantic import BaseModel

PROMPTS_CACHE_DIR = Path.home() / ".klaude" / "codex-prompts"
METADATA_FILE = PROMPTS_CACHE_DIR / "metadata.json"


class PromptFileInfo(BaseModel):
    filename: str
    sha256: str


class PromptCacheMetadata(BaseModel):
    version: str
    updated_at: int  # Unix timestamp
    files: dict[str, PromptFileInfo]


class PromptSyncStatus(BaseModel):
    cached_version: str | None
    latest_version: str | None
    is_up_to_date: bool
    last_updated: int | None  # Unix timestamp
    cached_files: list[str]
```

---

## Key Decisions

### D1: Prompt 使用策略

**决定**: 仅当用户未提供自定义 system prompt 时使用官方 Prompt

**实现**:
```python
async def call(self, param: LLMCallParameter) -> AsyncGenerator[...]:
    # If no custom system prompt, use official Codex prompt
    if not param.system:
        prompt_type = get_prompt_type_for_model(str(param.model))
        param.system = self._prompt_sync.get_prompt(prompt_type)
    
    # Continue with API call...
```

### D2: 缓存更新策略

**决定**: 手动更新为主，首次使用自动下载

**实现**:
```python
def get_prompt(self, prompt_type: str, force_update: bool = False) -> str:
    # Try cache first
    cached = self._cache.get(prompt_type)
    
    if cached and not force_update:
        return cached
    
    # Download if no cache or force update
    try:
        tag = self._get_latest_tag()
        content = self._download_prompt(tag, prompt_type)
        self._cache.save(prompt_type, content, tag)
        return content
    except Exception:
        # Fall back to cache if download fails
        if cached:
            return cached
        raise
```

### D3: 错误处理

**决定**: 优雅降级

```python
# 优先级:
# 1. 尝试获取最新版本
# 2. 如果失败，使用缓存
# 3. 如果无缓存，抛出错误并提示用户
```

---

## Integration Points

### CodexClient 集成

```python
# src/klaude_code/llm/codex/client.py

class CodexClient(LLMClientABC):
    def __init__(self, config: LLMConfigParameter):
        super().__init__(config)
        self._token_manager = CodexTokenManager()
        self._oauth = CodexOAuth(self._token_manager)
        self._prompt_sync = CodexPromptSync()  # NEW
        
        if not self._token_manager.is_logged_in():
            raise CodexNotLoggedInError(...)
        
        self.client = self._create_client()
    
    async def call(self, param: LLMCallParameter) -> AsyncGenerator[...]:
        # ... existing code ...
        
        # NEW: Use official prompt if no custom prompt
        instructions = param.system
        if not instructions:
            prompt_type = get_prompt_type_for_model(str(param.model))
            instructions = self._prompt_sync.get_prompt(prompt_type)
        
        stream = await call_with_logged_payload(
            self.client.responses.create,
            ...
            instructions=instructions,  # Use resolved prompt
            ...
        )
```

### CLI 集成

```python
# src/klaude_code/cli/main.py

@app.command("codex")
def codex_commands() -> None:
    """Codex-related commands."""
    pass

# Or as subcommands:
codex_app = typer.Typer(help="Codex management commands")

@codex_app.command("update-prompt")
def update_prompt() -> None:
    """Update Codex prompts from GitHub."""
    from klaude_code.auth.codex.prompt_sync import CodexPromptSync
    
    sync = CodexPromptSync()
    log("Checking for updates...")
    
    try:
        updated = sync.update_all()
        if updated:
            log(f"Updated to version {sync.get_status().cached_version}")
        else:
            log("Already up to date")
    except Exception as e:
        log(f"Update failed: {e}", style="red")

@codex_app.command("prompt-status")
def prompt_status() -> None:
    """Show Codex prompt cache status."""
    from klaude_code.auth.codex.prompt_sync import CodexPromptSync
    
    sync = CodexPromptSync()
    status = sync.get_status()
    
    log(f"Cached version: {status.cached_version or 'None'}")
    log(f"Last updated: {format_timestamp(status.last_updated)}")
    log(f"Cached files: {', '.join(status.cached_files)}")

app.add_typer(codex_app, name="codex")
```

---

## Error Handling

### 异常类型

```python
class PromptSyncError(Exception):
    """Base exception for prompt sync errors."""
    pass

class PromptNotFoundError(PromptSyncError):
    """Prompt file not found on GitHub."""
    pass

class PromptNetworkError(PromptSyncError):
    """Network error during prompt sync."""
    pass
```

### 错误处理流程

```
get_prompt() 调用
    |
    v
检查缓存 --有--> 返回缓存内容
    |
    无
    v
下载最新版本 --成功--> 保存缓存 --> 返回内容
    |
    失败
    v
有缓存? --是--> 返回缓存内容 (warn)
    |
    否
    v
抛出 PromptSyncError
```

---

## Testing Strategy

### 单元测试

```python
# tests/auth/codex/test_prompt_sync.py

def test_get_prompt_type_for_model():
    assert get_prompt_type_for_model("gpt-5.1-codex") == "codex"
    assert get_prompt_type_for_model("gpt-5.1-codex-max") == "codex-max"
    assert get_prompt_type_for_model("gpt-5.1") == "gpt-5.1"

def test_cache_save_and_load(tmp_path):
    cache = PromptCache(cache_dir=tmp_path)
    cache.save("codex", "test content", "v1.0.0")
    assert cache.get("codex") == "test content"

def test_cache_metadata(tmp_path):
    cache = PromptCache(cache_dir=tmp_path)
    cache.save("codex", "content", "v1.0.0")
    assert cache.get_version() == "v1.0.0"
```

### 集成测试

```python
@pytest.mark.network
def test_fetch_latest_release():
    sync = CodexPromptSync()
    tag = sync._get_latest_tag()
    assert tag.startswith("v")

@pytest.mark.network
def test_download_prompt():
    sync = CodexPromptSync()
    content = sync.get_prompt("codex", force_update=True)
    assert len(content) > 0
    assert "codex" in content.lower() or "assistant" in content.lower()
```

---

## File Structure After Implementation

```
~/.klaude/
├── klaude-config.yaml
├── codex-auth.json
└── codex-prompts/
    ├── metadata.json
    ├── gpt_5_codex_prompt.md
    ├── gpt-5.1-codex-max_prompt.md
    └── gpt_5_1_prompt.md

src/klaude_code/
├── auth/
│   └── codex/
│       ├── __init__.py
│       ├── exceptions.py
│       ├── jwt_utils.py
│       ├── oauth.py
│       ├── token_manager.py
│       └── prompt_sync.py      # NEW
├── llm/
│   └── codex/
│       ├── __init__.py
│       └── client.py           # MODIFIED
└── cli/
    └── main.py                 # MODIFIED
```
