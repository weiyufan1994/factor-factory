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
proxy_gateway="$(docker network inspect "${NETWORK_NAME}" --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}')"
expected_gateway="$(python3 -c 'import ipaddress, sys; print(ipaddress.ip_network(sys.argv[1], strict=True).network_address + 1)' "${NETWORK_SUBNET}")"
if [[ "${actual_subnet}" != "${NETWORK_SUBNET}" || "${ipv6_enabled}" != "false" || "${internal_network}" != "false" ]]; then
  echo "Factor Forge Console network metadata does not match the required policy" >&2
  exit 1
fi

if [[ "${proxy_gateway}" != "${expected_gateway}" ]]; then
  echo "Factor Forge Console proxy gateway does not match the required policy" >&2
  exit 1
fi

chain="FF_CONSOLE_EGRESS"
iptables -w 5 -N "${chain}" 2>/dev/null || true
iptables -w 5 -F "${chain}"
iptables -w 5 -A "${chain}" -d "${proxy_gateway}/32" -p tcp --dport 3128 -j ACCEPT
iptables -w 5 -A "${chain}" -j REJECT

while iptables -w 5 -C DOCKER-USER -s "${NETWORK_SUBNET}" -j "${chain}" 2>/dev/null; do
  iptables -w 5 -D DOCKER-USER -s "${NETWORK_SUBNET}" -j "${chain}"
done
iptables -w 5 -I DOCKER-USER 1 -s "${NETWORK_SUBNET}" -j "${chain}"

# Fail closed if the only allowed route is the host proxy.
iptables -w 5 -C DOCKER-USER -s "${NETWORK_SUBNET}" -j "${chain}"
iptables -w 5 -C "${chain}" -d "${proxy_gateway}/32" -p tcp --dport 3128 -j ACCEPT
iptables -w 5 -C "${chain}" -j REJECT
