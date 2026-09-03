# 接入新模型

执行清单：给内置配置加一个模型或一个 provider 时按顺序过一遍。
落点几乎只有一个文件：`src/klaude_code/config/assets/builtin_config.yaml`。字段语义的权威定义在 `src/klaude_code/protocol/llm_param.py`，本文只管**顺序、落点和坑**。

用户侧 `~/.klaude/config.yaml` 用同一套 schema（`UserProviderConfig`），按字段与内置配置合并，所以本文的字段说明对用户配置同样成立。

---

## 0. 判断改动范围

| 情况                      | 要改什么                                                  |
| ------------------------- | --------------------------------------------------------- |
| 已有 provider 加 / 换模型 | 只改 `builtin_config.yaml` 的 `model_list`                |
| 新 provider，协议已支持   | 加 `provider_list` 条目 + `SUPPORTED_API_KEYS` + 排好优先级 |
| 新协议（上游 wire 不同）  | 要写 `src/klaude_code/llm/<protocol>/client.py`，超出本文  |

已支持的 `protocol`：`openai` / `responses` / `openrouter` / `anthropic` / `bedrock` / `codex_oauth` / `xai_oauth` / `google` / `google_vertex`。上游能被这几种之一直接说通，就是纯配置改动。

---

## 1. 版本升级：bump `model_id`，不要改 `model_name`

**`model_name` 是对外稳定名，`model_id` 是发给上游的真实 ID。** 两者的分工决定了升级的做法：

```yaml
- model_name: gemini-flash # 稳定名，不动
  model_alias: [gemini-3.8-flash, gemini-3.7-flash, gemini-3.6-flash, gemini-flash-latest]
  model_id: gemini-3.8-flash # 升级只动这里
```

`model_name` 出现在用户的 `main_model` / `fast_model` / `compact_model` / `sub_agent_models` 里，也出现在 README 的示例里。改掉它等于让所有既有配置失效；而把旧的具体版本号留在 `model_alias` 里，旧配置和肌肉记忆都会解析到新版本。Gemini Flash 的 3.6 → 3.7 → 3.8 都是这么做的。

真正需要**新增条目**的只有两种：模型定位不同（如 flash 与 flash-lite），或需要与旧版本长期并存对比。并存意味着两条目、两份价格、两处后续维护，默认不要选它。

---

## 2. 模型条目字段

| 字段              | 说明                                                                       |
| ----------------- | -------------------------------------------------------------------------- |
| `model_name`      | 稳定选择名。同名可在多个 provider 下重复，解析规则见第 4 步                |
| `model_alias`     | 别名列表，含旧版本号、上游全称、习惯简写                                   |
| `model_id`        | 发给上游的真实 ID（OpenRouter 要带 `google/` 这类前缀）                    |
| `context_limit`   | 上下文窗口，驱动 compact 时机                                              |
| `max_tokens`      | 单次最大输出                                                               |
| `thinking`        | `reasoning_effort`（OpenAI 风格）或 `type` / `budget_tokens`（Claude 风格） |
| `effort`          | Anthropic `output_config.effort`：`low` / `medium` / `high` / `xhigh` / `max` |
| `verbosity`       | OpenAI 文本详略                                                            |
| `cost`            | 每百万 token 价格，见第 5 步                                               |
| `supports_vision` | **默认 `true`**，纯文本模型必须显式写 `false`，否则图片会真的发出去        |
| `fast_mode`       | Anthropic `speed=fast` / OpenAI `service_tier=priority`                    |
| `cache_retention` | `short`（默认 5m）/ `long`（1h）                                           |
| `provider_routing`| 仅 OpenRouter：`order` / `only` / `ignore` 等                              |
| `disabled`        | 临时下线单个模型，保留条目                                                 |

没读到官方依据的字段就别填。填错 `context_limit` 会让 compact 在错误的时机触发，填错 `supports_vision` 会把图片发给不认识图片的模型。

---

## 3. thinking 档位的命名约定

同一个模型的不同思考档位写成**多个条目**，用 `:<档位>` 后缀，YAML 锚点复用重复部分：

```yaml
- model_name: gemini-flash # 默认档
  thinking: { reasoning_effort: medium }

- &gemini_flash_low
  model_name: gemini-flash:low
  model_alias: [gemini-flash:minimal] # 上游不支持 minimal 时，用别名把它接到 low
  thinking: { reasoning_effort: low }

# 另一个 provider 复用同一份定义
- *gemini_flash_low
```

两个坑：

- **上游停止支持某个档位时，用别名兜住旧名字**，不要直接删条目——用户配置里写着 `gemini-flash:minimal` 的会变成"未知模型"。Gemini 3.7 / 3.8 Flash 拒绝 `minimal`，所以 `:minimal` 是 `:low` 的别名。
- 锚点（`&name` / `*name`）只在同一个 YAML 文档内有效，且**复制的是整条包括 `model_id`**。跨 provider 复用时确认这几个 provider 用的是同一个上游 ID（OpenRouter 的带前缀 ID 就不能复用）。

---

## 4. 多 provider 同名与解析顺序

选择器形如 `model_name@provider`（如 `sonnet@openrouter`），可写进用户配置。

- **不带 `@` 时**：`iter_model_config_candidates` 把它展开成**所有**「有凭据 + 未 disabled + 该模型未 disabled」的 provider 候选，顺序就是 `provider_list` 的声明顺序；第一个候选是实际使用的，其余是配额 / 权限 / 模型不可用这类不可重试错误时的运行时 fallback。所以 provider 在 YAML 里的位置既是默认优先级也是降级顺序。`tests/config/test_builtin_config_priority.py` 钉住了前三个必须是 `youtu-anthropic` / `youtu-openai` / `youtu-gemini`——往前插 provider 会让这条测试失败，这是有意的护栏。
- **`_find_model` 先匹配 `model_name`，再匹配 `model_alias`**：同一个 provider 内，别名永远让位于同名的正式条目。
- 交互选择时（`model_matcher.py`）匹配优先级是：完整选择器 → `model_name` → `别名@provider` → 别名 → 忽略大小写 → provider 限定 → 归一化 → 子串。多个命中不报错，而是**弹出选择器**让人挑。

归一化匹配只保留字母和数字（`gemini38` 命中 `gemini-3.8-flash`），子串匹配要求查询串 ≥4 字符。加别名时留意：**一个太短或太通用的别名会把别的模型也拖进候选列表**，让原本能直接命中的名字变成需要手选。

---

## 5. 价格

`cost` 是每百万 token 单价，`currency` 只接受 `USD`（默认）或 `CNY`——**按官方计价币种填，不要自己折算**。

```yaml
cost: { input: 0.75, output: 3.75, cache_read: 0.075 }
```

分时定价用 `peak`（`windows` + `timezone`，价格留 0 表示沿用平峰价），当前只有 DeepSeek 用到，`tests/config/test_builtin_config_cost.py` 按官方公告钉住了它的窗口和倍数。推广价要在 YAML 注释里写明到期时间与恢复后的价格。

不填 `cost` 不会报错，但用量统计会把这个模型算成 0 成本。

---

## 6. 新 provider 额外要做的

- [ ] `provider_list` 加条目：`provider_name` / `protocol` / `api_key`（`${ENV_VAR}` 或 `${A|B}` 多候选）/ `base_url`
- [ ] `src/klaude_code/config/builtin_config.py` 的 `SUPPORTED_API_KEYS` 加 `ApiKeyInfo`，否则 `klaude` 的 key 引导和诊断不认识这个环境变量（`tests/config/test_builtin_config_api_keys.py` 要求 env_var 唯一）
- [ ] 想清楚插在 `provider_list` 的哪个位置——那就是它的默认优先级
- [ ] Bedrock / Vertex 走的是 AWS / GCP 凭据字段（`aws_*` / `google_*`）而不是 `api_key`，可用性判断也走各自分支

`${A|B}` 的解析顺序是：先 `A` 后 `B`，每个变量都是真实环境变量优先于 `klaude-auth.json` 的 env 段。

---

## 7. 验证

```bash
make pre-push   # format + lint + test + build，AGENTS.md 要求推送前必须全绿
```

改内置配置至少要跑 `tests/config/`：优先级、价格、API key、`supports_vision` 都有断言盯着这份 YAML。

手动验证：

- [ ] `klaude --model <新名字>` 与 `klaude --model <别名>` 都能起会话
- [ ] 模型列表（`/model` 选择器）里的显示名、provider 归属、价格正确
- [ ] 别名没有把无关模型拖进候选列表

---

## 附：Gemini 3.8 Flash 的实际改动（2026-09-03，可作模板）

只改了 `builtin_config.yaml`：`youtu-gemini` / `google` / `google-vertex` / `openrouter`（`google/` 前缀）四个 provider 下的 `gemini-flash` 及其档位条目，`model_id` 全部指向 `gemini-3.8-flash`（`youtu-gemini` 有 `:low` / `:high` 两档，其余 provider 只有 `:low`，`google-vertex` 经锚点复用 `google` 的定义）。别名表补 `gemini-3.8-flash` 及各档位变体，旧版本号继续作为别名解析到新模型。价格与 3.7 Flash 同为 Google 推广价，2027-01-01 起恢复 $1.50 / $7.50 / $0.15。
