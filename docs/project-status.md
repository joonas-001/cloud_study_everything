# 云奕学项目状态

> 状态更新时间：2026-09-01（Asia/Shanghai）。本文件记录当前证据、边界和下一步，
> 不替代 `AGENTS.md` 中的项目所有者指令。

## 当前结论

- 6A 已交付，6B 合成数据私有预发布已在现有新加坡单实例完成当前范围验收；
- 6C 真实数据库加密副本迁移与回滚演练已通过，唯一真实库未替换、未迁入云端；
- 远程 Runner 精确候选 `f1d78f8` 已通过云端十项真实安全与资源矩阵；
- 6D 已按授权范围完成受控激活与最终验收；生产策略为 `1.1.0`，远程 Runner 已通过独立
  Broker 接入 live API；PR #19 已合并为 `main@d4f079c`；
- 6C 已通过 PR #16 合并到 `main@65529de`，PR 与合并后主线 CI 均为 22 项成功；
- 浏览器同源 API 修复 `c781fe1` 已部署并由项目所有者通过真实手机确认；账单已复核，
  剩余观察期已取消。Headless Chromium/Edge 的 `ERR_CONNECTION_CLOSED` 限制继续记录；
- 真实库 47 张表／54 行迁移一致，最终本地备份已真实恢复，旧 app、旧合成库、环境文件和
  本地库均保留回滚点；Runner 十项矩阵通过且项目容器残留为 0；
- 7A–7F 已进入主线；PR #18 已合并为 `main@90e16e2`。7F 代码、PR CI 自动验收和项目
  所有者完成确认均已完成；合并后 push CI `32806434805` 共 22 项成功；
- 第八里程碑 M8-D01–D15 和 8A–8F 当前授权范围已完成，8G 技术验收已通过、入口决定待确认；8B 已实现通用契约及关闭入口的
  `algorithm@0.3.0` 草稿，固定 12 域、46 能力、34 单元、4,740 分钟、166 活动、64 题和
  22 个 Runner 任务；8C 在独立分支实现完全确定性选题、三态路径信号、停止、解释审计、
  修正重算、恢复、重放、固定序列回退和未来／损坏状态拒绝；8D 实现默认 120 分钟每日任务、
  追加式延期、暂停恢复、范围化双语言 Runner 证据、真人评审、固定复习、十二域阶段检查和
  四分支准确门禁，并新增 Alembic `0011`；8E 实现按精确能力 ID、六维、时效与验证方式生成的
  本地能力档案、JSON／CSV／打印视图、非虚荣学习分析和完全隔离的复习候选影子评估；8F
  实现三个 Issue Forms、双语指南、安全入口、受管标签和生命周期契约，以及只读、可删字段、
  只复制不提交的允许列表诊断。8G 已完成第二评审、迁移回滚、Issues 隐私回归和真实 Runner
  全量复验；最终 `release-readiness` 通过 147 项后端测试（1 项按预期跳过）、44 项前端测试、
  生产构建与 13 个静态页面、26 项 E2E（6 项按既有范围跳过）、全部治理检查、契约无漂移和
  密钥扫描。`0.3.0` 入口仍关闭，默认入口仍为 `0.2.2`；远程来源实质复核和项目所有者入口
  决定尚未完成；除后续单独授权的 Issue #26 创建与置顶外，其他 GitHub 远程写操作、真实库
  写入、Tailnet 候选与云端变更均未授权；
- 真实 AI、真实来源、邮件、公开发布、扩容和新增付费资源仍未授权。
- 项目所有者于 2026-09-01 单独授权 GitHub Issues 置顶提交入口；Issue #26 已创建并置顶，
  Bug、Feature Request、Other 三类即时预填链接分别使用远程已有 `bug`、`enhancement`、
  `question` 标签。确定性链接解析和完整 `release-readiness` 已通过；该操作不授权同步受管
  标签、Milestone、仓库／安全设置或测试 Issue。

## 6C 证据

| 范围 | 状态 | 证据或限制 |
| --- | --- | --- |
| 真实数据演练 | 通过 | 47 张表、54 行；Schema、逐表语义摘要、外键、事件顺序、内容锁和反向恢复一致 |
| 本地服务恢复 | 通过 | 写入冻结后原 API/Web 已恢复健康 |
| 临时明文副本 | 未保留 | 只保留本机安全目录中的加密制品和无正文报告 |
| Runner 代码门禁 | 通过 | 6C 最终 `release-readiness`：114 项后端通过、1 项按预期跳过，42 项前端、生产构建、8 项 E2E、契约与密钥扫描成功 |
| 本机 Runner 复测 | 未执行 | Docker Desktop 未启动，探针在容器创建前停止；历史 4B 证据不受影响 |
| 云端 Runner 实测 | 通过 | Docker 29.1.3；锁定的 GCC 15.2.0 与 Python 3.14.3 镜像；Unix Socket 十项矩阵全部符合预期 |
| 云端权限与清理 | 通过 | FastAPI 身份不在 Docker 组且不能读取 Docker Socket；验证后项目容器为零，Broker 为 `inactive + static` |
| 云端资源与 live 回归 | 通过 | 根盘使用 31%，镜像 3.785 GB，可用内存 1.3 GiB、Swap 1.8 GiB；API、Web、备份计时器与 Tailnet HTTPS 正常 |

## 7F 当前证据

- Windows 本地覆盖 Chromium 桌面／移动／平板与 WebKit，11 个产品页面的 200% 文本、
  横向溢出、可访问名称、键盘入口、空／加载／错误、forced-colors 和重复导航已通过；
- 重放后完整本地 `release-readiness` 通过：114 项后端通过、1 项按预期跳过，42 项前端、
  生产构建、22 项 E2E、契约无漂移和密钥扫描成功；
- 代表性截图已复核；针对发现只调整平板学习操作区、干净数据库下的 WebKit 长表单控件／
  准备度双列网格和缩放侧栏布局；
- 7F 保持零新增依赖，不修改第六里程碑实现、服务器或部署状态；
- Windows Firefox 因 `RenderCompositorSWGL failed mapping default framebuffer` 未能启动，
  没有关闭沙箱规避；PR #18 最新 CI 运行 `32349073889` 共 22 项成功，Linux E2E 为 25 项通过、
  8 项按范围跳过，精确包含 Firefox 的 3 项通过与 2 项跳过；
- 项目所有者已确认 7F 完成；Windows 实际高对比度和连续两小时阅读疲劳调整为非阻断后续
  人工任务。两项未执行前不得写成已通过，也不得声称 WCAG 合规认证。

## 8G 当前证据

- 第二评审覆盖 9/34 学习单元、20/64 诊断题和 4/10 本地来源映射元数据，并全量复核
  22 个 Runner 任务、6 个量表、60 条评估准则和 4 个分支门禁；修正两项内容问题；
- `0011 → 0010 → 0011` 往返保留 0.3.0 诊断、规划和学习历史，迁移／历史／Issues 隐私
  定向测试 26 项通过；
- Docker Engine 29.6.2 下十项安全／资源探针通过，22 个任务／66 个测试全部通过，精确
  GCC 15.2.0 与 Python 3.14.3 镜像匹配，验证结束时项目标签容器为零；
- 最终完整门禁通过 147 项后端、44 项前端、13 个静态页面、26 项 E2E、契约无漂移和密钥
  扫描；WebKit 使用真实 API／同源代理就绪和首页数据完成条件，不采用错误白名单；
- 远程来源实质复核仍未授权，4/10 来源只表示本地元数据映射检查；当前推荐保持
  `algorithm@0.3.0` 关闭并等待项目所有者最终入口决定。

## 下一步

1. 保持 `algorithm@0.3.0` 关闭入口；8G 技术验收已完成，但远程来源实质复核仍待单独授权，
   项目所有者需决定继续关闭或承担该缺口进入后续候选；当前建议继续关闭；
2. 保持真实 AI、个人知识工作台、文件导入、完整富文本、通用插件平台、四分支课程及产品
   扩展为明确后续待办，不在 8A–8G 中实施；
3. 后续由项目所有者按需完成 Windows 实际高对比度与连续两小时阅读疲劳记录，并保持 6D
   回滚点、日备份、Runner 安全矩阵和费用边界的常规运维复核。

完整 6D 证据见 `docs/operations/milestone-6d-validation.md`；7F 证据见
`docs/design/milestone-7f-experience-acceptance.md`；8A 规格、8B 与 8C 证据见
`docs/architecture/milestone-8a-learning-core-spec.md` 和
`docs/architecture/milestone-8b-validation.md`、`docs/architecture/milestone-8c-validation.md`
和 `docs/architecture/milestone-8d-validation.md`、`docs/architecture/milestone-8e-validation.md`、
`docs/architecture/milestone-8f-validation.md`、`docs/architecture/milestone-8g-validation.md`。
