# 《EVOL LLM Backend 设计：直连 / 子进程 / 宿主三模式》

> LLM-BACKENDS.md · 这是对 IMPLEMENTATION.md §5.4「llm 抽象」的深化设计。
>
> EVOL 不仅服务"开发者直接拿 API key 调 Claude / GPT"的场景，
> 还要服务**作为 Skill 嵌入 Claude Code / Codex 等 AI 编码助手**的场景——
> 此时 EVOL 自己**没有也不应该有**独立的 LLM 凭据，而是要把"反思请求"交给宿主 agent 去执行。
>
> 本文设计三种 LLM backend 让 EVOL 在以上两类场景里都能跑得自然。

---

## 一、问题背景：两类截然不同的使用场景

### 场景 A：Standalone CLI（独立工具）

```
┌────────────────────────────┐
│   journal-cli, content-cli │
│   ────────────────────────│
│   import evol              │
│   evol = Evol.from_config()│
│                            │
│   reflect → Anthropic API ─┼──▶ api.anthropic.com
└────────────────────────────┘
```

特征：

- 工具自己持有 API key（`ANTHROPIC_API_KEY` env var）
- LLM 调用是同步的、可立即得到回复
- EVOL 完整控制 prompt / 模型 / 温度 / 重试

### 场景 B：作为 Skill 嵌入 Claude Code / Codex（宿主 Agent 内）

```
┌────────────────────────────────────────────────────┐
│   Claude Code (or Codex)                           │
│                                                    │
│   ┌─────────────────────────────┐                  │
│   │ skill: content-ultra        │                  │
│   │ ──────────────────────────  │                  │
│   │ import evol                 │                  │
│   │ evol = Evol.from_config(    │                  │
│   │   backend="host")           │                  │
│   │                             │                  │
│   │ reflect → ???               │                  │
│   └─────────────────────────────┘                  │
│                                                    │
│   ✓ 已有：用户 + 模型对话 + 上下文                 │
│   ✗ Skill 不应该再独立调一次 API                  │
│   ✗ Skill 也没有自己的 API key                    │
└────────────────────────────────────────────────────┘
```

特征：

- **宿主 agent 已经在线、已经持有模型连接**——再调一次 API 是浪费 + 重复扣费
- Skill 没有独立 API key（也不应该要求用户再配）
- 反思的"算力来源"理应是宿主 agent 自己
- 反思可以**异步**——用户和宿主 agent 在做别的事时，把反思请求堆在那里，宿主 agent 顺手处理就行

直接套场景 A 的设计去做场景 B，方向就错了。我们需要让 EVOL 同时支持两条路径。

---

## 二、三种 LLM Backend 模式

| Backend | 谁出算力 | 同步性 | 主要场景 |
|---|---|---|---|
| **direct**（直连 API） | EVOL 自己 | 同步 | 独立 CLI、Web 后端、企业服务 |
| **subprocess**（拉起本地 CLI） | 本地 `claude` / `codex` CLI | 同步（阻塞读子进程输出） | 用户本机有 Claude Code，但 EVOL 是另一个独立工具 |
| **host**（宿主代办） | 当前正在运行的宿主 agent | **异步**（deferred） | EVOL 作为 Skill 嵌入 Claude Code / Codex |

三者**都遵守同一份 LLM Client 抽象**——上层的 Reflector / Advisor 不需要知道底下用的是哪种 backend。

---

## 三、统一抽象：`LLMClient` 与两类响应

### 3.1 抽象基类

```python
# src/evol/llm/base.py
from abc import ABC, abstractmethod
from enum import Enum
from pydantic import BaseModel

class LLMBackendKind(str, Enum):
    DIRECT     = "direct"
    SUBPROCESS = "subprocess"
    HOST       = "host"

class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str

class LLMResponse(BaseModel):
    """同步响应：直接拿到了文本结果。"""
    text: str
    backend: LLMBackendKind
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None

class DeferredLLMResponse(BaseModel):
    """异步响应：请求被记下了，结果以后再说。"""
    request_id: str
    backend: LLMBackendKind
    pending_path: Path
    expected_response_path: Path
    created_at: ISO8601
    expires_at: ISO8601 | None = None
    purpose: Literal["reflection", "anchor_check", "inspiration"]

class LLMClient(ABC):
    @property
    @abstractmethod
    def backend_kind(self) -> LLMBackendKind: ...

    @property
    @abstractmethod
    def is_synchronous(self) -> bool: ...

    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        *,
        purpose: str = "reflection",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float = 120,
    ) -> LLMResponse | DeferredLLMResponse: ...

    def estimate_tokens(self, text: str) -> int:
        """缺省按 字符 / 4 估算。"""
        return max(1, len(text) // 4)
```

### 3.2 上层调用方的双分支处理

```python
# 任何调用 LLM 的地方都按以下模式写：
response = self.llm.chat(messages, purpose="reflection", ...)

if isinstance(response, LLMResponse):
    # Path A: 同步——立即解析与处理
    insights = parse_insights(response.text, ...)
    ...
elif isinstance(response, DeferredLLMResponse):
    # Path B: 异步——记录 deferred 状态，先返回
    persist_deferred_state(response)
    return ReflectionResult(status="pending_host", deferred_id=response.request_id)
```

---

## 四、Backend 1：`direct`（直连 API）

这是 IMPLEMENTATION.md §5.4 已经覆盖的方案，简要回顾：

```python
class AnthropicClient(LLMClient):
    backend_kind = LLMBackendKind.DIRECT
    is_synchronous = True

    def __init__(self, *, api_key: str | None = None, model: str = "claude-sonnet-4-6"):
        from anthropic import Anthropic
        self._client = Anthropic(api_key=api_key)
        self.model = model

    def chat(self, messages, **kw) -> LLMResponse:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=kw.get("max_tokens", 1024),
            temperature=kw.get("temperature", 0.7),
            messages=[{"role": m.role, "content": m.content} for m in messages
                      if m.role != "system"],
            system=next((m.content for m in messages if m.role == "system"), None),
        )
        return LLMResponse(
            text=resp.content[0].text,
            backend=LLMBackendKind.DIRECT,
            model=self.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            finish_reason=resp.stop_reason,
        )

class OpenAIClient(LLMClient): ...    # 类似实现
class MockClient(LLMClient): ...      # 测试用，按 fixture 字典返回响应
```

适用：独立 CLI 工具、企业服务、CI 环境。

---

## 五、Backend 2：`subprocess`（拉起本地 CLI）

当用户本机已经装了 `claude` / `codex` CLI（这些 CLI 自带凭据 + 模型选择），EVOL 可以**把 prompt 通过子进程发给它们，把回应读回来**。这避免了 EVOL 自己持有 API key 的负担。

### 5.1 设计要点

```python
# src/evol/llm/subprocess_client.py
import subprocess
import json
from pathlib import Path

class SubprocessLLMClient(LLMClient):
    backend_kind = LLMBackendKind.SUBPROCESS
    is_synchronous = True

    def __init__(
        self,
        *,
        command: list[str],                   # ["claude", "-p"] 或 ["codex", "exec"]
        timeout: float = 120,
        format: Literal["text", "json"] = "text",
        env: dict[str, str] | None = None,
    ):
        self.command = command
        self.timeout = timeout
        self.format = format
        self.env = env

    def chat(self, messages, **kw) -> LLMResponse:
        # 1. 把 messages 拼成 stdin 文本（保留 system / user 分隔）
        prompt_text = self._serialize_messages(messages)

        # 2. spawn 子进程
        try:
            result = subprocess.run(
                self.command,
                input=prompt_text,
                capture_output=True,
                text=True,
                timeout=kw.get("timeout", self.timeout),
                env=self.env,
            )
        except subprocess.TimeoutExpired as e:
            raise EvolLLMError(f"subprocess timeout: {e}")

        if result.returncode != 0:
            raise EvolLLMError(f"subprocess failed: {result.stderr}")

        # 3. 解析输出
        text = self._extract_text(result.stdout)
        return LLMResponse(text=text, backend=LLMBackendKind.SUBPROCESS, model=str(self.command[0]))

    def _serialize_messages(self, messages: list[Message]) -> str:
        parts = []
        for m in messages:
            if m.role == "system":
                parts.append(f"<<SYSTEM>>\n{m.content}\n<<END_SYSTEM>>\n")
            else:
                parts.append(f"<<{m.role.upper()}>>\n{m.content}\n<<END_{m.role.upper()}>>\n")
        return "\n".join(parts)

    def _extract_text(self, stdout: str) -> str:
        if self.format == "json":
            return json.loads(stdout).get("text", "")
        return stdout.strip()
```

### 5.2 配置示例

```yaml
# evol.config.yaml
llm:
  backend: subprocess
  subprocess:
    command: ["claude", "-p"]              # 或 ["codex", "exec"]
    timeout_seconds: 180
    format: text                            # text | json
```

### 5.3 适用场景

- 本机有 Claude Code / Codex CLI 且用户希望复用其凭据与模型
- EVOL 是一个独立工具（不嵌入在宿主 agent 内），但希望"借力"本地 CLI
- 离线 / 内网环境中，本地 CLI 是 LLM 的唯一访问通道

### 5.4 局限

- 子进程启动有延迟（启动 + cold start 通常 1-3s）
- stdin/stdout 协议不是结构化的——CLI 升级如果改了格式，EVOL 要跟着改
- 不适合高频调用（如 enhance 中的 anchor 评估）

> 因此 `subprocess` 主要服务于 **reflection** 场景；anchor 评估等高频调用应优先 direct 或纯 retrieval。

---

## 六、Backend 3：`host`（宿主 Agent 代办，本设计的核心）

### 6.1 核心思想

> EVOL 作为 Skill 运行在 Claude Code / Codex 等宿主 agent 内时——
> **它不发起 LLM 调用，而是发起"请求宿主代办"的工件**。

宿主 agent 自然就拥有 LLM 能力（它正是用 LLM 在和用户对话），EVOL 只需要：

1. 把反思 prompt 写成一个**人类与 agent 都能读懂**的请求文件
2. 让宿主 agent 知道"这里有一个待处理的反思请求"
3. 等宿主 agent 处理完，把响应写到约定路径
4. EVOL 下次调用时**捡起来 + 消化**

这是一种**文件协议驱动的 deferred RPC**——完全契合 EVOL 的"本地优先 + 可读 + 可审计"哲学。

### 6.2 工作流

```
Time →

   [Skill code (in Claude Code)]
        │
        │ evol.reflector.reflect()
        ▼
   ┌──────────────────────────┐
   │ HostAgentClient.chat()   │
   │ 1. 写 pending request 文件│
   │ 2. 写 response schema    │
   │ 3. 返回 DeferredResponse │
   └──────────┬───────────────┘
              │
              ▼
   ┌──────────────────────────────┐
   │ .evol/pending_reflections/   │
   │   ref_2026-05-03_a3f9.md     │
   │ (人类与 agent 都能读)        │
   └──────────────────────────────┘
              │
              │  Skill 输出给宿主 agent：
              │  "I've prepared a reflection request,
              │   please process it when convenient."
              ▼
   ┌──────────────────────────┐
   │ Host Agent (Claude Code) │
   │ 读 pending request 文件   │
   │ 用自己的模型执行 prompt   │
   │ 把 JSON 结果写到约定路径  │
   └──────────┬───────────────┘
              │
              ▼
   ┌──────────────────────────────┐
   │ .evol/completed_reflections/ │
   │   ref_2026-05-03_a3f9.json   │
   └──────────────────────────────┘
              │
              │  下次调用 evol.reflector.resume_pending() 或
              │  下次 evol.reflector.reflect() 触发时
              ▼
   ┌──────────────────────────┐
   │ Reflector consolidates:  │
   │ parse → anchor filter →  │
   │ memory.consolidate()     │
   └──────────────────────────┘
```

### 6.3 `HostAgentClient` 的核心实现

```python
# src/evol/llm/host_client.py
import json
from pathlib import Path
import yaml

class HostAgentClient(LLMClient):
    backend_kind = LLMBackendKind.HOST
    is_synchronous = False

    def __init__(
        self,
        *,
        evol_root: Path,                       # .evol/ 目录
        host_name: str = "unknown",            # 来自 EVOL_HOST_AGENT 环境变量
        request_ttl_hours: int = 168,          # 7 天后过期
    ):
        self.pending_dir   = evol_root / "pending_requests"
        self.completed_dir = evol_root / "completed_responses"
        self.host_name     = host_name
        self.ttl           = request_ttl_hours

    def chat(self, messages, *, purpose, **kw) -> DeferredLLMResponse:
        request_id   = self._gen_request_id(purpose)
        pending_path = self.pending_dir / f"{request_id}.md"
        completed_path = self.completed_dir / f"{request_id}.json"

        request_doc = self._render_request_doc(
            request_id=request_id,
            purpose=purpose,
            messages=messages,
            response_path=completed_path,
            response_schema=self._schema_for(purpose),
        )

        atomic_write(pending_path, request_doc)

        return DeferredLLMResponse(
            request_id=request_id,
            backend=LLMBackendKind.HOST,
            pending_path=pending_path,
            expected_response_path=completed_path,
            created_at=utc_now_iso(),
            expires_at=add_hours(utc_now_iso(), self.ttl),
            purpose=purpose,
        )

    def poll(self, deferred: DeferredLLMResponse) -> LLMResponse | None:
        if not deferred.expected_response_path.exists():
            return None
        try:
            data = json.loads(deferred.expected_response_path.read_text())
            return LLMResponse(
                text=data["text"] if "text" in data else json.dumps(data),
                backend=LLMBackendKind.HOST,
                model=data.get("model", self.host_name),
            )
        except Exception as e:
            raise EvolParseError(f"completed response invalid: {e}")
```

### 6.4 Pending Request 文件格式

这是 EVOL 与宿主 agent 之间的**协议**，必须**对人和对模型同样清晰**。

```markdown
---
request_id: req_2026-05-03T20-00-00_a3f9
purpose: reflection
created_at: 2026-05-03T20:00:00Z
expires_at: 2026-05-10T20:00:00Z
status: pending
host: claude-code
expected_response_path: .evol/completed_responses/req_2026-05-03T20-00-00_a3f9.json
expected_response_format: json
---

# EVOL Reflection Request

This file is a **deferred LLM request** generated by the EVOL framework
running inside a host agent (you, presumably).

## What you (the host agent) should do

1. Read the **System Prompt** and **User Prompt** sections below.
2. Treat them exactly as if they had been provided to you as a regular
   prompt — produce the requested output.
3. Write the output as a JSON file at the path specified in
   `expected_response_path` above.
4. The JSON must conform to the schema in **Expected Response Schema**.

If the user explicitly asks you to "process EVOL pending reflections" or
runs the `/evol-reflect` skill command, that's your trigger to handle this.
Otherwise feel free to ask the user before doing it (it can take a moment).

---

## System Prompt

You are an Evolution Reflector.
... (system prompt verbatim, exactly as the direct flow would build it) ...

## User Prompt

Existing Memory:
... (memory contents) ...

Recent Experiences:
... (experiences in chronological order) ...

Reflect on these Experiences. Produce Insights only when there is
sufficient evidence.

---

## Expected Response Schema

The response file MUST be a JSON object with this shape:

```json
{
  "insights": [
    {
      "scope": "user_profile|domain_knowledge|self_awareness",
      "key": "<snake_case>",
      "claim": "<short claim>",
      "proposed_change": {"op": "set|merge|strengthen|weaken|retire", "value": ...},
      "confidence": 0.0,
      "evidence_ids": ["exp_..."]
    }
  ],
  "model": "<the model name you used, optional>",
  "completed_at": "<ISO8601 timestamp, optional>"
}
```

Save the JSON to: `.evol/completed_responses/req_2026-05-03T20-00-00_a3f9.json`

---

> Created by EVOL · framework_version=0.1.0 · protocol_version=0.1
```

### 6.5 Completed Response 格式

```json
{
  "insights": [
    {
      "scope": "user_profile",
      "key": "summary_length",
      "claim": "用户偏好 60-80 字总结",
      "proposed_change": {"op": "set", "value": "60-80 字"},
      "confidence": 0.85,
      "evidence_ids": ["exp_001", "exp_007", "exp_023"]
    }
  ],
  "model": "claude-sonnet-4-6",
  "completed_at": "2026-05-03T20:15:00Z"
}
```

### 6.6 配置示例

```yaml
# evol.config.yaml
llm:
  backend: host
  host:
    request_ttl_hours: 168       # 一周后过期
    purpose_whitelist:           # 哪些 purpose 走 host backend
      - reflection
      - anchor_check
      - inspiration
```

### 6.7 自动检测

EVOL [SHOULD] 在启动时探测以下信号自动选择 backend：

| 信号 | 推断 |
|---|---|
| `EVOL_BACKEND` env var 显式设置 | 直接采纳 |
| `EVOL_HOST_AGENT` env var = `claude-code` / `codex` / `cursor` | backend = host |
| `ANTHROPIC_API_KEY` 或 `OPENAI_API_KEY` env var | backend = direct |
| 本机 `which claude` 成功 | backend = subprocess（候选） |
| 否则 | 报错请求显式配置 |

显式配置（`evol.config.yaml.llm.backend`）始终高于自动检测。

---

## 七、流程级影响

### 7.1 Reflection Flow 在 host backend 下的变化

```
   reflector.reflect()
       │
       ▼
   build prompt (与 direct 模式相同)
       │
       ▼
   llm.chat(messages, purpose="reflection")
       │
       ├── direct → LLMResponse（同步）
       │            ↓
       │        parse + filter + consolidate（同步链路）
       │
       └── host → DeferredLLMResponse（异步）
                    ↓
                持久化 deferred state 到 .evol/deferred/
                    ↓
                返回 ReflectionResult(status="pending_host", deferred_id=...)
                    ↓
                ⏸  时间流逝，宿主 agent 处理 pending request
                    ↓
                ⏵  下次 reflector.resume_pending() 或 reflector.reflect() 调用：
                    ↓
                扫描 completed_responses/ → 匹配 deferred → consolidate
```

新增 API：

```python
class Reflector:
    def reflect(self) -> ReflectionResult:
        ...   # 上述主流程

    def resume_pending(self) -> list[ReflectionResult]:
        """扫描 pending → completed 的差集，把已完成的处理掉。"""
        results = []
        for deferred in self._scan_deferred():
            response = self.llm.poll(deferred) if hasattr(self.llm, "poll") else None
            if response is None:
                continue
            results.append(self._consolidate_from_response(deferred, response))
        return results
```

`Evol.__init__` 时 [SHOULD] 自动调一次 `resume_pending()`——这样 deferred 反思在下次启动时无感衔接。

### 7.2 Enhance Flow 在 host backend 下的变化

**完全不受影响**。Enhance 是纯 retrieval-based，不调 LLM——参见 FLOWS §4。

### 7.3 Inspire Flow 在 host backend 下的变化

Inspire 默认要调 LLM，但在 host 模式下又不能阻塞产品任务流（用户是和宿主 agent 在对话，等不起 deferred response）。所以提供三档策略：

```yaml
inspiration:
  host_strategy: defer | template | disabled
```

| 策略 | 行为 |
|---|---|
| `defer`（缺省） | 当次 inspire 返回 null，但同时写一个 inspiration pending request 给宿主；下次产品调用时如果 completed response 就绪，就一并返回 |
| `template` | 不调 LLM，用 Memory 中最高 confidence 的 entry 套模板生成 inspiration 文本 |
| `disabled` | inspire 永远返回 null（最保守） |

### 7.4 Anchor Filter 在 host backend 下的变化

`AnchorFilter` 中的 `text` / `semantic` kind 锚点判定原本要调 LLM。在 host 模式下：

- [MUST] 启用 fail-safe：若不能立即得到 LLM 判定（host backend 异步），**保守判定为冲突**——拒绝该 Insight
- 这意味着 host 模式下 anchor 拒绝率会更高，但**不会有"错误通过"**
- 应对方法：开发者把高频锚点写成 `regex` kind（无需 LLM），保留 `text` / `semantic` 给低频 / 高价值锚点

---

## 八、新增的 `.evol/` 子目录

```
.evol/
├── ... (existing) ...
│
├── pending_requests/                     # ★ 新增
│   ├── req_2026-05-03_a3f9.md            # markdown 请求文件
│   └── req_2026-05-04_b1e2.md
│
├── completed_responses/                  # ★ 新增
│   ├── req_2026-05-03_a3f9.json
│   └── req_2026-05-04_b1e2.json
│
├── deferred/                             # ★ 新增（EVOL 内部状态）
│   └── req_2026-05-03_a3f9.state.json    # DeferredLLMResponse 持久化
│
└── ...
```

每个文件都是**人类可读 + agent 可读 + EVOL 可读**——完美贴合 EVOL 的"全文件协议"哲学。

---

## 九、Skill 与 EVOL 的协作模式（Claude Code 为例）

### 9.1 推荐的 SKILL.md 写法

```markdown
---
name: content-ultra
description: 内容创作智能体，由 EVOL 提供成长能力
---

# content-ultra

This skill helps you write content with growing intelligence
via the EVOL framework.

## Setup

When this skill loads, it initializes EVOL in **host backend** mode.
EVOL will record interactions and accumulate memory locally.

## When EVOL needs reflection

If you (the host agent) see files in `.evol/pending_requests/`, please:

1. Read the request file (it's a markdown file with embedded prompts)
2. Process it as a regular prompt (it's clearly marked)
3. Write the JSON response to `.evol/completed_responses/<request_id>.json`

You can do this proactively, or ask the user "EVOL has a pending
reflection request, would you like me to process it now?".

## Manual triggers

The user can also explicitly run:
  - `/evol-reflect`     — process all pending EVOL reflections now
  - `/evol-status`      — show EVOL's current state

These commands invoke `python -m evol.cli ...` under the hood.
```

### 9.2 调用示例

skill 内部代码：

```python
import os
from evol import Evol

# Skill 启动时
evol = Evol.from_config(
    "evol.config.yaml",
    # backend 自动从 EVOL_HOST_AGENT=claude-code 检测，或显式：
    # backend="host"
)

# 在每次任务时（这个任务是用户和 Claude Code 对话的一部分）
handle = evol.recorder.start_task(input=user_prompt, task_kind="content_writing")

enhanced = evol.advisor.enhance(prompt, task={"task_kind": "content_writing"})
# enhanced 已经注入了用户偏好——但 LLM 调用是 Claude Code 自己做的，
# Skill 只是把 enhanced prompt 返回给 Claude Code

# 任务结束时
evol.recorder.end_task(handle, output=claude_code_response)

# 当反思阈值到达
result = evol.reflector.reflect()
if result.status == "pending_host":
    print("EVOL has prepared a reflection request at:")
    print(f"  {result.pending_path}")
    print("Please process it when convenient.")
```

---

## 十、安全 / 隐私 / 合规考量

| 问题 | 处理 |
|---|---|
| **pending request 文件含 PII** | [MUST] redact 流程同样适用于 pending request；可配 `host.redact_in_pending: true` |
| **宿主 agent 可能不可信** | host backend 适合"用户可信任 + 宿主可信任"场景；不可信宿主下应用 direct backend |
| **completed response 可能被人工编辑** | 视为合法输入——人工审核本身就是 EVOL 设计中的一等公民（QUICKSTART §6 说过 `evol memory edit` 同等存在） |
| **pending 请求 TTL** | 默认 7 天；过期请求自动清理（写入 system Experience 标记 `expired`） |

---

## 十一、对 IMPLEMENTATION.md 的修改点

本设计需要回填到 IMPLEMENTATION.md 的以下位置：

| 位置 | 修改 |
|---|---|
| §3.2 目录结构 | `src/evol/llm/` 新增 `host_client.py` 和 `subprocess_client.py` |
| §5.4 LLM 模块 | 三个 backend 全部纳入；`LLMResponse` / `DeferredLLMResponse` 双类型；`poll()` 接口 |
| §5.7 Reflector | 增加 `resume_pending()` 方法；reflect() 处理 deferred 分支 |
| §5.8 Advisor | 增加 `inspiration.host_strategy` 配置处理 |
| §9 进度表 | 增加新任务（约 8 个） |

新增任务建议（嵌入 Phase 3 / Phase 4）：

| ID | 模块 | 任务 | 工作量(d) |
|---|---|---|---|
| P3-17 | llm | 实现 `subprocess_client.py` | 1 |
| P3-18 | llm | 实现 `host_client.py`（pending request 渲染 + poll） | 1.5 |
| P3-19 | llm | 实现 backend 自动检测（env var + which 探测） | 0.5 |
| P3-20 | reflector | 实现 `Reflector.resume_pending()` | 1 |
| P3-21 | reflector | 实现 deferred state 持久化（`.evol/deferred/`） | 0.5 |
| P3-22 | tests | host backend 端到端测试（mock pending → completed） | 1 |
| P4-18 | advisor | 实现 inspiration `host_strategy` 三档策略 | 0.5 |
| P5-11 | example | 实现 Claude Code Skill 包装的 journal-cli example | 1 |

新增工作量约 **7 天**——总工作量从 63 天 → 70 天，10 周仍可覆盖。

---

## 十二、对 CONTRACT.md / FLOWS.md 的修改点

### 12.1 CONTRACT.md

- §9 `.evol/` 目录契约：增加 `pending_requests/` / `completed_responses/` / `deferred/` 三个新子目录
- §13 增加新错误：deferred request 过期 / completed response schema 不匹配
- §15 协议版本：deferred 协议视为协议的一部分，跨 backend 通用

### 12.2 FLOWS.md

- §3.5 LLM 调用约束：明确"返回类型可能是 LLMResponse 或 DeferredLLMResponse"
- §3.10 反思状态机：增加 `pending_host` / `resumed_host` 两个新终态
- §6 异常恢复：增加 host backend 失败的恢复路径（pending request 写失败、completed response 损坏等）

### 12.3 ARCHITECTURE.md

- §1 分层定位图：在 EVOL 之下不仅可以是 Direct LLM SDK，还可以是宿主 Agent
- §10 非功能性属性：增加"嵌入式部署支持（作为 Skill）"

---

## 十三、写在最后

LLM Backend 的多模式支持，让 EVOL 不再是"独立工具的成长层"——
**它成为一种可以在任何 AI agent 中嵌入的、统一的成长协议**。

> 当 EVOL 嵌入到 Claude Code、Codex、Cursor、Continue、Aider……任何 agent 中，
> 它都用**同一份 `.evol/`**、**同一份协议**、**同一份 Memory**。
>
> 用户的成长是连续的，
> 不会因为切换工具而被打断。

这是 EVOL 从"框架"演化为"标准"的又一步——
**协议优先于实现，标准优先于工具，使用者的成长优先于一切。**

---

## 附：决策待你拍板

是否同意如下两个决定？

1. **把这份设计回填到 IMPLEMENTATION.md / FLOWS.md / CONTRACT.md / ARCHITECTURE.md 对应章节**？
2. **是否同时把新增的 8 个任务（P3-17..22 / P4-18 / P5-11）合并到 IMPLEMENTATION §9 进度表**？

确认后，我会一次性把上述四份文档同步更新到位。
