# Codex Integration Tasks

Last Updated: 2025-12-01

## Progress Overview

| Phase | Status | Progress |
|-------|--------|----------|
| Phase 1: OAuth 认证基础设施 | Completed | 5/5 |
| Phase 2: Codex 客户端实现 | Completed | 4/4 |
| Phase 3: CLI 集成 | Completed | 4/4 |
| Phase 4: 测试与文档 | Not Started | 0/3 |

---

## Phase 1: OAuth 认证基础设施 (P0)

### 1.1 创建 auth 模块结构
- **Status**: [ ] Not Started
- **Effort**: S
- **Dependencies**: None

**Tasks**:
- [ ] 创建 `src/klaude_code/auth/__init__.py`
- [ ] 创建 `src/klaude_code/auth/jwt_utils.py` (空文件)
- [ ] 创建 `src/klaude_code/auth/token_manager.py` (空文件)
- [ ] 创建 `src/klaude_code/auth/oauth.py` (空文件)
- [ ] 创建 `src/klaude_code/auth/exceptions.py`
- [ ] 运行 `uv run pyright` 确认无错误

---

### 1.2 实现 JWT 解析工具
- **Status**: [ ] Not Started
- **Effort**: S
- **Dependencies**: 1.1

**File**: `src/klaude_code/auth/jwt_utils.py`

**Tasks**:
- [ ] 实现 `decode_jwt_payload(token: str) -> dict[str, Any]`
  - 使用 base64 解码 JWT payload 部分
  - 处理 padding 问题
- [ ] 实现 `extract_account_id(token: str) -> str`
  - 从 JWT 中提取 `https://api.openai.com/auth.chatgpt_account_id`
- [ ] 添加类型注解
- [ ] 运行 `uv run pyright` 确认无错误

---

### 1.3 实现 Token 存储与加载
- **Status**: [ ] Not Started
- **Effort**: M
- **Dependencies**: 1.1

**File**: `src/klaude_code/auth/token_manager.py`

**Tasks**:
- [ ] 定义 `CodexAuthState` Pydantic 模型
  ```python
  class CodexAuthState(BaseModel):
      access_token: str
      refresh_token: str
      expires_at: int
      account_id: str
  ```
- [ ] 定义常量 `CODEX_AUTH_FILE = Path.home() / ".klaude" / "codex-auth.json"`
- [ ] 实现 `CodexTokenManager` 类
  - [ ] `load() -> CodexAuthState | None` - 从文件加载
  - [ ] `save(state: CodexAuthState) -> None` - 保存到文件
  - [ ] `delete() -> None` - 删除 token 文件
  - [ ] `is_logged_in() -> bool` - 检查是否已登录
  - [ ] `is_expired(buffer_seconds: int = 300) -> bool` - 检查是否过期
  - [ ] `get_access_token() -> str` - 获取 access token (如需刷新则刷新)
  - [ ] `get_account_id() -> str` - 获取 account id
- [ ] 运行 `uv run pyright` 确认无错误

---

### 1.4 实现 OAuth PKCE 流程
- **Status**: [ ] Not Started
- **Effort**: L
- **Dependencies**: 1.2, 1.3

**File**: `src/klaude_code/auth/oauth.py`

**Constants**:
```python
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
REDIRECT_URI = "http://localhost:1455/auth/callback"
REDIRECT_PORT = 1455
SCOPE = "openid profile email offline_access"
```

**Tasks**:
- [ ] 实现 PKCE 生成
  - [ ] `generate_code_verifier() -> str` - 生成随机 verifier
  - [ ] `generate_code_challenge(verifier: str) -> str` - SHA256 + base64url
- [ ] 实现 `build_authorize_url(code_challenge: str, state: str) -> str`
  - 包含所有必要参数: `response_type`, `client_id`, `redirect_uri`, `scope`, `code_challenge`, `code_challenge_method`, `state`, `id_token_add_organizations`, `codex_cli_simplified_flow`, `originator`
- [ ] 实现本地回调服务器
  - [ ] `start_callback_server() -> tuple[str, str]` - 返回 (code, state)
  - 使用 `http.server` 或 `aiohttp`
  - 监听 `localhost:1455`
  - 解析回调 URL 获取 `code` 和 `state`
  - 返回 HTML 页面通知用户关闭窗口
- [ ] 实现 `exchange_code_for_tokens(code: str, verifier: str) -> CodexAuthState`
  - POST 请求到 TOKEN_URL
  - 解析响应获取 tokens
  - 从 access_token 提取 account_id
  - 计算 expires_at
- [ ] 实现 `async def login() -> CodexAuthState` 主流程
  - 生成 PKCE
  - 构建授权 URL
  - 打开浏览器
  - 启动回调服务器等待
  - 换取 tokens
  - 保存到文件
- [ ] 运行 `uv run pyright` 确认无错误

---

### 1.5 实现 Token 刷新逻辑
- **Status**: [ ] Not Started
- **Effort**: M
- **Dependencies**: 1.3, 1.4

**File**: `src/klaude_code/auth/token_manager.py` (继续)

**Tasks**:
- [ ] 在 `CodexTokenManager` 中添加 `async refresh() -> CodexAuthState`
  - POST 请求到 TOKEN_URL
  - 使用 `grant_type=refresh_token`
  - 更新存储的 tokens
- [ ] 修改 `get_access_token()` 为 `async get_access_token()`
  - 检查是否过期
  - 如需刷新则调用 `refresh()`
  - 刷新失败时抛出 `CodexTokenExpiredError`
- [ ] 运行 `uv run pyright` 确认无错误

---

## Phase 2: Codex 客户端实现 (P0)

### 2.1 扩展 LLMClientProtocol 枚举
- **Status**: [ ] Not Started
- **Effort**: S
- **Dependencies**: None

**File**: `src/klaude_code/protocol/llm_param.py`

**Tasks**:
- [ ] 在 `LLMClientProtocol` 枚举中添加:
  ```python
  CODEX = "codex"
  ```
- [ ] 运行 `uv run pyright` 确认无错误

---

### 2.2 创建 Codex 客户端模块
- **Status**: [ ] Not Started
- **Effort**: S
- **Dependencies**: 2.1

**Tasks**:
- [ ] 创建 `src/klaude_code/llm/codex/__init__.py`
- [ ] 创建 `src/klaude_code/llm/codex/client.py` (空文件)
- [ ] 运行 `uv run pyright` 确认无错误

---

### 2.3 实现 CodexClient 类
- **Status**: [ ] Not Started
- **Effort**: M
- **Dependencies**: 1.5, 2.2

**File**: `src/klaude_code/llm/codex/client.py`

**Tasks**:
- [ ] 导入依赖
  ```python
  from klaude_code.llm.responses.client import ResponsesClient
  from klaude_code.llm.client import LLMClientABC
  from klaude_code.llm.registry import register
  from klaude_code.auth.token_manager import CodexTokenManager
  from klaude_code.auth.exceptions import CodexNotLoggedInError
  ```
- [ ] 定义常量
  ```python
  CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
  CODEX_HEADERS = {
      "OpenAI-Beta": "responses=experimental",
      "originator": "codex_cli_rs",
      "User-Agent": "GitHubCopilotChat/0.32.4",
  }
  ```
- [ ] 实现 `CodexClient` 类
  - [ ] 使用 `@register(LLMClientProtocol.CODEX)` 装饰器
  - [ ] `__init__`: 初始化 TokenManager，检查登录状态，创建 OpenAI client
  - [ ] `_create_client()`: 创建带有正确 headers 的 AsyncOpenAI 实例
  - [ ] 覆写 `call()` 方法:
    - 调用前确保 token 有效
    - 强制 `param.store = False`
    - 调用 `super().call()`
- [ ] 运行 `uv run pyright` 确认无错误

---

### 2.4 更新 LLM 模块导出
- **Status**: [ ] Not Started
- **Effort**: S
- **Dependencies**: 2.3

**File**: `src/klaude_code/llm/__init__.py`

**Tasks**:
- [ ] 添加 codex 模块导入以触发注册:
  ```python
  from klaude_code.llm import codex  # noqa: F401
  ```
- [ ] 运行 `uv run pyright` 确认无错误

---

## Phase 3: CLI 集成 (P1)

### 3.1 实现 login 命令
- **Status**: [ ] Not Started
- **Effort**: M
- **Dependencies**: Phase 1 Complete

**File**: `src/klaude_code/cli/main.py`

**Tasks**:
- [ ] 创建 `auth_app = typer.Typer(help="Authentication commands")`
- [ ] 实现 `login` 命令:
  ```python
  @auth_app.command("login")
  def auth_login(
      provider: str = typer.Argument("codex", help="Provider to login (codex)")
  ) -> None:
  ```
  - 调用 OAuth 流程
  - 显示登录结果
- [ ] 注册到主 app: `app.add_typer(auth_app, name="auth")`
- [ ] 或者作为顶级命令: `@app.command("login")`
- [ ] 运行 `uv run pyright` 确认无错误

---

### 3.2 实现 logout 命令
- **Status**: [ ] Not Started
- **Effort**: S
- **Dependencies**: 3.1

**File**: `src/klaude_code/cli/main.py`

**Tasks**:
- [ ] 实现 `logout` 命令:
  ```python
  @app.command("logout")
  def auth_logout(
      provider: str = typer.Argument("codex", help="Provider to logout (codex)")
  ) -> None:
  ```
  - 确认提示
  - 删除 token 文件
  - 显示结果
- [ ] 运行 `uv run pyright` 确认无错误

---

### 3.3 实现 status 命令集成
- **Status**: [ ] Not Started
- **Effort**: S
- **Dependencies**: 3.1

**File**: `src/klaude_code/config/list_model.py` 或 `cli/main.py`

**Tasks**:
- [ ] 在 `klaude list` 输出中添加 Codex 登录状态
- [ ] 显示信息:
  - 是否已登录
  - Token 过期时间
  - Account ID (部分掩码)
- [ ] 运行 `uv run pyright` 确认无错误

---

### 3.4 登录状态检查集成
- **Status**: [ ] Not Started
- **Effort**: M
- **Dependencies**: 2.3

**Tasks**:
- [ ] 在 `CodexClient.__init__` 中:
  - 检查是否已登录
  - 未登录时抛出 `CodexNotLoggedInError` 并附带提示信息
- [ ] 在 CLI runtime 中捕获此异常并友好显示
- [ ] 运行 `uv run pyright` 确认无错误

---

## Phase 4: 测试与文档 (P2)

### 4.1 单元测试
- **Status**: [ ] Not Started
- **Effort**: M
- **Dependencies**: Phase 2 Complete

**Tasks**:
- [ ] `tests/auth/test_jwt_utils.py`
  - [ ] test_decode_jwt_payload
  - [ ] test_extract_account_id
  - [ ] test_invalid_jwt_handling
- [ ] `tests/auth/test_token_manager.py`
  - [ ] test_save_and_load
  - [ ] test_is_expired
  - [ ] test_delete
- [ ] `tests/llm/codex/test_client.py`
  - [ ] test_client_init_not_logged_in
  - [ ] test_headers_setup
- [ ] 运行 `uv run pytest` 确认通过

---

### 4.2 集成测试
- **Status**: [ ] Not Started
- **Effort**: L
- **Dependencies**: Phase 3 Complete

**Tasks**:
- [ ] `tests/auth/test_oauth_integration.py`
  - [ ] test_full_login_flow (需要真实账号，标记 @pytest.mark.network)
- [ ] `tests/llm/codex/test_api_integration.py`
  - [ ] test_api_call (需要真实账号，标记 @pytest.mark.network)
- [ ] 手动测试完整流程

---

### 4.3 更新示例配置
- **Status**: [ ] Not Started
- **Effort**: S
- **Dependencies**: 2.1

**File**: `src/klaude_code/config/config.py`

**Tasks**:
- [ ] 在 `get_example_config()` 中添加 Codex 配置示例 (注释形式)
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

# 运行特定测试
uv run pytest tests/auth/

# 运行 CLI
uv run klaude --help
uv run klaude login codex
uv run klaude list
```

---

## Notes & Blockers

### Notes
- (记录实现过程中的发现和决定)

### Blockers
- (记录遇到的阻塞问题)

### Questions
- (记录需要确认的问题)
