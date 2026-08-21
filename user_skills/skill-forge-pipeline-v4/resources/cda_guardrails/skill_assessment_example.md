# CDA Guardrails 适配评估表（示例快照）

> 说明：这里的“层级”指三层护栏的 **认知/默认/断言** 覆盖情况（不是文档结构 L1-L4）。

| 技能 | 风险等级 | 当前层数（认知/默认/断言） | 缺失项 | 优先级 |
|---|---|---|---|---|
| smart-scheduler | 高 | ✅ / ✅ / ✅ | 无（标杆） | P0（已完成） |
| feishu-doc-writing-guide | 高 | ✅ / ✅ / ⚠️ | 部分业务级断言（例如“元数据盖章/编号”更多停留在 SOP） | P0 |
| pro-task-planner | 中 | ✅ / ⚠️ / ❌ | 缺 runtime validator（输出计划表结构/停机点断言） | P1 |
| managing-lark-bitable-data | 高 | ❌ / ⚠️ / ⚠️ | 缺认知层反借口；缺写操作前置的强断言模板（字段写形态/不可写字段等） | P0 |
| omni-asset-archiver | 高 | ⚠️ / ❌ / ✅ | L1 反借口不足；L2 默认存在“静默改主键”的风险倾向 | P0 |
