# 《EVOL 架构概览》

> ARCHITECTURE.md · 这是 EVOL 的「全局蓝图」。
>
> 目标：让任何新加入的开发者，**30 分钟内理解 EVOL 全貌**——它由哪几块组成、它们如何协作、数据如何流动、一次任务/一次反思/一次启动关闭里框架在做什么。
>
> 这份文档会被反复修改，但永远要保持「高层视角」。具体 API 留给 CONTRACT，具体数据结构留给 DATA-MODEL，具体流程留给 FLOWS。

---

## 一、EVOL 站在哪里：分层定位

EVOL 不替代任何已有的执行层 / 智能体层框架，它**架在它们之上**作为一个独立的"成长层"。

```
┌──────────────────────────────────────────────────────────────┐
│                       Product Code                            │
│        journal-cli  /  content-ultra  /  anything             │
└────────────────────────────┬─────────────────────────────────┘
                             │
   recorder.start_task / end_task / feedback                    
   advisor.enhance / advisor.inspire                            
                             │
                             ▼
┌──────────────────────────────────────────────────────────────┐
│                          EVOL                                 │
│              (Growth Infrastructure Layer)                    │
│       Recorder · Reflector · Memory · Advisor                 │
└────────────────────────────┬─────────────────────────────────┘
                             │
   prompts / retries / observability / tool-use                 
                             │
                             ▼
┌──────────────────────────────────────────────────────────────┐
│       Harness  /  LangGraph  /  Direct LLM SDK                │
│                  (Execution Layer)                            │
└────────────────────────────┬─────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────┐
│   LLM 算力来源（三选一，由 LLM Backend 配置切换）             │
│                                                                │
│   • Direct API     —— Claude / OpenAI 等远程 API              │
│   • Subprocess CLI —— 本机 claude / codex CLI 子进程          │
│   • Host Agent     —— 宿主 Agent 代办（EVOL 作为 Skill 嵌入）  │
└──────────────────────────────────────────────────────────────┘
```

**关键：**
- EVOL 不知道下层用的是 Harness 还是 LangGraph 还是裸 SDK
- EVOL 也不替代它们；执行的"做对"由它们负责，成长的"越来越好"由 EVOL 负责
- 上层产品和 EVOL 通过**5 个 API**对话（contract），与下层无强耦合
- 同一份 EVOL 可在 **独立 CLI 工具** 和 **嵌入 Claude Code / Codex 的 Skill** 两种部署形态下运行——LLM Backend 可切换，但 `.evol/` 协议与上层 5 个 API 完全相同。详见《LLM-BACKENDS.md》

---

## 二、五个核心抽象（The 5 Nouns）

EVOL 的全部世界，由五个名词构成。理解了它们，就理解了 EVOL 一半。

```
   Anchor                  ←  不可变的价值底线
      │
      ▼
 ┌─────────┐    reflect    ┌─────────┐  consolidate  ┌─────────┐
 │Experience│ ───────────▶ │ Insight │ ────────────▶ │ Memory  │
 └─────────┘                └─────────┘                └─────────┘
      ▲                                                    │
      │                                                    │
      │      (Recorder writes)              (Advisor reads)│
      │                                                    ▼
   产品任务                                           增强提示词
                                                    & 启发用户
```

| 抽象 | 一句话 | 物理形态 |
|---|---|---|
| **Experience** | 单次任务交互的结构化记录 | `experiences.jsonl` 中的一行 |
| **Signal** | 用户对一次 Experience 的反馈（隐式或显式） | 嵌在 Experience 中 |
| **Insight** | Reflector 对一批 Experience 的结构化反思产出 | `insights/YYYY-MM-DD.md` |
| **Memory** | 沉淀下来的长期资产（画像/领域/自我） | `memory/*.yaml` |
| **Anchor** | 来自配置的不可变价值底线 | `config.yaml` 中的 `anchors:` |

> **Insight 是中间产物，Memory 是最终资产。**
> Insight 必须经过 Anchor 检查，才能沉淀为 Memory。
> 这一步是 EVOL 的核心安全阀。

---

## 三、四个核心模块（The 4 Verbs）

如果说五个抽象是 EVOL 的"名词"，那四个模块就是它的"动词"。

```
                 ┌──────────────────────────────────┐
                 │                                  │
                 │   ┌──────────┐    ┌──────────┐  │
   产品 ◀───────▶│   │ Recorder │    │ Advisor  │ │◀──── 产品
                 │   │ (写经验) │    │ (注入&启发)│ │
                 │   └─────┬────┘    └────▲─────┘  │
                 │         │              │        │
                 │         ▼              │        │
                 │   ┌──────────┐    ┌────┴─────┐  │
                 │   │Reflector │───▶│  Memory  │  │
                 │   │(反思)    │    │(沉淀&版本)│  │
                 │   └──────────┘    └──────────┘  │
                 │                                  │
                 │           EVOL Runtime           │
                 └──────────────────────────────────┘
```

### Recorder（记录器） · "产品的日记本"
- **职责**：把产品运行时的事件结构化为 Experience，写入本地。
- **特点**：纯结构化日志，**不做智能判断**。轻量、快、不掉链子。
- **核心 API**：
  - `recorder.start_task(input, ctx)` → `task_handle`
  - `recorder.end_task(task_handle, output)` → `experience_id`
  - `recorder.feedback(experience_id, signal)` → 把用户反馈附加到 Experience

### Reflector（反思器） · "产品的周复盘"
- **职责**：周期性地把累积的 Experience 提炼成结构化 Insight。
- **特点**：LLM 重度使用，但**不做实时反思**。触发条件由配置决定（threshold / manual / scheduled）。
- **核心 API**：
  - `reflector.reflect()` → `[insight_id, ...]`
  - `reflector.replay(experience_range)` → 重新反思历史区间

### Memory（记忆库） · "产品的本事"
- **职责**：持久化三类长期资产 + 版本管理 + 提供查询。
- **特点**：人类可读（YAML）、版本化、可手工编辑。**不是数据库、不是向量库**。
- **核心 API**：
  - `memory.load() / save()`
  - `memory.query(scope, key) → entry`
  - `memory.consolidate(insights) → new_version`
  - `memory.snapshot() / rollback(version)`

### Advisor（建议者） · "产品的智慧输出"
- **职责**：在任务执行流中，把 Memory 的智慧反哺回去——增强提示词，或者反向启发用户。
- **特点**：是 EVOL 唯一一个**对产品调用栈直接施加影响**的模块；其他三个模块都是被动的。
- **核心 API**：
  - `advisor.enhance(prompt, task) → enhanced_prompt`
  - `advisor.inspire(task) → inspiration_text | None`

> 一组对偶关系：
> Recorder + Memory 是**被动的存储**——它们只是写下与读取。
> Reflector + Advisor 是**主动的智能**——它们调用 LLM，做判断。

---

## 四、三个横切组件（Cross-cutting）

四个模块的"内部工作"由三个横切组件协助：

### Anchor System（价值锚点系统）
- 加载 `config.yaml` 中声明的 anchors，转化为 system prompt 注入到 Reflector 的 LLM 调用
- 反思产出的每一条 Insight，都要经过 Anchor 后置过滤
- 任何与 Anchor 冲突的 Insight 被丢弃 + 记录拒因

### Provenance System（溯源系统）
- 每条 Memory entry 都携带 `evidence_ids: [exp_001, exp_007, ...]`
- 任何"系统说我喜欢长句"的结论，都能一键追溯到具体若干次 Experience
- 这是 EVOL 区别于"黑盒成长"的关键差异

### Inspiration Layer（启发层）
- Advisor.inspire 的执行策略：cooldown、frequency、触发条件
- 决定什么时候说话、说什么、怎么说
- "大师感"的工程化所在

---

## 五、三条主数据流（The 3 Loops）

EVOL 内部数据流总共只有三条。理解了它们，就理解了 EVOL 的全部行为。

### 主回路 ①：任务执行流（毫秒~秒级，每次任务）

```
[Product]
    │
    ├─── recorder.start_task(input) ─────────▶ Experience (open)
    │                                              │
    │                                              ▼
    │                                       experiences.jsonl
    │
    ├─── advisor.enhance(prompt) ────┐
    │         ▲                       │
    │         │   ┌─────────────┐    │
    │         └───┤  Memory     │◀───┘   query relevant entries
    │             │  .yaml      │
    │             └─────────────┘
    │
    │    enhanced_prompt
    │         │
    │         ▼
    ├─── [LLM call]
    │         │
    │         ▼
    │       output
    │
    ├─── recorder.end_task(output) ──────────▶ Experience (closed)
    │
    ├─── advisor.inspire() ─────────────────▶ Inspiration text (optional)
    │
    └─── (later) recorder.feedback(rating) ─▶ Signal attached
```

**关键约束**：这条流必须**轻**。本地文件读写 + 一次 YAML 查询 + 一次 prompt 拼接。增加的延迟控制在 50ms 内。

### 主回路 ②：反思流（分钟级，周期性）

```
   [Trigger]                          (threshold / manual / scheduled)
      │
      ▼
   Reflector.reflect()
      │
      ├──▶ read recent Experiences from .jsonl
      │
      ├──▶ build reflection prompt
      │      ├── system: anchors + reflection instructions
      │      └── user:   experience batch (sanitized)
      │
      ├──▶ [LLM call: produce candidate Insights]
      │
      ├──▶ Anchor.filter(candidates)       ← 锚点强约束过滤
      │      │
      │      └─▶ rejected insights logged with reason
      │
      ├──▶ Memory.consolidate(approved_insights)
      │      │
      │      ├── update memory/*.yaml
      │      └── versions/memory-v{N}.snapshot
      │
      └──▶ write insights/YYYY-MM-DD.md
```

**关键约束**：这条流必须**慢**得起，又必须**安全**。LLM 调用可能数十秒，但产品的任务执行流不能被它阻塞——所以反思永远是**异步、独立进程/协程**。

### 主回路 ③：启动与关闭

```
Startup:
   load evol.config.yaml
      │
      ├─▶ validate Anchors (拒绝畸形配置)
      │
      ├─▶ open experiences.jsonl (append mode)
      │
      ├─▶ hydrate Memory from memory/*.yaml
      │      └── verify checksum vs versions/memory-v{latest}.snapshot
      │
      └─▶ register signal handlers (SIGINT, SIGTERM)

Shutdown:
   flush experiences.jsonl
      │
      ├─▶ if Memory is dirty: snapshot
      │
      └─▶ release locks
```

---

## 六、典型时序：从产品视角看 EVOL

把上面三条流压缩到一张时序图：

```
时间 ──▶

  [Product Start]
       │
       ▼
   load config + memory   (启动)
       │
       ├── Task #1 ───▶ enhance ─▶ [LLM] ─▶ end ─▶ inspire?(no, cold start)
       ├── Task #2 ───▶ enhance ─▶ [LLM] ─▶ end ─▶ inspire?(no)
       │       …
       ├── Task #20 ──▶ enhance ─▶ [LLM] ─▶ end ─▶ feedback(edited)
       │
       │     ⟳ threshold reached → trigger Reflection (后台异步)
       │              │
       │              ├── read Exp #1..#20
       │              ├── LLM reflection
       │              ├── Anchor filter
       │              └── Memory v1 → v2  (snapshot)
       │
       ├── Task #21 ──▶ enhance(now smarter) ─▶ [LLM] ─▶ end
       ├── Task #22 ──▶ enhance ─▶ [LLM] ─▶ end ─▶ inspire?(yes!)  💡
       │       …
       │
       ▼
   [Product Shutdown]
       │
       ▼
   flush + final snapshot
```

注意三个时间尺度的差异：
- **任务执行**：毫秒~秒
- **反思**：分钟级，异步，不阻塞任务
- **启发**：在任务结束之后，是任务执行流的"尾巴"

---

## 七、目录结构：`.evol/` 的物理映射

EVOL 在产品本地维护的全部状态：

```
.evol/
├── config.yaml                    # 与 evol.config.yaml 同步的运行时副本
│
├── experiences.jsonl              # 全部 Experience（append-only）
│
├── memory/                        # Memory 资产（人类可读）
│   ├── user_profile.yaml          #   - 用户画像
│   ├── domain_knowledge.yaml      #   - 领域经验
│   └── self_awareness.yaml        #   - 自我认知
│
├── insights/                      # Reflector 产出（按反思日期归档）
│   ├── 2026-05-03-reflection.md
│   ├── 2026-05-23-reflection.md
│   └── ...
│
├── versions/                      # Memory 的历史快照
│   ├── memory-v1.snapshot
│   ├── memory-v2.snapshot
│   └── memory-v3.snapshot         # 当前版本由 manifest 标识
│
├── manifest.yaml                  # 当前 Memory 版本号、checksum、更新时间
│
└── locks/                         # 并发控制（文件锁）
    └── reflection.lock
```

**特点**：
- 全部明文（YAML / JSONL / Markdown）
- 可 `git add .evol/`
- 可手工编辑（编辑 user_profile.yaml 等同于"教导"产品）
- 跨机器迁移就是文件复制
- 备份 / 恢复 = `tar` / `untar`

> **更深一层的含义**：这份目录格式不是"某种语言 SDK 的私有产出"，而是 EVOL 的**真正标准**——下一节展开。

---

## 八、语言无关的磁盘协议 + 多语言 SDK 战略

EVOL 需要服务 **Python、TypeScript、Java** 三个生态。这一节回答一个根本问题：

**这三种语言的 SDK 之间，到底是什么关系？**

如果各做各的，那 EVOL 会变成"三个产品恰巧重名"——这是我们最要避免的。

### 8.1 双层架构：Protocol 优先于 SDK

EVOL 在多语言意义上分为两层：

```
┌──────────────────────────────────────────────────────────────┐
│   Layer 2:  Language SDK（Bindings）                          │
│                                                                │
│      ┌──────────┐   ┌────────────┐   ┌──────────────┐         │
│      │ evol-py  │   │  evol-ts   │   │  evol-java   │         │
│      │ (Python) │   │ (Node/TS)  │   │   (JVM)      │         │
│      └──────────┘   └────────────┘   └──────────────┘         │
│              每种语言一份"语言绑定"实现                       │
└────────────────────────┬─────────────────────────────────────┘
                         │  read / write / lock / version
                         ▼
┌──────────────────────────────────────────────────────────────┐
│   Layer 1:  EVOL Disk Protocol（语言无关的"共享真理"）         │
│                                                                │
│   • .evol/ 目录的精确文件格式与 schema                        │
│   • 五个核心抽象的字段定义                                    │
│   • 反思 / 沉淀 / 启发 / 版本变迁的状态机规范                 │
│   • 并发控制与原子性约束                                      │
│                                                                │
│           ★  这才是 EVOL 真正的"标准"  ★                      │
└──────────────────────────────────────────────────────────────┘
```

**核心原则：**

- **Disk Protocol 是唯一的"共享真理"**——它精确规定 `.evol/` 中每个文件的格式、字段语义、状态变迁、版本演进规则
- **Language SDK 是协议的实现**——只要它们读写同一份 `.evol/`、产生同样的状态变迁，**就是同一个 EVOL**
- **三种语言不是"翻译关系"，而是"共同实现一个标准"**——就像浏览器之间不是翻译关系，而是共同实现 W3C 标准

这条划分让 EVOL 在多语言意义上获得三个关键性质：

| 性质 | 含义 |
|---|---|
| **互操作性** | Python 写出的 `.evol/` 可被 Java SDK 读取并继续演化；反之亦然 |
| **可分阶段实现** | 不必等三种 SDK 同时就绪——只要 Disk Protocol 稳定，SDK 可以错时上市 |
| **可独立演化** | 各语言 SDK 可以采用不同的实现策略（CLI 薄壳 / 原生），互不干扰 |

### 8.2 SDK 实现策略：薄壳 vs 原生

每种语言的 SDK 可以选择两条路径，**两者都符合 Disk Protocol**：

**策略 A：薄壳实现（Thin Binding）**
- 埋点 API（start_task / end_task / feedback / enhance / inspire）由 SDK 直接读写本地文件
- 反思 / 沉淀 / 版本化等"重活"通过子进程调用 `evol` CLI（reference 实现提供）
- 适合：起步阶段 / 小语种生态 / 快速对齐

**策略 B：原生实现（Native Binding）**
- 全部模块（Recorder / Reflector / Memory / Advisor）在该语言生态内原生实现，不依赖外部二进制
- 适合：成熟阶段 / 大型企业部署 / 性能关键场景

**关键约束**：无论 A 还是 B，**只要遵守 Disk Protocol，对外行为必须一致**。
为此 EVOL 提供一份《Conformance Test Suite》——任何 SDK 实现都必须能跑过同一组测试集，确认其产生的 `.evol/` 与参考实现在关键字段上**逐字节兼容**。

### 8.3 Reference 实现：Python 先行

经过权衡，v0.1 的 reference 实现选择 **Python**，理由：

- LLM SDK 生态最成熟（Anthropic / OpenAI 官方 SDK 首发都在 Python）
- 反思流程深度依赖 LLM 调用，Python 在 prompt 工程领域工具链最完整
- 起步阶段开发者画像（CLI 工具作者、AI 应用工程师）以 Python 为主
- 一份 Python 包同时提供 `evol` CLI 二进制——TypeScript / Java SDK 起步时可以直接 shell out 复用

**版本路线图（参考）：**

| 版本 | SDK 进展 |
|---|---|
| **v0.1** | `evol-py` —— 完整原生实现，自带 `evol` CLI |
| **v0.2** | `evol-ts` —— 起步采用薄壳策略，复用 `evol` CLI |
| **v0.3** | `evol-java` —— 原生 / 薄壳由企业场景需求决定 |
| **v1.0** | 三种 SDK 全部具备完整原生能力，可彼此替换 |

> 路线图节奏可调，但**顺序不变**：Python first, TypeScript second, Java third。

### 8.4 多 SDK 共写同一 `.evol/`：并发约束

允许跨语言协作的低频场景——例如 Python 进程负责日常埋点、Node 工具触发反思、Java 服务做归档导出。Disk Protocol 必须为此预留：

- `experiences.jsonl` 是 **append-only**；多写入者通过 OS 级 advisory file lock 串行追加
- 反思流持有 `locks/reflection.lock` **全局排他锁**——同一项目同一时刻只允许一个反思过程在跑（任何语言的 SDK 都遵守）
- Memory 写入采用 **write-then-rename** 模式确保原子性
- 每次 Memory 变更必须同步更新 `manifest.yaml` 中的 `version + checksum`，作为版本同步的真相源

任何 SDK 实现都必须遵守这些约束——这是 Disk Protocol 的强约束部分，由 Conformance Test Suite 验证。

### 8.5 这条决定对后续文档的归属

这个分层让后续文档的归属变得清晰：

| 文档 | 归属 | 性质 |
|---|---|---|
| **CONTRACT.md** | **Disk Protocol** | API 行为契约——语言无关 |
| **DATA-MODEL.md** | **Disk Protocol** | 五个核心抽象的字段级定义——语言无关 |
| **FLOWS.md** | **Disk Protocol** | 反思 / 增强 / 启发的状态变迁——语言无关 |
| `evol-py/README` 等 | Layer 2（语言绑定） | Python SDK 的语言惯用 API、类型、错误模型 |
| `evol-ts/README` 等 | Layer 2（语言绑定） | TypeScript SDK 的语言惯用 API、类型、错误模型 |
| `evol-java/README` 等 | Layer 2（语言绑定） | Java SDK 的语言惯用 API、类型、错误模型 |

> **核心三份设计文档（CONTRACT / DATA-MODEL / FLOWS）描述的不是"Python SDK 的 API"，而是"EVOL 协议本身"。**
> 各语言 SDK 的具体 API 风格、类型表达、错误模型，归属于各自的"语言绑定文档"。

---

## 九、扩展点（Extension Points）

模块之间通过一条**Evolution Bus**通信，事件驱动。这让 EVOL 在不破坏接入契约的前提下保持可扩展：

| 扩展点 | 说明 | 示例 |
|---|---|---|
| `ReflectorPlugin` | 自定义反思策略与 prompt 模板 | 行业特定的反思角度 |
| `SignalAdapter` | 自定义信号语义 | 把"用户停留时长"映射为满意度 |
| `MemoryShape` | 在三类标准之外加一类 Memory | "团队画像"、"项目知识" |
| `AdvisorChannel` | 在 enhance 之外加预/后处理通道 | 输出风格后处理 |
| `AnchorRule` | 自定义锚点约束类型 | 正则、关键词、语义判别 |

> **所有扩展都必须遵守 PRINCIPLES**：
> 可读、可关闭、可回滚、不破坏接入成本。
> 任何扩展点的存在都不允许偷偷违反这四条。

---

## 十、非功能性属性

| 维度 | 目标 |
|---|---|
| **性能** | 任务执行流增加 < 50ms（仅文件读写 + 模板拼接） |
| **存储** | 1 万次任务约 10MB；100 万次约 1GB（可配压缩归档） |
| **依赖** | 只依赖标准库 + LLM SDK；**不依赖向量库 / 图数据库 / 外部服务** |
| **隔离** | 不同产品的 `.evol/` 完全独立，无共享状态 |
| **并发** | 任务执行支持并发；反思全局串行（一个产品一次只反思一次）|
| **可观测** | `experiences.jsonl` 本身即审计日志；`evol status` 一键查看健康度 |
| **可移植** | 单一目录结构，无外部依赖，可跨机器、跨用户、跨 OS 迁移 |
| **多语言** | Python（reference）/ TypeScript / Java；通过 Layer 1 Disk Protocol 互操作 |
| **嵌入式部署** | 支持 Direct API / Subprocess CLI / Host Agent 三种 LLM Backend；可作为 Skill 嵌入 Claude Code / Codex 等宿主 Agent（详见 LLM-BACKENDS.md） |

---

## 十一、明确不在 v0.1 的事

> 这一节**和 VISION 的「非目标」呼应**——架构层面，我们提前画好以下边界。

- **多用户场景**：v0.1 假设 `.evol/` 服务单一使用者
- **经验外部化**：一个产品的 Memory 导出给另一个产品继承（v0.2 +）
- **类比迁移**：跨场景 Insight 推理（v0.3 +）
- **元认知层**：反思"反思方式"本身（v0.4 +）
- **验证引擎**：Hypothesis A/B 验证（v0.5 +）
- **向量检索 / 图谱**：不在路线图，除非有强证据证明 YAML 撑不住
- **远程 / SaaS / 云同步**：不在路线图，本地优先是底线

每往这些方向加一步，都需要回到 VISION 与 PRINCIPLES 重新论证。

---

## 十二、和后续文档的关系

```
   VISION  ─────  我们要去哪里
       │
       ▼
   PRINCIPLES ──  在每个分岔路口怎么选
       │
       ▼
   QUICKSTART  ── 用起来到底什么样（试金石）
       │
       ▼
   ARCHITECTURE ─ 全局蓝图（你正在读这份）
       │
       ├──▶ Disk Protocol（语言无关层）
       │      ├── CONTRACT       —— API 行为契约
       │      ├── DATA-MODEL     —— 五个核心抽象的字段级定义
       │      ├── FLOWS          —— 反思 / 增强 / 启发的状态变迁
       │      └── LLM-BACKENDS   —— 三 backend（direct / subprocess / host）协议
       │
       ├──▶ Language Binding（每语言一份）
       │      ├── evol-py/README     —— Python 绑定（reference）
       │      ├── evol-ts/README     —— TypeScript 绑定
       │      └── evol-java/README   —— Java 绑定
       │
       └──▶ Implementation（实施层，绑定具体语言）
              └── IMPLEMENTATION.md  —— evol-py 工程结构、模块设计、进度表
```

后续三份文档（CONTRACT / DATA-MODEL / FLOWS）会基于这份架构往下钻。
**任何深入文档与本架构图冲突时，先回到这里对齐**——架构是其他设计文档的母版。

---

## 十三、写在最后

这份蓝图的目的，不是穷尽 EVOL 的所有细节，而是回答**八个最高频的问题**：

1. EVOL 站在哪一层？      → 第一节
2. EVOL 由什么组成？      → 第二、三节（5 名词 + 4 动词）
3. 数据怎么流？           → 第五节（三条主回路）
4. 一次任务发生了什么？   → 第六节（时序）
5. 状态存在哪里？         → 第七节（`.evol/`）
6. 多语言怎么做？         → 第八节（Disk Protocol + SDK 战略）
7. 怎么扩展？             → 第九节（扩展点）
8. 什么不做？             → 第十一节（非目标）

如果一个新人读完这份文档**还能清晰复述这八个问题的答案**，那这份架构就达到了它的目的。

> Harness 的架构图告诉你"任务怎么稳定地跑完"。
> EVOL 的架构图告诉你"任务怎么一次比一次跑得更好"。
>
> 形态可以演化，
> 这个底层意图永远不会变。

---

## 附：版本与迭代

- **v0.1（本版）** —— MVP 架构，5 名词 + 4 动词 + 3 横切 + 3 数据流
- 每一次重要架构变更，需附一份 ADR 说明触发原因与替代方案
- 子文档（CONTRACT / DATA-MODEL / FLOWS）是这份架构的细化，不是替代
