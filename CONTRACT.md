# 《EVOL 接入契约规范》

> CONTRACT.md · 这是 EVOL **Disk Protocol** 的核心规范文档。
>
> 本文不描述任何特定语言（Python / TypeScript / Java）的 API 风格，而是描述**协议本身**——
> 任何 SDK 实现，只要遵守本文档的全部契约，就是一个合规（conformant）的 EVOL 实现。
>
> 即便有人**不使用我们提供的任何 SDK**、纯手工读写文件，只要符合本规范，也能与其他 EVOL SDK 互操作。
>
> 这是框架"向标准演化"的根本依据。

---

## 一、本文定位与读者

本文是 EVOL 的**标准规范**——它独立于任何具体的语言绑定（Layer 2 SDK），只描述：

- 产品接入 EVOL **必须**做什么、**应该**做什么、**可以**做什么
- 配置文件 `evol.config.yaml` 的完整 schema
- 嵌入式 API（产品调用） + 管理 API（CLI / 守护进程）的行为契约
- `.evol/` 目录的完整结构与每个文件的格式契约
- 生命周期、并发、错误处理、版本兼容性
- 一致性验证（Conformance）的最低要求

**读者**：

- EVOL 各语言 SDK 实现者（evol-py / evol-ts / evol-java …）
- 想自己实现 EVOL 兼容产品的开发者
- 接入 EVOL 的产品开发者（仅看第四节"必选契约"即可入门）
- 安全 / 合规审计人员

---

## 二、规范关键字

本文使用 RFC 2119 风格的关键字，含义如下：

| 关键字 | 中文 | 含义 |
|---|---|---|
| **MUST** | 必须 | 不遵守即为不合规 |
| **MUST NOT** | 必须不 | 严格禁止 |
| **SHOULD** | 应当 | 不遵守需有充分理由，否则破坏互操作性 |
| **SHOULD NOT** | 应当不 | 反向同上 |
| **MAY** | 可以 | 实现者自由选择 |

> 文中以 `[MUST]` / `[SHOULD]` / `[MAY]` 等显式标注规范级别。

---

## 三、协议版本号

EVOL Disk Protocol 使用语义化版本号 `MAJOR.MINOR`：

- **MAJOR** 变更：不兼容的 schema 或语义变更——SDK 必须通过显式迁移流程升级
- **MINOR** 变更：向后兼容的扩展——旧 SDK 读取新文件时**MUST**忽略未知字段而不报错

`.evol/manifest.yaml` 的 `protocol_version` 字段记录写入此目录的 SDK 所遵循的协议版本。

**协议版本与 SDK 版本相互独立**——v0.1 协议可被 evol-py 1.x、evol-ts 1.x 等任意版本的 SDK 实现。

---

## 四、接入必选契约（MUST）

任何接入 EVOL 的产品 **MUST**：

**M-1**：在产品根目录提供一份 `evol.config.yaml`，至少包含 `product` 字段段（见第六节）。

**M-2**：在每次有意义的"任务"开始时调用 `start_task`，结束时调用 `end_task`，且**两次调用配对**——开始而无结束的"悬空 Experience"是非法状态。

**M-3**：在调用 LLM（或等效的成本敏感外部模型调用）之前，**MUST** 调用一次 `enhance`，将其返回的增强结果作为最终 prompt 使用。SDK **MUST** 保证调用 `enhance` 不修改原 prompt 的事实内容（仅追加上下文）。

**M-4**：所有 EVOL 产生的状态文件 **MUST** 写入 `.evol/` 目录（产品根目录下）。任何写入到 `.evol/` 之外的"成长资产"是非法的。

**M-5**：产品 **MUST** 尊重 `evol.config.yaml` 中声明的 `anchors`——SDK 在反思 / 沉淀流程中拒绝违反 anchor 的 Insight。**这是不可关闭的强约束**。

**M-6**：产品 **MUST** 支持 `pause / resume` 状态——pause 状态下 SDK 不再写入新 Experience、不触发反思、不输出 inspiration，但读取行为（`enhance` 注入既有 Memory）仍正常工作。

**M-7**：产品 **MUST** 不修改 `.evol/versions/` 目录下任何已存在的快照文件——版本快照是只读历史。

---

## 五、接入可选契约（SHOULD / MAY）

**S-1** [SHOULD]：在收到用户对任务结果的反馈时调用 `feedback`，把信号附加到对应 Experience。

**S-2** [SHOULD]：在 `end_task` 之后，调用一次 `inspire` 并向用户呈现其返回（若非空）。

**S-3** [SHOULD]：通过 `recorder.start_task` 的 `task_kind` 参数标注任务类型，便于反思产出更精细的 Insight。

**S-4** [MAY]：扩展 `evol.config.yaml` 的 `extensions` 字段以使用社区或自研插件。

**S-5** [MAY]：通过 `manifest.yaml` 的 `metadata` 自由字段，记录产品级元数据（部署环境、构建号等）。

---

## 六、配置文件契约：`evol.config.yaml`

**位置**：[MUST] 与产品可执行入口同级，或由 SDK 显式传入路径
**编码**：[MUST] UTF-8、LF 换行
**最小可用配置**：

```yaml
schema_version: 1
product:
  name: my-product
  version: 0.1.0
```

**完整 Schema**：

```yaml
# Required
schema_version: 1                    # int, currently MUST be 1

product:                             # Required
  name: string                       # 产品名（标识符）
  version: string                    # 产品自身版本，建议 SemVer
  domain: string?                    # 自由文本，描述领域

# Optional but strongly recommended
anchors:                             # 价值锚点列表
  - description: string              # 人类可读的锚点说明
    kind: text | regex | semantic    # 校验方式（v0.1 仅支持 text & semantic）
    rule: string                     # 规则正文（kind 决定其语义）

growth:                              # 成长维度开关，缺省时全部为 true
  knowledge_evolution: true | false
  inspirational_feedback: true | false

reflection:                          # 反思触发策略
  trigger: manual | threshold | scheduled
  threshold: int                     # 触发阈值（trigger=threshold 时必填）
  schedule: string                   # cron 表达式（trigger=scheduled 时必填）
  max_experiences_per_run: int       # 单次反思最大消费经验数，缺省 100

inspiration:
  frequency: never | low | medium | high
  cooldown_hours: int                # 启发之间最短间隔
  max_per_day: int

memory:
  retention:
    experiences:
      max_count: int                 # JSONL 滚动归档阈值
      max_days: int
    snapshots:
      keep: int                      # 保留多少份历史快照（默认 20）

llm:                                 # LLM Backend 配置（详见 LLM-BACKENDS.md）
  backend: direct | subprocess | host | auto    # 缺省 auto（自动检测）
  direct:
    provider: anthropic | openai
    model: string                    # 如 "claude-sonnet-4-6"
    api_key_env: string              # 环境变量名，如 "ANTHROPIC_API_KEY"
  subprocess:
    command: [string]                # ["claude", "-p"] 或 ["codex", "exec"]
    timeout_seconds: int             # 默认 180
    format: text | json
  host:
    request_ttl_hours: int           # pending request 过期时间，默认 168（7 天）
    purpose_whitelist: [string]      # 哪些 purpose 走 host backend

extensions:                          # 插件配置（v0.1 预留）
  - name: string
    config: object
```

**字段约束**：

- [MUST] `schema_version` 是已知值——SDK 遇到不识别的 `schema_version` **MUST** 拒绝启动并提示协议版本不匹配
- [MUST] `product.name` 仅由 `[a-zA-Z0-9_-]` 构成，长度 ≤ 64
- [MUST] `anchors[*].kind = text` 时，`rule` 是被反思 prompt 直接引用的自然语言指令
- [SHOULD] `anchors` 数量不超过 16 条，单条 `rule` 不超过 200 字（保证反思 prompt 不被锚点过度占用）
- [MUST] `llm.backend = "auto"` 时，SDK [MUST] 按以下优先级自动检测：(1) `EVOL_BACKEND` 环境变量、(2) `EVOL_HOST_AGENT` 环境变量（值为 `claude-code` / `codex` / `cursor` 等），(3) `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`，(4) `which claude` / `which codex` 探测，(5) 全部失败则启动期 fail-fast
- [MUST] `llm.backend = "host"` 时，SDK [MUST] 创建 `pending_requests/` / `completed_responses/` / `deferred/` 三个子目录
- [MUST] `llm.backend = "host"` 时，SDK [MUST NOT] 自行调用任何 LLM API（包括 anchor 评估）——所有 LLM 调用一律走 deferred 协议

---

## 七、嵌入式 API 行为契约（产品调用面）

下列 5 个调用是产品代码与 EVOL 的全部对话面。**契约只描述行为与返回语义，不规定具体语法**——具体语法由各语言 SDK 决定。

### 7.1 `start_task(input, ctx?) → task_handle`

**语义**：开启一次新 Experience，进入"开放"态。

**输入**：
- `input`: text | structured object —— 任务输入；将原文（或可还原的摘要）写入 `experiences.jsonl`
- `ctx`: object? —— 可选元数据（`task_kind`、`tags`、`session_id` 等）

**输出**：
- `task_handle`: 不透明句柄；之后的 `end_task` / `feedback` 必须通过它引用本任务

**行为约束**：
- [MUST] 同步、非阻塞——延迟 ≤ 50ms
- [MUST] 写入 Experience 的 `id` + `started_at`（UTC ISO 8601 + 毫秒）
- [MUST] 即便 LLM 不可达、Memory 损坏，也不能让本调用失败
- [MUST NOT] 进行任何 LLM 调用

### 7.2 `end_task(task_handle, output) → experience_id`

**语义**：闭合 Experience，进入"关闭"态。

**输入**：
- `task_handle`: 来自 `start_task` 的句柄
- `output`: text | structured object —— 任务最终输出

**输出**：
- `experience_id`: 持久化后的全局唯一 ID

**行为约束**：
- [MUST] 写入 `output` + `ended_at`
- [MUST] 若 SDK 在 `start_task` 与 `end_task` 之间崩溃重启，**MUST** 在下次启动时把孤立 Experience 标记为 `status: orphaned` 而非删除
- [MUST] 调用 `end_task` 后，task_handle 不再有效（再次使用为非法）

### 7.3 `feedback(experience_id, signal)`

**语义**：将用户反馈附加到已结束的 Experience。

**输入**：
- `signal`: 取下列预定义类型之一，或扩展类型：
  - `kept` —— 用户原样采用了输出
  - `edited` —— 用户编辑后采用
  - `discarded` —— 用户弃用
  - `rated:{1..5}` —— 显式打分
  - `dwell_ms:{int}` —— 停留时长
  - `comment:{text}` —— 自由评论

**行为约束**：
- [MUST] 是幂等的——同一 `experience_id + signal_type` 重复调用，结果与单次调用一致（多次评分以最后一次为准）
- [MAY] 一次 Experience 可附加多种类型 signal
- [MUST NOT] 修改 Experience 的 `output` 或 `input` 字段

### 7.4 `enhance(prompt, task?) → enhanced_prompt`

**语义**：把 Memory 的智慧注入到 prompt 中。

**输入**：
- `prompt`: text —— 产品自己拼装的原始 prompt
- `task`: object? —— 可选上下文（task_kind、当前 task_handle 等），帮助 SDK 选取相关 Memory

**输出**：
- `enhanced_prompt`: text —— 最终发给 LLM 的 prompt

**行为约束**：
- [MUST] **不修改原 prompt 的事实信息**——仅追加从 Memory 读取的上下文（如系统消息前缀、用户偏好块）
- [MUST] 若 Memory 为空 / 加载失败，**MUST** 原样返回 `prompt` 而非抛错
- [MUST] 在被注入的内容中标记可追溯标记（如 `<!-- evol:advice ref=mem_user_profile_v7#summary_length -->`），便于事后审计
- [SHOULD] 注入内容的总 token 数受配置上限约束（默认不超过原 prompt 的 30%）
- [MUST NOT] 在本调用内进行 LLM 反思——`enhance` 是只读路径

### 7.5 `inspire(task?) → inspiration | null`

**语义**：在合适时机生成对用户的启发性洞见。

**输入**：
- `task`: object? —— 上下文

**输出**：
- `inspiration`: { text, kind, evidence_ids, confidence } —— 启发内容（可为 null，表示当前不适合启发）

**行为约束**：
- [MUST] 检查 cooldown / frequency / max_per_day 配置，超出限额时返回 null
- [MUST] 若返回非 null，其 `text` **MUST** 可追溯到具体若干条 evidence
- [MAY] 内部进行一次轻量 LLM 调用（受配置 budget 控制），但 [MUST NOT] 阻塞产品任务流——若超时则返回 null
- [MUST] 不允许出现违反 `anchors` 的启发内容

---

## 八、管理 API 行为契约（CLI / 守护面）

下列调用通常由 `evol` CLI 或外部守护进程发起，不是产品调用面。

### 8.1 `reflect(experience_range?) → reflection_id`

- 触发一次显式反思；可指定经验区间，缺省为"上次反思之后的所有 Experience"
- [MUST] 持有 `locks/reflection.lock` 全局排他锁，否则等待或失败
- [MUST] 即便部分 Insight 被 anchor 拒绝，反思流程仍 **MUST** 完成并产出 `insights/<date>-reflection.md`，记录拒因

### 8.2 `rollback(version)`

- 把 Memory 回滚到指定历史版本
- [MUST] 不删除任何已有快照，仅切换 `manifest.yaml` 中的 `current_version` 指针
- [MUST] 写入一条 `rollback` 事件到 `experiences.jsonl`（作为系统级 Experience，类型 `system.rollback`）

### 8.3 `snapshot()`

- 强制创建一个 Memory 快照，写入 `versions/memory-v{N+1}.snapshot`
- [MUST] 是幂等的——若 Memory 自上次快照后未变更，**MAY** 跳过写入并返回现有版本号

### 8.4 `pause()` / `resume()`

- 切换 SDK 的运行态。pause 之后：[MUST] 拒绝写入新 Experience；[MUST] 不触发 reflection；[MUST] 不输出 inspiration；[MAY] `enhance` 仍正常工作

### 8.5 `export(path)` / `import(path)`

- 全量导出 / 导入 `.evol/` 目录（含 manifest 校验）
- [MUST] 在导入前验证 protocol_version 兼容；不兼容时拒绝并提示

---

## 九、`.evol/` 目录结构契约

```
.evol/
├── config.yaml                  # [MUST] 启动时由 SDK 写入，是 evol.config.yaml 的运行时副本
├── manifest.yaml                # [MUST] 当前协议版本、Memory 版本、checksum 等
├── experiences.jsonl            # [MUST] 经验日志（append-only）
├── memory/                      # [MUST] 至少存在三个文件：
│   ├── user_profile.yaml
│   ├── domain_knowledge.yaml
│   └── self_awareness.yaml
├── insights/                    # [MUST] 反思产出归档目录
│   └── YYYY-MM-DD-reflection.md
├── versions/                    # [MUST] Memory 历史快照
│   └── memory-v{N}.snapshot
├── locks/                       # [MUST] 文件锁目录
│   └── reflection.lock
├── pending_requests/            # [MUST when llm.backend=host] deferred LLM 请求
│   └── req_{ts}_{rand}.md       #   每个请求一个 markdown 文件（人 + agent 可读）
├── completed_responses/         # [MUST when llm.backend=host] 宿主写回的响应
│   └── req_{ts}_{rand}.json     #   完成后由 EVOL 解析并清理
├── deferred/                    # [MUST when llm.backend=host] EVOL 内部 deferred 状态
│   └── req_{ts}_{rand}.state.json
└── tmp/                         # [MAY] 中间临时文件（重启时 SDK MUST 清理）
```

**约束**：

- [MUST] 任何对 `memory/` 或 `manifest.yaml` 的写入采用 **write-then-rename**（先写 `*.tmp`，再 rename，确保原子性）
- [MUST] `experiences.jsonl` 的写入使用 OS-level advisory file lock（POSIX `flock` 或等价）
- [MUST] 同一项目同一时刻最多一个 reflection 进程（通过 `locks/reflection.lock` 保证）
- [MUST when host backend] `pending_requests/*.md` 在生成后是**只读资产**——一旦写入即不可由 EVOL 修改；只能等待 `completed_responses/*.json` 出现或过期清理
- [MUST when host backend] `completed_responses/*.json` 一旦被消化（解析 + consolidate），[MUST] 在 `deferred/<request_id>.state.json` 中标记 `status: consumed`，并把响应文件移动到 `completed_responses/processed/` 归档
- [MUST] `pending_requests/` 中超过 `llm.host.request_ttl_hours` 的文件 [MUST] 在启动时被自动清理，且写入一条 `task_kind: system.deferred_expired` 的 Experience
- [SHOULD NOT] 把任何二进制 / 不可读资产存入 `.evol/`
- [MUST NOT] 在 `.evol/` 之外维护任何 EVOL 状态

---

## 十、文件格式契约（高层）

> 字段级精确定义见《DATA-MODEL.md》。本节仅约定每个文件的**格式与结构性约束**。

### 10.1 `manifest.yaml`

```yaml
schema_version: 1
protocol_version: "0.1"
product: { name, version }
memory:
  current_version: int
  checksum: string                  # sha256 of memory/*.yaml union
  last_updated: ISO8601
experiences:
  count: int
  last_id: string
  oldest_kept: string
last_reflection:
  id: string
  performed_at: ISO8601
metadata: object?
```

[MUST] checksum 算法 = `sha256(sort(memory/*.yaml).join("\n"))`，便于跨语言一致计算。

### 10.2 `experiences.jsonl`

- 每行一个 JSON 对象，UTF-8，无 BOM，LF 终止
- [MUST] 包含字段：`id`, `task_kind`, `started_at`, `ended_at | null`, `input`, `output | null`, `signals[]`, `advice_used[]`, `anchors_applied[]`, `status`
- [MUST] `id` 全局唯一；推荐格式 `exp_{ISO8601}_{shortrand}`
- [MUST] `started_at` / `ended_at` 是 UTC，含毫秒
- [MAY] 自定义字段写入 `metadata` 子对象

### 10.3 `memory/*.yaml`

- 三种核心 memory 文件均遵循同一外层结构：

```yaml
schema_version: 1
memory_kind: user_profile | domain_knowledge | self_awareness
version: int
last_updated: ISO8601
entries:
  - key: string
    value: text | object
    confidence: number              # 0.0 – 1.0
    evidence_ids: [string]          # references to experiences
    rationale: string
    created_at: ISO8601
    last_validated_at: ISO8601
```

- [MUST] 同一 `key` 在 `entries` 内唯一
- [MUST] `evidence_ids` 至少 1 条；空 evidence 的条目非法
- [MAY] 实现可在 `value` 中使用任意 YAML 结构

### 10.4 `insights/YYYY-MM-DD-reflection.md`

- Markdown，含 YAML frontmatter
- frontmatter [MUST] 包含：`reflection_id`, `performed_at`, `experience_range`, `trigger`, `anchors_applied`, `status`, `memory_versions: { before, after }`
- 正文 [SHOULD] 含两节：「通过的 Insight」与「被 Anchor 拒绝的 Insight」，便于人工 review

### 10.5 `versions/memory-v{N}.snapshot`

- [MUST] 是 `memory/` 目录在某时刻的 tar 归档，文件名严格 `memory-v{int}.snapshot`
- [MUST] 通过 `manifest.yaml` 的 `current_version` 指针确定"当前"版本

### 10.6 `pending_requests/req_{...}.md`（host backend 专用）

- [MUST] 是带 YAML frontmatter 的 markdown 文件
- frontmatter [MUST] 包含：`request_id`, `purpose`, `created_at`, `expires_at`, `status`, `host`, `expected_response_path`, `expected_response_format`
- 正文 [MUST] 包含三节：
  1. `## What you (the host agent) should do` —— 给宿主 agent 的工作指令
  2. `## System Prompt` 与 `## User Prompt` —— 原样的 LLM 提示词
  3. `## Expected Response Schema` —— 期望响应的 JSON Schema 描述
- 详细模板见 LLM-BACKENDS.md §6.4
- [MUST] 文件一旦生成不可由 EVOL 修改；只能由人或宿主 agent 通过写 `completed_responses/<request_id>.json` 来"应答"

### 10.7 `completed_responses/req_{...}.json`（host backend 专用）

- [MUST] 是 UTF-8 JSON 文件
- 顶层 schema 取决于 `purpose`：
  - `reflection` → `{ "insights": [...], "model": "...", "completed_at": "..." }`
  - `inspiration` → `{ "kind": "...", "text": "...", "evidence_ids": [...] }`
  - `anchor_check` → `{ "verdict": "pass|reject", "reason": "..." }`
- [MUST] EVOL 解析失败 [MUST] 标记 deferred state 为 `parse_failed` 并保留原文件供调试
- [MUST] 解析成功后 [MUST] 把响应文件移至 `completed_responses/processed/`

### 10.8 `deferred/req_{...}.state.json`（host backend 专用）

- [MUST] 跟踪 deferred request 的 EVOL 内部状态
- 字段：`request_id`, `purpose`, `pending_path`, `expected_response_path`, `created_at`, `expires_at`, `status: pending | consumed | expired | parse_failed`, `consumed_at?`, `reflection_id?`

---

## 十一、生命周期契约

```
   [SDK Init]
        │
        ├── load evol.config.yaml      (fail-fast on schema mismatch)
        ├── verify .evol/manifest.yaml protocol_version compatible
        ├── verify memory checksum (warn if mismatch, do not auto-correct)
        ├── acquire process-level handle on experiences.jsonl
        ├── register signal handlers (SIGINT/SIGTERM trigger graceful shutdown)
        └── ready
        
   [Per task]
        start_task → enhance → end_task → (optional) feedback / inspire
        
   [On reflection trigger]
        acquire reflection.lock
        produce insights → filter via anchors → consolidate Memory → snapshot → release lock
        
   [Graceful Shutdown]
        flush experiences.jsonl
        if memory dirty: snapshot
        update manifest.yaml
        release locks
        
   [Crash Recovery on Next Init]
        scan experiences.jsonl for orphaned Experience (started without end)
        mark orphaned status = "orphaned"
        verify manifest checksum vs disk
```

[MUST] 实现支持崩溃恢复——任何半完成的状态都能在下次启动时被检测并安全处理（见 §12）。

---

## 十二、并发与原子性契约

| 资源 | 并发策略 | 实现要求 |
|---|---|---|
| `experiences.jsonl` 写入 | 多写者 / 串行 | OS advisory file lock，写入完整一行后释放 |
| `memory/*.yaml` 写入 | 仅反思流程 | write-then-rename，单写者持有 reflection.lock |
| `manifest.yaml` 写入 | 与 memory 一致 | write-then-rename + atomic |
| `versions/*.snapshot` 写入 | 只新增不修改 | 文件名带版本号，存在即不可写 |
| `enhance / inspire` 读 | 多读者无锁 | 容忍读取过时 Memory（最大 1 版本差） |
| `reflection.lock` | 全局排他 | 整个 reflection 流程持锁，崩溃后下次启动 [MUST] 检测并清理 |

---

## 十三、Anchor 守护契约

锚点是 EVOL 的"宪法"——在反思与沉淀流程中**MUST**被严格遵守：

**A-1**：反思 prompt 的 system 消息中 [MUST] 包含全部 active anchors（kind=text 时直接拼接，kind=semantic 时由反思元 prompt 指引）

**A-2**：反思产出的每条 Insight [MUST] 经过后置过滤——若与任一 anchor 冲突，**MUST** 被丢弃，且拒因写入 `insights/<date>-reflection.md` 的「Rejected」节

**A-3**：被 anchor 拒绝的 Insight [MUST NOT] 进入 Memory；[MUST] 计入度量（用于评估锚点是否过严）

**A-4**：anchors 一旦在 `evol.config.yaml` 声明 [SHOULD NOT] 在产品生命周期内变更；若必须变更，**MUST** 在 manifest 中记录变更时间并强制创建一个 Memory snapshot

**A-5**：SDK [MUST NOT] 提供任何 API 让产品在运行时绕过 anchors

---

## 十四、错误处理与降级契约

EVOL 的错误处理遵循"**永不阻塞产品任务流**"的最高原则。

| 故障 | 行为 |
|---|---|
| Memory 读取失败 | `enhance` 原样返回 prompt；记录 warning |
| Memory 校验失败 | 拒绝写入新版本；产品任务流仍可工作（只是不再成长）|
| 反思 LLM 调用失败 | 标记本次反思 `status: failed`，下次重试；不破坏既有 Memory |
| 配置文件畸形 | 启动时 fail-fast，不允许"半启用"状态 |
| Anchor 校验异常 | 视为最严格 fallback——拒绝该 Insight |
| 文件锁获取超时 | reflection 直接放弃；产品任务流不受影响 |
| 协议版本不兼容 | [MUST] 拒绝挂载 `.evol/`；用户必须显式 migrate |
| **host: pending request 写入失败** | reflection `status: pending_write_failed`；下次 reflect 重试 |
| **host: completed response 缺失** | resume_pending 跳过；deferred state 维持 `pending`；不报错 |
| **host: completed response 解析失败** | deferred state 标 `parse_failed`，保留原文件；写 warning 让人工介入 |
| **host: pending request 过期** | 启动时清理；写 `task_kind: system.deferred_expired` 的 Experience；不报错 |
| **subprocess: 子进程超时** | 标记为 `llm_failed`；不破坏既有 Memory；warning 提示用户检查本地 CLI |
| **subprocess: 子进程退出码非零** | 同上；stderr 截断后写入日志（去除 PII） |

错误**MUST**通过结构化日志输出，且不在 stdout 干扰产品自身的输出。

---

## 十五、版本兼容性策略

### 15.1 协议版本演进规则

- **MAJOR 升级**（0.1 → 1.0、1.x → 2.0）：可不向后兼容，但 [MUST] 提供 `evol migrate` 工具
- **MINOR 升级**（0.1 → 0.2）：必须向后兼容——旧 SDK 读取新 manifest 时 [MUST] 忽略未知字段；新 SDK 读取旧 manifest 时 [MUST] 推断缺省值

### 15.2 SDK 与协议版本组合

某 SDK 必须公开声明其支持的 `protocol_version` 范围。例如：

```text
evol-py 1.3 supports protocol_version: "0.1" – "0.3"
evol-ts 0.5 supports protocol_version: "0.1" – "0.2"
```

启动时若 `manifest.yaml.protocol_version` 不在 SDK 支持范围内 → 拒绝挂载、给出可执行的 migration 提示。

### 15.3 字段级演进

- 新增字段：可在 MINOR 中加入，[MUST] 提供合理缺省值
- 重命名字段：[MUST] 在过渡期同时支持新旧名称（至少一个 MAJOR 周期）
- 删除字段：[MUST] 在 MAJOR 升级中进行，并提供迁移脚本

### 15.4 host backend 协议是协议的一部分

- pending_requests/ 中 markdown 模板的章节结构、frontmatter 字段、expected_response_path 约定，**MUST 在 MINOR 内向后兼容**
- completed_responses/ JSON schema 的字段顺序与 purpose-specific 形态，**视同协议字段级变更**
- deferred state schema 是 EVOL 内部状态——SDK 间需要兼容，但人类工具不需要解析，因此约束略松
- host backend 的"宿主接口"（即 markdown 协议）一旦稳定，**SDK [MUST NOT] 单方面改动**——这是与第三方宿主 agent 共享的契约面

---

## 十六、Conformance（一致性验证）

任何声称是"EVOL 兼容"的实现，**MUST** 通过《Conformance Test Suite》（CTS）。CTS 由以下几类测试构成：

| 类别 | 内容 |
|---|---|
| **Schema** | config.yaml / manifest.yaml / memory/*.yaml / experiences.jsonl 的格式校验 |
| **Behavior** | 5 个嵌入式 API + 5 个管理 API 的语义一致性 |
| **Concurrency** | 多进程并发写入的安全性 |
| **Atomicity** | 模拟崩溃后的恢复行为 |
| **Anchor** | 锚点守护行为（包括尝试构造违反 anchor 的 Insight） |
| **Cross-SDK** | 用 SDK A 写入、SDK B 读取并继续演化的端到端验证 |

CTS 自身是 **Disk Protocol 的一部分**——它的版本与协议版本同步演进。任何 SDK 实现 [MUST] 在 CI 中跑通对应版本的 CTS。

---

## 十七、当本协议被违反时

若一个实现违反本规范的某条契约，可能后果：

- **违反 MUST**：实现不合规，**MUST NOT** 自称"EVOL 兼容"。其他 SDK 在检测到不兼容时 [MAY] 拒绝继续协作
- **违反 SHOULD**：实现可能在边缘场景下与其他 SDK 互操作失败
- **违反 MAY**：无后果

强烈建议：在 SDK README 中声明"protocol_version + 已通过的 CTS 版本"，便于使用者评估。

---

## 十八、写在最后

CONTRACT 是 EVOL **从"框架"演化为"标准"**的根本依据。

只要这份契约稳定，三件事就会成立：

1. 不同语言 SDK 之间可以**互相替代**
2. 某种语言 SDK 升级，**不会破坏**其他语言 SDK 已经在用的 `.evol/`
3. 即便没有任何 SDK，**手工**遵守此规范的产品也能加入 EVOL 生态

> Harness 之所以是基础设施，不是因为它实现了什么，而是因为它**定义了什么**。
> EVOL 也是。

---

## 附：版本与迭代

- **v0.1（本版）** —— 初版协议规范，对应 `protocol_version: "0.1"`
- 任何契约变更都 [MUST] 附带 ADR + CTS 同步更新
- 字段级、API 级的精确定义见《DATA-MODEL.md》与《FLOWS.md》
