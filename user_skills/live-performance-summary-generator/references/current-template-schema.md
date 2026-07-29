# 当前官方模版 Schema（2026-06-19）

## Spreadsheet

- 标题：`Live 场次分析：FGUK`
- URL：`https://dyqe3ary97.larksuite.com/sheets/VVeQshKyvhyK7stx4gbuqOQ4sBb`

## 工作表清单

1. `1. 数据底表`（sheet id: `cfc575`）
2. `2. 计算汇总`（sheet id: `YKHVS`）

## 1. 数据底表结构

- 第 1 行：banner / date range
- 第 2 行：真实表头
- 第 3 行起：raw 数据区（官方模版已清空，等待粘贴）
- 冻结：2 行，0 列

### 当前真实表头（A:AE）

| 列 | 字段名 |
|---|---|
| A | Room ID |
| B | Live Name |
| C | TT UID |
| D | TT Handle |
| E | Country |
| F | Start Timestamp |
| G | End Timestamp |
| H | Start Timestamp(Local Time) |
| I | End Timestamp(Local Time) |
| J | Duration(s) |
| K | CL GMV |
| L | CL GMV USD |
| M | Show PV |
| N | Valid CL Watch PV |
| O | Enter room rate |
| P | Valid CL CTR |
| Q | Valid CL C_O |
| R | AOV(Main) |
| S | AOV(Main)(USD) |
| T | Show GPM |
| U | Show GPM(USD) |
| V | Buyers |
| W | Paid Orders |
| X | Valid CL Viewers |
| Y | New Buyers |
| Z | Like rate |
| AA | Live comment rate |
| AB | Follow rate |
| AC | Share rate |
| AD | Watch Duration(AVG.) |
| AE | Valid CL Watch Duration(AVG.) |

## 2. 计算汇总结构

- 冻结：2 行，2 列
- 合并：`B1:K1`、`L1:P1`
- 第 1 行分区：`基础数据` / `互动指标｜Fashion Live 过程指标优化2505`
- 第 2 行表头：
  - A `Handle`
  - B `日期`
  - C `GMV`
  - D `时均GMV`
  - E `时均show PV /K`
  - F `开播小时`
  - G `Show GPM`
  - H `ERR`
  - I `CTR`
  - J `C_O`
  - K `AOV`
  - L `Watch Duration(AVG.)>55秒`
  - M `Follow rate >1%`
  - N `Like rate >500%`
  - O `Share rate \n观察持续提升`
  - P `Comment rate >5%`

## 当前汇总映射基线

- Handle → D (`TT Handle`)
- 日期 → F (`Start Timestamp`)
- GMV → K (`CL GMV`)
- 时均GMV → `CL GMV / 开播小时`
- 时均show PV /K → `Show PV / 开播小时 / 1000`
- 开播小时 → `Duration(s) / 3600`
- Show GPM → T (`Show GPM`)
- ERR → O (`Enter room rate`)
- CTR → P (`Valid CL CTR`)
- C_O → Q (`Valid CL C_O`)
- AOV → S (`AOV(Main)(USD)`)
- Watch Duration(AVG.)>55秒 → AE (`Valid CL Watch Duration(AVG.)`)
- Follow rate >1% → AB (`Follow rate`)
- Like rate >500% → Z (`Like rate`)
- Share rate 观察持续提升 → AC (`Share rate`)
- Comment rate >5% → AA (`Live comment rate`)

## Benchmark 规则

- L `< 55` 标红
- M `< 0.01` 标红
- N `< 5` 标红
- O 不标红，仅观察
- P `< 0.05` 标红
