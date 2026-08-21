# am_analysis_core —— EU AM 效率分析核心引擎

> 来源：EU AM 效率专项分析页 `am-funnel-diagnosis`（#s1~#s7）的分析逻辑代码化。
> 定位：「EU AM效率分析」技能 1.0 的**计算内核**，与渲染层（HTML / 飞书文档 / ECharts）完全解耦。
> 文件：`projects/eu-am-efficiency/am_analysis_core.py`（纯计算，无网络、无副作用）

---

## 1. 分析逻辑总览（结构化描述）

### 1.1 输入数据格式

标准输入 `snapshots`：**两周快照**，纯 Python / JSON 结构。

```python
snapshots = {
    "period_old": "W31",          # 可选，仅展示
    "period_new": "W32",
    "total_label": "大盘总计",     # 可选，默认「大盘总计」
    "entities": {                 # key = 实体名（行业 / AM / 国家…）
        "Fashion":     {"old": [550, 424, 139, 75, 31], "new": [526, 420, 176, 112, 56]},
        "Home&Living": {"old": [496, 243,  65, 11,  8], "new": [486, 440,  91,  18,  9]},
    },
    "total": {"old": [1434, 1005, 259, 97, 44],         # 可选，缺省由 entities 加总
              "new": [1363, 1194, 357, 145, 70]},
}
```

- 每个 list 的元素顺序**必须严格对应** `FunnelSpec.stages`。
- 缺失值**禁止用 0 填充**，会直接抛 `ValueError`（零信任口径）。
- 若手上是明细表 / 汇总表（DataFrame），用 `build_snapshots_from_dataframe()` 转换。

### 1.2 漏斗定义 `FunnelSpec`

| 参数 | 说明 | 默认（EU AM 招商口径） |
|---|---|---|
| `stages` | 阶段名，自上而下有序，首个为线索池 | 线索数 → 已触达 → 有意愿 → 新增入驻 → 新增入驻可售 |
| `segment_names` | 环节段名，长度 = 阶段数 - 1 | 线索→已触达 / 已触达→有意愿 / 有意愿→新增入驻 / 新增入驻→可售 |
| `rate_names` | 段转化率业务别名 | 触达率 / 意愿率 / 入驻率 / 可售转化率 |
| `weights` | 机会点排序的环节业务权重 | 0.6 / 1.0 / 2.5 / 3.0（越下游越值钱） |
| `min_samples` | 实体进入分析的最小线索数 | 5 |
| `min_benchmark_samples` | 实体可作标杆的最小线索数 | 15 |

### 1.3 处理步骤（8 步流水线）

| # | 步骤 | 函数 | 核心口径 |
|---|---|---|---|
| 1 | 阶段层计算 | `compute_stage_table` | Δ = 新周 - 旧周；Δ% = Δ / 旧周 × 100；新周占线索比 |
| 2 | 环节段层计算 | `compute_segment_table` | 段转化率 = 下一阶段 / 当前阶段 × 100；Δpt = 新周率 - 旧周率；绝对流失 = 当前阶段 - 下一阶段 |
| 3 | 瓶颈 / 收益定位 | `locate_bottleneck_and_gain` | 🔴 最大瓶颈 = 新周段转化率最低段；🟢 做功收益 = Δpt 最大段；另给最大绝对流失段（区分「率低」vs「量大」） |
| 4 | 阶段画像定性 | `classify_phase` | 做功重心 = 做功环节中 Δ 最大者 → 映射为 触达攻坚期 / 意愿堆积期 / 入驻卡点期 / 可售收割期；全环节 Δ ≤ 0 → 「无做功」 |
| 5 | 做功热力矩阵 | `build_heat_matrix` | 行 = 实体，列 = 做功环节，值 = Δ%（或 Δ）。绿 = 强做功，灰 = 零增量，红 = 负增长 |
| 6 | 漏斗几何比例 | `build_funnel_geometry` | 宽度**严格正比**于绝对值（无最小宽度补偿）；层高正比于该段体量占比；`abs` 跨实体共用基准 / `norm` 自身归一化 |
| 7 | 瓶颈排序 | `rank_bottlenecks` | 按新周最低段转化率升序；率低且逆势下跌 = 🔴🔴 |
| 8 | 机会点量化 | `quantify_benchmark_uplift` | 标杆拉平法：增量 = (标杆率 - 当前率)/100 × 段起始量；权重增量 = 增量 × 环节权重；剔除转化率 ≥ 100% 的定向池实体作标杆 |
| ✅ | 零信任校验 | `validate_zero_trust` | ① 双引擎（dict 累加 vs pandas 聚合）逐阶段对账，容差 0.05%；② 各实体加总 == 大盘；③ 漏斗单调性；④ 空值/负值扫描 |

### 1.4 关键口径红线（承自分析页 #s7）

1. **首阶段（线索数）变动不计入做功判定** —— 线索数下降系清库 / 去重，非线索流失。做功判定只看 `act_stages`（已触达 / 有意愿 / 新增入驻 / 新增入驻可售）。
2. **入驻 / 可售为累计新增口径**（已剔除存量），Δ 反映本周净新增。
3. **分母为 0 一律返回 `NaN`**，绝不返回 0 冒充「零转化」。
4. **本引擎不做归因**，只出瓶颈定位与量化增量；卡点原因需业务侧确认。

### 1.5 输出格式

`run_diagnosis()` 返回一个 dict，渲染层可直接消费：

| key | 类型 | 内容 |
|---|---|---|
| `meta` | dict | 口径与参数快照（阶段、权重、门槛、周期标签、口径说明） |
| `stage_table` | records | 阶段明细（对应页面 #s5 基础数据表） |
| `segment_table` | records | 环节段转化明细（对应 #s5b） |
| `focus` | records | 每实体的瓶颈段 / 收益段 / 最大流失段 |
| `phase` | records | 阶段画像 + 做功重心 |
| `heat_matrix` | nested dict | 做功热力矩阵（对应 #s3） |
| `bottleneck_rank` | records | 跨实体瓶颈排序（对应 #s2 顶部排行） |
| `opportunity` | records | Top N 标杆拉平机会点 |
| `funnel_geometry` | dict | 各实体梯形漏斗真实比例（对应 #s2 自绘 SVG） |
| `validation` | dict | `{checks, asserts, check_count, fail_count, fail_detail, passed}` |

`export_json(result, path)` 落盘时自动把 `NaN` 转为 `null`。

---

## 2. 调用方式

### 2.1 最短路径（已有两周汇总数字）

```python
from am_analysis_core import FunnelSpec, run_diagnosis, export_json

result = run_diagnosis(
    snapshots,
    spec=FunnelSpec.default(),
    dim_name="行业",        # 分组维度展示名
    top_n_opportunity=8,
    strict=True,            # 校验 FAIL 直接抛异常（生产强制模式）
)
export_json(result, "step_result.json")
```

### 2.2 从明细表进入（一行一条线索）

```python
import pandas as pd
from am_analysis_core import FunnelSpec, build_snapshots_from_dataframe, run_diagnosis

spec = FunnelSpec.default()
snapshots = build_snapshots_from_dataframe(
    df_old=pd.read_csv("db_w31.csv"),
    df_new=pd.read_csv("db_w32.csv"),
    spec=spec,
    dim_col="EU行业",
    stage_cols={               # spec 阶段名 → 实际列名；首阶段缺省按行数计
        "已触达": "已触达",
        "有意愿": "有意愿",
        "新增入驻": "已入驻",
        "新增入驻可售": "可售数",
    },
    period_old="W31", period_new="W32",
)
result = run_diagnosis(snapshots, spec, dim_name="行业")
```

### 2.3 换维度：AM 个人效率诊断

引擎是维度无关的，把 `dim_col` 换成 `负责AM` 即可复用全套逻辑：

```python
snapshots_am = build_snapshots_from_dataframe(df_old, df_new, spec, dim_col="负责AM", ...)
result_am = run_diagnosis(snapshots_am, spec, dim_name="负责AM")
# 此时 opportunity 即为「某 AM 某环节拉到组内标杆可多产出多少家」
```

### 2.4 换漏斗：自定义阶段

```python
spec = FunnelSpec(
    stages=("线索数", "已触达", "有意愿", "已入驻"),
    rate_names=("触达率", "意愿率", "入驻率"),
    weights=(0.6, 1.0, 2.5),
    min_samples=3, min_benchmark_samples=10,
)
result = run_diagnosis(snapshots, spec, dim_name="国家",
                       phase_names=("触达攻坚期", "意愿堆积期", "入驻卡点期"))
```

### 2.5 自检 / 回归

```bash
python3 projects/eu-am-efficiency/am_analysis_core.py
```

模块内置 `DEMO_SNAPSHOTS`（分析页真实数据）与硬回归断言：大盘四率 87.6 / 29.9 / 40.6 / 48.3、触达段 Δpt +17.5、3C 入驻段 3.5% / -4.8pt / 流失 55 家。当前跑通结果：**31 项校验 0 FAIL，断言全部通过**。

---

## 3. 依赖

- Python ≥ 3.8
- `pandas`

（DuckDB 不再是必需项：双引擎对账已改为 `dict 累加 × pandas 聚合` 的异构双路重算，去掉了外部依赖。）

---

## 4. 边界与已知限制

- **不含归因**：只定位瓶颈与量化增量，不推断卡点原因。
- **不含渲染**：`funnel_geometry` 只给 0~1 的比例数字，SVG / ECharts 由渲染层生成。
- **标杆法的样本前提**：同组内至少 1 个实体线索数 ≥ `min_benchmark_samples`，否则该环节机会点为空。
- **累计口径依赖上游**：若上游看板把「新增入驻」改为存量口径，Δ 的业务含义会失真，需同步调整 `stages` 与口径说明。
- **单调性 FAIL 不阻断计算**（除 `strict=True`），会在 `validation.fail_detail` 中显性暴露，供人工修数。
