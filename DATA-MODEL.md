# 《EVOL 数据资产规范》

> DATA-MODEL.md · 这是 EVOL **Disk Protocol** 的字段级定义。
>
> 与 CONTRACT 的关系：
> - **CONTRACT** 回答 "API 怎么用、文件怎么放、行为怎么演"
> - **DATA-MODEL** 回答 "每个字段长什么样、怎么填、怎么演化"
>
> 数据模型是 EVOL 的"底座"——它一旦定型就极难变更，所以本文档每一处约束都经过严肃考量。
>
> **数据模型决定框架的天花板。**

---

## 一、本文定位

本文规定 EVOL Disk Protocol 中**全部持久化数据**的字段级 schema：

- 五个核心抽象（Experience / Signal / Insight / Memory / Anchor）的精确字段
- 实体之间的关系（ER 模型）
- 证据链（Provenance）的语义
- 版本化机制（文件级、记录级、字段级）
- 隐私与敏感数据的处理规则
- 跨 SDK 的一致性保证（checksum、字段顺序、序列化）

任何 SDK 实现 **MUST** 严格遵守本文档的字段定义。**字段级偏差 = 数据底座破坏 = 跨 SDK 互操作失败**。

---

## 二、数据底座的六条设计原则

在进入 schema 细节前，先列出本文档贯穿始终的设计原则——它们是 PRINCIPLES 在数据层的具体投射：

1. **Append-only 优于 mutate**——所有"事实"（Experience、Insight）一旦写入就不可修改；变更只能通过新版本叠加
2. **Evidence chain 必须连续**——任何 Memory 条目都能一步追溯到具体若干个 Experience
3. **字段最小化**——若一个字段在 v0.1 没有明确读者，不要加；可以未来扩展，不要预先添加
4. **置信度优于绝对值**——所有"系统对自己的认知"都带 `confidence`，没有"100% 确定"
5. **PII 隔离**——可能含敏感信息的字段（input / output / comment）必须支持 redact 操作
6. **跨 SDK 一致性高于性能**——schema 字段顺序、序列化方式、hash 算法**MUST**统一规定，便于跨语言 checksum 一致

---

## 三、五个核心抽象的关系（ER 模型）

```
                         +----------+
                         |  Anchor  |   ← 来自 evol.config.yaml
                         | (immutable)|
                         +-----+----+
                               │ guards (filter)
                               ▼
   +-------------+  reads   +---------+   produces   +-----------+
   | Experience  | ◀───────│Reflector│─────────────▶│  Insight  │
   +------+------+          +─────────+               +─────+─────+
          ▲                                                 │
          │ feedback                          consolidate   │
          │                                  (if approved)  │
   +------+------+                                          ▼
   |   Signal    |                                  +---------------+
   | (embedded)  |                                  |   Memory      |
   +-------------+                                  | (3 kinds)     |
                                                    +-------+-------+
                                                            │
                              ┌─────────────────────────────┘
                              ▼
                        Advisor reads → enhance / inspire
```

**关键关系**：

| 关系 | 基数 | 描述 |
|---|---|---|
| Experience → Signal | 1 : 0..N | 一次任务可附加多个反馈信号 |
| Reflector reads Experiences | N : 1 | 一次反思消费一批 Experience |
| Reflector → Insight | 1 : 0..N | 一次反思可产生多条 Insight 候选 |
| Anchor → Insight | M : N | 锚点对每条 Insight 进行准入过滤 |
| Insight → Memory.entry | 1 : 0..1 | 通过的 Insight 沉淀为某个 Memory 条目的新版本 |
| Memory.entry → Experiences | 1 : 1..N | 通过 evidence_ids 反向追溯（证据链） |

---

## 四、Experience（经验）

### 4.1 定义

一次**完整任务交互**的不可变记录。是 EVOL 学习的"原始素材"。

### 4.2 物理位置

`.evol/experiences.jsonl` —— 每行一个 JSON 对象，append-only。

### 4.3 字段 schema

```yaml
id:                string         # MUST 全局唯一；推荐 "exp_{ISO8601}_{shortrand}"
task_kind:         string         # 由产品通过 ctx.task_kind 声明；缺省为 "default"
status:            enum           # open | closed | orphaned | redacted
started_at:        ISO8601        # UTC，含毫秒；MUST 单调
ended_at:          ISO8601 | null # closed 状态时必填
input:             text | object  # 任务输入；可为结构化 JSON
output:            text | object | null
signals:           [Signal]       # 见 §5
advice_used:       [AdviceRef]    # 见 §4.4
anchors_applied:   [AnchorRef]    # 见 §4.4
metadata:          object         # 自由元数据
redacted:          bool           # 是否经过脱敏处理
```

### 4.4 引用类型

**AdviceRef**（在 enhance 中注入到 prompt 的智慧引用）：
```
"mem_{kind}_v{version}#{key}"
例如: "mem_user_profile_v7#summary_length"
```

**AnchorRef**（被本次任务执行流应用的锚点）：
```
"anchors[{index}]"   # index 来自 evol.config.yaml 的 anchors 数组
```

### 4.5 生命周期与状态机

```
   start_task        end_task            (graceful)
       │                 │                   │
       ▼                 ▼                   ▼
   [open] ─────────▶ [closed] ─────────▶ persisted
       │                                     ▲
       │ (process crash before end_task)     │
       ▼                                     │
   [orphaned]                                │
                                             │
   redact()                                  │
       │                                     │
       ▼                                     │
   [redacted] ───────────────────────────────┘
```

| 字段 | open | closed | orphaned | redacted |
|---|---|---|---|---|
| `started_at` | ✓ | ✓ | ✓ | ✓ |
| `ended_at` | null | ✓ | null | ✓ or null |
| `input` / `output` | ✓ / null | ✓ / ✓ | ✓ / null | "[REDACTED]" |
| `signals` | [] | mutable (append) | [] | preserved |

### 4.6 完整示例

```json
{
  "id": "exp_2026-05-03T14:30:00.123Z_a3f9",
  "task_kind": "summarize",
  "status": "closed",
  "started_at": "2026-05-03T14:30:00.123Z",
  "ended_at":   "2026-05-03T14:30:02.456Z",
  "input": "今天主要在搭 EVOL 的雏形……",
  "output": "今天搭了 EVOL 雏形，敲定了 Recorder 接口。",
  "signals": [
    { "type": "kept", "ts": "2026-05-03T14:35:00.000Z", "source": "explicit" }
  ],
  "advice_used": [
    "mem_user_profile_v7#summary_length",
    "mem_user_profile_v7#tone"
  ],
  "anchors_applied": ["anchors[0]", "anchors[1]"],
  "metadata": {
    "sdk": "evol-py",
    "sdk_version": "0.1.0",
    "product_version": "0.1.0"
  },
  "redacted": false
}
```

---

## 五、Signal（信号）

### 5.1 定义

用户对一次 Experience 的反馈（隐式或显式）。不独立存储，**嵌在 Experience 的 `signals` 数组里**。

### 5.2 字段 schema

```yaml
type:    enum         # kept | edited | discarded | rated | dwell | comment | <ext>
ts:      ISO8601
value:   any          # type-specific：rated 是 1..5，dwell 是 ms 数，comment 是 text
source:  enum         # explicit | implicit
weight:  number       # 0.0–1.0，可选，反思时的权重提示
```

### 5.3 标准 type 取值与语义

| type | value 类型 | source 默认 | 含义 |
|---|---|---|---|
| `kept` | null | explicit | 用户原样采用 |
| `edited` | text? | explicit/implicit | 用户编辑后采用；value 可选含 diff |
| `discarded` | null | explicit | 用户弃用 |
| `rated` | int 1–5 | explicit | 显式评分 |
| `dwell` | int (ms) | implicit | 用户停留 / 阅读时长 |
| `comment` | text | explicit | 自由文本评论 |

[MAY] 实现可定义自定义 type，但 [MUST] 以命名空间前缀（如 `myorg:click_through`）避免冲突。

### 5.4 多 signal 的合并语义

同一 Experience 上可附加多条 signal。反思流程在解读时：

- 多个 `rated` 取**最后一条**
- 多个 `dwell` 取**总和**
- 其他 type 保留全部
- `weight` 字段（若提供）用于显式调权

---

## 六、Insight（洞察）

### 6.1 定义

Reflector 对一批 Experience 反思后产出的**结构化主张**。是 Memory 的输入候选。

### 6.2 物理位置

`.evol/insights/YYYY-MM-DD-reflection.md` —— Markdown 文件，frontmatter 携带元数据，正文按"通过 / 拒绝"分节列出。

### 6.3 字段 schema（每条 Insight）

```yaml
id:                string          # ins_{date}_{seq}, e.g., "ins_2026-05-03_001"
reflection_id:     string          # 所属反思批次的 ID
created_at:        ISO8601
scope:             enum            # user_profile | domain_knowledge | self_awareness | meta
key:               string          # Memory 中目标 entry 的 key
claim:             text            # 自然语言主张
proposed_change:   object          # 见 §6.4
confidence:        number          # 0.0–1.0
evidence_ids:      [exp_id]        # MUST ≥ 1
status:            enum            # pending | applied | rejected | superseded
rejection:         object | null   # 仅 status=rejected 时；见 §6.5
applied_to:        MemoryRef | null # 仅 status=applied 时
notes:             text?
```

### 6.4 `proposed_change` 子结构

```yaml
op:    enum          # set | merge | strengthen | weaken | retire
value: any           # op-specific（set 时是新值；strengthen 时是 confidence 增量）
```

### 6.5 `rejection` 子结构

```yaml
by_anchor:  int      # 拒绝该 Insight 的 anchor 在 config 中的 index
rule:       text     # 被违反的 anchor 规则原文
reason:     text     # SDK 给出的拒因（人类可读）
```

### 6.6 完整示例（passed）

```yaml
id: ins_2026-05-03_001
reflection_id: ref_2026-05-03_001
created_at: 2026-05-03T20:05:12Z
scope: user_profile
key: summary_length
claim: "用户偏好 60-80 字总结，比 config 声明的 100 字上限明显更短"
proposed_change:
  op: set
  value: "60-80 字（短于声明的 100 字上限）"
confidence: 0.85
evidence_ids: [exp_001, exp_007, exp_023, exp_031, exp_042, exp_058, exp_071]
status: applied
applied_to: "mem_user_profile_v7#summary_length"
```

### 6.7 完整示例（rejected）

```yaml
id: ins_2026-05-03_004
reflection_id: ref_2026-05-03_001
created_at: 2026-05-03T20:05:14Z
scope: user_profile
key: language
claim: "可以把英文输入也总结成中文输出"
proposed_change: { op: set, value: "always_zh" }
confidence: 0.42
evidence_ids: [exp_017, exp_034]
status: rejected
rejection:
  by_anchor: 1
  rule: "输出语言与输入保持一致"
  reason: "Insight 与 anchors[1] 冲突"
```

---

## 七、Memory（记忆）

### 7.1 定义

经过反思与锚点过滤后**沉淀的长期资产**。

### 7.2 三种 Memory kind

| kind | 文件 | 作用 |
|---|---|---|
| `user_profile` | `memory/user_profile.yaml` | 使用者的偏好、习惯、风格 |
| `domain_knowledge` | `memory/domain_knowledge.yaml` | 任务领域内的常见模式、陷阱、最佳实践 |
| `self_awareness` | `memory/self_awareness.yaml` | 系统自身擅长 / 不擅长 / 易错处 |

[MUST] v0.1 起步阶段固定为这三种；新增 kind 需 MAJOR 协议升级。

### 7.3 文件级 schema（外层）

```yaml
schema_version: 1
memory_kind:    enum                 # 见 §7.2
version:        int                  # 单调递增，与 versions/memory-v{N}.snapshot 对齐
last_updated:   ISO8601
checksum:       string               # sha256 of canonicalized entries (见 §11)
entries:
  - <Entry>
  - <Entry>
```

### 7.4 Entry 级 schema（每条记忆）

```yaml
key:                string           # 在该 kind 内 MUST 唯一；推荐 snake_case
value:              text | object    # 自由结构；建议保持人类可读
confidence:         number           # 0.0–1.0
evidence_ids:       [exp_id]         # MUST ≥ 1（无证据的 entry 非法）
rationale:          text             # 该结论的简短自然语言说明
created_at:         ISO8601
last_validated_at:  ISO8601          # 最近一次反思中再次确认的时间
last_revision_id:   string           # 最后一次更新它的 Insight ID
revision_count:     int              # 该 entry 历史被修订的次数
status:             enum             # active | retired | superseded
```

### 7.5 完整示例（user_profile.yaml）

```yaml
schema_version: 1
memory_kind: user_profile
version: 7
last_updated: 2026-05-03T20:05:30Z
checksum: sha256:9a3f4e8c2b1d6a7e5f0c2b4d1e9a8c3f...

entries:
  - key: summary_length
    value: "60-80 字（短于声明的 100 字上限）"
    confidence: 0.85
    evidence_ids: [exp_001, exp_007, exp_023, exp_031, exp_042, exp_058, exp_071]
    rationale: "用户在 7 次任务中将默认 100 字编辑到 80 字以下"
    created_at: 2026-04-15T19:00:00Z
    last_validated_at: 2026-05-03T20:05:30Z
    last_revision_id: ins_2026-05-03_001
    revision_count: 3
    status: active

  - key: highlight_pattern
    value: "用户重视'今天学到了什么'远超'今天做了什么'"
    confidence: 0.90
    evidence_ids: [exp_042, exp_058, exp_071, exp_088, exp_092, exp_103]
    rationale: "用户 12 次任务的编辑记录中，6 次保留了'学到的'段落，5 次删除了'做了的'段落"
    created_at: 2026-04-20T18:30:00Z
    last_validated_at: 2026-05-03T20:05:30Z
    last_revision_id: ins_2026-05-03_002
    revision_count: 2
    status: active
```

---

## 八、Anchor（锚点）

### 8.1 定义

来自 `evol.config.yaml` 的不可演化约束，是反思与沉淀流程的**强过滤器**。

### 8.2 配置级 schema（来自 config）

```yaml
- description: string         # 人类可读说明
  kind:        enum           # text | regex | semantic
  rule:        string         # kind-specific
```

| kind | rule 含义 | 应用方式 |
|---|---|---|
| `text` | 自然语言指令 | 直接拼接到反思 prompt 的 system 消息 |
| `regex` | 正则表达式 | 对 Insight.claim 做模式匹配；命中即拒绝 |
| `semantic` | 语义判别 prompt | 由 SDK 用元 prompt 判断 Insight 是否违反 |

### 8.3 运行时表征（在 manifest.yaml 中）

```yaml
anchors:
  - index: 0
    description: "总结必须忠实于原文，不杜撰、不加戏"
    kind: text
    rule_hash: sha256:7c8a9b...
    activated_at: 2026-04-01T00:00:00Z
    deactivated_at: null
```

`rule_hash` 是 anchor 内容的 sha256；**MUST** 在每次启动时重算并比对——若 hash 与 manifest 中记录不符，[MUST] 强制创建一个 Memory snapshot 并更新 hash 记录（说明锚点被人工修改过）。

### 8.4 锚点不可在运行时变更

[MUST NOT] 提供任何 API 让产品代码在运行时增删 / 修改 anchors。
[MUST] 锚点变更只能通过编辑 `evol.config.yaml` + 重启 + 强制 snapshot 完成。

---

## 九、Provenance（证据链）

### 9.1 全链路追溯关系

每一条 Memory 的来由都能从产品代码出发逆向追溯到具体 Experience：

```
   Memory.entry
        │
        │ last_revision_id  ─────────────┐
        ▼                                │
        evidence_ids[]                   │
        │                                │
        ▼                                ▼
   [Experience₁, Experience₂, ...]    Insight (in insights/*.md)
                                         │
                                         ▼
                                       evidence_ids[]
                                         │
                                         ▼
                                   [Experience₁, Experience₂, ...]
```

[MUST] 任何 Memory entry 都必须能通过 `evidence_ids` 一步、`last_revision_id → Insight.evidence_ids` 两步追到原始 Experience。

### 9.2 证据链的完整性约束

- [MUST] `Memory.entry.evidence_ids` 中的每个 ID 都对应 `experiences.jsonl` 中真实存在的 Experience
- [MUST] 当某 Experience 被 redact，引用它的 Memory entry [MUST] 在 `rationale` 中标记 `[evidence redacted]`，但 evidence_ids 保留——证据链断了 ID 还在
- [MUST] 当 Experience 被归档（rotated to `experiences/YYYY-MM.jsonl.gz`），引用 [MUST] 仍可解析（实现 [MUST] 在归档时维护索引）

### 9.3 evidence 数量与 confidence 的关系

[SHOULD] 实现遵循经验法则：

| evidence count | 推荐 confidence 上限 |
|---|---|
| 1 | 0.30 |
| 2–3 | 0.60 |
| 4–7 | 0.85 |
| ≥ 8 | 0.95 |

但 [MAY] 实现使用更精细的统计模型替代——本表只是缺省最小约束。

---

## 十、版本化机制

### 10.1 文件级版本（Memory）

- `manifest.yaml.memory.current_version` 是当前版本号
- `versions/memory-v{N}.snapshot` 是历史归档（tar 形式打包 `memory/` 全目录）
- 每次 `consolidate` 成功 [MUST] 自增 version 并写入新 snapshot
- 历史 snapshot **MUST NOT** 被修改或删除（除非配置 `memory.retention.snapshots.keep` 主动 prune）

### 10.2 记录级版本（Memory.entry）

- 每条 entry 通过 `revision_count` 跟踪修订次数
- 通过 `last_revision_id` 指向最后一次修订该 entry 的 Insight
- 在 `versions/memory-v{N}.snapshot` 中保留全量历史

### 10.3 字段级版本（Schema 演进）

文件外层都有 `schema_version: 1`：

- 当 `schema_version` 升级（极少发生），[MUST] 在 SDK 中提供 in-place 迁移
- 协议 minor 升级 [MUST] **不**升级 schema_version
- `schema_version` 升级仅在 protocol MAJOR 升级时允许

### 10.4 Insight 与 Reflection 不版本化

Insight 一旦写入即不可变（immutable）。同一议题的修正以新 Insight 出现，旧 Insight 通过 `status: superseded` 标记。

Reflection 文件（`insights/YYYY-MM-DD-reflection.md`）一旦完成 [MUST NOT] 修改。

---

## 十一、跨 SDK 一致性：Canonicalization

为保证 Python / TypeScript / Java 三种 SDK 计算出的 checksum 完全一致，本节强制规定**序列化的规范化方式**。

### 11.1 YAML 写出规范

- [MUST] 使用 UTF-8、LF 换行、2 空格缩进
- [MUST] 顶层字段顺序固定为：`schema_version → memory_kind → version → last_updated → checksum → entries`
- [MUST] entries 内字段顺序固定为：`key → value → confidence → evidence_ids → rationale → created_at → last_validated_at → last_revision_id → revision_count → status`
- [MUST] 浮点数（confidence）以两位小数串表示（"0.85" 而非 0.8500001）
- [MUST] 时间戳统一为 UTC ISO 8601、带 `Z` 后缀、毫秒精度（秒级亦可，但 [SHOULD] 毫秒）

### 11.2 JSONL 写出规范

- [MUST] UTF-8、无 BOM、LF 终止
- [MUST] 单行 JSON（不允许跨行）
- [MUST] 字段顺序固定（同 §4.3 列出顺序）
- [MUST] 不输出空字段（null 值字段照常输出）
- [MUST] 不使用空格缩进；键值之间使用 `:` `,` 紧贴

### 11.3 Checksum 计算

```
checksum_input = sort(memory_kind, by="user_profile,domain_knowledge,self_awareness")
                 .map(yaml_canonical_serialize)
                 .join("\n---\n")
checksum = "sha256:" + hex(sha256(checksum_input))
```

[MUST] 任何 SDK 实现都 **MUST** 产生同一 input 的同一 hash。该计算受 Conformance Test Suite 验证。

---

## 十二、隐私与敏感数据

### 12.1 敏感数据可能进入哪些字段

| 字段 | 风险等级 | 处理建议 |
|---|---|---|
| `Experience.input / output` | 高 | 默认明文存储；[MAY] 启用 redact-on-rotate |
| `Signal.value`（comment） | 中 | 同上 |
| `Memory.entry.rationale` | 中 | [MUST] 不直接复制 input/output 全文，仅引用 evidence_ids |
| `Insight.claim` | 低 | [MUST] 是抽象主张而非原文复述 |

### 12.2 Redact 操作

```
redact(experience_id):
   set status = "redacted"
   set input  = "[REDACTED]"
   set output = "[REDACTED]"
   strip Signal.value if comment-typed
   preserve id, timestamps, signal types, advice_used, anchors_applied
```

- [MUST] redact 是**幂等**的
- [MUST] redact 不影响 Memory 的现有 entry（evidence_ids 保留，但 rationale [MUST] 自动追加 `[evidence redacted]`）
- [MUST NOT] redact 删除 Experience 行——保留行结构，仅清空敏感字段

### 12.3 Export 模式

`evol export` 提供两种模式：

- `--full`：完整导出，含敏感字段（默认拒绝；需 `--allow-pii` 显式确认）
- `--redacted`：自动对所有 Experience 跑一遍 redact 后导出（缺省）

### 12.4 不允许做的事

- [MUST NOT] 把 Experience 内容写入 `manifest.yaml`
- [MUST NOT] 在反思 prompt 中直接拼接未脱敏的多条 Experience（[SHOULD] 反思 prompt 限制每条 Experience 的最大字符数）
- [MUST NOT] 把 PII 写入日志 / stdout / stderr

---

## 十三、大小估算与归档

### 13.1 单元大小参考

| 实体 | 典型大小 |
|---|---|
| 1 条 Experience | 0.5–2 KB（取决于 input/output） |
| 1 条 Insight | 0.5 KB |
| 1 条 Memory.entry | 0.3 KB |
| 1 个 Memory snapshot | 5–30 KB |

### 13.2 归档策略

```
config:
  memory.retention.experiences.max_count: 10000
  memory.retention.experiences.max_days: 365
  memory.retention.snapshots.keep: 20
```

- [MUST] 当 `experiences.jsonl` 达到 `max_count` 或 `max_days` 阈值，触发滚动归档：
  - 旧条目压缩为 `experiences/{YYYY-MM}.jsonl.gz`
  - 在 `experiences.jsonl` 中保留最近窗口
- [MUST] 维护 `experiences/index.yaml` 提供归档查询能力
- [MUST] 归档过程中，反思流不能开始（通过 `reflection.lock` 互斥）

---

## 十四、与 CONTRACT / FLOWS 的边界

| 文档 | 关心的事 |
|---|---|
| **CONTRACT** | API 行为 / 文件结构 / 生命周期 / 协议演进 |
| **DATA-MODEL（本文）** | 字段级 schema / 关系 / 证据链 / 序列化规范 / 隐私 |
| **FLOWS** | 反思 / 增强 / 启发流的内部细节（prompt 模板、决策逻辑） |

三者在某些条目上有意重叠（例如 `experiences.jsonl` 在 CONTRACT 提到结构、本文给出字段、FLOWS 描述追加协议），但只要互相不矛盾即可。

**冲突处理顺序**：CONTRACT > DATA-MODEL > FLOWS。

---

## 十五、写在最后

数据模型不是一份越完整越好的文档。**一个干净的数据底座，应该让读者一眼能看清三件事**：

1. **每条事实从哪里来**（evidence_ids 一路追溯到 Experience）
2. **每个判断有多确定**（confidence + revision_count）
3. **每个变更何时发生、由谁触发**（last_revision_id → Insight → reflection_id）

如果未来某次设计冲动想加一个新字段，请先回答：

> **这个字段服务上面三件事中的哪一件？**
> 如果都不是，几乎一定不应该加。

> 数据模型决定框架天花板。
> EVOL 的天花板是「让任何成长结论都能被追溯、被怀疑、被回滚」。

---

## 附：版本与迭代

- **v0.1（本版）** —— 初版数据规范；与 protocol_version "0.1" 对应
- 任何字段级变更 [MUST] 附带：
  - 一份 ADR（说明触发原因）
  - Conformance Test Suite 同步更新
  - 跨 SDK 序列化样例对比
- 字段在 v0.1 内的"未读者"扩展 [SHOULD NOT] 通过——克制原则适用于数据底座
