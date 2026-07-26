# 技能包系统架构提案

> 状态：已获项目所有者批准  
> 适用范围：技能包注册、治理、依赖、兼容性、生命周期和可执行评分器  
> 当前阶段：本地单用户验证

## 1. 目标

技能包系统必须同时满足以下目标：

- 技能内容和学习引擎解耦；
- 注册表与文件系统严格一致；
- 学习计划可以稳定复现；
- 技能包之间可以声明依赖，但运行时不允许隐式升级；
- 学习引擎升级时能够判断并验证向后兼容性；
- 新技能包和状态变更必须经过明确的自动化门禁与人工授权；
- 技能包代码、评分器和校验脚本不得进入 FastAPI 主进程执行；
- 当前单人项目能够简单运行，未来团队扩大后无需推翻治理模型。

## 2. 仓库结构

建议结构如下：

```text
apps/
├── web/
└── api/
contracts/
├── api/
├── skill-pack/
└── runner/
skill-packs/
├── registry.yaml
└── algorithm/
    └── versions/
        └── 0.1.0/
            ├── manifest.yaml
            ├── curriculum/
            ├── assessments/
            ├── sources/
            └── tests/
runtimes/
├── cpp-basic/
├── python-basic/
└── ml/
tools/
└── skill-pack-cli/
docs/
└── architecture/
```

`skill-packs/<skill-id>/versions/<version>/manifest.yaml` 是某个技能包版本的唯一清单文件。技能目录根部不再放置另一个可能与版本清单冲突的 `manifest.yaml`。

## 3. 注册表与文件系统一致性

### 3.1 一一对应

`registry.yaml` 必须列出仓库内的每一个技能包版本，包括 `draft`、`validating`、`active`、`deprecated` 和 `archived` 版本。

每个注册项至少包含：

```yaml
id: algorithm
version: 0.1.0
path: skill-packs/algorithm/versions/0.1.0
state: draft
manifest_sha256: "..."
```

注册表和文件系统必须满足集合相等：

```text
registry 中的 (id, version)
==
skill-packs/*/versions/*/manifest.yaml 中的 (id, version)
```

### 3.2 启动与加载校验

`skill-pack-cli validate-registry` 必须依次执行：

1. 校验 `registry.yaml` 自身的 Schema；
2. 检查 `(id, version)` 是否唯一；
3. 检查注册路径是否位于 `skill-packs/` 内，禁止路径穿越；
4. 检查对应 `manifest.yaml` 是否存在；
5. 检查目录名、注册项和 manifest 中的 ID、版本是否完全一致；
6. 检查 manifest 与内容文件的校验和；
7. 反向扫描文件系统，拒绝未注册的技能包版本；
8. 解析完整依赖图；
9. 校验生命周期状态与注册信息一致；
10. 生成确定性的注册表快照。

对于仓库内置注册表：

- CI 校验失败时禁止合并；
- 开发、测试和生产启动校验失败时，API 必须拒绝启动；
- 运行过程中检测到文件被修改时，不得热加载不一致内容。

对于未来可能引入的远程第三方注册表，只拒绝加载无效的远程技能包并将其隔离，不让一个第三方包导致整个核心服务退出。

隔离流程必须：

1. 将原始包保存到不可执行、只读的隔离区；
2. 计算并保存内容摘要、来源、签名状态和失败原因；
3. 禁止隔离包进入活动注册表、Runner 或 FastAPI 导入路径；
4. 向用户展示隔离报告并提供原始包的受控查看或导出入口；
5. 为用户当前选择的 AI 创建安全净化后的审查材料；
6. 由 AI 提出拒绝、修复、请求更多证据或调整教学安排的建议；
7. 由用户决定是否进入修复流程；
8. 修复后的包必须作为新候选重新走完整验证和审批流程。

不得把隔离包中的任意提示词、可执行代码或未净化全文直接放入 AI 的高权限系统上下文。发送给外部 AI 的材料仍受最小化外发和对话模型锁定规则约束。

## 4. 提交、审批和激活权限

### 4.1 当前单用户阶段

- 项目所有者可以提交、审批和激活技能包；
- AI 可以生成草稿、测试和评审意见，但不能批准自己的修改，也不能自行把技能包标记为 `active`；
- 状态变更必须通过受版本控制的变更完成，不允许直接修改运行中数据库绕过审查。

### 4.2 未来团队角色

建议采用以下角色：

| 角色 | 权限 |
| --- | --- |
| Contributor | 通过分支和 PR 提交或修改 `draft` |
| Skill Owner | 审核具体技能内容、来源和评估标准 |
| Runtime Owner | 审核 Runner、评分器和运行环境 |
| Release Manager | 在所有门禁通过后批准状态进入 `active` |
| Security Owner | 审核可执行内容、依赖和紧急停用 |

同一个变更的作者不得作为唯一激活审批者。

### 4.3 Git 仓库强制措施

未来连接 GitHub 后，应：

- 在 `.github/CODEOWNERS` 中保护 `skill-packs/`、`contracts/`、`runtimes/`、部署配置和 `CODEOWNERS` 文件本身；
- 保护默认分支；
- 强制所有修改通过 PR；
- 要求 Code Owner 审批；
- 要求最新提交通过所有必需状态检查；
- 禁止管理员绕过关键规则；
- 对发布标签或发布清单采用额外保护。

实际 GitHub 用户名和团队名尚未提供，因此当前不能生成真实 `CODEOWNERS` 条目。

## 5. 技能包依赖与锁定

### 5.1 依赖类型

必须区分：

- `skill_dependencies`：其他技能包提供的能力、课程或评估；
- `runtime_profiles`：执行练习需要的 C++、Python、PyTorch 等运行环境；
- `engine_contract`：技能包所需的学习引擎协议版本。

三类依赖不能混写。

示例：

```yaml
skill_dependencies:
  - id: data-structures
    version: ">=1.2.0 <2.0.0"

runtime_profiles:
  - id: cpp-basic
    version: "1.1.0"

engine_contract:
  version: ">=1.0.0 <2.0.0"
```

### 5.2 解析规则

为新学习计划选择技能包时，依赖解析器必须：

1. 从根技能包开始解析完整有向依赖图；
2. 检测循环依赖；
3. 检测缺失依赖；
4. 检测版本范围冲突；
5. 只从允许用于新计划的版本中选择候选；
6. 将每个传递依赖解析为一个精确版本；
7. 记录每个技能包和运行环境的内容校验和；
8. 生成不可变的计划锁文件。

如果出现循环、缺失或无法同时满足的版本约束，必须拒绝创建学习计划，不能自行忽略依赖或选择近似版本。

### 5.3 计划锁文件

每个学习计划保存完整依赖树，而不只保存根技能包：

```yaml
plan_id: "..."
root:
  id: algorithm
  version: 1.0.0
packages:
  algorithm:
    version: 1.0.0
    sha256: "..."
  data-structures:
    version: 1.4.2
    sha256: "..."
runtimes:
  cpp-basic:
    version: 1.1.0
    image_digest: "sha256:..."
engine_contract: 1.3.0
runner_protocol: 1.0.0
```

已创建计划不得使用浮动版本。注册表升级只影响之后创建的新计划。

已经发布的技能包版本内容不得原地修改。修复必须发布新版本。

## 6. 学习引擎与旧技能包兼容

技能包必须分别声明：

- `schema_version`：技能包文件格式；
- `engine_contract`：学习引擎读取和执行技能包的协议；
- `runner_protocol`：调用评分器或校验器的协议；
- `runtime_profiles`：运行镜像或工具链。

### 6.1 兼容矩阵

每次学习引擎发布前，CI 必须运行兼容矩阵：

```text
候选引擎版本
× 所有 active 技能包版本
× 仍有进行中计划引用的 deprecated 技能包版本
```

候选引擎不能通过兼容矩阵时，不得发布，除非同时提供并验证迁移方案。

### 6.2 兼容策略

- `active`：必须得到当前引擎完整支持；
- `deprecated`：不得用于新计划，但必须继续支持所有已锁定的进行中计划，直到这些计划完成；
- `archived`：内容和历史记录保持可读，不保证继续执行；
- 旧 Schema 优先通过显式兼容适配器读取；
- 破坏性迁移必须创建新计划版本或经过用户确认迁移，不能静默改写；
- 运行镜像使用精确摘要锁定，而不是可漂移标签。

### 6.3 安全例外

不能为了可复现性永久运行已知存在严重漏洞的旧运行环境。

如果锁定运行环境出现不可接受的安全风险：

1. 立即禁止该环境执行，但保留课程与历史记录可读；
2. 发布经过兼容验证的修补运行环境；
3. 生成迁移报告；
4. 获得用户确认后更新计划锁；
5. 保留原锁文件和变更审计记录。

`deprecated` 版本的常规兼容支持持续到所有引用它的进行中计划结束。严重安全或法律问题仍按上一节的安全例外处理。

当新版技能包包含值得现有学习者掌握的新内容时：

1. AI 比较旧版锁定计划和新版内容差异；
2. 生成单独版本化的“补充学习单元”，说明来源、必要性、工作量和插入位置；
3. 补充单元锁定自己引用的新版技能包与依赖版本；
4. 原始计划锁文件保持不变；
5. 系统通知用户，并记录 AI 的规划依据；
6. 用户可以查看补充内容和影响；
7. 只有得到用户确认后，补充单元才能加入学习计划；
8. 用户之后可以撤销补充单元并要求 AI 重新规划；
9. 确认、撤销和重新规划都必须保留审计记录。

## 7. 生命周期状态与转换门禁

### 7.1 `draft → validating`

必须满足：

- manifest 和内容 Schema 通过；
- 注册表一致性通过；
- 依赖图可以解析；
- 必填来源和许可证信息齐全；
- 基础内容测试存在；
- 已通过 PR 发起验证。

### 7.2 `validating → active`

必须满足：

- 所有必需 CI 检查通过；
- 权威来源与引用检查通过；
- 课程图无断裂、无循环先修关系；
- 诊断、练习和评分规则测试通过；
- 所需 Runner 兼容性与安全测试通过；
- 学习引擎兼容矩阵通过；
- Skill Owner 审批；
- 涉及可执行内容时 Runtime Owner 或 Security Owner 审批；
- Release Manager 明确批准；
- 生成不可变校验和与发布记录。

自动化可以证明检查通过，但不能代替最终激活授权。

### 7.3 `active → deprecated`

建议条件：

- 存在替代版本、维护终止决定或明确的质量/安全原因；
- 已声明停止用于新计划的时间；
- 已生成对进行中计划的影响报告；
- 已提供继续完成、迁移或停止的处理方式；
- 状态变更经过所有者审批。

`deprecated` 的目的之一就是允许已有计划继续完成，因此不应要求进行中引用数量为零。

### 7.4 `deprecated → archived`

必须满足以下条件之一：

- 不再有进行中的计划引用该版本；
- 所有进行中计划已完成显式迁移；
- 因安全或法律原因必须停止，且已经生成影响报告并由所有者批准。

归档后不得删除仍被历史记录引用的 manifest、内容摘要、来源、锁文件和校验和。

### 7.5 紧急停用

建议增加一个与生命周期正交的 `availability` 字段：

```yaml
availability: available | suspended
```

这样可以在安全、法律或数据完整性事件中立即停止加载或执行某个 `active` 版本，而不伪造其生命周期历史。

项目所有者已确认增加 `suspended` 能力。

## 8. 可执行评分器和自定义校验器

这是硬性安全边界：

- 技能包中的可执行评分器、自定义校验脚本和用户代码不得被 FastAPI 进程导入；
- 不得使用 Python entry points、动态 `import` 或 `exec` 把技能包代码加载进 API；
- FastAPI 只负责编排、权限检查、任务创建、状态持久化和结果校验；
- 所有可执行内容必须通过版本化 Runner 协议调用隔离进程或容器；
- Runner 请求和响应必须符合 `contracts/runner/` 中的 Schema；
- Runner 默认禁用网络；
- 使用临时文件系统、非特权用户、只读基础镜像；
- 限制 CPU、内存、进程数、输出大小和执行时间；
- 不向 Runner 注入 AI API 密钥或数据库凭据；
- Runner 返回的数据必须在 API 边界再次校验；
- 评分器制品必须锁定版本和内容摘要；
- 运行记录必须包含评分器版本、运行环境摘要、资源使用、退出原因和审计 ID。

Runner 失败不能导致 API 静默使用另一个评分器。需要重试或迁移时必须保留原始失败记录。

## 9. 必需的自动化检查

建议设置以下稳定检查名称：

- `registry-consistency`
- `manifest-schema`
- `dependency-resolution`
- `content-integrity`
- `source-policy`
- `curriculum-graph`
- `assessment-contract`
- `engine-compatibility`
- `runner-contract`
- `runner-security`
- `api-tests`
- `web-tests`
- `integration-tests`
- `release-readiness`

`release-readiness` 是汇总门禁，只有所有适用检查完成且成功后才通过。必需检查不得因为路径过滤而完全不创建，否则 GitHub 可能长期等待不存在的检查结果。

## 10. 运维与责任

当前单用户阶段：

- 项目所有者是唯一激活授权人；
- AI 可以准备变更和验证结果，但不能自我审批；
- 本地应用不需要持续在线运维。

未来团队阶段：

- 内容质量由 Skill Owner 负责；
- Runner 与执行安全由 Runtime/Security Owner 负责；
- 发布由 Release Manager 负责；
- 基础设施由明确指定的平台或运维负责人负责；
- CODEOWNERS、分支规则、必需检查和审计记录负责机械执行规则。

## 11. 待项目所有者确认

1. 连接 GitHub 后，由哪些用户或团队担任 Skill Owner、Runtime Owner、Security Owner 和 Release Manager。

已于 2026-07-27 确认首版本地工程基线：

- CI 使用 GitHub Actions；
- Python 依赖管理使用 uv；
- 运行时使用 Node.js 24 LTS 和 Python 3.14.3。
- SQLite 数据访问使用 SQLAlchemy 2，迁移使用 Alembic；必要依赖不支持 Python 3.14 时停止并报告，不得静默降级。

## 12. 参考资料

- GitHub CODEOWNERS：
  <https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners>
- GitHub 受保护分支：
  <https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches>
- GitHub 必需状态检查：
  <https://docs.github.com/en/pull-requests/reference/status-checks>
- Semantic Versioning 2.0.0：
  <https://semver.org/>

## 13. CI 启动顺序

不建议在项目骨架和本地检查命令尚不存在时先写一套空 CI，也不建议先开发业务功能再补 CI。

项目所有者已批准把“项目骨架 + 本地质量命令 + CI 基线”作为第一个实现里程碑：

1. 创建最小目录结构；
2. 创建可在本地执行的确定性检查命令；
3. 为每个检查添加一个最小的真实测试或校验对象；
4. 创建 CI 工作流调用完全相同的本地命令；
5. 创建稳定的 `release-readiness` 汇总检查；
6. 确认干净环境能够完成依赖安装和全部基线检查；
7. CI 通过后才开始自适应访谈等业务功能。

第一阶段 CI 至少包含：

- Markdown 与仓库结构检查；
- 注册表一致性；
- manifest 和 contracts Schema 校验；
- 依赖图解析；
- FastAPI lint、类型检查和单元测试；
- Next.js lint、类型检查和构建；
- 前后端契约生成无漂移检查；
- 密钥与敏感信息扫描；
- `release-readiness` 汇总结果。

仓库已经配置 GitHub remote，因此第一阶段创建工作流并在本地验证其调用的全部命令。由于实际角色和 GitHub 用户名仍未确认，本阶段不生成虚假的 `CODEOWNERS` 条目，也不擅自修改远程规则集、必需检查或禁止绕过策略。
