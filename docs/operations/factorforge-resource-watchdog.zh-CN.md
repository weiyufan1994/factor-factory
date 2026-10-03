# 本地进程资源监控入口

`scripts/run_factorforge_resource_guard.py` 将原研究中的轮询、流式日志和同进程组终止逻辑参数化。它只接受调用者已选定的 argv，不生成研究命令，不选择 release/report/workspace/prepared inputs，不替代 Ultimate 原有 manifest/pin 或研究 review，也不改变因子、评价器或窗口。

使用研究所 pin 运行环境的 Python，传显式工作目录、所需内存估算和已有 Ultimate 命令：

```text
<pinned-python> <published-guard-script> \
  --cwd <study-workspace> \
  --minimum-required-gib <caller-estimated-total-requirement> \
  -- <pinned-release>/run-ultimate <the-existing-reviewed-Ultimate-arguments>
```

默认只打印 argv 并返回 2，不启动子进程、不创建日志。准备执行时在 `--` 前加入 `--run-reviewed-guard`；该开关只启动调用者选定命令，不生成或验证研究审批。`--` 后 argv 原样传给 Popen，不经 shell。选择明确的已发布绝对路径，不依赖变化中的 current；既有研究可以保持旧 release pin。

`--minimum-required-gib` 是调用方估算的**总进程树最低预算要求**，必须为 (0,4] 内的有限值，并被记录。参数不证明实际负载能装入预算。旧 ACR 的 3.615 GiB 不是新研究通用阈值；评价器自身估算也不能当作父进程加 native 子进程全树峰值。未知部分由研究负责人保留并判断，不由 guard 捏造。

执行时重新读取本机资源，沿用原有界限：

- 总 RSS 预算 `min(4 GiB, floor(0.55 * available_memory))`，低于调用方给的最低要求则不启动。
- 每 50 ms 合计 monitor 自身、入口子进程及递归可枚举后代的当前 RSS。
- 运行超时 7200 秒。
- 启动时至少 128 GiB 磁盘空闲；运行时至少保留 `max(128 GiB, initial_free - 128 GiB)`，兼顾留足 128 GiB 与最多净消耗 128 GiB。不会删除文件腾空间。
- 超 RSS、超时、低磁盘或日志读取/写入失败即失败，终止**本次 start_new_session 创建的进程组**，不按名字终止其他研究进程。

日志位于显式 cwd 下的 logs，时间戳和随机后缀独占创建，stdout/stderr 按块写出；不会将全部输出积累进 RAM。JSON 记录原 argv、cwd、guard 源码 SHA、调用者估算、实时预算、采样峰值/进程数、最小观测磁盘、耗时、退出码和失败原因。`GUARDED_PROCESS_EXITED_ZERO` 只表示所监控进程退出零，不是 Step4/5 通过或因子有效。

边界沿用原逻辑：轮询不是 OS 硬内存上限，峰值可能发生于两次采样之间。当前同步 launcher 子树保持同进程组是终止覆盖的前提；自行 detach、新会话或 reparent 的后代不保证被清理。入口退出后不继续充当通用孤儿进程管理器，后续独立归档进程也不在范围内。进程枚举会有竞态；无访问权限等异常按失败处理。磁盘/日志严重故障仍可能留下不完整 JSON，不能把无有效回执视为成功。没有自动重试、后台恢复或市场数据读取。

验收 `tests/test_resource_watchdog.py` 包括：默认不执行、递归 RSS 合计、各资源/日志故障只杀自己的组、非零退出、启动前预算不足、非法估算、原磁盘两边界、日志不覆盖，以及真实的微小 Python 多层子进程完成。合成控制不是当前研究的内存/速度实测。
