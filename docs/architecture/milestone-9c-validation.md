# 第九里程碑 9C 验证记录

> 验证完成日期：2026-09-08（Asia/Shanghai）
>
> 分支：`codex/milestone-9c`
> 基线：9B 完成工作区；9B 与 9C 改动均未提交、推送或部署

## 1. 结论

9C 已在授权范围内完成合成认证候选。实现覆盖 OIDC Authorization Code + PKCE、精确
issuer/audience/nonce/state 校验、MFA 声明、一次性邀请、应用会话、撤销、停用、恢复和
7 天删除等待期。验证只使用合成身份、合成邀请、本地确定性适配器和 loopback 临时
PostgreSQL；没有创建 Clerk 账号、应用或订阅，没有接入真实身份、真实邀请、邮件或个人
数据，也没有修改 6D 生产环境、产生费用或开放注册。

`managed_oidc` 当前故意使用失败关闭适配器。真实 Clerk 接入、数据位置、完整导出/退出、
精确套餐和生产身份配置仍是后续门禁，因此本结论不能解释为“Clerk 已接通”或可以邀请真实
用户。9D–9H 仍未授权。

## 2. 已实现边界

- 登录使用随机 state、nonce 和 PKCE verifier；数据库只保存 state/nonce 哈希和加密后的
  verifier，回调先原子占用 state，再交换一次性 code；
- issuer、audience、nonce、签发/到期/认证时间和 MFA 声明不满足时统一拒绝，不自动合并
  不同外部身份；
- 邀请原文只返回一次，数据库只保存 SHA-256；邀请有期限、角色范围和撤销状态，接受使用
  条件更新原子占用，并发两个回调只能创建一个账号；
- 应用会话只保存 token SHA-256，登录时轮换旧会话；Cookie 固定为 `HttpOnly`、`Secure`、
  `SameSite=Strict`，同时执行空闲和绝对到期、当前设备/全设备退出及服务端撤销；
- 非安全方法要求精确 Origin；受限支持角色默认不能访问用户数据；管理邀请和账号停用/恢复
  要求 owner-operator 且 5 分钟内完成 MFA；
- 账号状态转换使用条件更新防止并发覆盖；删除请求立即撤销全部会话，删除等待账号只能通过
  新的已验证 MFA 会话撤销删除；实际数据删除属于 9D，9C 不提前实施；
- 登录、回调、邀请和恢复分别限流。限流计数使用数据库原子更新和唯一冲突重试，存储的键是
  服务端 HMAC，不保存原始网络标识；
- 安全审计只记录允许列表事件类型、结果、原因码、内部用户 ID 和随机关联 ID，不记录身份
  subject、原始会话 token、授权 code 或邀请 token；
- 迁移 `0013` 为邀请、登录事务、会话、安全事件和限流建立外键、唯一约束与状态/期限约束。

## 3. 安全反例与自动化验证

最终完整 `release-readiness` 通过：167 项后端测试通过、1 项按预期跳过，45 项前端测试、
生产构建与 13 个静态页面、26 项 E2E 通过（6 项按既有范围跳过），全部治理检查、契约无
漂移和密钥扫描成功。

9C 定向测试覆盖：

| 风险 | 反例或断言 | 结果 |
| --- | --- | --- |
| issuer/audience 混淆 | 错误 issuer、错误 audience | 拒绝 |
| nonce/state/code/PKCE 重放 | 错 nonce、重复 state/code、错误 verifier | 拒绝 |
| 过期或弱认证 | 已过期声明、缺少 MFA、超过再认证窗口 | 拒绝 |
| 邀请泄露/重复使用 | 只存哈希、过期/撤销/复用、两个并发回调 | 拒绝或只接受一次 |
| 会话固定与残留 | 登录轮换、空闲/绝对到期、当前/全设备退出 | 旧会话失效 |
| CSRF/Cookie | 错误或缺失 Origin；Cookie 属性检查 | 拒绝；属性齐全 |
| 账号生命周期 | 停用、恢复、自锁定、删除等待、撤销删除 | 状态机按范围执行 |
| 日志泄露 | subject、会话和邀请原文检索 | 未进入安全审计 |
| 生产误回退 | `managed_oidc` 未激活 | 503 失败关闭，不回退 owner |
| 迁移 | SQLite 与 PostgreSQL `0013→0012→0013` | 成功 |

完整后端套件首次运行还发现 7 个历史测试把 Schema head 写死为 `0012`；这些断言只更新为
`0013`，所有明确验证 9B 回退到 `0012` 的断言均保留。精确失败集修复后 7 项全部通过，随后
在最终完整门禁中复验。

第一次完整门禁的 E2E 阶段还暴露一个既有故障注入测试的清理竞态：测试在被拦截请求完成
渲染前调用 `unrouteAll`，页面因而停在读取状态。清理被移到“今日概览”出现之后；生产代码
未修改。修正后完整 E2E 和最终完整 `release-readiness` 均成功。

## 4. PostgreSQL 17.6 实机证据

验证复用本机缓存且摘要锁定的镜像，并创建只绑定 `127.0.0.1:55439` 的临时容器：

`postgres:17.6-bookworm@sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3`

| 项目 | 结果 |
| --- | --- |
| 空库迁移 | PostgreSQL `0001→0013` 成功 |
| SQLite 复制 | 57 张模型表、22 行合成数据；源库不变，目标摘要一致 |
| RLS | 40 条策略；A/B 仅见自己的诊断 |
| 跨主体写入 | 更新 0 行、删除 0 行 |
| 缺失主体 | 读取 0 行、写入被 RLS 拒绝 |
| 应用角色 | 非超级用户，无建库、建角色权限；不继承 owner 角色 |
| 复制后序列 | 新用户的 `user_settings.id=4`、`notification_preferences.id=4` |
| 9C 往返 | `0013→0012→0013` 成功 |

临时环境第一次使用 owner 角色继承授予应用权限时，RLS 探针按预期发现缺失主体仍可见数据并
失败。撤销 owner 角色继承、改用显式表/序列权限后全部通过。这一反例确认应用角色不得成为
表所有者或其可继承成员。验证完成后，唯一带
`com.cloud-study.scope=milestone-9c` 标签的临时容器和其中合成数据库已删除；镜像缓存保留，
没有云资源和费用。

## 5. Clerk 官方能力核验

以下只读核验用于判断候选协议能否与 Clerk 对齐，不表示已采购或接入：

- Clerk OAuth Applications 文档说明其支持 OAuth/OIDC、`openid` scope、公开客户端和
  PKCE S256；9C 候选采用 Authorization Code + PKCE 边界；
- Clerk Session options 文档提供 inactivity timeout、maximum lifetime 和会话撤销；官方
  当前说明新实例默认最大期限为 7 天，自定义生产 maximum lifetime 涉及付费套餐；
- Clerk 支持 MFA、自定义 MFA 登录流程和敏感操作 reverification；官方 reverification
  窗口可配置为 1–10 分钟，9C 本地候选使用 5 分钟；
- 尚未完成适用于首批真实用户地区的数据位置、完整用户导出/退出、删除传播和精确套餐价格
  核验。这些项目未满足前不得创建真实 Clerk 资源或宣称可退出性已验证。

官方来源（核验日期 2026-09-06）：

- [Clerk 如何实现 OAuth](https://clerk.com/docs/guides/configure/auth-strategies/oauth/how-clerk-implements-oauth.md)
- [Clerk Session options](https://clerk.com/docs/guides/secure/session-options.md)
- [Clerk Reverification](https://clerk.com/docs/guides/secure/reverification.md)
- [Clerk 自定义 MFA 流程](https://clerk.com/docs/guides/development/custom-flows/authentication/multi-factor-authentication.md)
- [Clerk Pricing](https://clerk.com/pricing)

## 6. 保留门禁

- 真实 Clerk 应用、SDK/JWKS/token exchange、密钥轮换、供应商故障和退出演练未实施；
- Clerk 数据位置、导出/删除/退出和精确套餐仍须使用届时有效的官方材料核验；任何订阅、
  年付或费用都需重新报价和单独授权；
- 真实身份、真实邀请、邮件、专用支持/隐私联系渠道和真实个人数据均未授权；
- 9D 必须另行完成告知/同意、访问、更正、导出、实际删除和备份删除传播；9E–9H 也必须逐
  阶段授权，9C 完成不开放公开注册；
- 6D 继续保持现有 owner-only 生产身份与运行边界，本分支没有部署或生产数据库写入。
