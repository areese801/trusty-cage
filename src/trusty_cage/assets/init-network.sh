#!/usr/bin/env bash
################################################################################
# init-network.sh — Apply network policy for trusty-cage containers
#
# Blocks:
#   - Port 22 (SSH) outbound to all hosts
#   - hub.docker.com and registry-1.docker.io (resolved via getent)
#
# Allows:
#   - Everything else (HTTPS git, packages, web, DNS)
#
# Must be run as root. Idempotent — uses iptables -C before adding rules.
#
# USAGE:
#   bash /tmp/init-network.sh
################################################################################

set -euo pipefail

# --- Helpers ---

add_rule_if_missing() {
    local table="$1"
    shift
    # Check if rule exists; if not, append it
    if ! iptables -t "${table}" -C "$@" 2>/dev/null; then
        iptables -t "${table}" -A "$@"
    fi
}

add_rule6_if_missing() {
    local table="$1"
    shift
    if ! ip6tables -t "${table}" -C "$@" 2>/dev/null; then
        ip6tables -t "${table}" -A "$@"
    fi
}

# --- Block port 22 outbound (SSH) ---

add_rule_if_missing filter OUTPUT -p tcp --dport 22 -j DROP
add_rule6_if_missing filter OUTPUT -p tcp --dport 22 -j DROP

# --- Block Docker Hub / registry ---

DOCKER_HOSTS="hub.docker.com registry-1.docker.io"

for host in ${DOCKER_HOSTS}; do
    # Resolve IPv4 addresses via getent
    ips=$(getent ahosts "${host}" 2>/dev/null | awk '{print $1}' | sort -u) || true
    for ip in ${ips}; do
        # Skip IPv6 addresses for iptables (handled by ip6tables)
        if echo "${ip}" | grep -q ':'; then
            add_rule6_if_missing filter OUTPUT -d "${ip}" -j DROP
        else
            add_rule_if_missing filter OUTPUT -d "${ip}" -j DROP
        fi
    done
done

echo "Network policy applied."
