# Factor Forge Console Web Pilot 运行手册

日期：2026-08-01

## 1. 启动前检查

必须同时满足：

1. `source_repo` 是 clean、固定 commit 的专用控制 worktree。
2. worktree root 和 state root 位于 repo 外部，目录权限为 `0700`。
3. Data API catalog 存在且仅作为读取输入。
4. Docker agent image、专用 egress bridge 和 `DOCKER-USER` 私网阻断规则已就绪。
5. auth seed SQLite 只含一个指定 provider 的静态 `api_key`，不含 OAuth/session。
6. 邀请口令和 cookie secret 已通过环境或 Secrets Manager 注入。

## 2. 必需环境变量

```text
FACTORFORGE_CONSOLE_INVITE_PASSWORD=<shared invite password>
FACTORFORGE_CONSOLE_COOKIE_SECRET=<at least 32 random bytes>
FACTORFORGE_CONSOLE_COOKIE_SECURE=1
FACTORFORGE_CONSOLE_OPENCLAW_PROFILE=factorforge-console
FACTORFORGE_CONSOLE_MODEL=deepseek/deepseek-reasoner
FACTORFORGE_CONSOLE_THINKING=high
FACTORFORGE_CONSOLE_OPENCLAW_AUTH_PROVIDER=deepseek
FACTORFORGE_CONSOLE_OPENCLAW_AUTH_SEED_DB=<private seed sqlite path>
FACTORFORGE_CONSOLE_EXECUTION_MODE=container
FACTORFORGE_CONSOLE_CONTAINER_RUNTIME=docker
FACTORFORGE_CONSOLE_CONTAINER_NETWORK=factorforge-console-egress
FACTORFORGE_CONSOLE_CONTAINER_NETWORK_SUBNET=172.29.0.0/24
FACTORFORGE_CONSOLE_AGENT_IMAGE=factorforge-console-agent:2026.08.01
FACTORFORGE_CONSOLE_OPENCLAW_PROFILE_TEMPLATE=<committed profile template>
FACTORFORGE_CONSOLE_STATE_ROOT=<external private state root>
FACTORFORGE_CONSOLE_WORKTREE_ROOT=<external worktree root>
FACTORFORGE_DATA_CATALOGS=<comma separated approved catalog paths>
FACTORFORGE_DATA_API_PYTHONPATH=<clean committed Data API package root>
```

禁止把真实值写入 Git、网页、artifact 或 agent prompt。

生产服务每次启动只读下载 active catalog
`s3://yufan-data-lake/factorforge/data/catalog/data_catalog.json` 到 Console 私有 state；不得用 repo 内旧 catalog 或 Mac 本地绝对路径替代 production truth。

## 3. 构建与本地 UI 开发

Linux Pilot 主机先构建固定 agent image，并配置隔离网络：

```bash
docker build -f deploy/factorforge-console/Dockerfile.agent \
  -t factorforge-console-agent:2026.08.01 .

sudo -E deploy/factorforge-console/configure-container-network.sh

python3 scripts/run_factorforge_console.py \
  --source-repo /path/to/clean/factor-factory-control \
  --state-root /path/to/private/console-state \
  --worktree-root /path/to/private/factor-runs \
  --base-ref HEAD \
  --catalog /path/to/approved/data_catalog.json \
  --data-api-pythonpath /path/to/clean/factor-factory-data-api \
  --host 127.0.0.1 \
  --port 8765
```

Mac 上只做 UI 开发时，可显式设置 `FACTORFORGE_CONSOLE_EXECUTION_MODE=shared_gateway` 并使用 loopback `--auth-disabled`；该路径不属于隔离验收，不能暴露公网或形成正式研究 proof。正式朋友测试必须使用 Linux container mode。

## 4. 健康与审计

服务启动前会自动检查：

- 控制 worktree clean、base commit 可解析。
- agent image、专用 bridge 的 subnet/IPv6/internal 属性。
- OpenClaw profile 的 model endpoint、plugin 和 tool allowlist。
- auth seed provider/type/key 合法。
- 启动时回收 Console 标签下的遗留 agent 容器。

运行中检查：

- `/healthz` 同时报告 ledger、worker、engine、agent runtime 和 catalog；任一失败返回 503。
- 任务详情不出现服务器绝对路径、session key 或原始日志。
- `worktree_root/<factor>/<research>/repo` 与 workspace 一一对应。
- 每个任务结束后 Git changed/untracked/ignored 路径全部位于当前 workspace。

## 5. AWS Pilot

不得复用共享 `openclaw-new`，不得唤醒 `factor-research-worker`。

新建专用 EC2：

1. Region 使用 `ap-southeast-1`，与现有 Data API/S3 同区。
2. 加密 EBS；使用 SSM 管理，不开放 22。
3. Security Group 只允许公网 80/443，Console 只监听 `127.0.0.1`。
4. Instance profile 只允许读取 approved catalog/datamart prefix；明确拒绝对象写入/删除。
5. `/srv/factorforge/control` 是 clean、固定 commit 的部署 checkout。
6. `/var/lib/factorforge-console` 存任务账本、agent state 和 factor worktrees。
7. `/etc/factorforge-console` 只存 root-readable 配置或 Secrets Manager materialization。
8. Caddy 负责 HTTPS 和反向代理；systemd 管理 `factorforge-console-network.service` 和 `factorforge-console.service`。
9. EC2 metadata hop limit 设为 1；容器环境固定 `AWS_EC2_METADATA_DISABLED=true`，并验证 `169.254.169.254` 不可达。
10. 在开放邀请前执行容器内网络负例、Data API read smoke、一个真实 factor workspace E2E 和浏览器路径/secret 扫描。

域名、证书和实例就绪后才能向朋友开放；未配置 HTTPS 时禁止把共享口令站点暴露到公网。

## 6. 恢复与回滚

- Console 重启：运行中任务自动转为 `REVIEW_REQUIRED`，用户决定是否继续。
- Console 重启会停止或回收它自己标签下的遗留 agent 容器，不自动重放 agent turn。
- 新版本异常：停止 Console，切回上一固定 commit，保留 state/worktree，再启动核验。
- 任务 BLOCK：保留 workspace 和外部账本，不自动删除。
- 凭据泄漏：先轮换 provider key、邀请口令和 cookie secret，再失效旧 session，最后恢复服务。

任何清理都先按任务 manifest 和 Git worktree registration 盘点；禁止通配删除或清理其他活跃研究。
