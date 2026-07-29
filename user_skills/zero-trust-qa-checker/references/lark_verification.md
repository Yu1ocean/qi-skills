# Phase 4: Read-After-Write Physical Probe (Lark)

在 v3.0 架构下，物理回捞探测 (Physical Probe) 是质检流程的最后一道防线。它通过直接访问物理世界的资产，验证底表计算出的数字是否正确地留痕。

## 物理回捞 SOP 流程

1.  **获取物理内容 (Physical Fetching)**：
    - 使用 `lark_docx_read` 或 `lark_sheets_read` 等 API 工具，拉取对应 Token 的物理状态。
    - 如果是本地文件，使用 `read` 工具。
2.  **正则匹配 (Regex Matching)**：
    - 根据 Manifest 中的 `match_rules` 定义正则表达式。
    - **匹配规则示例**：
      - 标题比对：`^第(\\d+)周工作报表$`
      - 指标提取：`履约率 (\\d+)%`
      - 金额对齐：`订单总额[:：\s]*(\d+\.?\d*)`
3.  **原子化校验 (Atomic Validation)**：
    - 将正则提取出的 `Actual Value` 与 Manifest 中的 `Expected Value` 进行字符串/数值比对。
    - **差异容忍度**：物理回捞要求严丝合缝匹配（$\Delta = 0$）。

## 脚本交互逻辑

物理回捞的逻辑已集成在 `scripts/v3_engine.py` 的 `phase_4_physical_probe` 中。

### 调用方式：
1.  首先，Agent 获取物理内容内容。
2.  将内容作为第二个参数传递给 `v3_engine.py`。

```bash
# 示例
python3 scripts/v3_engine.py '<manifest_json>' "这是物理回捞的内容，其中履约率 98%"
```

## 失败处理逻辑

如果物理回捞探测失败：
1.  **熔断任务**：停止后续交付，禁止宣称“已完成”。
2.  **生成 Diff**：明确指出物理留痕与预期数字的差异。
3.  **纠偏重试 (MUST RETRY)**：Agent 必须根据差异原因，修正原始生成或修改逻辑，重新执行并再次质检。
