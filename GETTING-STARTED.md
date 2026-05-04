# 《EVOL 入门教程》

> GETTING-STARTED.md · 面向第一次接触 EVOL 的开发者。
>
> 目标不是解释完整理论，而是让你在 30 分钟内完成三件事：
> 1. 跑起 Python reference implementation；
> 2. 看见 `.evol/` 里真实生成的成长资产；
> 3. 知道如何把 EVOL 接入自己的 AI 产品。

---

## 一、先理解一句话

**EVOL 是一个轻量、可嵌入的成长进化基础设施。**

接入 EVOL 后，你的产品会多出一条“成长层”：

```text
Product Code
  ├─ recorder.start_task / end_task / feedback     记录经验
  ├─ advisor.enhance                               读取记忆，增强 prompt
  ├─ reflector.reflect                             批量反思，沉淀记忆
  └─ advisor.inspire                               偶发启发用户

.evol/
  ├─ experiences.jsonl                             每次任务的经验日志
  ├─ memory/*.yaml                                 用户画像 / 领域经验 / 自我认知
  ├─ insights/*.md                                 每次反思的审计记录
  └─ versions/*.snapshot                           可回滚的记忆快照
```

EVOL 不替代你的 LLM 调用、不替代 Harness / LangGraph / AutoGen，也不修改你的源代码。它只负责一件事：**把每次使用留下来的经验，变成可读、可审计、可回滚的长期成长资产。**

---

## 二、准备环境

当前已经完成的实现位于 `evol-py/`，包名是 `evol-kit`，import 名是 `evol`。

```bash
cd evol-py
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

确认安装成功：

```bash
evol --version
evol --help
python -c "from evol import Evol; print(Evol)"
```

`evol --help` 会列出所有 11 个子命令（`init` / `status` / `reflect` / `memory` / `versions` / `diff` / `rollback` / `pause` / `resume` / `export` / `import`），不读完本文档也能从这里反查每个命令的用法。

如果只想先体验，不需要配置 API key。后面的 30 天模拟使用的是内置 mock LLM。

---

## 三、5 分钟看见 EVOL 真的在成长

进入内置示例：

```bash
cd examples/journal-cli
python simulate_30_days.py
```

这个脚本会模拟一个日记总结工具连续使用 30 天：

- 每天产生一条 `Experience`
- 每 3 天附加一次 `edited` 反馈信号
- 每 5 条经验触发一次反思（参考 `evol.config.yaml` 的 `reflection.threshold: 5`）
- 反思结果沉淀进 `memory/*.yaml`
- 每次记忆变更都会生成新快照

跑完后控制台会显示从 `Day 0 — fresh .evol/` 到 `Day 30 — final state` 的演化过程，记忆版本会从 v0 递增到 v5~v6 左右，并能看到 `user_profile` / `domain_knowledge` / `self_awareness` 三类记忆里出现具体条目。

跑完后查看生成物：

```bash
cat .evol/manifest.yaml
cat .evol/memory/user_profile.yaml
cat .evol/memory/domain_knowledge.yaml
cat .evol/memory/self_awareness.yaml
ls .evol/insights/
ls .evol/versions/
```

你应该能看到类似这样的结构：

```text
.evol/
├── manifest.yaml
├── experiences.jsonl
├── experiences.feedback.jsonl
├── memory/
│   ├── user_profile.yaml
│   ├── domain_knowledge.yaml
│   └── self_awareness.yaml
├── insights/
└── versions/
```

这一步最重要的不是 demo 输出，而是打开这些文件看一眼：EVOL 学到的东西不是黑盒向量，也不是隐藏状态，而是你可以 `cat`、`vim`、`git diff` 的明文资产。

---

## 四、用 CLI 检查和管理成长资产

仍然在 `examples/journal-cli/` 目录下：

```bash
evol --root . status
evol --root . memory show
evol --root . memory show user_profile
evol --root . versions
```

比较两个记忆版本：

```bash
evol --root . diff 0 1
```

如果某次反思让产品变差，可以回滚：

```bash
evol --root . rollback 1 --yes
```

如果你希望产品暂时停止成长，但仍然允许 `advisor.enhance()` 读取已有 Memory：

```bash
evol --root . pause
evol --root . status
evol --root . resume
```

导出 `.evol/` 时默认会脱敏 `input` / `output`：

```bash
evol --root . export ./evol-backup.tgz
```

需要包含原始经验文本时才使用：

```bash
evol --root . export ./evol-full-backup.tgz --full
```

---

## 五、跑一次真实 LLM 示例

如果你有 Anthropic API key：

```bash
export ANTHROPIC_API_KEY=...
python journal_cli.py <<'EOF'
今天主要在整理 EVOL 的入门教程。上午确认了 QUICKSTART、CONTRACT
和 Python SDK 的实现差异，下午跑通了 journal-cli 的模拟流程。
我发现最重要的不是把概念讲完整，而是让第一次接入的人尽快看见
.evol/ 目录里真实出现的经验、记忆和版本快照。
EOF
```

给最近一次任务追加反馈：

```bash
python journal_cli.py --feedback edited
python journal_cli.py --feedback kept
python journal_cli.py --feedback discarded
```

示例配置 `examples/journal-cli/evol.config.yaml`（已经精简，实际文件还多了两条 anchor 和一段 `memory.retention`）：

```yaml
schema_version: 1

product:
  name: journal-cli
  version: 0.1.0
  domain: 个人日记总结

anchors:
  - description: 忠实于原文
    kind: text
    rule: 总结必须忠实于原文，不杜撰，不加戏

reflection:
  trigger: threshold
  threshold: 5

inspiration:
  frequency: low
  cooldown_hours: 24
  max_per_day: 2

llm:
  backend: auto
  direct:
    provider: anthropic
    model: claude-sonnet-4-6
```

`llm.backend: auto` 会按顺序探测环境变量、host agent、API key、本地 `claude` / `codex` CLI。没有可用后端时，初始化和记录仍能工作，但触发反思或启发时会 fail-fast 或降级返回空结果。

---

## 六、把 EVOL 接入你自己的产品

### 1. 写配置

在产品根目录创建 `evol.config.yaml`：

```yaml
schema_version: 1

product:
  name: my-product
  version: 0.1.0
  domain: 你的产品领域

anchors:
  - description: 不可违背的底线
    kind: text
    rule: 这里写产品不能在成长中背离的原则

# 启用哪些成长维度（v0.1 默认两层都开）
growth:
  knowledge_evolution: true       # 用户画像 / 领域经验 / 自我认知
  inspirational_feedback: true    # 启发反哺

reflection:
  trigger: threshold              # manual / threshold / scheduled
  threshold: 20                   # 默认每积累 20 条 Experience 反思一次

inspiration:
  frequency: low                  # never / low / medium / high
  cooldown_hours: 24
  max_per_day: 2

llm:
  backend: auto
```

所有字段都有合理默认值，开发者也可以只写 `product` 一节就跑起来；剩余配置 EVOL 会按上面注释里的默认值填充。

初始化：

```bash
evol init
```

`evol init` 会在当前目录创建 `.evol/`，并把 `evol.config.yaml` 拷一份到 `.evol/config.yaml` 作为快照（运行时实际加载的仍是项目根的那一份）。

### 2. 在任务链路里加四个调用

最小接入代码：

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

    # end_task 返回 experience_id，下一节的 feedback 用它定位这条 Experience
    experience_id = evol.recorder.end_task(handle, output=output)
    return output, experience_id
```

这四个点分别对应：

| 调用 | 作用 | 是否阻塞核心链路 |
|---|---|---|
| `start_task` | 打开一条 Experience，返回 `TaskHandle` | 极轻，本地写 JSONL |
| `enhance` | 从 Memory 读取建议并追加到 prompt | 极轻，只读路径 |
| `end_task` | 关闭 Experience，返回 `experience_id` | 极轻，本地写 JSONL |
| `feedback` | 给指定 `experience_id` 追加用户反馈信号 | 可选，但强烈建议 |

四个调用都按"失败降级"语义实现：底层文件写失败只会打 warning，绝不抛回核心链路（详见第九节"常见问题"）。

### 3. 接入反馈

当用户采纳、编辑、弃用、评分或评论结果时，把信号写回 EVOL（用上一步 `end_task` 返回的 `experience_id`）：

```python
from evol.core.time_utils import utc_now_iso
from evol.core.types import Signal

evol.recorder.feedback(
    experience_id,
    Signal(type="edited", ts=utc_now_iso(), source="explicit"),
)

# 带 value 的反馈：1-5 评分
evol.recorder.feedback(
    experience_id,
    Signal(type="rated", ts=utc_now_iso(), value=4, source="explicit"),
)

# 带文本的反馈：自由评论
evol.recorder.feedback(
    experience_id,
    Signal(type="comment", ts=utc_now_iso(), value="希望更简洁", source="explicit"),
)
```

常用信号：

| 信号 | 语义 | `value` |
|---|---|---|
| `kept` | 用户原样采用 | 不需要 |
| `edited` | 用户编辑后采用 | 不需要 |
| `discarded` | 用户弃用 | 不需要 |
| `rated` | 用户显式评分 | int 1-5 |
| `comment` | 用户自由评论 | 文本 |

`source` 字段区分 `"explicit"`（用户主动反馈）和 `"implicit"`（产品根据行为推断，比如停留时间、复制行为）。两类都会被反思阶段使用，但权重不同。

### 4. 触发反思

开发阶段可以手动触发：

```bash
evol reflect
evol memory show
```

生产中通常使用 `threshold`：每积累 N 条新 Experience 后，由产品后台任务或运维脚本调用 `evol reflect`。反思永远不应该放在用户请求的关键路径上。

### 5. 输出启发

在任务结束后，可以偶发调用：

```python
inspiration = evol.advisor.inspire(task={"task_kind": "your_task_kind"})
if inspiration:
    print(inspiration.text)
```

`inspire()` 有四道门：

- `frequency`
- `cooldown_hours`
- `max_per_day`
- 至少 10 条 Experience 的 warmup

所以它默认不会频繁打扰用户。

---

## 七、LLM 后端怎么选

EVOL 抽象了三种真实后端，加上一种自动选择策略：

| 后端 | 适合场景 | 配置 |
|---|---|---|
| `direct` | 独立 Python 工具，自带 API key | 通过 `ANTHROPIC_API_KEY` 或 `OPENAI_API_KEY` |
| `subprocess` | 本机已经登录 `claude` / `codex` CLI | `llm.subprocess.command` |
| `host` | EVOL 作为 Claude Code / Codex Skill 嵌入 | host agent 代办 LLM 请求 |

`backend: auto` 是默认值，按以下顺序探测并落到上面三种之一：环境变量 `EVOL_LLM_BACKEND` → host agent 标记 → API key → 本地 `claude` / `codex` CLI。探测完成后表现完全等同于被选中的那一种后端。

入门阶段建议先用 `auto`。当产品形态稳定后，再根据部署环境明确指定后端，避免环境差异导致行为漂移。详见 `LLM-BACKENDS.md`。

---

## 八、什么时候算接入成功

最小成功标准：

- `evol status` 能看到产品名、协议版本、memory version、experience count
- 每次任务后 `.evol/experiences.jsonl` 增加记录
- 用户反馈后 `.evol/experiences.feedback.jsonl` 增加记录
- `evol reflect` 后 `.evol/insights/` 出现反思文件
- `evol memory show` 能看到用户画像、领域经验或自我认知条目
- `.evol/versions/` 中出现新的 `memory-vN.snapshot`
- `advisor.enhance()` 在 Memory 非空时会把可追溯建议块追加进 prompt

如果这些都成立，你的产品已经具备 EVOL v0.1 的两层成长能力：**知识进化**与**启发反哺**。

---

## 九、常见问题

### EVOL 会不会影响我的产品稳定性？

Recorder 和 Advisor 都按“失败降级”设计。`start_task` / `end_task` / `feedback` 失败时只记录 warning，不应该打断产品主流程；`enhance` 失败会原样返回 prompt；`inspire` 失败会返回 `None`。

### `.evol/` 要不要提交到 git？

开发和 demo 项目可以提交，便于审计成长过程。真实用户数据通常不应直接提交，至少要先使用 `evol export` 的默认脱敏模式，或在仓库策略里排除 `experiences*.jsonl`。

### Memory 可以手工改吗？

可以。EVOL 的原则是“可读优于黑盒”。你可以用：

```bash
evol memory edit user_profile
```

编辑后 SDK 会重新加载并校验 schema。

### 反思是不是每次任务都跑？

不是。反思是慢路径，应该手动、阈值或定时触发。每次任务只走轻量的记录与增强路径。

### EVOL 会自改代码吗？

不会。v0.1 的进化只发生在四类轻量资产上：经验、洞察、记忆、提示词增强。代码、工作流和模型权重不在 EVOL v0.1 的自动修改范围内。

### 调试期间如何"重置"或"冻结"成长？

最常用的三种姿势：

```bash
# 完全重置：删掉 .evol/，下次跑 evol init 重建
rm -rf .evol/

# 临时冻结：保留所有资产，但停止反思与启发，advisor.enhance() 仍可读
evol pause
evol resume

# 回到某个历史状态：先 list 再 rollback
evol versions
evol rollback 3 --yes
```

调试自有产品的 prompt 时，常见做法是：先 `evol pause` 锁住记忆 → 反复跑任务 → 满意后 `evol resume` 让反思继续。

---

## 十、下一步读什么

建议按这个顺序继续：

| 你想了解 | 阅读 |
|---|---|
| EVOL 为什么存在 | `VISION.md` |
| 设计取舍怎么判断 | `PRINCIPLES.md` |
| 快速理解接入体验 | `QUICKSTART.md` |
| 了解全局架构 | `ARCHITECTURE.md` |
| 实现其他语言 SDK | `CONTRACT.md` + `DATA-MODEL.md` + `FLOWS.md` |
| 理解 Python 实现 | `IMPLEMENTATION.md` + `evol-py/README.md` |
| 理解 LLM 后端 | `LLM-BACKENDS.md` |

---

## 附：入门路线图

```text
第 1 步：跑 simulate_30_days.py
第 2 步：查看 .evol/memory、insights、versions
第 3 步：用 evol status / memory / versions / diff / rollback 管理资产
第 4 步：在自己的产品里加 start_task / enhance / end_task / feedback
第 5 步：根据 config 中 reflection.threshold 触发反思（手动可用 evol reflect）
第 6 步：观察 advisor.enhance 是否让输出更贴近用户
第 7 步：谨慎开启 advisor.inspire，让产品开始反向启发用户
```

到这里，EVOL 就不再只是一个概念文档，而是一套已经接入你产品运行链路的成长基础设施。
