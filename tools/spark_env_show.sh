#!/usr/bin/env bash
cd ~/spark/accnomos/deploy-repo || exit 1
grep -E '^(HMRC_|RELAY_|CORS|OLLAMA|MODEL)' .env | sed -E 's/(SECRET|KEY)=.*/\1=<hidden>/'
echo "--- public ip:"
curl -s --max-time 8 https://api.ipify.org; echo
echo "--- compose:"
docker compose ps --format '{{.Name}} {{.Status}}' 2>/dev/null
