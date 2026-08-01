# Factor Forge Console Web Pilot 运行手册

日期：2026-08-01

## 1. 启动前检查

必须同时满足：

1. `source_repo` 是 clean、固定 commit 的专用控制 worktree。
2. worktree root 和 state root 位于 repo 外部，目录权限为 `0700`。
3. Data API catalog 存在且仅作为读取输入。
4. 使用专用 OpenClaw profile；gateway health 为 `ok=true`，plugin errors 为空。
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
FACTORFORGE_CONSOLE_STATE_ROOT=<external private state root>
FACTORFORGE_CONSOLE_WORKTREE_ROOT=<external worktree root>
FACTORFORGE_DATA_CATALOGS=<comma separated approved catalog paths>
FACTORFORGE_DATA_API_PYTHONPATH=<clean committed Data API package root>
```

禁止把真实值写入 Git、网页、artifact 或 agent prompt。

## 3. 本地运行

先启动专用 gateway，再启动 Console：

```bash
openclaw --profile factorforge-console gateway run

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

开发 UI 时可在 loopback 使用 `--auth-disabled`；该参数在非 loopback 地址会被拒绝。

## 4. 健康与审计

服务启动前会自动检查：

- 控制 worktree clean、base commit 可解析。
- OpenClaw config 和 gateway health。
- plugin errors 为 0。
- auth seed provider/type/key 合法。

运行中检查：

- `/healthz` 返回服务健康。
- 任务详情不出现服务器绝对路径、session key 或原始日志。
- `worktree_root/<factor>/<research>/repo` 与 workspace 一一对应。
- 每个任务结束后 Git changed/untracked/ignored 路径全部位于当前 workspace。

## 5. AWS Pilot

不得复用共享 `openclaw-new`，不得唤醒 `factor-research-worker`。

新建专用 EC2：

1. Region 使用 `ap-southeast-1`，与现有 Data API/S3 同区。
2. 加密 EBS；使用 SSM 管理，不开放 22。
3. Security Group 只允许公网 80/443，Console/OpenClaw 端口只监听 `127.0.0.1`。
4. Instance profile 只允许读取 approved catalog/datamart prefix；明确拒绝对象写入/删除。
5. `/srv/factorforge/control` 是 clean、固定 commit 的部署 checkout。
6. `/var/lib/factorforge-console` 存任务账本、agent state 和 factor worktrees。
7. `/etc/factorforge-console` 只存 root-readable 配置或 Secrets Manager materialization。
8. Caddy 负责 HTTPS 和反向代理，systemd 管理 gateway/Console。

域名、证书和实例就绪后才能向朋友开放；未配置 HTTPS 时禁止把共享口令站点暴露到公网。

## 6. 恢复与回滚

- Console 重启：运行中任务自动转为 `REVIEW_REQUIRED`，用户决定是否继续。
- Gateway 重启：不自动重放 agent turn。
- 新版本异常：停止 Console，切回上一固定 commit，保留 state/worktree，再启动核验。
- 任务 BLOCK：保留 workspace 和外部账本，不自动删除。
- 凭据泄漏：先轮换 provider key、邀请口令和 cookie secret，再失效旧 session，最后恢复服务。

任何清理都先按任务 manifest 和 Git worktree registration 盘点；禁止通配删除或清理其他活跃研究。
