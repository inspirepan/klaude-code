# Codex Prompt Sync Plan

Last Updated: 2025-12-01

## Executive Summary

为 klaude-code 实现从 GitHub 动态获取最新 Codex 官方 System Prompt 的机制，支持本地缓存以避免频繁网络请求。

**核心目标：**
- 从 `openai/codex` GitHub 仓库获取官方 Prompt
- 本地缓存 Prompt，避免每次启动都请求网络
- 支持按模型类型选择对应的 Prompt 文件
- 提供手动更新命令

**预期收益：**
- 用户可使用 OpenAI 官方 Codex Prompt
- 自动跟踪最新版本
- 离线时可使用缓存的 Prompt

---

## Current State Analysis

### 现有架构

Codex 集成已完成，当前使用用户自定义的 system prompt：

```
src/klaude_code/
├── auth/codex/           # OAuth 认证 (已实现)
├── llm/codex/
│   └── client.py         # Codex 客户端 (已实现)
└── ...
```

### 当前 Prompt 处理

在 `CodexClient.call()` 中，直接使用 `param.system` 作为 instructions：
```python
stream = await call_with_logged_payload(
    self.client.responses.create,
    ...
    instructions=param.system,  # 用户自定义 prompt
    ...
)
```

### GitHub 上的 Codex Prompt

OpenAI 官方仓库: `https://github.com/openai/codex`

Prompt 文件位置:
```
codex-rs/core/
├── gpt_5_codex_prompt.md       # gpt-5.1-codex
├── gpt-5.1-codex-max_prompt.md # gpt-5.1-codex-max  
└── gpt_5_1_prompt.md           # gpt-5.1
```

获取最新 release tag:
```
GET https://api.github.com/repos/openai/codex/releases/latest
-> { "tag_name": "v0.x.x" }
```

下载 Prompt:
```
GET https://raw.githubusercontent.com/openai/codex/{tag}/codex-rs/core/{filename}
```

---

## Proposed Future State

### 目标架构

```
src/klaude_code/
├── auth/codex/
│   └── prompt_sync.py    # [NEW] Prompt 同步逻辑
├── llm/codex/
│   └── client.py         # [MODIFY] 集成 Prompt 获取
└── ...

~/.klaude/
├── codex-auth.json       # 现有 OAuth tokens
└── codex-prompts/        # [NEW] Prompt 缓存目录
    ├── metadata.json     # 版本信息和时间戳
    ├── gpt_5_codex_prompt.md
    ├── gpt-5.1-codex-max_prompt.md
    └── gpt_5_1_prompt.md
```

### 缓存策略

```python
# metadata.json
{
    "version": "v0.1.2025052900",
    "updated_at": 1701432000,
    "files": {
        "gpt_5_codex_prompt.md": "sha256:...",
        "gpt-5.1-codex-max_prompt.md": "sha256:...",
        "gpt_5_1_prompt.md": "sha256:..."
    }
}
```

### 更新触发条件

1. **首次使用**: 缓存不存在时自动下载
2. **手动更新**: `klaude codex update-prompt` 命令
3. **自动检查** (可选): 每 24 小时检查一次新版本

---

## Implementation Phases

### Phase 1: Prompt 同步核心 (P0)

实现从 GitHub 获取和缓存 Prompt 的核心逻辑。

### Phase 2: 客户端集成 (P0)

将 Prompt 获取集成到 CodexClient 中。

### Phase 3: CLI 命令 (P1)

提供手动更新和状态查看命令。

---

## Detailed Tasks

### Phase 1: Prompt 同步核心

#### 1.1 创建 prompt_sync 模块
- **优先级**: P0
- **工作量**: S
- **依赖**: 无
- **文件**: `src/klaude_code/auth/codex/prompt_sync.py`
- **验收标准**:
  - [ ] 定义常量 (GitHub API URL, Prompt 文件映射)
  - [ ] 定义缓存目录路径
  - [ ] 类型检查通过

#### 1.2 实现版本检查
- **优先级**: P0
- **工作量**: S
- **依赖**: 1.1
- **验收标准**:
  - [ ] `get_latest_release_tag() -> str` 从 GitHub API 获取最新 tag
  - [ ] 处理网络错误，返回 None 时使用缓存
  - [ ] 类型检查通过

#### 1.3 实现 Prompt 下载
- **优先级**: P0
- **工作量**: M
- **依赖**: 1.2
- **验收标准**:
  - [ ] `download_prompt(tag: str, model_type: str) -> str` 下载指定 Prompt
  - [ ] 支持的 model_type: `codex`, `codex-max`, `gpt-5.1`
  - [ ] 处理 404 等错误
  - [ ] 类型检查通过

#### 1.4 实现缓存管理
- **优先级**: P0
- **工作量**: M
- **依赖**: 1.3
- **验收标准**:
  - [ ] `PromptCache` 类
    - [ ] `get(model_type: str) -> str | None` 获取缓存的 Prompt
    - [ ] `save(model_type: str, content: str, version: str)` 保存到缓存
    - [ ] `get_version() -> str | None` 获取当前缓存版本
    - [ ] `is_stale(max_age_hours: int = 24) -> bool` 检查是否需要更新
  - [ ] metadata.json 读写
  - [ ] 类型检查通过

#### 1.5 实现主同步逻辑
- **优先级**: P0
- **工作量**: M
- **依赖**: 1.4
- **验收标准**:
  - [ ] `CodexPromptSync` 类
    - [ ] `get_prompt(model_type: str, force_update: bool = False) -> str`
      - 优先使用缓存
      - 缓存不存在或 force_update 时下载
      - 下载失败时返回缓存（如有）
    - [ ] `update_all() -> bool` 更新所有 Prompt 文件
    - [ ] `get_status() -> PromptSyncStatus` 返回当前状态
  - [ ] 类型检查通过

---

### Phase 2: 客户端集成

#### 2.1 修改 CodexClient 使用官方 Prompt
- **优先级**: P0
- **工作量**: M
- **依赖**: Phase 1 完成
- **文件**: `src/klaude_code/llm/codex/client.py`
- **验收标准**:
  - [ ] 在 `__init__` 中初始化 `CodexPromptSync`
  - [ ] 在 `call()` 中:
    - 如果 `param.system` 为空或为默认值，使用官方 Prompt
    - 否则使用用户自定义 Prompt
  - [ ] 根据 `param.model` 选择对应的 Prompt 文件
  - [ ] 类型检查通过

#### 2.2 添加模型类型映射
- **优先级**: P0
- **工作量**: S
- **依赖**: 2.1
- **验收标准**:
  - [ ] `get_prompt_type_for_model(model: str) -> str` 函数
    - `gpt-5.1-codex` -> `codex`
    - `gpt-5.1-codex-max` -> `codex-max`
    - `gpt-5.1` -> `gpt-5.1`
    - 其他 -> `codex` (默认)
  - [ ] 类型检查通过

---

### Phase 3: CLI 命令

#### 3.1 实现 update-prompt 命令
- **优先级**: P1
- **工作量**: S
- **依赖**: Phase 1 完成
- **文件**: `src/klaude_code/cli/main.py`
- **验收标准**:
  - [ ] `klaude codex update-prompt` 命令
  - [ ] 显示下载进度
  - [ ] 显示更新结果（版本号变化）
  - [ ] 类型检查通过

#### 3.2 实现 prompt-status 命令
- **优先级**: P1
- **工作量**: S
- **依赖**: 3.1
- **验收标准**:
  - [ ] `klaude codex prompt-status` 命令
  - [ ] 显示当前缓存版本
  - [ ] 显示最后更新时间
  - [ ] 显示缓存文件列表
  - [ ] 类型检查通过

#### 3.3 集成到 list 命令
- **优先级**: P2
- **工作量**: S
- **依赖**: 3.2
- **验收标准**:
  - [ ] `klaude list` 显示 Codex Prompt 版本信息
  - [ ] 类型检查通过

---

## Risk Assessment and Mitigation

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|-------|------|---------|
| GitHub API 限流 | 中 | 低 | 使用缓存，减少请求频率 |
| Prompt 文件路径变更 | 低 | 高 | 集中管理路径常量，便于快速更新 |
| 网络不可用 | 中 | 中 | 优先使用缓存，仅在必要时请求网络 |
| Prompt 格式变更 | 低 | 中 | Prompt 作为纯文本处理，无需解析 |
| openai/codex 仓库删除 | 极低 | 高 | 缓存机制保证离线可用 |

---

## Success Metrics

1. **功能完整性**
   - [ ] 首次使用自动下载官方 Prompt
   - [ ] 缓存机制正常工作
   - [ ] 手动更新命令可用

2. **可靠性**
   - [ ] 网络失败时优雅降级到缓存
   - [ ] 不影响现有自定义 Prompt 用户

3. **用户体验**
   - [ ] 更新过程有进度提示
   - [ ] 错误信息清晰

---

## Required Resources and Dependencies

### 无需新增依赖

使用现有依赖：
- `httpx` - HTTP 请求
- `pydantic` - 数据模型
- 标准库 `pathlib`, `json` - 文件操作

### 外部依赖

| 依赖 | 说明 | 风险 |
|------|------|------|
| GitHub API | releases/latest 端点 | 有速率限制 (60 req/hour 未认证) |
| GitHub Raw Content | 下载 Prompt 文件 | 稳定 |
| openai/codex 仓库 | Prompt 文件来源 | OpenAI 官方维护 |

---

## Timeline Estimates

| 阶段 | 预估工作量 | 说明 |
|------|-----------|------|
| Phase 1 | ~2-3 小时 | 核心同步逻辑 |
| Phase 2 | ~1-2 小时 | 客户端集成 |
| Phase 3 | ~1 小时 | CLI 命令 |
| **总计** | **~4-6 小时** | 可在一个工作日完成 |

---

## Design Decisions

### D1: Prompt 使用策略

**决定**: 仅当用户未提供自定义 system prompt 时使用官方 Prompt

**理由**:
- 保持向后兼容
- 用户可能有自己的定制需求
- 不强制覆盖用户配置

### D2: 缓存更新策略

**决定**: 手动更新为主，不自动后台检查

**理由**:
- 简化实现
- 避免意外网络请求
- 用户完全控制

### D3: 错误处理

**决定**: 网络失败时静默使用缓存，仅在无缓存时报错

**理由**:
- 最大化可用性
- 避免网络问题阻断用户工作

### D4: Prompt 文件存储

**决定**: 存储在 `~/.klaude/codex-prompts/` 目录

**理由**:
- 与其他 klaude 配置放在一起
- 用户可手动查看/编辑
