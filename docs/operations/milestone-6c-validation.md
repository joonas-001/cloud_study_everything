# 第六里程碑 6C 验证记录

> 验证日期：2026-08-15（Asia/Shanghai）。本记录只证明已授权的真实数据库演练和云端
> Runner 基础设施范围，不授权 6D，不代表远程 Runner 已在生产启用，也不能充当用户个人
> `verified` 或 `retained` 能力证据。

## 授权与边界

项目所有者授权真实数据库加密副本迁移与回滚演练，以及远程 Runner 实现和云端验证。
验证通过前保持关闭；验证结束后也先停止 Broker。范围不包含扩容、公开上线、真实数据迁入
云端、自动增加费用或 6D。

Runner 使用独立 Unix Socket Broker。`cloud-study` 运行 FastAPI，不属于 Docker 组；
`cloud-study-runner` 是唯一加入 Docker 组的 Broker 身份。候选位于独立 release 目录，
没有替换或重启 live API/Web。

## 真实数据库迁移与回滚

- 加密制品：`cloud-study-20260815T6C0000Z.csbak`；
- 制品 SHA-256：`822fbebcdf44229e5bf0841962b68b3bb8bc892587b98cddb5bf87dc3d6b6748`；
- 无正文报告：`milestone-6c-migration-20260815.json`；
- Alembic 版本：`0010`；
- 数据范围：47 张表，共 54 行；
- 校验结果：Schema、逐表语义摘要、外键、事件顺序、内容锁和反向恢复一致；
- 唯一真实库未替换，未迁入云端；临时明文副本未保留，原 API/Web 已恢复健康；
- 离线私钥不在仓库、报告或云端候选中。

## 精确云端候选

- Git 提交：`f1d78f858626d82bed8ecced3c464c92cdbff9c7`；
- `git archive` SHA-256：
  `8c522187a7e8bf6eef244c4f147372b4c4e2a62c8553f39961f2f88ff6dce11c`；
- release：`/opt/cloud-study/runner/releases/f1d78f8`；
- 操作系统：Ubuntu 24.04；
- Python：受管路径中的 3.14.3；
- uv：0.11.32；
- Docker Engine：29.1.3；
- C++ 镜像：
  `gcc@sha256:c101370f78e4a30be178c11dd18aeee64c65d617908a98157db2392ca73ab04f`；
- Python 镜像：
  `python@sha256:843ef86c4efef6d065c1767855730cc974e4998e66d65d6739449f0bc0ae4d93`。

首次候选部署暴露了虚拟环境解释器误链接到 `/root` 的问题，systemd 以 `203/EXEC` 拒绝
启动，未进入 live API，也未据此接受验证结果。随后安装脚本增加服务身份可执行、Python
3.14.3、Broker 依赖导入、服务 active 和 Unix Socket 就绪硬校验；最终候选改用
`/opt/cloud-study/python` 中的受管解释器并重新执行全部验证。

## 十项真实矩阵

最终验证于 2026-08-15 20:07:12+08:00 前完成，传输为 `unix_broker`，顶层结果为
`ok=true`，并确认 API 身份不能访问 Docker Socket。

| 探针 | 观察结果 | 验收 |
| --- | --- | --- |
| C++ 执行 | `passed` | 通过 |
| Python 执行 | `passed` | 通过 |
| 断网 | `passed` | 通过 |
| 只读根文件系统 | `passed` | 通过 |
| 无宿主仓库挂载 | `passed` | 通过 |
| 无 Docker Socket | `passed` | 通过 |
| 进程限制 | `passed` | 通过 |
| 3 秒墙钟超时 | `timeout / wall_timeout` | 通过 |
| 64 KiB 合并输出限制 | `output_limit / output_limit_exceeded` | 通过 |
| 256 MB 内存限制 | `failed / runtime_failed` | 通过 |

每项都报告：网络为 `none`、根文件系统只读、用户为 `65534:65534`、全部 capabilities
移除、禁止提权、使用 Docker 默认 seccomp、不挂载 Docker Socket 或宿主路径，并采用
`pull=never`。超时、输出和内存探针的非 `passed` 状态是受管限制被正确触发的预期结果。

## 资源、回归与最终关闭状态

- 矩阵后项目标签容器为 0，Docker 容器、卷和构建缓存均为 0；
- 两个锁定镜像共 3.785 GB；Docker 数据根使用约 0.9 GB，可用约 25.92 GB；
- 40 GB 根盘使用 31%，可用约 26 GB；
- 1.9 GiB 内存中可用约 1.3 GiB，1.9 GiB Swap 中可用约 1.8 GiB；
- live API 健康检查返回 `200`，Tailnet HTTPS 返回 `200`；
- live API/Web 继续只监听 `127.0.0.1:8000` 和 `127.0.0.1:3000`，Tailscale 监听私有
  `443`；
- 每日加密备份计时器保持 `active + enabled`；
- 生产策略保持 `remote_enabled=false`；
- 最终 Broker 为 `inactive + static`，Unix Socket 已移除，项目标签容器残留为 0；
- Docker 和锁定镜像保留安装，但没有把 Broker 接入 live API。

## 后续决定与尚未解除的门禁

- 项目所有者已确认将远程 Runner 纳入 6D 启用范围；该决定不改变当前关闭状态；
- 6D 所有者单用户受控上线仍需最后一次单独授权；
- 6D 获得授权并实施时，Runner 仍须重新通过上线预检、安全矩阵、资源和回滚复核；
- 本次基础设施验证不生成学习证据，不解除 5C 中当前用户的个人证据缺口；
- 真实 AI、真实来源、邮件、扩容、公开注册和公开品牌发布仍未授权。

## 最终本地门禁

包含部署防护和本验证记录的最终工作树已通过完整 `pnpm release-readiness`：

- Ruff 格式与规则检查、mypy 严格检查通过；
- 后端 114 项测试通过，1 项按预期跳过；
- 前端 42 项测试通过；
- Next.js 生产构建成功并生成 13 个静态页面；
- 桌面／移动共 8 项 E2E 通过；
- 契约无漂移，密钥扫描无发现。
