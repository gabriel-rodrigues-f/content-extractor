#!/usr/bin/env bash
# Painel do lote: o que está rodando e quanto já foi, a partir do STATUS.md e dos logs. Atualiza a cada 30 s.
# Uso: bash scripts/painel.sh [pasta do staging]   (Ctrl-C para sair)
RAW="${1:-$HOME/Documents/30-resources/32-tech-vault/_staging/raw}"
STATUS="$RAW/STATUS.md"
while true; do
  clear
  date '+%H:%M:%S'
  echo "feitos: $(grep -c '^- \[x\]' "$STATUS") | rodando: $(grep -c '^- \[>\]' "$STATUS") | pendentes: $(grep -c '^- \[ \]' "$STATUS") | falhas: $(grep -c '^- \[!\]' "$STATUS") | fila: $(grep -c '^- \[~\]' "$STATUS")"
  echo
  echo "RODANDO AGORA (páginas ok / erros até aqui):"
  ls -t "$RAW"/.logs/*.log 2>/dev/null | head -12 | while read -r log; do
    if grep -q "item(ns) extraído(s)" "$log"; then continue; fi  # já terminou
    printf '  %-60s %5s ok  %3s erro\n' "$(basename "$log" .log | cut -c1-60)" "$(grep -c '✓' "$log")" "$(grep -c '✗' "$log")"
  done
  echo
  echo "TERMINADOS POR ÚLTIMO:"
  grep '^- \[[x!]\]' "$STATUS" | tail -5 | sed -E 's/^- \[(.)\] ([^ ]+).* — ([0-9]+\/[0-9]+ lições).*/  [\1] \3  \2/' | cut -c1-130
  sleep 30
done
