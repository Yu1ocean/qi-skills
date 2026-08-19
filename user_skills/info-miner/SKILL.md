---
name: info-miner
id: 95b1248a-7aaa-42fa-b9ef-f58492536e09
version: 1.11
description: 从碎片线索追溯权威来源并产出结构化阅读结果，可同步沉淀到飞书文档。适用于微博/推文/短贴溯源、研究资料整理、内部分享与知识归档场景。
---

# info-miner（信息挖掘）

将碎片化线索“顺藤摸瓜”追到最权威、最长文、最原始的出处，并按**原文语言**选择输出路径：

- **中文信息源**：直接抽取并结构化输出中文；不做英中双语翻译；不做左右双栏对照排版。
- **非中文信息源**：输出英中双语逐段对照（左英文右中文），用于高保真对照阅读。
- **新增闭环归档**：生成飞书文档后，必须把资产写入指定 Wiki 分类节点的「已归档资产」表格；归档失败即明确 raise error 并阻断执行。

**当前版本：1.11（2026-08-19）**

> **v1.11 变更要点**：修复 Wiki 归档阶段 `toolset lark_download not found` 的 P1 熔断。根因是 `inner_skills/lark_download/lark_download.py` **文件仍存在但其背后的 AIME toolset 已下线**，而 `wiki_archive_guard.py` 的候选 resolver 只做 `exists()` 存在性判定，"文件存在" 被误当成 "可用"，导致下载链路直接 raise（更新链路早已有 `lark-cli` 兜底，下载链路缺同类兜底）。修复：① 新增**可用性探测** `is_toolset_unavailable()`，识别 `toolset ... not found` / `AimeError` / `Error from AIME Server` 等特征后**继续降级**而非熔断；② 新增 **lark-cli 下载兜底** `lark_cli_download()`，走 `lark-cli docs +fetch --as user --doc-format xml --detail with-ids`（唯一能拿到 `doxcn...` block id 的路径）；③ 新增 **DocxXML → 伪 `.lark.md` 转换** `docx_xml_to_pseudo_markdown()` / `xml_table_to_markdown_table()`，把 `<thead><tr><th><p id>` 规范化为 markdown-format `<table header-row="true" col-widths="...">` + `<tr><td>`，`<h2>` 还原为 `## 📂 已归档资产`，产物落盘到 `/workspace/.ephemeral_pool/` 任务唯一文件名。全部候选（本地 MCP 脚本 + lark-cli）都不可用才 `raise`；仍严禁退回 OpenAPI / JWT 直调。

> **v1.9.2 变更要点**：修复 Wiki 归档脚本对历史 `inner_skills/lark/mcp_lark_lark_download.py` 与 `mcp_lark_update_lark_doc.py` 的硬编码依赖。`scripts/wiki_archive_guard.py` 现在在 info-miner 侧执行多候选 MCP/shortcut resolver：下载优先兼容旧脚本，缺失时切换当前可用的 `inner_skills/lark_download/lark_download.py`；更新链路保留旧脚本优先并探测可用的 lark-doc update shortcut，若本地脚本候选缺失则切换 `lark-cli docs +update --as user`，候选均缺失才明确熔断且禁止退回 OpenAPI。根因是 inner skill 目录结构演进后历史 wrapper 缺失，导致归档阶段在下载/更新前 P1 熔断。验收要求：`wiki_archive_guard.py --selftest` 与 CDA Guardrails 自检必须通过；远端归档仍必须 MCP-only、用户身份、`include_secrets=true`。

> **v1.9 变更要点**：微博 Visitor System 场景将“浏览器模拟访问”从规则层补齐为可执行锚点。命中微博（`weibo.com` / `m.weibo.cn` / `weibo.cn`）的 `Visitor System / 403 / anti-bot / 需登录` 拦截时，**必须先触发** `user_skills/yt-dlp-media-downloader` 做物理探针；若 `yt-dlp probe` 仍失败，则**自动调用** `user_skills/info-miner/weibo_headless_fetcher.py`，在容器内启动 Playwright Chromium Headless/CDP，尝试获取访客 cookie、渲染页面、提取标题/作者/发布时间/正文/HTML，并在退出前写入 `/workspace/.ephemeral_pool/browser_gc.log`。只有该脚本也失败，才允许请求用户介入或要求补充 cookies/登录态。

> **v1.8 变更要点**：微博 Visitor System 场景新增二段降级链路。命中微博（`weibo.com` / `m.weibo.cn` / `weibo.cn`）的 `Visitor System / 403 / anti-bot / 需登录` 拦截时，**必须先触发** `user_skills/yt-dlp-media-downloader` 做物理探针；若 `yt-dlp probe` 仍失败，则**自动切换到浏览器模拟访问**，参考 2026-07-26 梁文锋微博资料抓取任务的成功路径继续拿标题、作者、发布时间与首段摘要，禁止在 yt-dlp 失败后直接中断或把决策抛回主进程。

> **v1.6 变更要点**：Phase 0 fallback 分支新增「微信视频号（weixin.qq.com/sph、channels.weixin.qq.com、finder.video.qq.com）专用解析」子分支。命中视频号域名时，**优先调用** `scripts/wechat_channels_resolver.py`（而非直接 yt-dlp，因 yt-dlp 对视频号直接 `Unsupported URL`）。脚本走「分享链接解析 → 提取 exportId(eid)+generalToken → 调用 feed_info 接口」三段式，默认 POST 到已验证可用的公开 Worker，绕过登录墙拿到 `videoUrl`（H264/H265）、作者、文案、封面、互动数等结构化信息；公开 Worker 不可用时明确 `raise` 并提示按 `wx_channels_download` 仓库自建 Worker 兜底，禁止静默降级。

> **v1.5 变更要点**：新增“一手来源最低交付”硬标准。最终 Docx 必须显式包含：用户给出的解读原文链接、一手原文链接，以及一手原文抓取状态（`SUCCESS / FAILED`，失败需写明原因）。若存在一手来源，必须继续抓取一手来源全文；非中文一手原文还必须产出英中双语逐段对照，并作为附录写入同一篇 Docx。

> **v1.4 变更要点**：当 Phase 0 轻量抓取遭遇 `403 / timeout / Visitor System / anti-bot / 需登录` 等拦截时，不再直接向主进程抛错等待人工干预；必须**自动触发** `user_skills/yt-dlp-media-downloader` 作为前置物理摄入探针。若 `yt-dlp probe` 拿到可用元信息（标题 / 提取器 / 上传者 / 时长 / stderr 线索），则继续完成溯源、全文、结构化与飞书归档；只有 `yt-dlp` 探针也失败时，才允许显式报错中断。

> **v1.1 变更要点**：新增浏览器操作收尾阶段的 Browser Tab GC。凡使用 Chrome DevTools Protocol / Browser Extension 打开的任务标签页，结束前必须逐个调用 `Target.closeTarget` 关闭；随后以 append 模式向 `/workspace/.ephemeral_pool/browser_gc.log` 写入结构化成功 / 失败记录，禁止残留标签页或静默跳过 GC。

> **v0.5 变更要点**：新增交付 payload 防污染规则。强制要求交付卡片 / post payload 使用 `.ephemeral_pool` 下的任务唯一文件名，发送前执行主题一致性断言，发送后执行上下文熔断，禁止复用根目录 `card.json` 等静态路径。

## 适用场景（Trigger）
- 只有一个关键词、概念名、微博/推文短句，但想找到它真正指向的**原始长文/官方文章**
- 看到二手转述，想“溯源”到**原始出处**核对细节
- 找到原文后，希望快速获得：**关键信息总结 + 中文结构化阅读 / 英中双语对照全文**
- 希望把最终飞书文档自动归档到 Aime 知识库分类节点，形成可检索台账

## 输入要求
- 一段碎片线索（文本即可）：可以是微博/推文片段、短贴内容、作者名 + 关键词、概念名、截图中的文字抄录等
- 可选：
  - 倾向的来源类型（官方博客 / 论文 / 产品公告 / 新闻 / 论坛长文）
  - 目标文档语言偏好说明（若用户另有要求再覆盖默认分支）
  - `category`：用户显式指定归档分类；未给定时允许在完成内容理解后自动推断

## ⚙️ 核心架构 / SOP / 约束条件

## 文档与感性资产分离标准（强制执行）
- **物理分离铁律**：理性的飞书文档（Docx）和感性的灵感卡片（EP-CARD）必须完全分离。严禁将灵感卡片、小说文案或视觉图嵌入飞书文档头部概览区或任何正文模块。
- **交付解耦**：在向用户最终交付时，飞书文档链接与灵感卡片必须作为两条独立消息发送，绝对禁止放在同一张富文本消息卡片中。
- **同步台账**：调用 `cyber-inspiration-generator` 产生灵感卡片后，必须将卡片记录存入【灵感台账】（Bitable ID: `PRbvbUyLqaeITqsXNMRcRCM5nhh`）。归档 Wiki 前必须自查台账同步状态。

## 交付 payload 防污染规则（强制执行）
- **唯一文件名铁律**：凡需交付飞书卡片 / post / payload，必须先落盘到 `/workspace/.ephemeral_pool/`，并使用 `[TASK_ID]_[TOPIC_SLUG].card.json`、`[TASK_ID]_[TOPIC_SLUG].post.json` 之类的唯一文件名。严禁复用根目录 `card.json`、`post.json`、`payload.json` 等静态文件名。
- **主题断言**：发送前必须检查 payload 标题、首段摘要、主链接与本轮溯源主题一致；若当前任务主题是 `NeuroGum`，payload 却出现“认知投降”等历史主题，必须立即熔断并回报，不得继续发送。
- **上下文熔断**：交付成功后，必须把本轮卡片 DSL、临时话术、摘要片段从活动上下文中物理清空，禁止把上一轮成功案例当作下一轮默认模板继续复用。
- **旧文件取证但不可复用**：若发现根目录或其他共享路径残留旧 `card.json` / `post.json`，只能视作故障取证样本，不得覆盖式复用或作为当前发送输入。

## 浏览器操作收尾与 Browser Tab GC（强制执行）
- **触发条件**：只要本次 `info-miner` 执行过程中通过 Browser Extension、Chrome DevTools Protocol 或等效浏览器调试链路打开过标签页，就必须执行 Browser Tab GC；不因“任务已完成”或“马上断连”而豁免。
- **关闭顺序**：进入收尾阶段后，必须先枚举本次任务打开的全部 `targetId`，再逐个调用 Chrome DevTools Protocol `Target.closeTarget` 关闭；禁止在调试连接仍存活时直接退出，导致标签页残留在用户 Chrome 中。
- **日志落盘**：关闭完成后，必须以 append 模式向 `/workspace/.ephemeral_pool/browser_gc.log` 写入结构化记录。成功格式：`[YYYY-MM-DD HH:MM] [task_id] [Browser GC] closed N tabs | task: <任务名称>`；失败格式：`[YYYY-MM-DD HH:MM] [task_id] [Browser GC] FAILED: <原因>`。
- **运行时护栏**：统一调用 `scripts/browser_tab_gc.py` 生成日志行，避免时间格式、成功 / 失败文案或 append 行为漂移。仅当实际完成日志写入后，才允许断开浏览器调试连接或结束任务。

## Common Rationalizations（常见借口库）
以下借口一旦出现，视为准备绕过护栏，必须立刻停下并回到 SOP：

- “URL 看起来差不多，先直接全文抓取吧。”
- “用户给的链接肯定是对的，不用再做摘要比对了。”
- “中文源也顺手给成双语对照吧，省得再判断语言。”
- “先把飞书文档建出来，归档回头再补。”
- “分类不太确定，先随便扔进一个 Wiki 节点，后面再改。”
- “候选脚本文件存在，那就当它能用，直接跑不用探测。”（错误：toolset 可能已下线，`exists()` ≠ 可用，必须探测并继续降级）
- “下载脚本报 `toolset not found`，那就直接熔断报错吧。”（错误：必须继续降级到 `lark-cli docs +fetch xml with-ids`）
- “归档写入失败了也没关系，先把文档链接交付就算完成。”
- “卡片挺好看的，顺手贴在文档开头给用户个惊喜。”
- “交付消息太多了，把文档链接和卡片放在一起发更整洁。”
- “浏览器标签页反正用户自己会关，先断开调试连接再说。”
- “GC 日志只是复盘用的，漏一条也没关系。”
- “微博 Visitor System 被拦了，yt-dlp 也没拿到，就先报错等主进程拍板吧。”（错误：微博必须继续切到浏览器模拟访问，不得中途停在 yt-dlp 失败）
- “Phase 0 已经 403 / 超时了，先报错给主进程，回头再人工决定要不要 yt-dlp。”
- “微信视频号链接嘛，先用 yt-dlp 抓一下试试，不行再说。”（错误：视频号 yt-dlp 直接 Unsupported URL，必须先走 `wechat_channels_resolver.py`）
- “公开 Worker 挂了，视频号这条就先只存个链接算了。”（错误：必须按提示自建 Worker 复现三段式，禁止静默降级）

## Red Flags（危险信号）
出现任意一条，必须熔断或要求用户确认，禁止继续“假装成功”：

- 还没做轻量抓取与摘要比对，就直接调用全文抓取 / 排版 / 飞书写入。
- 用户上下文与页面作者、主题、关键词明显冲突，却继续推进 Step 3+。
- 中文源仍然输出双语对照，或中文源使用左右双栏排版。
- 生成飞书文档后没有执行归档，或归档失败后仍然把任务宣称为完成。
- 用户显式给了 `category`，却被自动推断结果覆盖。
- 归档写入没有落在 `## 📂 已归档资产` 标题下的表格，或者表头不是 `序号 | 归档日期 | 资产名称 | 来源/主题 | 访问链接`。
- 归档写入没有走飞书 MCP 路径，而是回退到 OpenAPI / 旧脚本。
- **下载链路只判 `exists()` 未做可用性探测**，或候选脚本报 `toolset ... not found` / `AimeError` 后没有继续降级到 `lark-cli docs +fetch`。
- 用 `--doc-format markdown` 抓取后就去构造 block 级补丁（markdown 管道表格无 block id，必须用 `xml --detail with-ids`）。
- **飞书文档中出现了灵感卡片或赛博小说文案。**
- **交付消息中将文档链接与灵感卡片合并发送。**
- **灵感卡片未同步至 Bitable `PRbvbUyLqaeITqsXNMRcRCM5nhh`。**
- **交付 payload 复用了根目录 `card.json` / `post.json` 等静态文件名。**
- **当前主题与 payload 标题 / 摘要 / 主链接明显不一致，却仍继续发送。**
- **浏览器调试连接已退出，但本次任务打开的标签页仍未全部调用 `Target.closeTarget` 关闭。**
- **`/workspace/.ephemeral_pool/browser_gc.log` 未追加本轮结构化 GC 记录，却把任务宣称为已收尾。**
- **Phase 0 轻量抓取遭遇 `403 / timeout / Visitor System / anti-bot / 需登录` 后，没有自动触发 `user_skills/yt-dlp-media-downloader` 的 `probe`。**
- **微博域名（`weibo.com` / `m.weibo.cn` / `weibo.cn`）命中 Visitor System，且 `yt-dlp probe` 已失败，却没有继续切换到浏览器模拟访问。**
- **命中微信视频号域名（weixin.qq.com/sph、channels.weixin.qq.com、finder.video.qq.com），却直接调用 yt-dlp 或普通网页抓取，而没有优先调用 `scripts/wechat_channels_resolver.py`。**
- **微信视频号解析器报错（Worker 不可用 / feedInfo 缺失），却把裸链接当成功交付，而不是按提示自建 Worker 复现三段式或显式报错中断。**

## Verification（强制验收清单）
当宣称“本次溯源与归档已完成”时，必须同时满足：

1. **轻量抓取已完成**：拿到了标题、作者/署名（若可得）、发布时间（若可得）、域名、首段摘要（200~400 字以内），并显式列出。
2. **比对/确认证据可见**：
   - 分支 A（用户给了上下文）：显式给出作者 / 主题 / 关键词三维度比对结果。
   - 分支 B（用户未给上下文）：显式给出【目标确认卡片】并拿到用户明确回复。
3. **一手来源最低交付达标**：最终 Docx 中已显式包含 `解读原文链接`、`一手原文链接`、`一手原文抓取状态（SUCCESS / FAILED + 原因）`。
4. **一手来源抓取合规**：若存在一手来源，则已抓取一手来源全文；若未抓取，必须有明确不可访问原因。
5. **语言分支正确**：中文源只输出中文结构化阅读；非中文源才输出英中双语对照。
6. **飞书文档已生成**：正文结构符合【模块一】+【模块二】+【模块三】约定，访问链接可回跳；**且文档中无感性卡片内容**。
7. **非中文一手附录已落地**：若一手原文为非中文，则同一篇 Docx 中已写入英中双语逐段对照附录，而非仅提供外链。
8. **分类选择合规**：优先使用用户显式给定的 `category`；仅在用户未提供时才允许推断，并且结果必须落在白名单分类中。
9. **归档写入已完成**：目标 Wiki 节点的 `## 📂 已归档资产` 表格中能看到新增行，且至少包含自增序号、归档日期、资产名称、来源/主题、访问链接。
10. **RAW 回读验收已完成**：归档写后重新下载目标文档，确认新增行真实存在；若回读失败，必须 raise error。
11. **未静默降级**：任何抓取失败、文档创建失败、赋权失败、归档失败，都必须显式报错并中断，不得输出“应该/大概/先这样”。
12. **资产分离交付**：交付时已确认分两条消息发送，且灵感卡片已存入指定 Bitable 台账。
13. **payload 防污染验收已通过**：本轮交付文件位于 `/workspace/.ephemeral_pool/` 的任务唯一文件名路径，且发送前已完成主题一致性断言，发送后已执行上下文熔断。
14. **Browser Tab GC 验收已通过**：若本轮使用过浏览器调试链路，则已在断开连接前完成 `Target.closeTarget` 批量关闭，并向 `/workspace/.ephemeral_pool/browser_gc.log` 追加一条符合规范的成功 / 失败记录。
15. **Phase 0 fallback 验收已通过**：若轻量抓取命中 `403 / timeout / Visitor System / anti-bot / 需登录` 等阻断：
    - 命中**微信视频号域名**时，已优先调用 `scripts/wechat_channels_resolver.py` 且拿到含 `videoUrl` 的 `feedInfo`（而非直接 yt-dlp / 普通抓取）；若解析器报错，已按提示自建 Worker 复现三段式或显式回报失败，未把裸链接当成功。
    - 命中**微博域名**（`weibo.com` / `m.weibo.cn` / `weibo.cn`）时，已先自动调用 `user_skills/yt-dlp-media-downloader` 执行 `probe`；若 `yt-dlp probe` 仍失败，已继续切到浏览器模拟访问，并拿到可用于 Phase 0 的标题 / 作者 / 发布时间 / 首段摘要，而不是直接中断。
    - 其它站点已自动调用 `user_skills/yt-dlp-media-downloader` 执行 `probe`；若 `yt-dlp probe` 仍失败，已显式回传 stderr / 提取器错误，而不是静默报错或直接跳过。
16. **归档下载链路降级验收已通过**：候选 MCP 下载脚本已做**实际可用性探测**（而非仅 `exists()`）；命中 `toolset ... not found` / `AimeError` 时已自动降级到 `lark-cli docs +fetch --doc-format xml --detail with-ids`，并完成 DocxXML → 伪 `.lark.md` 转换（表头可被 `validate_archive_table_headers()` 提取、标题还原为 `## 📂 已归档资产`）；只有全部候选都不可用时才 `raise`，且未退回 OpenAPI / JWT 直调。

### Phase 0：目标前置校验 (Pre-Flight Target Assertion)（硬熔断，必须最先执行）
> 目标：把“溯源准确性”从软约束升格为硬熔断。第一动作不是搜索、不是全文抓取、不是排版，而是先确认拿到的就是用户想要的那篇文章。

#### Phase 0 第一动作：轻量抓取（Lightweight Probing）
拿到 URL 后，先只提取元信息：
- 标题（`<title>` / `<h1>` / `og:title` 等）
- 作者 / 署名（若可得）
- 发布时间 / 更新时间（若可得）
- 域名 / 站点名
- 首段摘要（**200~400 字以内的核心内容预览**，不要全文）

**若轻量抓取阶段命中 `403 / timeout / Visitor System / anti-bot / 需登录` 等阻断：**
- 不得直接把错误抛给主进程等待人工选择
- **① 微信视频号（weixin.qq.com/sph、channels.weixin.qq.com、finder.video.qq.com）专用解析分支（最高优先级）**：
  - 一旦命中微信视频号域名，**严禁**直接走 yt-dlp（视频号页面对常规抓取只返回「视频号」空壳页，yt-dlp 会直接 `Unsupported URL`），必须**优先调用** `scripts/wechat_channels_resolver.py`：
    ```bash
    cd user_skills/info-miner && python3 scripts/wechat_channels_resolver.py --url "<sph/视频号分享链接>"
    ```
  - 原理：该脚本走「分享链接解析 → 提取 exportId(eid)+generalToken → 调用 feed_info 接口」三段式（默认 POST 到已验证可用的公开 Worker `https://sph.litao.workers.dev/api/fetch_video_profile`），全程使用视频号**分享/预览态**的临时 token，无需用户扫码登录个人微信账号，因此能绕过登录墙。
  - 返回结构化 JSON：`author`（作者）、`title`（文案）、`videoUrl`（H264/H265 视频直链）、`cover`（封面）、`interactions`（点赞/评论/转发/收藏）、`createtime`、`status`。
  - **兜底**：若公开 Worker 不可用（如 Cloudflare 1010 / 网络失败），脚本会 `raise WeChatChannelsError` 并显式提示「可依据 `wx_channels_download` 仓库（`internal/api/sph/worker.js`）自建 Cloudflare Worker 或本地服务复现同一三段式逻辑，再用 `--endpoint` 指向自建服务」。此时按提示自建后重试，禁止静默降级。
  - 只要解析拿到 `feedInfo`（含 `videoUrl`），即视为 Phase 0 fallback 已命中，可继续后续溯源/转写/结构化/归档。
- **② 其它站点（非微信视频号）**：必须立即自动触发 `user_skills/yt-dlp-media-downloader`，先执行：
```bash
cd user_skills/yt-dlp-media-downloader && python3 scripts/yt_dlp_fetch.py --mode probe --url "<媒体链接>"
```
- **③ 微博 Visitor System 二段降级分支（weibo.com / m.weibo.cn / weibo.cn）**：若上一步 `yt-dlp probe` 也失败，则不得直接中断，必须继续调用可执行锚点：
```bash
cd user_skills/info-miner && python3 weibo_headless_fetcher.py --url "<微博链接>" --task-id "<task_id>"
```
该脚本在容器内启动 Playwright Chromium Headless/CDP，执行访客 cookie 获取、页面渲染、桌面/移动详情页双路提取，并输出 JSON（`title` / `author` / `publish_time` / `domain` / `summary` / `text_path` / `html_path` / `gc_log_status`）。拿到结果后，必须把脚本返回的元信息交回 Phase 0 断言层；只有脚本也失败，才允许请求用户介入。
- 只要视频号解析器、`yt-dlp probe`，或微博浏览器模拟访问产出了标题、作者/上传者、视频直链、提取器、时长、媒体 ID、stderr 摘要中的任意有效元信息，就视为 Phase 0 fallback 已命中，可继续后续溯源
- 只有对应分支的专用解析（微信视频号 → `wechat_channels_resolver.py`；微博 → `yt-dlp probe` 后浏览器模拟访问；其它 → `yt-dlp probe`）**也失败**，才允许显式报错中断

**严禁**此时进入：
- 全文抓取
- 翻译、排版、双语对照表生成
- 任何飞书写入、飞书赋权、归档写入等副作用动作

#### Phase 0 第二动作：分支处理
##### 分支 A：用户提供了上下文（截图、关键词、作者名、主题描述等）
必须把轻量抓取得到的标题、作者、摘要、域名，与用户上下文做三维交叉比对：
1. **作者匹配度**：用户期望作者 vs 页面署名是否一致 / 同义
2. **主题匹配度**：用户描述的主题 / 事件 vs 页面首段摘要是否吻合
3. **关键词覆盖度**：用户提供的关键词是否在标题 / 摘要中得到体现

判定规则：
- 三个维度均明确匹配 → 通过 Phase 0，进入 Step 1+
- 任一维度明显不一致 → **立即熔断**，输出「⚠️ 目标不一致告警」，请求用户确认或更换 URL
- 模棱两可 → 视同不一致，仍然熔断

##### 分支 B：用户未提供上下文
不能“看起来像那么回事”就自行判定通过。必须先输出【目标确认卡片】，等待用户显式确认：

```text
🎯 【目标确认卡片】
- 标题：xxx
- 作者 / 署名：xxx
- 发布时间：xxx
- 域名 / 站点：xxx
- 首段摘要（≤400 字）：xxx

❓ 这是您要溯源的目标文章吗？
   - 回复「是 / 确认 / 继续」即进入全文抓取与排版流程。
   - 如果不是，请提供新的 URL 或补充更多上下文（作者名、关键词、发表时间等）。
```

#### Phase 0 物理护栏脚本（L3 断言层）
在进入 Step 3+ 之前，必须调用 `scripts/preflight_target_assertion.py` 的 `assert_phase0_ready` 入口；任一维度不满足即 `raise PhasePreflightError`。若常规轻量抓取失败但错误命中 fallback 条件，则必须把 `ytdlp_probe` 一并传入，让断言层强制校验“是否已经自动触发 yt-dlp 探针”，禁止只传 `fetch_error` 后草草中断。

调用示例：

```python
from preflight_target_assertion import assert_phase0_ready

assert_phase0_ready(
    probe={
        "title": "...",
        "author": "...",
        "publish_time": "...",
        "domain": "...",
        "summary": "≤400 字首段摘要……",
    },
    expected={"author": "...", "topic": "...", "keywords": ["..."]},
    # 或 user_reply="确认"
)

# 若常规轻量抓取失败，则必须把 yt-dlp 探针结果一起交给断言层
assert_phase0_ready(
    probe=None,
    fetch_error="Visitor System / timeout",
    ytdlp_probe={
        "title": "微博视频标题",
        "domain": "weibo.com",
        "summary": "基于 yt-dlp probe 整理出的 ≤400 字元信息摘要……",
        "extractor": "Weibo",
        "uploader": "xxx",
    },
    expected={"topic": "...", "keywords": ["..."]},
)

# 若微博常规轻量抓取与 yt-dlp probe 都失败，则必须继续把浏览器模拟访问结果交给断言层
assert_phase0_ready(
    probe=None,
    fetch_error="Visitor System / timeout",
    ytdlp_error="yt-dlp extractor failed: login required",
    browser_probe={
        "title": "微博长帖标题",
        "author": "作者名",
        "publish_time": "2026-07-26",
        "domain": "weibo.com",
        "summary": "基于浏览器模拟访问拿到的 ≤400 字首段摘要……",
    },
    domain_hint="https://weibo.com/xxx",
    expected={"topic": "...", "keywords": ["..."]},
)
```

可用以下命令自检：

```bash
python3 user_skills/info-miner/scripts/preflight_target_assertion.py --selftest
```

## 合规默认值（Defaults）
以下默认值与 `scripts/preflight_target_assertion.py`、`scripts/wiki_archive_guard.py` 保持一致：

- **DEFAULT_SUMMARY_MIN_CHARS = 200**：Phase 0 首段摘要长度下限
- **DEFAULT_SUMMARY_MAX_CHARS = 400**：Phase 0 首段摘要长度上限
- **DEFAULT_KEYWORD_HIT_RATIO = 0.5**：分支 A 关键词命中阈值
- **DEFAULT_REQUIRE_USER_CONFIRM = True**：分支 B 默认必须等待用户显式确认
- **DEFAULT_BLOCK_ON_FETCH_FAIL = True**：轻量抓取失败默认硬熔断
- **DEFAULT_PHASE0_FALLBACK_TO_YTDLP = True**：命中 `403 / timeout / Visitor System / anti-bot / 需登录` 时默认强制自动触发 `yt-dlp probe`
- **DEFAULT_WEIBO_HEADLESS_FETCHER = `user_skills/info-miner/weibo_headless_fetcher.py`**：微博域名命中 Visitor System 且 `yt-dlp probe` 失败时，默认调用容器内 Headless/CDP 可执行锚点，不依赖用户本地 Chrome。
- **DEFAULT_WECHAT_CHANNELS_FIRST = True**：命中微信视频号域名（weixin.qq.com/sph、channels.weixin.qq.com、finder.video.qq.com）时，默认优先走 `scripts/wechat_channels_resolver.py` 而非 yt-dlp
- **DEFAULT_WECHAT_WORKER_ENDPOINT = `https://sph.litao.workers.dev/api/fetch_video_profile`**：视频号解析默认公开 Worker 端点（不可用时按提示自建 Worker 兜底）
- **DEFAULT_OUTPUT_LANG = 中文**：要点总结、结构化整理默认使用中文输出
- **DEFAULT_NON_CHINESE_LAYOUT = HTML 两列表格**：仅当原文为非中文时启用左右双语对照排版
- **DEFAULT_ARCHIVE_REQUIRED = True**：飞书文档生成完成后必须继续归档；不能停在“只给文档链接”
- **DEFAULT_CATEGORY_POLICY = explicit_first_then_infer**：先吃用户显式分类，再允许模型推断
- **DEFAULT_ARCHIVE_HEADING = `## 📂 已归档资产`**：归档表格必须落在这个标题下
- **DEFAULT_TABLE_HEADERS = `序号 | 归档日期 | 资产名称 | 来源/主题 | 访问链接`**：表头固定，不允许擅自变形
- **DEFAULT_VERIFY_AFTER_WRITE = True**：归档写入后必须重新下载并核对新增行
- **INSPIRATION_BITABLE_ID = `PRbvbUyLqaeITqsXNMRcRCM5nhh`**：灵感台账指定 ID
- **INSPIRATION_TABLE_ID = `tblHHVXl9ObjSyRw`**：灵感台账指定 Table ID

### Step 0：语言判断分支（硬约束，必须执行）
- **默认输出语言 = 中文**（要点总结、结构化整理均以中文输出）
- 当抓取到的原文**主要为中文**时：执行“中文源路径”
- 当抓取到的原文为**非中文**时：执行“非中文源路径”
- **严禁**中文源输出英中双语翻译
- **严禁**中文源使用左右双栏对照排版

### Step 1：基于线索做“溯源式搜索”
- 使用 `search` 做多轮搜索：关键词 → 可能作者 / 组织 → 可能标题 → 原文站点
- 优先官方域名 / 作者主页 / 论文官网 / 产品公告
- 避免停留在转载 / 二手解读，尽量追到首发来源
- **目标定义（最低交付）**：将用户给出的二手解读 / 转载，追到“最原始的一手来源”（官方博客、论文原文、产品公告首发）。
- **最低交付硬标准**：最终 Docx 必须显式包含以下三项，缺一不可：
  1. `解读原文链接`：用户给出的二手解读 / 转载链接
  2. `一手原文链接`：溯源得到的最原始出处链接
  3. `一手原文抓取状态`：`SUCCESS / FAILED`；若为 `FAILED`，必须写明失败原因（如 403、登录墙、源站删除、反爬拦截）

### Step 2：判定是否“唯一高度匹配”
- 若找到**高度匹配且唯一**的目标文章：直接进入 Step 3
- 若存在多个疑似出处：先给候选列表（建议 3~8 条），每条包含标题、作者 / 机构、发布时间、站点 / 域名、直达 URL、简短理由；再请求用户确认

### Step 3：抓取全文（必须使用网页提取工具）
- 对用户确认 / 已判定的目标 URL，使用网页提取工具抓取正文全文并保存为本地 Markdown
- 遇到分页、脚注、代码块、引用，尽量完整提取
- **硬规定**：若已确认存在一手来源，必须同时抓取一手来源全文；除非已明确说明无法访问（如 403、登录墙、源站删除、地区限制、反爬拦截），否则不得只停留在二手解读层。

### Step 4：深度提炼（中文要点总结）
- **🛡️ 内容隔离法则（最高优先级）**：只允许对原文做客观归纳，严禁结合用户的电商工作背景做商业转化、话术包装或过度引申
- 基于全文提炼 3~6 个核心框架 / 观点（偏框架化，不是流水账摘要）
- 对每个框架 / 观点给 1~3 句中文解释，必要时补充关键术语释义

### Step 5：正文组织（按语言分支）
#### 分支 A：中文源 → 中文结构化直出
- 只输出中文；不翻译、不对照
- 推荐输出结构：
  - 【模块一】💡 关键信息总结（中文）
  - 【模块二】🧾 原文结构化阅读（中文）
- 模块二开头必须给出原文直达 URL：`原文链接：https://...`
- 正文按自然段 / 小标题 / 列表组织；必要时在段落后补 1 句结构化注解

#### 分支 B：非中文源 → 英中双语左右对照
- 以自然段为最小对齐单元；不要按句子逐句硬切
- 对每一段生成高保真中文翻译：
  - 保留技术原味和行业黑话
  - 专有名词首次出现时可在中文中括注英文
  - 不要过度意译，不要写成科普文
- **强化要求**：若一手原文为非中文，除主阅读模块外，还必须将一手原文的英中双语逐段对照作为“附录”写入同一篇 Docx，避免只给外链不落正文。

### Step 6：生成标准化飞书文档（必须遵守排版契约）
#### 输出结构（严格遵守）
- 【模块一】💡 关键信息总结（中文）：3~6 个核心框架或观点
- 【模块二】🧭 溯源结果与抓取状态：必须显式列出 `解读原文链接`、`一手原文链接`、`一手原文抓取状态（SUCCESS / FAILED + 原因）`
- 【模块三】根据语言分支选择：
  - **中文源**：🧾 原文结构化阅读（中文，普通段落排版；严禁双栏）
  - **非中文源**：🌐 深度双语对照阅读（左英文、右中文，逐段对齐）
- 【附录】若一手原文为非中文：必须补充同一篇 Docx 内的“一手原文英中双语逐段对照附录”

#### 版式实现
- **仅当原文为非中文**时，使用 HTML `<table>` 两列表格（禁止 Markdown 管道表格）
- 中文源使用普通段落、列表、引用块；不要生成双栏

#### 写入飞书的硬性要求（必须执行）
- 必须使用 `user_skills/feishu-doc-writing-guide` 的规范链路写入飞书文档：
  1. 先在本地生成 `.lark.md`（只写正文，不要写 H1 标题）
  2. 调用飞书文档创建工具将 `.lark.md` 转为 docx
  3. 创建完成后，必须执行赋权，确保 `yuqinan@bytedance.com` 拥有 `full_access`
- **🛡️ 严禁嵌入**：严禁在此飞书文档中嵌入任何来自 `cyber-inspiration-generator` 的卡片、文案或图片。文档必须保持 100% 的理性结构化阅读体验。
- **⚠️ 鉴权要求：** 涉及飞书 API / MCP 调用时，必须通过 `bash` 工具直接执行，并设置 `include_secrets=true`

### Step 7：闭环归档到 Wiki 节点（新增，强制执行）
#### 7.1 分类选择策略
- **优先使用用户显式给定的 `category`**
- 仅当用户未给定时，才允许根据文章主题、来源、关键词推断最合适分类
- 分类只能落在以下 6 个白名单中：
  - `AI/Agent`
  - `文案/创意`
  - `跨境运营`
  - `组织/管理`
  - `行业趋势`
  - `工具/方法论`
- 具体路由 Token 由 `scripts/wiki_archive_guard.py` 内部的 `CATEGORY_NODE_MAP` 硬编码维护，禁止运行时自由改写

#### 7.2 归档写入要求
- 目标位置：对应 Wiki 节点背后的 Docx 文档中，`## 📂 已归档资产` 标题下的表格
- 若表格已存在：向表尾追加一行
- 若表格不存在：先在该标题下创建表格，再写入首行数据
- 表头固定为：`序号 | 归档日期 | 资产名称 | 来源/主题 | 访问链接`
- 新增行至少包含：
  - 自增序号
  - 归档日期（`YYYY-MM-DD`）
  - 资产名称
  - 来源/主题
  - 访问链接（飞书文档直达链接）

#### 7.3 必须走飞书 MCP 路径（不要退回 OpenAPI，不要用旧脚本）
优先直接执行护栏脚本：

```bash
python3 scripts/wiki_archive_guard.py archive \
  --category "AI/Agent" \
  --asset-name "<归档资产名称>" \
  --source-topic "<来源/主题>" \
  --access-link "https://bytedance.larkoffice.com/docx/xxx"
```

如果用户没有显式给出分类，则把推断结果传给 `--inferred-category`，不要覆盖显式 `--category`：

```bash
python3 scripts/wiki_archive_guard.py archive \
  --inferred-category "工具/方法论" \
  --asset-name "<归档资产名称>" \
  --source-topic "<来源/主题>" \
  --access-link "https://bytedance.larkoffice.com/docx/xxx"
```

#### 7.4 灵感卡片同步与分离交付（新增，强制执行）
- **同步**：必须调用护栏脚本将本次高光卡片存入灵感台账（`PRbvbUyLqaeITqsXNMRcRCM5nhh`）：
```bash
python3 scripts/inspiration_archiver.py \
  --subject "<标题>" \
  --story "<小说文案>" \
  --fact "<事实说明>" \
  --image-url "<视觉图链接>" \
  --screenshot "<全尺寸截图路径>" \
  --deployed-url "<网页卡片链接>"
```
- **解耦交付**：
  1. 发送消息一：交付理性文档链接及其摘要。
  2. 发送消息二：交付感性灵感卡片（EP-CARD）。
  3. **严禁合并**：绝不允许在一次回复中将两者放在同一个 block 或 card 内部发送。

`wiki_archive_guard.py` 的职责：
- 承载 `CATEGORY_NODE_MAP`
- 规范化 / 校验分类
- 构造归档行与固定表头
- 在 info-miner 侧解析可用的 Lark MCP/shortcut 脚本，并对候选做**运行时可用性探测**（`exists()` 不等于可用）：下载链路优先 `inner_skills/lark/mcp_lark_lark_download.py`，其次 `inner_skills/lark_download/lark_download.py`；任一候选输出命中 `toolset ... not found` / `AimeError` / `Error from AIME Server` 即判定不可用并继续降级
- 下载兜底（v1.11）：所有本地 MCP 下载候选均不可用时，改走 `lark-cli docs +fetch --as user --doc <url> --doc-format xml --detail with-ids --format json`，解析 `.data.document.content`，再由 `docx_xml_to_pseudo_markdown()` 转成带 `<!-- BLOCK_n | doxcn... -->` 标记的伪 `.lark.md`（XML 表格规范化为 markdown-format HTML 表格、`<h2>` 还原为 `## 📂 已归档资产`），落盘 `/workspace/.ephemeral_pool/` 任务唯一文件名
- 更新链路优先历史 `inner_skills/lark/mcp_lark_update_lark_doc.py`，并探测当前 lark-doc update shortcut；本地脚本候选缺失时切换 `lark-cli docs +update --as user` 执行 `block_replace` / `block_insert_after`；全部候选缺失时必须显式熔断，禁止退回 OpenAPI/JWT 直调
- 写后重新下载目标文档并做 RAW 回读验收
- 任一步失败都 `raise WikiArchiveError`，阻断主流程

可用以下命令做本地护栏自检：

```bash
python3 user_skills/info-miner/scripts/wiki_archive_guard.py --selftest
```

### Step 8：交付收尾
- 向用户返回：原文链接、飞书文档链接、归档分类、归档节点、归档表格中的新增记录摘要、灵感台账同步确认。
- 若本轮使用过浏览器调试链路，则必须在最终退出前执行 Browser Tab GC：逐个调用 `Target.closeTarget` 关闭本次任务打开的标签页，并通过 `python3 user_skills/info-miner/scripts/browser_tab_gc.py success --task-id "<task_id>" --tabs N --task-name "<任务名称>"` 或 `... failure --task-id "<task_id>" --reason "<失败原因>"` 追加日志。
- 若任一步失败，直接说明失败点与已完成状态，不得把失败包装成成功

## 失败重试策略
- 搜索结果不稳定：扩大 / 收敛关键词，加入作者 / 机构 / 站点限定
- 目标文章无法抓取：先尝试 canonical 链接、AMP、镜像页；若 Phase 0 轻量抓取已命中 `403 / timeout / Visitor System / anti-bot / 需登录`，则**优先自动走 fallback**：命中微信视频号域名先走 `scripts/wechat_channels_resolver.py`，命中微博域名先走 `yt-dlp probe`，若 `yt-dlp` 仍失败则继续调用 `weibo_headless_fetcher.py` 执行容器内 Headless/CDP 抓取，其它站点走 yt-dlp probe，不得等待主进程人工拍板
- 微信视频号解析失败：默认公开 Worker（`https://sph.litao.workers.dev/api/fetch_video_profile`）不可用时，脚本会 `raise WeChatChannelsError` 并给出自建提示；此时依据 `wx_channels_download` 仓库自建 Cloudflare Worker / 本地服务复现三段式，用 `--endpoint` 指向后重试；仍失败必须显式报错，禁止只交付裸链接
- 多候选无法判定：回到用户确认分支，避免拍脑袋选错出处
- 归档分类不确定：先用显式分类；没有显式分类时再推断；若仍无法落入白名单，则停止并说明分类无法确定
- 归档写入失败：重新下载目标 Wiki 文档并核查 `## 📂 已归档资产` 区块；若仍失败，必须报错中断，不得只交付文档链接

## 更新日志 (Changelog)
- 1.11（2026-08-19）：修复 Wiki 归档阶段 `toolset lark_download not found` 的 P1 熔断。
  - 根因：`inner_skills/lark_download/lark_download.py` 文件存在但背后 AIME toolset 已下线，而 resolver 只做存在性判定，把「文件存在」当成「可用」；更新链路已有 `lark-cli` 兜底，下载链路没有。
  - 修复：新增 `is_toolset_unavailable()` 可用性探测（命中 `toolset ... not found` / `AimeError` / `Error from AIME Server` 即继续降级）；新增 `lark_cli_download()` 走 `lark-cli docs +fetch --doc-format xml --detail with-ids`；新增 `docx_xml_to_pseudo_markdown()` / `xml_table_to_markdown_table()` 完成 DocxXML → 伪 `.lark.md` 与 markdown-format 表格规范化；产物落 `/workspace/.ephemeral_pool/` 任务唯一文件名。
  - 验收：`--selftest` 新增 3 条用例（toolset 不可用探测、XML→伪 lark.md 转换与表头提取、XML 链路补丁构造）；真机对 AI/Agent 节点验证解析出表格 block id 与 `next_index`，并在临时 docx 上完成 `block_replace --doc-format markdown` 写回 + RAW 回读。
- 1.9.2（2026-08-15）：修复 Wiki 归档脚本因历史 Lark MCP wrapper 缺失导致的 P1 熔断。
  - 根因：`wiki_archive_guard.py` 硬编码依赖 `inner_skills/lark/mcp_lark_lark_download.py` 与 `inner_skills/lark/mcp_lark_update_lark_doc.py`，但当前 `inner_skills` 已演进为 `inner_skills/lark_download/lark_download.py` 等 shortcut 目录，旧 wrapper 不存在。
  - 修复：在 info-miner 侧新增多候选 resolver 与下载输出解析器；下载链路兼容旧脚本并 fallback 到当前 `lark_download` shortcut；更新链路保留 MCP-only 候选解析，本地脚本缺失时通过 `lark-cli docs +update --as user` 执行块替换/插入，全部候选缺失时明确熔断，禁止 OpenAPI/JWT 直调。
  - 验收：`scripts/wiki_archive_guard.py --selftest` 覆盖本地归档补丁构造；CDA Guardrails 自检继续要求 L1/L2/L3 护栏齐备。
- 1.9.1（2026-07-29）：优化 `weibo_headless_fetcher.py` 抽取质量与误报控制。
  - `ttarticle` 长文：新增正文容器 selector + iframe 兜底，并在正文过短时触发二次提取。
  - `m.weibo.cn/detail`：新增 `window.$render_data` / `window.$data` 结构化抽取兜底，强化 title/author 规则。
  - 新增质量闸门：当 `text_len < 200` 时标记 `status=failed`，并在 `notes` 中写入 `content_too_short`。
- 1.9（2026-07-29）：补齐微博 Visitor System 的容器内 Headless/CDP 可执行降级路径。新增 `weibo_headless_fetcher.py`，通过 Playwright Chromium headless 启动独立浏览器实例，先尝试访客 cookie 获取，再执行桌面页与移动详情页双路渲染提取，输出标题/作者/发布时间/摘要/正文/HTML 路径，并在退出前调用 `scripts/browser_tab_gc.py` 写入 `/workspace/.ephemeral_pool/browser_gc.log`。SKILL.md 将降级链路固化为 `yt-dlp probe 失败 → 自动调用 weibo_headless_fetcher.py → 脚本失败才请求用户介入`，避免继续依赖用户本地 Chrome。
- 1.8（2026-07-26）：微博 Visitor System 新增二段降级链路。命中 `weibo.com` / `m.weibo.cn` / `weibo.cn` 且常规轻量抓取失败时，先强制走 `user_skills/yt-dlp-media-downloader` 的 `probe`；若 `yt-dlp probe` 仍失败，再自动切换浏览器模拟访问，参考 2026-07-26 梁文锋微博资料抓取任务的成功经验补齐 Phase 0 所需元信息。同步更新 Common Rationalizations / Red Flags / Verification(15) / Defaults / 失败重试策略，并扩展 `scripts/preflight_target_assertion.py` 支持 `ytdlp_error`、`browser_probe`、`domain_hint` 三个断言入口与自检用例。
- 1.6（2026-07-16）：Phase 0 fallback 新增「微信视频号专用解析」子分支。新增 `scripts/wechat_channels_resolver.py`：输入 sph/视频号分享链接（weixin.qq.com/sph、channels.weixin.qq.com、finder.video.qq.com），走「分享链接解析 → 提取 exportId(eid)+generalToken → feed_info 接口」三段式，默认 POST 到已验证可用的公开 Worker（`https://sph.litao.workers.dev/api/fetch_video_profile`），输出作者/文案/videoUrl(H264/H265)/封面/互动数/createtime 等结构化 JSON。命中视频号域名时优先调用该脚本而非 yt-dlp（yt-dlp 对视频号直接 Unsupported URL）；脚本带 L3 运行时断言（`validate_channels_url` 校验域名合法性、网络失败/feedInfo 缺失一律 raise），Worker 不可用时明确提示按 `wx_channels_download` 仓库自建 Worker 兜底，禁止静默降级。同步更新 Common Rationalizations / Red Flags / Verification(15) / Defaults / 失败重试策略。
- 1.5（2026-06-30）：新增“一手来源最低交付”硬标准。Step 1 明确要求把二手解读 / 转载追到最原始一手来源，并在最终 Docx 中显式写出「解读原文链接 + 一手原文链接 + 一手原文抓取状态（SUCCESS / FAILED + 原因）」。Step 3 新增硬规定：若存在一手来源，必须抓取其全文，除非明确不可访问。Step 5 / Step 6 强化非中文一手原文处理：必须将英中双语逐段对照作为附录写入同一篇 Docx，避免只给外链。
- 1.4（2026-06-16）：新增 Phase 0 自动 fallback 到 `user_skills/yt-dlp-media-downloader`。当轻量抓取遭遇 `403 / timeout / Visitor System / anti-bot / 需登录` 时，必须无缝触发 `yt-dlp probe` 作为前置物理摄入探针；断言层新增 `ytdlp_probe` 校验入口，要求在常规抓取失败时强制验证 fallback 是否已执行，避免再次把是否切换 yt-dlp 的决策抛回主进程。
- 1.1（2026-06-13）：新增浏览器操作收尾阶段的 Browser Tab GC。凡通过 Browser Extension / Chrome DevTools Protocol 打开的标签页，结束前必须逐个调用 `Target.closeTarget` 关闭，并通过 `scripts/browser_tab_gc.py` 以 append 模式向 `/workspace/.ephemeral_pool/browser_gc.log` 写入结构化成功 / 失败记录。
- 0.5（2026-05-22）：新增“交付 payload 防污染规则”。强制要求卡片 / post payload 落盘到 `/workspace/.ephemeral_pool/` 且使用任务唯一文件名；发送前必须做主题一致性断言；发送后必须执行上下文熔断；旧 `card.json` / `post.json` 仅可取证，不得复用。
- 0.4（2026-05-22）：物理隔离理性与感性资产。废除“前置嵌入文档头部”规则；强制要求飞书文档（Docx）与灵感卡片（EP-CARD）完全分离，交付时必须分发两条独立消息。新增“灵感台账”同步规则，强制要求记录存入指定 Bitable（`PRbvbUyLqaeITqsXNMRcRCM5nhh`）。
- 0.3（2026-05-20）：新增“闭环归档 SOP”。引入 `scripts/wiki_archive_guard.py`，内置 `CATEGORY_NODE_MAP` 六分类路由表，支持显式分类优先 / 自动推断兜底、固定表头归档行构造、飞书 MCP 路径写入 `## 📂 已归档资产` 表格、写后 RAW 回读验收，以及归档失败即 raise 的硬熔断逻辑；同时保留 Phase 0 目标前置校验、中文源中文直出、非中文源双语对照、内容隔离法则等原有高质量能力。
- 0.2（2026-05-19）：在 Step 0 之前新增【Phase 0：目标前置校验 (Pre-Flight Target Assertion)】硬熔断闸门：拿到 URL 后必须先做轻量抓取（标题 / 作者 / 发布时间 / 域名 / 首段摘要），并按“分支 A 用户上下文交叉比对（作者 / 主题 / 关键词三维度）/ 分支 B 输出【目标确认卡片】等待用户显式确认”分流；任意 mismatch 或抓取失败立即熔断，禁止越级进入全文抓取 / 翻译 / 排版 / 写飞书。
- 0.1.2（2026-05-04）：增加内容隔离法则，防止信息挖掘时过度联想电商场景。
- 0.1.1（2026-04-26）：新增“语言判断分支”硬规则：中文源 → 中文结构化直出；非中文源 → 英中双语逐段对照。
- 0.1.0（2026-04-26）：初版，固化“溯源式搜索 → 网页抓取 → 关键信息总结 → 外文源双语对照 → 飞书文档排版”主流程。


## 操作示例
Skill 资源位于 `user_skills/info-miner`，**文档中所有相对路径/命令均相对于此目录**，按需执行以下操作：
- 读取文档：`view_skill user_skills/info-miner/<文件相对路径>, 优先使用 view_skill 查看`
- 执行脚本：先 `cd user_skills/info-miner`，再执行（如 `python3 weibo_headless_fetcher.py --url "<微博链接>"`、`python3 scripts/preflight_target_assertion.py`、`python3 scripts/wiki_archive_guard.py`、`python3 scripts/wechat_channels_resolver.py --selftest`、`python3 scripts/browser_tab_gc.py --selftest`）
- 若本 Skill 内容中提及 MCP 工具（如 `mcp_lark_*`、`mcp_aeolus_*` 等），需先通过 `view_skill` 读取对应 MCP skill 了解参数 schema 后再调用
