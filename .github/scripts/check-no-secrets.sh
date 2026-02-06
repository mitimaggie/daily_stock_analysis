#!/bin/sh
# 防止误将 .env 或含敏感信息的文件提交到 Git
# 用法：chmod +x .github/scripts/check-no-secrets.sh && .github/scripts/check-no-secrets.sh
# 或作为 pre-commit hook：ln -sf ../../.github/scripts/check-no-secrets.sh .git/hooks/pre-commit

set -e
STAGED=$(git diff --cached --name-only 2>/dev/null || true)
for f in $STAGED; do
  case "$f" in
    .env|.env.*|*.env)
      echo "错误: 禁止提交敏感文件: $f"
      echo "请从暂存区移除: git reset HEAD -- $f"
      exit 1
      ;;
  esac
done
exit 0
