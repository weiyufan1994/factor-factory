# Factor Forge 知识模块预览

构建：

```bash
python3 scripts/build_factorforge_knowledge_preview.py --output /tmp/factorforge-knowledge-preview.zip
unzip -q /tmp/factorforge-knowledge-preview.zip -d /tmp/knowledge-preview
cd /tmp/knowledge-preview
python3 query_knowledge.py --query '占用测度 价值 支撑'
```

这是离线、只读、advisory-only 的知识模块预览，不是完整 Ultimate 生产包，也不是 canonical admission。正式因子研究仍通过已有 Factor Forge Ultimate 及受治理数据环境执行。

验收顺序：先记录用户原始经济/数学假设；再调用 query 获取 advisory 历史案例；最后由研究者决定采用、拒绝或仅作类比。检索命中不代表收益或生产接纳。默认输出适合人读；加 `--json` 获取机器可读结果。

可回放：`占用测度 价值 支撑`、`open volume correlation low turnover payer`、`economic estimand mathematical model measurement`、`MAD sparse event execution constraint`、`小波分析`。`tropical geometry 热带几何`用于验证未覆盖方法的 cold-start；这些是历史知识/方法参考，不是收益声称。

打包副本会删除历史绩效数值字段及绝对个人路径，仅保留机制、数学对象、失败条件、复用边界和相对来源。若默认项目已有完成 Step6 后 create-only 的 workspace experience export，预览会只投影该明确候选记录到包内 retrieval index；它仍是 advisory、仅同因子不可泛化，不是 Host/canonical memory、收益结论或正式晋级。包内不扫描研究工作区，也不带原始实证文件。包内仅含知识检索运行时所需最小 Python 模块、公开 graph/taxonomy 副本和查询 CLI；不含原 PDF、行情/OOS payload、Host keys/state、私人配置或完整 contracts。
