#!/bin/bash
# Post-forge Git Push Hook
# 在每次技能锻造/迭代完成后调用此脚本，自动 commit+push 到 qi-skills
set -e

SKILL_NAME="${1:-unknown-skill}"
SKILL_VERSION="${2:-latest}"

cd /workspace/iris_19f7e856-22a9-491e-b611-5e5c09e9e419

git add user_skills/
git diff --cached --quiet && echo "No changes to commit" && exit 0

git commit -m "feat(skill): upsert ${SKILL_NAME} ${SKILL_VERSION}

Auto-pushed by post_forge_git_push hook.

Co-Authored-By: Aime aime@bytedance.com"
git push origin main
echo "✅ ${SKILL_NAME} pushed to qi-skills"
