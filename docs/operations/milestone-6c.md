# 第六里程碑 6C 运行手册

## 1. 授权与边界

项目所有者于 2026-08-15 授权真实数据库迁移与回滚演练，并另行授权远程 Runner 的实现和
云端验证。验证通过前及验证结束后，私有预发布策略中的 `remote_enabled` 均保持 `false`；
是否在 6D 启用仍需再次决定。

6C 不替换唯一真实数据库、不切换生产流量、不部署尚未授权上线的前端、不创建新云资源、
不扩容、不启用真实 AI／来源／邮件，也不构成 6D 授权。

## 2. 真实数据库演练

1. 确认源数据库、备份公钥和本机离线私钥副本均存在；私钥不得上传服务器。
2. 使用仓库启动器停止本地 API/Web，并确认 `3000`、`8000` 均无监听。
3. 运行 `tools/run_migration_rehearsal.py`，同时传入 `--confirm-writes-stopped`。
4. 工具通过 SQLite 在线备份 API 创建一致快照并加密，只在临时目录中解密副本。
5. 对副本执行正式 Alembic `upgrade`，核验完整性、外键、逐表行数与语义摘要、事件顺序和
   内容锁；再从同一加密制品反向恢复并重复核验。
6. 临时明文副本随临时目录清理；安全目录只保留加密制品和不含正文的 JSON 报告。
7. 无论演练成功或失败都恢复原本地服务；不得以演练副本替换唯一真实库。

## 3. 远程 Runner 拓扑

```text
FastAPI (cloud-study，无 Docker 权限)
  -> /run/cloud-study-runner/runner.sock
  -> cloud-study-runner broker（独立 systemd 服务、docker 组）
  -> Docker Engine
  -> 无网络、非 root、只读根、无宿主挂载的短生命周期容器
```

- Runner 候选发布到 `/opt/cloud-study/runner/current`，不替换 live app；
- Broker 只接受 `availability`、`execute`、`cleanup_stale` 三种长度受限 JSON 帧；
- FastAPI 账号不得加入 `docker` 组，也不得读写 Docker Socket；
- Broker 无 TCP 地址族、无 Linux capability、无提权、只读系统和独立临时目录；
- systemd 单元故意没有安装段，不能设为开机启用；验证后必须停止；
- 运行镜像只按 `runtimes/registry.yaml` 中的精确摘要预置，练习时 `--pull never`；
- 现有单任务、编译／执行内存、CPU、进程、超时、输出和 tmpfs 上限保持不变。

## 4. 云端验证顺序

1. 记录 live app 提交、服务状态、端口、内存、Swap、磁盘和费用边界；
2. 创建现有合成数据库加密备份，不接触本机离线私钥；
3. 在独立目录部署精确候选提交并核验归档 SHA-256；
4. 从 Ubuntu 24.04 官方安全仓库安装并记录 Docker Engine 版本；
5. 预置 GCC 15.2.0 与 Python 3.14.3 的精确摘要镜像；
6. 启动不可开机启用的 Broker，验证 API 身份无 Docker Socket 权限；
7. 通过 Unix Socket 执行 C++、Python、断网、只读根、无仓库、无 Docker Socket、进程、
   超时、合并输出和内存十项矩阵；
8. 确认无项目标签容器残留，并停止 Broker；
9. 复核 API/Web/备份计时器、回环监听、Tailscale 私有访问、内存和磁盘；
10. 任一失败都保持 `remote_enabled=false`，记录失败并停止扩大范围。

## 5. 停止条件

- 镜像摘要、平台、Runner 协议或安全声明不一致；
- API 身份能够访问 Docker Socket；
- 容器出现网络、宿主目录、Docker Socket、root、可写根或额外 capability；
- 资源矩阵失败、残留资源无法按项目标签清理或单实例资源不足；
- 安装或运行引入新付费项、要求扩容或费用无法估算；
- live API/Web、备份、Tailscale 或唯一真实数据库受到影响。

触发停止条件时不得静默降级、自动扩容、切换 Runner 或进入 6D。

