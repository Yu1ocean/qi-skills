# EU AM 效率漏斗分析器 (eu-am-efficiency-analyzer) v1.2.4 技能说明

<figure view-type="Card"><source name="eu-am-efficiency-analyzer.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OTM1NzI5YjliZmZlM2FjNmJmZWE1ZmM3ZmJiNTZlNGJfNDkxMTk1ZjgyNWJlZWRjNzBkOTlhZTFlZDc0OTE0YTBfSUQ6NzY3NjgyNzAwMzc5NzkxNzMwMV8xNzg3NDAwNTc3OjE3ODc0MDQxNzdfVjM" mime="application/zip" size="45991" token="WUtqbHckboaahoxX6WCmdMVSyEc"/></figure>

> 🤖 **本区块由 forge 流水线自动生成（Overwrite Zone），请勿手工编辑**  
> **技能名称**：`eu-am-efficiency-analyzer`  
> **版本号**：1.2.4  
> **描述**：EU AM（EU 招商商务）效率漏斗分析器。从飞书分层读写架构（3底表+3阅读视图）读取分析基盘，计算各 AM 的线索量/有意愿数/主口径入驻数/备用口径入驻数，输出漏斗阶段与段转化诊断、瓶颈定位与对标提升量化，并渲染白底气泡矩阵（ECharts HTML + PNG，全行业总览 + 分行业 Tab、四象限、中位数分界线），附带完整口径说明。  
> **更新时间**：2026-08-22 20:09

## 📌 技能简介

`eu-am-efficiency-analyzer`（EU AM 效率漏斗分析器 v1.2）把 EU 招商商务（AM）的效率评估，从「一堆明细行 + 手工透视」升级为「可判断的漏斗诊断 + 可看懂的白底气泡矩阵」。它从飞书底层数据库读取分析基盘，计算每位 AM 的线索量 / 有意愿数 / 主口径入驻数 / 备用口径入驻数，输出阶段与段转化诊断、瓶颈定位与对标提升量化，并渲染 ECharts 气泡矩阵（全行业总览 + 分行业 Tab 切换）。计算内核纯函数无副作用，内置双路重算与漏斗单调性断言（零信任校验），渲染层强制白底。**v1.2 起**另含飞书电子表格「3 底表 + 3 阅读视图」人机分层读写同步架构（底表 106 列全字段幂等覆盖 / 阅读视图 38 列 INDEX+MATCH 动态引用 / 受保护 Sheet 硬熔断）。

适用谁：EU AM 团队负责人、招商效率复盘同学、需要做 AM 分层与瓶颈定位的分析同学。

## 🔑 触发词

- 核心关键词：

  - EU AM 效率
  - AM 漏斗诊断 / 招商漏斗
  - 气泡矩阵 / 四象限 AM 分层
  - 入驻率 / 意愿→入驻转化率
  - 明细_分析基盘
- 典型指令示例：

  > 分析一下 EU AM 的招商效率，出个气泡矩阵  
  > 按行业拆一下 AM 的入驻率和意愿转化率，定位瓶颈环节

## ⚙️ 核心架构 / SOP / 约束条件

```text
飞书分层读写架构（3 底表 + 3 阅读视图）--(MCP lark-sheets)--> DataFrame / CSV
   数据源：https://bytedance.my.larkoffice.com/sheets/RvpVsoUODhqCXJt4rFgm1M6ky2e
   优先读：【2.AM看板】（sheet=t5m7r4）或 【2.AM底表】（sheet=8953af）
   └─> am_analysis_core.py（纯计算：阶段表 / 段转化 / 瓶颈 / 对标 / 零信任校验）
         └─> run_funnel_diagnosis.py（薄封装 CLI + L3 运行时断言）--> result.json
   └─> render_bubble_matrix.py --> 白底 ECharts HTML（聚焦版 / 全轴版）+ PNG + data.json
```

**Step 1 · 读取分析基盘**：分层数据基盘 `https://bytedance.my.larkoffice.com/sheets/RvpVsoUODhqCXJt4rFgm1M6ky2e`  
优先读取：`【2.AM看板】`（sheet=t5m7r4）；全量分析时读 `【2.AM底表】`（sheet=8953af）。  
读取必须走 MCP `lark-sheets` 链路（`lark-cli sheets +csv-get`），禁止裸调飞书 OpenAPI；涉及飞书的脚本调用必须 `include_secrets=true`。  
受保护 Sheet（禁止写入）：`历史入驻`、`AM分析（原分析基盘_阅读视图）`。

**Step 2 · 计算漏斗指标**：

| 指标 | 口径 |
|-|-|
| 线索量 | 该 AM 名下线索行数 |
| 有意愿数 | 意愿标记为「有意愿」的行数 |
| 主口径入驻数 | EU / UK 入驻时间字段**有值** |
| 备用口径入驻数 | 入驻状态 = `5-已入驻` |

派生：主口径入驻率 = 主口径入驻 / 线索量；备用口径意愿→入驻转化率 = min(备用口径入驻, 有意愿) / 有意愿。

**Step 3 · 渲染气泡矩阵**：横轴 = 主口径入驻率，纵轴 = 备用口径意愿→入驻转化率，气泡大小 = 线索量；分界线取**有效 AM**（主口径入驻 > 0）中位数；四象限 = 明星（右上）/ 精耕小池（左上）/ 规模待提效（右下）/ 待突破（左下）。支持全行业总览 + 分行业 Tab 切换。背景强制白底 `#FFFFFF`。

**Step 4 · 口径说明（不可省）**：数据截止日期、剔除规则（如剔除罗才鑫）、灰色 AM 逻辑（入驻时间待回填 → 落备用口径、灰色气泡、标注需复核、不参与中位数）、主/备用口径定义、有效 AM 数与灰色 AM 数。

**约束条件（三层护栏）**：

- L1 认知层：SKILL.md 顶部固化 Common Rationalizations / Red Flags / Verification 三件套。
- L2 默认层：合规默认值（数据源、工作表名、默认维度 `负责AM`、剔除名单、白底 `#FFFFFF`、零信任默认开启）。
- L3 断言层：`run_funnel_diagnosis.py` 在落盘前执行 `validate_input_path` / `validate_snapshots` / `validate_zero_trust_passed` / `validate_output_written`，任一失败 `raise` 熔断（退出码 2）。
- 零信任校验 FAIL 禁止导出结果或对外交付；白底断言要求 PNG 四角像素 `(255,255,255)`、HTML 含 `backgroundColor` 且不含 `111111`。

**能力归属如实说明**：漏斗阶段诊断能力内聚在 `scripts/am_analysis_core.py`；本技能不存在独立的 `funnel_stage_analyzer.py`（源项目磁盘上亦无该文件）。`scripts/run_funnel_diagnosis.py` 是围绕 `run_diagnosis` 新写的薄封装 CLI，并非从旧文件迁移。

## 🔄 数据源同步链路（v1.2.4 新增）

真实数据源（多维表格）：[EU AM 源表](https://bytedance.my.larkoffice.com/base/MPN9bUhBTaUsgcsrN92m2Oq0yde?table=tbl5IlstItZOpInx&view=vewm2HQxRS)（base_token=MPN9bUhBTaUsgcsrN92m2Oq0yde，table_id=tbl5IlstItZOpInx）

- ETL 同步脚本：`projects/eu-am-efficiency/source_sync.py`（幂等：Pass A 文本清底 + Pass B typed 全量重写；禁用 `+cells-clear`，禁止新建/复制/删除 sheet）
- 技能内入口：`scripts/sync_source_entry.py`（L3 断言：真相源缺失即 raise FileNotFoundError，存在则子进程转发，不复制副本）
- 同步频率：每日工作日 08:50 CST（cron: `50 8 * * 1-5`，须使用绝对路径 `/usr/local/bin/lark-cli`）
- 同步目标：明细_分析基盘（全量重写）/ 元数据与质检（追加同步日志）
- 过滤口径：AM优先级=AM招商推进 且 历史入驻≠1；历史入驻=1 仅记数不入基盘
- 长整型字段：EU/UK_global seller id、EU/UK_匹配global_seller_id 一律 dtype=object（文本格式 @）
- 零信任门禁：行数断言 / 关键字段空值率<5%（负责AM、seller_id[已入驻口径]、AM优先级）/ RAW 抽 10 行 0 差异；任一 FAIL → 写失败日志并非 0 退出

真机验证：源 8496 行 → 明细_分析基盘 1423 行 / 历史入驻 1832 行，三项质检全 PASS，幂等连跑两次结果一致。

## 🗂 分层读写架构：3 底表 + 3 阅读视图（v1.2.4 新增）

自 v1.2 起，数据同步从「1 底表 + 1 阅读视图」升级为**人机分层读写**架构：底表层给机器（106 列全字段、每日幂等覆盖），阅读层给人（38 列固定表头、公式动态引用）。

```text
多维表格源（106 字段 / 8496 行）
   └─ build_layered_sheets.py --layer base   ← 机器层：3 张底表，106 列全字段，每日幂等覆盖
        ├─ 【1.全量底表】            8496 行  无筛选（全量快照，含历史入驻）
        ├─ 【2.AM底表】     AM优先级 == "AM招商推进" & 历史入驻 != 1
        └─ 【3.BD底表】              负责BD 非空 & 历史入驻 != 1
   └─ build_layered_sheets.py --layer view   ← 人类层：3 张阅读视图，38 列固定表头
        ├─ 【1.全量看板】        → 【1.全量底表】         （8496 行）
        ├─ 【2.AM看板】  → 【2.AM底表】  （1906 行）
        └─ 【3.BD看板】          → 【3.BD底表】           （1480 行）
   受保护不可写：历史入驻、AM分析
```

目标电子表格：[EU AM 分层同步表（3 底表 + 3 阅读视图）](https://bytedance.my.larkoffice.com/sheets/RvpVsoUODhqCXJt4rFgm1M6ky2e)

### Sheet 台账（sheetId 为线上事实，写入前仍须 `+workbook-info` 复核）

| 层 | Sheet 名 | sheetId | 行数 | 列 | 筛选口径 / 引用来源 |
|-|-|-|-|-|-|
| 底表 | `【1.全量底表】` | `YNN8uk` | 8496 | 106 | 无筛选（源全量快照，**含历史入驻商家**） |
| 底表 | `【2.AM底表】` | `8953af` | 动态\* | 106 | `AM优先级 == "AM招商推进" & 历史入驻 != 1`（v1.2.2 起追加剔除历史入驻商家） |
| 底表 | `【3.BD底表】` | `MpyNOP` | 动态\* | 106 | `负责BD` 非空（非 None / 非空串 / strip 后非空） `& 历史入驻 != 1`（v1.2.2 起追加剔除历史入驻商家） |
| 阅读 | `【1.全量看板】` | `KYImDl` | 8496 | 38 | 引用 `【1.全量底表】` |
| 阅读 | `【2.AM看板】` | `t5m7r4` | 动态\* | 38 | 引用 `【2.AM底表】` |
| 阅读 | `【3.BD看板】` | `JC5aOe` | 动态\* | 38 | 引用 `【3.BD底表】` |
| 🔒 受保护 | `历史入驻` | `Tc3dvL` | — | — | **只读**，任何写入/clear 立刻熔断 |
| 🔒 受保护 | `AM分析` | `M45mLI` | — | 38 | **只读**（原名「分析基盘_阅读视图」，线上已被人工改名） |

\* 自 v1.2.2 起，`【2.AM底表】` / `【3.BD底表】` 追加筛选条件 `历史入驻 != 1`（剔除历史入驻商家），实际行数以下次同步的 `layered_result.json` 为准（剔除前分别为 1906 / 1480 行）；`【1.全量底表】` 保留全量快照语义，不加任何新筛选。

阅读视图公式形态（按字段名动态引用，抗源表列序变动）：

```text
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

1. **写入前必须** `+workbook-info` **取真实 sheet 名/ID**，绝不凭上下文里的名字直接写——实测线上 sheet 已被人工改名（`分析基盘_阅读视图` → `AM分析`）。
2. `+cells-clear` **打不存在的 sheet 会** `900015206` **熔断** → 先判存在再 clear；不存在的子表交给 `+table-put` 自动创建。
3. `+formula-verify` **单次扫描上限 20 万单元格**：大表返回 `status=partial` + `has_more=true` 时 `total_errors=0`**不可信**，必须 `--range` 分段复扫，并校验 `Σtotal_formulas == 行数 × 38`。
4. **INDEX 行上界必须按底表实际行数参数化**，禁止硬编码（旧 `build_reading_view.py` 写死 `$DB$1423`，是本条护栏的反例来源）。
5. `MATCH(表头名, 底表!$A$1:$DB$1, 0)` **的上界** `$DB` **恰好等于 106 列**：源表新增字段导致超过 106 列时必须同步放宽上界，否则新字段会静默 MATCH 不到。
6. **长整型 ID 强制文本**：`seller_id` / `shop_id` / `leads_id` / `临时id` / 任意含 `id` 的字段一律 `dtypes:object`（文本 `@`），并以「15 位数值阈值」兜底识别漏配字段。
7. `PROTECTED` **白名单在所有写入入口** `guard()` **硬熔断**（`历史入驻` / `AM分析`），不依赖人工小心。
8. **质检口径按底表分别配置断言阈值**：`负责AM` / `AM优先级` 空值率 <5% **只适用于 AM 相关底表**；`【1.全量底表】`（77% 无 AM）与 `【3.BD底表】`（72% 无 AM）是源数据事实，不构成 FAIL。`【3.BD底表】` 的硬断言是 **负责BD 非空率 == 100%**。

### 分层架构验收口径（涉及数据同步时强制）

- 6 张 Sheet 行数与 `layered_result.json` 一致；
- 每个阅读视图 `Σtotal_formulas == 行数 × 38`；
- `PROTECTED` Sheet 零写入；
- `overall == true`。

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：

```text
分析一下 EU AM 的招商效率，出个气泡矩阵
```

- 🤖 标准输出：

```text
1. MCP lark-sheets 读取「明细_分析基盘」→ 24 位 AM（已剔除罗才鑫）
2. run_funnel_diagnosis.py 退出码 0，零信任校验 PASS（双路重算一致 + 漏斗单调）
3. 白底 ECharts 气泡矩阵：聚焦版 am_bubble_v2_clip.html / 全轴版 am_bubble_v2_preview.html + PNG
   分界线 = 有效 AM 中位数；四象限：明星 / 精耕小池 / 规模待提效 / 待突破
4. 附口径说明：数据截止日期、剔除规则、灰色 AM（入驻时间待回填，走备用口径，需复核）
```

## 🧾 变更记录

- **v1.2.2**：`【2.AM底表】`、`【3.BD底表】` 新增筛选条件「`历史入驻 != 1`」，剔除历史入驻商家；`【1.全量底表】` 不变（保留全量快照语义）。实现上 `filter_records()` 新增 `is_hist_settled()` 判定，经 `norm_scalar` 归一化，兼容数字 `1` / 浮点 `1.0` / 字符串 `"1"` / 带空格 `" 1 "` / 布尔 `True` 五种存储形态。
- **v1.2**：数据同步架构由「1 底表 + 1 阅读视图」升级为「3 底表 + 3 阅读视图」人机分层读写（底表层 106 列全字段每日幂等覆盖：【1.全量底表】 8496 行 / 【2.AM底表】 1906 行 / 【3.BD底表】 1480 行；阅读层 38 列固定表头 + INDEX+MATCH 按字段名动态引用）；`【2.AM底表】` 筛选口径改为仅 `AM优先级 == "AM招商推进"`（不再叠加 `历史入驻 != 1`，1422 → 1906 行）；`历史入驻` / `AM分析` 列为受保护只读 Sheet；沉淀 8 条工程护栏；新增技能内薄壳入口 `scripts/layered_sync_entry.py`（L3 断言 + 子进程转发到 `projects/eu-am-efficiency/build_layered_sheets.py`）。
- **v1.1**：补齐真实数据源 ETL 同步链路（多维表格 → 明细_分析基盘 每日工作日 08:50 CST 全量重写，幂等 Pass A/Pass B），并内置三项零信任门禁（行数断言 / 关键字段空值率<5% / RAW 抽 10 行 0 差异，任一 FAIL 即非 0 退出）；新增技能内 L3 入口脚本 `scripts/sync_source_entry.py`。
- **v1.0**：首版。内核 `am_analysis_core.py`（含零信任双路重算与漏斗单调性断言）+ 白底渲染层 `render_bubble_matrix.py` + 薄封装 CLI `run_funnel_diagnosis.py`（L3 断言熔断）；补齐 L1 反合理化三件套与 L2 合规默认值。

## 📝 使用案例 & 踩坑记录

> 💡 此区域为人工沉淀区（Preserve Zone），forge 不会覆盖，请在此记录使用案例、踩坑与注意事项。

[待补充使用案例]

## 📋 更新日志

> 📌 此区域为更新日志区（Append Zone），forge 每次发布后自动追加，请勿手动修改已有条目。

- **V1.2.4**：forge 流水线发布（详见 SKILL.md 更新日志）。