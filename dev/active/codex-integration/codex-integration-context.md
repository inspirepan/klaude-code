# Codex Integration Context

Last Updated: 2025-12-01

## Key Files Reference

### 需要新增的文件

| 文件路径 | 用途 | 依赖 |
|---------|------|------|
| `src/klaude_code/auth/__init__.py` | Auth 模块导出 | - |
| `src/klaude_code/auth/exceptions.py` | 认证异常定义 | - |
| `src/klaude_code/auth/jwt_utils.py` | JWT 解析工具 | 标准库 |
| `src/klaude_code/auth/token_manager.py` | Token 存储与刷新 | jwt_utils |
| `src/klaude_code/auth/oauth.py` | OAuth PKCE 流程 | token_manager |
| `src/klaude_code/llm/codex/__init__.py` | Codex 模块导出 | - |
| `src/klaude_code/llm/codex/client.py` | Codex API 客户端 | auth, responses |

### 需要修改的文件

| 文件路径 | 修改内容 |
|---------|---------|
| `src/klaude_code/protocol/llm_param.py` | 新增 `CODEX = "codex"` 枚举值 |
| `src/klaude_code/llm/__init__.py` | 导入 codex 模块 |
| `src/klaude_code/cli/main.py` | 新增 login/logout 命令 |
| `src/klaude_code/config/config.py` | 示例配置添加 Codex |

### 关键参考文件

| 文件路径 | 参考用途 |
|---------|---------|
| `src/klaude_code/llm/responses/client.py` | 复用 API 调用逻辑 |
| `src/klaude_code/llm/responses/input.py` | 直接复用消息转换 |
| `src/klaude_code/llm/registry.py` | 理解注册机制 |
| `src/klaude_code/llm/client.py` | 理解基类接口 |

---

## OAuth Constants (from opencode)

```python
# OAuth 配置
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
REDIRECT_URI = "http://localhost:1455/auth/callback"
SCOPE = "openid profile email offline_access"

# API 配置
API_BASE_URL = "https://chatgpt.com/backend-api/codex"

# 必需 Headers
REQUIRED_HEADERS = {
    "OpenAI-Beta": "responses=experimental",
    "originator": "codex_cli_rs",
    "User-Agent": "GitHubCopilotChat/0.32.4",
}

# JWT claim path for account ID
ACCOUNT_ID_CLAIM = "https://api.openai.com/auth"
ACCOUNT_ID_KEY = "chatgpt_account_id"
```

---

## Data Models

### Token 存储格式 (`~/.klaude/codex-auth.json`)

```json
{
  "access_token": "eyJ...",
  "refresh_token": "...",
  "expires_at": 1701432000,
  "account_id": "user-xxxx"
}
```

### Pydantic Model

```python
from pydantic import BaseModel

class CodexAuthState(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: int  # Unix timestamp
    account_id: str
    
    def is_expired(self, buffer_seconds: int = 300) -> bool:
        """Check if token is expired or will expire soon."""
        import time
        return time.time() + buffer_seconds >= self.expires_at
```

---

## API Request Format

### Codex API 请求示例

```python
# Headers
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json",
    "OpenAI-Beta": "responses=experimental",
    "chatgpt-account-id": account_id,
    "originator": "codex_cli_rs",
    "User-Agent": "GitHubCopilotChat/0.32.4",
}

# Request body (与 Responses API 完全相同)
body = {
    "model": "gpt-5.1-codex",
    "store": False,  # 必须为 False
    "stream": True,
    "instructions": "...",
    "input": [...],
    "reasoning": {
        "effort": "medium",
        "summary": "auto"
    },
    "text": {
        "verbosity": "medium"
    },
    "include": ["reasoning.encrypted_content"]
}
```

---

## Key Decisions

### D1: 客户端实现方式

**决定**: 继承 `ResponsesClient` 而非组合

**理由**:
- 事件处理逻辑完全相同
- 仅需覆盖 `__init__` 和客户端创建
- 代码复用最大化

**实现**:
```python
@register(LLMClientProtocol.CODEX)
class CodexClient(ResponsesClient):
    def __init__(self, config: LLMConfigParameter):
        # 跳过 ResponsesClient.__init__，直接调用基类
        LLMClientABC.__init__(self, config)
        self._token_manager = CodexTokenManager()
        self.client = self._create_codex_client()
```

### D2: Token 刷新时机

**决定**: 在每次 API 调用前检查

**理由**:
- 简单可靠
- 避免长时间运行后 token 过期

**实现**:
```python
async def call(self, param: LLMCallParameter) -> AsyncGenerator[...]:
    # 每次调用前确保 token 有效
    await self._ensure_valid_token()
    # 继续正常调用
    async for item in super().call(param):
        yield item
```

### D3: 登录状态检查

**决定**: 在 `CodexClient.__init__` 时检查，未登录则抛出明确异常

**理由**:
- 快速失败，避免运行时错误
- 提供清晰的用户指引

**实现**:
```python
def __init__(self, config: LLMConfigParameter):
    ...
    if not self._token_manager.is_logged_in():
        raise CodexNotLoggedInError(
            "Codex authentication required. Run 'klaude login codex' first."
        )
```

### D4: 架构层级

**决定**: auth 模块放在与 llm 同级，而非 llm 内部

**理由**:
- 认证是独立关注点
- 未来可能扩展支持其他 OAuth provider (如 Claude Max)
- 符合 importlinter 层级约束

**目录结构**:
```
src/klaude_code/
├── auth/        # 新增，与 llm 同级
├── llm/
├── protocol/
└── ...
```

### D5: System Prompt

**决定**: 不支持自动获取 Codex 官方 System Prompt，使用用户自定义 prompt

**理由**:
- 简化实现
- 用户已有自己的 prompt

### D6: Token 存储

**决定**: 明文 JSON 存储

**理由**:
- 与现有 api_key 配置方式一致
- 简化实现

### D7: 账号支持

**决定**: 仅支持单账号

**理由**:
- 覆盖大多数使用场景
- 简化实现

---

## Dependencies Between Tasks

```
Phase 1: OAuth 认证基础设施
┌─────────────────────────────────────────────────┐
│                                                 │
│  1.1 创建 auth 模块结构                          │
│       │                                         │
│       ├──> 1.2 JWT 解析工具                      │
│       │         │                               │
│       └──> 1.3 Token 存储                        │
│                 │                               │
│                 └──> 1.4 OAuth PKCE 流程         │
│                           │                     │
│                           └──> 1.5 Token 刷新    │
│                                                 │
└─────────────────────────────────────────────────┘
                      │
                      v
Phase 2: Codex 客户端实现
┌─────────────────────────────────────────────────┐
│                                                 │
│  2.1 扩展 LLMClientProtocol ──> 2.2 创建模块     │
│                                      │          │
│                                      v          │
│                               2.3 CodexClient   │
│                                      │          │
│                                      v          │
│                               2.4 更新导出       │
│                                                 │
└─────────────────────────────────────────────────┘
                      │
                      v
Phase 3: CLI 集成
┌─────────────────────────────────────────────────┐
│                                                 │
│  3.1 login 命令 ──> 3.2 logout 命令              │
│         │                                       │
│         └──> 3.3 status 集成                     │
│                    │                            │
│                    └──> 3.4 登录状态检查集成      │
│                                                 │
└─────────────────────────────────────────────────┘
```

---

## Error Handling Strategy

### 错误类型定义

```python
# src/klaude_code/auth/exceptions.py

class CodexAuthError(Exception):
    """Base exception for Codex authentication errors."""
    pass

class CodexNotLoggedInError(CodexAuthError):
    """User has not logged in to Codex."""
    pass

class CodexTokenExpiredError(CodexAuthError):
    """Token expired and refresh failed."""
    pass

class CodexOAuthError(CodexAuthError):
    """OAuth flow failed."""
    pass
```

### 错误处理流程

1. **未登录**: 提示运行 `klaude login codex`
2. **Token 过期**: 自动尝试刷新，失败则提示重新登录
3. **OAuth 失败**: 显示具体错误，建议重试
4. **API 错误**: 显示 OpenAI 返回的错误信息

---

## Testing Strategy

### 单元测试 (可离线)

```python
# tests/auth/test_jwt_utils.py
def test_decode_jwt():
    # 使用预生成的测试 token
    ...

def test_extract_account_id():
    ...

# tests/auth/test_token_manager.py
def test_token_save_and_load(tmp_path):
    ...

def test_token_expiry_check():
    ...
```

### 集成测试 (需要网络)

```python
# tests/auth/test_oauth_integration.py
@pytest.mark.network
def test_full_oauth_flow():
    # 需要真实 ChatGPT 账号
    ...
```

---

## Rollback Plan

如果实现过程中遇到阻塞问题：

1. **Phase 1 阻塞**: OAuth 端点变更
   - 回退: 暂停开发，等待 opencode 项目更新
   
2. **Phase 2 阻塞**: API 不兼容
   - 回退: 不继承 ResponsesClient，独立实现

3. **Phase 3 阻塞**: CLI 冲突
   - 回退: 将 login 作为独立脚本

所有新增代码都在独立模块中，不影响现有功能，可安全回退。
