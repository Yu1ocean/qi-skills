---
name: feishu-doc-writing-guide
description: 飞书电子表格（Sheets）与文档（Docs）的安全写入与归属治理指南，包含执行人身份穿透法则、个人空间优先创建、MCP 迁移兜底、三级防爆破自检机制、反合理化四件套、公式与多选单元格结构化写入护栏、标题去重、元数据标头及幽灵对象清除 SOP。适用于生成/更新飞书文档、写入台账、写入多选/公式单元格、处理权限与数据安全。
version: 7.5
---

# 飞书文档写入权威指南 (feishu-doc-writing-guide) v7.5

本 Skill 汇总了 Aime 系统及团队在处理飞书文档与电子表格时的血泪经验，规定了写入、更新及维护操作的权威标准。

**v7.5 关键升级：新增「多选单元格结构化写入护栏」。** 飞书多选（Multi-Select）单元格的值本质是**选项数组**而非字符串，用逗号串（如 `"EU,UK,JP"`）经 `+csv-put` 或 `value` 文本通道写入，会被引擎当作**一个整体文本**去匹配选项列表，导致药丸（Pill/Tag）不渲染并触发右上角红色校验失败角标。从本版本起，多选列写入必须走 `+cells-set` 的 `multiple_values` 结构化数组，写后必须 `+cells-get --include value,multiple_values` 回读断言，并可用 `scripts/multiselect_write_guard.py` 做 L3 运行时熔断预检。详见「陷阱6」。

**v7.3 关键升级：新增「个人空间优先创建法则」并废弃 JWT 直调 Permission API。** 从本版本起，创建飞书文档时必须默认 `target_type=personal`，让文档直接落到用户个人空间；若因历史路径或工具默认值导致资产仍停留在系统云盘，必须立刻通过 MCP `move_lark_doc` 迁移到 `personal`。`scripts/grant_doc_permissions.py` 保留为兼容入口，但底层已不再使用 `AIME_USER_CLOUD_JWT` 直调 Drive Permission API，而是改为转发到 MCP 迁移链路，彻底规避 `code=99991668` 一类鉴权错位问题。

## 📌 技能简介

适用于以下场景：
- 生成新的飞书文档，并要求用户天然具备可管理权限。
- 更新已有飞书文档或电子表格，并要求严格遵守 MCP-only、安全写入与写后回读规范。
- 修复“文档已创建成功，但用户无法管理/移动/继续编辑”的归属错位问题。

## 🔑 触发词

- 核心关键词：
  - 飞书文档创建
  - 飞书表格写入
  - 个人空间
  - move_lark_doc
  - 幽灵块
- 典型指令示例：
  > 生成一份飞书文档并写入报告，确保直接落到我的个人空间
  > 修复这个飞书文档创建后无法管理的问题

## 何时使用

1. **表格写入**：向项目台账、灵感台账、文档库（Sheets）等追加、插入单条记录或批量更新时。
2. **文档生成**：使用 `mcp:lark_create_lark_doc` 或内置 `lark` 能力生成报告、复盘、设计稿（Docs）时。
3. **归属修复**：文档/表格创建成功，但用户无法编辑、移动、分享或管理时。
4. **安全自检**：重要台账更新前，执行三级防御体系，防止数据污染或结构损毁。
5. **幽灵清除**：文档中出现“看得见删不掉”或由于上下文溢出导致的空 Block 对象时。

## Common Rationalizations（AI 常见的偷懒借口）

以下话术一旦出现，几乎等价于“准备越过红线”：

- “先按默认参数创建，回头再补权限。”
- “MCP 创建已经成功了，我就顺手拿 JWT 直接调一下 Permission API。”
- “反正 `grant_doc_permissions.py` 能跑，我就不管底层是不是 Drive OpenAPI 了。”
- “先把文档留在系统云盘，等用户来报错时再迁移到个人空间。”
- “表格写入量不大，我就不做 Schema 校验和 RAW 回读了。”
- “幽灵块先不处理，反正文档还能打开。”
- “多选列我先用逗号串灌一版，能显示就行。”
- “单值那格（只写 `EU`）没报错，多值应该也没事。”

这些借口本质上都在尝试绕过：**MCP 权威通道、个人空间优先创建、MCP 迁移兜底、三级防爆破、写后即读 RAW 原子锁、反影子克隆定律、幽灵块物理斩除、多选单元格结构化写入**。

## Why they fail（为什么这些借口是致命的）

- **JWT ≠ 飞书标准 Access Token**：`AIME_USER_CLOUD_JWT` 是字节云身份凭证，不是 Drive Permission API 预期的标准飞书访问令牌。直接拿它调 OpenAPI，极易触发 `code=99991668` 或同类鉴权错误。
- **系统云盘落点错位 = 管理权错位**：文档创建在系统空间，即使用户能看到，也可能无法移动、赋权、继续维护；后续任何自动化链路都可能被权限墙卡死。
- **绕开 MCP = 失去宿主权限继承**：非 MCP 通道常导致权限视野不一致，最终出现“我创建成功了，但你管不了”的权限灾难。
- **不做全列对齐/不拉 Schema = 主键与合同破裂**：主键缺失、列错位、部分字段写入，会直接触发重复数据、幂等性失效，甚至导致整表公式列崩坏。
- **忽略幽灵块 = 文档结构腐烂**：空 Block/不可见对象会在后续更新中变成“无法定位、无法修复”的结构性错误；必须按信标→定位→物理斩除处理。
- **逗号串 ≠ 选项数组**：飞书多选单元格存的是**选项对象数组**，引擎按「整串文本」去匹配选项列表。`"EU,UK,JP"` 会被当成一个名叫 `EU,UK,JP` 的选项去查表，选项列表里必然没有这一项 → 判定「不在选项列表内」→ 必然触发数据校验失败角标且不渲染药丸。更阴险的是单值（`"EU"`）恰好能命中选项，于是“偶发正常”，让人误判为已修复。

## Red Flags（危险信号）

出现任意一条，即判定为“高风险偷懒”，必须立刻切回本 Skill 的 SOP：

- 调用 `mcp_lark_create_lark_doc` 时没有显式传 `target_type=personal`。
- 文档创建成功后，仍然试图使用 `requests` / Drive Permission API / `AIME_USER_CLOUD_JWT` 去补 `full_access`。
- 声称“已修复权限”，但没有 `move_lark_doc -> personal` 或 `ensure_doc_in_personal.py` 的执行日志。
- 表格写入动作没有展示 **写入参数**（sheet_url、sheet_name、row_index、data_json）或 **读回原始数组**。
- 遇到 404/无权限后没有熔断告警，却继续“新建/复制/换 token”完成任务。
- 提到“修复”但没有给出 **幽灵块信标**（如 `GHOST_TARGET_001`）与对应 block 定位证据。
- 向飞书 Sheet 多选（Multi-Select）单元格写入时，使用逗号串文本（如 `"EU,UK,JP"`）经 `+csv-put` 或普通 `value` 文本通道写入，而非 `+cells-set` 的 `multiple_values` 结构化数组。

## Verification（强制物理验证与核对清单）

把以下清单视为“不可跳过的物理验收”。只要任务涉及写入/更新/创建，必须逐项满足：

1. **通道验证（MCP 优先）**
   - 表格/文档操作优先走 MCP（`lark` / `lark_sheets_update` 等）。
   - 任何理由无法走 MCP：必须停止并输出致命错误（不得自行兜底）。

2. **执行人身份验证（bytedcli-auth）**
   - 进入飞书读写前，优先完成 `bytedcli-auth` 挂载与用户身份校验。
   - `bytedcli-auth` 失败时必须熔断，不得降级为 Bot/OpenAPI 直调。

3. **创建默认落个人空间（Personal-First）**
   - 调用 `mcp_lark_create_lark_doc` 时，必须显式传入 `target_type=personal`。
   - 如果是迁移已有文档，也必须优先使用 `mcp_lark_move_lark_doc` 到 `personal`。

4. **归属兜底（Move to Personal）**
   - 新建文档若未直接落到用户空间，必须立刻执行 `scripts/ensure_doc_in_personal.py "<document_url>"`。
   - `scripts/grant_doc_permissions.py` 仅允许作为兼容包装器存在，不再允许直调 Permission API。

5. **Schema 合同验证（全列对齐）**
   - 写入前拉取并确认表头 Schema。
   - 行数据必须全列对齐，尤其包含主键列/编号列时必须填充且唯一。

6. **RAW 原子锁（写→等→读）**
   - 写入后等待至少 2 秒。
   - 读回刚写区域，并用代码块原样输出读回数组（例如 `[[A1, B1, C1]]`），逐字段核对。
   - 任意不一致：立刻熔断，禁止继续自动化。

7. **反影子克隆熔断**
   - 遇到 404/无权限：必须熔断告警。
   - 允许的极端降级只有：写入本地 DLQ（JSON/CSV）并显式标注 `[DLQ-待合并]`。

8. **幽灵块验收**
   - 必须“植入信标→定位父 block→物理斩除”。
   - 删除后再次下载/读取文档，确认信标已消失且结构可持续更新。

9. **公式零错误收敛（Formula Zero-Error）**
   - 任何写入/修改公式的动作完成后，必须执行 `lark-cli sheets +formula-verify --url "<sheet_url>"`。
   - 必须收敛到 `status=success` 且 `total_errors=0`；存在任一 `#VALUE!` / `#REF!` / `#NAME?` 即视为未完成，立刻熔断修复。
   - 同时用 `+cells-get --include value,formula` 回读目标单元格，确认存在 `formula` 字段（防伪公式文本）。
   - 可用本地断言脚本预检：`python3 scripts/formula_write_guard.py --formula "=INDEX('明细'!J:J,COUNTA('明细'!J:J))" --sheet-names '明细,US行业统计' --field formula`

10. **多选单元格结构化写入收敛（Multi-Select Structured Write）**
   - 任何写入多选（Multi-Select）列的动作，必须走 `+cells-set` 的 `multiple_values` 结构化数组，禁止 `value` 逗号串与 `+csv-put`。
   - 写后必须回读断言：`lark-cli sheets +cells-get --url "<sheet_url>" --range "<Sheet名>!G2" --include value,multiple_values`。
   - 断言口径：`multiple_values` 数组必须存在，长度与预期标签数一致，且每个 `value` 命中选项列表；只有 `value` 字符串而无 `multiple_values` 数组即判定为逗号串污染，立刻熔断重写。
   - 可用本地断言脚本预检：`python3 scripts/multiselect_write_guard.py --values "EU,UK,JP" --field multiple_values --allowed-options "EU,UK,JP,US,SEA"`

## ⚙️ 核心架构 / SOP / 约束条件

### 0. 执行人身份穿透法则 (Identity Auth Penetration)

- 机器人（Bot）或系统账号默认以“应用身份”调用飞书 OpenAPI/MCP。对于未公开或未向该应用授予编辑权限的文档/表格，这种身份会被 403 拦截，表象可能是“文档不存在”或“不可编辑”，本质是执行人身份错位。
- 为了实现零阻力、零惊喜的写入路径，所有飞书读写任务在进入表格/文档操作前，必须**优先在前置步骤挂载 `bytedcli-auth` Skill**，利用当前用户的云端 JWT 凭证完成 `bytedcli login` / `userinfo` 校验。
- 随后所有 MCP 通道（如 `lark`、`lark_sheets_update`、`mcp:lark_create_lark_doc`、`mcp:lark_move_lark_doc` 等）的调用，都应基于该用户级 JWT，让“执行人”从 Bot 身份下沉为真实用户身份，使权限视野与用户本人 1:1 对齐。
- 若 `bytedcli-auth` 失败（如 JWT 过期、403 等），必须熔断并提示用户处理，不得降级为匿名/Bot 身份继续写入。

### 0.1 个人空间优先创建法则 (Personal-First Creation)

- 只要是在本任务中**新建**飞书文档，默认就应该这样调用：

```bash
python3 inner_skills/lark/mcp_lark_create_lark_doc.py '{"file_path":"/abs/path/report.lark.md","title":"报告标题","target_type":"personal"}'
```

- 这一步不是“可选优化”，而是默认创建合同。缺失 `target_type=personal` 就视为流程不合格。
- 若是历史遗留文档，或创建后仍落在系统空间，必须立刻迁移到个人空间：

```bash
python3 scripts/ensure_doc_in_personal.py "<document_url>"
```

- 如需直接调用 MCP 原生脚本，可使用：

```bash
python3 inner_skills/lark/mcp_lark_move_lark_doc.py '{"document_urls":["<document_url>"],"target_type":"personal"}'
```

- `scripts/grant_doc_permissions.py` 仍保留同名入口，是为了兼容旧调用方；但它已经不再调用 Permission API，而是转发到 `ensure_doc_in_personal.py`。任何继续把它当成“JWT 赋权脚本”使用的行为，都属于错误认知。

### 1. 飞书表格三级防爆破与自检机制 (Lark Sheets 3-Level Defense System)

在对重要飞书台账进行任何写入操作时，必须严格执行以下三级防御体系。

#### 【核心红线】禁止暴力兜底与增强约束 (Anti-Destruction & Strict Constraints)

- **剥夺“Delete Sheet”权限**：在执行行级别的修正或插入任务时，绝对禁止调用删除工作表操作。遇到无法对齐等报错时，必须终止任务并拉响警报，严禁物理兜底。
- **强制全列对齐 (Full-Column Schema Contract)**：向飞书表格写入时，必须提供完整的行数据，尤其是当首列（或关键列）包含【主键/编号】时。
- **主键强制填充与唯一性约束**：每次插入行前必须先拉取表头 Schema，如果包含编号列，系统必须自动生成并补齐全局唯一的主键（如 `LOG_260417_000X`）。
- **强制幂等性锁 (Idempotency Anti-Duplication)**：写入前必须全表检索是否存在相同主键或内容的数据，若存在则更新或阻断，严防重复插入。
- **质检结果原貌输出**：执行 Read-After-Write 探针回捞等质检时，必须使用 Code Block 原汁原味输出诸如 `[ [A1, B1, C1] ]` 的原始数组结构。

#### 第一级：全面拥抱 MCP 通道 (MCP Authority Level)

- **强制首选 MCP 工具**：表格写入优先使用系统内置 MCP 工具（如 `lark_sheets_update`、`lark`）。
- **原生穿透**：MCP 作为宿主原生客户端运行，天然继承用户视野权限。

#### 第二级：模型层 RAW 原子锁 (Model-Level Read-After-Write)

- 将“写后即读”的校验上浮到 Prompt 流程控制层（由特工自主执行）。
- 特工强制三步走 SOP：
  1. **写**：调用 `lark_sheets_update` 等工具执行精准数据写入。
  2. **等**：等待至少 2 秒。
  3. **读**：将刚写的区域读回，自主核对校验，若不一致立即拉响警报。

#### 第三级：人工熔断与快照 (Audit Level)

- **本地快照备份**：写入前建议保存目标 Sheet 的本地 JSON/CSV 快照。
- **Diff 报告确认**：对于重要操作，生成数据变动 Diff 报告供审核。
- **自动熔断**：当 RAW 原子锁校验失败或 Diff 范围异常时，立即停止后续自动化。

### 1.5 高可用自愈协议 (Self-Healing Protocol) 与 反影子克隆定律

在面对系统级异常（如跨域 404、无权限或网络熔断）时，绝对禁止大模型产生“过度主观能动性”去随意克隆影子台账。

1. **剥夺新建兜底权**：遇到明确指定的 `Target_Token` 报 404 或无权限时，必须抛出致命错误并告警，要求人类介入。
2. **降级创建（极端情况）**：优先写入本地死信队列（DLQ）JSON/CSV；如必须云端兜底，强制命名为 `[DLQ-待合并] ...` 并写 A1 红色警告。
3. **显式告警**：触发降级必须明确告警并解释风险。
4. **异步闭环与阅后即焚**：主表恢复后自动合并，合并成功后物理删除临时表。

### 2. 飞书表格格式保持规范 (Lark Sheets Format Maintenance)

- **插入位置**：追加记录推荐设为第 2 行（表头正下方），以确保最新记录（倒序）始终位于首屏。
- **超链接格式**：写入文档链接等字段时，必须使用 `HYPERLINK` 公式：`=HYPERLINK("网址", "标题")`。

### 3. 飞书文档创建与编号强制锁死 SOP (Doc Creation & ID Allocation Guard)

触发新建飞书文档、生成复盘报告等任务时，执行“三步物理锁死”工作流：

1. **前置拿号 (ID Allocation)**：先向主台账申请全局业务流水号（如 `DOC-2604-XXX`）。
2. **规范盖章 (Header Injection)**：文档正文顶端必须包含元数据引用块，并避免正文再用 `# 标题`（H1）。
3. **台账落盘 (Registry Sync)**：文档盖章完成后，将 `[Global ID] + [文档名称] + URL` 以 `HYPERLINK` 公式写入主台账，完成资产闭环。

### 4. “幻觉对象”终极除虫指南 (Ghost Object Eradication)

遇到不可见/空 Block 错误时：

1. **植入信标**：在异常区域输入信标 `GHOST_TARGET_001`。
2. **定位 ID**：读取文档，定位信标所在的父级 Block ID。
3. **物理斩除**：调用更新接口置空该 Block 内容。

### 陷阱1：飞书跨 Sheet COUNTIFS + `"<>"` 非空条件失效

- **现象**：在 COUNTIFS 的第三个条件中使用 `"<>"` 判断非空，跨 Sheet 场景下返回异常大数（如 207、82），而非真实非空行数。
- **根因**：飞书电子表格跨 Sheet 引用时，`COUNTIFS(..., range, "<>")` 可能无法正确识别空单元格，属于已知兼容性缺陷。
- **正确做法（反向计法）**：
  ```
  = COUNTIFS(基础条件) - COUNTIFS(基础条件, 目标列, "")
  ```
  即：用"总数 - 空单元格数"替代直接非空判断。
- **验证方式**：写入后必须回捞，确认合计值与底表实际非空行数一致。

### 陷阱2：隐藏列导致 MCP 列位偏移

- **现象**：MCP 工具跳过隐藏列计数，导致 MCP 视角下的列字母与飞书引擎实际列字母不同，写入公式时引用到错误的列。
- **根因**：飞书底表存在隐藏列（如 M/N/O/P、AW/AX/AY/AZ），MCP 按可见列编号，而飞书公式引擎按全量列编号。
- **正确做法**：写公式前，先在目标 Sheet 某空格写一个临时 `=COUNTA('底表'!$XX$5:$XX$6379)` 验证公式是否引用正确；或通过用户提供的已知可执行公式反推正确列字母（如用户提供 U3 公式确认跨 Sheet 引用语法）。
- **禁止行为**：不能仅凭 MCP 返回的列号盲目拼接公式，必须先验证列位。

### 陷阱3：sheet_id 冒充 sheet_name 导致跨 Sheet 公式失效

- **现象**：`=MAX('VM2reD'!J:J)` 写入后公式无效 / 报错 / 恒为 0，其中 `VM2reD` 实际是「明细」Sheet 的 `sheet_id`。
- **根因**：飞书公式引擎只识别 **sheet_name**（如 `'明细'`），不接受 `sheet_id`。MCP/CLI 返回的 `sheet_id` 只能用于 API 定位，不能进入公式文本。
- **正确做法**：写任何跨 Sheet 公式前，先取真实名称：

  ```bash
  lark-cli sheets +workbook-info --url "<sheet_url>"   # 读取 sheet_name
  ```

  再用 `'明细'` 这类 sheet_name 拼公式：`=INDEX('明细'!J:J,COUNTA('明细'!J:J))`。
- **诊断命令**：`lark-cli sheets +workbook-info` 对照公式中的引用名；若引用串出现在 sheet_id 列表中即判定为误用。
- **禁止行为**：严禁把 MCP/CLI 返回的 `sheet_id` 直接拼进公式；严禁凭记忆猜 Sheet 名。

### 陷阱4：伪公式文本引发级联 #VALUE!

- **现象**：N2 看似公式，实际是文本字符串 `"=MAX('VM2reD'!J:J)"`；下游 `=N2-1` 对文本做算术，报 `#VALUE!`，并沿依赖链级联扩散。
- **根因**：写入时用了 `value` 字段（或 `+csv-put`），飞书按纯文本存储，不进公式引擎。
- **诊断命令**：

  ```bash
  lark-cli sheets +cells-get --url "<sheet_url>" --range "US行业统计!N2" --include value,formula
  ```

  **有 `value` 无 `formula` 字段 = 伪公式文本**，必须重写。
- **正确做法**：公式必须走 formula 字段写入：

  ```bash
  lark-cli sheets +cells-set --url "<sheet_url>" --range "US行业统计!N2" \
    --cells '[[{"formula":"=INDEX(\u0027明细\u0027!J:J,COUNTA(\u0027明细\u0027!J:J))"}]]'
  ```
- **禁止行为**：禁止用 `value` 字段写公式；禁止用 `+csv-put` 批量灌公式；禁止只看单元格显示文本就断定公式生效。

### 陷阱5：文本型日期列不可 MAX

- **现象**：对「更新日期」列取最新值用 `=MAX('明细'!J:J)`，结果恒为 `0`。
- **根因**：该列是文本型日期（如 `"8/14"`），并非日期序列值；`MAX` 忽略文本，返回 0。
- **正确做法**：取“最后一条有效值”而非最大值：

  ```
  =INDEX('明细'!J:J,COUNTA('明细'!J:J))
  ```
- **诊断命令**：`+cells-get --include value,formula` 观察目标列样本是否为纯字符串；或临时写 `=ISTEXT('明细'!J2)` 判定类型。
- **禁止行为**：禁止在未确认列类型前对日期列使用 MAX/MIN 聚合并直接对外交付结果。

### 陷阱6：多选单元格逗号串写入导致药丸不渲染 + 红色校验角标

- **现象**：向多选列（如「覆盖区域」G 列）写入 `"EU,UK,JP"` 后，单元格不渲染多选药丸（Pill/Tag），右上角出现红色校验失败角标；而单值场景（如只写 `"EU"`）恰好命中选项时不报错，造成「偶发正常」的假象，极易误判为已修复。
- **根因**：飞书多选单元格的值是**选项数组**，不是字符串。逗号串会被引擎当作**一个整体文本**去匹配选项列表，多值时匹配失败 → 判定为「不在选项列表内」→ 触发数据校验失败角标且不渲染药丸。
- **正确做法**：使用 `+cells-set` 的 `multiple_values` 字段，以结构化数组写入：

  ```bash
  lark-cli sheets +cells-set --url "<sheet_url>" --range "<Sheet名>!G2" \
    --cells '[[{"multiple_values":[{"value":"EU"},{"value":"UK"},{"value":"JP"}]}]]'
  ```

- **诊断命令**：

  ```bash
  lark-cli sheets +cells-get --url "<sheet_url>" --range "<Sheet名>!G2" --include value,multiple_values
  ```

  回读若只有 `value` 字符串、没有 `multiple_values` 数组，即判定为逗号串污染，必须重写。
- **写后验收**：写完必须回读断言 `multiple_values` 数组长度与预期标签数一致，且每个 `value` 命中选项列表；不一致立刻熔断。
- **前置断言（L3 熔断）**：写入前先跑本地护栏脚本，违规直接非 0 退出：

  ```bash
  python3 scripts/multiselect_write_guard.py --values "EU,UK,JP" --field multiple_values --allowed-options "EU,UK,JP,US,SEA"
  ```

- **禁止行为**：禁止用 `+csv-put` 批量灌多选列；禁止用 `value` 纯文本字段写多选单元格；禁止因「单值写成功」就推断多值也没问题。

## Defaults（合规默认值）

- 新建飞书文档默认：`target_type=personal`
- 归属修复默认：`scripts/ensure_doc_in_personal.py "<document_url>"`
- 兼容入口默认用户：`yuqinan@bytedance.com`
- 写后即读 RAW 校验：默认开启
- 公式写入通道默认：`+cells-set --cells '[[{"formula":"=..."}]]'`（禁用 `value` / `+csv-put`）
- 公式写后校验默认：`lark-cli sheets +formula-verify` 必须 `total_errors=0`
- 取“最新日期值”默认公式：`=INDEX('<sheet_name>'!J:J,COUNTA('<sheet_name>'!J:J))`
- 多选列写入通道默认：`+cells-set --cells '[[{"multiple_values":[...]}]]'`（禁用 `value` / `+csv-put`）
- 多选写后校验默认：`+cells-get --include value,multiple_values`，`multiple_values` 数组长度必须等于预期标签数

## 脚本工具箱（可选，但遇到对应场景必须用）

- **迁移文档到个人空间（推荐主入口）**：

  ```bash
  python3 scripts/ensure_doc_in_personal.py "<document_url>"
  ```

- **兼容旧入口（已废弃 JWT 直调，仅做 MCP 转发）**：

  ```bash
  python3 scripts/grant_doc_permissions.py "<document_url>"
  ```

- **表格安全 upsert 单行**：

  ```bash
  python3 scripts/safe_insert_sheet_row.py "<sheet_url>" "<sheet_name>" <row_index> '<data_json>'
  ```

- **写前快照 / 写后 diff**：

  ```bash
  python3 scripts/snapshot_diff_helper.py snapshot "<sheet_url>" "<sheet_name>" [snapshot_file]
  python3 scripts/snapshot_diff_helper.py diff "<sheet_url>" "<sheet_name>" [snapshot_file]
  ```

- **公式写入前置断言（L3 熔断）**：

  ```bash
  python3 scripts/formula_write_guard.py --formula "=INDEX('明细'!J:J,COUNTA('明细'!J:J))" --sheet-names '明细,US行业统计' --field formula
  ```

- **多选单元格写入前置断言（L3 熔断）**：

  ```bash
  # 正例：标签数组 + 选项白名单校验，通过后打印可直接复制的 cells payload
  python3 scripts/multiselect_write_guard.py --values "EU,UK,JP" --field multiple_values --allowed-options "EU,UK,JP,US,SEA"

  # 也可直接体检既有 cells payload（逗号串污染 / 缺失 multiple_values 会熔断）
  python3 scripts/multiselect_write_guard.py --cells-json '[[{"multiple_values":[{"value":"EU"},{"value":"UK"}]}]]'
  ```

- **清理幽灵 Block**：

  ```bash
  python3 scripts/delete_ghost_block.py "<document_url>" "<markdown_file_path>" "GHOST_TARGET_001"
  ```

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：
  ```text
  生成一份飞书文档并写入报告，解决创建后自动赋权失败的问题
  ```
- 🤖 标准输出：
  ```text
  1. 先执行 bytedcli-auth，确保后续 MCP 写入以用户身份运行。
  2. 创建文档时显式传 target_type=personal，让文档直接落到用户个人空间。
  3. 若文档为历史资产或落点异常，立即执行 scripts/ensure_doc_in_personal.py 做 MCP 迁移。
  4. 禁止再用 AIME_USER_CLOUD_JWT 直调 Drive Permission API。
  ```

## 变更记录

- **v7.5**: 新增多选单元格结构化写入护栏。
  - 新增「陷阱6：多选单元格逗号串写入导致药丸不渲染 + 红色校验角标」，明确飞书多选值是**选项数组**而非字符串，逗号串会被当作整串文本匹配选项列表而必然校验失败。
  - 多选列写入通道锁定为 `+cells-set --cells '[[{"multiple_values":[{"value":"EU"},...]}]]'`，禁用 `value` 纯文本与 `+csv-put` 批量灌列。
  - 诊断法固化为 `+cells-get --include value,multiple_values`：只有 `value` 字符串而无 `multiple_values` 数组即判定为逗号串污染。
  - Verification 新增第 10 条「多选单元格结构化写入收敛」：写后必须回读断言数组长度与选项命中。
  - Red Flags / Common Rationalizations / Why they fail 同步新增「逗号串写多选」「单值没报错就推断多值也行」的反合理化条款。
  - 新增 L3 断言脚本 `scripts/multiselect_write_guard.py`，对逗号串污染、`multiple_values` 结构缺失、选项越界三类违规运行时熔断。
- **v7.4**: 新增公式类三大陷阱与零错误收敛护栏。
  - 新增「陷阱3：sheet_id 冒充 sheet_name 导致跨 Sheet 公式失效」，规定写公式前必须 `lark-cli sheets +workbook-info` 拿 `sheet_name`。
  - 新增「陷阱4：伪公式文本引发级联 #VALUE!」，明确 `+cells-get --include value,formula` 诊断法（有 value 无 formula 即伪公式），公式必须走 `+cells-set --cells '[[{"formula":"=..."}]]'`。
  - 新增「陷阱5：文本型日期列不可 MAX」，取最新值改用 `=INDEX(列,COUNTA(列))`。
  - Verification 新增第 9 条「公式零错误收敛」：写公式后必须 `+formula-verify` 收敛到 status=success / total_errors=0。
  - 新增 L3 断言脚本 `scripts/formula_write_guard.py`，对 sheet_id 误用、value 字段写公式、文本列 MAX 三类违规运行时熔断。
- **v7.3**: 新增「个人空间优先创建法则」，默认以 `target_type=personal` 创建飞书文档；新增 `scripts/ensure_doc_in_personal.py` 作为 MCP 迁移兜底；废弃 `grant_doc_permissions.py` 的 JWT 直调 Permission API 方案，并将同名脚本降级为兼容包装器。
- **v7.2**: 新增「执行人身份穿透法则」，明确要求在所有飞书文档/表格读写前优先挂载 `bytedcli-auth`，以用户云端 JWT 作为执行人身份，通过 MCP 通道配合本 Skill 实现“无感物理级穿透写入”。
- **v7.1**: 新增「反合理化四件套」（Common Rationalizations / Why they fail / Red Flags / Verification），用以对抗“先跳过校验/先不落用户空间/先复制一份台账/先糊一个结果”等偷懒冲动，并明确与三级防爆破、反影子克隆、幽灵块清理、归属治理等红线的联动校验。
- **v7.0**: 引入 `scripts/grant_doc_permissions.py` 作为历史兼容方案；该方案现已废弃，不再作为标准路径。
- **v6.0**: MCP 化改造，将 RAW 锁上浮至模型层流程控制。
- **v5.0**: 强制高权限通道、RAW 原子锁（写后即读 2s）。
- **v4.0**: 强化影子表预演与快照对比机制。

## 调用约束

- 表格写入优先使用 MCP 类型能力（如 `lark`、`lark_sheets_update`）。
- 文档创建默认必须显式传 `target_type=personal`。
- 历史文档归属修复必须使用 `move_lark_doc -> personal` 链路，不得再使用 Drive Permission API 直调兜底。
- 台账写入遵循三级防线 + RAW 原子锁（写后即读）。
- 多选（Multi-Select）列写入必须走 `+cells-set` 的 `multiple_values` 结构化数组，并以 `+cells-get --include value,multiple_values` 回读断言。
- 涉及飞书脚本或 MCP 操作时，必须设置 `include_secrets=true`。
