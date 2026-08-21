# 归档记录：skill-forge-pipeline-v4

> ⚠️ 本目录为**墓碑归档区（Tombstone）**，非可运行技能。目录内无 `SKILL.md`，不会被技能扫描器识别为技能，不占用预加载候选池槽位。

## 一、归档原因

`user_skills/skill-forge-pipeline-v4/` 是 `skill-forge-pipeline`（v5.19 起改名，**正主**，当前 v5.21+）的僵尸副本，两者**共享同一 Skill ID `SKILL-FORGE-PIPELINE`**，并共享同一说明文档 `HgY3dJBPfowjJfxWnxWcvItJncg`。

该双活目录是 2026-08-21 「ZIP 幽灵块事故」的直接根源：

- 子特工在派发 forge 任务时按技能名自行猜目录，**误改了 v4 僵尸副本并执行 forge**；
- 结果把飞书「专属技能清单」台账的版本从 **5.20.2 倒灌为 5.15**，技能名被写成 `skill-forge-pipeline-v4`；
- 同时给共享说明文档挂上了第 2 个 ZIP 文件块，成为幽灵安装包。

事故已于同日修复（台账回正为 `skill-forge-pipeline` / v5.21，全库 22 个幽灵 ZIP 块清理完毕，forge 的 ZIP upsert 护栏由 `⚠️ WARNING` 升级为 `raise GuardrailViolation` 硬熔断）。本目录归档即为斩断复发路径。

## 二、归档现状（重要）

原始源码目录**在归档动作之前已被物理移除**，见 commit `4786fa9`（*chore: remove deprecated skill-forge-pipeline-v4 dir (renamed to skill-forge-pipeline at v5.19)*）；其孤儿 gitlink 已在 commit `99c6c03` 通过 `git rm --cached` 摘除并写入 `.gitignore`。

因此本次归档实际收拢的是**残留物**：

| 残留物 | 原路径 | 现路径 | Git 状态 |
|---|---|---|---|
| 构建产物 ZIP（2.9MB） | `user_skills/skill-forge-pipeline-v4.zip` | `user_skills/_archived_skill-forge-pipeline-v4_20260821/skill-forge-pipeline-v4.zip` | 未跟踪（`.gitignore: *.zip`） |
| 陈旧草稿快照（2026-07-30） | `.aime/skill_draft/skill-forge-pipeline-v4/` | `.aime/skill_draft_archived/skill-forge-pipeline-v4_20260821/` | 未跟踪 |

> 草稿快照**刻意不放入 `user_skills/`**：该目录会被 Git 跟踪，移入即等于把僵尸代码重新灌回版本库。

## 三、生命周期

- **归档日期**：2026-08-21
- **TTL 到期日**：2026-09-21（满 30 天后可授权物理删除）
- **授权条件**：用户奇楠确认 30 天内无异常后，**口头授权即可执行**物理删除（无需额外书面流程）。

## 四、物理删除操作步骤（到期后执行）

```bash
cd /workspace/iris_19f7e856-22a9-491e-b611-5e5c09e9e419

# 1. 删除墓碑目录与草稿快照
rm -rf user_skills/_archived_skill-forge-pipeline-v4_20260821/
rm -rf .aime/skill_draft_archived/skill-forge-pipeline-v4_20260821/

# 2. 摘除 Git 索引（ARCHIVED.md 是唯一被跟踪的文件）
git rm -r --cached user_skills/_archived_skill-forge-pipeline-v4_20260821/

# 3. 提交并推送（注意工作区常不在 main 分支）
git commit -m "chore: purge archived skill-forge-pipeline-v4 tombstone (TTL expired 2026-09-21)"
git push origin HEAD:refs/heads/main
```

> 删除属**灾难性操作**，须遵守 DEC-20260613-005：执行前必须取得用户显式授权，禁止自主推进。

## 五、防复发护栏

1. **派发 forge 任务前，主脑必须在 Prompt 中显式钉死目标目录**，禁止让子特工按技能名自行猜目录。
2. 台账**版本号只能升不能降**，出现版本回退即视为事故信号，立即熔断排查。
3. forge 前核对目录内 `SKILL.md` frontmatter 的 `name` 与 `version`，确认是「正主」。
