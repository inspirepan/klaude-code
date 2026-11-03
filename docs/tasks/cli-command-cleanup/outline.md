# CLI 命名与帮助整理

## 已确认

1. `login/logout` 提升为顶层命令，移除 `auth` 分组。
2. `config` 作为配置入口；`kill/resume` 改为 `interrupt/unpause`。
3. `-r/--resume` 继续恢复历史；`unpause` 继续使用现有在线会话控制语义。
4. 同步帮助、首次启动与 OAuth 错误提示、README 和 `--skill` 指南。

## 进度

- [x] 替换入口与引用，整理根帮助并补齐 tasks/web 说明。
- [x] 验证新命令分发、交互选择、历史恢复及帮助与注册表一致。
- [x] 运行格式、lint、全量非网络测试与构建。

## 验证结果

- 登录选择/取消、配置编辑和帮助针对性测试：20 passed；未执行真实 OAuth 登录或修改个人凭证。
- `make format`、`make lint` 通过；全量非网络回归 3624 passed、1 skipped、4 deselected。
- `uv build --offline` 与分发包 Web 资源验证通过；未发布新包。
- 本次提交前 `make pre-push` 全部通过：格式无改动，3624 passed、1 skipped、4 deselected，Web/wheel/sdist 构建与资源验证通过。
- 实际 CLI 的根帮助、`login --help`、`tasks --help` 输出正常；根帮助覆盖全部 19 个公开命令。
- 旧 `auth/conf/kill/resume` 入口移除；当前源码、README 和指南已同步。
- 用户已授权本批 CLI 改动提交并推送 main；Loading 卡顿调查留待复现，不纳入本次提交。

## 本期不做

- 不修改认证存储、任务执行和内部控制协议。
- 不调整其他命令和选项名称。
