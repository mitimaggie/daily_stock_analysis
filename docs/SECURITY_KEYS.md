# API Key 安全说明

## 为什么收到 Google「Publicly accessible API key」告警？

说明该 API Key 曾在**公开可访问**的地方出现，例如：

- `.env` 被误 `git add` 并 push 到公开仓库（或 fork）
- 在 Issue、文档、截图里粘贴过 key
- CI/构建日志中打印了环境变量

**即使现在 .gitignore 里有 .env，历史提交里若有过一次就会一直被扫描到。**

---

## 立即要做的事（必须）

### 1. 在 Google Cloud 里作废旧 Key、换新 Key

1. 打开 [Google Cloud Console](https://console.cloud.google.com/) → 选择项目 **Default Gemini Project**
2. **API 和服务** → **凭据** → 找到当前使用的 API 密钥
3. **删除**该密钥（或「限制密钥」里先禁用）
4. **创建新的 API 密钥**，仅用于本机/服务器
5. 在**本机**的 `.env` 里把 `GEMINI_API_KEY=...` 改成新 key，**不要**提交 `.env`

旧 key 一旦泄露就应视为永久失效，仅换新 key 才能止血。

---

## 如何保护 API Key（长期）

### 1. 确保 .env 永不进 Git

- 项目已把 `.env`、`.env.*`、`*.env` 写进 `.gitignore`，**不要**用 `git add -f .env` 强制添加
- 新 clone 仓库后：复制 `.env.example` 为 `.env`，在**本地**填写 key，不要提交 `.env`

### 2. 不要在任何公开处粘贴 Key

- 不在 GitHub/GitLab 的 Issue、PR、Wiki、README 里贴 key
- 不在截图、录屏里露出 `.env` 或终端里 `echo $GEMINI_API_KEY` 的输出
- 文档/示例里只用占位符，例如 `GEMINI_API_KEY=your_key_here`

### 3. 可选：用 pre-commit 防止误提交

在仓库根目录执行（只需一次）：

```bash
chmod +x .github/scripts/check-no-secrets.sh
ln -sf ../../.github/scripts/check-no-secrets.sh .git/hooks/pre-commit
```

之后每次 `git commit` 都会检查是否误加了 `.env` / `.env.*`，若有会拒绝提交。

---

## 若确认 .env 曾被提交过

1. **先按上面步骤换新 key**，再考虑改历史  
2. 从 Git 历史里删除敏感文件要用重写历史（如 `git filter-repo` 或 BFG），操作前备份仓库并通知协作者  
3. 换 key 后，旧 key 已失效，历史里即使还有旧 key 也无法再被滥用，但建议仍从历史中移除以符合安全规范  

---

## 小结

| 步骤 | 说明 |
|------|------|
| 立即 | 在 Google Cloud 删除/禁用旧 API 密钥，创建新密钥，只在本机 `.env` 中更新 |
| 日常 | 不提交 `.env`，不把 key 贴到任何公开地方 |
| 可选 | 启用 pre-commit 检查，防止误提交含 key 的文件 |
