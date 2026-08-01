#!/usr/bin/env bash
set -euo pipefail

NETWORK_NAME="${FACTORFORGE_CONSOLE_CONTAINER_NETWORK:-factorforge-console-egress}"
NETWORK_SUBNET="${FACTORFORGE_CONSOLE_CONTAINER_NETWORK_SUBNET:-172.29.0.0/24}"

if ! docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
  docker network create \
    --driver bridge \
    --subnet "${NETWORK_SUBNET}" \
    --opt com.docker.network.bridge.enable_ip_masquerade=true \
    "${NETWORK_NAME}" >/dev/null
fi

actual_subnet="$(docker network inspect "${NETWORK_NAME}" --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}')"
ipv6_enabled="$(docker network inspect "${NETWORK_NAME}" --format '{{.EnableIPv6}}')"
internal_network="$(docker network inspect "${NETWORK_NAME}" --format '{{.Internal}}')"
if [[ "${actual_subnet}" != "${NETWORK_SUBNET}" || "${ipv6_enabled}" != "false" || "${internal_network}" != "false" ]]; then
  echo "Factor Forge Console network metadata does not match the required policy" >&2
  exit 1
fi

blocked_destinations=(
  0.0.0.0/8
  10.0.0.0/8
  100.64.0.0/10
  127.0.0.0/8
  169.254.0.0/16
  172.16.0.0/12
  192.0.0.0/24
  192.0.2.0/24
  192.168.0.0/16
  198.18.0.0/15
  198.51.100.0/24
  203.0.113.0/24
  224.0.0.0/4
  240.0.0.0/4
)

for destination in "${blocked_destinations[@]}"; do
  rule=(-s "${NETWORK_SUBNET}" -d "${destination}" -j REJECT)
  if ! iptables -w 5 -C DOCKER-USER "${rule[@]}" 2>/dev/null; then
    iptables -w 5 -I DOCKER-USER 1 "${rule[@]}"
  fi
done

# Fail closed if any required rule is absent after reconciliation.
for destination in "${blocked_destinations[@]}"; do
  iptables -w 5 -C DOCKER-USER -s "${NETWORK_SUBNET}" -d "${destination}" -j REJECT
done
