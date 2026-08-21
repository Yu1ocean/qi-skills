# 【技能说明】赛博周期性汇报生成器

<figure view-type="Card"><source name="periodic-report-generator.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=M2RlZjJhZjA4NjZhNzlkMGM1MTE0OTFlMTczZDgzZjZfMTkxYTNhMTcwMGYxN2EyNTRjNTY1NjYwNDliZWNjMWJfSUQ6NzY3NjQ0NjQ0MTUzMDkzNjUzMF8xNzg3MzExOTcyOjE3ODczMTU1NzJfVjM" mime="application/zip" size="471102" token="Bhovb0unEoPr98xQuHecbrNonTg"/></figure>

> 📄 **文档编号**：SYS-2604-011 📅 **归档日期**：2026-04-13

---

<callout emoji="💡">
**技能定位**：赛博周期性汇报生成器。专门处理“每日 100 字工作日报”与“结构化周报”的自动化生成、结构化组装与安全归档。
</callout>

## 🔑 触发词

- 核心关键词：

  - 周报
  - 日报归档
  - --write-perf-pool
  - 绩效素材池
- 典型指令示例：

  > 生成本周周报，并把 GMV、实验和决策高亮写入绩效素材池跑日报归档质检并写入 Daily_Logs

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：

  ```Plain Text
  生成本周结构化周报，并开启 --write-perf-pool
  
  ```
- 🤖 标准输出：

  ```Plain Text
  先生成周报飞书文档并完成台账归档，再将 GMV、实验、决策三类高亮以 [日期, 事项类型, 内容摘要, 来源报告链接] 写入 Perf_Material_Pool，并输出 RAW 回捞行号。
  
  ```

## 一、 工作日报 (Daily Log) 规范

<grid>
<column width-ratio="0.500000">
**核心要求**
- 字数：100 字左右。
- 风格：极简、数据驱动。
- 严禁：过度使用形容词、虚浮表述。
</column>
<column width-ratio="0.500000">
**归档 SOP**
- 目标：台账 `Daily_Logs` 工作表。
- 路径：调用 `safe_insert_sheet_row.py`。
- 模式：`[[日期, 内容]]` 格式。
</column>
</grid>

## 二、 结构化周报 (Weekly Report) 模块

周报必须包含以下五个维度的深度复盘，以确保“数字生命”的可回溯性：

1. **代码层复盘**：Repository 变动、逻辑重构、架构演进。
2. **指令层复盘**：Prompt 迭代、Skill 演进、Agent 交互逻辑变更。
3. **【图书馆】资产**：本周新增的 Doc/Sheet/Bitable 资产链接。
4. **风险应对矩阵**：未来实验计划与潜在风险评估。
5. **赛博碎碎念**：带有赛博朋克色彩的第一人称视角感慨。

## 三、 安全与约束机制

- **双轨归档**：文档生成后，必须以 `HYPERLINK` 形式同步到台账。
- **原子锁机制**：强制调用 `feishu-doc-writing-guide` 的安全插入 API。
- **元数据标头**：所有周报顶部必须包含标准编号与日期盖章。

<callout emoji="🥇">
**Changelog V2**: 风格从“极客幽默”全面转向“极简数据驱动”，强制量化所有技术指标。
</callout>