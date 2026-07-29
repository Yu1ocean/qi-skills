# 公式映射与动态生成规则（V1.2）

> V1.2 起：raw sheet 列字母**不再硬编码**，全部由 raw 表头行 → 字段语义动态推导。

## 行规则

- 第 1 行：分区标题行（`基础数据` / `互动指标｜...`）
- 第 2 行：summary 字段表头
- 第 3 行起：公式行
- 动态终点：以 raw sheet 实际最后一个非空数据行为准，不写死 38 行
- 清理策略：当历史 summary 比本次更长时，先清空 `A1:P{clear_end_row}` 再整体重写，避免遗留旧公式和旧样式

## 字段语义 → 候选表头别名

脚本会按以下优先级匹配 raw sheet 表头（去空白/标点、忽略大小写）：

| 字段语义 key | 候选表头（按命中优先级） |
|---|---|
| `handle` | `TT Handle` / `Handle` / `Account Handle` |
| `date` | `Start Timestamp` / `Live Start Time` / `Start Time` |
| `duration_sec` | `Duration(s)` / `Duration (s)` / `Live Duration(s)` |
| `cl_gmv` | `CL GMV` / `GMV` / `CL_GMV` |
| `show_pv` | `Show PV` / `ShowPV` |
| `show_gpm` | `Show GPM` / `Show GPM(USD)` / `Show GPM (USD)` |
| `enter_room_rate` | `Enter room rate` / `ERR` / `Enter Room Rate` |
| `valid_cl_ctr` | `Valid CL CTR` / `CTR` / `CL CTR` |
| `valid_cl_co` | `Valid CL C_O` / `C_O` / `CL C_O` |
| `aov` | `AOV(Main)(USD)` / `AOV(Main)` / `AOV(USD)` / `AOV` |
| `watch_duration_avg` | `Valid CL Watch Duration(AVG.)` / `Watch Duration(AVG.)` / `Watch Duration (AVG.)` |
| `follow_rate` | `Follow rate` / `Follow Rate` |
| `like_rate` | `Like rate` / `Like Rate` |
| `share_rate` | `Share rate` / `Share Rate` |
| `comment_rate` | `Live comment rate` / `Comment rate` / `Live Comment Rate` |

## Summary 列 → 字段语义

| Summary 列 | 字段语义 key | 公式行为 |
|---|---|---|
| A | handle | 直通 |
| B | date | `DATEVALUE(LEFT(...,10))` |
| C | cl_gmv | 直通 |
| D | （派生）C/F | 时均 GMV |
| E | show_pv | show_pv / F / 1000 |
| F | duration_sec | duration_sec / 3600 |
| G | show_gpm | 直通 |
| H | enter_room_rate | 直通 |
| I | valid_cl_ctr | 直通 |
| J | valid_cl_co | 直通 |
| K | aov | 直通 |
| L | watch_duration_avg | 直通 |
| M | follow_rate | 空值兜底 + `*1` 转数值 |
| N | like_rate | 空值兜底 + `*1` 转数值 |
| O | share_rate | 空值兜底 + `*1` 转数值 |
| P | comment_rate | 空值兜底 + `*1` 转数值 |

> 公式生成逻辑见 `scripts/generate_summary_sheet.py::build_formula_for_cell`。

## 表头布局

- `A1`：`基础数据`
- `B1:K1`：`自动计算，在【1. 数据底表】贴入数据即可`
- `L1:P1`：URL 对象 `{"type":"url","text":"互动指标｜Fashion Live 过程指标优化2505","link":"https://bytedance.sg.larkoffice.com/docx/DzfedikUGoxzT0x6dqklQAFogsh"}`
- 第 2 行表头：`Handle / 日期 / GMV / 时均GMV / 时均show PV /K / 开播小时 / Show GPM / ERR / CTR / C_O / AOV / Watch Duration(AVG.)>55秒 / Follow rate >1% / Like rate >500% / Share rate \n观察持续提升 / Comment rate >5%`

## 实现约束

- 公式必须以飞书表格支持的对象格式写入：`{"type":"formula","text":"=..."}`
- 运行时只允许通过 `inner_skills/lark-sheets/bin/lark-sheets-cli` 读写飞书表格
- 允许使用导出的本地 xlsx 计算"最后一行"和 benchmark 命中范围，但不得直连 OpenAPI
- 所有 raw 列字母必须经过【表头识别 → 字段映射】解析得到，禁止在脚本里写死 `D` / `AF` / `AC` 等字面量
- 写入完成后强制 RAW 回读 `A1:P2` 与首尾数据行做断言式校验
