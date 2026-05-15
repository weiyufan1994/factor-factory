# Factor Forge Knowledge Sync SOP

本 SOP 固定 Mac、EC2、S3、GitHub 的分工，避免把知识库绑死在某一台在线机器上。

## 分工

- Mac：主编辑源，负责正式研究、review、知识库吸收与人工确认。
- GitHub：代码、skill、文档、SOP 的 canonical source。
- S3：Factor Forge 知识包耐久共享层，提供 `latest.json` 指针。知识包同时包含结构化 `objects/`、人类可读 `knowledge/因子工厂/` vault、以及 retrieval index。
- EC2：计算与缓存节点，从 GitHub 拉代码，从 S3 拉知识对象；产出结果后可上传到独立 `ec2-results` 前缀。
- Tailscale：可作为快速通道，但不是知识库可用性的依赖。Mac 关机时，EC2 仍应能从 S3 取最近一次发布的知识包。

## Mac 发布权威知识包

在 Mac repo 根目录执行：

```bash
python3 scripts/sync_factorforge_knowledge_bundle.py bundle \
  --runtime-root /Users/humphrey/projects/factor-factory \
  --upload \
  --update-latest \
  --bucket yufan-data-lake \
  --prefix factorforge-knowledge/mac-authoritative \
  --source-role mac_authoritative
```

结果：

- 上传 immutable `.tgz` 到 `s3://yufan-data-lake/factorforge-knowledge/mac-authoritative/`
- 更新 `s3://yufan-data-lake/factorforge-knowledge/mac-authoritative/latest.json`
- `latest.json` 包含 bundle URI、sha256、文件数、来源角色、git commit。

## Canonical Layout

Mac 本地只认这一套路径：

```text
/Users/humphrey/projects/factor-factory/objects/
/Users/humphrey/projects/factor-factory/knowledge/因子工厂/
/Users/humphrey/projects/factor-factory/knowledge/retrieval/
```

含义：

- `objects/`：唯一结构化写入源。Step5/6、factor library、knowledge base、iteration、case、handoff 都以这里为准。
- `knowledge/因子工厂/`：唯一人类可读 Obsidian/Markdown vault；包括普通因子库、正式因子库、知识库、研究迭代、手工研究 archive。
- `knowledge/retrieval/`：从 `objects/` 构建的检索索引。

不要把以下路径当作新的知识库入口：

- `knowledge/obsidian_vault/`：legacy 英文 vault，已废弃。
- `factorforge/objects/`：legacy/runtime 残留，不是 Mac canonical root。

因子研究员、Bernard、Codex 都应默认使用 `objects/` + `knowledge/因子工厂/` 这同一套地址。`ALPHA015_20160101_RESEARCH_ARCHIVE.md` 这类手工研究 archive 位于 `knowledge/因子工厂/知识库/`，并随 S3 knowledge bundle 同步。

## EC2 拉取 Mac 知识包

在 EC2 repo 根目录执行：

```bash
/home/ubuntu/.openclaw/workspace/.venvs/quant-research/bin/python \
  scripts/sync_factorforge_knowledge_bundle.py apply \
  --runtime-root /home/ubuntu/.openclaw/workspace/factorforge \
  --source s3://yufan-data-lake/factorforge-knowledge/mac-authoritative/latest.json \
  --apply \
  --rebuild-index
```

安全行为：

- 先读取 `latest.json`，下载对应 bundle。
- 校验 sha256，不一致直接 BLOCK。
- 默认只创建缺失文件。
- official library、case、handoff、validation 等 protected paths 默认不覆盖。
- 写同步审计到 `objects/sync_audit/sync_audit__*.json`。

## EC2 上传计算侧知识包

EC2 如果完成了需要回流的研究对象，上传到独立前缀，不能覆盖 Mac authoritative latest：

```bash
/home/ubuntu/.openclaw/workspace/.venvs/quant-research/bin/python \
  scripts/sync_factorforge_knowledge_bundle.py bundle \
  --runtime-root /home/ubuntu/.openclaw/workspace/factorforge \
  --upload \
  --update-latest \
  --bucket yufan-data-lake \
  --prefix factorforge-knowledge/ec2-results \
  --source-role ec2_results
```

## Mac 吸收 EC2 结果

Mac 端人工吸收 EC2 结果：

```bash
python3 scripts/sync_factorforge_knowledge_bundle.py apply \
  --runtime-root /Users/humphrey/projects/factor-factory \
  --source s3://yufan-data-lake/factorforge-knowledge/ec2-results/latest.json \
  --apply \
  --rebuild-index \
  --export-obsidian
```

吸收后必须查看 `objects/sync_audit/`。如果 protected overwrite 被 blocked，不能手工绕过；应先 review 对应对象是否应成为新的 canonical 记录。

## GitHub 同步

代码、skill、smoke、SOP 走 GitHub：

```bash
git status --short
git add <changed-files>
git commit -m "<message>"
git push
```

EC2 更新 repo 时使用 GitHub 分支或 commit，不用 Mac 在线文件系统作为唯一来源。

## 验证

本地无 S3 smoke：

```bash
python3 scripts/run_factorforge_knowledge_sync_smoke.py --fresh --root /tmp/factorforge_knowledge_sync_smoke
```

需要看到：

- `verdict=ACCEPT`
- latest manifest 可以解析 bundle。
- sha256 mismatch 被 BLOCK。
- protected overwrite 默认被 BLOCK。
- unsafe tar path 被 BLOCK。
- canonical pollution 为 false。
