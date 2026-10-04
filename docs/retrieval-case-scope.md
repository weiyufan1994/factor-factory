# Query-relative historical case scope

A source record's `knowledge_scope="same_factor"` describes its original
research context. When a different factor retrieves that record, it is an
analogy, not current same-factor evidence. The index and source record keep
their original meaning and identities.

Step6's `build_retrieval_context` now projects scope **after** all existing
lexical/semantic/graph ranking, deduplication and top-k selection. It retains
every selected reference and the original order, score, source path and hashes.
Only an unambiguous different source factor is projected to
`knowledge_scope="similar_case"`. `source_knowledge_scope="same_factor"` and
`retrieval_scope_resolution` record the original scope, source factor and query
factor. The query's routing identity must agree with its actual artifact
identity; all supplied source factor identities must agree exactly.

Unknown, malformed or conflicting factor identities are not downgraded. Records
of the current factor remain on the existing strict comparison path: formula,
code, code contract, custom block, hybrid, branch and run mismatches still block.
The existing hash/run checks in `build_case_comparison` remain; a directly supplied
incorrect same-factor claim still blocks. Its factor-owner check additionally
rejects an empty current factor or contradictions across top-level,
artifact-identity and source-identity factor claims, even when the preferred
identity alone happens to match. Similar-case material is analogy only and never
counts as current promotion evidence. Other existing knowledge scopes remain
unchanged. No identity is renamed or substituted.

This is a framework maintenance fix. It does not edit or filter a published
index, suppress retrieval, alter a query, increase top-k, or rewrite a study's
specification, results or pin. An older immutable runtime does not contain the
fix. There is no separate resolver override in its native Step6 run/validate
path: any formal consumption requiring a maintenance runtime must record that
version change explicitly through the research owner's existing maintenance
procedure. Keeping an old pin means keeping its original code; using a different
index to avoid a valid cross-factor record is not a supported workaround.

Offline tests cover source provenance preservation, all existing same-factor
hash/run guards, unknown/conflicting identities, exact same-factor history and
unchanged result ordering/budget across lexical, local semantic and legacy
embedding candidates. Real-study verification is a read-only component replay,
with no Step6 execution or market computation.
