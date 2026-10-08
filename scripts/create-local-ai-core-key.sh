#!/usr/bin/env bash
# create-local-ai-core-key.sh — grava .env.aicore (AICORE_SERVICE_KEY) na raiz deste projeto, para o passo
# `spa-extract format` usar o Claude no SAP AI Core. Mesmo AI Core das outras POCs (subaccount dev-ai-l2d, instância
# ai-core-integration-hub, resource group default).
#
# Quem roda: uma PESSOA, no próprio terminal, com `cf login` feito e acesso ao space `dev` da org de IA (o agente de
# código nunca roda — ele não manipula credenciais). Nada é impresso: a credencial vai direto para o arquivo, criado com
# permissão 600. O arquivo está no .gitignore (.env*): só o processo do formatter o lê,
# nunca entra no git. Ao terminar, o cf volta para o org/space em que estava.
#
# Uso:  scripts/create-local-ai-core-key.sh
# Opcionais: --ai-org "Lab2Dev Solucoes em Technologia Ltda_dev-ai-l2d" --ai-space dev
#            --ai-instance ai-core-integration-hub --ai-key spa-content-extractor-local
# Para revogar: cf delete-service-key ai-core-integration-hub spa-content-extractor-local (no space da org de IA) e
# apague .env.aicore.
set -euo pipefail
set +x # nunca ecoar comandos: há segredo em variável

AI_ORG="Lab2Dev Solucoes em Technologia Ltda_dev-ai-l2d"
AI_SPACE="dev"
AI_INSTANCE="ai-core-integration-hub" # resource group default: deployment de Orchestration db713ca009933568
AI_KEY="spa-content-extractor-local"
OUT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.env.aicore"

while [ $# -gt 0 ]; do
  case "$1" in
    --ai-org) AI_ORG="$2"; shift 2 ;;
    --ai-space) AI_SPACE="$2"; shift 2 ;;
    --ai-instance) AI_INSTANCE="$2"; shift 2 ;;
    --ai-key) AI_KEY="$2"; shift 2 ;;
    *) echo "argumento desconhecido: $1" >&2; exit 1 ;;
  esac
done
for bin in cf jq; do command -v "$bin" >/dev/null || { echo "precisa de $bin instalado" >&2; exit 1; }; done

ORIG_ORG=$(cf target | awk -F': *' '/^org:/{print $2}')
ORIG_SPACE=$(cf target | awk -F': *' '/^space:/{print $2}')
restore() { [ -n "$ORIG_ORG" ] && [ -n "$ORIG_SPACE" ] && cf target -o "$ORIG_ORG" -s "$ORIG_SPACE" >/dev/null 2>&1 || true; }
trap restore EXIT

echo "==> 1/2 service key '$AI_KEY' em '$AI_INSTANCE' ($AI_ORG / $AI_SPACE)"
cf target -o "$AI_ORG" -s "$AI_SPACE" >/dev/null
GUID=$(cf service "$AI_INSTANCE" --guid)
[ -n "$GUID" ] || { echo "instância '$AI_INSTANCE' não encontrada" >&2; exit 1; }
if ! cf service-key "$AI_INSTANCE" "$AI_KEY" >/dev/null 2>&1; then
  cf create-service-key "$AI_INSTANCE" "$AI_KEY" --wait >/dev/null
  echo "    criada"
else
  echo "    já existia"
fi
BINDING=$(cf curl "/v3/service_credential_bindings?names=$AI_KEY&service_instance_guids=$GUID" | jq -r '.resources[0].guid // empty')
[ -n "$BINDING" ] || { echo "chave '$AI_KEY' não encontrada" >&2; exit 1; }

echo "==> 2/2 gravando $OUT (permissão 600, sem exibir o conteúdo)"
umask 077
CREDS=$(cf curl "/v3/service_credential_bindings/$BINDING/details" | jq -c '.credentials')
# confere o formato da chave do AI Core sem mostrar nada
jq -e '.clientid and .clientsecret and .url and .serviceurls.AI_API_URL' >/dev/null <<<"$CREDS" \
  || { unset CREDS; echo "a chave não tem o formato esperado do AI Core (clientid, clientsecret, url, serviceurls.AI_API_URL)" >&2; exit 1; }
case "$CREDS" in *"'"*) unset CREDS; echo "a chave tem aspas simples: não dá para gravar no formato do env_file" >&2; exit 1 ;; esac
printf "# gerado por service/scripts/create-local-ai-core-key.sh — NÃO versionar, NÃO compartilhar\nAICORE_SERVICE_KEY='%s'\n" "$CREDS" > "$OUT"
unset CREDS
chmod 600 "$OUT"
echo "==> pronto: $(wc -c <"$OUT" | tr -d ' ') bytes em $OUT. Rode: uv run spa-extract format output/<host>/<data>"
