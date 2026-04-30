#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="/home/ubuntu/.openclaw/workspace"
PYTHON_BIN="/home/ubuntu/miniconda3/envs/rdagent/bin/python"
COLLECTOR="$WORKSPACE/scripts/collect_data_yichu_intraday_source_layer.py"
FEISHU_TARGET="chat:oc_c9d1a01e479bf4292208b5d46a94a0d8"
HUMPHREY_TARGET="user:ou_b1a819365266bc4b91224ec75b91359a"
OPENCLAW_CMD=(sudo -u ubuntu -H openclaw)

cd "$WORKSPACE"

OUT="$("$PYTHON_BIN" "$COLLECTOR")"
JSON_PATH="$(printf '%s\n' "$OUT" | awk -F'JSON: ' '/^JSON: / {print $2}' | tail -n 1)"
MD_PATH="$(printf '%s\n' "$OUT" | awk -F'MD: ' '/^MD: / {print $2}' | tail -n 1)"

if [[ -z "${JSON_PATH:-}" || -z "${MD_PATH:-}" ]]; then
  echo "failed to parse output paths" >&2
  printf '%s\n' "$OUT" >&2
  exit 1
fi

SUMMARY="$("$PYTHON_BIN" - <<'PY' "$JSON_PATH" "$MD_PATH"
import json
import sys

jpath, mpath = sys.argv[1], sys.argv[2]
obj = json.load(open(jpath, "r", encoding="utf-8"))
summary = obj.get("strong_pool_summary", {})
topics = obj.get("topic_resonance", [])[:5]
status = obj.get("source_status", {})
hhi = obj.get("intraday_hhi", {})
exposure_hhi = hhi.get("exposure_hhi", {})
score_hhi = hhi.get("score_hhi", {})

status_bits = []
for key in ("realtime_list", "kpl_list:涨停", "kpl_concept_cons", "dc_concept_cons", "dc_member", "ths_member"):
    item = status.get(key, {})
    state = item.get("status", "unknown")
    source = item.get("source")
    if source:
        status_bits.append(f"{key}={state}/{source}")
    else:
        status_bits.append(f"{key}={state}")

lines = [
    "数据一处｜盘中题材共振汇报",
    f"- 时间：{obj.get('collected_at_beijing', '')}",
    (
        "- 强势股池："
        f"{summary.get('strong_pool_count', 0)}只；"
        f"涨停阈值{summary.get('limit_up_threshold_count', 0)}只；"
        f"涨速Top100覆盖{summary.get('rise_top100_count', 0)}只；"
        f"5分钟Top100覆盖{summary.get('five_min_top100_count', 0)}只"
    ),
    (
        "- 盘中题材垄断度："
        f"强势股暴露HHI={exposure_hhi.get('hhi', 0)} "
        f"norm={exposure_hhi.get('hhi_norm', 0)} "
        f"级别={exposure_hhi.get('level', '未知')}；"
        f"Top1={float(exposure_hhi.get('top1_share', 0)):.1%} "
        f"Top3={float(exposure_hhi.get('top3_share', 0)):.1%}；"
        f"score_HHI={score_hhi.get('hhi', 0)}"
    ),
]

if topics:
    lines.append("- 题材共振Top5：")
    for idx, item in enumerate(topics, 1):
        samples = "、".join(
            (s.get("name") or s.get("ts_code") or "") for s in item.get("sample_stocks", [])[:4]
        )
        lines.append(
            f"  {idx}. {item.get('topic')} score={item.get('score')} "
            f"stocks={item.get('stock_count')} limit={item.get('limit_up_threshold_count')} "
            f"sources={','.join(item.get('sources', []))} 样本={samples}"
        )
else:
    lines.append("- 题材共振Top5：暂无可确认共振")

lines.extend(
    [
        f"- 数据源状态：{'; '.join(status_bits)}",
        "- 边界：盘中realtime只服务intraday workflow；ai-interest-topic-pipeline继续用收盘后limit_list_d。",
        f"- 归档：JSON={jpath} | MD={mpath}",
    ]
)
print("\n".join(lines))
PY
)"

REPORT_PATH="${JSON_PATH%.json}.report.md"
LATEST_REPORT="/home/ubuntu/.openclaw/workspace/runs/data-yichu-source-layer-intraday/latest-report.md"
printf '%s\n' "$SUMMARY" > "$REPORT_PATH"
cp "$REPORT_PATH" "$LATEST_REPORT"

SEND_STATUS="ok"
SEND_DETAIL=""
if ! SEND_OUT="$("${OPENCLAW_CMD[@]}" message send --channel feishu --target "$FEISHU_TARGET" --message "$SUMMARY" 2>&1)"; then
  SEND_STATUS="direct_failed"
  SEND_DETAIL="$SEND_OUT"
  HUMPHREY_PROMPT="$(cat <<EOF
请用宏观一处日报同一条 Humphrey 飞书推送链路，把下面这份“数据一处｜盘中题材共振汇报”原文发送给 Prime Minister。

要求：
- 直接发送正文，不要改写数字，不要增加后台过程解释。
- 如果需要一句前缀，只写“盘中题材共振快照如下：”。
- 发送对象：$HUMPHREY_TARGET。

正文：
$SUMMARY
EOF
)"
  if HUMPHREY_OUT="$("${OPENCLAW_CMD[@]}" agent \
      --agent main \
      --channel feishu \
      --message "$HUMPHREY_PROMPT" \
      --deliver \
      --reply-channel feishu \
      --reply-to "$HUMPHREY_TARGET" \
      --timeout 600 2>&1)"; then
    SEND_STATUS="humphrey_ok"
    SEND_DETAIL="$SEND_DETAIL"$'\n'"fallback: $HUMPHREY_OUT"
  else
    SEND_STATUS="humphrey_failed"
    SEND_DETAIL="$SEND_DETAIL"$'\n'"fallback: $HUMPHREY_OUT"
  fi
fi

{
  printf '\n- 通知发送：%s\n' "$SEND_STATUS"
  if [[ "$SEND_STATUS" != "ok" ]]; then
    printf -- '- 通知异常：%s\n' "$SEND_DETAIL"
  fi
  printf -- '- 本地汇报：%s\n' "$REPORT_PATH"
  printf -- '- 最新汇报：%s\n' "$LATEST_REPORT"
} >> "$REPORT_PATH"
cp "$REPORT_PATH" "$LATEST_REPORT"

printf '%s\n' "$SUMMARY"
printf '\n通知发送：%s\n' "$SEND_STATUS"
if [[ "$SEND_STATUS" != "ok" ]]; then
  printf '通知异常：%s\n' "$SEND_DETAIL"
fi
printf '本地汇报：%s\n' "$REPORT_PATH"
