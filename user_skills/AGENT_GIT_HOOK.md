# Qi-Skills Git Push Hook

## 仓库
https://github.com/Yu1ocean/qi-skills

## 自动 push 触发方式
每次 skill-forge-pipeline-v4 锻造/迭代完成后，执行：
```bash
bash user_skills/scripts/post_forge_git_push.sh <skill_name> <version>
```

## 手动 push（任何时候）
```bash
cd /workspace/iris_19f7e856-22a9-491e-b611-5e5c09e9e419
git add user_skills/
git commit -m "chore: manual sync $(date +%Y-%m-%d)"
git push origin main
```

## 凭证存储
GitHub PAT 已存储在 `~/.git-credentials`，credential.helper=store。
