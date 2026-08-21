---
name: eu-am-efficiency-analyzer
description: EU AM（EU 招商商务）效率漏斗分析器。从飞书分层读写架构（3底表+3阅读视图）读取分析基盘，计算各 AM 的线索量/有意愿数/主口径入驻数/备用口径入驻数，输出漏斗阶段与段转化诊断、瓶颈定位与对标提升量化，并渲染白底气泡矩阵（ECharts HTML + PNG，全行业总览 + 分行业 Tab、四象限、中位数分界线），附带完整口径说明。
author: 于奇楠
version: 1.2
---

# EU AM 效率漏斗分析器 (eu-am-efficiency-analyzer) v1.2

把 EU AM 招商效率从「一堆明细行」变成「可判断的漏斗诊断 + 可看懂的气泡矩阵」。计算内核纯函数、无副作用、内置双路重算与漏斗单调性断言（零信任校验）；渲染层强制白底，与计算解耦。

## Common Rationalizations（常见借口库）

以下话术一旦出现，等价于准备越过红线，必须立刻停下回到 SOP：

- 「MCP 链路麻烦，我直接拿 token 调飞书 OpenAPI 读一下 Sheet。」
- 「零信任校验 FAIL 只差一点点，先出图，数字后面再对。」
- 「主口径入驻时间没回填，我就当它 0 混进有效 AM 一起算中位数。」
- 「背景色是深色更好看，白底以后再改。」
- 「口径说明（截止日期 / 剔除规则 / 灰色 AM）先省了，看图的人自己懂。」
- 「罗才鑫这行留着也不影响大局。」
- 「上下文里就写着 sheet 名叫 X，不用再 `+workbook-info` 查一遍了。」
- 「`+formula-verify` 返回 total_errors=0 就算通过，partial/has_more 不用管。」
- 「INDEX 行上界先按 1423 写死，行数变了再改。」
- 「阅读视图公式我直接在技能目录里再写一份生成逻辑，比调 projects 下的方便。」

## Red Flags（危险信号）

出现任意一条即熔断或要求确认：

- 绕过 `lark-sheets` MCP 链路裸调 OpenAPI 读写飞书表格。
- `validate_zero_trust` 返回 FAIL 却继续导出 JSON / 渲染图表 / 对外交付。
- 中位数分界线把 `pending`（入驻时间待回填）AM 计入有效样本。
- 产出 HTML/PNG 背景非 `#FFFFFF`（或残留 `#111111` 深色块）。
- 交付物没有口径说明四要素（数据截止日期、剔除规则、灰色 AM 逻辑、主/备用口径定义）。
- 汇报里出现「应该 / 大概 / 大约」但没有可回读的数字证据。
- 未先 `+workbook-info` 取真实 sheet 名/ID 就直接写入（线上 sheet 已被人工改名过）。
- 对 `历史入驻` / `AM分析` 等受保护 Sheet 发起任何写入或 clear。
- `+formula-verify` 返回 `status=partial` + `has_more=true` 却拿 `total_errors=0` 当验收通过。
- 阅读视图 INDEX 行上界或 MATCH 列上界被硬编码，与底表实际行数/列数脱节。
- 用「全量底表 AM 空值率 77%」当质检 FAIL（错误口径），或对 `BD底表` 不校验 `负责BD` 非空率 == 100%。

## Verification（强制验收清单）

宣称「分析完成」时必须同时满足：

1. **来源可回读**：数据来自分层同步表的 `AM招商推进_阅读视图` / `全量_AM招商推进`，且走 MCP `lark-sheets` 读取，行数与飞书侧一致。
2. **零信任 PASS**：`validate_zero_trust` / `run_funnel_diagnosis.py` 退出码 0，无 FAIL 项。
3. **双口径齐备**：每个 AM 同时给出主口径入驻数（EU/UK 入驻时间有值）与备用口径入驻数（状态=5-已入驻）。
4. **剔除生效**：`罗才鑫` 已剔除，有效 AM 数与灰色 AM 数在输出中显式打印。
5. **白底断言**：PNG 四角像素为 `(255,255,255)`；HTML 含 `backgroundColor` 且不含 `111111`。
6. **象限与分界线**：分界线取**有效 AM**（非 pending）中位数，四象限命名为明星 / 精耕小池 / 规模待提效 / 待突破。
7. **口径说明随交付**：数据截止日期、剔除规则、灰色 AM 复核提示一并输出。
8. **分层架构验收**（涉及数据同步时强制）：6 张 Sheet 行数与 `layered_result.json` 一致；每个阅读视图 `Σtotal_formulas == 行数 × 38`；`PROTECTED` Sheet 零写入；`overall == true`。

## 合规默认值（Defaults）

- 数据源 Sheet：`https://bytedance.my.larkoffice.com/sheets/RvpVsoUODhqCXJt4rFgm1M6ky2e`（分层同步表）
- 分析基盘工作表：优先读 `AM招商推进_阅读视图`（`t5m7r4`），需全字段时读底表 `全量_AM招商推进`（`8953af`）；读取只走 MCP `lark-sheets`，`include_secrets=true`
- 默认分组维度：`负责AM`（内核维度无关，可传 `行业` / `国家`）
- 默认剔除名单：`罗才鑫`
- 背景色：`#FFFFFF`（HTML `backgroundColor` + matplotlib fig/ax/savefig facecolor）
- 零信任校验：默认开启，FAIL 即熔断
- 结果 JSON 默认名：`am_funnel_diagnosis.json`

### 数据源同步链路（ETL Defaults）

- 真实数据源（多维表格）：https://bytedance.my.larkoffice.com/base/MPN9bUhBTaUsgcsrN92m2Oq0yde?table=tbl5IlstItZOpInx&view=vewm2HQxRS（base_token=MPN9bUhBTaUsgcsrN92m2Oq0yde, table_id=tbl5IlstItZOpInx）
- 同步脚本（唯一真相源）：`projects/eu-am-efficiency/build_layered_sheets.py`；技能内副本 `scripts/build_layered_sheets.py`，薄壳入口 `scripts/layered_sync_entry.py`
- 同步目标：https://bytedance.my.larkoffice.com/sheets/RvpVsoUODhqCXJt4rFgm1M6ky2e（3 底表全量幂等覆盖 + 3 阅读视图公式重建）
- 同步频率：每日工作日 08:50 CST（cron: 50 8 * * 1-5，须使用绝对路径 /usr/local/bin/lark-cli）
- 长整型字段：`seller_id` / `shop_id` / `leads_id` / `匹配global_seller_id` 一律 dtype=object（文本格式 @）
- 零信任门禁：行数断言 / 表头列序 / 关键字段空值率 / RAW 回捞 5 行；任一 FAIL → `sys.exit(3)`

### 入口命令

```bash
# 全量更新（底表 + 阅读视图）
python3 scripts/build_layered_sheets.py

# 仅更新底表
python3 scripts/build_layered_sheets.py --layer base

# 技能内薄壳入口
python3 scripts/layered_sync_entry.py
```

### 合规默认值变更（v1.1 → v1.2）

| 项目 | v1.1 | v1.2 |
|------|------|------|
| 分析基盘读取 | 旧单表（已停用） | 优先读 `AM招商推进_阅读视图` 或 `全量_AM招商推进` |
| 架构 | 单表 | 3 底表 + 3 阅读视图 |

## 🗂 分层读写架构（3 底表 + 3 阅读视图）

自 v1.2 起，数据同步从「1 底表 + 1 阅读视图」升级为**人机分层读写**架构：底表层给机器（全字段、幂等覆盖），阅读层给人（固定 38 列表头、公式动态引用）。

```
多维表格源（106 字段 / 8496 行）
   └─ build_layered_sheets.py --layer base   ← 机器层：3 张底表，106 列全字段，每日幂等覆盖
        ├─ 全量底表            8496 行  无筛选
        ├─ 全量_AM招商推进     1906 行  AM优先级 == "AM招商推进"
        └─ BD底表              1480 行  负责BD 非空
   └─ build_layered_sheets.py --layer view   ← 人类层：3 张阅读视图，38 列固定表头
        ├─ 全量_阅读视图        → 全量底表         （8496 行）
        ├─ AM招商推进_阅读视图  → 全量_AM招商推进  （1906 行）
        └─ BD_阅读视图          → BD底表           （1480 行）
   受保护不可写：历史入驻、AM分析
```

目标电子表格：<https://bytedance.my.larkoffice.com/sheets/RvpVsoUODhqCXJt4rFgm1M6ky2e>

### Sheet 台账（sheetId 为线上事实，写入前仍须 `+workbook-info` 复核）

| 层 | Sheet 名 | sheetId | 行数 | 列 | 筛选口径 / 引用来源 |
|---|---|---|---|---|---|
| 底表 | `全量底表` | `YNN8uk` | 8496 | 106 | 无筛选（源全量） |
| 底表 | `全量_AM招商推进` | `8953af` | 1906 | 106 | `AM优先级 == "AM招商推进"`（**新口径，不再叠加 `历史入驻 != 1`**；旧口径为 1422 行） |
| 底表 | `BD底表` | `MpyNOP` | 1480 | 106 | `负责BD` 非空（非 None / 非空串 / strip 后非空） |
| 阅读 | `全量_阅读视图` | `KYImDl` | 8496 | 38 | 引用 `全量底表` |
| 阅读 | `AM招商推进_阅读视图` | `t5m7r4` | 1906 | 38 | 引用 `全量_AM招商推进` |
| 阅读 | `BD_阅读视图` | `JC5aOe` | 1480 | 38 | 引用 `BD底表` |
| 🔒 受保护 | `历史入驻` | `Tc3dvL` | — | — | **只读**，任何写入/clear 立刻熔断 |
| 🔒 受保护 | `AM分析` | `M45mLI` | — | 38 | **只读**（原名「分析基盘_阅读视图」，线上已被人工改名） |

阅读视图公式形态（按字段名动态引用，抗源表列序变动）：

```
=IFERROR(INDEX(底表!$A$2:$DB$<底表行数+1>, ROW()-1, MATCH(<表头名>, 底表!$A$1:$DB$1, 0)), "")
```

### 复现命令（唯一真相源 + 技能内薄壳入口）

真相源：`projects/eu-am-efficiency/build_layered_sheets.py`（单文件参数化），结果落 `projects/eu-am-efficiency/layered_result.json`。

```bash
cd user_skills/eu-am-efficiency-analyzer
python3 scripts/layered_sync_entry.py --dry-run          # 只算行数与筛选，不写飞书
python3 scripts/layered_sync_entry.py --layer base       # 只重建 3 张底表
python3 scripts/layered_sync_entry.py --layer view       # 只重建 3 张阅读视图
python3 scripts/layered_sync_entry.py                    # 全链路（base + view）
python3 scripts/layered_sync_entry.py --cache <records.ndjson>   # 复用本地拉取缓存
```

`scripts/layered_sync_entry.py` 是**纯 L3 断言 + 子进程转发**的薄壳：真相源缺失即 `raise FileNotFoundError`，绝不在技能目录内复制业务逻辑（与 `sync_source_entry.py` 完全同构）。所有飞书链路调用必须 `include_secrets=true`。

### 工程护栏（8 条，踩坑换来的硬约束）

| # | 护栏 |
|---|------|
| G1 | 写入前必须 `+workbook-info` 确认 sheet 名与 sheet_id |
| G2 | PROTECTED 白名单硬熔断：`历史入驻` / `AM分析` / `分析基盘_阅读视图` 拒绝写入 |
| G3 | 底表写入：Pass A `+cells-clear` 清空 + Pass B `+table-put` 全量重写 |
| G4 | 长整型字段（`seller_id` / `shop_id` / `leads_id` / `匹配global_seller_id`）强制 dtype=object（文本格式 @） |
| G5 | 字段名 key 映射写入，不依赖 API 返回列位置顺序 |
| G6 | 阅读视图通过 INDEX+MATCH 按列名引用底表 |
| G7 | `负责AM` / `AM优先级` 空值率断言 <5%（全量底表 / BD底表豁免 `负责AM`；BD底表追加 `负责BD` 非空率 = 100%） |
| G8 | 零信任质检 4 项（行数断言 / 表头列序 / 关键字段空值率 / RAW 回捞 5 行）任一 FAIL 即 `sys.exit(3)` |

细则：

1. **写入前必须 `+workbook-info` 取真实 sheet 名/ID**，绝不凭上下文里的名字直接写——实测线上 sheet 已被人工改名（`分析基盘_阅读视图` → `AM分析`）。
2. **`+cells-clear` 打不存在的 sheet 会 `900015206` 熔断** → 先判存在再 clear；不存在的子表交给 `+table-put` 自动创建。
3. **`+formula-verify` 单次扫描上限 20 万单元格**：大表返回 `status=partial` + `has_more=true` 时 `total_errors=0` **不可信**，必须 `--range` 分段复扫，并校验 `Σtotal_formulas == 行数 × 38`。
4. **INDEX 行上界必须按底表实际行数参数化**，禁止硬编码（旧 `build_reading_view.py` 写死 `$DB$1423`，是本条护栏的反例来源）。
5. **`MATCH(表头名, 底表!$A$1:$DB$1, 0)` 的上界 `$DB` 恰好等于 106 列**：源表新增字段导致超过 106 列时必须同步放宽上界，否则新字段会静默 MATCH 不到。
6. **长整型 ID 强制文本**：`seller_id` / `shop_id` / `leads_id` / `临时id` / 任意含 `id` 的字段一律 `dtypes:object`（文本 `@`），并以「15 位数值阈值」兜底识别漏配字段。
7. **`PROTECTED` 白名单在所有写入入口 `guard()` 硬熔断**（`历史入驻` / `AM分析`），不依赖人工小心。
8. **质检口径按底表分别配置断言阈值**：`负责AM` / `AM优先级` 空值率 <5% **只适用于 AM 相关底表**；`全量底表`（77% 无 AM）与 `BD底表`（72% 无 AM）是源数据事实，不构成 FAIL。`BD底表` 的硬断言是 **`负责BD` 非空率 == 100%**。


## ⚙️ 核心架构 / SOP

```
飞书 AM招商推进_阅读视图 --(MCP lark-sheets)--> DataFrame/CSV
   └─> am_analysis_core（纯计算：阶段/段转化/瓶颈/对标/零信任）
         └─> run_funnel_diagnosis.py（薄 CLI + L3 断言）--> result.json
   └─> render_bubble_matrix.py --> 白底 ECharts HTML（聚焦版/全轴版）+ PNG + data.json
```

### Step 1 · 读取分析基盘（禁止裸调 OpenAPI）

使用 `lark-sheets` 技能读取，例如：

```bash
lark-cli sheets +csv-get --url "https://bytedance.my.larkoffice.com/sheets/RvpVsoUODhqCXJt4rFgm1M6ky2e" \
  --sheet-name "AM招商推进_阅读视图" > /tmp/eu_am_base.csv
```

调用飞书相关脚本/命令时必须设置 `include_secrets=true`。先 `+workbook-info` 确认工作表名，再读取；不要凭直觉猜 sheet 名。

### Step 2 · 计算漏斗指标

每个 AM 输出四个基础量：

| 指标 | 口径 |
|---|---|
| 线索量 | 该 AM 名下线索行数 |
| 有意愿数 | 意愿标记为有意愿的行数 |
| 主口径入驻数 | EU / UK 入驻时间字段**有值** |
| 备用口径入驻数 | 入驻状态 = `5-已入驻` |

派生：主口径入驻率 = 主口径入驻 / 线索量；备用口径意愿→入驻转化率 = min(备用口径入驻, 有意愿) / 有意愿。

诊断（阶段表 / 段转化 / 瓶颈 / 对标提升 / 零信任）走内核：

```bash
cd user_skills/eu-am-efficiency-analyzer
python3 scripts/run_funnel_diagnosis.py --csv /tmp/eu_am_base.csv --dim 负责AM --out am_funnel_diagnosis.json
```

内核 API（详见 [references/am_analysis_core_README.md](references/am_analysis_core_README.md)）：`FunnelSpec` / `build_snapshots_from_dataframe` / `compute_stage_table` / `compute_segment_table` / `locate_bottleneck_and_gain` / `classify_phase` / `build_heat_matrix` / `rank_bottlenecks` / `quantify_benchmark_uplift` / `validate_zero_trust` / `run_diagnosis` / `export_json`。

> 能力归属说明（如实标注）：漏斗阶段诊断能力**内聚在 `scripts/am_analysis_core.py`**，本技能不存在独立的 `funnel_stage_analyzer.py`（源项目磁盘上亦无该文件）。`scripts/run_funnel_diagnosis.py` 是围绕 `run_diagnosis` **新写的薄封装 CLI**，不是从旧文件迁移而来。

### Step 3 · 渲染白底气泡矩阵

```bash
cd user_skills/eu-am-efficiency-analyzer && python3 scripts/render_bubble_matrix.py
```

- 横轴 = 主口径入驻率；纵轴 = 备用口径意愿→入驻转化率；气泡大小 = 线索量。
- 分界线 = **有效 AM**（主口径入驻数 > 0）中位数；四象限：明星（右上）/ 精耕小池（左上）/ 规模待提效（右下）/ 待突破（左下）。
- 主口径入驻时间待回填的 AM 记为 `pending`，以**灰色气泡**落在备用口径位置并标注「需复核」，不参与中位数计算。
- 输出：`am_bubble_v2_clip.html`（聚焦版）、`am_bubble_v2_preview.html`（全轴版）、PNG、`am_bubble_v2_data.json`；`deploy_site/` 存在时同步产出同域版。
- 全行业总览 + 分行业 Tab：按 `行业` 维度重复 Step 2/3，各行业一个 series/Tab，共用同一套象限与配色。
- 白底为硬约束：改动渲染层后必须复验 PNG 四角像素 `(255,255,255)`，HTML 含 `backgroundColor` 且不含 `111111`。

### Step 4 · 输出口径说明（不可省）

交付必须附：数据截止日期；剔除规则（如剔除罗才鑫）；灰色 AM 逻辑（入驻时间待回填 → 备用口径 + 灰色 + 需复核）；主/备用口径定义；有效 AM 数与灰色 AM 数。

## 📖 案例实录

- 🧑‍💻 用户输入：`分析一下 EU AM 的招商效率，出个气泡矩阵`
- 🤖 标准输出：
  1. MCP 读取 `AM招商推进_阅读视图` → 24 位有效 AM（已剔除罗才鑫）；
  2. `run_funnel_diagnosis.py` 退出码 0、零信任 PASS；
  3. 白底 ECharts 聚焦版/全轴版 HTML + PNG，中位数分界线 x=…、y=…；
  4. 附口径说明与灰色 AM 复核清单。

## 变更记录

- **v1.2**：数据同步架构由「1 底表 + 1 阅读视图」升级为「3 底表 + 3 阅读视图」人机分层读写（底表层 106 列全字段每日幂等覆盖：全量底表 8496 行 / 全量_AM招商推进 1906 行 / BD底表 1480 行；阅读层 38 列固定表头 + INDEX+MATCH 按字段名动态引用）；`全量_AM招商推进` 筛选口径改为仅 `AM优先级 == "AM招商推进"`（不再叠加 `历史入驻 != 1`，1422 → 1906 行）；`历史入驻` / `AM分析` 列为受保护只读 Sheet；沉淀 8 条工程护栏（workbook-info 前置复核、cells-clear 存在性判断、formula-verify 分段复扫、INDEX/MATCH 上界参数化、长整型 ID 文本化、PROTECTED guard 硬熔断、质检阈值按底表分别配置）；新增技能内薄壳入口 `scripts/layered_sync_entry.py`（L3 断言 + 子进程转发到 `projects/eu-am-efficiency/build_layered_sheets.py`）；新增技能内主脚本 `scripts/build_layered_sheets.py`；沉淀 8 条工程护栏（G1-G8）；分层同步表 `RvpVsoUODhqCXJt4rFgm1M6ky2e`；移除旧版 `Bi8ms...` 单表数据源引用。
- **v1.1**：补齐真实数据源 ETL 同步链路（多维表格 → 分析基盘 每日工作日 08:50 CST 全量重写，幂等 Pass A/Pass B），并内置三项零信任门禁（行数断言 / 关键字段空值率<5% / RAW 抽 10 行 0 差异，任一 FAIL 即非 0 退出）；新增技能内 L3 入口脚本 `scripts/sync_source_entry.py`。
- **v1.0**：首版。内核 `am_analysis_core.py`（含零信任双路重算与漏斗单调性断言）+ 白底渲染层 `render_bubble_matrix.py` + 薄封装 CLI `run_funnel_diagnosis.py`（L3 断言熔断）；补齐 L1 反合理化三件套与 L2 合规默认值。

## ☁️ 云端发布记录

- `cloud_publish_status`: **SUCCESS**
- `skill_name`: `eu-am-efficiency-analyzer`
- `version`: `1.2`
- `cloud_scope`: `user`
- `cloud_published_at`: `2026-08-21 21:30`
- `cloud_skill_id`: `3b6bdf3f-82e1-481b-945a-ec801dec95a9`
