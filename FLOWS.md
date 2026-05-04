# 《EVOL 关键流程设计》

> FLOWS.md · 这是 EVOL 内部三条主流程（反思 / 增强 / 启发）以及异常处理流程的**实现级**说明。
>
> 与前两份文档的关系：
> - **CONTRACT** 规定 "API 长什么样、文件放哪里、协议怎么演"
> - **DATA-MODEL** 规定 "每个字段长什么样"
> - **FLOWS（本文）** 规定 "里面到底怎么转——什么时候触发、读什么、调什么 prompt、产出什么、写到哪"
>
> 这份文档面向 SDK 实现者。读完它，应该能动手写 reflector / advisor 的核心代码。

---

## 一、本文定位

本文规定 EVOL 三条主流程的内部决策逻辑：

1. **Reflection Flow（反思流）** —— 把 Experience 提炼为 Insight，写入 Memory
2. **Enhancement Flow（增强流）** —— 把 Memory 注入到产品的 prompt
3. **Inspiration Flow（启发流）** —— 在合适时机向用户输出洞见

外加一组**异常与恢复流程**：LLM 调用失败、锁残留、checksum 失配、版本回滚等。

> **本文不绑定具体语言**——所有伪码、prompt 模板、状态机均独立于 Python / TypeScript / Java。
> 各语言 SDK 在实现时可适配语言惯用法，但**决策语义必须一致**（由 Conformance Test Suite 验证）。

---

## 二、流程总览

```
                   ┌──────────────────────────────────┐
                   │            Product               │
                   └──────────────────────────────────┘
                          │  start_task     │
                          ▼  end_task       │
                                            ▼
   +-----------+   advisor.enhance(prompt) ──────────────┐
   |           |                                         │
   |  Memory   |◀────── consolidate ─────┐               │
   |           |                         │               │
   +-----+-----+                         │              read
         │                               │               │
         │ query                         │               ▼
         │                          +----+-----+    +--------+
         │                          |Reflector |    |Advisor |
         │                          | (流 ①)   |    | (流 ②) |
         │                          +----+-----+    +---+----+
         │                               │               │
         │                       reads   │           reads│
         ▼                               │               │
    +----------+                         │               │
    |Experience|◀───── Recorder ─────────┼───────────────┘
    +----------+                         │
                                         │
                  triggered by    ┌──────┘
                ┌───────────┐     │
                │ Threshold │ ────┤
                │ Manual    │     │
                │ Scheduled │     │
                └───────────┘     │
                                  ▼
                            (流 ① runs)
                                  │
                                  ▼
                         insights/*.md + new Memory snapshot

   advisor.inspire() ─────────────────────────▶ 流 ③ Inspiration
```

三条流的时间尺度截然不同：

| 流 | 频率 | 时延 | 是否阻塞产品 |
|---|---|---|---|
| Enhancement | 每次任务一次 | < 50ms | 是（但极轻） |
| Inspiration | 每次任务尾部偶发 | < 2s（可超时返 null） | 否（异步可中断） |
| Reflection | 阈值 / 周期 / 手动 | 数秒~数分钟 | 否（独立进程或协程） |

---

## 三、Reflection Flow（反思流）

> 这是 EVOL 最复杂、最关键的流程。Reflector 是从「数据」到「智慧」的炼金炉。

### 3.1 触发器

三种触发器，由 `evol.config.yaml.reflection.trigger` 决定：

| trigger | 触发条件 |
|---|---|
| `manual` | 仅由 CLI `evol reflect` 或外部调用 `reflector.reflect()` 触发 |
| `threshold` | 自上次反思后新增 Experience 数 ≥ `threshold`（默认 20） |
| `scheduled` | cron 表达式到期（如每天 20:00） |

[MUST] 任何触发器都通过同一入口进入反思流程，差别仅在"谁来按下按钮"。

### 3.2 前置条件检查

```
1. acquire locks/reflection.lock                    [MUST exclusive]
   └── if held by another process:
        ├── (manual)    error fast 提示锁占用
        └── (auto)      静默放弃，等待下次窗口

2. verify manifest.yaml.protocol_version  matches   [MUST]
3. verify memory checksum vs disk                   [MUST]
   └── if mismatch:                                 [MUST]
        ├── log warning + write to insights/<date>-reflection.md
        ├── set status = "preflight_failed"
        └── abort（不允许 best-effort 反思）

4. compute experience batch:                        [MUST]
   └── range = (last_reflection_end_id, latest_id]
       size  = min(len(range), max_experiences_per_run)
```

### 3.3 反思批次的"取材"策略

不是所有 Experience 都同等重要。Reflector 在构造反思 prompt 前 [MUST] 做一次**采样与排序**：

| 优先级 | 含义 |
|---|---|
| **优先纳入** | 含 `signal: edited / discarded / rated:1-2 / comment` 的 Experience（这些是高信号） |
| **均衡纳入** | 没有 signal 但 task_kind 多样的 Experience，避免反思过窄 |
| **末位纳入** | 含 `signal: kept` 且无其他差异的 Experience（信号低） |

[SHOULD] 当 batch 超过 `max_experiences_per_run` 时，按优先级保留高优先级 Experience。

### 3.4 反思 Prompt 的标准结构

EVOL 推荐（[SHOULD]）使用如下三段式 prompt 模板。各 SDK 可微调措辞，但**段落结构与字段输出格式 MUST 保持一致**。

```
══════════ SYSTEM ══════════
You are an Evolution Reflector. 
Your job: examine a batch of past task interactions and produce 
structured Insights about how the product can serve its user better.

Domain: {product.domain}
Memory kinds you can update:
  - user_profile      (preferences, habits, style)
  - domain_knowledge  (patterns, pitfalls, best practices)
  - self_awareness    (own strengths, weaknesses, error patterns)

You MUST respect the following anchors. If an Insight contradicts 
any anchor, do NOT emit it.

  Anchors:
  [0] {anchors[0].rule}
  [1] {anchors[1].rule}
  ...

You MUST output a JSON array of Insight objects. Each object:
  {
    "scope": "user_profile|domain_knowledge|self_awareness",
    "key":   "<snake_case>",
    "claim": "<short natural-language claim>",
    "proposed_change": { "op": "set|merge|strengthen|weaken|retire", 
                         "value": <op-specific> },
    "confidence": 0.0..1.0,
    "evidence_ids": [<exp_id>, ...]
  }

══════════ USER ══════════
Existing Memory (current state):
<canonicalized memory/*.yaml content>

Recent Experiences:
<experiences in chronological order, sanitized to fit budget>

Reflect on these Experiences. Produce Insights only when there is 
sufficient evidence. Prefer "merge / strengthen" over "set" when 
existing entries are partly correct.

Return only the JSON array. No prose.
```

### 3.5 LLM 调用约束

- [MUST] LLM 调用返回类型可能是同步的 `LLMResponse`（direct / subprocess backend）或异步的 `DeferredLLMResponse`（host backend）；调用方 [MUST] 用 isinstance 分支处理
- [MUST] direct / subprocess backend：反思 LLM 调用 [MUST] 在自身的超时窗口内完成（默认 120s）；超时 [MUST] 触发流程降级为 `status: timeout`
- [MUST] host backend：返回 `DeferredLLMResponse` 后 [MUST] 立即持久化 deferred state 到 `.evol/deferred/<request_id>.state.json`，写出 `pending_requests/<request_id>.md`，状态机进入 `pending_host`，整个反思流程**不阻塞**地结束
- [MUST] LLM 输出（同步路径）[MUST] 经 JSON 解析；解析失败 [MUST] 重试 1 次（同 prompt），二次失败标记 `status: parse_failed`
- [SHOULD] 总 token 上限受配置约束；超长 batch [MUST] 自动按优先级裁剪到上限内

### 3.6 Anchor 后置过滤

LLM 已在 system prompt 中被告知 anchor，但仍 [MUST] 做后置过滤——LLM 不可信。

```
for insight in raw_insights:
   for anchor in anchors:
      if conflict(insight, anchor):
         insight.status   = "rejected"
         insight.rejection = { by_anchor: anchor.index,
                               rule:      anchor.rule,
                               reason:    explain(insight, anchor) }
         break
   else:
      insight.status = "pending"   # 待沉淀
```

`conflict()` 的实现因 anchor.kind 而异：

| anchor.kind | 冲突判定 |
|---|---|
| `text` | 调用一次轻量 LLM 元判定（system + insight + anchor.rule → boolean） |
| `regex` | 对 `insight.claim` 做 regex 匹配 |
| `semantic` | 用 `anchor.rule` 中的 prompt 模板做语义判别 |

[MUST] 任何 `conflict()` 评估失败 [MUST] **保守地**判定为冲突（fail-safe）。

### 3.7 Insight → Memory 沉淀

**逐条 Insight 处理**：

```
for insight in pending_insights:
   target_entry = memory[insight.scope].entries.find(key = insight.key)
   
   match insight.proposed_change.op:
      "set":
         create or replace target_entry with {
            value: change.value,
            confidence: insight.confidence,
            evidence_ids: insight.evidence_ids,
            rationale: insight.claim,
            ...
         }
      
      "merge":
         target_entry.evidence_ids = union(existing, new)
         target_entry.confidence  = recompute(see §3.8)
         target_entry.rationale   = merge_rationale(...)
      
      "strengthen":
         target_entry.confidence = min(1.0, current + change.value)
         target_entry.evidence_ids = union(...)
      
      "weaken":
         target_entry.confidence = max(0.0, current - change.value)
         if target_entry.confidence < threshold:
            target_entry.status = "retired"
      
      "retire":
         target_entry.status = "retired"  # 不删除，保留历史
   
   insight.status = "applied"
   insight.applied_to = MemoryRef(target_entry)
```

**冲突解决**：若同一批 Insight 中有多条针对同一 `(scope, key)`：

```
1. 按 confidence 降序排列
2. 取 top-1 处理；其余标记 status = "superseded"
3. superseded 的 evidence_ids 仍并入 top-1（不丢证据）
```

### 3.8 Confidence 重算约束

[MUST] 在 `merge` 操作后，confidence 必须按 evidence 数量重算（与 DATA-MODEL §9.3 推荐表一致）：

```
new_confidence = min(
    LLM_returned_confidence,
    confidence_cap_by_evidence_count(len(evidence_ids))
)
```

这层"硬上限"防止 LLM 报告过度自信。

### 3.9 写出与版本化

```
1. write memory/*.yaml using write-then-rename atomicity
2. compute new checksum
3. snapshot:    versions/memory-v{N+1}.snapshot ← tar of memory/
4. update manifest.yaml: { current_version: N+1, checksum: ..., last_updated, last_reflection }
5. write insights/<YYYY-MM-DD>-reflection.md  ← frontmatter + 通过/拒绝两节
6. release locks/reflection.lock
```

[MUST] 任何中间步骤失败 [MUST] 回滚——绝不允许"半完成"的反思。

### 3.10 Reflection 状态机

```
   [triggered]
       │
       ▼
   acquire_lock ─── failed ───▶ [skipped]
       │
       ▼
   preflight_check ─── failed ──▶ [preflight_failed]
       │
       ▼
   build_batch ─── empty ──▶ [no_op]
       │
       ▼
   call_llm ──── DeferredLLMResponse (host backend) ─▶ persist_deferred_state ─▶ [pending_host]
       │
       │ LLMResponse (direct / subprocess backend)
       │
       ├── timeout/failure ──▶ [llm_failed]
       │
       ▼
   parse_output ─── invalid ──▶ retry_once ──▶ [parse_failed]
       │
       ▼
   anchor_filter (always succeeds; rejected insights logged)
       │
       ▼
   consolidate ─── any failure ──▶ rollback ─▶ [consolidate_failed]
       │
       ▼
   snapshot + write_manifest + write_insights_md
       │
       ▼
   release_lock ──▶ [completed]


   [resume_pending] (host backend, 由 SDK init 或 reflect 触发)
       │
       ▼
   scan .evol/deferred/  ──── 无 pending ──▶ [no_op]
       │
       ▼
   for each pending:
       poll(deferred) ─── completed_response not yet ──▶ skip (keep pending)
       │
       │ completed_response ready
       ▼
       parse → anchor_filter → consolidate → snapshot
       │
       ▼
       mark deferred state = "consumed";
       move completed file to processed/
       │
       ▼
   release_lock ──▶ [resumed_host]
```

每种终态 [MUST] 写入 `insights/<date>-reflection.md` 的 frontmatter `status` 字段。
`pending_host` 终态特殊：[MUST] 写入 `insights/<date>-pending.md` 的占位条目，并把 `status: pending` + 关联 `deferred_id`；待 `resumed_host` 完成后 [MUST] 把占位条目转为正式条目（追加到当天 reflection.md 或单独成文）。

---

## 四、Enhancement Flow（增强流）

> 这条流必须**毫秒级**——任何抖动都会被产品代码感知。

### 4.1 调用形态

```
enhanced_prompt = advisor.enhance(prompt, task_ctx?)
```

### 4.2 流程步骤

```
1. resolve current Experience (from active task_handle, or task_ctx)
2. determine relevance keys:
      keys = derive_keys(task_kind, task_ctx, prompt)
3. query Memory:
      candidates = []
      for kind in [user_profile, domain_knowledge, self_awareness]:
          for entry in memory[kind].entries:
              if entry.status != "active":  continue
              if entry.confidence < min_confidence:  continue
              score = relevance_score(entry, keys, task_ctx)
              if score > 0:
                  candidates.append((score, entry, kind))
4. rank candidates by score desc
5. apply token budget:
      selected = []
      remaining = budget   # default 30% of original prompt tokens
      for cand in candidates:
          if cand.size <= remaining:
              selected.append(cand); remaining -= cand.size
6. format injection:
      block = render_template("advice_block", selected)
7. compose:
      enhanced = system_prefix(block) + prompt
8. record into current Experience:
      experience.advice_used += [adviceref(e) for e in selected]
9. return enhanced
```

### 4.3 关键决策

#### 4.3.1 Memory 检索：不是向量检索

v0.1 [MUST NOT] 使用向量数据库。检索用三种手段：

```
relevance_score(entry, keys, ctx):
   score = 0
   # (a) keyword overlap
   if any(k in entry.key for k in keys):              score += 3
   if any(k in entry.value for k in keys):            score += 1
   # (b) task_kind match
   if entry.tags contains ctx.task_kind:              score += 2
   # (c) recency boost
   if entry.last_validated_at > now - 30 days:        score += 1
   return score * entry.confidence
```

[SHOULD] 实现可在 v0.2 引入更高级的检索，但 v0.1 [MUST] 满足"不依赖向量库"原则。

#### 4.3.2 Token 预算

```
budget = min(
   config.advisor.max_advice_tokens,           # default 600
   0.3 * tokens(prompt)                        # default cap
)
```

[MUST] 任何增强结果的 token 数不超过预算。超出 [MUST] 截断（按 score 升序丢弃低分项）。

#### 4.3.3 注入位置

[MUST] 注入到 prompt 的 **最前面**（system prefix），而非 user content；
[MUST] 用清晰的分隔符标记，便于 LLM 识别上下文：

```
[Advice from EVOL · derived from prior interactions]
- [user_profile / summary_length, conf 0.85] 用户偏好 60-80 字总结
- [user_profile / tone, conf 0.75] 偏好简洁陈述句，避免感叹号
[End advice]

<original prompt continues here>
```

[MUST] 每条建议附带 `kind / key / confidence` 三元组——便于 LLM 自己评估是否采纳。

#### 4.3.4 可追溯标记

[SHOULD] 在被注入的内容中追加可追溯的 HTML 风格注释（这些注释不出现在 user 视域，但供下游审计工具解析）：

```
<!-- evol:advice ref="mem_user_profile_v7#summary_length" conf="0.85" -->
```

### 4.4 失败降级

| 失败 | 行为 |
|---|---|
| Memory 文件读取失败 | 原样返回 prompt；记录 warning |
| 检索抛异常 | 同上 |
| Token 计算失败（无 tokenizer） | fallback 用字符数 / 4 估算 |
| 当前没有 active Experience | 仍可工作；advice_used 记到一个 anonymous handle |

[MUST] enhance **永不抛异常**到产品代码——它必须是"装饰性"的，缺失时降级为 no-op。

---

## 五、Inspiration Flow（启发流）

> 这条流是 EVOL 的灵魂，也是最容易被滥用的能力。
> **节制是它的一等设计目标。**

### 5.1 调用形态

```
inspiration | null = advisor.inspire(task_ctx?)
```

### 5.2 节流（Throttling）门控

[MUST] 在生成前先做四道节流检查；任意一道失败立刻返回 null：

```
1. config.inspiration.frequency != "never"               (otherwise return null)

2. cooldown_check:
      last = read_inspiration_history()
      if now - last.timestamp < config.cooldown_hours:
          return null

3. daily_quota_check:
      if today.count >= config.max_per_day:
          return null

4. warmup_gate:
      total_experiences  = count(experiences.jsonl)
      if total_experiences < min_warmup (default 10):
          return null
```

### 5.3 触发概率

通过节流后，[MUST] 进一步按 frequency 抛硬币：

| frequency | 通过节流后的输出概率 |
|---|---|
| `never` | 0% |
| `low` | 15% |
| `medium` | 35% |
| `high` | 70% |

[SHOULD] 实现使用确定性 PRNG（按 task_id 哈希）以保证可重现性测试。

### 5.4 启发 Prompt（与反思 Prompt 截然不同）

启发 prompt 的目标不是产出 Insight 候选，而是**生成对用户友好的洞见**：

```
══════════ SYSTEM ══════════
You are an Evolution Inspirer.
Your job: based on accumulated user-specific knowledge, offer ONE 
short observation or suggestion that the user has likely not yet 
considered. The tone is gentle, curious, never preachy.

Anchors (MUST honor):
  [0] {anchors[0].rule}
  ...

You MUST output a JSON object:
  {
    "kind":         "pattern|suggestion|question|insight",
    "text":         "<≤ 80 字>",
    "evidence_ids": [<exp_id>, ...]
  }

If nothing valuable to share, output: { "kind": "none", "text": null }

══════════ USER ══════════
Active Memory:
<top-N entries from memory by confidence × recency>

Last few Experiences:
<recent 5-10 experiences>

Generate one inspiration if it would genuinely help the user. Otherwise, 
return "none". Quality over quantity.
```

### 5.5 输出后处理

```
1. parse JSON
2. if kind == "none":  return null
3. anchor_filter(text)  ── if violates → return null
4. if len(evidence_ids) == 0:  return null   # 必须有证据
5. record to inspiration_history (for cooldown)
6. record to current Experience as { kind: "inspiration_emitted", ref: ... }
7. return { text, kind, evidence_ids, confidence }
```

### 5.6 用户呈现层（不是协议范畴，但建议）

[SHOULD] 各 SDK 提供一个轻量的呈现帮助函数：

```
"💡 EVOL: <text>"
"   (基于 <N> 条历史观察 · 信心 <conf>)"
```

但**呈现方式不是协议约束**——产品可以自定义。

### 5.7 失败降级

| 失败 | 行为 |
|---|---|
| LLM 超时 / 失败 | 返回 null；不计入 cooldown（不"惩罚"用户） |
| Anchor 拒绝 | 返回 null；记录到本次 Experience |
| 评估流程异常 | 返回 null；warning |

[MUST] inspire 永不抛异常到产品代码。

---

## 六、异常与恢复流程

### 6.1 LLM 调用失败

| 调用 | 失败行为 |
|---|---|
| Reflection LLM | 标记 reflection.status; 不破坏既有 Memory |
| Inspiration LLM | 静默返回 null |
| Anchor `text` 元判定 LLM | **保守判定为冲突**（fail-safe） |

[MUST] 任何 LLM 调用失败 [MUST] 通过结构化日志记录，不输出到 stdout / stderr。

### 6.2 锁残留恢复

```
on SDK init:
   if exists(locks/reflection.lock):
      stale = (now - lock.mtime) > stale_threshold (default 5 min)
      if stale:
         log warning
         delete lock
      else:
         status = "another reflection in progress"
```

[MUST] 启动时**只读取**锁文件元数据；不主动获取锁。
[MUST] 若有 PID 在锁文件中，[SHOULD] 通过 OS 探测进程是否存活。

### 6.3 Memory checksum 失配

```
on SDK init:
   computed = compute_checksum(memory/*.yaml)
   recorded = manifest.checksum
   if computed != recorded:
      mode = config.checksum_mismatch_policy   # default "warn_and_freeze"
      
      "warn_and_freeze":
         log error
         freeze writes (no new reflection / consolidate)
         enhance / inspire continue to work (read-only)
         require user intervention
      
      "auto_repair":         # 仅企业模式可用，需显式配置
         take snapshot of current state
         rebuild manifest.checksum from disk
```

[MUST NOT] 在 `auto_repair` 模式下静默修改 Memory；任何变更都必须创建 snapshot。

### 6.4 版本回滚（rollback）

```
rollback(target_version):
   1. acquire reflection.lock
   2. verify target snapshot exists in versions/
   3. extract target snapshot to memory/  (write-then-rename)
   4. update manifest.current_version = target_version
   5. update manifest.checksum
   6. append a system Experience to experiences.jsonl:
        { id: exp_..., task_kind: "system.rollback",
          input: { from: N, to: target_version },
          output: "completed",
          status: closed }
   7. write insights/<date>-rollback.md  describing what changed
   8. release lock
```

[MUST] rollback **不删除**任何已有 snapshot——它只是切换 manifest 指针。
[MUST] rollback 后下次反思 [MUST] 从 rollback 后的 Memory 状态开始演化。

### 6.5 跨 SDK 并发冲突

```
case A: 两个 SDK 同时 append experiences.jsonl
   → 通过 OS advisory lock 串行化；每个 SDK 写一行后释放

case B: 两个 SDK 同时尝试 reflect
   → 后者获取 reflection.lock 失败，返回 "skipped"

case C: SDK A 反思完成后，SDK B 启动并发现 manifest version 比自己缓存的新
   → SDK B [MUST] 重新加载 Memory，再继续

case D: SDK A 修改了 anchors，SDK B 仍持有旧 anchors
   → 启动时 anchors_hash 校验会暴露差异；
     SDK B [MUST] 重读 config，并强制下次反思前刷新 anchors
```

[MUST] 所有 SDK 共享同一份 Disk Protocol 的并发约束。

### 6.6 Host backend 异常恢复路径

| 异常 | 恢复路径 |
|---|---|
| pending request 写入失败（磁盘满 / 权限） | reflection 终态标 `pending_write_failed`；下次 reflect 重试；不破坏既有 Memory |
| completed response 缺失（宿主未处理） | resume_pending 在该 deferred 上 skip；deferred state 维持 `pending`；reflect 触发时仅消化已就绪的项 |
| completed response 解析失败（schema 不匹配） | deferred state 标 `parse_failed`；保留原文件供调试；写一条 warning 让人工介入或重新生成 |
| pending request 过期（超过 TTL） | 启动时清理：移动到 `pending_requests/expired/`；写一条 `task_kind: system.deferred_expired` 的 Experience；不报错 |
| 宿主 agent 错误地修改了 pending request | 启动时 frontmatter `request_id` checksum 校验失败 → 视同 `parse_failed` |
| EVOL 与宿主 agent 时钟不同步 | 不影响——TTL 比对使用 EVOL 端时钟，宿主端未参与计时 |
| 同一 deferred 被 poll 两次（不应发生） | 第二次 poll 在 `consumed` 状态下 [MUST] 直接返回 None（幂等） |

### 6.7 Subprocess backend 异常恢复路径

| 异常 | 恢复路径 |
|---|---|
| 子进程超时 | 标记为 `llm_failed`；不破坏既有 Memory；warning 提示用户检查本地 CLI 配置 |
| 子进程退出码非零 | 同上；stderr 截断后写入日志（去除 PII） |
| 子进程不存在（command 错误） | 启动时 fail-fast；提示用户检查 `llm.subprocess.command` |
| 子进程输出格式不匹配 | 视同 LLM 解析失败；进入 `parse_failed` 路径 |

---

## 七、流程之间的不变量（Invariants）

无论哪条流程进行到哪一步，下列不变量 [MUST] 在 disk 上保持成立：

| Invariant | 含义 |
|---|---|
| **I-1** | `experiences.jsonl` 是单调追加；不存在被修改的历史行 |
| **I-2** | `manifest.yaml.memory.current_version` 必然指向 `versions/memory-v{N}.snapshot` 中的合法 N |
| **I-3** | `Memory.entry.evidence_ids` 中每个 ID 在 `experiences.jsonl`（或归档）中可被找到 |
| **I-4** | `insights/*.md` 一旦写入即不可修改；新反思产生新文件 |
| **I-5** | 任意时刻最多一个反思过程持有 `reflection.lock` |
| **I-6** | `manifest.yaml.checksum` 与 `memory/*.yaml` 的 canonical 序列化 sha256 严格一致 |
| **I-7** | 任何 `status: rejected` 的 Insight [MUST] 在 `insights/*.md` 中可被定位、可解释 |

[MUST] Conformance Test Suite 包含针对每个 Invariant 的破坏性测试。

---

## 八、与 CONTRACT / DATA-MODEL 的衔接

| 决定 | 由谁规定 |
|---|---|
| API 签名形态 | CONTRACT |
| 文件外层 schema | CONTRACT |
| 字段细节 | DATA-MODEL |
| 流程内部决策 | **本文** |
| Prompt 模板细节 | 本文（参考性，可由 SDK 微调） |
| 各语言惯用法 | 各语言 SDK 文档 |

冲突处理优先级：**CONTRACT > DATA-MODEL > FLOWS > Language Binding**。

---

## 九、写在最后

流程的复杂性是不可逃避的——成长性本身就是复杂能力。但流程的复杂**不是借口**：

> 三条流程加起来不过 30 个步骤。
> 比起任何一个完整的智能体框架，这已经是极度克制的设计。

如果未来某个新功能想加入 EVOL，请先回答：

- **它属于哪条已有流程？** → 如果不属于，强烈怀疑应该不应该加
- **它会让 enhance 的 50ms 预算变长吗？** → 如果会，几乎一定要拒绝
- **它会让反思的状态机多一个分支吗？** → 如果会，先看能不能复用现有终态

**保持流程的简洁，就是保持 EVOL 的可信赖。**

> Harness 让流程**稳定地跑完**。
> EVOL 让流程**反思着跑、克制地跑、可解释地跑**。
> 这就是 FLOWS 的全部哲学。

---

## 附：版本与迭代

- **v0.1（本版）** —— 初版流程规范；与 protocol_version "0.1" 对应
- 任何流程级变更 [MUST] 附带：
  - ADR
  - Conformance Test Suite 同步更新
  - 新增 / 调整的 invariants 单独列出
- Prompt 模板可在不破坏输出 schema 的前提下迭代；输出 schema 变更视同协议变更
