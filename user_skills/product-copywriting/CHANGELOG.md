# CHANGELOG

## 1.1.0 - 2026-05-16

- 保持技能包目录 `user_skills/product-copywriting/`、包名 `product-copywriting` 与技能编号 `SKL-2605-001` 不变，按一次正常功能迭代升级版本号至 `1.1.0`。
- 升级固定输出格式：每个创意方向在原有“策略差异 + 完整成稿 + 五法拆解 + 3 条备选短句”基础上，新增 **文案气质**、**一句话预览**、**Slogan 短句**、**视觉锤符号** 4 个固定字段。
- 同步改写 `SKILL.md` 的 SOP、默认值、自检项与约束条件，明确要求每个方向都必须产出 `Slogan 短句` 与 `视觉锤符号`，且不得省略 `文案气质` 与 `一句话预览`。
- 升级 `output/product-copywriting_skill_doc.lark.md`：保留“便携咖啡机”模拟案例，并将展示改成完整新格式，覆盖 FABE 校验结果、3 个创意方向、主轴 / 策略差异、文案气质、一句话预览、Slogan 短句、视觉锤符号、完整成稿、五法拆解与 3 条备选短句。
- 更新 `references/source-rule-extract.md`，补记本轮迭代相对原始 Prompt 的新增锚点字段与用途，便于后续归档和复盘。

## 1.0.0 - 2026-05-16

- 初始创建 `product-copywriting` 用户级技能，面向用户触发口径「产品文案」。
- 基于 `产品文案指引_性张力五法.lark_5.md` 提炼规则，固化“先 FABE 校验、后五法生成”的主流程。
- 相比原始 Prompt，新增 **3 个创意方向** 的硬约束：每次必须产出 3 个彼此有明显策略差异的版本，并允许动态命名方向。
- 新增本地运行脚本 `scripts/fabe_validator.py`，支持 JSON / 文件输入、缺项识别、空泛 Benefit 检测、Evidence 缺失检查，以及 `--strict` 模式下的运行时熔断。
- 新增本地飞书文档草稿 `output/product-copywriting_skill_doc.lark.md`，用于后续 Feishu Doc 创建与归档前整理。
- 新增 `references/source-rule-extract.md`，记录从原始 Prompt 文档中提炼的核心规则与本技能升级点。
