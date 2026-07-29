# 样式、颜色与 benchmark 规则（V1.2）

## 基础样式

必须满足以下硬规则：

1. 所有文字使用黑色：`#000000`
2. `A1:K2` 使用浅绿色底：`#E2F0D9`
3. `L1:P2` 使用浅黄色底：`#FFF2CC`
4. benchmark 未达标的过程指标单元格使用浅红底：`#F4CCCC`
5. 冻结设置：2 行、2 列

## benchmark 规则

按**原始数值**判断，不按单元格展示文本判断：

| Summary 列 | 指标 | 对应字段语义 | 阈值 | 动作 |
|---|---|---|---|---|
| L | Watch Duration(AVG.) | `watch_duration_avg` | `< 55` | 浅红底 |
| M | Follow rate | `follow_rate` | `< 0.01` | 浅红底 |
| N | Like rate | `like_rate` | `< 5` | 浅红底 |
| O | Share rate | `share_rate` | 暂无 benchmark | 不标红 |
| P | Comment rate | `comment_rate` | `< 0.05` | 浅红底 |

> 字段语义 → raw 列字母由 `detect_header_mapping` 在运行时动态解析，详见 `formula-mapping.md`。

## 建议格式化

为兼顾样例表现与 CLI 兼容性，主脚本对以下列强制设置 formatter：

- `B`：`yyyy/MM/dd`（日期）
- `C`-`G`、`K`：`0`（数字无小数点）
- `H`-`J`：`0%`（百分比无小数点）
- `M`、`N`、`O`、`P`：`0%`（百分比无小数点）

其他排版规则：

- 第 2 行（表头行）：设置自动换行（`wrapStrategy: WRAP`）
- `O2`：表头文案必须保留换行，使用 `Share rate \n观察持续提升`
- `E` 列：展示 `时均show PV /K`，公式逻辑为 `show_pv / 开播小时 / 1000`
- `C`-`K` 列：列宽 65px
- `L1` 单元格：内容为带超链接的 URL 对象，指向 Fashion Live 过程指标优化文档
- `2. 计算汇总` 默认位于第 2 个工作表位置（raw sheet 之后）

说明：

- 经过真实验证，`yyyy/MM/dd`、`0%`、`0` 可以稳定通过现有 CLI。
- 列宽通过 `+update-dimension --dimension COLUMNS --fixed-size 65` 设置。

## 脏数据清理策略

因为历史 summary 可能保留比本次更长的公式区，所以每次执行都要：

1. 先解除 `B1:K1`、`L1:P1` 合并；
2. 清空 `A1:P{clear_end_row}` 的值；
3. 清空同范围样式；
4. 重写表头、公式、合并和新样式；
5. 再按 benchmark 命中范围上红底。
