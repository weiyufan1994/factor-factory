#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="/home/ubuntu/.openclaw/workspace"
PYTHON_BIN="/home/ubuntu/miniconda3/envs/rdagent/bin/python"
REPORTER="$WORKSPACE/scripts/report_topic_liquidity_dragon_candidates.py"
FEISHU_TARGET="chat:oc_c9d1a01e479bf4292208b5d46a94a0d8"
HUMPHREY_TARGET="user:ou_b1a819365266bc4b91224ec75b91359a"
OPENCLAW_CMD=(sudo -u ubuntu -H openclaw)

cd "$WORKSPACE"

OUT="$("$PYTHON_BIN" "$REPORTER" "$@")"
JSON_PATH="$(printf '%s\n' "$OUT" | awk -F'JSON: ' '/^JSON: / {print $2}' | tail -n 1)"
MD_PATH="$(printf '%s\n' "$OUT" | awk -F'MD: ' '/^MD: / {print $2}' | tail -n 1)"

if [[ -z "${JSON_PATH:-}" || -z "${MD_PATH:-}" ]]; then
  echo "failed to parse dragon report paths" >&2
  printf '%s\n' "$OUT" >&2
  exit 1
fi

SUMMARY="$(cat "$MD_PATH")"

SEND_STATUS="ok"
SEND_DETAIL=""
if ! SEND_OUT="$("${OPENCLAW_CMD[@]}" message send --channel feishu --target "$FEISHU_TARGET" --message "$SUMMARY" 2>&1)"; then
  SEND_STATUS="direct_failed"
  SEND_DETAIL="$SEND_OUT"
  HUMPHREY_PROMPT="$(cat <<EOF
请用宏观一处日报同一条 Humphrey 飞书推送链路，把下面这份“宏观一处｜题材资金龙头交易日报”原文发送给 Prime Minister。

要求：
- 直接发送正文，不要改写数字，不要增加后台过程解释。
- 如果需要一句前缀，只写“题材资金龙头交易日报如下：”。
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
  printf -- '- JSON：%s\n' "$JSON_PATH"
  printf -- '- MD：%s\n' "$MD_PATH"
} >> "$MD_PATH"

printf '%s\n' "$SUMMARY"
printf '\n通知发送：%s\n' "$SEND_STATUS"
if [[ "$SEND_STATUS" != "ok" ]]; then
  printf '通知异常：%s\n' "$SEND_DETAIL"
fi
printf '本地汇报：%s\n' "$MD_PATH"
