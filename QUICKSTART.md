# 《EVOL 接入示例：Hello, EVOL》

> QUICKSTART.md · 这是 EVOL 的「试金石文档」。
>
> 在写一行框架代码之前，先把这份接入示例写到自己满意——
> 如果开发者用起来不爽、改动太多、命令太复杂，那就不是文档不好，**是框架设计错了**。
>
> 这份文档存在的意义，是逼我们回答一个问题：
> **"开发者接入 EVOL 之后，到底是什么体验？"**

---

## 一、我们要造的虚构产品：`journal-cli`

为了让 EVOL 的接入价值看得见，我们先构造一个最小、但完整的小产品作为示例。

**产品名**：`journal-cli`
**形态**：一个命令行工具
**做什么**：每天结束时，把当天的日记文本喂进去，输出一段 100 字以内的总结
**目标用户**：把"每日反思"作为习惯的写作型用户（也包括我们自己）

```bash
$ cat today.txt | journal-cli
今天主要在搭 EVOL 的雏形。上午把 Recorder 的接口签名敲定了……
（一段简短总结）
```

这就是产品的全部能力。

接下来我们要做的事——
**让这个 100 行的小工具，在使用 30 天后变得越来越懂用户；使用 90 天后，开始反过来给用户提供洞见。**

不是靠模型升级，不是靠手工调 prompt——靠接入 EVOL。

---

## 二、接入 EVOL 之前：原始代码

```python
# journal_cli.py
import sys
from anthropic import Anthropic

client = Anthropic()

PROMPT_TEMPLATE = """请把下面的日记总结成一段 100 字以内的概要：

{journal}
"""

def summarize(journal: str) -> str:
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": PROMPT_TEMPLATE.format(journal=journal)}],
    )
    return msg.content[0].text


if __name__ == "__main__":
    print(summarize(sys.stdin.read()))
```

干净、能跑、毫无成长性。

每一次调用，模型都在"重新认识"这个用户。
用户偏好的长度、想被强调的主题、不喜欢的语气——**全部在每次任务结束后被丢弃**。

这是当代 99% 的 AI 工具的现状。

---

## 三、接入 EVOL 之后：完整代码（加了 7 行）

```python
# journal_cli.py
import sys
from anthropic import Anthropic
from evol import Evol                                          # ① 新增

client = Anthropic()
evol = Evol.from_config("evol.config.yaml")                    # ② 新增

PROMPT_TEMPLATE = """请把下面的日记总结成一段 100 字以内的概要：

{journal}
"""

def summarize(journal: str) -> str:
    task = evol.recorder.start_task(input=journal)             # ③ 新增

    prompt = PROMPT_TEMPLATE.format(journal=journal)
    prompt = evol.advisor.enhance(prompt, task="summarize")    # ④ 新增

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    output = msg.content[0].text

    evol.recorder.end_task(task, output=output)                # ⑤ 新增
    return output, evol.advisor.inspire(task="summarize")      # ⑥ 新增


if __name__ == "__main__":
    summary, inspiration = summarize(sys.stdin.read())
    print(summary)
    if inspiration:
        print(f"\n💡 EVOL: {inspiration}")                      # ⑦ 新增
```

**净改动：6 行新增 + 1 行返回值变化。**
没有继承任何基类，没有改造架构，没有重写 prompt。

接下来再看一下用户反馈的回灌——它是**可选的**，但强烈建议加上：

```bash
# 用户编辑了总结后，命令行选择"采纳" / "改了" / "弃用"
$ journal-cli --feedback kept       # 或 edited / discarded
```

底层就是一句：
```python
evol.recorder.feedback(task_id, rating="kept")
```

至此整个接入完成。**实际工作量：30 分钟以内。**

---

## 四、接入契约：开发者要做的全部三件事

```
契约 ①：写一份 evol.config.yaml         （一次性，5 分钟）
契约 ②：在三个时机打三个埋点             （每个产品改一次，10 分钟）
         - start_task / end_task / feedback
契约 ③：在 LLM 调用前调用一次 advisor.enhance()   （每个产品改一处，5 分钟）
```

> 如果接入成本超过半天，那就违反了《PRINCIPLES》里的"接入成本即设计标尺"。
> 这份契约的简短，本身就是 EVOL 的产品承诺。

---

## 五、`evol.config.yaml`：产品自己声明"我是谁"

```yaml
# 一份接入 EVOL 的产品都要写一份这样的配置
product:
  name: journal-cli
  version: 0.1.0
  domain: 个人日记总结

# 价值锚点：不可演化的核心原则。EVOL 的所有反思 / 沉淀 / 启发，
# 都不能产出与下面任何一条冲突的结论。
anchors:
  - 总结必须忠实于原文，不杜撰、不加戏
  - 输出语言与输入保持一致
  - 篇幅控制在 100 字以内

# 启用哪些成长维度（MVP 阶段只支持这两层）
growth:
  knowledge_evolution: true       # 用户画像 + 领域经验 + 自我认知
  inspirational_feedback: true    # 启发反哺

# 反思的触发策略
reflection:
  trigger: threshold              # manual / threshold / scheduled
  threshold: 20                   # 每积累 20 次任务，反思一次

# 启发反哺的策略
inspiration:
  frequency: low                  # never / low / medium / high
  cooldown_hours: 24              # 至少间隔 24 小时再启发一次
```

整份配置不超过 30 行。
所有字段都有合理默认值——开发者甚至可以只写 `product` 一节就跑起来。

---

## 六、`.evol/` 目录：产品成长的物理体现

接入 EVOL 后，运行第一次 `evol init`，产品根目录会出现：

```
.evol/
├── config.yaml                       # 配置（与 evol.config.yaml 同步）
├── experiences.jsonl                 # 经验日志（每个任务一行 JSON）
├── memory/
│   ├── user_profile.yaml             # 用户画像
│   ├── domain_knowledge.yaml         # 领域经验
│   └── self_awareness.yaml           # 自我认知
├── insights/
│   ├── 2026-05-03-reflection.md      # 反思产出（人类可读）
│   └── 2026-05-23-reflection.md
└── versions/
    ├── memory-v1.snapshot
    ├── memory-v2.snapshot
    └── memory-v3.snapshot            # 当前版本
```

**重点**：
- 全部是**人类可读的明文**（YAML / JSONL / Markdown），不是数据库、不是向量库
- 可以直接 `cat .evol/memory/user_profile.yaml` 看
- 可以直接编辑（出错时人工修正比让 LLM 反思来得快）
- 可以 `git add .evol/` 全部纳入版本管理
- 团队协作 / 跨设备迁移 / 备份恢复，全部就是文件操作

这就是《PRINCIPLES》里"可读优于黑盒""本地优先""版本化"三条原则的物理落地。

---

## 七、产品行为的演化：Day 1 / Day 30 / Day 90

同一段日记输入，三个时间点的输出对比：

### Day 1：刚接入，EVOL 还没积累任何经验

```
> 输入：（一段 800 字的日记，关于今天 debug 了一个棘手的问题）

> 输出：
今天作者主要在工作中处理了一个技术问题，花费了较长时间排查。
此外还提到了与同事的交流和午餐。整体来说是充实的一天，但
也有一些挫败感。
```

**评价**：泛泛的总结。和接入前几乎没差别——这是合理的，EVOL 不是魔法。

---

### Day 30：积累了 30 次使用 + 几次用户编辑反馈

`.evol/memory/user_profile.yaml` 已沉淀出：

```yaml
version: 7
last_updated: 2026-06-01
confidence: medium

preferences:
  summary_length:
    value: 60-80 字（用户经常把 100 字编辑到 80 字以下）
    confidence: high
    evidence_count: 9

  highlight_pattern:
    value: 用户重视"今天学到了什么"远超"今天做了什么"
    confidence: high
    evidence_count: 12

  tone:
    value: 偏好简洁陈述句，反感感叹号与"充实的一天"这类总结性形容
    confidence: high
    evidence_count: 6

writing_topics:
  primary: [AI 工程, 产品设计, 阅读笔记]
```

同样的输入，输出变成：

```
> 输出：
今天 debug 了一个 retry 队列里的死锁问题，根因是错误的锁顺序。
学到的是：分布式系统里"看似无关的两把锁"经常是同一个状态机
的两个面，下次画状态图先于写代码。
```

**评价**：长度短了、删去了"充实的一天"、突出了"学到什么"。
**EVOL 没有重写 prompt**——只是在 `advisor.enhance()` 时把上面那份 user_profile 注入了进去。

---

### Day 90：第一次启发反哺

某次任务结束后，命令行多了一行：

```
> 输出：
今天读完了《Designing Data-Intensive Applications》第 7 章，
关键收获是事务隔离级别的取舍其实是延迟与一致性的换算。

💡 EVOL: 我注意到你最近 6 篇日记里有 4 篇是"读完一本书 / 一章"
   的总结，但你最初接触日记时更多是"今天做了什么"。这个转变
   是有意的吗？如果是，要不要把"本周阅读"做成一个独立的周报？
```

**评价**：这就是「启发反哺」——
EVOL 不只是更好地完成任务，**它开始向用户提出用户自己没想到的视角**。

这一步是 EVOL 区别于所有 Agent 框架的灵魂。

---

## 八、CLI 命令速览

接入 EVOL 后，开发者额外得到一组管理命令：

```bash
# 项目级
evol init                       # 初始化 .evol/ 目录
evol status                     # 当前积累的经验数 / 记忆版本 / 上次反思时间

# 反思与成长
evol reflect                    # 手动触发一次反思
evol memory show                # 查看当前记忆库的核心摘要
evol memory edit user_profile   # 用 $EDITOR 直接打开 YAML 修改

# 版本控制
evol versions                   # 列出所有记忆版本
evol rollback v3                # 回滚到 v3 版本
evol diff v3 v5                 # 比较两个版本的差异

# 安全开关
evol pause                      # 冻结所有成长（只服务任务）
evol resume                     # 恢复成长
evol export ./backup.tgz        # 全量导出
evol import ./backup.tgz        # 全量导入
```

> 这些命令都是 EVOL 框架自带的，开发者无需为自己的产品再造一套。

---

## 九、5 分钟自检清单

作为框架设计者，我们用这份 checklist 反复审视自己：
**只要任何一项做不到，就是框架设计错了。**

- [ ] 接入只需要 ≤ 7 行代码改动
- [ ] 配置文件 ≤ 30 行，且大部分字段有默认值
- [ ] 三个埋点（start / end / feedback）+ 一处 enhance + 可选 inspire
- [ ] 不需要继承任何基类、不需要改造架构、不需要迁移存储
- [ ] 所有成长资产可以 `cat` 看懂、可以 `vim` 直接编辑
- [ ] 任何时刻可以 `evol pause` 冻结成长，产品仍能正常工作
- [ ] 任何时刻可以 `evol rollback` 回到之前的状态
- [ ] 启发反哺是有节制的（默认 low + 24h cooldown）
- [ ] 用户体验从 Day 1 到 Day 90 有清晰可感的"在变好"

---

## 十、写在最后

这份 QUICKSTART 不是给开发者读的——它**首先是给我们自己读的**。

每当我们设计一个新接口、提出一个新约定、加入一个新概念时，回到这份文档问自己：

> 这个改动会让上面的代码变长吗？
> 会让 `evol.config.yaml` 多出几行吗？
> 会让"7 行接入"变成"50 行接入"吗？
> 会让 Day 30 / Day 90 那个"令人惊艳的成长瞬间"延后吗？

如果会——那这个改动几乎一定违反了 PRINCIPLES，应该被拒绝。

> Harness 让 `journal-cli` 每一次执行都稳定可靠。
> EVOL 让 `journal-cli` 每一次执行都让自己和用户更聪明一点。
>
> **这就是我们要造的那个东西。**

---

## 附：版本与迭代

- **v0.1（本版）** —— 起步阶段示例：`journal-cli`，6 行新增 + 1 行返回值变化
- 真正的 SDK 实现完成后，本文档将被一份**可运行的**示例仓库替代
- 未来加入的每一个新接口，都必须先回到这份文档"试装"一次——装不进去的接口，本身就值得怀疑
