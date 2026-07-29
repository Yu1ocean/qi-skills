---
name: live-performance-summary-generator
description: 以 Live Performance 模版表为基准，先复制整份飞书表格，再向 raw sheet 导入数据并重建“2. 计算汇总”工作表。适用于日常直播分析、副本化分析留档、汇总页错位修复和 benchmark 安全回写场景。
---

# Live Performance Summary Generator

version: 1.5
## 🧭 总览（L1-L4）

> 一段读完即可知道：**做什么 → 怎么做 → 关键步骤 → 怎么验收**。

### L1 · 做什么（What）
把 Live Performance 模版表复制成一份新的分析副本，在副本里的 raw sheet（默认 `1. 数据底表`）贴入原始数据后，一键重建飞书表格里的 `2. 计算汇总` 工作表，包含 16 列指标公式、表头排版、冻结、互动指标 benchmark 标红；其中 `时均show PV /K` 按 `show_pv / 开播小时 / 1000` 计算。

### L2 · 怎么做（How，核心思路）
1. **副本工作流优先**：每次分析都先复制整份模版文件，绝不直接覆盖模版本体；后续所有 raw 导入与 summary 重建都在副本里进行。
2. **动态表头映射**：读取 raw sheet 真表头行（自动跳过 banner 行），按【字段语义】（如 `TT Handle`、`Show GPM`、`Valid CL Watch Duration(AVG.)`）解析每个字段的实际列字母。**绝不**写死 raw 列字母。
3. **导出 + 本地分析**：先用 `lark-sheets-cli +export` 导出 xlsx，再用 `openpyxl` 在本地识别真实数据末行与 benchmark 命中单元格。
4. **就地重建 summary**：先解合并、清值清样式，再写矩阵公式 + 重新合并 + 冻结 + 上色。
5. **RAW 写后回读**：脚本结束前必须读回 `A1:P2` 与首尾若干行，断言表头与关键列非空，失败即报错。

### L3 · 关键步骤（Steps）
1. `bytedcli-auth` 鉴权（必须 `include_secrets=true`）。
2. 以模版文件 `https://dyqe3ary97.larksuite.com/sheets/VVeQshKyvhyK7stx4gbuqOQ4sBb` 创建整表副本。
3. 在副本的 raw sheet（默认 `1. 数据底表`）贴入 Live Performance 原始数据。
4. 解析 spreadsheet token → 获取 raw / summary sheet 元信息。
5. `+export` 导出 xlsx → `openpyxl` 扫描前 4 行定位真表头 → 构建【字段语义 → 列字母】字典。
6. 计算 `last_raw_row`、`benchmark_red_ranges`、`clear_end_row`。
7. 重建 summary sheet（清→写→合并→冻结→上色→标红）。
8. RAW 回读校验（`A1:P2` + 首尾若干数据行）。
9. 输出结果 JSON。

### L4 · 怎么验收（Done）
- `result.field_to_letter` 必须包含 14 个语义字段，且字母合理（不会出现 raw 表里不存在的 `AJ`、`AF` 等）。
- `result.readback.success == true`，`findings == []`。
- 飞书目标表 `2. 计算汇总` 第 3 行起公式区长度 == raw 实际数据行数。
- benchmark 标红单元格只覆盖 `L / M / N / P` 四列，`O` 列从不参与标红。

---

## 📦 依赖声明（Dependencies）

> 每次升级或排错都要先扫一遍依赖矩阵，确保链路全通。

### 1. 内置 Skill 依赖
| Skill 路径 | 调用方式 | 用途 |
|---|---|---|
| `inner_skills/bytedcli-auth/scripts/bytedcli_auth.sh` | 子进程 `bash` 调用 | 用户身份鉴权，必须先于任何飞书操作执行 |
| `inner_skills/lark-sheets/bin/lark-sheets-cli` | 子进程 CLI 调用 | 唯一允许的飞书表格读写通道；本技能仅使用其中以下能力 |

### 2. lark-sheets CLI 子命令使用矩阵
| 子命令 | 用途 |
|---|---|
| `sheets +info` | 读取 spreadsheet 中所有 sheet 元信息（id/title/index/grid） |
| `sheets +create-sheet` | summary sheet 不存在时创建 |
| `sheets +update-sheet` | 设置冻结行列 |
| `sheets +add-dimension` | 扩容 row/col 至清理范围 |
| `sheets +read` | 写后回读校验 (`value-render-option=ToString`) |
| `sheets +write` | 写入表头矩阵与公式对象 |
| `sheets +set-style` | 上色 / formatter / clean 旧样式 |
| `sheets +merge-cells` / `+unmerge-cells` | 重建标题区合并 |
| `sheets +export` | 导出 xlsx 副本到本地，识别真表头与末行 |

### 3. MCP / 飞书原生工具依赖
- 本技能**不**直接调用 lark / lark MCP，所有飞书写操作统一走 `lark-sheets-cli`。
- 不调用 OpenAPI、不调用 Webhook 直推。

### 4. Python 运行时依赖
| 包 | 来源 | 用途 |
|---|---|---|
| `openpyxl` | 公网 PyPI（`pip3 install openpyxl`） | 解析导出的 xlsx 副本（表头识别、末行定位、benchmark 计算） |
| `byted-aime-sdk` | 内网 PyPI | 鉴权与平台基础能力 |

> 所有依赖均已纳入 `.aime/setup/setup.sh`，首次运行会自动安装。

---

## Common Rationalizations（常见借口）

以下想法一旦出现，说明已经偏离这个技能的护栏：

- "先写死 38 行公式，样例能跑就行。"
- "raw 列字母用最近一次跑通的值就行，反正用户不会改源表。"  ← **本次重构的根本目标就是斩断这条**
- "先在 summary 后面继续追加，不清旧数据也没关系。"
- "benchmark 颜色先不做，反正用户能自己看。"
- "直接调 OpenAPI 更快，不必经过 lark-sheets CLI。"
- "bytedcli-auth 太麻烦，先赌一下当前环境已经登录。"
- "写完直接返回 ok=true，不用回读。"

## Red Flags（危险信号）

出现任一条，都必须立刻停下并修正：

- 没有通过 `bash` 直接执行 `scripts/generate_summary_sheet.py`，或者没有 `include_secrets=true`
- 直接连 OpenAPI，而不是走 `inner_skills/lark-sheets/bin/lark-sheets-cli`
- 在 raw sheet 中按列字母而不是按字段语义生成公式
- 公式里出现 raw sheet 中不存在的列字母（如 `AJ`、`AF` 当数据只到 `AE`）
- 没有先清理旧 summary 区，就开始覆盖写新公式
- 把 `O` 列也纳入 benchmark 标红
- 没有写后回读校验，只验证写入接口返回值

## Verification（强制验收）

当宣称"生成完成"时，必须同时满足：

1. `2. 计算汇总` 工作表存在，且冻结为 **2 行、2 列**
2. `A1:K2` 为浅绿色区，`L1:P2` 为浅黄色区，所有文字目标色为黑色
3. 第 3 行起的公式区长度与 raw sheet 实际有效行数一致，而不是固定样例行数
4. `L / M / N / P` 低于 benchmark 的单元格已写入浅红底，`O` 列未参与标红
5. 至少回读 `A1:P2` 与首/末数据行，对表头与关键列做断言式校验，结果反映在 `result.readback`
6. `result.field_to_letter` 中 14 个字段映射到的列字母全部存在于 raw 表头行

## 适用场景

- 收到 Live Performance 原始数据表，需要自动生成 `2. 计算汇总`
- 目标表已有旧版 summary，需要就地重建、覆盖并清理旧脏数据
- raw 表新增/删除/隐藏列，导致旧版按列字母硬编码的脚本整体错位
- 需要快速验证某份 raw 数据贴入后 summary 是否正常出数

## 合规默认值（Defaults）

- `template spreadsheet url`：`https://dyqe3ary97.larksuite.com/sheets/VVeQshKyvhyK7stx4gbuqOQ4sBb`
- `raw sheet title`：`1. 数据底表`
- `summary sheet title`：`2. 计算汇总`
- `summary index`：默认位于第 2 个工作表位置（raw sheet 之后）
- `冻结`：2 行、2 列
- `文字颜色`：`#000000`
- `浅绿色 1`：`#E2F0D9`
- `浅黄色 1`：`#FFF2CC`
- `浅红色底`：`#F4CCCC`
- `表头扫描行数上限`：4 行（用 TT Handle / CL GMV / Show PV 三个核心字段定位真表头）
- `清理范围下限`：至少清到 500 行，并在实际最后一行后额外预留 100 行清理缓冲
- `O2` 表头：`Share rate \n观察持续提升`
- `E2` 表头：`时均show PV /K`

## 核心执行约束

### 1. 必须先完成用户身份鉴权

运行主脚本时，必须通过 `bash` 工具直接执行，并设置 `include_secrets=true`。主脚本内部会先执行 `bytedcli-auth`，然后才调用飞书表格 CLI。

```bash
python3 scripts/generate_summary_sheet.py "<spreadsheet_url_or_token>"
```

### 2. 只允许走 lark-sheets CLI

所有飞书表格读写、建表、冻结、样式、合并都必须经过：

- `inner_skills/lark-sheets/bin/lark-sheets-cli`

不要自己拼 OpenAPI 请求。

### 3. 副本工作流（V1.4 新增）

每次分析时，必须先复制整份模版文件：

- 模版文件：`https://dyqe3ary97.larksuite.com/sheets/VVeQshKyvhyK7stx4gbuqOQ4sBb`
- 禁止直接向模版本体写入 raw 数据
- 禁止在模版本体上重建 summary
- 后续所有导数、公式、benchmark 标红、人工核对都只在副本里完成

推荐顺序：
1. 创建整表副本
2. 在副本 `1. 数据底表` 中贴入 raw 数据
3. 对副本运行 `scripts/generate_summary_sheet.py`
4. 校验副本中的 `2. 计算汇总`

### 4. 动态表头映射（V1.2 重构核心）

主脚本在 raw sheet 导出 xlsx 后：

1. 扫描前 4 行，逐行尝试解析 `RAW_FIELD_HEADER_CANDIDATES` 中的字段；
2. 命中三个核心字段（`TT Handle` / `CL GMV` / `Show PV`）的行视为真表头行；
3. 用该行表头建立【字段语义 → 列字母】映射；
4. 后续公式与 benchmark 全部基于该映射生成，不再依赖任何硬编码列字母。

### 5. summary sheet 的重建策略

**summary 不存在：** 自动创建 `2. 计算汇总`

**summary 已存在：** 在原 sheet 上执行以下重建动作：
1. 解除 `B1:K1`、`L1:P1` 合并
2. 清空 `A1:P{clear_end_row}` 的旧值
3. 清空同范围旧样式
4. 重写表头与公式区
5. 重新合并、冻结并批量上色

### 6. benchmark 标红规则

- `L < 55` → 浅红底（Watch Duration AVG）
- `M < 0.01` → 浅红底（Follow rate）
- `N < 5` → 浅红底（Like rate）
- `O` 暂不判断（Share rate 持续观察）
- `P < 0.05` → 浅红底（Comment rate）

判断基于 raw sheet 的原始数值，不基于 summary 的显示文本。

### 7. RAW 写后回读校验（V1.2 新增）

写入完成后强制执行：
- 读 `A1:P2`：断言 `A1=='基础数据'` 且第二行 16 列严格等于 `SUMMARY_HEADERS`
- 读首/末数据行：断言 A（Handle）、C（GMV）、F（开播小时）三列非空
- 任一断言失败立刻 `raise SummaryGenerationError`，绝不向用户返回 `ok=true`

## 执行步骤

1. 以模版文件 `https://dyqe3ary97.larksuite.com/sheets/VVeQshKyvhyK7stx4gbuqOQ4sBb` 创建整表副本
2. 在副本 `1. 数据底表` 贴入目标 raw 数据
3. 对副本 spreadsheet URL 或 token 运行 `scripts/generate_summary_sheet.py`
4. 如 raw / summary 标题不是默认值，显式传 `--raw-sheet-title` 与 `--summary-sheet-title`
5. 完成后查看 `result.readback` 与 `result.field_to_letter`
6. 再读取表格元信息，确认 summary sheet 冻结正确、位置在 raw sheet 之后
7. 如需核对公式、颜色或阈值细节，再按需读取 references 文档

## 脚本

- `scripts/generate_summary_sheet.py`
  - 低自由度主脚本
  - 负责鉴权、导出、动态表头映射、动态行数识别、重建 summary、写公式、冻结、上色、benchmark 标红、写后回读校验
- `scripts/lark_sheets_cli.py`
  - 对 `inner_skills/lark-sheets/bin/lark-sheets-cli` 的本地封装
  - 只提供本技能所需的安全读写接口

## References

- `references/formula-mapping.md`
  - 字段语义、候选表头别名、公式映射规则
- `references/style-and-benchmark.md`
  - 颜色、formatter、benchmark 与脏数据清理规则
- `references/usage-and-validation.md`
  - 标准命令、最小验证动作、常见失败原因
- `references/template-copy-workflow.md`
  - 模版副本工作流、操作边界与推荐分析节奏
- `references/current-template-schema.md`
  - 当前官方模版的工作表清单、raw 真表头、summary 映射与 benchmark 基线

## 标准命令

推荐场景（对副本执行，而不是对模版本体执行）：

```bash
python3 scripts/generate_summary_sheet.py "https://dyqe3ary97.larksuite.com/sheets/<copied_spreadsheet_token>"
```

显式指定 sheet 标题：

```bash
python3 scripts/generate_summary_sheet.py "<copied_spreadsheet_url_or_token>" \
  --raw-sheet-title "1. 数据底表" \
  --summary-sheet-title "2. 计算汇总"
```

调试时输出结果 JSON：

```bash
python3 scripts/generate_summary_sheet.py "<copied_spreadsheet_url_or_token>" \
  --output-json live-performance-summary-result.json
```

## 输出要求

主脚本标准输出为 JSON，至少包含：

- `spreadsheet_token`
- `raw_sheet_id`
- `summary_sheet_id`
- `data_rows`
- `header_row` / `data_start_row` / `last_raw_row`
- `clear_end_row`
- `benchmark_red_ranges`
- `exported_xlsx`
- `field_to_letter`（动态字段映射结果，用于人工核对）
- `readback`（RAW 写后回读校验明细，含 `success` / `findings`）

出现任何硬错误时，直接返回 `ok=false` 与错误信息，不要假装成功。

## Changelog

- **V1.5 (2026-06-19)**：
  - 基于当前官方飞书表格重新固化模版：raw 页清空数据区，仅保留 banner + 真实表头；summary 页清空公式区，仅保留表头与样式。
  - 对齐新的 summary 口径：`E2` 改为 `时均show PV /K`，公式同步改为 `show_pv / 开播小时 / 1000`。
  - 新增 `references/current-template-schema.md`，把当前官方模版的工作表名称、raw 真表头、summary 映射和 benchmark 基线固化成 SSOT。
- **V1.4 (2026-06-19)**：
  - 新增“副本工作流”SOP：每次分析必须先复制整份模版文件，再向副本 raw sheet 导入数据，禁止直接改模版本体。
  - 对齐模版默认设置：`template spreadsheet url` 固定为 `https://dyqe3ary97.larksuite.com/sheets/VVeQshKyvhyK7stx4gbuqOQ4sBb`，`summary index` 明确为 raw sheet 之后的第 2 个工作表位置。
  - 对齐模版表头细节：`O2` 改为 `Share rate \n观察持续提升`，与当前模版页展示保持一致。
- **V1.2 (2026-05-20)**：
  - 重构动态表头映射，杜绝硬编码列字母导致的错位（AOV 变百分比、Follow rate 3000%+ 等）。
  - 新增 RAW 写后回读校验机制：`A1:P2` 表头 + 首尾数据行三列断言，失败即 raise。
  - 补齐 `openpyxl` 安装到 `setup.sh`，新增 L1-L4 总览置顶 + 完整依赖声明章节。
  - 清理 `__pycache__/` / `tmp_live_performance_exports/` / `_release/` / `verification_after.xlsx` / `validation_result.json` 进入 `.skillignore`，缩减打包域。
- **V1.1**：动态行数识别 + benchmark 命中范围；解除旧 summary 后重建。
- **V1.0**：首版，按硬编码列字母生成 38 行样例公式。
