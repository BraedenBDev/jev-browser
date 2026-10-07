#!/bin/sh
# Run a command with jev's OpenRouter access, through the Agent Vault broker.
# Inside a Hermes job the session env (AGENT_VAULT_TOKEN/ADDR) is already present.
# Run standalone (e.g. a manual test from an SSH shell) and this borrows the live
# session from the running hermes-gateway unit so `agent-vault run` can authenticate.
# The token is only exported into this process; it is never written to disk.
set -u
if [ -z "${AGENT_VAULT_TOKEN:-}" ]; then
    G=$(systemctl --user show -p MainPID --value hermes-gateway.service 2>/dev/null)
    if [ -n "$G" ] && [ "$G" != "0" ] && [ -r "/proc/$G/environ" ]; then
        # Assign directly (no eval): a value with shell metacharacters must not be executed.
        while IFS='=' read -r k v; do
            [ -n "$k" ] && export "$k=$v"
        done <<EOF
$(tr '\0' '\n' < "/proc/$G/environ" | grep -E '^AGENT_VAULT_(TOKEN|ADDR|VAULT)=')
EOF
    fi
fi
AV="${AV_BIN:-/usr/local/bin/agent-vault}"
FIN="$HOME/.hermes/scripts/agent-vault/finish_env.sh"
exec "$AV" run -- "$FIN" "$@"
