# 如何提交高质量问题 / How to report a high-quality issue

> 状态：8F 仓库内置顶指南正文候选。将它创建为远程置顶 Issue、同步标签或提交测试 Issue
> 都属于 GitHub 外部写操作，必须另行授权。

## 快速流程 / Quick flow

1. 确认问题仍能在当前版本复现，并搜索相似标题、原因码、能力或活动 ID；
2. 选择“缺陷”“功能或改进”或“内容或证据”表单；安全问题改走私密入口；
3. 在“设置 → 系统状态 → 报告问题”生成诊断，完整预览并删除不需要的可选字段；
4. 复制脱敏诊断，再由你主动打开 GitHub、最终检查并提交。系统不会自动提交或上传。

1. Reproduce on the current version and search by title, reason code, capability ID, or activity ID.
2. Choose Bug, Feature or improvement, or Content or evidence. Use the private entry for security.
3. Generate a diagnostic under Settings → System status → Report an issue; review it in full and
   remove any optional fields you do not need.
4. Copy the sanitized diagnostic, then explicitly open GitHub, inspect, and submit it yourself. The
   application never submits or uploads automatically.

## 隐私规则 / Privacy rules

应用内诊断只允许版本、非识别性系统摘要、健康状态、数据库 schema revision、页面路由、
受管操作、精确技能版本、Runner 协议和启用状态、功能开关、UUID 审计 ID、原因码、时间以及
受管事件名称。首版不支持完整日志、附件或后台上传。

不要提交答案、代码、作品、证据正文、真人评审材料、凭据、身份、邮箱、私有地址、任意本地
路径、SQLite、备份密钥、AI 或市场正文、收入或账单。截图也适用同一规则。

The in-app diagnostic is allowlist-only and supports no full logs, attachments, or background
uploads. Do not submit answers, code, artifacts, evidence bodies, reviewer material, credentials,
identity data, email, private addresses, any local path, SQLite data, backup keys, AI or market
bodies, income, or billing data. The same rule applies to screenshots.

## 分诊与关闭 / Triage and closure

- 新 Issue 从 `status:needs-triage` 开始；缺信息时进入 `status:needs-info`；
- 重复问题关联原 Issue 并加 `duplicate`，不通过重建丢失上下文；
- `needs-info` 14 天无补充可人工关闭，仍可 reopen；首版没有自动关闭；
- `status:accepted` 只表示问题被接受，不表示已授权实施；
- 实施前必须绑定精确阶段、GitHub Milestone 和 `TODO.md` 编号；
- PR 只有在测试、验收证据和限制说明齐全后才能使用 `Closes #...` 完成关闭；
- 关闭原因必须说明为 `completed`、`duplicate`、`not-planned` 或 `cannot-reproduce`；
- 同一缺陷再次出现时优先 reopen 并加 `regression`。

New reports begin in `status:needs-triage`. Acceptance is not implementation authorization.
Duplicates link to the original report, missing-information reports may be closed manually after
14 days while remaining reopenable, and regressions should reopen the original issue.

## 账本关系 / Source-of-truth relationship

`AGENTS.md` 保存长期约束，`TODO.md` 是授权和门禁账本，GitHub Milestone 是远程执行视图，
Issue 是可验证工作单元，PR 保存实现与 CI 证据。Issue 或标签不能替代产品数据库，也不能
扩大仓库授权。
