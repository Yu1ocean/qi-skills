#!/bin/bash
# Post-forge Git Push Hook (v2 — 远端 SHA 回读断言版)
# 在每次技能锻造/迭代完成后调用此脚本，自动 commit 并把【当前 HEAD】推到 qi-skills 的 main。
#
# 修复的 P1 假成功缺陷：
#   旧实现执行 `git push origin main`。当工作副本 HEAD 处于特性分支（如 aime/xxx）时，
#   该命令推送的是【本地陈旧的 main ref】而非刚提交的 HEAD，退出码依然是 0，
#   于是流水线宣称“已 push 到 qi-skills”，而新版本 SKILL.md / 脚本根本没到 GitHub（幽灵资产）。
#
# 本版本的两条铁律：
#   1. 一律 `git push --force-with-lease origin HEAD:main`，不再依赖本地 main ref；
#   2. push 后必须回读远端 refs/heads/main 的 SHA 并与本地 HEAD SHA 比对；
#      不一致 => 判定 FAIL，以非 0 退出码退出，禁止仅凭 git push 的退出码判定成功。
#
# 环境开关：
#   SKIP_POST_FORGE_GIT_PUSH=1  跳过整个 hook（调试用，保留原语义）
#   POST_FORGE_REMOTE           远端名，默认 origin
#   POST_FORGE_TARGET_BRANCH    远端目标分支，默认 main
#   POST_FORGE_DRY_RUN=1        故障注入：跳过真实 push，但仍执行远端回读断言
#                               （用于验证“push 未真正生效”时脚本能否非 0 退出）
#
# v3 并发安全（C+D 组合）：
#   C. flock 系统级文件锁（/tmp/qi-skills-forge.lock）串行化 git add/commit/push，
#      最多等待 300s，超时熔断退出，避免多个 forge 进程同时操作同一工作副本。
#   D. push 一律带 --force-with-lease，远端被其他 session 改写时拒绝无声覆盖。

set -uo pipefail

# ---------- C 方案：flock 系统级文件锁 ----------
LOCK_FILE="${POST_FORGE_LOCK_FILE:-/tmp/qi-skills-forge.lock}"
exec 9>"$LOCK_FILE"
flock -x -w 300 9 || { echo "[forge-lock] 等待超时(300s)，另一 forge 进程可能仍在运行，退出" >&2; exit 1; }

SKILL_NAME="${1:-unknown-skill}"
SKILL_VERSION="${2:-latest}"

REPO_ROOT="${POST_FORGE_REPO_ROOT:-/workspace/iris_19f7e856-22a9-491e-b611-5e5c09e9e419}"
REMOTE="${POST_FORGE_REMOTE:-origin}"
TARGET_BRANCH="${POST_FORGE_TARGET_BRANCH:-main}"

log()  { printf '%s\n' "$*"; }
fail() {
  log ""
  log "================ POST-FORGE GIT PUSH: FAIL ================"
  log "❌ $*"
  log "🧑‍🔧 需人工介入：请在仓库根目录手动执行"
  log "     git push --force-with-lease ${REMOTE} HEAD:${TARGET_BRANCH}"
  log "   并用 git ls-remote ${REMOTE} refs/heads/${TARGET_BRANCH} 回读确认 SHA。"
  log "==========================================================="
  exit 1
}

if [ "${SKIP_POST_FORGE_GIT_PUSH:-}" = "1" ]; then
  log "⏭️ post-forge git push skipped by SKIP_POST_FORGE_GIT_PUSH=1"
  exit 0
fi

cd "$REPO_ROOT" || fail "无法进入仓库根目录: $REPO_ROOT"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "不是 git 工作副本: $REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"

log "=========== POST-FORGE GIT PUSH (HEAD:${TARGET_BRANCH}) ==========="
log "skill        : ${SKILL_NAME} ${SKILL_VERSION}"
log "repo_root    : ${REPO_ROOT}"
log "local_branch : ${BRANCH}"

# ---------- 1. commit 阶段 ----------
git add user_skills/ || fail "git add user_skills/ 失败"

if git diff --cached --quiet; then
  log "commit       : no staged changes (跳过 commit，继续执行 push + 远端断言)"
else
  git commit -m "feat(skill): upsert ${SKILL_NAME} ${SKILL_VERSION}

Auto-pushed by post_forge_git_push hook.

Co-Authored-By: Aime aime@bytedance.com" || fail "git commit 失败"
  log "commit       : created"
fi

LOCAL_HEAD="$(git rev-parse HEAD)" || fail "无法解析本地 HEAD"
log "local_head   : ${LOCAL_HEAD}"

remote_main_sha() {
  git ls-remote "$REMOTE" "refs/heads/${TARGET_BRANCH}" 2>/dev/null | awk '{print $1}' | head -1
}

do_push() {
  if [ "${POST_FORGE_DRY_RUN:-}" = "1" ]; then
    log "push         : SKIPPED (POST_FORGE_DRY_RUN=1 故障注入，仅执行远端断言)"
    return 0
  fi
  # --force-with-lease 需要本地存在远端跟踪 ref 作为 lease 基准，缺失时先补一次 fetch
  git rev-parse --verify --quiet "refs/remotes/${REMOTE}/${TARGET_BRANCH}" >/dev/null 2>&1 \
    || git fetch "$REMOTE" "$TARGET_BRANCH" >/dev/null 2>&1 || true
  git push --force-with-lease "$REMOTE" "HEAD:${TARGET_BRANCH}" 2>&1
}

# ---------- 2. 首次 push ----------
PUSH_OUT="$(do_push)"; PUSH_RC=$?
log "push_attempt1: rc=${PUSH_RC}"
[ -n "$PUSH_OUT" ] && log "$PUSH_OUT"

# ---------- 3. non-fast-forward 冲突处理：fetch + rebase(或 merge) 后重试一次 ----------
if [ "$PUSH_RC" -ne 0 ]; then
  log "⚠️ 首次 push 失败，尝试 fetch + rebase/merge 后重试一次..."
  git fetch "$REMOTE" "$TARGET_BRANCH" || fail "git fetch ${REMOTE} ${TARGET_BRANCH} 失败"

  if git rebase "${REMOTE}/${TARGET_BRANCH}"; then
    log "reconcile    : rebase onto ${REMOTE}/${TARGET_BRANCH} OK"
  else
    log "⚠️ rebase 失败，回滚并改用 merge..."
    git rebase --abort 2>/dev/null || true
    if git merge --no-edit "${REMOTE}/${TARGET_BRANCH}"; then
      log "reconcile    : merge ${REMOTE}/${TARGET_BRANCH} OK"
    else
      git merge --abort 2>/dev/null || true
      fail "rebase 与 merge 均失败（存在冲突），无法自动与远端 ${TARGET_BRANCH} 对齐"
    fi
  fi

  LOCAL_HEAD="$(git rev-parse HEAD)" || fail "无法解析本地 HEAD"
  log "local_head   : ${LOCAL_HEAD} (reconciled)"

  PUSH_OUT="$(do_push)"; PUSH_RC=$?
  log "push_attempt2: rc=${PUSH_RC}"
  [ -n "$PUSH_OUT" ] && log "$PUSH_OUT"

  if [ "$PUSH_RC" -ne 0 ]; then
    fail "重试后 push 仍失败（rc=${PUSH_RC}），需人工介入"
  fi
fi

# ---------- 4. 远端回读断言（核心：杜绝假成功） ----------
REMOTE_SHA="$(remote_main_sha)"
[ -z "$REMOTE_SHA" ] && fail "无法回读远端 ${REMOTE}/${TARGET_BRANCH} 的 SHA（ls-remote 为空）"

log "remote_${TARGET_BRANCH}  : ${REMOTE_SHA}"
log "-----------------------------------------------------------"
log "assert       : local_head == remote_${TARGET_BRANCH} ?"

if [ "$LOCAL_HEAD" != "$REMOTE_SHA" ]; then
  log "assert_result: FAIL"
  log "   local  HEAD                     = ${LOCAL_HEAD}"
  log "   remote ${REMOTE}/${TARGET_BRANCH} = ${REMOTE_SHA}"
  fail "远端 ${TARGET_BRANCH} 的 SHA 与本地 HEAD 不一致 —— push 未真正生效（假成功已被拦截）"
fi

log "assert_result: PASS"
log "✅ ${SKILL_NAME} ${SKILL_VERSION} 已真实同步到 ${REMOTE}/${TARGET_BRANCH} @ ${REMOTE_SHA}"
log "   (branch=${BRANCH}, pushed via HEAD:${TARGET_BRANCH})"
log "==========================================================="
log "💡 如果尚未安装 >50MB pre-push 熔断 hook，可运行：bash user_skills/scripts/install_hooks.sh"
exit 0
