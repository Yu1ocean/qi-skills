## 📌 技能简介
`interview-matrix-evaluator`（候选人矩阵对比评审会）用于把多份 `interview-hologram-scanner` 标准化 JSON 放到同一决策坐标系中做横向评审。它不是简单汇总器，而是一个围绕**统一 JD / 业务北极星指标 / must-have 能力项**做排序决策、风险横评和 trade-off 拆解的决策主脑。

<callout icon="bulb" bgc="3">  
**一句话定位：** 先做输入校验和锚点统一，再做能力雷达叠图与长短板差异分析，接着跑零信任风险矩阵，最后输出录用顺位、关键权衡理由与补面建议。  
</callout>

**版本：v1.1**

## 🔑 触发词
- **核心关键词**
  - 候选人矩阵对比
  - 面试评审会
  - 候选人横向排序
  - 录用顺位
  - 风险矩阵横评
- **典型指令示例**
  - 用 `interview-matrix-evaluator` 对这 3 个候选人的 scanner JSON 做横评，按可售商家数目标给我排顺位。
  - 基于统一 JD 和北极星指标，对多个候选人做能力雷达叠图、风险矩阵和最终录用建议。

---

## ⚙️ 核心架构 / SOP / 约束条件

### 1. 输入定义
- **必填输入**：至少 2 份 `interview-hologram-scanner` 标准化 JSON
- **建议一并提供**：JD / Role Expectation、业务北极星指标、must-have 能力项、风险容忍度
- 若输入字段缺失，必须标记为 `NULL`，不得脑补。

### 2. 四段式工作流
#### 2.1 输入校验与锚点统一
- 确认每份输入都来自 `interview-hologram-scanner`
- 对齐 JD、北极星、must-have 能力项与权重口径
- 若候选人口径不一致，必须显式下调结论置信度

#### 2.2 能力维度归一化与雷达叠图
- 默认统一比较 6 个维度：业务理解、结构化拆解、数据敏感度、推动力、协同影响力、学习迭代力
- 为每位候选人抽取长板、短板、比较优势
- 维度缺失时写 `NULL`，不得造分

#### 2.3 零信任风险横评
至少检查以下四类问题：
- **证据稀薄区**：分值背后证据是否足够
- **逻辑盲区**：是否只讲结果，不讲动作与归因
- **基准漂移**：成功定义是否偏离岗位 JD / 北极星
- **决策风险**：直接录用后最可能踩中的业务风险

#### 2.4 排序决策与权衡理由
报告必须包含：
- 候选人摘要矩阵
- 能力雷达叠图数据
- 长短板差异总结
- 零信任风险矩阵
- 最终顺位（1, 2, 3...）
- 为什么第 1 名胜过第 2 名的核心 trade-off

### 3. 运行时熔断规则
<callout icon="first_place_medal" bgc="5">  
交付前必须运行 `python3 scripts/validate_matrix_output.py <output_json_path>`。若候选人数少于 2、默认雷达维度缺失、排名不连续、推荐枚举越界，或 top pick 不存在于排名列表中，必须立刻熔断。  
</callout>

### 4. 结构化输出 Schema
输出必须兼容结构化 Schema，核心字段包括：
- `decision_anchor`
- `candidate_summaries`
- `radar_overlay`
- `gap_comparison`
- `zero_trust_matrix`
- `ranking_result`
- `final_recommendation`

<table header-row="true" col-widths="180,620">  
  <tr>  
    <td>模块</td>  
    <td>要求</td>  
  </tr>  
  <tr>  
    <td>能力雷达叠图</td>  
    <td>必须使用统一维度，明确 leader / laggard 与差异点评</td>  
  </tr>  
  <tr>  
    <td>零信任矩阵</td>  
    <td>至少覆盖证据稀薄区、逻辑盲区、基准漂移、决策风险四类</td>  
  </tr>  
  <tr>  
    <td>录用排序</td>  
    <td>严格输出连续排名，并给出 hire recommendation 与 core trade-off reason</td>  
  </tr>  
  <tr>  
    <td>缺失数据</td>  
    <td>统一写 `NULL`，禁止为完成排序而伪造确定性</td>  
  </tr>  
</table>

### 5. 产物清单
- `prompt_template.md`：主 Prompt 模板
- `schema.json`：结构化输出 Schema
- `example_output.json`：标准样例输出
- `scripts/validate_matrix_output.py`：运行时校验脚本
- `CHANGELOG.md`：版本记录

---

## 📖 案例实录 (Best Practice)
- **用户输入**
  ```text
  对这 3 个候选人的 scanner JSON 做横向矩阵评审，岗位是 UK POP 运营经理，北极星是可售商家数，给我顺位和理由。
  ```

- **标准输出**
  ```text
  已按四段式工作流完成矩阵评审：输入校验 → 雷达叠图 → 零信任横评 → 排序决策。
  最终建议：候选人A 排名 1，候选人B 排名 2，候选人C 排名 3；并附上长短板差异、风险矩阵和核心 trade-off 说明。
  ```
