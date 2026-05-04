# 《EVOL 技术实现文档》

> IMPLEMENTATION.md · 这是从 **设计文档** 到 **真实代码** 的桥梁。
>
> 本文聚焦 **evol-py**（reference 实现，Python 版本），但工程结构与模块切分对其他语言绑定（evol-ts / evol-java）同样适用。
>
> **目标**：让任何熟悉 Python 的工程师，按照本文 + CONTRACT/DATA-MODEL/FLOWS 三份规范，可以独立实现一个合规（CTS-conformant）的 EVOL SDK。
>
> **核心交付**：第九节《开发进度跟踪表》——这是你在 IDE 中边写边勾选的真实进度看板。

---

## 一、文档定位

本文是 EVOL 实施阶段的"操作手册"，覆盖：

- 工程结构（目录树、文件职责、构建配置）
- 模块切分与依赖关系（10 个模块）
- 每个模块的**类签名 + 关键算法 + 边界**（不做完整代码示范，但足够让你照着写）
- 错误处理、日志、测试策略
- **开发进度跟踪表（80+ 任务，5 阶段，10 周）**
- 编码规范、提交规范、里程碑验收标准

**读者**：

- evol-py 的实施者（你 / 你的团队）
- 后续 evol-ts / evol-java 的实施者（结构可类比）
- review / 审计 / onboarding 的同事

---

## 二、技术栈与依赖

### 2.1 语言与运行时

- Python **3.10+**（必须支持 `match`、`X | Y` 类型联合）
- 跨平台：Linux / macOS / Windows 全部一等支持

### 2.2 运行依赖（runtime dependencies）

| 包 | 版本 | 用途 |
|---|---|---|
| `pydantic` | `>=2.5,<3` | 数据模型与配置校验 |
| `pyyaml` | `>=6.0` | YAML 序列化 |
| `click` | `>=8.1` | CLI 框架 |
| `rich` | `>=13` | CLI 漂亮输出 |
| `portalocker` | `>=2.8` | 跨平台 advisory file lock |
| `anthropic` | `>=0.40` | Claude 调用（默认 LLM 后端） |

### 2.3 可选依赖

| 包 | 用途 | 启用方式 |
|---|---|---|
| `openai` | 备用 LLM 后端 | `pip install evol-kit[openai]` |
| `tiktoken` | 精确 token 计数 | `pip install evol-kit[tokenizer]` |
| `croniter` | 定时反思（cron 解析） | `pip install evol-kit[scheduler]` |

### 2.4 开发依赖（dev dependencies）

| 包 | 用途 |
|---|---|
| `pytest`, `pytest-cov`, `pytest-mock` | 单元 / 集成测试 |
| `ruff` | lint + 格式化 |
| `mypy` | 静态类型检查 |
| `pre-commit` | git 钩子 |
| `mkdocs` + `mkdocs-material` | 文档站点（可选） |

### 2.5 打包形态

- 包名：`evol-kit`（pypi）
- import 名：`evol`
- 提供 console_scripts：`evol = evol.cli.main:main`

---

## 三、工程结构总览

### 3.1 顶层目录

```
evol-py/
├── pyproject.toml                # 构建配置 + 依赖
├── README.md                     # 项目首屏
├── LICENSE                       # 许可证（建议 Apache 2.0）
├── CHANGELOG.md                  # 变更日志（沿用 keepachangelog）
├── .gitignore
├── .pre-commit-config.yaml
├── .github/
│   └── workflows/
│       ├── ci.yml                # 跑 ruff + mypy + pytest
│       └── release.yml           # 发布到 pypi
├── src/
│   └── evol/                     # 源码主包
│       └── ...                   # 见 §3.2
├── tests/
│   ├── unit/                     # 单元测试
│   ├── integration/              # 集成测试
│   ├── conformance/              # CTS（与协议同版本）
│   └── fixtures/                 # 测试用 .evol/ 目录样本
├── examples/
│   └── journal-cli/              # QUICKSTART.md 中的 reference example
└── docs/
    ├── index.md
    ├── api/                      # 自动生成的 API 文档
    └── recipes/                  # 进阶用法
```

### 3.2 `src/evol/` 内部结构

```
src/evol/
├── __init__.py                   # 公共 API（from evol import Evol, ...）
├── _version.py                   # 单行：__version__ = "0.1.0"
├── errors.py                     # 异常体系
├── logging.py                    # 结构化日志
│
├── config/                       # 模块 1: 配置
│   ├── __init__.py
│   ├── schema.py                 # pydantic 模型（Config, AnchorConfig, ...）
│   ├── loader.py                 # load_config()
│   └── anchors.py                # Anchor 解析、hash、conflict 判定接口
│
├── core/                         # 模块 2: 核心类型与协议工具
│   ├── __init__.py
│   ├── types.py                  # Experience, Signal, Insight, MemoryEntry, ...
│   ├── ids.py                    # exp_id / ins_id / ref_id 生成
│   ├── time_utils.py             # ISO 8601 / utc_now()
│   └── canonical.py              # 规范化序列化（YAML/JSON）+ checksum
│
├── concurrency/                  # 模块 3: 并发与原子性
│   ├── __init__.py
│   ├── file_lock.py              # FileLock 上下文管理器（基于 portalocker）
│   └── atomic_io.py              # write_then_rename / tar_snapshot
│
├── llm/                          # 模块 4: LLM 抽象（三 backend）
│   ├── __init__.py
│   ├── base.py                   # LLMClient ABC + LLMResponse / DeferredLLMResponse
│   ├── detector.py               # backend 自动检测（env var + which 探测）
│   ├── anthropic_client.py       # direct backend：Anthropic
│   ├── openai_client.py          # direct backend：OpenAI（可选依赖）
│   ├── subprocess_client.py      # subprocess backend：拉起本地 claude / codex CLI
│   ├── host_client.py            # host backend：宿主 Agent 代办（异步 deferred）
│   └── mock_client.py            # 测试用 MockClient
│
├── recorder/                     # 模块 5: 记录器
│   ├── __init__.py
│   ├── recorder.py               # Recorder 主类
│   └── jsonl_store.py            # append-only JSONL 写入
│
├── memory/                       # 模块 6: 记忆库
│   ├── __init__.py
│   ├── store.py                  # MemoryStore（load/save/query）
│   ├── consolidator.py           # 把 Insight 应用为 Memory 变更
│   ├── checksum.py               # 复用 core.canonical 的 checksum
│   ├── manifest.py               # ManifestStore（manifest.yaml R/W）
│   └── snapshot.py               # SnapshotManager（快照、回滚、prune）
│
├── reflector/                    # 模块 7: 反思器
│   ├── __init__.py
│   ├── reflector.py              # Reflector.reflect() 入口
│   ├── trigger.py                # ManualTrigger / ThresholdTrigger / ScheduledTrigger
│   ├── batcher.py                # Experience 取材采样
│   ├── prompt.py                 # 反思 Prompt 构造（FLOWS §3.4 模板）
│   ├── parser.py                 # LLM 输出解析为 InsightCandidate
│   └── filter.py                 # AnchorFilter（后置过滤）
│
├── advisor/                      # 模块 8: 建议者
│   ├── __init__.py
│   ├── advisor.py                # 主门面：enhance() / inspire()
│   ├── retrieval.py              # 关键词 + tag + recency 检索（v0.1 不用向量）
│   ├── budget.py                 # token 预算管理
│   ├── inspire.py                # InspirationFlow（节流 + 概率 + LLM）
│   └── inspiration_history.py    # cooldown / daily_quota 跟踪
│
├── cli/                          # 模块 9: 命令行
│   ├── __init__.py
│   ├── main.py                   # entry point；click group
│   ├── output.py                 # rich 助手
│   └── commands/
│       ├── __init__.py
│       ├── init.py               # `evol init`
│       ├── status.py             # `evol status`
│       ├── reflect.py            # `evol reflect`
│       ├── memory_cmd.py         # `evol memory show / edit`
│       ├── pause_resume.py       # `evol pause / resume`
│       ├── rollback.py           # `evol rollback v3`
│       ├── versions.py           # `evol versions`
│       └── export_import.py      # `evol export / import`
│
└── api/                          # 模块 10: 公共 Facade
    ├── __init__.py
    └── evol.py                   # Evol 类（Evol.from_config）
```

### 3.3 模块依赖关系（DAG）

```
                              api/evol.Evol  ◀── 用户进入点
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        ▼                         ▼                         ▼
   recorder/                  advisor/                 reflector/
        │                         │                         │
        │       ┌─────────────────┼─────────────────────────┤
        ▼       ▼                 ▼                         ▼
              memory/                                    llm/
        │       │                                         │
        ▼       ▼                                         │
   concurrency/, core/, config/  (基础设施)               │
        ▲       ▲                                         │
        └───────┴─────────────────────────────────────────┘
        (所有上层模块都使用 core/ + concurrency/ + config/)
```

依赖原则：

- 上层模块 [MUST NOT] 反向依赖下层
- 同层模块（如 memory ↔ recorder）通过 `core/types.py` 的数据类型沟通，不直接耦合
- `cli/` 是 `api/evol.Evol` 的薄封装，不绕过 facade 直接调底层

---

## 四、核心数据类型设计

> 本节展示 Python 实现细节；其他语言绑定可对照 DATA-MODEL.md 类比。

### 4.1 `core/types.py`

```python
from datetime import datetime
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict

ISO8601 = str  # type alias for clarity


# ─────── Signal ───────

SignalType = Literal[
    "kept", "edited", "discarded", "rated", "dwell", "comment"
]

class Signal(BaseModel):
    type: SignalType | str               # 允许扩展 type，但需带命名空间前缀
    ts: ISO8601
    value: Any | None = None
    source: Literal["explicit", "implicit"] = "explicit"
    weight: float | None = None


# ─────── Experience ───────

ExperienceStatus = Literal["open", "closed", "orphaned", "redacted"]

class Experience(BaseModel):
    model_config = ConfigDict(extra="allow")  # 允许 metadata 扩展

    id: str
    task_kind: str = "default"
    status: ExperienceStatus
    started_at: ISO8601
    ended_at: ISO8601 | None = None
    input: Any
    output: Any | None = None
    signals: list[Signal] = Field(default_factory=list)
    advice_used: list[str] = Field(default_factory=list)
    anchors_applied: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    redacted: bool = False


# ─────── Insight ───────

InsightScope = Literal[
    "user_profile", "domain_knowledge", "self_awareness", "meta"
]
InsightStatus = Literal["pending", "applied", "rejected", "superseded"]
InsightOp = Literal["set", "merge", "strengthen", "weaken", "retire"]

class ProposedChange(BaseModel):
    op: InsightOp
    value: Any | None = None

class Rejection(BaseModel):
    by_anchor: int
    rule: str
    reason: str

class Insight(BaseModel):
    id: str
    reflection_id: str
    created_at: ISO8601
    scope: InsightScope
    key: str
    claim: str
    proposed_change: ProposedChange
    confidence: float
    evidence_ids: list[str]
    status: InsightStatus = "pending"
    rejection: Rejection | None = None
    applied_to: str | None = None
    notes: str | None = None


# ─────── Memory ───────

MemoryKind = Literal[
    "user_profile", "domain_knowledge", "self_awareness"
]
MemoryEntryStatus = Literal["active", "retired", "superseded"]

class MemoryEntry(BaseModel):
    key: str
    value: Any
    confidence: float
    evidence_ids: list[str]
    rationale: str
    created_at: ISO8601
    last_validated_at: ISO8601
    last_revision_id: str
    revision_count: int = 0
    status: MemoryEntryStatus = "active"

class MemoryFile(BaseModel):
    schema_version: int = 1
    memory_kind: MemoryKind
    version: int
    last_updated: ISO8601
    checksum: str | None = None       # filled in only after canonical write
    entries: list[MemoryEntry] = Field(default_factory=list)


# ─────── Anchor (runtime view) ───────

AnchorKind = Literal["text", "regex", "semantic"]

class Anchor(BaseModel):
    index: int
    description: str
    kind: AnchorKind
    rule: str
    rule_hash: str
    activated_at: ISO8601
    deactivated_at: ISO8601 | None = None


# ─────── Manifest ───────

class Manifest(BaseModel):
    schema_version: int = 1
    protocol_version: str = "0.1"
    product: dict[str, str]                       # {name, version, domain?}
    memory: dict[str, Any]                        # {current_version, checksum, last_updated}
    experiences: dict[str, Any]
    last_reflection: dict[str, Any] | None = None
    anchors: list[Anchor] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 4.2 `core/ids.py`

```python
import secrets
from .time_utils import utc_now_iso

def gen_experience_id(prefix: str = "exp") -> str:
    """exp_{ISO8601-no-colons}_{shortrand}"""
    ts = utc_now_iso().replace(":", "").replace(".", "")
    rand = secrets.token_hex(2)
    return f"{prefix}_{ts}_{rand}"

def gen_insight_id(reflection_id: str, seq: int) -> str:
    """ins_{reflection_date}_{seq:03d}"""
    date = reflection_id.removeprefix("ref_").split("_")[0]
    return f"ins_{date}_{seq:03d}"

def gen_reflection_id() -> str:
    return f"ref_{utc_now_iso().split('T')[0]}_{secrets.token_hex(2)}"
```

### 4.3 `core/canonical.py`

```python
import hashlib
import json
from typing import Any
import yaml

# 强制字段顺序（与 DATA-MODEL §11 规范一致）

_FILE_FIELD_ORDER = [
    "schema_version", "memory_kind", "version", "last_updated",
    "checksum", "entries"
]
_ENTRY_FIELD_ORDER = [
    "key", "value", "confidence", "evidence_ids", "rationale",
    "created_at", "last_validated_at", "last_revision_id",
    "revision_count", "status"
]

def canonical_yaml_dump(memory_file_dict: dict) -> str:
    """规范化 YAML 序列化：固定字段顺序、UTF-8、LF、2 空格缩进、浮点 2 位小数。"""
    ordered = _reorder(memory_file_dict, _FILE_FIELD_ORDER)
    if "entries" in ordered:
        ordered["entries"] = [_reorder(e, _ENTRY_FIELD_ORDER) for e in ordered["entries"]]
    # 浮点固定 2 位小数
    ordered = _normalize_floats(ordered)
    return yaml.safe_dump(
        ordered,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=80,
        indent=2,
    )

def canonical_jsonl_dump(experience_dict: dict) -> str:
    """单行 JSON：UTF-8、无空格缩进、字段顺序固定。"""
    ordered = _reorder(experience_dict, [
        "id", "task_kind", "status", "started_at", "ended_at",
        "input", "output", "signals", "advice_used",
        "anchors_applied", "metadata", "redacted",
    ])
    return json.dumps(ordered, ensure_ascii=False, separators=(",", ":")) + "\n"

def compute_memory_checksum(memory_files: dict[str, dict]) -> str:
    """memory/*.yaml → 规范序列化 → 联合 → sha256."""
    kinds = ["user_profile", "domain_knowledge", "self_awareness"]
    parts = [canonical_yaml_dump(memory_files[k]) for k in kinds]
    blob = "\n---\n".join(parts).encode("utf-8")
    return f"sha256:{hashlib.sha256(blob).hexdigest()}"

def _reorder(d: dict, order: list[str]) -> dict: ...
def _normalize_floats(obj: Any, ndigits: int = 2) -> Any: ...
```

### 4.4 `core/time_utils.py`

```python
from datetime import datetime, timezone

def utc_now_iso() -> str:
    """ISO 8601 with milliseconds, Z suffix."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

def parse_iso(s: str) -> datetime: ...
def is_after(a: str, b: str) -> bool: ...
```

---

## 五、模块详细设计

### 5.1 模块 1：`config/`

**职责**：加载 / 校验 `evol.config.yaml`；解析 anchors。

**关键类**：

```python
# config/schema.py
class ProductConfig(BaseModel):
    name: str        # 限制 [a-zA-Z0-9_-], len <= 64
    version: str
    domain: str | None = None

class AnchorConfig(BaseModel):
    description: str
    kind: AnchorKind = "text"
    rule: str

class GrowthConfig(BaseModel):
    knowledge_evolution: bool = True
    inspirational_feedback: bool = True

class ReflectionConfig(BaseModel):
    trigger: Literal["manual", "threshold", "scheduled"] = "threshold"
    threshold: int = 20
    schedule: str | None = None
    max_experiences_per_run: int = 100

class InspirationConfig(BaseModel):
    frequency: Literal["never", "low", "medium", "high"] = "low"
    cooldown_hours: int = 24
    max_per_day: int = 3
    host_strategy: Literal["defer", "template", "disabled"] = "defer"   # ★ host backend 行为

class MemoryRetentionExperiences(BaseModel):
    max_count: int = 10000
    max_days: int = 365

class MemoryRetentionSnapshots(BaseModel):
    keep: int = 20

class MemoryConfig(BaseModel):
    retention: dict = Field(default_factory=lambda: {
        "experiences": MemoryRetentionExperiences().model_dump(),
        "snapshots":   MemoryRetentionSnapshots().model_dump(),
    })

class LLMDirectConfig(BaseModel):
    provider: Literal["anthropic", "openai"] = "anthropic"
    model: str = "claude-sonnet-4-6"
    api_key_env: str = "ANTHROPIC_API_KEY"

class LLMSubprocessConfig(BaseModel):
    command: list[str]                                # ["claude", "-p"]
    timeout_seconds: int = 180
    format: Literal["text", "json"] = "text"

class LLMHostConfig(BaseModel):
    request_ttl_hours: int = 168                      # 7 天
    purpose_whitelist: list[str] = ["reflection", "anchor_check", "inspiration"]

class LLMConfig(BaseModel):
    backend: Literal["direct", "subprocess", "host", "auto"] = "auto"
    direct:     LLMDirectConfig | None = None
    subprocess: LLMSubprocessConfig | None = None
    host:       LLMHostConfig | None = None

class Config(BaseModel):
    schema_version: int = 1
    product: ProductConfig
    anchors: list[AnchorConfig] = []
    growth: GrowthConfig = GrowthConfig()
    reflection: ReflectionConfig = ReflectionConfig()
    inspiration: InspirationConfig = InspirationConfig()
    memory: MemoryConfig = MemoryConfig()
    llm: LLMConfig = LLMConfig()                      # ★ 新增
    extensions: list[dict] = []
```

**关键函数**：

```python
# config/loader.py
def load_config(path: str | Path) -> Config:
    """读取 + 校验 + 返回；失败 fail-fast 抛 EvolConfigError。"""

# config/anchors.py
def parse_anchors(config: Config) -> list[Anchor]:
    """AnchorConfig → 运行时 Anchor（含 rule_hash, activated_at）。"""

def detect_anchor_drift(current: list[Anchor], stored: list[Anchor]) -> bool:
    """比对 hash；如果有变更，调用方应触发 snapshot。"""
```

### 5.2 模块 2：`core/`

见第四节。要点：

- `types.py` 全部用 pydantic v2，启用 `extra="allow"` 兼容协议 minor 升级
- `canonical.py` 是跨语言 checksum 一致性的关键——任何修改 [MUST] 同步更新 CTS
- `ids.py` 必须保证全局唯一（含进程并发）

### 5.3 模块 3：`concurrency/`

```python
# concurrency/file_lock.py
from contextlib import contextmanager
import portalocker

@contextmanager
def file_lock(path: str | Path, timeout: float = 5.0, exclusive: bool = True):
    """advisory file lock；非阻塞超时设计。"""

# concurrency/atomic_io.py
def atomic_write(path: Path, content: str | bytes) -> None:
    """write → fsync → rename。"""

def make_snapshot_tar(src_dir: Path, dst_path: Path) -> None:
    """打包 memory/ 为 tar 归档。"""

def extract_snapshot_tar(src_path: Path, dst_dir: Path) -> None:
    """rollback 时使用。"""
```

### 5.4 模块 4：`llm/`（三 Backend：direct / subprocess / host）

> 详细设计见独立文档《LLM-BACKENDS.md》。本节给出实施级签名要点。

EVOL 同时支持三种 LLM 接入方式，由统一抽象 `LLMClient` 收敛：

| Backend | 谁出算力 | 同步性 | 主要场景 |
|---|---|---|---|
| **direct** | EVOL 自己持 API key | 同步 | 独立 CLI、Web 后端、企业服务 |
| **subprocess** | 本机 `claude` / `codex` CLI | 同步 | 复用本地 CLI 凭据 |
| **host** | 当前正在运行的宿主 Agent | **异步** | EVOL 作为 Skill 嵌入 Claude Code / Codex |

```python
# llm/base.py
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from pydantic import BaseModel
from typing import Literal

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
    """异步响应：请求被记下了，结果以后再说（host backend 用）。"""
    request_id: str
    backend: LLMBackendKind            # always HOST
    pending_path: Path
    expected_response_path: Path
    created_at: str                    # ISO8601
    expires_at: str | None = None
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

    def poll(self, deferred: DeferredLLMResponse) -> LLMResponse | None:
        """仅 host backend 实现；同步 backend 返回 None。"""
        return None

    def estimate_tokens(self, text: str) -> int:
        """缺省按字符 / 4 估算；有 tiktoken 则精确计算。"""
        return max(1, len(text) // 4)
```

#### 5.4.1 Direct Backend

```python
class AnthropicClient(LLMClient):
    backend_kind = LLMBackendKind.DIRECT
    is_synchronous = True
    # __init__(api_key, model="claude-sonnet-4-6")
    # chat() 调用 Anthropic SDK，返回 LLMResponse

class OpenAIClient(LLMClient):  # 可选依赖
    backend_kind = LLMBackendKind.DIRECT
    is_synchronous = True

class MockClient(LLMClient):    # 仅测试
    backend_kind = LLMBackendKind.DIRECT
    is_synchronous = True
```

#### 5.4.2 Subprocess Backend

```python
class SubprocessLLMClient(LLMClient):
    backend_kind = LLMBackendKind.SUBPROCESS
    is_synchronous = True

    def __init__(self, *, command: list[str], timeout: float = 120,
                 format: Literal["text","json"] = "text",
                 env: dict | None = None):
        ...

    def chat(self, messages, **kw) -> LLMResponse:
        prompt_text = self._serialize_messages(messages)
        result = subprocess.run(self.command, input=prompt_text,
                                capture_output=True, text=True,
                                timeout=kw.get("timeout", self.timeout),
                                env=self.env)
        if result.returncode != 0:
            raise EvolLLMError(...)
        return LLMResponse(text=self._extract_text(result.stdout),
                           backend=LLMBackendKind.SUBPROCESS,
                           model=str(self.command[0]))
```

#### 5.4.3 Host Backend（核心）

```python
class HostAgentClient(LLMClient):
    backend_kind = LLMBackendKind.HOST
    is_synchronous = False

    def __init__(self, *, evol_root: Path, host_name: str = "unknown",
                 request_ttl_hours: int = 168):
        self.pending_dir   = evol_root / "pending_requests"
        self.completed_dir = evol_root / "completed_responses"
        self.host_name     = host_name
        self.ttl           = request_ttl_hours

    def chat(self, messages, *, purpose, **kw) -> DeferredLLMResponse:
        request_id   = self._gen_request_id(purpose)
        pending_path = self.pending_dir / f"{request_id}.md"
        response_path = self.completed_dir / f"{request_id}.json"
        # 渲染 markdown 请求文件（人和 agent 都能读）
        atomic_write(pending_path, self._render_request_doc(...))
        return DeferredLLMResponse(request_id=request_id,
                                   backend=LLMBackendKind.HOST,
                                   pending_path=pending_path,
                                   expected_response_path=response_path,
                                   created_at=utc_now_iso(),
                                   expires_at=add_hours(utc_now_iso(), self.ttl),
                                   purpose=purpose)

    def poll(self, deferred: DeferredLLMResponse) -> LLMResponse | None:
        if not deferred.expected_response_path.exists():
            return None
        data = json.loads(deferred.expected_response_path.read_text())
        return LLMResponse(text=data.get("text", json.dumps(data)),
                           backend=LLMBackendKind.HOST,
                           model=data.get("model", self.host_name))
```

Pending request 文件的 markdown 模板见 LLM-BACKENDS.md §6.4——
**它必须对人和对模型同样清晰**——这是 host backend 的协议核心。

#### 5.4.4 Backend 自动检测

```python
# llm/detector.py
def detect_backend(config: Config) -> LLMClient:
    # 1. 显式配置最高优先
    if config.llm.backend:
        return _build_explicit(config)
    # 2. EVOL_HOST_AGENT env var
    if os.environ.get("EVOL_HOST_AGENT") in {"claude-code", "codex", "cursor"}:
        return HostAgentClient(...)
    # 3. API key env var
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicClient()
    if os.environ.get("OPENAI_API_KEY"):
        return OpenAIClient()
    # 4. 本机 CLI 探测
    if shutil.which("claude"):
        return SubprocessLLMClient(command=["claude", "-p"])
    # 5. 全部失败
    raise EvolConfigError("无法确定 LLM backend，请显式配置 llm.backend")
```

#### 5.4.5 上层调用模式（关键）

任何调用 `llm.chat()` 的地方都要按双类型分支：

```python
response = self.llm.chat(messages, purpose="reflection", ...)

if isinstance(response, LLMResponse):
    # 同步路径
    insights = parse_insights(response.text, ...)
    ...

elif isinstance(response, DeferredLLMResponse):
    # 异步路径：持久化 deferred state，早返回
    persist_deferred_state(response, evol_root / "deferred")
    return ReflectionResult(status="pending_host", deferred_id=response.request_id)
```

### 5.5 模块 5：`recorder/`

```python
# recorder/recorder.py
class TaskHandle(BaseModel):
    experience_id: str

class Recorder:
    def __init__(self, store: JsonlStore, anchors: list[Anchor]):
        ...

    def start_task(self, input: Any, *, task_kind: str = "default",
                   ctx: dict | None = None) -> TaskHandle:
        """写入 status=open 的 Experience 行；同步、< 50ms。"""

    def end_task(self, handle: TaskHandle, output: Any,
                 *, advice_used: list[str] = None,
                 anchors_applied: list[str] = None) -> str:
        """status=closed; 返回 experience_id。"""

    def feedback(self, experience_id: str, signal: Signal) -> None:
        """append 一个 signal 到对应 Experience。
        实现要点：JSONL 不允许原地修改——做法是另开
        feedback_overlay.jsonl 记录 (exp_id, signal)；
        读取 Experience 时合并。"""

# recorder/jsonl_store.py
class JsonlStore:
    def __init__(self, path: Path):
        self.path = path

    def append(self, experience_dict: dict) -> None:
        """portalocker.exclusive append; canonical_jsonl_dump."""

    def iter_all(self) -> Iterator[dict]:
        """流式读取；不加载全部到内存。"""

    def find_by_id(self, exp_id: str) -> dict | None: ...
```

**关键设计点：feedback 不可原地修改 JSONL**

> JSONL 是 append-only。若 feedback 要"修改"已有 Experience，
> 实现 [MUST] 通过 overlay 文件 `experiences.feedback.jsonl` 记录
> `{exp_id, signal}` 配对。读取时合并 overlay。
> 反思流取材时，从合并视图中获取最终 Experience 状态。

### 5.6 模块 6：`memory/`

```python
# memory/store.py
class MemoryStore:
    def __init__(self, root: Path):
        self.root = root  # .evol/memory/

    def load(self, kind: MemoryKind) -> MemoryFile: ...
    def query(self, kind: MemoryKind, key: str) -> MemoryEntry | None: ...
    def save(self, kind: MemoryKind, mem: MemoryFile) -> None:
        """canonical_yaml_dump + atomic_write."""

# memory/consolidator.py
class Consolidator:
    def apply(self, insights: list[Insight], stores: dict[MemoryKind, MemoryFile]
              ) -> dict[MemoryKind, MemoryFile]:
        """按 FLOWS §3.7 逻辑应用 op；返回新 MemoryFile。"""

# memory/snapshot.py
class SnapshotManager:
    def __init__(self, root: Path):
        self.versions_dir = root / "versions"

    def create(self, memory_dir: Path, version: int) -> Path:
        """memory-v{N}.snapshot ← tar(memory/)."""

    def rollback_to(self, version: int, memory_dir: Path) -> None:
        """extract snapshot → memory_dir."""

    def list_versions(self) -> list[int]: ...
    def prune(self, keep: int) -> list[int]:
        """删除超出 keep 的旧 snapshot；返回删除列表。"""

# memory/manifest.py
class ManifestStore:
    def __init__(self, path: Path):
        self.path = path

    def read(self) -> Manifest: ...
    def write(self, manifest: Manifest) -> None:
        """atomic_write."""

    def update_memory_pointer(self, version: int, checksum: str,
                              last_updated: str) -> None: ...
```

### 5.7 模块 7：`reflector/`

```python
# reflector/reflector.py
class ReflectionResult(BaseModel):
    reflection_id: str
    status: Literal["completed", "skipped", "preflight_failed",
                    "no_op", "llm_failed", "parse_failed",
                    "consolidate_failed", "timeout",
                    "pending_host", "resumed_host"]      # ★ host backend 增加 2 种终态
    insights_total: int = 0
    insights_applied: int = 0
    insights_rejected: int = 0
    memory_version_before: int | None = None
    memory_version_after: int | None = None
    deferred_id: str | None = None                       # ★ host backend：pending request id
    notes: str | None = None

class Reflector:
    def __init__(
        self,
        config: Config,
        llm: LLMClient,
        recorder: Recorder,
        memory: MemoryStore,
        manifest: ManifestStore,
        snapshot: SnapshotManager,
        anchors: list[Anchor],
        root: Path,                           # .evol/
    ):
        ...

    def reflect(self, experience_range: tuple[str, str] | None = None
                ) -> ReflectionResult:
        """完整反思流；按 FLOWS §3 实现。
        host backend 下：调用 llm.chat() 得到 DeferredLLMResponse 后，
        持久化 deferred state 到 .evol/deferred/，立即返回 status='pending_host'。"""

    def resume_pending(self) -> list[ReflectionResult]:
        """扫描 .evol/deferred/ 中所有 pending 状态的 deferred 请求；
        对每一个调用 llm.poll()，若 completed response 已就绪，
        则解析 → AnchorFilter → consolidate → 返回 status='resumed_host'。
        Evol.__init__ 时自动调一次，保证启动即衔接。"""

# reflector/trigger.py
class TriggerBase(ABC):
    def should_fire(self, manifest: Manifest, exp_count: int) -> bool: ...

class ManualTrigger(TriggerBase): ...
class ThresholdTrigger(TriggerBase):
    def __init__(self, threshold: int): ...
class ScheduledTrigger(TriggerBase):
    def __init__(self, schedule: str): ...   # cron via croniter

# reflector/batcher.py
class Batcher:
    def select(self, all_experiences: list[Experience], *,
               since: str | None, max_n: int
               ) -> list[Experience]:
        """按 FLOWS §3.3 优先级（high signal first）采样。"""

# reflector/prompt.py
class PromptBuilder:
    def build(self, memory: dict[MemoryKind, MemoryFile],
              experiences: list[Experience], anchors: list[Anchor]
              ) -> list[Message]: ...

# reflector/parser.py
def parse_insights(llm_text: str, reflection_id: str
                   ) -> list[Insight]:
    """解析 JSON 数组 → Insight 列表；失败抛 EvolParseError。"""

# reflector/filter.py
class AnchorFilter:
    def __init__(self, anchors: list[Anchor], llm: LLMClient):
        ...
    def filter(self, insights: list[Insight]
               ) -> tuple[list[Insight], list[Insight]]:
        """returns (approved, rejected)."""
    def _conflict(self, insight: Insight, anchor: Anchor) -> bool:
        """fail-safe: 任何评估失败一律返回 True。"""
```

### 5.8 模块 8：`advisor/`

```python
# advisor/advisor.py
class Advisor:
    def __init__(
        self,
        config: Config,
        memory: MemoryStore,
        recorder: Recorder,
        llm: LLMClient,
        anchors: list[Anchor],
        history: InspirationHistory,
    ):
        ...

    def enhance(self, prompt: str, *, task: dict | None = None) -> str:
        """FLOWS §4 实现。永不抛异常。"""

    def inspire(self, *, task: dict | None = None
                ) -> Inspiration | None:
        """FLOWS §5 实现。永不抛异常。
        host backend 下按配置 inspiration.host_strategy 切换：
          - "defer"（缺省）：写 inspiration pending request，本次返回 None；
                              下次 inspire() 调用时若 completed response 就绪则返回
          - "template"：不调 LLM，用 Memory 最高 confidence 条目套模板生成
          - "disabled"：永远返回 None（最保守）"""

# advisor/retrieval.py
class Retrieval:
    def relevant_entries(
        self,
        memory: dict[MemoryKind, MemoryFile],
        keys: list[str],
        ctx: dict,
        min_confidence: float = 0.3,
    ) -> list[tuple[float, MemoryEntry, MemoryKind]]:
        """relevance_score → 排序。"""

    def derive_keys(self, prompt: str, ctx: dict) -> list[str]:
        """从 task_kind / 关键词 / tags 派生检索 key。"""

# advisor/budget.py
class BudgetManager:
    def __init__(self, llm: LLMClient, *, max_advice_tokens: int = 600):
        ...
    def fit(self, prompt: str, candidates: list, ratio: float = 0.30
            ) -> list:
        """按 score 降序逐条放入预算池。"""

# advisor/inspire.py（在 inspire 调用流中使用）
def build_inspiration_prompt(...) -> list[Message]: ...
def parse_inspiration(text: str) -> Inspiration | None: ...

# advisor/inspiration_history.py
class InspirationHistory:
    def __init__(self, path: Path):
        self.path = path                # .evol/insights/inspiration_history.jsonl

    def last_emitted_at(self) -> datetime | None: ...
    def count_today(self) -> int: ...
    def record(self, inspiration: Inspiration) -> None: ...
```

### 5.9 模块 9：`cli/`

每个 CLI 命令实现都很薄——把 click 参数转译成 facade 调用。

```python
# cli/main.py
import click
from evol.api.evol import Evol

@click.group()
@click.option("--root", default=".", help="项目根目录（包含 .evol/）")
@click.pass_context
def main(ctx, root):
    ctx.ensure_object(dict)
    ctx.obj["root"] = root

# 每个子命令都注册到 main：
from .commands import init, status, reflect_cmd, memory_cmd, ...
main.add_command(init.cmd)
main.add_command(status.cmd)
...

if __name__ == "__main__":
    main()
```

**所有命令清单**（见 QUICKSTART §8）：

| 命令 | 功能 |
|---|---|
| `evol init` | 创建 .evol/ 骨架 |
| `evol status` | 显示当前 manifest 状态 + 健康度 |
| `evol reflect` | 手动触发反思 |
| `evol memory show [--kind]` | 展示 memory |
| `evol memory edit <kind>` | 用 $EDITOR 打开 yaml |
| `evol pause` / `resume` | 切换运行态 |
| `evol versions` | 列出所有 snapshot 版本 |
| `evol rollback v3` | 回滚到指定版本 |
| `evol diff v3 v5` | 对比两版 memory |
| `evol export <path>` / `import <path>` | 全量 export/import |

### 5.10 模块 10：`api/evol.py`（用户进入点）

```python
# api/evol.py
class Evol:
    def __init__(self, *, config: Config, root: Path,
                 llm: LLMClient | None = None):
        self.config = config
        self.root = root
        self.llm = llm or AnthropicClient()
        # Wire up modules:
        self.manifest = ManifestStore(root / ".evol" / "manifest.yaml")
        self.memory = MemoryStore(root / ".evol" / "memory")
        self.snapshot = SnapshotManager(root / ".evol")
        self.anchors = parse_anchors(config)
        self._validate_state()
        self.recorder = Recorder(...)
        self.advisor = Advisor(...)
        self.reflector = Reflector(...)
        self._paused: bool = self._read_pause_state()

    @classmethod
    def from_config(cls, path: str | Path = "evol.config.yaml",
                    root: Path | None = None) -> "Evol":
        config = load_config(path)
        return cls(config=config, root=Path(root or "."))

    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def is_paused(self) -> bool: ...

    # The 5 product-facing APIs are accessed via:
    #   self.recorder.start_task / end_task / feedback
    #   self.advisor.enhance / inspire
```

**用户使用方式**（与 QUICKSTART 一致）：

```python
from evol import Evol
evol = Evol.from_config("evol.config.yaml")

handle = evol.recorder.start_task(input=...)
prompt = evol.advisor.enhance(prompt, task={"task_kind": "summarize"})
# ... call LLM ...
evol.recorder.end_task(handle, output=...)
inspiration = evol.advisor.inspire()
```

---

## 六、错误处理体系

### 6.1 异常基类与子类（`errors.py`）

```python
class EvolError(Exception):
    """所有 EVOL 异常的基类。"""

class EvolConfigError(EvolError):
    """配置加载/校验失败。"""

class EvolProtocolMismatch(EvolError):
    """manifest.yaml 协议版本不兼容。"""

class EvolChecksumError(EvolError):
    """memory checksum 失配。"""

class EvolLockError(EvolError):
    """锁竞争超时 / 残留锁问题。"""

class EvolLLMError(EvolError):
    """LLM 调用失败的统一封装。"""

class EvolParseError(EvolError):
    """LLM 输出无法解析。"""

class EvolStorageError(EvolError):
    """文件 I/O 错误。"""
```

### 6.2 错误处理总原则

| 模块 | 错误处理 |
|---|---|
| `recorder.start/end/feedback` | [MUST] 不抛错；失败仅 log warning |
| `advisor.enhance/inspire` | [MUST] 不抛错；降级返回原 prompt 或 None |
| `reflector.reflect` | [MUST] 抛错（reflect 是显式调用） |
| `cli` | [MUST] 抛错时给可执行的修复建议 |
| `api.Evol.__init__` | [MUST] fail-fast；配置错误等 |

---

## 七、日志策略

### 7.1 日志库

使用 Python 标准 `logging`，但所有日志通过 `evol.logging.get_logger(name)` 获取，统一带前缀 `evol.<module>`。

### 7.2 结构化输出

[MUST] 所有日志通过 `extra={...}` 附加结构化字段，使用 JSON formatter（默认）：

```json
{"ts": "...", "level": "INFO", "logger": "evol.reflector",
 "msg": "reflection completed",
 "reflection_id": "ref_2026-05-03_a3f9",
 "insights_applied": 4, "insights_rejected": 1}
```

### 7.3 日志等级约定

| 等级 | 用途 |
|---|---|
| DEBUG | 内部决策细节（生产环境关闭） |
| INFO | 正常流程节点（任务开始 / 反思完成 / Memory 版本变更） |
| WARNING | 降级行为（LLM 失败、checksum 失配但 freeze） |
| ERROR | 流程中断（如 consolidate 失败） |
| CRITICAL | 不可恢复（永远不应发生，写入即应该报警） |

### 7.4 不允许做的事

- [MUST NOT] 把 PII（input/output/comment）写入日志
- [MUST NOT] 用 `print` 替代 logging
- [MUST NOT] 在日志中输出 stack trace 到 stdout（应通过 logging.exception）

---

## 八、测试策略

### 8.1 测试金字塔

```
              ┌─────────────────────────────┐
              │      Conformance Tests      │  ← CTS, 跨 SDK 一致性
              ├─────────────────────────────┤
              │     Integration Tests       │  ← 端到端流程
              ├─────────────────────────────┤
              │       Unit Tests            │  ← 每模块独立
              └─────────────────────────────┘
```

### 8.2 单元测试

每个模块对应 `tests/unit/test_<module>.py`：

- `core/types.py` → schema validation, edge cases
- `core/canonical.py` → checksum 一致性、字段顺序
- `concurrency/file_lock.py` → 锁竞争、死锁恢复
- `recorder/recorder.py` → start/end 配对、feedback overlay
- `memory/consolidator.py` → 5 种 op 行为
- `reflector/parser.py` → JSON 解析鲁棒性
- `advisor/retrieval.py` → relevance_score 边界
- `advisor/budget.py` → token 预算约束

### 8.3 集成测试（`tests/integration/`）

| 测试 | 验证 |
|---|---|
| `test_e2e_journal_cli.py` | 模拟 30 天用 journal-cli 的演化 |
| `test_reflection_cycle.py` | start_task × N → reflect → memory v+1 |
| `test_rollback.py` | 反思后回滚 → memory 恢复 |
| `test_anchor_rejection.py` | 触发 anchor 冲突 → 拒绝并写 insights |
| `test_concurrent_writers.py` | 多进程同时 append experiences.jsonl |

### 8.4 Conformance Test Suite（`tests/conformance/`）

CTS 是协议级一致性验证——其他语言 SDK 也要跑。Python 实现既是 reference 也是 CTS 的载体：

```
tests/conformance/
├── schema/                  # 各文件 schema 校验
├── behavior/                # 5 个 API + 5 个 admin 操作语义
├── concurrency/             # 并发安全性
├── atomicity/               # 模拟崩溃恢复
├── anchor/                  # 锚点守护
└── cross_sdk/               # 用 SDK A 写、SDK B 读（v0.2+ 引入）
```

### 8.5 测试覆盖率目标

- 单元：≥ 85%
- 集成：覆盖所有"流程主干"
- CTS：100%（任何 protocol 行为都有对应测试）

---

## 九、开发进度跟踪表

> 这是本文档的核心交付。
>
> 每完成一个任务，在 **状态** 列把 `☐` 改为 `☑`，并在 **完成日期** 填写 ISO 日期。
> 阻塞的任务把状态改为 `🚫` 并在备注里写阻塞原因。
> 使用 markdown checkbox 即可在 IDE 里一目了然。

### 9.1 状态约定

| 符号 | 含义 |
|---|---|
| `☐` | 未开始 |
| `🟡` | 进行中 |
| `☑` | 已完成 |
| `✅` | 已完成 + 已通过测试 |
| `🚫` | 阻塞 |

### 9.2 阶段一：地基（Phase 1 · Week 1–2）

**目标**：项目骨架 + 核心数据类型 + 基础设施层。

| ID | 模块 | 任务 | 优先级 | 状态 | 工作量(天) | 完成日期 | 备注 |
|---|---|---|---|---|---|---|---|
| P1-01 | repo | 初始化 git 仓库、`pyproject.toml`、`README.md`、`LICENSE` | P0 | ✅ | 0.5 | 2026-05-03 | hatchling 后端，src/ 布局 |
| P1-02 | repo | 配置 ruff + mypy + pre-commit | P0 | ✅ | 0.5 | 2026-05-03 | 配置写入 pyproject + .pre-commit-config |
| P1-03 | repo | GitHub Actions CI（lint + test） | P1 | ✅ | 0.5 | 2026-05-03 | 3 OS × 3 Python 版本矩阵 |
| P1-04 | core | 实现 `core/types.py`（所有 pydantic 模型） | P0 | ✅ | 1.5 | 2026-05-03 | 含 DeferredState |
| P1-05 | core | 实现 `core/ids.py` | P0 | ✅ | 0.5 | 2026-05-03 | 含 deferred request id |
| P1-06 | core | 实现 `core/time_utils.py` | P0 | ✅ | 0.3 | 2026-05-03 | ISO8601 + add_hours |
| P1-07 | core | 实现 `core/canonical.py` 的 yaml/jsonl 序列化 | P0 | ✅ | 1.5 | 2026-05-03 | 100% 覆盖 |
| P1-08 | core | 实现 `compute_memory_checksum` + 单测 | P0 | ✅ | 0.5 | 2026-05-03 | 6 个 checksum 测试通过 |
| P1-09 | config | 实现 `config/schema.py` + `loader.py` | P0 | ✅ | 1 | 2026-05-03 | 含 LLMConfig 三 backend |
| P1-10 | config | 实现 `config/anchors.py`（rule_hash + drift detect） | P0 | ✅ | 1 | 2026-05-03 | |
| P1-11 | concur | 实现 `concurrency/file_lock.py` | P0 | ✅ | 0.5 | 2026-05-03 | portalocker + timeout |
| P1-12 | concur | 实现 `concurrency/atomic_io.py`（write-then-rename + tar） | P0 | ✅ | 0.5 | 2026-05-03 | 含 tar 安全过滤 |
| P1-13 | errors | 实现 `errors.py` 异常体系 | P0 | ✅ | 0.3 | 2026-05-03 | 8 个子类 |
| P1-14 | logging | 实现 `logging.py` 结构化日志 | P1 | ✅ | 0.5 | 2026-05-03 | JsonFormatter + NullHandler 默认 |
| P1-15 | tests | 写 `tests/unit/test_canonical.py`（最重要） | P0 | ✅ | 1 | 2026-05-03 | 16 个测试 |
| P1-16 | tests | 写 `tests/unit/test_config.py` + `test_concurrency.py` | P0 | ✅ | 1 | 2026-05-03 | 含 test_types / test_ids / test_time_utils |

阶段总工作量：**~12 天** · 阶段验收：**✅ 全部通过**——79 个测试通过、整体覆盖 87%、核心模块 88-100%。

### 9.3 阶段二：Recorder + Memory + 存储层（Phase 2 · Week 3–4）

**目标**：能够 start/end Experience，能够读写 Memory，CLI 雏形可用。

| ID | 模块 | 任务 | 优先级 | 状态 | 工作量(天) | 完成日期 | 备注 |
|---|---|---|---|---|---|---|---|
| P2-01 | recorder | 实现 `recorder/jsonl_store.py`（append + read + lock） | P0 | ✅ | 1 | 2026-05-03 | portalocker + 容错 read |
| P2-02 | recorder | 实现 `recorder/recorder.py`（start/end） | P0 | ✅ | 1 | 2026-05-03 | TaskHandle + 永不抛错 |
| P2-03 | recorder | 实现 `feedback overlay`（experiences.feedback.jsonl） | P0 | ✅ | 1 | 2026-05-03 | overlay 文件 + iter 时合并 |
| P2-04 | recorder | 实现 orphaned 状态检测（init 时 scan） | P1 | ✅ | 0.5 | 2026-05-03 | 通过 overlay 标记 |
| P2-05 | memory | 实现 `memory/store.py`（load/save/query） | P0 | ✅ | 1 | 2026-05-03 | canonical YAML 写盘 |
| P2-06 | memory | 实现 `memory/manifest.py` | P0 | ✅ | 0.5 | 2026-05-03 | 含 build_initial_manifest |
| P2-07 | memory | 实现 `memory/snapshot.py`（create/rollback/list/prune） | P0 | ✅ | 1.5 | 2026-05-03 | 不可覆盖 + 安全提取 |
| P2-08 | memory | 实现 `memory/checksum.py`（thin wrapper of core） | P0 | ✅ | 0.3 | 2026-05-03 | |
| P2-09 | memory | 启动时校验：protocol_version + checksum | P0 | ✅ | 0.5 | 2026-05-03 | 含 anchor drift 检测 |
| P2-10 | api | 实现 `api/evol.py` 雏形（不含 reflector / advisor） | P0 | ✅ | 0.5 | 2026-05-03 | Evol facade + EvolState |
| P2-11 | cli | 实现 `evol init`（创建 .evol/ + 默认 manifest） | P0 | ✅ | 1 | 2026-05-03 | rich 表格输出 |
| P2-12 | cli | 实现 `evol status` | P0 | ✅ | 0.5 | 2026-05-03 | |
| P2-13 | cli | 实现 `evol pause` / `evol resume` | P0 | ✅ | 0.5 | 2026-05-03 | 通过 .evol/PAUSED 标记 |
| P2-14 | cli | 实现 `evol versions` | P1 | ✅ | 0.3 | 2026-05-03 | 表格列出含 active 标记 |
| P2-15 | tests | 单元：recorder（含 feedback overlay） | P0 | ✅ | 1 | 2026-05-03 | recorder 88% / jsonl_store 91% |
| P2-16 | tests | 单元：memory store + snapshot | P0 | ✅ | 1 | 2026-05-03 | memory 全模块 82-100% |
| P2-17 | tests | 集成：end-to-end "init → start_task × 5 → end_task × 5" | P0 | ✅ | 1 | 2026-05-03 | 含跨重启持久化、orphan 恢复、anchor drift |

阶段总工作量：**~13 天** · 阶段验收：**✅ 全部通过**——121 个测试通过、CLI 5 个命令端到端冒烟通过、Phase 2 实现模块覆盖 82-100%。

### 9.4 阶段三：Reflector + 三 LLM Backend（Phase 3 · Week 5–6）

**目标**：手动触发反思能跑通；Memory 在反思后真的演化；direct / subprocess / host 三种 LLM Backend 全部就绪。

| ID | 模块 | 任务 | 优先级 | 状态 | 工作量(天) | 完成日期 | 备注 |
|---|---|---|---|---|---|---|---|
| P3-01 | llm | 实现 `llm/base.py` ABC + `Message` / `LLMResponse` | P0 | ✅ | 0.5 | 2026-05-03 | 含 DeferredLLMResponse 双类型 |
| P3-02 | llm | 实现 `llm/anthropic_client.py` | P0 | ✅ | 1 | 2026-05-03 | system 拆分 + usage 透传 |
| P3-03 | llm | 实现 `llm/mock_client.py`（测试用） | P0 | ✅ | 0.5 | 2026-05-03 | list 或 callable，记录 calls |
| P3-04 | llm | 实现 `llm/openai_client.py`（可选依赖） | P2 | ✅ | 0.5 | 2026-05-03 | 仅在 openai 可选依赖装上时跑 |
| P3-05 | reflector | 实现 `reflector/trigger.py`（3 种 trigger） | P0 | ✅ | 1 | 2026-05-03 | manual/threshold/scheduled |
| P3-06 | reflector | 实现 `reflector/batcher.py`（按信号优先级采样） | P0 | ✅ | 1 | 2026-05-03 | 高信号优先 + 时序保留 |
| P3-07 | reflector | 实现 `reflector/prompt.py`（FLOWS §3.4 模板） | P0 | ✅ | 1.5 | 2026-05-03 | 三段式 + per-experience 截断 |
| P3-08 | reflector | 实现 `reflector/parser.py`（JSON 解析 + retry） | P0 | ✅ | 1 | 2026-05-03 | code fence / 包装对象 / 散文恢复 |
| P3-09 | reflector | 实现 `reflector/filter.py`（AnchorFilter） | P0 | ✅ | 1 | 2026-05-03 | regex/text/semantic + fail-safe |
| P3-10 | memory | 实现 `memory/consolidator.py`（5 种 op） | P0 | ✅ | 1.5 | 2026-05-03 | confidence cap + 冲突解决 |
| P3-11 | reflector | 实现 `reflector/reflector.py` 主流程编排 | P0 | ✅ | 1.5 | 2026-05-03 | 完整 10+2 状态机 |
| P3-12 | reflector | 写 `insights/<date>-reflection.md` | P0 | ✅ | 0.5 | 2026-05-03 | frontmatter + 通过/拒绝 两节 |
| P3-13 | api | 接入 reflector 到 `api/evol.py` | P0 | ✅ | 0.3 | 2026-05-03 | 懒加载 LLM；启动自动 resume |
| P3-14 | cli | 实现 `evol reflect` | P0 | ✅ | 0.5 | 2026-05-03 | 含 --pickup-only |
| P3-15 | tests | 单元：parser / filter / consolidator | P0 | ✅ | 1.5 | 2026-05-03 | 39 个测试 |
| P3-16 | tests | 集成：反思周期完整跑（含 anchor reject case） | P0 | ✅ | 1.5 | 2026-05-03 | direct + anchor reject + parse_failed + no_op |
| P3-17 | llm | 实现 `subprocess_client.py`（拉起本地 claude / codex CLI） | P1 | ✅ | 1 | 2026-05-03 | text/json 双格式；超时与异常映射 |
| P3-18 | llm | 实现 `host_client.py`（pending request 渲染 + poll） | P0 | ✅ | 1.5 | 2026-05-03 | 三种 purpose 各自 schema 模板 |
| P3-19 | llm | 实现 `detector.py` backend 自动检测 | P1 | ✅ | 0.5 | 2026-05-03 | EVOL_BACKEND > HOST_AGENT > KEY > CLI |
| P3-20 | reflector | 实现 `Reflector.resume_pending()` | P0 | ✅ | 1 | 2026-05-03 | 扫 deferred → poll → consolidate |
| P3-21 | reflector | 实现 deferred state 持久化（`.evol/deferred/`） | P0 | ✅ | 0.5 | 2026-05-03 | pending/consumed/parse_failed 状态 |
| P3-22 | tests | host backend 端到端测试（mock pending → completed） | P0 | ✅ | 1 | 2026-05-03 | 含跨重启自动 resume 验证 |

阶段总工作量：**~19.5 天** · 阶段验收：**✅ 全部通过**——180 个测试通过 + 1 跳过（无 anthropic 包），整体覆盖 77%；direct + host backend 均端到端跑通；anchor 拒绝路径有真实集成测试覆盖；host 模式下跨 session auto-resume 验证通过。

### 9.5 阶段四：Advisor + 启发流 + host_strategy（Phase 4 · Week 7–8）

**目标**：完成 enhance / inspire；Memory 真的能反哺 prompt；启发能产出；host backend 下 inspire 三档策略到位。

| ID | 模块 | 任务 | 优先级 | 状态 | 工作量(天) | 完成日期 | 备注 |
|---|---|---|---|---|---|---|---|
| P4-01 | advisor | 实现 `advisor/retrieval.py`（关键词 + tag + recency） | P0 | ✅ | 1.5 | 2026-05-04 | 含双向 fragment + 5 字符前缀松匹配 |
| P4-02 | advisor | 实现 `advisor/budget.py`（token 预算管理） | P0 | ✅ | 1 | 2026-05-04 | 按候选 score 顺序填充 + 60 token 下限 |
| P4-03 | advisor | 实现 enhance 注入模板（HTML 注释式 ref） | P0 | ✅ | 1 | 2026-05-04 | system prefix + `<!-- evol:advice -->` |
| P4-04 | advisor | 实现 `advisor.enhance()` 主流程 | P0 | ✅ | 1 | 2026-05-04 | 永不抛错；空 memory 原样返回 |
| P4-05 | advisor | 实现 `advisor/inspiration_history.py` | P0 | ✅ | 0.5 | 2026-05-04 | append-only jsonl + cooldown/today 查询 |
| P4-06 | advisor | 实现 4 道节流门控（freq/cooldown/quota/warmup） | P0 | ✅ | 1 | 2026-05-04 | 任一不通过即返回 None |
| P4-07 | advisor | 实现确定性 PRNG 概率投币 | P1 | ✅ | 0.3 | 2026-05-04 | sha256(count\|today\|task_kind) |
| P4-08 | advisor | 实现启发 prompt 与解析 | P0 | ✅ | 1 | 2026-05-04 | code fence/包装对象/散文容错 |
| P4-09 | advisor | 实现 `advisor.inspire()` 主流程 | P0 | ✅ | 1 | 2026-05-04 | regex anchor 后置过滤 + 历史记录 |
| P4-10 | api | 接入 advisor 到 `api/evol.py` | P0 | ✅ | 0.3 | 2026-05-04 | 懒加载（与 reflector 同模式）|
| P4-11 | cli | 实现 `evol memory show` | P1 | ✅ | 0.5 | 2026-05-04 | rich 表格 + 单 kind 过滤 |
| P4-12 | cli | 实现 `evol memory edit`（启动 $EDITOR） | P1 | ✅ | 0.5 | 2026-05-04 | $EDITOR/$VISUAL/默认 + 保存后 schema 校验 |
| P4-13 | cli | 实现 `evol rollback v3` | P0 | ✅ | 1 | 2026-05-04 | 含 reflection.lock + system.rollback Experience |
| P4-14 | cli | 实现 `evol diff v3 v5` | P2 | ✅ | 0.5 | 2026-05-04 | unified diff，按 kind 分别比较 |
| P4-15 | cli | 实现 `evol export` / `evol import` | P1 | ✅ | 1 | 2026-05-04 | --redacted 缺省，--full 需显式 |
| P4-16 | tests | 单元：retrieval / budget / inspiration_history | P0 | ✅ | 1.5 | 2026-05-04 | 26 个新测试 |
| P4-17 | tests | 集成：100 次任务 + 反思 + enhance/inspire 实际效果 | P0 | ✅ | 1.5 | 2026-05-04 | 100 任务 → 反思 → enhance 注入完整链路 |
| P4-18 | advisor | 实现 inspiration `host_strategy` 三档（defer / template / disabled） | P1 | ✅ | 0.5 | 2026-05-04 | template 不调 LLM 走 Memory 套模板 |

阶段总工作量：**~14.5 天** · 阶段验收：**✅ 全部通过**——215 个测试通过 + 1 跳过；100 任务全链路集成测试覆盖（reflect → enhance 反哺）；inspire 在合适时机给出非空启发；rollback / diff / export-import 全部端到端 CLI 跑通；host 模式 template 策略验证。

### 9.6 阶段五：Reference Example（含 Skill）+ CTS + 发布（Phase 5 · Week 9–10）

**目标**：journal-cli 在 direct backend 真实跑通；同一 example 经 Claude Code Skill 包装后在 host backend 跑通；CTS 第一版；可发布到 PyPI 测试。

| ID | 模块 | 任务 | 优先级 | 状态 | 工作量(天) | 完成日期 | 备注 |
|---|---|---|---|---|---|---|---|
| P5-01 | example | 实现 `examples/journal-cli`（完整可跑） | P0 | ✅ | 1.5 | 2026-05-04 | 含 evol.config.yaml + journal_cli.py + README |
| P5-02 | example | 自动化 30 天演化模拟脚本 | P1 | ✅ | 1 | 2026-05-04 | 模拟运行：6 次反思 / Memory v0→v6 / 4 类沉淀 |
| P5-03 | cts | 搭 `tests/conformance/` 框架 | P0 | ✅ | 1 | 2026-05-04 | conformance marker + README |
| P5-04 | cts | Schema 一致性测试套件 | P0 | ✅ | 1 | 2026-05-04 | 12 测试：canonicalization 字节稳定 + 各 yaml/jsonl 校验 |
| P5-05 | cts | Behavior 一致性测试套件 | P0 | ✅ | 1.5 | 2026-05-04 | 16 测试：5 API + admin 操作行为契约 |
| P5-06 | cts | Concurrency 测试套件 | P0 | ✅ | 1 | 2026-05-04 | 7 测试：file lock + 80 行并发追加 + 残锁恢复 |
| P5-07 | cts | Anchor 守护测试套件 | P0 | ✅ | 1 | 2026-05-04 | 9 测试：fail-safe + 审计 + 无运行时变更 API |
| P5-08 | docs | 完成 README、API doc、recipes | P1 | ✅ | 1.5 | 2026-05-04 | README 完全重写；CHANGELOG + RELEASE_NOTES 就位 |
| P5-09 | release | 配置 PyPI 发布（test PyPI 先） | P1 | ✅ | 0.5 | 2026-05-04 | pyproject.toml 自带 hatchling + console_script |
| P5-10 | release | 准备 v0.1.0 release notes + tag | P1 | ✅ | 0.3 | 2026-05-04 | RELEASE_NOTES.md 全面发布说明 |
| P5-11 | example | 实现 Claude Code Skill 包装的 journal-cli example（host backend） | P1 | ✅ | 1 | 2026-05-04 | SKILL.md + scripts/journal_summarize.py（双调用模式：prepare / record） |

阶段总工作量：**~11 天** · 阶段验收：**✅ 全部通过**——262 测试通过 + 1 跳过；CTS 47 项全绿；30 天 simulation 实跑 Memory 6 次成长；direct + host 双形态 example 就位；CHANGELOG/RELEASE_NOTES 完整；pyproject.toml 可发布。

### 9.7 阶段总览

| 阶段 | 周次 | 任务数 | 工作量 | 累计 |
|---|---|---|---|---|
| Phase 1：地基 | W1–2 | 16 | 12 | 12 |
| Phase 2：Recorder + Memory | W3–4 | 17 | 13 | 25 |
| Phase 3：Reflector + 三 LLM Backend | W5–6 | 22 | 19.5 | 44.5 |
| Phase 4：Advisor + host_strategy | W7–8 | 18 | 14.5 | 59 |
| Phase 5：Example（含 Skill）+ CTS + 发布 | W9–10 | 11 | 11 | 70 |
| **合计** | **10 周** | **84** | **70 天** | |

> **84 个任务、70 天工作量、10 周时间。**
> 假定单人全职，预留 30% 缓冲（实际投入约 90 天）。
> 多人并行可压缩到 6–7 周（核心瓶颈仍在 Phase 3 的 reflector 编排 + 三 backend 集成）。

---

## 十、里程碑与验收标准

| 里程碑 | 周次 | 验收标准 |
|---|---|---|
| **M1：地基就绪** | 末 W2 | core / config / concurrency / errors 单测通过；canonical 跨平台 checksum 一致 |
| **M2：日记本就绪** | 末 W4 | `evol init` + `evol status` 可用；连跑 100 次 start_task + end_task 不出错 |
| **M3：反思就绪** | 末 W6 | `evol reflect` 完整执行；anchor 拒绝路径有覆盖；Memory v0→v1 真实演化 |
| **M4：智慧就绪** | 末 W8 | enhance 真的注入 advice；inspire 在合适时机真的输出；rollback 工作 |
| **M5：v0.1 发布** | 末 W10 | journal-cli 跑通 30 天演化；CTS 全绿；test PyPI 发布；README 完整 |

每个里程碑结束 [SHOULD] 写一份 retrospective 短文，沉淀踩坑与改进点（这本身就是 EVOL 哲学的实践）。

---

## 十一、编码规范与提交规范

### 11.1 代码风格

- **Formatter**：`ruff format`（替代 black）
- **Linter**：`ruff check`（含 isort、pyupgrade、bugbear）
- **Type check**：`mypy --strict`（生产代码）；测试代码可 relaxed

### 11.2 命名约定

- 模块名：小写 + 下划线（snake_case），如 `inspiration_history.py`
- 类名：CamelCase
- 常量：UPPER_SNAKE_CASE
- 私有：单下划线前缀

### 11.3 类型注解

- 公共 API [MUST] 全部带类型注解
- 内部辅助函数 [SHOULD] 带类型注解

### 11.4 Commit 规范（Conventional Commits）

```
<type>(<scope>): <subject>

[optional body]

[optional footer(s)]
```

`type`: `feat` / `fix` / `docs` / `refactor` / `test` / `chore` / `perf`
`scope`: 模块名（recorder / memory / reflector / ...）
`subject`: 一句话，祈使语气

例：

```
feat(reflector): implement anchor post-filter with fail-safe semantics

Implements FLOWS §3.6. The filter conservatively rejects an Insight 
when conflict() evaluation itself fails (LLM error, etc.).

Refs: #42
```

### 11.5 PR 准入门槛

- CI 全绿（lint + mypy + pytest + coverage）
- 所有新代码有对应的单测
- 涉及行为变更 [MUST] 同步更新对应文档（CONTRACT / DATA-MODEL / FLOWS）
- PR description 引用相关任务 ID（如 `Closes P3-09`）

---

## 十二、本文档与其他文档的关系

```
   规范层（不绑定语言）：
       VISION ── PRINCIPLES ── QUICKSTART ── ARCHITECTURE
                                    │
                                    ├── CONTRACT
                                    ├── DATA-MODEL
                                    └── FLOWS

   实施层（绑定 Python，仅 evol-py）：
       IMPLEMENTATION（本文）
            │
            └── 落地为：src/evol/**/*.py + tests/**/*.py + examples/journal-cli
```

**关系**：

- 当本文与 CONTRACT/DATA-MODEL/FLOWS 冲突时，**协议层（前者）优先**——本文是 Python 实现细节，不能反向修改协议
- 本文的"任务表"完成后，evol-py 即达到 v0.1.0；evol-ts / evol-java 可基于同一份协议另行实施

---

## 附 A：快速启动 checklist（Day 1）

按这个顺序在新机器上启动：

```bash
# 1. 创建仓库
mkdir evol-py && cd evol-py
git init

# 2. Python 环境
python3.10 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

# 3. 创建 pyproject.toml（手写或拷贝模板）
# 4. 安装基础依赖
pip install pydantic pyyaml click rich portalocker anthropic
pip install -e ".[dev]"        # 开发依赖

# 5. 创建目录骨架
mkdir -p src/evol/{config,core,concurrency,llm,recorder,memory,reflector,advisor,cli/commands,api}
mkdir -p tests/{unit,integration,conformance,fixtures}
touch src/evol/__init__.py

# 6. 配置 ruff + mypy + pre-commit
pre-commit install

# 7. 跑一个空 pytest 验证环境
pytest -q

# 8. 开始 P1-04（实现 core/types.py）
```

---

## 附 B：依赖于决策的关键技术问题（提前对齐）

下列问题在编码前最好先做一次决定，避免反复返工：

| 问题 | 推荐 | 原因 |
|---|---|---|
| 是否在 v0.1 引入 `tiktoken` | 默认不引入；用字符 / 4 估算 | 保持 zero-extra-deps |
| `experiences.jsonl` 的 feedback overlay 文件名 | `experiences.feedback.jsonl` | 易理解、与主文件并列 |
| Snapshot 用 tar 还是 zip | tar.gz | Linux 原生、无 windows 兼容问题（Python tarfile 跨平台） |
| Memory rollback 后是否保留 rollback 后做出的 reflection | 保留——rollback 不删 insights/*.md | 历史可见原则 |
| 多 memory_kind 是否合并到一个 yaml 文件 | 不——保持 3 个独立文件 | 可读性与文件锁粒度 |
| LLM 调用是否走异步（asyncio） | v0.1 同步；v0.2 考虑 async 双形态 | 简化起步实现 |

---

## 附 C：本文档的迭代承诺

本文档不是一次写就。预计在以下时机迭代：

- **每个里程碑结束后** —— 根据实际遇到的问题，更新模块设计 / 任务清单 / 工作量估算
- **任何 ADR 落地时** —— 同步更新对应模块设计
- **CTS 新增大类时** —— 同步更新 §8.4 测试策略

> 本文档既是**蓝图**，也是**日志**——它会跟随 evol-py 的成长一起成长。

---

## 附 D：参考片段（First Code）

下面是建议的"第一个 commit"内容——一旦这段代码跑通，意味着 P1-04 完成。

```python
# src/evol/core/types.py
from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict

ISO8601 = str

class Signal(BaseModel):
    type: str
    ts: ISO8601
    value: Any | None = None
    source: Literal["explicit", "implicit"] = "explicit"
    weight: float | None = None

class Experience(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    task_kind: str = "default"
    status: Literal["open", "closed", "orphaned", "redacted"]
    started_at: ISO8601
    ended_at: ISO8601 | None = None
    input: Any
    output: Any | None = None
    signals: list[Signal] = Field(default_factory=list)
    advice_used: list[str] = Field(default_factory=list)
    anchors_applied: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    redacted: bool = False
```

```python
# tests/unit/test_types.py
from evol.core.types import Experience, Signal

def test_experience_minimal():
    exp = Experience(
        id="exp_test_0001",
        status="open",
        started_at="2026-05-03T14:30:00.000Z",
        input="hello",
    )
    assert exp.task_kind == "default"
    assert exp.signals == []

def test_signal_default_source():
    s = Signal(type="kept", ts="2026-05-03T14:35:00.000Z")
    assert s.source == "explicit"
```

跑通：

```bash
$ pytest tests/unit/test_types.py -v
test_experience_minimal PASSED
test_signal_default_source PASSED
```

恭喜——这是 EVOL 在你的机器上的第一次"心跳"。后面 75 个任务都从这里出发。

---

> 框架的真正落地，不在文档的厚度，而在第一行能跑的代码。
> 第一行 PR 之后，本文档就从"设计"变成"实施"——
> 每勾掉一个 ☐，EVOL 就离"会成长的软件"近一步。
