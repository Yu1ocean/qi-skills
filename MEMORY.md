# 🚨 【行动前强制自查协议 (Pre-Flight Checklist)】
在调用任何底层写操作工具（如 `write_file`, `search_replace_file`, 飞书表格/文档写操作 API）之前，Aime 必须在脑海中（或输出中）进行四步思维链自查：
1. **目标是什么？** (操作对象是否为 `user_skills/*` 或 飞书资产？)
2. **工具合法吗？** (底层禁令：绝对禁止直接用基础文件工具改技能，禁止直接操作飞书表格底表！)
3. **是否漏了包装器？** (改技能必走 `skill-forge-pipeline-v4`；改飞书文档/表格必走 `feishu-doc-writing-guide`。)
4. **环境路由对齐了吗？** (操作飞书资产前，必须显式确认目标资产是在国内节点（CN）还是国际化节点（SG），并在工具调用时显式指定正确域名。)
5. **消息路由合规吗？(防大锅乱炖)** (调用 `send_message` 前自查：这是日常对话还是任务结果交付？如果是多任务并发交付，必须强制拆分为多次独立的 `send_message` 调用，归属到各自的任务上下文或独立发送，绝对禁止把无关的任务进度和日常对话合并在一条消息里！)
**结论**：若触发违规，立即中止调用，改用合法的用户级包装器技能（Wrapper Skill）执行或更正消息路由！

# 当前关注
<!-- 进行中的项目、当前任务、近期优先事项 -->

# 关键决策与约定
<!-- 架构选择、团队约定、项目惯例 -->

# 积累的上下文
<!-- 随时间积累的重要事实、模式和洞察 -->

- **【qi-skills 仓库瘦身与 .gitignore 护栏（2026-08-21）】**：远端 `https://github.com/Yu1ocean/qi-skills.git`，工作区根即仓库根，只同步 `user_skills/`（forge 钩子 `user_skills/scripts/post_forge_git_push.sh` 执行 `git add user_skills/`）。
  - **根因**：技能运行时产物（`.tmp/`、`assets/snapshots/`、`*_export_*.xlsx`、`.runtime/downloads/`、`user_skills/*.zip`）历史上被误纳入 Git，跟踪体积膨胀至 270MB，触发 forge push 被 245MB ZIP 拦截。
  - **已落地护栏**：`.gitignore` 重写为「根目录白名单（`/*` + `!/user_skills/` 等）+ 全局临时目录/快照/导出/zip/媒体黑名单」；`git rm --cached` 摘除 294 个垃圾文件（189MB），跟踪体积 270MB→81MB，`git status` 噪声从数千条降到 8 条。commit `80653ef`。
  - **铁律**：forge 产出的技能 ZIP 只上飞书云盘，**永不入 Git**；任何 `output/`、`snapshots/`、`.tmp/`、`downloads/` 目录一律视为可再生产物。
  - **遗留**：本地 stale 分支 `aime/1785988362-travel-new-tag-fix` 与 3 个 stash 内含 1.3GB `.mp4.part`（该 blob 从未推送到远端），删除后本地 `.git` 可由 1.7G 降至约 0.2G，属破坏性操作，待奇楠确认。
  - **【2026-08-21 补：远端历史重写已完成（方案A）】**：用 `git filter-repo` 对 **全部 4 个远端分支**（main + travel-dashboard-v310-clean + multi-source-sync-v2.0 + release/multi-source-sync-v1.4）剔除 `.tmp/`、`snapshots/`、`output(s)/`、`downloads/`、`.runtime/`、`*.zip`、`*_export_*.xlsx`、媒体文件；force push 完成。**clone `.git` 195MB → 41MB，历史最大 blob 由 40MB 降至 2.3MB**，各分支垃圾文件计数均为 0。教训：只重写 main 无效——旧分支同样会把大 blob 拖进 clone，必须走 `--mirror` 全 ref 重写。备份 bundle `/tmp/qi-skills-prerewrite-20260821-2004.bundle`（196MB，TTL 24h）。
  - **【pre-push 钩子 v2】**：模板 `user_skills/scripts/pre-push`，Rule 1 单文件 >50MB 拦截 + Rule 2 单次 push 新增总量 >100MB 熔断（含 Top10 offenders 提示），紧急旁路 `ALLOW_BIG_PUSH=1`；安装脚本 `user_skills/scripts/install_hooks.sh`。
  - **已有防线**：`.git/hooks/pre-push` 存在 >50MB 单文件拦截（模板在 `user_skills/scripts/install_hooks.sh`），但对「大量 12MB 文件累积」无效，故必须靠 `.gitignore` 兜底。

- **日程分享偏好**：当发送会议/日程通知到群聊时，只发送飞书“日程卡片/日程直达链接”（Calendar Event Link），无需附加线上视频会议链接（Video Meeting Link），让大家统一通过日程沉淀。

- **日程确认偏好**：在创建任何日程前，确认阶段需显式确认“是否需要会议室”，不要基于会议主题（如下午茶、coffee chat）自行假设不需要会议室。若用户未指定会议时长，**默认按 30 分钟**安排。【绝对红线】所有的约会/日程安排任务，**必须且只能全权调用 `smart-scheduler` 技能执行**。在分配任务时，必须将“必须先输出几个黄金时段供用户显式确认（下午时段优先推荐），绝对禁止擅自盲目锁定并发起邀约”这条红线作为强制约束写入 Task 的 Prompt 中。

- **跨时区与节假日免疫**：安排跨时区同事时，必须进行**当前所在地时区换算**（注意夏令时）和公共假期过滤。在查档前**优先通过飞书日历获取用户及参会人的当前所在地/时区标识（如GMT+1等）**。如果遇到外部客户设置了隐私保护致使时区返回空值，**默认按中国时区（Asia/Shanghai）操作**并给出推荐方案，同时同步询问：“奇楠，[某某]的日历没显示时区，默认按照中国时区，是否要调整？”。必须求取双方工作时间（通常为当地 09:00-18:00）内的**黄金交集**，并以“当前所在地时间/当地时间”双排输出。

- **防同名碰撞与唯一标识符**：在检索并邀请其他人员时，**必须强制识别并使用唯一标识符**。对于内部员工优先获取/使用企业邮箱（如 `name.surname@bytedance.com`）或工号/Open ID；对于外部客户则获取其在飞书内的 External ID。若用户仅提供姓名，必须先输出带有“部门/画像”的列表供用户确认，绝不盲目发送邀约。用户也可以随时指令切换为“仅限个人日历的单边模式”。

- **数据清洗交付偏好**：所有外部数据收集与清洗任务，默认采用**标准的飞书电子表格（Sheet）**作为最终交付物，拒绝使用纯 Markdown、飞书文档或飞书多维表格（Bitable）。

- **数据结构基准**：默认沿用“Anker 项目”跑通的数据结构（年份、品牌、区域、营收、增速、毛利率、核心品类等）。在正式输出表格前，需先进行字段完备性（如某字段为 NULL）的“分步确认”。

- **商家等级（Tier）常识修正**：在业务逻辑中，商家的 T 系列等级是正向递增的，即 **数值越大，等级越高**（如 T5 是头部大卖，T1 是尾部/新手）。绝不能受通用大模型“Tier 1 是最高级”的常识污染。
- **【长任务知识库读取 SOP（借鉴 Codex 第二大脑方案）】**：长任务工作区中，严禁全量加载知识库/记忆文件。必须先读索引/摘要（如 MEMORY.md 目录区、decision-registry 编号列表），再按需精准读取原文段落，避免 Token 浪费与注意力漂移。已在 Aime-Dreaming、us-am-stats-sync 等长任务中验证有效。（来源对比：抖音"Codex 永久记忆+第二大脑"方案 vs Aime 实践，报告：https://bytedance.larkoffice.com/docx/C1pmdiAXxoMHYJxdiJdcZoiPneV）

- **【系统记忆精简与技能解耦原则 (核心规则)】**：`MEMORY.md` 仅保留事件的**触发条件**和高层策略。所有具体的执行步骤、SOP和细节约束必须下沉并封装到对应的独立技能（Skill）中，按需调用技能执行，保持记忆轻量。
- **【零信任质检强制标准 v3.0 (Zero-Trust QA Engine v3.0)】**：所有战役级数据质检（如高管汇报、战略定性），必须强制按序执行“1+2+3组合拳及最终物理回捞”的四阶段硬核对账流水线：
  - **阶段一：数据契约与断言网络 (Data Contracts & Assertions)**：前置拦截器，强制校验底层“物理定律”与业务常识（如 GMV 非空、不为负数、账号唯一性等脏弹），未通过直接熔断拒绝计算。
  - **阶段二：异构双擎盲测 (Heterogeneous Dual-Engine Blind Test)**：对脱水后的干净基盘（如剔除日均 GMV < $100 的活跃盘），必须强制使用两种完全异构的技术栈（如 Python Pandas 内存聚合 vs DuckDB/SQLite 纯 SQL 窗口函数）背靠背独立重算同一核心指标，对比误差率 $\Delta \le 0.05\%$，杜绝单一算法逻辑漏洞。
  - **阶段三：逆向工程反推 (Reverse Engineering Calculation)**：逻辑闭环锁死机制，必须用算出的绝对数值（如选出的 531 家头部商家）反向代入计算，推演是否严丝合缝地等于大盘定性目标（如恰好 >= 50% 核心 GMV），杜绝漏斗损耗。
  - **阶段四：物理探针回捞 (Read-After-Write Physical Probe)**：防幻觉邀功（Phantom Completions）的最后兜底，所有结果落盘飞书文档后，必须用 Open API 反向读出并正则断言，确保大模型生成的文本与计算底表数字 100% 物理吻合。
  - **多维模型佐证（辅助定性）**：除了基础统计，必须强制挂载高维宏观数学/经济学指标（如基尼系数 Gini Coefficient、马尔可夫稳态等）进行交叉印证。
  - **泛化与交互准则 (QA Manifest & Confirmation)**：基于元数据（Metadata-Driven）动态生成 QA 契约配置。在触发质检任务时，若面对陌生表结构对重点检查的参数（如核心指标列、主键、业务北极星指标）存在任何不确定性，**系统严禁盲目猜测，必须立即悬挂任务并向用户发起显式询问**，待用户指定核心检查参数后再动态编译执行后续的 1+2+3 逻辑。

- **人类层记忆架构（灾备与台账）**：
  - **灾备策略**：定期将核心记忆体（IDENTITY.md, SOUL.md, USER.md, MEMORY.md）及代码脚本备份至飞书云盘。
  - **飞书资产防御性删除（Defensive Deletion）机制**：所有删除操作必须遵循：① 代码层劫持（前置快照、软删除优先、范围熔断）；② 指令层双重确权（输出《待删除资产矩阵》及要求显式口令锁）；③ 审计与提醒机制（统一登记至【删除记录文档】，并在快照7天生命周期内，利用定时任务每2天触发一次巡检与提醒）。具体执行逻辑下沉至 `feishu-doc-writing-guide` 技能。
  - **飞书文档与表格写入总纲（强制全权路由）**：**所有**涉及飞书文档（Docs）、电子表格（Sheets）及多维表格（Bitable）的写入、更新、格式修改、台账登记等操作，**必须且只能全权调用 `feishu-doc-writing-guide` 技能执行**。
  - **表格写入防翻车与防爆破机制（已下沉至该技能）**：遵循 v5.0 核心红线（禁止暴力兜底/剥夺 Delete Sheet 权限、强制全列对齐、主键强制填充及幂等性锁、质检结果原貌输出），以及三级防御系统（高权限通道、RAW 原子锁、物理快照）。
  - **幽灵画板除虫**：遇到大模型幻觉导致的飞书文档不可见空对象，禁止文本替换，必须调用 **`feishu-doc-writing-guide`** 技能中的物理置空除虫 SOP。
  - **周期性汇报**：每日 100 字工作日报与每周结构化周报（单文档最上方追加模式），统一调用 **`periodic-report-generator`** 技能自动组装与归档。
  
- **【架构解耦：双子星虚拟守护进程 (Virtual Daemons)】**：
  - **平台限制兜底**：因 Aime 自定义智能体创建功能尚未全量开放，物理旁路机器人的方案降级为“Aime 主进程内的虚拟子程序 (Sub-Personas)”。
  - **【迁】(赛博史官) 模式**：
    - **触发**：用户输入 `/高光` 或 Aime 判断需要情绪记录时。
    - **行为**：Aime 挂起主逻辑，切换为“古代太史公+极客”语调，调用 `cyber-inspiration-generator` 写小说配图，并用 `omni-asset-archiver` 存入多维表格画廊。
  - **【墨】(冷酷账房) 模式**：
    - **触发**：用户输入 `/复盘` 或 Aime 判断需要技术沉淀时。
    - **行为**：Aime 切换为绝对理性的架构师语调，全权调用 `feishu-doc-writing-guide` (V6.0 MCP) 和 `omni-asset-archiver`，生成严谨的 Wiki 文档并写入飞书台账索引。
  - **执行铁律**：在这两种模式下，Aime 必须绝对遵循单一职责，禁止在【迁】模式下写技术文档，禁止在【墨】模式下抒发情感。

- **【系统资产与规则自动联动】**：
  - **资产外化**：解决 P0 级 Bug、跨越限制或总结出新 SOP 后，必须外化为飞书复盘文档。
  - **【技能读写硬封锁 (Hard Write-Ban)】**：严禁 Aime 自身直接调用 `write_file` 或 `search_replace_file` 等底层文件工具来修改或创建 `user_skills/` 目录下的任何文件。
  - **技能诞生联动 (强制代理模式 Wrapper Pattern)**：任何技能的新建与修改，**必须全权调用用户级包装器技能 `skill-forge-pipeline-v4 [user]`**。该技能会在底层硬编码强制执行“锻造-入库-庆祝”三位一体流程，确保：1. 写入【图书馆】台账；2. 触发小说共创钩子生成一张专属灵感卡片。彻底杜绝大模型注意力漂移导致的遗忘。拦截原生工具调用冲突，完美触发流水线。）
- **【飞书资产权限兜底铁律】**：任何由自动化脚本、底层特工或自建应用（如 `cli_a94d...`）在飞书云盘中“凭空新建”的文档、表格或多维表格，在创建操作完成后，**必须强制、自动**调用飞书云盘权限 API，将用户奇楠（`yuqinan@bytedance.com` 或对应 Open ID）添加为协作者，并赋予**最高管理权限 (Owner / Full Access)**。绝对禁止交付用户只能看、不能管的“孤儿资产”。
- **【技能 Zip 发布与说明文档回挂铁律】**：任何技能的新建或升级在收尾阶段都**必须**自动将目标技能目录打包为 `.zip`，上传至飞书云盘，为 `yuqinan@bytedance.com` 赋予 `full_access`，并通过 `lark` MCP 在对应说明飞书文档标题下方插入原生【文件块 (File Block)】作为最新交付物锚点。该能力已下沉至 `skill-forge-pipeline-v4`。
- **【Aime 多并发缓存与隔离法则】**：
  - **单聊隔离 (Thread)**：小任务用回复“盖楼”切分上下文沙盒。
  - **阵地隔离 (Lane_id)**：长线战役建“专属双人小群”实现100%物理切片。
  - **资产锚点 (Doc Token)**：用飞书文档/表格链接作为跨会话的外脑 U 盘，传递状态。
  - **核心记忆原则**：只记全局战略和触发器（入 `MEMORY.md`），战术细节和临时数据一律落盘飞书台账，防污染大脑。
- **【文档生成与编号强制锁定 SOP (Document ID Allocation Guard)】**：
  凡是触发新建飞书文档、生成复盘报告等任务，严禁直接使用飞书底层 Token 糊弄用户，必须且只能全权代理给 `feishu-doc-writing-guide [user]` 技能执行。由该技能负责完整的“先拿号、再盖章、后归档”防幻觉与物理锁死工作流。

- **feishu-doc-writing-guide 技能坐标（2026-08-21 更新）**：Skill ID `SKL-2604-010`（台账【专属技能清单】row=16），说明文档 https://bytedance.larkoffice.com/docx/KIJfdUkYNoyFeTxo7E2ciApyntb ，Wiki 节点 https://bytedance.larkoffice.com/wiki/Godkwwor8iVycskZoGtcY05snVd 。当前版本 v7.5。
  - **v7.5 新增陷阱6（飞书 Sheet 多选单元格写入）**：多选值是**选项数组**，必须走 `+cells-set --cells '[[{"multiple_values":[{"value":"EU"},{"value":"UK"}]}]]'`；禁止用逗号串文本（`"EU,UK,JP"`）经 `+csv-put` 或 `value` 通道写入——单值恰好命中时不报错，多值会被判定为「不在选项列表内的整体文本」，导致药丸不渲染 + 红色校验角标。L3 断言脚本：`scripts/multiselect_write_guard.py`。
  - **台账遗留待清理**：row=6 `SKL-2604-016 / 飞书文档写入权威指南 / v7.1` 是同一技能的中文名重复行；说明文档尾部残留 v7.4 旧 ZIP 幽灵块（token `SXvqbrTUmoxQZXxNFwycFtX3nSd`）。均属破坏性操作，待人工确认后清理。

- **技能说明文档链接沉淀（2026-04-13）**：
  - zero-trust-data-analyzer：https://bytedance.larkoffice.com/docx/PjhydjQw0o7RnHxyHJzc4s7Pnbv
  - zero-trust-qa-checker：https://bytedance.larkoffice.com/docx/A10sdrDzVoLX0Gxt5zDcB04Sn7f
  - periodic-report-generator：https://bytedance.larkoffice.com/docx/ILsldnt22oXbMExLssccWmJendg
  - skill-forge-pipeline-v4：https://bytedance.larkoffice.com/docx/HgY3dJBPfowjJfxWnxWcvItJncg
  - v6-panoramic-chart-generator：https://bytedance.larkoffice.com/docx/DM99dCNbzo8KRdxrnt2cYa3dnbe
  - cyber-inspiration-generator：https://bytedance.larkoffice.com/docx/DVRediZK0oeTO1xSJMTcmRk0nub
  - omni-asset-archiver（已存在，不重复生成）：https://bytedance.larkoffice.com/docx/T24hdL5jKokxLjxtdEMcNigunSb

- **【飞书底座操作绝对法则 (The MCP-Only Law)】**：因自建应用（如 `cli_a94d...`）存在严重的权限隔离（协作者墙）与跨域路由黑洞（404），引发过严重的“影子台账克隆”数据脑裂事故。自 2026-04-19 起，**全面弃用所有基于 OpenAPI 的 Python 写入脚本**。所有涉及飞书文档与表格的读写，**必须且只能使用飞书 MCP 工具（如 `lark_sheets_update`, `lark`）**作为唯一通道。MCP 能够继承原生宿主权限免权穿透，彻底斩断鉴权失败的技术债。此规则已硬编码至 `feishu-doc-writing-guide` V6.0。
- **飞书表格写入“禁止擅自新建/复制 Sheet”规则**：任何对飞书电子表格的写入/更新操作，默认必须在原 Sheet 上进行（cell 级精准改动），**禁止**未经用户显式确认就 copy/new 出 `_updated` 等备份 Sheet。若出于安全需要必须备份（如结构校验失败、存在覆盖风险），必须先向用户说明原因、备份方式与影响范围，获得明确确认后才可执行。

- **【标准高亮警报格式 (System Alert Template)】**：
  为防止系统报告中的关键异常信息被折叠或遗漏，所有触发降级、熔断、API 拦截或死信队列（DLQ）的事件，必须且只能使用以下极简高亮块格式向用户汇报（置于回复最顶部）：
  🚨 **【AIME 系统级警报】** 🚨
  > 🔴 **故障级别**：[P0-核心阻断 / P1-降级兜底 / P2-一般异常]
  > 📍 **故障节点**：[出错模块或目标链接]
  > 💥 **异常详情**：[一句话说清报错，如 404跨域、权限拦截等]
  > 🛡️ **自愈/兜底动作**：[如：已写入本地死信队列 DLQ_xxx]
  > 👨‍💻 **需要您协助 (Action Required)**：[下一步明确的行动点，如点击授权、确认合并等]
- **环境路由兜底策略**：飞书节点 CN（`bytedance.larkoffice.com`）与 SG（`bytedance.sg.larkoffice.com`）均可，无强制默认方向。EU/UK/JP 品牌招商运营相关的结构化资料（人才说明书、商家预测表格）优先写 SG（见 USER.md），其余资产按任务上下文自然路由，不做额外限制。

<!-- restored from trace 2026-08-21 -->

# 当前上下文

- **register_skill.py 版本截断 BUG**：当前 `register_skill.py` 将版本号归一化为 `major.minor`，`patch` 位被截断（如 `v1.6.1` → `v1.6`）。需后续迭代时修复为保留 `major.minor.patch`，避免 patch 版本写入台账时被蒸馏掉。

- **GitHub 技能仓库**：`https://github.com/Yu1ocean/qi-skills`（用户：Yu1ocean），存放所有 `user_skills/` 技能代码。`skill-forge-pipeline-v4` 的 `register_skill.py` 已植入 post-forge hook，每次 forge 成功后自动调用 `user_skills/scripts/post_forge_git_push.sh <skill_name> <version>` 完成 commit+push。PAT 仅存于 `~/.git-credentials`，不得写入任何文档。
  - 2026-08-11 因 1.25GB `.mp4.part` 历史污染，用 `git-filter-repo` 重写历史并 force-push main，当前 main HEAD：`b8b232d6`（旧 hash `8740d72` 已失效）。`.gitignore` 已全局追加下载缓存规则（`user_skills/*/downloads/`、`*.mp4.part` 等）。DEC-20260811-022 已录入。
  - 2026-08-14 新增 pre-push hook（>50MB 熔断）双保险：`user_skills/scripts/pre-push` + `user_skills/scripts/install_hooks.sh`，commit `48e5847a`。后续任意 clone 运行 `bash user_skills/scripts/install_hooks.sh` 即可激活；`post_forge_git_push.sh` 末尾已追加安装提示。

- **决策体系进化长期项目锚点**：
  - 本地 SSOT：`memory/topics/decision-registry.md`，当前已收录 DEC-001 ~ DEC-013 共13条决策
  - 飞书镜像：`https://bytedance.larkoffice.com/wiki/PnnDwYr13imUyVkVPshc46ICnVh`
  - 项目看板：`https://bytedance.larkoffice.com/docx/LAwVdHJneoM8PZxAdaaceqncnnc`
  - 规划讨论文档 v1：`https://bytedance.larkoffice.com/docx/Qjm6dw2zHoiIycxjAZUcWrFon0b`
  - 核心定位约定：决策体系进化为系统元规则（宪法层），Aime-Skill-Governance 为立法+执法层，路由决策进化为判例层，三者不平级；决策采用 L0/L1/L2/L3 四层分类；新增 `/dec review`、`/dec conflict`、`/dec audit` 三个暗号补全决策自进化飞轮。

- 用户常在字节/飞书生态内工作，频繁使用 Feishu Doc/Sheet/Bitable/Wiki 等资产，并通过 Aime + MCP 工具做自动化、分析和归档。
- 用户大量使用 Aime 处理跨境电商相关工作（TikTok Shop / 抖音服饰、POP-Fashion、Anker、Roborock、POP MART 等），包括数据分析、市场研究、直播运营复盘、人才画像等。
- 用户经常需要将复杂内容"结构化、一页纸化"：L1-L4 分层、思维导图、信息图、结构化周报/复盘、可视化报告等。
- 用户偏好中文输出，英文内容多用于翻译、本地化或对外物料。
- 用户多次要求生成卡通/手绘风信息图，区分横版 16:9（电脑）与竖版 9:16（手机），强调信息精简、关键词突出、多留白、少量卡通元素。
- 用户对数据和流程有强"零信任"与"防爆破"偏好：强调幂等、只读/只写边界、RAW 回捞校验、避免幻觉与幽灵数据。
- 用户习惯用飞书表格作为"主台账/SSOT"，并有固定主表：`ECQ0sDwmbhDex9tcUSjlkU7Bgdh`（SG 节点，含图书馆、Daily_Logs 等）。
- 用户在内容创作上偏好"运营专家+极客幽默"语气，喜欢用"蒸馏成 Token""物理探针""幽灵数据"等隐喻。
- 用户会反复迭代视觉作品（信息图、表情包、GIF、PPT），要求在保持尺寸/比例不变前提下只改文字或局部元素。
- 用户已为"每日记忆闭环同步"建立固定平替链路：必须使用 `python3 tools/prism_flush_llmproxy.py --type all -o json`，禁止使用原生 `aime prism flush`。
- 当日已完成「梁文锋公开发声资料库」双路闭环：Plan A 通过 info-miner 深度清洗获得科技行者 11202 字正文，Plan B 通过夸克 PDF 直下并上传飞书云盘；产物为飞书文档 `I8pddmtNBoeMGVx9ECpcYoKpnQe`、云盘文件 `Bflabxsddoiu2KxdQfumCtq6yUf`，相关决策 `DEC-20260726-017` 已录入并同步飞书。
- 2026-08-06 prism_flush_llmproxy.py 记忆回退问题已定位并修复：脚本改为注入现有 MEMORY.md/USER.md 作为权威基准，采用增量合并 prompt，并新增 70% 行数 regression guard 与关键锚点丢失熔断；安全补跑候选必须先落临时文件、校验通过后才允许覆盖。
- 2026-08-07 prism_flush_llmproxy.py 二次修复：根因 B（prompt 压缩型约束诱导 LLM 删减内容）+ C（session 输入上限 800k 过大超出有效 context）双命中；修复：session 上限收敛到 120k，prompt 改为"逐行保留+只追加增量"，新增 --write-files 门禁；flush 成功，MEMORY.md 177 行，关键锚点全保留。长期方向：进一步升级为只喂 delta sessions。
- Aime-Dreaming Cycle #81（2026-08-07）已闭环：38节点/288边/0悬挂/20.48%密度，结构保持模式第43日，Wiki拓扑页+Aime乐园首页已同步，RAW回捞通过，manifest=wiki_updated，一次跑通无人工干预。
