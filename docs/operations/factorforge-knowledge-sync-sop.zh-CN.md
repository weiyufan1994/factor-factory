# Factor Forge Knowledge Sync SOP

本 SOP 固定 Mac、EC2、S3、GitHub 的分工，避免把知识库绑死在某一台在线机器上。

## 分工

- Mac：主编辑源，负责正式研究、review、知识库吸收与人工确认。
- GitHub：代码、skill、文档、SOP 的 canonical source。
- S3：Factor Forge 知识包耐久共享层，提供 `latest.json` 指针。知识包可包含 workspace 导出的结构化对象、人类可读 vault、retrieval index，以及导出 provenance。
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

正式生产研究首先只认 factor workspace 内路径：

```text
<factor_workspace>/objects/
<factor_workspace>/knowledge/canonical/
<factor_workspace>/knowledge/human_readable/
<factor_workspace>/knowledge/retrieval/
<factor_workspace>/knowledge/export_manifest/
```

含义：

- `<factor_workspace>/objects/`：该因子的结构化写入源。Step5/6、factor library、knowledge base、iteration、case、handoff 都以这里为准。
- `<factor_workspace>/knowledge/human_readable/`：该因子的生产人类可读 Markdown 输出。
- `<factor_workspace>/knowledge/canonical/`：该因子的结构化知识与队列输出。
- `<factor_workspace>/knowledge/retrieval/`：从 workspace objects/knowledge 构建的检索索引。
- `<factor_workspace>/knowledge/export_manifest/`：显式导出到 repo-root vault 或 S3 vault 时的审计记录。

不要把以下路径当作新的知识库入口：

- `knowledge/因子工厂/`：显式 export/vault，不再是 production 默认写入路径。
- `knowledge/obsidian_vault/`：legacy 英文 vault，已废弃。
- `factorforge/objects/`：legacy/runtime 残留，不是新研究 canonical root。

因子研究员、Bernard、Codex 都应默认使用当前 factor workspace。`knowledge/因子工厂/` 只用于明确执行 `--export-knowledge-vault` 的人工阅读/共享导出。

## Repo-root Vault 显式导出

累计 release 如果包含 `knowledge/因子工厂/` payload，必须新增当前快照
manifest；历史 manifest 只保留，不回写。当前 manifest 必须覆盖固定 base
commit 以来的全部 repo-root knowledge payload，并逐文件绑定 bytes 与 SHA-256：

```bash
python3 scripts/build_factor_knowledge_export_manifest.py \
  --base-ref <fixed-main-commit> \
  --output knowledge/因子工厂/export_manifest/repo_root_knowledge_export_<date>.json

python3 scripts/validate_factor_knowledge_commit_scope.py \
  --export-only \
  --export-manifest knowledge/因子工厂/export_manifest/repo_root_knowledge_export_<date>.json
```

验收要求：

- `verdict=ACCEPT`；
- `required_payload_count` 与 `entry_count` 一致；
- `failures=[]`；
- 任一遗漏文件、bytes/SHA 漂移或不属于固定 diff scope 的额外文件都必须 BLOCK；
- graph index/manifest 只能写 repository/artifact-root 相对路径，不能写 worktree
  绝对路径或 wall-clock 字段，以免无意义地污染后续 worktree。

## EC2 拉取 Mac 知识包

在 EC2 repo 根目录执行：

```bash
/home/ubuntu/.openclaw/workspace/.venvs/quant-research/bin/python \
  scripts/sync_factorforge_knowledge_bundle.py apply \
  --runtime-root /home/ubuntu/.openclaw/workspace/factorforge \
  --source s3://yufan-data-lake/factorforge-knowledge/mac-authoritative/latest.json \
  --apply \
  --overwrite-unprotected \
  --rebuild-index
```

安全行为：

- 先读取 `latest.json`，下载对应 bundle。
- 校验 sha256，不一致直接 BLOCK。
- 默认只创建缺失文件；如果需要让 EC2 普通知识层跟 Mac authoritative 对齐，使用 `--overwrite-unprotected`。
- `--overwrite-unprotected` 只覆盖普通对象、Markdown vault、retrieval index 等非 protected 文件。
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
