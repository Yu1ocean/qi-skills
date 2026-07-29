---
name: v6-panoramic-chart-generator
description: 生成 v6 全景断轴图的制图方案与配置，突出长尾层级和结构占比。适用于长尾业务看板、分层经营复盘、GMV 结构分析与汇报制图场景。
---

# v6-panoramic-chart-generator

将“长尾放大看数”的 v6 规则沉淀为可复用的出图 SOP：把**头部冲顶**与**尾部细节**在同一张图里“同时可读”。

## 什么时候用

- 需要同时看清 **头部极大值** 与 **长尾细节波动**（线性轴会让尾部贴地）。
- 需要按商家/商品/作者等实体做 **日均 GMV 分层（T0-T6）**，并观察层级结构变化。
- 汇报中需要**图例不占空间**（内联图例拼接到图面），且结构占比不要被压缩。

## 输入数据约定（CSV）

至少包含以下列（列名可通过参数映射）：
- 日期列：date（可被解析为日期）
- 实体列：entity（商家/商品/作者/门店等）
- GMV 列：gmv（数值）

可选：订单数、曝光等指标列可先忽略，本 Skill 默认聚焦 GMV。

## 核心规则（v6）

1. **基于日均 GMV 自动打标 T0-T6**
   - 先算每个实体在分析窗口的 `daily_avg_gmv = sum(gmv)/active_days`（active_days 为出现过数据的日期数）。
   - 用分位点自适应切分为 7 档（T0 最头、T6 最尾），默认分位点：50/80/90/95/98/99.5。

2. **长尾断轴（Broken Axis）**
   - 针对 GMV 量级长尾，用两处断点（默认 P90、P99）做分段线性压缩。
   - 图上展示的是“映射后的值”，坐标轴标签展示“反映射后的真实值”。

3. **T1-T5 占比非线性分割防压缩**
   - 针对占比落在 0%~几个百分点的层级，使用分段映射让低占比获得更多屏幕高度。
   - 同样采用“值映射 + 轴反映射”的方式保持读数真实。

4. **内联图例拼接（Inline Legend Splicing）**
   - 关闭默认 legend（或放到图外），改用 `graphic` 在图内拼接色块+文案，避免挤占有效绘图区。

## 使用方式（脚本）

运行脚本从 CSV 生成：T 分层结果 + 两张图的 ECharts option（JS）。

```bash
python3 scripts/gen_v6_panoramic_echarts.py \
  --input "数据文件.csv" \
  --date_col date \
  --entity_col entity \
  --gmv_col gmv \
  --output_dir output
```

输出物：
- output/tiers.csv：实体→T 档映射（含 daily_avg_gmv）
- output/panoramic_gmv_option.js：GMV 断轴版趋势图 option
- output/panoramic_share_option.js：占比非线性版趋势图 option
- output/v6_meta.json：本次计算用到的阈值、断轴断点、映射参数

## 参考文档

- 规则总览与口径解释：references/v6-chart-philosophy.md
- 断轴/非线性映射的实现约定：references/v6-axis-mapping.md
