# Factor Forge Ultimate — 研究源码与 SDK

这是可阅读、可本地运行的研究包。发布内容取自 `bundle_inventory.json` 指明的 Git 提交，不包含作者工作区的未提交改动。运行中的研究仍使用自己的固定版本；解压本包不会安装全局 Skill、切换默认环境或更改历史结果。

研究主线保持：理解原文/假设 → 经济机制与数学推导 → 因子类实现和评审 → 标准因子值及评估 → 解释、修订或停止。知识库提供有来源的参考，GP/MCTS 帮助实现和检验已限定的数学机制，不代替新的推导。

## 包里有什么

| 路径 | 用途 |
|---|---|
| `factor-forge/` | 研究框架、Skill、脚本、例子、测试及只读知识参考。 |
| `wheels/factor_factory-*.whl` | 可独立安装的 Python 研究库；纯计算 SDK、Step5/6 公共能力可直接调用。 |
| `factorforge-data-api/`、对应 wheel | 构建时显式选入的独立 Data API SDK；客户端和必要资源，不含生产补数脚本。未选入时由使用环境另行提供。 |
| `bundle_inventory.json` | 源提交、文件选择和实际 wheel 内容；用于检查交付一致性。 |

完整 Ultimate 还使用包中的 `scripts/`、`skills/`、`docs/` 和 `examples/`。SDK wheel 不是独立的完整研究编排应用；运行完整流程时保留源码树，不能只复制一个 Python 包。

包里没有商业行情、原研报 PDF、账户凭据或完整历史运行目录。安装后的离线例子可独立验证接口，不等于多年回测、真实独立评审或研究收益验证。

## 安装

最低 Python 3.11；本轮目标为 3.11–3.14，实际已测系统/版本见 `docs/publish-verification.zh-CN.md`。核心 pandas 保持 2.x。

在解压后的 `factor-forge/` 目录：

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[console,step4,test]'
# 如果本次包附带独立 Data API SDK：
python -m pip install '../factorforge-data-api[test]'
python -m pip check
```

`console` 目前是保留的依赖分组名，包含 PDF/历史证明解析依赖，不表示启动 Web Console。纯 DataFrame 使用者安装框架 wheel 或 `pip install .` 即可；Step4 增加 `.[step4]`，明确选择 Qlib 时才安装 `.[qlib]`。

第三方版本按实际测试环境记录：`packaging/constraints-tested-macos.txt` 对应 macOS Python 3.13，`packaging/constraints-tested-macos-py311.txt` 对应 macOS Python 3.11。在相同环境安装时可加 `-c` 使用；3.13 清单不能直接用于 3.11，也不是所有平台已通过的声明。依赖未缓存时安装需要网络；研究包没有自动下载行情、安装 Qlib 或连接服务的步骤。

## 三个手算例子

```bash
python examples/manual_interface_replay/run_demo.py --output-dir /tmp/factor-manual-interface
python examples/manual_interface_replay/run_account_demo.py --output-dir /tmp/factor-manual-account
python examples/manual_interface_replay/run_result_artifact_demo.py --output-dir /tmp/factor-manual-results
```

每次使用新的输出目录。例子提供逐值结果和复算材料；账户例子的已知净值路径是 1010 / 1000 / 1000 / 1188，总费用 22。代码、factor head/tail、指标与样本属于同一组显式输入。

完整离线测试：

```bash
export PYTHONPATH="$PWD"
export PFVV_MONTHLY_EXECUTION_ENGINE_PATH="$PWD/examples/mszq_intraday_momentum_pulse/local_is_execution_engine"
python -m pytest -c pytest-offline.ini
```

`pytest-offline.ini` 明确测试范围；真实行情/云环境、可选后端与独立研究的状态分别记录。两项历史 Git 状态测试仍明确 deselect，因为交付源码不带旧 Git 历史；不把研究失败转成跳过。测试中的 agent 输出是合成输入，不冒充真实独立评审。

## 研究入口与标准接口

默认 11 个 Skill 及可选/兼容入口见 `packaging/research-skills.json`。让研究员读取本包 `skills/factor-forge-ultimate/SKILL.md`，不要混用另一版全局 Skill。默认入口之外的旧角色路径仅用于兼容；研究员日志已并入 Ultimate，证据解释和独立评议在 Step6 维护。

常用 Python 入口：

- `factor_factory.factors`：`BaseFactor`、`PriceVolumeFactor`、`FundamentalFactor`、`FormulaFactor`。
- `factor_factory.research_api`：标准因子表、标签、覆盖、IC 等统计。
- `factor_factory.portfolio_api`：账户回测，沿用显式价格、交易约束和费用。
- `factor_factory.result_artifacts`：可阅读样本、结果和复算材料。

因子表为有序唯一的 `(datetime, instrument)` MultiIndex，`factor_value` 为 float64；真实零和 NaN 保留。研究员自行用明确输入实现因子类，不在计算入口隐式取数或生成未来标签。Qlib 兼容结构不等于已经证明两个账户引擎逐笔等价。

完整流程的普通帮助与全部兼容参数：

```bash
python scripts/run_factorforge_ultimate.py --help
python scripts/run_factorforge_ultimate.py --help-all
```

实际研究使用单独工作区、用户指定 IS 范围和已有 Data API/catalog。普通本地 IS 走 `--local-is-only`，不要求部署 Host/SoD。改变经济机制或估计对象时回到 Step2；Step3 代码先经真实评审再执行。新普通研究 V2 允许一条充分的推导/证伪和有理由停止，旧研究保留原解释。

## 知识读取与搜索

```bash
python query_knowledge.py --query '小波分析' --json
python query_knowledge.py --query 'zzuncoveredq42' --json
```

图谱、方法参考和两个既有经验种子由选定提交生成脱敏副本，保持 advisory/candidate。无命中正常；检索不证明原研报已复现或知识提高了收益。原文 PF/VV 基线和 EVENT_U/signed-A 扩展继续分开。

已有 GP/MCTS 的合成测试在离线清单中，研究增益只有真实研究记录才能支持。这里没有另外启动搜索预算、OOS、训练或知识库发布。

## 构建与排除范围

唯一完整包构建入口仍为 `scripts/build_factorforge_publish_bundle.py`。开发者先提交改动，再执行：

```bash
python -m pip install '.[build]'
python scripts/build_factorforge_publish_bundle.py \
  --source-commit HEAD \
  --data-sdk-root /path/to/delivered-data-api-sdk \
  --output /path/to/new-output-directory
```

构建只读选定 Git 提交和明确提供的 SDK，不自动拉取上游；SDK 文件身份单独记录。wheel 从临时副本离线构建，逐个模块核对实际 wheel 与分发源码。已有输出目录不覆盖。

`packaging/research-files.toml` 是单一分发选择表。历史 Host 构建巨型实现、Console 服务端入口、生产数据运维脚本和相应历史测试不随标准研究包交付，原始文件继续保存在 Git 中。仍被研究或兼容功能使用的辅助模块保留，并在验证说明中列出残余依赖；不是根据文件名批量删除 EVO/信息边界检查。

本轮本地候选不自动推送 GitHub或切换研究环境。公开发布前仍需所有者确认代码/参考资料许可；当前定位是私有研究试用。
