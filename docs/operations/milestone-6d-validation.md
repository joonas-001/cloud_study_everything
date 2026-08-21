# 第六里程碑 6D 受控上线验证记录

> 验证日期：2026-08-21（Asia/Shanghai）。本记录证明现有单用户新加坡私有实例已经按
> 已授权范围完成真实库迁移和远程 Runner 受控激活；仍不授权真实 AI、真实来源、邮件、
> 扩容、公开注册或公开发布，也不能充当用户个人 `verified`／`retained` 学习证据。

## 精确版本与发布门禁

- 精确提交：`5b4af163cffd0daccb99b6532cba648f7bae74a3`；
- Git 归档 SHA-256：
  `b7ad179b67267eceac5742dd386e96be53962d854ccd3e4426e2a8c6ebcbab1c`；
- Draft PR #19 最新 GitHub Actions 运行 `32445151440` 共 22 项成功；
- 本地完整 `release-readiness`：115 项后端通过、1 项按预期跳过，42 项前端、生产构建、
  桌面／移动 8 项 E2E、契约无漂移和密钥扫描成功；
- 项目所有者确认采用独立 6D 基线，因此云端界面从未合并的 7F 状态回到当前主线基线。

## 真实数据库与备份

- 本地写入者已停止；最终加密制品为
  `cloud-study-20260821T040127Z.csbak`，制品 SHA-256 为
  `3c3f58e2fdcd8e36a7abbd010be445ff1ead054153e02803d584d8bedf9a46d8`；
- 加密制品使用策略 `single-user-singapore@1.1.0`，已用离线私钥真实恢复并验证；一次性
  本机明文恢复／传输副本已删除，私钥未上传云端；
- 迁移快照 SHA-256 为
  `624d062c73c6003bff9e6d67b43d5d71d51109a8e0cbc52af5adf75c643d34e8`；
- 本地与云端无正文语义摘要均为
  `99476171a436a8f19c27fb18777837ead412240ebc1517db495223b2cb4e2d90`；
- 两端均为 Alembic `0010`、47 张表、54 行，完整性、外键、事件顺序和内容锁摘要一致；
- 旧合成库保留在
  `/var/lib/cloud-study/cloud-study.synthetic-pre-6d-20260821T042304Z.db`，切换前加密备份
  SHA-256 为 `c5edc9b2ddcdebd115511705ee9ee410069c69d2db707840c355bd6e982262cd`；
- 首份云端策略 `1.1.0` 加密备份为 `cloud-study-20260821T042854Z.csbak`，制品 SHA-256
  为 `d32cf98194f6916a322d47cf0bd84241c69435703a6a9f323ab82abecd3b28b9`；
- 7 日保留策略按设计淘汰 2026-08-14 的最旧日备份；当前保留 2026-08-15 至 08-21 七份
  日备份和额外的切换前加密回滚备份。

## App、身份与网络

- live app 和 Runner release 均锁定精确提交；旧 7F app 保留在
  `/opt/cloud-study/releases/app-pre-6acdaca-20260821T042304Z`；
- API、Web、备份计时器和 Runner 均为 `active + enabled`，观察起点为
  2026-08-21 12:26（Asia/Shanghai），自动重启计数均为 0；
- API/Web 只监听 `127.0.0.1:8000`／`127.0.0.1:3000`；私有 HTTPS 只由 Tailscale
  在 Tailnet 地址的 443 端口提供；
- 无身份 Web 为 401，错误身份 Web/API 为 403，精确所有者 Web/API 为 200；所有者设备
  通过 Tailnet HTTPS 访问首页、学习、证据和设置四条路由均为 200；
- 两次计划内停止 Web 时 Node 包装进程以 SIGTERM 143 退出，systemd 记录为瞬时
  `exit-code`；每次均由受控流程重新启动，之后无自动重启或警告级运行异常；
- Headless Chromium 和 Edge 通过同一设备访问 Tailscale Serve 时均得到
  `ERR_CONNECTION_CLOSED`，因此不能声称远端自动浏览器烟雾通过。仓库桌面／移动 E2E、
  Tailnet HTTPS 路由和身份链路已经通过，真实交互浏览器体验仍需项目所有者在观察期确认。

## Runner 与资源

- 策略为 `single-user-singapore@1.1.0`，只有 `remote_enabled` 改为 `true`；外部 AI、
  真实来源和邮件继续为 `false`；
- Broker Socket 为 `660:cloud-study-runner:cloud-study`；FastAPI 身份不在 Docker 组，
  独立 Broker 身份在 Docker 组；
- Docker Engine `29.1.3`，GCC 15.2.0 与 Python 3.14.3 镜像摘要精确匹配；
- 激活脚本和激活后独立复测均通过 C++、Python、断网、只读根、无宿主仓库、无 Docker
  Socket、进程、超时、合并输出和内存十项矩阵；传输为 `unix_broker`；
- 每个容器均使用非 root `65534:65534`、`network=none`、只读根、移除全部 capabilities、
  禁止提权、默认 seccomp、`pull=never`，矩阵后项目容器残留为 0；
- 验收时根盘剩余约 25 GB，可用内存约 1.2 GiB，Swap 可用约 1.9 GiB；没有扩容或新增
  付费资源。

## 观察期与未完成验收

- 本地真实库、旧云端 app、旧合成库、切换前环境文件和加密备份均保留为回滚点；
- 观察期时长和结束时间仍待项目所有者确认；期间触发健康、数据、身份、Runner、安全、
  资源或费用停止条件时必须关闭 Runner 并回滚；
- 腾讯云月度账单实际消耗仍需项目所有者在账单侧复核；不能只根据实例规格推断；
- 真实桌面／移动浏览器交互需要项目所有者人工确认。未完成这些事项前，6D 状态为
  “已激活、观察中”，不得表述为最终观察验收全部完成。
