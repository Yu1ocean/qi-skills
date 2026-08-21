# 【技能说明】飞书文档写入指南

<figure view-type="Card"><source name="feishu-doc-writing-guide.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ODc5OWM5MzJhNmNiNmQ3ODVlYjkxZmM4MjVkMTdlNThfZjJmZDQzZTVhMmRmYzUzNzRlYjM0NzA0YmNhZDYwNjNfSUQ6NzY3NjQ1NzEzMDQ3MTI0NzA2N18xNzg3MzE0NDU4OjE3ODczMTgwNThfVjM" mime="application/zip" size="1865315" token="Rhjubyvw1oaLFJxaPYRcV2sDnBg"/></figure>

> 📄 **文档编号**：[SYS-2604-003] 📅 **归档日期**：[2026-04-07] 🏷️ **当前版本**：v7.5 🔄 **最近更新**：[2026-08-21]

---

## 一、 引言

本指南（feishu-doc-writing-guide）汇总了 Aime 系统在处理飞书文档与电子表格时的核心经验，规定了写入、更新及维护操作的绝对权威标准。遵循本指南可有效防止数据覆盖、格式擦除及文档“幻觉对象”导致的系统异常。

## 二、 核心规则与 SOP

### 1. 飞书表格安全插入规范 (Lark Sheets Safety Insertion)

为防止意外擦除历史格式（如 `HYPERLINK` 公式）或覆盖已有数据，严禁对台账类文档采用“全量覆盖”模式。

- **操作要求**：必须调用专用脚本 `scripts/safe_insert_sheet_row.py` 进行单行精准插入。
- **插入位置**：默认位置为第 2 行（表头正下方），确保最新记录始终位于首屏。
- **格式保持**：在写入文档链接等字段时，**必须强制使用 `HYPERLINK` 公式**，格式如：`=HYPERLINK("网址", "标题")`。

### 2. 飞书文档标题去重规范 (Doc Title De-duplication)

使用 `mcp:lark_create_lark_doc` 工具生成飞书文档时：

- **内容约束**：由于工具已通过 `title` 参数设定全局文档标题，Markdown 正文**绝对不能再以 `# 标题` (H1) 开头**。
- **起始结构**：正文应直接从导语或 H2 标题（##）开始。

### 3. 飞书文档元数据标头规范 (Metadata Header)

所有项目文档、报告或复盘正文的最顶端，必须包含标准化的元数据引用块。

- **格式约束**：

  - `> 📄 **文档编号**：[ID] 📅 **归档日期**：[YYYY-MM-DD]`
  - 引用块下方紧跟 `---` 分割线。
- **前置逻辑**：系统在生成文档前，需先在台账（Sheets）中完成登记或获取对应的流水号。

### 4. “幻觉对象”终极除虫指南 (Ghost Object Eradication)

当文档中出现无法删除的空 Block 或画板残留时，应按以下 SOP 操作：

1. **植入信标**：在异常区域输入信标字符串（如 `GHOST_TARGET_001`）。
2. **下载文档**：使用 `mcp:lark_lark_download` 工具获取 Markdown 全量结构。
3. **定位并斩除**：调用 `scripts/delete_ghost_block.py` 脚本，通过信标定位父级 Block ID 并置空。

## 三、 资源调用参考

### 3.1 安全插入脚本 (Safe Insert)

```Bash
python3 scripts/safe_insert_sheet_row.py <document_url> <sheet_name> <row_index> '<data_json>'

```

- `<row_index>`: 推荐设为 `1` (插入在首行表头之后)。
- `<data_json>`: 数据格式为嵌套列表。

### 3.2 幽灵清除流程 (Ghost Eradication)

```Bash
python3 scripts/delete_ghost_block.py <document_url> <markdown_file_path> GHOST_TARGET_001

```

## 四、 附件

---

**本文档由 Aime 系统自动生成，遵循 SYS-2604 系列归档标准。**

## 🔑 触发词

- 核心关键词：

  - 飞书文档创建
  - 飞书表格写入
  - 跨 Sheet 公式
  - sheet_name / sheet_id
  - formula-verify
  - 个人空间 / move_lark_doc / 幽灵块
- 典型指令示例：

  > 生成一份飞书文档并写入报告，确保直接落到我的个人空间  
  > 修复这张表 N2 公式报 #VALUE! 的问题

## ⚙️ v7.4 新增：公式故障三大陷阱

### 陷阱3：sheet_id 冒充 sheet_name 导致跨 Sheet 公式失效

- 现象：`=MAX('VM2reD'!J:J)` 公式无效或恒为 0，其中 VM2reD 实为「明细」Sheet 的 sheet_id。
- 根因：飞书公式引擎只认 sheet_name（`'明细'`），sheet_id 仅用于 API 定位。
- 正确做法：先 `lark-cli sheets +workbook-info --url "<sheet_url>"` 取 sheet_name，再拼公式。
- 禁止行为：严禁把 MCP/CLI 返回的 sheet_id 直接拼进公式，严禁凭记忆猜 Sheet 名。

### 陷阱4：伪公式文本引发级联 #VALUE!

- 现象：N2 是文本字符串 `"=MAX('VM2reD'!J:J)"`，下游 `=N2-1` 报 #VALUE! 并级联扩散。
- 根因：写入时用了 `value` 字段（或 `+csv-put`），飞书按纯文本存储，不进公式引擎。
- 诊断命令：`lark-cli sheets +cells-get --range "US行业统计!N2" --include value,formula`；**有 value 无 formula 即伪公式文本**。
- 正确做法：`lark-cli sheets +cells-set --cells '[[{"formula":"=..."}]]'`。
- 禁止行为：禁止用 value 字段写公式，禁止用 +csv-put 批量灌公式。

### 陷阱5：文本型日期列不可 MAX

- 现象：`=MAX('明细'!J:J)` 恒为 0。
- 根因：J 列「更新日期」是文本型日期（如 "8/14"），MAX 忽略文本。
- 正确做法：`=INDEX('明细'!J:J,COUNTA('明细'!J:J))` 取最后一条有效值。
- 禁止行为：未确认列类型前禁止对日期列做 MAX/MIN 聚合并直接交付。

## ✅ Verification 补充条款（第 9 条）

- **公式零错误收敛**：任何公式写入/修改后必须执行 `lark-cli sheets +formula-verify --url "<sheet_url>"`，必须收敛到 `status=success` 且 `total_errors=0`；同时用 `+cells-get --include value,formula` 回读确认存在 formula 字段（防伪公式文本）。
- 本地预检脚本：`python3 scripts/formula_write_guard.py --formula "=INDEX('明细'!J:J,COUNTA('明细'!J:J))" --sheet-names '明细,US行业统计' --field formula`

## 变更记录 v7.4

- 新增陷阱3/4/5（sheet_id 冒充 sheet_name、伪公式文本级联 #VALUE!、文本型日期列不可 MAX）。
- Verification 新增第 9 条「公式零错误收敛」。
- 新增 L3 断言脚本 `scripts/formula_write_guard.py`，对三类违规运行时熔断。
- 合规默认值新增：公式写入通道 `+cells-set --cells '[[{"formula":"=..."}]]'`；写后必须 `+formula-verify` 且 total_errors=0。

## ⚙️ v7.5 新增：多选单元格结构化写入护栏

### 陷阱6：多选单元格逗号串写入导致药丸不渲染 + 红色校验角标

- 现象：向多选列（如「覆盖区域」G 列）写入 `"EU,UK,JP"` 后，单元格不渲染多选药丸（Pill/Tag），右上角出现红色校验失败角标；而单值场景（如只写 `"EU"`）恰好命中选项时不报错，造成「偶发正常」的假象，极易误判为已修复。
- 根因：飞书多选单元格的值是**选项数组**，不是字符串。逗号串会被引擎当作**一个整体文本**去匹配选项列表，多值时匹配失败 → 判定为「不在选项列表内」→ 触发数据校验失败角标且不渲染药丸。
- 正确做法：使用 `+cells-set` 的 `multiple_values` 字段，以结构化数组写入：`lark-cli sheets +cells-set --url "<sheet_url>" --range "<Sheet名>!G2" --cells '[[{"multiple_values":[{"value":"EU"},{"value":"UK"},{"value":"JP"}]}]]'`
- 诊断命令：`lark-cli sheets +cells-get --url "<sheet_url>" --range "<Sheet名>!G2" --include value,multiple_values`；回读若只有 `value` 字符串、没有 `multiple_values` 数组，即判定为逗号串污染，必须重写。
- 写后验收：写完必须回读断言 `multiple_values` 数组长度与预期标签数一致，且每个 `value` 命中选项列表；不一致立刻熔断。
- 禁止行为：禁止用 `+csv-put` 批量灌多选列；禁止用 `value` 纯文本字段写多选单元格；禁止因「单值写成功」就推断多值也没问题。

## ✅ Verification 补充条款（第 10 条）

- **多选单元格结构化写入收敛**：任何写入多选（Multi-Select）列的动作，必须走 `+cells-set` 的 `multiple_values` 结构化数组，禁止 `value` 逗号串与 `+csv-put`；写后必须 `+cells-get --include value,multiple_values` 回读断言数组长度与选项命中，不一致立刻熔断。
- 本地预检脚本：`python3 scripts/multiselect_write_guard.py --values "EU,UK,JP" --field multiple_values --allowed-options "EU,UK,JP,US,SEA"`

## 变更记录 v7.5

- 新增「陷阱6：多选单元格逗号串写入导致药丸不渲染 + 红色校验角标」，明确飞书多选值是**选项数组**而非字符串，逗号串会被当作整串文本匹配选项列表而必然校验失败。
- 多选列写入通道锁定为 `+cells-set --cells '[[{"multiple_values":[{"value":"EU"},...]}]]'`，禁用 `value` 纯文本与 `+csv-put` 批量灌列。
- 诊断法固化为 `+cells-get --include value,multiple_values`：只有 `value` 字符串而无 `multiple_values` 数组即判定为逗号串污染。
- Verification 新增第 10 条「多选单元格结构化写入收敛」；Red Flags / Common Rationalizations / Why they fail 同步新增「逗号串写多选」「单值没报错就推断多值也行」的反合理化条款。
- 新增 L3 断言脚本 `scripts/multiselect_write_guard.py`，对逗号串污染、`multiple_values` 结构缺失、选项越界三类违规运行时熔断（正例 exit=0，反例 exit=1）。

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：

```text
「US行业统计」Sheet 的 A1 报 #VALUE!，N2 想取明细表更新日期的最新值
```

- 🤖 标准输出：

```text
1. +workbook-info 取 sheet_name，确认 'VM2reD' 是 sheet_id 而非 '明细'。
2. +cells-get --include value,formula 判定 N2 有 value 无 formula = 伪公式文本。
3. +cells-set --cells '[[{"formula":"=INDEX(\u0027明细\u0027!J:J,COUNTA(\u0027明细\u0027!J:J))"}]]' 重写 N2。
4. A1 恢复表头文本 "US行业"；sleep 2s 回读 N2 = 2026-08-16。
5. +formula-verify 返回 status=success, total_errors=0，方可宣称修复完成。
```