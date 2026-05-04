# EVOL

> 让软件学会生长，也让使用者一同进化。

EVOL 是一个轻量、可嵌入的 **AI 软件成长进化基础设施**。产品接入 EVOL 后，可以从自己的真实使用中持续学习，并把学习结果以受控、可解释、可回滚的方式反哺到后续任务与用户启发中。

EVOL 不是 Agent 框架，不是执行引擎，也不是 SaaS 平台。它是一套本地优先的 SDK、一份可互操作的 Disk Protocol，以及一个以 `.evol/` 目录为核心的成长资产管理约定。

[English README](./README.md)

## EVOL 为什么存在

大多数 AI 产品只优化“当前任务完成得怎么样”。任务结束后，用户的修改、反馈、偏好、反复出现的失败、偶然出现的高质量结果，往往被丢弃，或散落在临时日志里。

EVOL 把每一次交互同时视为：

- 一次要完成的任务
- 一份可被反思和沉淀的经验

它希望帮助产品从静态工具走向成长型伙伴，同时保证这种成长是可读的、版本化的、可回滚的。

## EVOL 站在哪里

EVOL 位于执行层和智能体层之上，与它们互补，而不是替代它们。

```text
Product Code
  ├─ recorder.start_task / end_task / feedback
  ├─ advisor.enhance
  └─ advisor.inspire
        │
        ▼
EVOL Growth Layer
  Recorder · Reflector · Memory · Advisor
        │
        ▼
Execution Layer
  Harness / LangGraph / AutoGen / direct LLM SDK / your own runtime
```

Harness 让流程每次都更可靠地“做对”。EVOL 让产品在长期使用中“做得越来越好”。

## EVOL 提供什么

| 能力 | 含义 |
|---|---|
| 经验记录 | 把有意义的产品任务写成 append-only Experience 日志 |
| 反馈信号 | 支持 `kept`、`edited`、`discarded`、`rated`、`comment` 与自定义信号 |
| 结构化反思 | 把一批 Experience 反思为可审计的 Insight |
| 长期记忆 | 用 YAML 保存用户画像、领域经验、自我认知 |
| Prompt 增强 | 在产品调用 LLM 前，将相关 Memory 注入 prompt |
| 启发反哺 | 在合适时机向用户输出有价值的观察或建议 |
| 版本与回滚 | 对 Memory 变更生成快照，可回滚到历史版本 |
| 本地优先存储 | 所有成长资产都在 `.evol/`，可读、可 diff、可备份、可脱敏 |

## 当前实现状态

Python reference implementation 位于 [`evol-py/`](./evol-py/)。

- 包名：`evol-kit`
- import 名：`evol`
- 协议版本：`0.1`
- 当前状态：`v0.1.0 alpha`
- 已验证测试：`263 passed`

核心 API：

| API | 作用 |
|---|---|
| `recorder.start_task(input, ...)` | 打开一条 Experience |
| `recorder.end_task(handle, output=...)` | 关闭一条 Experience |
| `recorder.feedback(experience_id, signal)` | 追加用户反馈 |
| `advisor.enhance(prompt, task=...)` | 把相关 Memory 注入 prompt |
| `advisor.inspire(task=...)` | 可能返回一条面向用户的启发 |
| `reflector.reflect()` | 把近期 Experience 提炼成 Memory |

## 快速开始

本地安装 Python reference implementation：

```bash
cd evol-py
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

运行不需要 API key 的 30 天模拟：

```bash
cd examples/journal-cli
python simulate_30_days.py
```

查看生成的成长资产：

```bash
cat .evol/memory/user_profile.yaml
cat .evol/memory/domain_knowledge.yaml
cat .evol/memory/self_awareness.yaml
ls .evol/insights/
ls .evol/versions/
```

使用 CLI 检查状态：

```bash
evol --root . status
evol --root . memory show
evol --root . versions
evol --root . diff 0 1
```

完整上手流程见 [GETTING-STARTED.md](./GETTING-STARTED.md)。

## 最小接入方式

在产品根目录创建 `evol.config.yaml`：

```yaml
schema_version: 1

product:
  name: my-product
  version: 0.1.0
  domain: 你的产品领域

anchors:
  - description: 核心产品约束
    kind: text
    rule: 产品不能学习任何违反这条原则的行为。

reflection:
  trigger: threshold
  threshold: 20

inspiration:
  frequency: low
  cooldown_hours: 24
  max_per_day: 2

llm:
  backend: auto
```

在任务链路里加入 EVOL：

```python
from evol import Evol

evol = Evol.from_config("evol.config.yaml")

def run_task(user_input: str) -> str:
    handle = evol.recorder.start_task(
        input=user_input,
        task_kind="your_task_kind",
    )

    prompt = build_prompt(user_input)
    prompt = evol.advisor.enhance(
        prompt,
        task={"task_kind": "your_task_kind"},
    )

    output = call_your_llm(prompt)
    experience_id = evol.recorder.end_task(handle, output=output)

    return output
```

当用户产生反馈时，写回 EVOL：

```python
from evol.core.time_utils import utc_now_iso
from evol.core.types import Signal

evol.recorder.feedback(
    experience_id,
    Signal(type="edited", ts=utc_now_iso(), source="explicit"),
)
```

在用户请求主链路之外触发反思：

```bash
evol reflect
evol memory show
```

## `.evol/` 目录

EVOL 的成长资产都显式存在磁盘上：

```text
.evol/
├── manifest.yaml
├── config.yaml
├── experiences.jsonl
├── experiences.feedback.jsonl
├── memory/
│   ├── user_profile.yaml
│   ├── domain_knowledge.yaml
│   └── self_awareness.yaml
├── insights/
├── versions/
└── locks/
```

这是 EVOL 可信赖设计的核心：

- 你可以看见产品学到了什么。
- 你可以手工编辑 Memory。
- 你可以比较不同版本。
- 你可以回滚错误成长。
- 你可以导出脱敏包用于审计或迁移。

## LLM 后端

EVOL 支持三种后端形态：

| 后端 | 适合场景 |
|---|---|
| `direct` | 产品自己持有 Anthropic / OpenAI API key |
| `subprocess` | 复用本机 `claude` 或 `codex` CLI 登录态 |
| `host` | EVOL 运行在宿主 Agent 或 Skill 中，由宿主代办 LLM 调用 |
| `auto` | 让 EVOL 自动探测可用后端 |

详见 [LLM-BACKENDS.md](./LLM-BACKENDS.md)。

## CLI 速览

```bash
evol init
evol status
evol reflect
evol memory show
evol memory edit user_profile
evol versions
evol diff 0 1
evol rollback 1
evol export ./backup.tgz
evol import ./backup.tgz
evol pause
evol resume
```

## 文档地图

| 层级 | 文档 |
|---|---|
| 愿景 | [VISION.md](./VISION.md) |
| 设计原则 | [PRINCIPLES.md](./PRINCIPLES.md) |
| 入门教程 | [GETTING-STARTED.md](./GETTING-STARTED.md) |
| 原始接入试金石 | [QUICKSTART.md](./QUICKSTART.md) |
| 架构概览 | [ARCHITECTURE.md](./ARCHITECTURE.md) |
| 协议契约 | [CONTRACT.md](./CONTRACT.md) |
| 数据模型 | [DATA-MODEL.md](./DATA-MODEL.md) |
| 内部流程 | [FLOWS.md](./FLOWS.md) |
| LLM 后端设计 | [LLM-BACKENDS.md](./LLM-BACKENDS.md) |
| Python 实现说明 | [IMPLEMENTATION.md](./IMPLEMENTATION.md) |

## 开发

```bash
cd evol-py
python -m pip install -e ".[dev]"

ruff check src tests
ruff format src tests
mypy
pytest -q
pytest tests/conformance/ -v
```

## 非目标

EVOL 明确不做：

- 不修改自己的源代码
- 不模仿人类意识或情绪
- 不替代执行框架或 Agent Runtime
- 不要求接入 SaaS 服务
- 不把成长资产隐藏在黑盒向量或模型权重里
- 不在每一次用户请求中实时反思

## License

Apache License 2.0. See [LICENSE](./LICENSE).
