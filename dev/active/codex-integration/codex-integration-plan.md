# Codex Integration Plan

Last Updated: 2025-12-01

## Executive Summary

为 klaude-code 项目添加 ChatGPT Codex 订阅模型支持，允许用户通过 OAuth 认证复用其 ChatGPT Plus/Pro 订阅来调用 GPT-5.1-codex 系列模型。

**核心目标：**
- 实现 OAuth PKCE 认证流程
- 复用现有 Responses API 客户端代码
- 提供无缝的用户体验（一次登录，自动刷新 Token）

**预期收益：**
- 用户可使用 ChatGPT 订阅额度调用 Codex 模型
- 无需按 token 付费（订阅用户）
- 扩展 klaude-code 的模型支持范围

---

## Current State Analysis

### 现有架构

```
src/klaude_code/
├── llm/
│   ├── registry.py          # LLM 客户端注册系统
│   ├── client.py             # 抽象基类 LLMClientABC
│   ├── responses/
│   │   ├── client.py         # OpenAI Responses API 客户端
│   │   └── input.py          # 消息格式转换
│   └── ...
├── protocol/
│   └── llm_param.py          # LLMClientProtocol 枚举、配置参数
├── config/
│   └── config.py             # 配置加载/保存
└── cli/
    └── main.py               # CLI 入口
```

### 现有认证机制

- 仅支持静态 API Key 认证
- 配置在 `~/.klaude/klaude-config.yaml` 中的 `api_key` 字段
- 无 Token 刷新机制
- 无 OAuth 支持

### 可复用组件

| 组件 | 复用程度 | 说明 |
|------|---------|------|
| `responses/input.py` | 100% | 消息格式转换完全兼容 |
| `responses/client.py` | 90% | 事件处理逻辑完全兼容，仅需调整认证 |
| `registry.py` | 100% | 注册系统无需修改 |
| `llm_param.py` | 需扩展 | 新增 CODEX 协议枚举值 |

---

## Proposed Future State

### 目标架构

```
src/klaude_code/
├── auth/                     # [NEW] 认证模块
│   ├── __init__.py
│   ├── exceptions.py         # 认证异常定义
│   ├── oauth.py              # OAuth PKCE 流程
│   ├── token_manager.py      # Token 存储与刷新
│   └── jwt_utils.py          # JWT 解析工具
├── llm/
│   ├── codex/                # [NEW] Codex 客户端
│   │   ├── __init__.py
│   │   └── client.py         # 继承 ResponsesClient
│   └── ...
├── protocol/
│   └── llm_param.py          # [MODIFY] 新增 CODEX 协议
└── cli/
    └── main.py               # [MODIFY] 新增 login 命令
```

### Token 存储位置

```
~/.klaude/
├── klaude-config.yaml        # 现有配置
└── codex-auth.json           # [NEW] Codex OAuth tokens
```

### 配置示例

```yaml
provider_list:
  - provider_name: codex
    protocol: codex
    # 无需 api_key，使用 OAuth

model_list:
  - model_name: gpt-5.1-codex
    provider: codex
    model_params:
      model: gpt-5.1-codex
      max_tokens: 32000
      verbosity: medium
      thinking:
        reasoning_effort: medium
        reasoning_summary: auto
```

---

## Implementation Phases

### Phase 1: OAuth 认证基础设施 (P0)

建立 OAuth 认证的核心能力，这是整个功能的基础。

### Phase 2: Codex 客户端实现 (P0)

基于现有 Responses 客户端，实现 Codex 专用客户端。

### Phase 3: CLI 集成 (P1)

提供用户交互入口，包括登录命令和状态检查。

### Phase 4: 测试与文档 (P2)

确保功能稳定性和用户可用性。

---

## Detailed Tasks

### Phase 1: OAuth 认证基础设施

#### 1.1 创建 auth 模块结构
- **优先级**: P0
- **工作量**: S
- **依赖**: 无
- **验收标准**:
  - [ ] 创建 `src/klaude_code/auth/__init__.py`
  - [ ] 创建 `src/klaude_code/auth/jwt_utils.py`
  - [ ] 类型检查通过 (`uv run pyright`)

#### 1.2 实现 JWT 解析工具
- **优先级**: P0
- **工作量**: S
- **依赖**: 1.1
- **验收标准**:
  - [ ] `decode_jwt(token: str) -> dict` 函数实现
  - [ ] `extract_account_id(token: str) -> str` 函数实现
  - [ ] 单元测试覆盖

#### 1.3 实现 Token 存储与加载
- **优先级**: P0
- **工作量**: M
- **依赖**: 1.1
- **文件**: `src/klaude_code/auth/token_manager.py`
- **验收标准**:
  - [ ] `CodexAuthState` Pydantic 模型定义
  - [ ] Token 保存到 `~/.klaude/codex-auth.json`
  - [ ] Token 加载与验证
  - [ ] Token 过期检查 (`is_expired()`)
  - [ ] 支持加密存储（可选，P2）

#### 1.4 实现 OAuth PKCE 流程
- **优先级**: P0
- **工作量**: L
- **依赖**: 1.2, 1.3
- **文件**: `src/klaude_code/auth/oauth.py`
- **验收标准**:
  - [ ] PKCE challenge/verifier 生成
  - [ ] 构建授权 URL
  - [ ] 启动本地 HTTP 服务器 (localhost:1455)
  - [ ] 接收 OAuth 回调并提取 code
  - [ ] 用 code 换取 access_token
  - [ ] 从 JWT 提取 chatgpt_account_id
  - [ ] 保存 tokens 到文件

#### 1.5 实现 Token 刷新逻辑
- **优先级**: P0
- **工作量**: M
- **依赖**: 1.3, 1.4
- **验收标准**:
  - [ ] `refresh_token()` 方法实现
  - [ ] 提前 5 分钟刷新策略
  - [ ] 刷新失败时的错误处理
  - [ ] 刷新后更新存储

---

### Phase 2: Codex 客户端实现

#### 2.1 扩展 LLMClientProtocol 枚举
- **优先级**: P0
- **工作量**: S
- **依赖**: 无
- **文件**: `src/klaude_code/protocol/llm_param.py`
- **验收标准**:
  - [ ] 新增 `CODEX = "codex"` 枚举值
  - [ ] 类型检查通过

#### 2.2 创建 Codex 客户端模块
- **优先级**: P0
- **工作量**: S
- **依赖**: 2.1
- **验收标准**:
  - [ ] 创建 `src/klaude_code/llm/codex/__init__.py`
  - [ ] 创建 `src/klaude_code/llm/codex/client.py`

#### 2.3 实现 CodexClient 类
- **优先级**: P0
- **工作量**: M
- **依赖**: 1.5, 2.2
- **文件**: `src/klaude_code/llm/codex/client.py`
- **验收标准**:
  - [ ] 继承 `ResponsesClient` 或复用其逻辑
  - [ ] 集成 `CodexTokenManager` 获取动态 token
  - [ ] 配置 `base_url = "https://chatgpt.com/backend-api/codex"`
  - [ ] 添加必要的 headers:
    - `OpenAI-Beta: responses=experimental`
    - `chatgpt-account-id: {account_id}`
    - `originator: codex_cli_rs`
    - `User-Agent: GitHubCopilotChat/0.32.4`
  - [ ] 强制 `store=False`
  - [ ] 使用 `@register(LLMClientProtocol.CODEX)` 注册

#### 2.4 更新 LLM 模块导出
- **优先级**: P0
- **工作量**: S
- **依赖**: 2.3
- **文件**: `src/klaude_code/llm/__init__.py`
- **验收标准**:
  - [ ] 导入 codex 模块以触发注册
  - [ ] 类型检查通过

---

### Phase 3: CLI 集成

#### 3.1 实现 login 命令
- **优先级**: P1
- **工作量**: M
- **依赖**: Phase 1 完成
- **文件**: `src/klaude_code/cli/main.py`
- **验收标准**:
  - [ ] `klaude login codex` 命令启动 OAuth 流程
  - [ ] 自动打开浏览器
  - [ ] 显示登录状态和结果
  - [ ] 登录成功后显示 account info

#### 3.2 实现 logout 命令
- **优先级**: P1
- **工作量**: S
- **依赖**: 3.1
- **验收标准**:
  - [ ] `klaude logout codex` 命令删除 tokens
  - [ ] 确认提示

#### 3.3 实现 status 命令集成
- **优先级**: P1
- **工作量**: S
- **依赖**: 3.1
- **验收标准**:
  - [ ] `klaude list` 显示 Codex 登录状态
  - [ ] 显示 token 过期时间

#### 3.4 登录状态检查集成
- **优先级**: P1
- **工作量**: M
- **依赖**: 2.3
- **验收标准**:
  - [ ] 使用 Codex provider 时自动检查登录状态
  - [ ] 未登录时提示用户运行 `klaude login codex`
  - [ ] Token 过期时自动刷新

---

### Phase 4: 测试与文档

#### 4.1 单元测试
- **优先级**: P2
- **工作量**: M
- **依赖**: Phase 2 完成
- **验收标准**:
  - [ ] JWT 解析测试
  - [ ] Token 存储/加载测试
  - [ ] Token 刷新逻辑测试
  - [ ] CodexClient 初始化测试

#### 4.2 集成测试
- **优先级**: P2
- **工作量**: L
- **依赖**: Phase 3 完成
- **验收标准**:
  - [ ] 完整 OAuth 流程测试（需要真实账号）
  - [ ] API 调用测试
  - [ ] Token 刷新测试

#### 4.3 更新示例配置
- **优先级**: P2
- **工作量**: S
- **依赖**: 2.1
- **文件**: `src/klaude_code/config/config.py`
- **验收标准**:
  - [ ] `get_example_config()` 包含 Codex 配置示例

---

## Risk Assessment and Mitigation

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|-------|------|---------|
| OpenAI 更改 OAuth 端点/参数 | 中 | 高 | 集中管理常量，便于快速更新 |
| Token 刷新失败 | 低 | 中 | 实现重试机制，提示用户重新登录 |
| 本地服务器端口被占用 | 低 | 低 | 尝试备用端口或提示用户 |
| chatgpt.com API 不稳定 | 中 | 中 | 添加重试逻辑和友好错误提示 |
| OAuth Client ID 被撤销 | 低 | 高 | 监控 opencode 项目更新，及时同步 |

---

## Success Metrics

1. **功能完整性**
   - [ ] 用户可通过 `klaude login codex` 完成登录
   - [ ] 可正常调用 gpt-5.1-codex 模型
   - [ ] Token 自动刷新无需手动干预

2. **代码质量**
   - [ ] 类型检查通过 (`uv run pyright`)
   - [ ] 代码格式规范 (`uv run isort . && uv run ruff format`)
   - [ ] 测试覆盖核心逻辑

3. **用户体验**
   - [ ] 登录流程 < 30 秒
   - [ ] 错误信息清晰可操作
   - [ ] 与现有 provider 配置方式一致

---

## Required Resources and Dependencies

### 新增 Python 依赖

无需新增依赖，现有依赖已足够：
- `httpx` (通过 openai 间接依赖) - HTTP 请求
- `pydantic` - 数据模型
- 标准库 `base64`, `hashlib`, `secrets` - PKCE 生成
- 标准库 `http.server` - 本地回调服务器

### 外部依赖

| 依赖 | 说明 | 风险 |
|------|------|------|
| OpenAI OAuth 服务 | auth.openai.com | 第三方服务，无法控制 |
| ChatGPT Backend API | chatgpt.com/backend-api | 非官方 API，可能变更 |
| opencode 项目 | OAuth 常量来源 | 需要跟踪更新 |

---

## Timeline Estimates

| 阶段 | 预估工作量 | 说明 |
|------|-----------|------|
| Phase 1 | ~4-6 小时 | OAuth 是核心，需要仔细实现 |
| Phase 2 | ~2-3 小时 | 大量复用现有代码 |
| Phase 3 | ~2-3 小时 | CLI 集成相对直接 |
| Phase 4 | ~2-4 小时 | 测试需要真实账号验证 |
| **总计** | **~10-16 小时** | 可分 2-3 个工作日完成 |

---

## Design Decisions

1. **Codex 官方 System Prompt**: 不支持自动获取，使用用户自定义 system prompt

2. **Token 存储方式**: 明文 JSON 存储（与 api_key 配置一致）

3. **账号支持**: 仅支持单账号
