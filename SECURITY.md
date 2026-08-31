# 安全政策 / Security Policy

## 私密报告 / Private reporting

凭据泄露、身份绕过、私有部署暴露、Runner 隔离逃逸、未授权外发或其他安全问题不得创建
公开 GitHub Issue。请使用仓库的
[Private Vulnerability Reporting](https://github.com/joonas-001/cloud_study_everything/security/advisories/new)
私密报告入口。

Do not open a public GitHub Issue for credential exposure, authentication bypass, private
deployment exposure, Runner isolation escape, unauthorized data transfer, or another security
problem. Use the repository's Private Vulnerability Reporting entry instead.

如果该私密入口尚未由仓库所有者启用，请停止提交，不要改用公开 Issue、评论、截图或附件。
8F 中的此链接只是仓库内准备；启用远程功能仍需项目所有者另行授权。

If the private entry has not been enabled by the repository owner, stop rather than falling back
to a public Issue, comment, screenshot, or attachment. The 8F link is repository-side preparation;
enabling the remote feature still requires separate owner authorization.

## 不得提交的内容 / Prohibited content

- API、SMTP、OAuth、Microsoft、GitHub、Tailscale 或其他凭据；
- 用户名、邮箱、Tailnet 名称、私有 IP/URL、数据库路径或任意本地路径；
- 诊断回答、学习答案、代码、作品、迁移任务、证据正文或真人评审敏感材料；
- AI 提示或响应、市场摘录、收入金额、合同、账单、银行材料；
- SQLite 数据、备份密钥、原始日志、完整日志压缩包、崩溃转储或基础设施秘密。

Do not submit credentials, identity data, private addresses, local paths, learning content, code,
evidence bodies, AI or market bodies, financial data, databases, keys, raw logs, log archives,
crash dumps, or infrastructure secrets.

## 响应边界 / Response boundary

本项目当前为项目所有者单用户使用，不承诺公开漏洞奖励或固定响应时限。收到报告后应先
限制暴露、保存最小审计证据、评估受影响范围，再按 `AGENTS.md`、`TODO.md` 和既有部署回滚
门禁处理。安全报告本身不构成扩容、付费、公开发布或其他实施授权。

This owner-only project does not promise a public bounty or fixed response time. A report does not
authorize expansion, spending, public release, or any other implementation beyond the governed
repository decisions.
