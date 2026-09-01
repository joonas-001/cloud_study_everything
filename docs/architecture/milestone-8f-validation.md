# 第八里程碑 8F 验证记录

> 状态：8F 当前授权范围本地实现与验证完成
> 日期：2026-08-31（Asia/Shanghai）
> 分支：`codex/milestone-8f`
> 基线：`codex/milestone-8e@8cd0e36`

## 1. 授权与结论

项目所有者于 2026-08-31 单独授权 8F。当前范围已完成 GitHub Issues 仓库内发布准备和
应用内脱敏反馈闭环，但没有执行任何 GitHub 远程写操作。

本次结论只表示以下静态文件、确定性 API、界面和测试在本地通过。它不表示远程标签、
GitHub Milestone、置顶 Issue 或 Private Vulnerability Reporting 已创建或启用，也不表示
`algorithm@0.3.0` 可以开放，更不构成 8G、公开发布、云端变更或外部调用授权。

## 2. 已交付范围

### 2.1 仓库反馈入口

- `.github/ISSUE_TEMPLATE/bug.yml`：缺陷、期望行为、最小复现、影响、版本和经预览诊断；
- `.github/ISSUE_TEMPLATE/feature.yml`：问题、理想行为、时机、边界关系和验收标准；
- `.github/ISSUE_TEMPLATE/content.yml`：精确技能版本、受管 ID、问题类型、最小证据和期望处理；
- `.github/ISSUE_TEMPLATE/config.yml`：关闭空白 Issue，安全问题只引导到私密入口；
- `SECURITY.md`：中英双语私密报告、禁止内容和响应边界；
- `docs/contributing/reporting-issues.md`：可作为未来置顶 Issue 正文的中英双语指南。

上述文件落盘不等于已在 GitHub 远程同步标签、配置入口或创建置顶 Issue。

### 2.2 受管治理契约

`governance/issues-v1.json` 固定：

- 类型、状态、优先级、区域和特殊关系标签的名称、颜色与说明；
- `needs-triage → needs-info / duplicate / rejected / accepted → blocked / in-progress →
  needs-verification → closed → regression reopen` 生命周期；
- `needs-info` 14 天无补充只允许人工关闭，首版没有定时自动关闭；
- 关闭原因只允许 `completed`、`duplicate`、`not-planned`、`cannot-reproduce`；
- 被接受的实施 Issue 必须绑定精确 GitHub Milestone、`TODO.md` 编号和阶段；
- `accepted` 不产生实施授权；远程同步明确为 `authorized: false`。

新增 `pnpm check:issues`，并纳入根级 `release-readiness`，确定性校验三个表单、关闭空白
Issue、安全入口、标签唯一性与颜色、生命周期状态、14 天人工规则和隐私指南。

### 2.3 应用内只读诊断

设置页新增“系统状态 → 报告问题”区域，流程为：

1. 选择缺陷、功能或内容／证据报告；
2. 后端只接受受管页面、操作、精确技能版本、UUID 审计 ID、原因码和事件名称；
3. 用户完整预览所有允许列表字段，并可取消任一可选字段；
4. 用户显式复制后，界面才把禁用按钮替换为真实 GitHub 链接；
5. 用户自行打开、检查和提交，系统不自动创建、评论、上传或重试。

诊断包含应用版本、可选发布提交、非识别性系统摘要、Web/API 健康、数据库 revision、部署
模式、Runner 和外部调用布尔状态，以及用户明确选中的受管上下文。诊断不读取或返回用户
答案、代码、证据正文、原始日志、SQLite 数据、凭据、身份、私有端点、收入或 AI／市场正文。

后端在返回前再次扫描 Windows／UNC／常见 Unix 本地路径、邮箱、私有 IPv4、常见令牌或
密码赋值和非 GitHub URL。失败只返回稳定原因，不回显命中值。预览不持久化数据库，不接受
附件，GitHub URL 只预选表单和标题，不携带诊断正文。

## 3. 自动化证据

### 3.1 后端与治理

- 14 项 8F 定向测试通过，覆盖三类表单、允许列表字段、删除可选字段、无自动提交／附件、
  未受管路由／操作／版本／审计 ID／原因码／事件拒绝及禁止模式负面样本；
- 完整后端门禁：146 项通过，1 项按既有范围跳过；
- Ruff 格式与规则、Mypy、Issue 治理检查全部通过；
- 无数据库迁移、依赖或技能包受管字节变化。

### 3.2 Web 与 E2E

- ESLint、TypeScript 和 44 项前端单元测试通过；
- Next.js 生产构建通过，13 个静态页面生成成功；
- 完整 Playwright：26 项通过，6 项按既有范围跳过；
- 新增流程在 Chromium 桌面和移动端分别覆盖三类报告、本地预览、删除页面路由字段、剪贴板
  复制、复制前无链接以及复制后才出现 GitHub 链接；测试从未点击该链接。

### 3.3 完整门禁

根级 `pnpm release-readiness` 通过，包括全部内容、来源、评估、证据、Runner、市场、部署、
Issues、API、Web、E2E、契约漂移和密钥扫描检查。

## 4. 未授权与未完成

- 未创建或修改远程标签、GitHub Milestone、置顶 Issue、仓库设置或测试 Issue；
- 未开启 GitHub Private Vulnerability Reporting，若远程入口不可用必须停止而非改用公开 Issue；
- 未访问 GitHub API、远程来源或其他外部服务；
- 未运行 22 个任务的真实 Runner 全量复验，未完成来源实质复核或强制第二评审；
- 未写入真实库，未迁移数据，未修改云端，未调用外部 AI；
- `algorithm@0.3.0` 继续 `draft + intake: closed`，默认入口继续为 `algorithm@0.2.2`；
- 8G 完整验收与入口决定仍须项目所有者另行授权。

## 5. 8F 后续远程入口记录

2026-09-01，项目所有者另行授权创建一个 GitHub Issues 提交入口。远程
[Issue #26](https://github.com/joonas-001/cloud_study_everything/issues/26) 已按标题
“提交issues请看这里”创建并置顶，提供 Bug、Feature Request 和 Other 三栏即时预填链接，
分别使用 GitHub 已存在的 `bug`、`enhancement` 和 `question` 标签；置顶 Issue 自身使用
`documentation` 标签。正文来源为 `docs/contributing/issue-submission-hub.md`。

这次授权只覆盖该 Issue 的创建与置顶。受管 `type:*`／`status:*` 标签同步、GitHub
Milestone、仓库设置、Private Vulnerability Reporting 开关和测试 Issue 仍未授权。

仓库新增确定性校验，解析三条链接并核对标题、标签、预填正文、私密安全入口、详细研究
链接和唯一受管远程操作记录。完整 `pnpm release-readiness` 通过 147 项后端测试（1 项按
预期跳过）、44 项前端测试、13 个静态页面、26 项 E2E（6 项按既有范围跳过）、全部治理、
契约无漂移和密钥扫描。
