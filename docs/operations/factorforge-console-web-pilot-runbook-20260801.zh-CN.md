# Factor Forge Console Web Pilot 运行手册

日期：2026-08-01

## 1. 启动前检查

必须同时满足：

1. `source_repo` 是 clean、固定 commit 的专用控制 worktree。
2. worktree root 和 state root 位于 repo 外部；共享 state 根目录属于 `factorforge-console` group，任务私有目录保持 `0700`。
3. 固定 Data API checkout 的 `factor_factory/data_api` 子包存在；active catalog 只能从固定 S3 key 刷新并带 receipt。
4. Docker agent image、专用 egress bridge 和 `DOCKER-USER` 私网阻断规则已就绪。
5. auth seed SQLite 只含 broker 占位 key，不含真实模型 key、OAuth 或 session；真实模型 key 只对 `factorforge-model` 可读。
6. EC2 host role 只有 SSM 与假设 data-read role 的权限；容器只取得一小时 data-read lease。S3 读取绑定专用 VPC endpoint，IAM 显式拒绝写删。
7. 邀请口令和 cookie secret 已注入 Web 环境，且与模型 key 分离。

## 2. 必需环境变量

```text
FACTORFORGE_CONSOLE_INVITE_PASSWORD=<shared invite password>
FACTORFORGE_CONSOLE_COOKIE_SECRET=<at least 32 random bytes>
FACTORFORGE_CONSOLE_COOKIE_SECURE=1
FACTORFORGE_CONSOLE_OPENCLAW_PROFILE=factorforge-console
FACTORFORGE_CONSOLE_MODEL=deepseek/deepseek-reasoner
FACTORFORGE_CONSOLE_THINKING=high
FACTORFORGE_CONSOLE_AGENT_TIMEOUT=3300
FACTORFORGE_CONSOLE_OPENCLAW_AUTH_PROVIDER=deepseek
FACTORFORGE_CONSOLE_OPENCLAW_AUTH_SEED_DB=<private seed sqlite path>
FACTORFORGE_CONSOLE_EXECUTION_MODE=container
FACTORFORGE_CONSOLE_CONTAINER_RUNTIME=docker
FACTORFORGE_CONSOLE_CONTAINER_NETWORK=factorforge-console-egress
FACTORFORGE_CONSOLE_CONTAINER_NETWORK_SUBNET=172.29.0.0/24
FACTORFORGE_CONSOLE_CONTAINER_PROXY_URL=http://172.29.0.1:3128
FACTORFORGE_CONSOLE_MODEL_BROKER_URL=http://172.29.0.1:8781
FACTORFORGE_CONSOLE_MODEL_BROKER_CLIENT_TOKEN_FILE=/etc/factorforge-console/model-broker-client-token
FACTORFORGE_CONSOLE_MODEL_BROKER_SECRET_SCAN_ROOT=/var/lib/factorforge-console/secret-scan
FACTORFORGE_CONSOLE_AWS_READONLY_ROLE_NAME=factorforge-console-pilot-data-read-role
FACTORFORGE_CONSOLE_AWS_HOST_ROLE_NAME=factorforge-console-pilot-host-role
FACTORFORGE_CONSOLE_AWS_ACCOUNT_ID=525164180577
FACTORFORGE_CONSOLE_INSTALLATION_ID=factorforge-console-pilot-20260801
FACTORFORGE_CONSOLE_ENGINE_COMMIT=<exact 40-char deployment commit>
FACTORFORGE_CONSOLE_AGENT_IMAGE=sha256:<exact local Docker image id>
FACTORFORGE_CONSOLE_OPENCLAW_PROFILE_TEMPLATE=<committed profile template>
FACTORFORGE_CONSOLE_STATE_ROOT=<external private state root>
FACTORFORGE_CONSOLE_LEDGER_ROOT=<shared ledger root>
FACTORFORGE_CONSOLE_WORKTREE_ROOT=<external worktree root>
FACTORFORGE_DATA_CATALOGS=<comma separated approved catalog paths>
FACTORFORGE_CONSOLE_CATALOG_RECEIPT=<active catalog receipt path>
FACTORFORGE_DATA_API_PYTHONPATH=<clean committed Data API package root>
FACTORFORGE_CONSOLE_DATA_API_COMMIT=<exact 40-char Data API commit>
```

禁止把真实值写入 Git、网页、artifact 或 agent prompt。

生产服务每次启动只读下载 active catalog
`s3://yufan-data-lake/factorforge/data/catalog/data_catalog.json` 到 Console 私有 state；不得用 repo 内旧 catalog 或 Mac 本地绝对路径替代 production truth。

## 3. Linux 主机布局

新主机先安装 `docker`、`squid`、`python3-venv`、`git`、`iptables` 和 Caddy，随后固定以下布局：

```bash
sudo groupadd --system factorforge-console
sudo groupadd --system factorforge-secret-scan
sudo useradd --system --home /var/lib/factorforge-console/web-home --shell /usr/sbin/nologin factorforge-web
sudo useradd --system --home /var/lib/factorforge-console/runner-home --shell /usr/sbin/nologin factorforge-runner
sudo useradd --system --home /var/lib/factorforge-console/model-home --shell /usr/sbin/nologin factorforge-model
sudo usermod -aG factorforge-console factorforge-web
sudo usermod -aG factorforge-console,docker,factorforge-secret-scan factorforge-runner
sudo usermod -aG factorforge-console,factorforge-secret-scan factorforge-model

sudo install -d -o factorforge-runner -g factorforge-console -m 0750 /var/lib/factorforge-console
sudo install -d -o factorforge-runner -g factorforge-console -m 0750 /var/lib/factorforge-console/state
sudo install -d -o factorforge-runner -g factorforge-console -m 0770 /var/lib/factorforge-console/ledger
sudo install -d -o factorforge-runner -g factorforge-console -m 0750 /var/lib/factorforge-console/runs
sudo install -d -o factorforge-model -g factorforge-secret-scan -m 2770 /var/lib/factorforge-console/secret-scan
sudo install -d -o root -g factorforge-console -m 0750 /etc/factorforge-console
sudo install -d -o root -g root -m 0755 /opt/factorforge-console

sudo python3 -m venv /opt/factorforge-console/venv
sudo /opt/factorforge-console/venv/bin/pip install --no-cache-dir \
  -r deploy/factorforge-console/requirements-host.txt
sudo install -o root -g root -m 0755 \
  deploy/factorforge-console/configure-container-network.sh \
  /opt/factorforge-console/configure-container-network.sh
sudo install -o root -g root -m 0644 deploy/factorforge-console/*.service /etc/systemd/system/
sudo install -o root -g root -m 0644 deploy/factorforge-console/*.timer /etc/systemd/system/
sudo install -o root -g root -m 0644 \
  deploy/factorforge-console/squid-factorforge-console.conf \
  /etc/squid/factorforge-console.conf
```

`/srv/factorforge/control` 与 `/srv/factorforge/data-api` 必须分别是 clean checkout，HEAD 必须等于环境中固定的 engine commit 与 Data API commit。控制 checkout 归 runner 读取；只有其 `.git/worktrees` 元数据允许 runner 写入。不得把主开发 worktree 或共享研究机目录直接挂到服务中。

密钥文件权限必须是：DeepSeek key `factorforge-model:factorforge-model 0600`；broker client token `root:factorforge-secret-scan 0640`；auth seed SQLite `factorforge-runner:factorforge-runner 0600`。auth seed 的唯一 `deepseek/api_key` 值必须与 broker client token 完全相同，不能放真实 DeepSeek key。

## 4. 构建与本地 UI 开发

Linux Pilot 主机先构建固定 agent image，并配置隔离网络：

```bash
docker build -f deploy/factorforge-console/Dockerfile.agent \
  -t factorforge-console-agent:2026.08.01 .

docker image inspect factorforge-console-agent:2026.08.01 --format '{{.Id}}'
# 把输出的 sha256 image id 写入 FACTORFORGE_CONSOLE_AGENT_IMAGE。

sudo -E deploy/factorforge-console/configure-container-network.sh
# 将 squid-factorforge-console.conf 安装到 /etc/squid/，再启动 proxy unit。

python3 scripts/run_factorforge_console.py \
  --mode combined \
  --auth-disabled \
  --source-repo /path/to/clean/factor-factory-control \
  --state-root /path/to/private/console-state \
  --worktree-root /path/to/private/factor-runs \
  --base-ref HEAD \
  --catalog /path/to/approved/data_catalog.json \
  --data-api-pythonpath /path/to/clean/factor-factory-data-api \
  --host 127.0.0.1 \
  --port 8765
```

上述 combined 命令仅用于本机 UI 开发。生产只允许 systemd 分别以
`--mode worker` 和 `--mode web` 启动两个进程。

Mac 上只做 UI 开发时，可显式设置 `FACTORFORGE_CONSOLE_EXECUTION_MODE=shared_gateway` 并使用 loopback `--auth-disabled`；该路径不属于隔离验收，不能暴露公网或形成正式研究 proof。正式朋友测试必须使用 Linux container mode。

## 5. 健康与审计

服务启动前会自动检查：

- 控制 worktree clean、base commit 可解析。
- agent image、专用 bridge 的 subnet/IPv6/internal 属性。
- `DOCKER-USER` 只允许 bridge -> `172.29.0.1:3128/8781`；容器外部 DNS 解析必须失败；Squid 仅允许指定 S3 bucket host，模型原站只能由 broker 访问。
- OpenClaw profile 的 model endpoint、plugin 和 tool allowlist。
- auth seed provider/type/key 合法，且不含 SQLite WAL/SHM sidecar。
- model broker denied-secret 目录只对 `factorforge-model` 与 runner 的专用 group 开放；`active.registry` 必须只指向当前任务的 registry，删除该目标后 broker `/healthz` 必须返回 503，即使目录中仍有历史 registry；当前 AWS lease 原值和常见编码不得通过模型请求。
- active catalog receipt 的 role、hash、dataset count 和刷新时间有效。
- 启动时只回收相同 installation id 的遗留 agent 容器；回收失败则 runner 不启动。
- 容器 Data API read smoke 能从 active S3 catalog 对 `clean_daily_bar` 做真实单日读取。

运行中检查：

- `/healthz` 同时报告 ledger、worker、engine、agent runtime 和 catalog；任一失败返回 503。
- 任务详情不出现服务器绝对路径、session key 或原始日志。
- 浏览器下载只能命中任务结果白名单中的不可变 publication set，不能直接读取 workspace。
- `worktree_root/<factor>/<research>/repo` 与 workspace 一一对应。
- 容器内 `git rev-parse HEAD` 必须命中任务 base commit，且 `GIT_DIR` 指向任务私有 shallow Git view，不指向控制仓库 `.git`。
- 每个任务结束后 Git changed/untracked/ignored 路径全部位于当前 workspace。

## 6. AWS Pilot

不得复用共享 `openclaw-new`，不得唤醒 `factor-research-worker`。

新建专用 EC2：

1. Region 使用 `ap-southeast-1`，与现有 Data API/S3 同区。
2. 加密 EBS；使用 SSM 管理，不开放 22。
3. Security Group 只允许公网 80/443，Console 只监听 `127.0.0.1`。
4. 新建专用 S3 Gateway VPC endpoint；instance profile 的 host role 只允许 SSM 与假设 data-read role，data-read role 只允许经该 endpoint 读取 approved catalog/datamart prefix，并明确拒绝对象写入/删除。
5. `/srv/factorforge/control` 是 clean、固定 commit 的部署 checkout。
6. `/var/lib/factorforge-console` 存任务账本、agent state 和 factor worktrees。
7. `/etc/factorforge-console` 只存 root-readable 配置或 Secrets Manager materialization。
8. Caddy 负责 HTTPS 和覆盖 `X-Forwarded-For`；systemd 管理 network、S3 proxy、model broker、runner、Web、Caddy 六个 unit。Caddy 对 Web 使用 `Wants` 而不是 `Requires`，代码更新期间 Web 短暂停机不得连带停止 HTTPS unit。Web 用户不得进入 Docker group。
9. EC2 metadata hop limit 设为 1；容器环境固定 `AWS_EC2_METADATA_DISABLED=true`，并验证 `169.254.169.254` 不可达。
10. 在开放邀请前执行容器内六项网络正负例、Data API read smoke、一个真实 factor workspace E2E、正式 evidence verifier 和浏览器路径/secret 扫描。

域名、证书和实例就绪后才能向朋友开放；未配置 HTTPS 时禁止把共享口令站点暴露到公网。

## 7. 恢复与回滚

- Console 重启：运行中任务自动转为 `REVIEW_REQUIRED`，用户决定是否继续。
- Console 重启会停止或回收它自己标签下的遗留 agent 容器，不自动重放 agent turn。
- 新版本异常：停止 Console，切回上一固定 commit，保留 state/worktree，再启动核验。
- 任务 BLOCK：保留 workspace 和外部账本，不自动删除。
- 凭据泄漏：先轮换 provider key、邀请口令和 cookie secret，再失效旧 session，最后恢复服务。

任何清理都先按任务 manifest 和 Git worktree registration 盘点；禁止通配删除或清理其他活跃研究。
