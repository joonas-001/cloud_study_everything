# GitHub Issues 提交流程研究与云奕学适配

> 状态：第八里程碑方法基线，不构成创建 GitHub Issue、标签、里程碑或自动化的授权  
> 核验日期：2026-08-28（Asia/Shanghai）  
> 参照项目：`xingkongliang/skills-manager@8f34bf144c579421e9dad25b89c9d936915d4615`  
> 许可证：参照仓库根级 MIT；本文只提炼方法，不复制模板正文或产品代码

## 1. 核验结论

用户提供的 `xingkongliang` 主页下有多个公开仓库。与“同款 Issues 提交流程”直接对应、
且近期持续使用的是 [skills-manager](https://github.com/xingkongliang/skills-manager)。本次核验了：

- 精确提交 `8f34bf144c579421e9dad25b89c9d936915d4615` 下的 Bug 模板；
- 同一提交下的 Feature Request 模板；
- 同一提交下的 Issue Template 配置；
- 置顶指南 [Issue #155](https://github.com/xingkongliang/skills-manager/issues/155)；
- Bug、功能、安全/隐私类代表性 Issues，包括 #405、#406、#407；
- 2026-08-28 可观察的近期 Issue 标签、状态和正文结构。

该项目的核心不是复杂项目管理，而是把问题反馈压缩为低门槛流程：

```text
升级当前版本
  → 应用内点击“报告问题”
  → 自动复制脱敏诊断并打开预填 Issue
  → 用户补一句问题描述、粘贴诊断并提交
```

## 2. 原流程的组成

### 2.1 Bug 模板

根级模板使用中英双语 Markdown，只要求三个区域：

1. `What happened? / 发生了什么？`；
2. `Diagnostics / 诊断信息`；
3. `Full logs (optional) / 完整日志（可选）`。

模板自动加 `bug` 标签。置顶 Issue 说明应用内“报告问题”按钮会复制版本、操作系统、
Agent、界面语言和近期日志摘要，并打开预填模板。

### 2.2 Feature Request 模板

功能模板只要求 `What would you like? / 想要什么？`，提示提交者说明要解决的问题和理想
行为，并自动加 `enhancement` 标签。

### 2.3 入口配置

`config.yml`：

- 禁止空白 Issue；
- 问题、想法和一般讨论转到 Discussions；
- 提供官方网站入口。

### 2.4 置顶快速指南

Issue #155 进一步规定：

- 提交前先升级到包含自动诊断按钮的当前版本；
- 先搜索已知问题；
- 简短描述也可以，但诊断越完整越容易定位；
- 中文和英文都接受；
- `needs-info` 两周未补充时可关闭，并保留 reopen 权利；
- `known-issue` 表示已有专门跟踪；
- 黑屏、卡死、启动失败等复杂问题可以导出脱敏日志压缩包。

### 2.5 代表性高质量 Issue

Issue #405 和 #406 虽通过简短 Feature Request 入口创建，但正文实际补充了：

- 想要的改变；
- 当前行为和精确版本/提交；
- 可复核证据；
- 为什么重要；
- 建议改进；
- 验收标准；
- 关联治理讨论。

这套结构比原始功能模板更适合作为云奕学的正式功能、隐私和安全事项模板。

## 3. 不应照搬的部分

### 3.1 标签不一致

近期样本中有功能建议被标为 `bug`，也有同类 Issue 没有标签。云奕学若依赖标签生成待办或
发布门禁，必须使用受管标签集合和模板自动标签，不能让标签语义漂移。

### 3.2 重复 Issue

安全签名和 GitHub Backup 权限问题分别出现过关闭后重新建立的新 Issue。云奕学需要显式的
重复搜索、`duplicate-of` 关联和 reopen 规则，不能通过重建 Issue 丢失讨论上下文。

### 3.3 缺少里程碑绑定

抽查的近期 Issues 没有 Milestone、Assignee 或项目字段。云奕学已有严格里程碑和 TODO 账本，
每个被接受的实施 Issue 应绑定精确里程碑、阶段和 `TODO.md` 编号。

### 3.4 完整日志附件不适合直接照搬

skills-manager 支持把脱敏日志 zip 拖入 Issue。云奕学处理学习答案、代码、证据、AI 配置、
市场材料、收入和私有部署信息，误传风险更高。第八里程碑首版不应支持完整日志附件，只应
生成允许列表字段组成、用户可预览的文本诊断。

### 3.5 Discussions 不一定适合单用户阶段

云奕学当前仅项目所有者本人使用。除非以后公开社区或协作维护，Questions/Ideas 不需要单独
启用 Discussions；不确定的问题仍可走 Bug 或 Feature 入口并在分诊时改类。

## 4. 云奕学适配后的入口

建议使用 GitHub Issue Forms，而不是直接复制 Markdown 模板，以获得必填字段、下拉选项和
稳定自动标签。建议文件只在第八里程碑相应阶段获授权后创建：

| 入口 | 建议文件 | 自动标签 | 用途 |
| --- | --- | --- | --- |
| 缺陷报告 | `.github/ISSUE_TEMPLATE/bug.yml` | `type:bug`、`status:needs-triage` | 可复现故障、错误状态、回归 |
| 功能或改进 | `.github/ISSUE_TEMPLATE/feature.yml` | `type:enhancement`、`status:needs-triage` | 新能力、体验和运维改进 |
| 内容或证据问题 | `.github/ISSUE_TEMPLATE/content.yml` | `type:content`、`status:needs-triage` | 来源、题目、答案、能力范围、证据边界问题 |
| 安全问题 | `config.yml` 中的私密入口 | 不创建公开标签 | 跳转 `SECURITY.md` 和 GitHub Private Vulnerability Reporting |

`config.yml` 推荐：

- `blank_issues_enabled: false`；
- 不把安全问题引导到公开 Issue；
- 单用户阶段不强制启用 Discussions；
- 文档或私有应用入口只有在 URL 稳定且不会暴露 Tailnet 地址时才显示。

## 5. 模板字段

### 5.1 缺陷报告

必填：

- 一句话问题摘要；
- 发生了什么；
- 期望行为；
- 最小复现步骤；
- 影响范围和是否阻断学习；
- 当前版本或提交；
- 用户已预览的脱敏诊断。

选填：

- 截图，但必须先确认不含答案、代码、证据正文、账户或私有地址；
- 相关 Issue、PR、审计 ID 或错误原因码。

### 5.2 功能或改进

必填：

- 要解决的问题；
- 理想行为；
- 为什么现在需要；
- 与已确认产品边界是否冲突；
- 可观察验收标准。

选填：

- 替代方案；
- 依赖、费用、隐私和迁移影响；
- 相关里程碑或差距编号。

### 5.3 内容或证据问题

必填：

- 精确技能和版本；
- 能力范围、单元、活动或来源 ID；
- 问题类型：来源、事实、歧义、答案、Runner 测试、量表、证据等级或时效；
- 可复核的最小描述；
- 期望处理方式。

禁止直接粘贴用户答案、完整代码、作品正文、付费内容或未获许可的第三方课程。

## 6. 应用内“报告问题”流程

建议保留参照项目的四步体验，但增加云奕学的预览和外发确认：

1. 用户在“设置 → 系统状态 → 报告问题”点击生成诊断；
2. 后端只生成允许列表字段，前端完整展示将复制的文本；
3. 用户可删除任一可选字段并确认复制；
4. 浏览器打开预填 GitHub Issue 页面，用户自行检查并提交。

系统不得自动创建、提交或上传 Issue，不得在后台发送诊断，也不得因为生成诊断而切换 AI
供应商、调用外部 AI 或访问学习来源。

### 6.1 允许进入诊断的字段

- 应用版本、精确提交和部署策略版本；
- 操作系统和架构的非识别性摘要；
- Web/API 健康状态与数据库 schema revision；
- 当前页面路由和失败操作类型；
- 精确技能包版本，但不含学习正文；
- Runner 协议、运行时 ID/版本、启用状态和基础设施原因码；
- 功能开关的开/关状态，不含密钥或端点；
- 请求审计 ID、错误原因码、时间和时区；
- 允许列表内的结构化日志事件名称和级别。

### 6.2 禁止进入诊断、截图或附件的内容

- API、SMTP、OAuth、Microsoft、GitHub、Tailscale 或其他凭据；
- 用户名、邮箱、Tailnet 名称、私有 IP、私有 URL、数据库路径和任意用户本地路径；
- 学习答案、诊断回答、用户代码、作品、迁移任务和自由文本；
- 六维证据正文、真人评审者身份材料或敏感附件；
- 市场来源摘录、AI 提示词、AI 响应原文和供应商请求正文；
- 收入金额、合同、账单、银行信息或费用明细；
- SQLite 数据、备份密钥、日志原文或崩溃内存转储；
- Docker Socket、宿主挂载和其他基础设施秘密。

第八里程碑首版不提供“完整日志 zip 上传”。如果以后需要，必须另行确认私有传输、自动
脱敏、秘密扫描、用户逐文件预览、保留期限和删除方式。

## 7. 标签和生命周期

### 7.1 受管标签

| 类别 | 标签 |
| --- | --- |
| 类型 | `type:bug`、`type:enhancement`、`type:content`、`type:governance` |
| 状态 | `status:needs-triage`、`status:needs-info`、`status:accepted`、`status:blocked`、`status:in-progress`、`status:needs-verification` |
| 优先级 | `priority:p0`、`priority:p1`、`priority:p2` |
| 区域 | `area:web`、`area:api`、`area:learning`、`area:evidence`、`area:runner`、`area:deployment`、`area:docs` |
| 特殊关系 | `known-issue`、`duplicate`、`regression` |

标签说明和颜色应保存在仓库文档或版本化配置中。标签同步属于 GitHub 外部写操作，实施时
需要项目所有者明确授权，不能因为模板文件已合并就自动修改远程仓库。

### 7.2 生命周期

```text
needs-triage
  → needs-info / duplicate / rejected-with-reason
  → accepted
  → blocked / in-progress
  → needs-verification
  → closed
  → regression 时 reopen
```

规则：

- 提交前搜索标题、原因码和能力/活动 ID；
- 重复问题优先关联原 Issue，不重新创建丢失上下文；
- `needs-info` 连续 14 天无补充可人工关闭，保留 reopen 权利；首版不建立定时自动关闭；
- `accepted` 只表示问题被接受，不构成阶段授权；
- 实施 Issue 必须绑定 GitHub Milestone、`TODO.md` 编号和精确范围；
- PR 使用 `Closes #...`，但只有测试、验收证据和限制说明齐全后才合并；
- 关闭原因必须是 `completed`、`duplicate`、`not-planned` 或 `cannot-reproduce` 之一，并说明理由；
- 重新出现同一缺陷时优先 reopen 并标 `regression`。

## 8. GitHub 与仓库账本的关系

- `AGENTS.md`：已确认的长期产品和工程约束；
- `TODO.md`：授权、门禁、阻塞和完成证据的唯一仓库级账本；
- GitHub Milestone：某一已确认阶段的远程执行视图；
- GitHub Issue：一个可验证问题或工作单元；
- Pull Request：实现、审查和 CI 证据；
- 项目内数据库：学习、证据和产品审计真值，绝不由 GitHub Issue 替代。

GitHub Issue 不能自行扩大授权。未进入 `TODO.md` 或未取得所需确认的 Issue 可以研究和分诊，
但不能借 `accepted` 标签绕过项目门禁。

## 9. 建议的第八里程碑交付物

第八里程碑建议新增专门阶段完成：

- 三个 Issue Forms 和禁用空白 Issue 的配置；
- `SECURITY.md` 与私密安全报告入口；
- 置顶的中英双语“如何提交高质量问题”指南；
- 受管标签字典、Milestone 和 TODO 映射规则；
- 应用内可预览、可删字段、只复制不提交的脱敏诊断；
- Bug、功能、内容/证据三条 E2E；
- 重复、needs-info、reopen、PR 关闭和发布验证流程；
- 不含敏感正文的安全测试和秘密扫描。

创建远程标签、Milestone、置顶 Issue、开启 Private Vulnerability Reporting 或真实提交测试
Issue 都是 GitHub 外部写操作，必须在对应阶段取得明确授权后执行。

## 10. 维护记录

- 2026-08-28：核验 `skills-manager@8f34bf1` 模板、配置、MIT 许可证、置顶 #155 和代表性
  Issues；形成云奕学适配方案，未创建或修改任何远程 Issue、标签、Milestone 或仓库设置。
