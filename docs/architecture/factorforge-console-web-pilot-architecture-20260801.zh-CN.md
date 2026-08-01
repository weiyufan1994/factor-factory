# Factor Forge Console Web Pilot 架构书

日期：2026-08-01

状态：实现与本地验收

适用范围：邀请制朋友测试，不是公开注册 SaaS

## 1. 目标

用户通过网页提交自然语言因子假设，随后在同一个页面查看：

1. Ultimate 五阶段研究进度与暂停状态。
2. 经济机制、数学对象、数据合同和实现说明。
3. IC、Rank IC、ICIR、Fama-MacBeth、long-side after-cost、换手、回撤、恢复期和分组单调性等已有正式证据。
4. Council 结论、blocker、下一步和可公开 artifact。
5. 因子最终 `ACCEPT / REJECT / ITERATE / BLOCK`，并与研究协议 `PASS / BLOCK` 分开显示。

Web Pilot 复用现有 Factor Forge、Data API 和模型账号，但不写共享数据、不复用共享 agent 会话，也不在共享研究机上部署。

## 2. 核心不变量

### 2.1 一个因子研究一个隔离单元

每个任务必须同时拥有：

```text
factor_id + research_id + report_id
固定 engine commit
独立 detached Git worktree
worktree 内独立 factor workspace
独立 OpenClaw agent id / session
外部任务账本记录
```

路径结构：

```text
<worktree_root>/<factor_id>/<research_id>/repo/
  factor_research/<factor_id>/<research_id>/
    manifest.json
    identity/
    reports/
    objects/
    step3_runtime/
    knowledge/
```

因子代码、模型中间产物、Council packet、图表、回测和知识只能写入该 workspace。任务结束后执行 Git 级写入审计；任何越界写入都把任务置为 `BLOCK_FACTORFORGE_CONSOLE_ISOLATION_AUDIT_FAILED`。

### 2.2 数据只读

现有 Data API catalog 和 approved datamart 是输入，不是 Console 的数据库：

- 不写 raw S3、clean data、catalog 或 production datamart。
- 缺数据时生成 workspace 内的 data request / blocker。
- 不允许用 fixture、mock、smoke 或 dry-run 代替正式研究证据。
- 云上 IAM 只授予明确 catalog/datamart prefix 的读取权限，不授予 `PutObject` 或 `DeleteObject`。

### 2.3 状态语义分离

网页必须分别展示：

| 维度 | 含义 |
|---|---|
| execution status | 排队、研究、核验、待人工继续、完成、阻断、失败 |
| protocol status | Ultimate 研究协议是否 PASS |
| factor verdict | 因子是 ACCEPT、REJECT、ITERATE 还是 BLOCK |
| Council status | Council 是否完成、暂停或阻断 |
| proof eligibility | 当前证据能否作为正式 proof |

`protocol=PASS` 不等于 `factor=ACCEPT`。正式 `REJECT` 是完成了一次有效研究，不是系统失败；wrapper 返回 0 也不能覆盖 Council pause。

## 3. 系统结构

```mermaid
flowchart LR
  U["浏览器"] --> P["Caddy HTTPS"]
  P --> W["Console Web"]
  W --> L["SQLite WAL 任务账本"]
  W --> Q["单并发队列"]
  Q --> A["Worktree Allocator"]
  A --> FW["因子专属 Git worktree + workspace"]
  Q --> O["专用 OpenClaw Gateway"]
  O --> AG["因子专属 agent/session"]
  AG --> FW
  AG --> D["Data API / approved datamarts 只读"]
  FW --> V["Ultimate evidence reader + isolation audit"]
  V --> L
  L --> W
```

### 3.1 Web 层

- Python 标准库 HTTP server，避免给现有仓库引入新的前端构建链。
- 共享邀请口令登录；签名 `HttpOnly`、`SameSite=Lax` cookie。
- 所有写操作要求 CSRF token。
- 请求体和字段长度有限制，登录有基础限速。
- 只公开安全扩展名和经过扫描的 workspace-relative artifact。
- HTML/SVG 强制下载，服务端绝对路径、日志、凭据和疑似 secret 不公开。

### 3.2 任务账本

SQLite 位于 repo 外部，使用 WAL 和原子 claim。Pilot 并发固定为 1：

- 防止多个完整 Ultimate 同时耗尽本机资源。
- 服务重启时，运行中任务转为 `REVIEW_REQUIRED`，不自动重复执行。
- 失败现场、worktree 和 workspace 默认保留，不自动破坏性清理。

### 3.3 Agent 层

Console 使用独立 OpenClaw profile 和独立 loopback gateway：

- 无聊天频道、无 cron、无 heartbeat。
- 不使用共享主 agent 的 session 或 OAuth 数据库。
- 每个因子创建独立 agent state 和 session key。
- 认证来自只含一个可移植 API key 的只读 seed SQLite；复制到新 agent 后不再共享写入。
- 启动前必须通过 config、gateway health、plugin error 和 seed schema 检查。

当前 Pilot 固定使用 `deepseek/deepseek-reasoner` 和 `thinking=high`。后续 BYOK 必须新增 provider/model/thinking/auth-seed 的成组校验，不能只让用户填一个 key 字符串。

### 3.4 Ultimate 执行

Agent 先读取仓库内正式 skills，然后：

1. 把网页输入当作 `natural_language_hypothesis`，不伪造研报来源。
2. 生成 Step1/Step2 语义研究对象和 mechanism/math contracts。
3. Step3-6 只调用 `scripts/run_factorforge_ultimate.py`。
4. 不调用现有 `run_factorforge_ultimate_loop.py`，直至其 workspace 和审批语义缺陷关闭。
5. 缺数据、缺 Council 证据或无法完成时形成可审计 pause/BLOCK，不编造结果。
6. 最后写 `identity/web_agent_completion.json`，但网页仍以正式 Ultimate artifact 为主证据核验。

## 4. 任务生命周期

```text
QUEUED
  -> ALLOCATING
  -> RESEARCHING
  -> VERIFYING
  -> COMPLETED | REVIEW_REQUIRED | BLOCKED | FAILED
```

- `COMPLETED + REJECT`：研究协议完成，因子被否决。
- `REVIEW_REQUIRED`：证据处于合法暂停，用户可从网页明确点击继续。
- 网页继续只写 `web_user_resume`，不能伪造 human approval 或 official promotion。
- 未知异常统一 BLOCK 并保留证据，不让后台 worker thread 静默死亡。

## 5. 信任边界

### 5.1 允许

- 读取固定 commit 的 Factor Forge 代码和 skills。
- 读取 allowlisted Data API catalog/datamart。
- 写该任务 workspace、该任务 agent state 和 Console 外部 SQLite。
- 从公开 HTTPS URL 读取用户提供的研究参考。

### 5.2 禁止

- 写另一个因子 workspace、baseline Step3、repo-root `knowledge/` 或 `data/`。
- 访问 localhost、私网、metadata host 或带 URL 凭据的参考链接。
- 使用共享 `openclaw-new` 或唤醒 `factor-research-worker` 部署网站。
- 将研究机关闭、抢占、清理其他用户进程或复用其他任务 worktree。
- 自动 `git add .`、自动合并因子 workspace 产物或自动删除失败现场。

## 6. 云部署决策

首个朋友测试版采用 `ap-southeast-1` 的独立单机：

- 新 EC2、新 security group、新 instance profile、新加密 EBS。
- SSM 管理，不开放 SSH；公网只开放 80/443。
- Caddy 终止 HTTPS；Console 和 OpenClaw gateway 只监听 loopback。
- Console 与 OpenClaw 分别由 systemd 管理。
- Data API 通过现有 approved catalog/datamart 只读访问。
- 模型 key、邀请口令和 cookie secret 来自 Secrets Manager 或 root-only 环境文件。

单机是 Pilot 的成本/复杂度选择，不是长期多租户架构。达到多用户并发、按用户隔离或计费需求后，再拆成 Web/API、队列、worker 和对象存储。

## 7. 验收门槛

### 7.1 代码验收

- Console 全量单测和 legacy smoke PASS。
- 源 worktree clean，固定 commit 可解析。
- Agent profile config/health PASS，插件错误为 0。
- 静态 auth seed 仅含一个指定 provider 的 `api_key` profile。
- 桌面和手机 Playwright 截图无重叠、无路径泄漏。

### 7.2 使用结果验收

至少提交一个真实假设并观察：

- 独立 worktree/workspace/agent 创建成功。
- Data API 只读调用可用，或产生准确 data request。
- 页面能区分 protocol、factor、Council 和 proof eligibility。
- REJECT/BLOCK/pause 仍展示完整研究方法和证据链。
- Git 写入审计没有 workspace 外路径。

这是一项“Web 能安全驱动正式框架”的 proof，不等于任一因子已 `ACCEPT`，也不等于多租户生产 SaaS 已完成。
