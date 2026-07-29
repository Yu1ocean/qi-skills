---
name: visit-todo-priority-manager
description: 从飞书 Wiki/Docx 会议纪要、拜访记录、复盘文档中提取 To-Do，完成 Owner/DDL/来源结构化整理，并按 P0/P1/P2 打标及校准 diff。适用于把飞书文档沉淀为项目管理清单、向 task-flow-engine 输出任务条目、或对人工调整后的优先级做回捞校准的场景。
author: 于奇楠
---

version: 1.1
# Visit Todo Priority Manager

## Common Rationalizations（常见借口库）

- “先把明显的 To-Do 抓出来，评论区补材料/追问先忽略。”
- “Owner 没确认就先留邮箱，后面再改名字。”
- “DDL 不明确也没关系，先按高优先级一股脑打红。”
- “原文里写了很多业务背景，我就顺手把已解决事项也记进去，免得漏。”
- “用户已经人工改过优先级，我就直接覆盖，不用产出 diff。”
- “先把飞书文档写出来，task-flow-engine 的下游字段以后再补。”

## Red Flags（危险信号）

- 输入链接不是飞书 `wiki` / `docx`，却继续执行。
- 还没下载原文与评论，就开始提取 To-Do。
- Owner 仍是邮箱、open_id、`@xxx@bytedance.com` 或空值，却继续交付。
- 把纯背景描述、历史结论、已解决事项当成待办输出。
- P0/P1/P2 只给结论，不给判定依据或升级原因。
- 人工校准后没有输出变更 diff，就直接覆盖优先级。
- 明确存在 DDL ≤ 3 天未完成的 P1，却没有给出“应升级为 P0”的巡检规则说明。
- 飞书文档写入未通过 `feishu-doc-writing-guide` 包装链路。

## Verification（强制验收清单）

宣称“提取与优先级管理完成”时，至少要满足：

1. **输入合法**：所有输入都是飞书 Wiki/Docx 链接，且已成功下载原文。
2. **抽取完整**：正文与评论区中的补材料/解释要求都已纳入候选池。
3. **过滤合规**：纯背景描述、已解决事项、无行动导向的陈述已被剔除。
4. **Owner 合规**：Owner 已转成真实姓名、角色或团队名；不得残留邮箱占位符。
5. **结构齐全**：每条记录至少包含 `Owner / DDL / 优先级 / 事项描述 / 来源`。
6. **优先级可解释**：每条 P0/P1/P2 都能回溯到明确规则或时间约束。
7. **校准可追踪**：若用户提供人工校准结果，必须输出变更 diff，而不是静默覆盖。
8. **下游可衔接**：输出结果可直接映射给 `task-flow-engine` 做任务追踪与 DDL 巡检。
9. **写后可读**：若生成飞书文档，必须通过 `feishu-doc-writing-guide` 路径完成写入并返回可访问链接。

## 📌 技能简介

把“纪要里散落的行动项”拉直成一份可管理、可巡检、可回溯的 To-Do 清单。上游负责飞书文档摄入、待办识别、P0/P1/P2 判级与校准 diff；下游由 `task-flow-engine` 接手任务台账追踪、DDL 巡检和催办升级。

## 🔑 触发词

- 核心关键词：
  - 飞书文档 To-Do 提取
  - 拜访记录整理
  - 会议纪要转任务清单
  - 优先级打标
  - 校准 diff
- 典型指令示例：
  > 把这两篇飞书纪要里的待办抽出来，按 P0/P1/P2 排好
  > 基于我人工改过的优先级，帮我输出一版变更 diff
  > 把这篇复盘文档整理成可以接 task-flow-engine 的任务清单

## 适用场景

- 拜访记录、会议纪要、项目复盘、方案对齐文档中存在大量行动项，需要抽取成任务清单。
- 需要把评论区中的“补材料 / 给一下 / 看下 / 对齐下”等追办要求一起纳入。
- 需要把任务按 P0/P1/P2 排序，做周会推进或直接对接任务台账。
- 用户已经人工改过优先级，希望输出机器判定 vs 人工校准的 diff。
- 需要为 `task-flow-engine` 准备结构化任务条目与升级规则说明。

## 输入 / 输出 Schema

### 输入 Schema

```yaml
inputs:
  doc_urls:
    type: array[string]
    required: true
    rule: 只接受飞书 Wiki / Docx 链接；v1 不支持妙记、CSV、表格。
  calibration_note:
    type: string
    required: false
    rule: 用户人工调整优先级后的说明，可按自然语言描述或条目列表提供。
  output_mode:
    type: enum[doc_only, doc_plus_diff, export_taskflow]
    required: false
    default: doc_only
```

### 输出 Schema

```yaml
outputs:
  todo_rows:
    type: array[object]
    fields:
      - owner
      - ddl
      - priority
      - description
      - source
      - priority_reason
  calibration_diff:
    type: array[object]
    optional: true
    fields:
      - task_key
      - old_priority
      - new_priority
      - change_reason
  taskflow_export_rows:
    type: array[object]
    optional: true
    fields:
      - task_name
      - owner
      - ddl
      - priority
      - source_doc
      - note
  feishu_doc_link:
    type: string
    optional: true
```

## ⚙️ 核心架构 / SOP / 约束条件

### Step 0｜输入校验（先过护栏）

1. 用 `scripts/todo_priority_guard.py` 校验输入链接是否全部为飞书 `wiki/docx`。
2. 任一链接不合法，立即熔断；不要把非飞书网页、表格或截图链接混进 v1 流程。
3. 若用户要求写入飞书文档，必须走 `feishu-doc-writing-guide`；不要裸调 OpenAPI。

### Step 1｜飞书文档摄入

1. 使用 `lark-doc` 下载每篇输入文档。
2. 读取正文、评论和内联备注；评论中的补材料 / 解释要求也属于候选待办。
3. 若文档包含多张表或附件，优先抽取正文和评论中明确指向行动项的部分，不对附件内容做无限扩写。

### Step 2｜候选 To-Do 识别

只把满足以下至少 2 条的内容放入候选池：

1. 出现明确行动动词或推进语气：如“需要 / 请 / 辛苦 / 给一下 / 看下 / 补充 / 对齐 / 安排 / 确认 / 推进 / 提供 / 输出 / 跟进 / 评估”。
2. 有明确责任方：人名、角色、团队、双方或相关负责人。
3. 有时间约束：明确 DDL、阶段节点、日期或“下周 / 本月底 / 会前”等可锚定窗口。
4. 即使没写死日期，但对主线目标、GMV、跨团队承诺有显著影响。
5. 评论中明确要求补材料、补解释、补 case、补链接，也要纳入。

### Step 3｜候选过滤

以下内容必须剔除：

- 纯背景描述、问题陈述、结论复述。
- 已明确标注“已解决 / 已完成 / 已同步”的事项。
- 没有责任方、没有行动方向、也没有业务影响的闲聊型表述。
- 只是在正文中描述现状、但未形成下一步动作的内容。

### Step 4｜字段标准化

对每一条待办补齐以下字段：

- **Owner**：优先保留真实姓名；若原文只有邮箱或 @ 提及，必须回捞真实姓名；查不到则写“待确认”，禁止直接留邮箱。
- **DDL**：只保留明确时间点；无法锚定则写“待确认”。
- **事项描述**：改写成一句可执行、可跟进的话，不丢失原始意图。
- **来源**：记录原文来源文档；多篇文档重叠主线可写“文档A / 文档B”或“合并”。
- **priority_reason**：简述为何被定为 P0/P1/P2，便于后续校准。

### Step 5｜P0 / P1 / P2 打标规则

#### P0
命中任一条即可：
- 直接阻塞主线目标、关键 GMV 目标或跨团队承诺。
- 原文存在明确 DDL / 会前节点 / 本周必须完成。
- 不做会直接影响主线节奏、预算承诺、合作推进。

#### P1
满足以下特征：
- 有明确行动项，且对业务有显著影响。
- 暂不阻塞主线，但属于近期待推进事项。
- DDL 待确认，或虽重要但可在短期内排期推进。

#### P2
满足以下特征：
- 补充信息、背景调研、case 收集、样例补全。
- nice-to-have，可延后但不能丢。
- 对主线的影响较间接，适合作为留档追踪项。

### Step 6｜结构化输出

默认输出为项目管理版飞书文档，推荐表头：

<table header-row="true" col-widths="140,100,90,360,180,220">
  <tr>
    <td>**Owner**</td>
    <td>**DDL**</td>
    <td>**优先级**</td>
    <td>**事项描述**</td>
    <td>**来源**</td>
    <td>**优先级依据**</td>
  </tr>
  <tr>
    <td>于奇楠</td>
    <td>2026-06-20</td>
    <td>**P0**</td>
    <td>补充 UK 经营模型关键指标并同步跨团队共识</td>
    <td>chicme / OQQ</td>
    <td>阻塞目标拆解，且会前需对齐</td>
  </tr>
</table>

写入飞书前，先在本地生成 `.lark.md`，再通过 `feishu-doc-writing-guide` 规范链路创建文档。

### Step 7｜人工校准 diff

当用户提供人工校准后的优先级说明时：

1. 不要直接覆盖原结果。
2. 先把原始清单与校准结果做任务级匹配。
3. 输出 `old_priority → new_priority` 的变更表，并补一句变更原因。
4. 只有 diff 输出完成后，才允许生成“校准后版本”。
5. 可调用 `scripts/priority_diff.py` 生成 markdown 或 JSON diff。

### Step 8｜接入 task-flow-engine 的自动升级规则

- 本技能只负责产出结构化任务条目，不直接做台账巡检。
- 输出给 `task-flow-engine` 时，保留 `priority`、`ddl`、`owner`、`source_doc`。
- 自动升级规则（供下游执行）：**DDL ≤ 3 天且状态未完成的 P1 自动升级为 P0，并触发催办提醒。**
- 若当前没有状态字段，则在输出中明确提示：下游接入前需补 `status` 字段。

## Owner 真实姓名治理规则

- 优先采用正文中的中文姓名。
- 文档评论里若出现 `@邮箱` 或 open_id，应通过飞书用户信息回捞真实姓名。
- 若只能拿到角色名（如“业务侧”“物流侧”），允许保留角色名。
- **禁止**把 `xxx@bytedance.com` 直接写进最终 Owner 列。
- 查不到真实姓名时写 `待确认`，并在备注中说明“原文仅出现邮箱 / 模糊指代”。

## 合规默认值（Defaults）

- `DEFAULT_OUTPUT_MODE = doc_only`
- `DEFAULT_DDL_PLACEHOLDER = 待确认`
- `DEFAULT_OWNER_PLACEHOLDER = 待确认`
- `DEFAULT_PRIORITY_ORDER = P0 > P1 > P2`
- `DEFAULT_DOC_SCOPE = 只处理 wiki/docx`
- `DEFAULT_INCLUDE_COMMENTS = True`
- `DEFAULT_ALLOW_ROLE_OWNER = True`
- `DEFAULT_ESCALATION_RULE = DDL ≤ 3 天未完成的 P1 → P0`

## 失败熔断策略

- **链接非法**：直接报错，要求用户提供飞书 Wiki/Docx 链接。
- **文档下载失败**：说明哪一篇失败，不要对其内容做猜测。
- **Owner 无法解析**：写 `待确认` 并显式标记原因；禁止用邮箱占位。
- **DDL 无法锚定**：写 `待确认`，不要脑补具体日期。
- **多条任务高度重复**：先合并主线，再在来源列保留多文档引用。
- **校准说明过于模糊**：保留原优先级，并把需人工确认的条目标记出来。
- **飞书写入失败**：返回本地 `.lark.md` / JSON 成果，并明确说明未完成云端落盘。

## 推荐脚本

- [scripts/todo_priority_guard.py](scripts/todo_priority_guard.py)
  - 校验输入链接是否合法
  - 校验输出行字段是否完整
  - 根据规则对单条待办做优先级建议
- [scripts/priority_diff.py](scripts/priority_diff.py)
  - 对原始优先级与人工校准结果生成 diff
  - 输出 markdown / json 两种格式

## References

- 详细抽取口径与边界示例：见 [references/extraction-playbook.md](references/extraction-playbook.md)
- 人工校准与 task-flow-engine 对接约定：见 [references/calibration-handoff.md](references/calibration-handoff.md)

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：
  ```text
  把这两篇拜访记录里的 To-Do 提出来，按 P0/P1/P2 排好；我后面会手动改几条优先级，再帮我出 diff。
  ```
- 🤖 标准输出：
  ```text
  1. 下载两篇飞书文档，连同评论区一起抽取候选待办。
  2. 过滤掉背景描述和已解决事项，只保留有 Owner / 动作 / 时间约束或业务影响的任务。
  3. 输出 Owner / DDL / 优先级 / 事项描述 / 来源 / 优先级依据 的项目管理版清单。
  4. 若收到人工校准说明，再输出 old_priority → new_priority 的 diff，并给出变更原因。
  5. 如需接 task-flow-engine，下游按“DDL ≤ 3 天未完成的 P1 自动升级为 P0”执行巡检。
  ```
