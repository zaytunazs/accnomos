#!/usr/bin/env bash
# Sets the non-secret relay values in the Spark deploy .env (secrets are left for the owner).
set -e
cd ~/spark/accnomos/deploy-repo
ip=$(curl -s --max-time 8 https://api.ipify.org)
grep -q '^RELAY_PUBLIC_IP=' .env && sed -i "s|^RELAY_PUBLIC_IP=.*|RELAY_PUBLIC_IP=$ip|" .env || echo "RELAY_PUBLIC_IP=$ip" >> .env
grep -q '^HMRC_VENDOR_VERSION=' .env || echo "HMRC_VENDOR_VERSION=0.1.0" >> .env
grep -E '^(RELAY_PUBLIC_IP|HMRC_VENDOR_VERSION|HMRC_CLIENT_ID)=' .env | sed -E 's/(HMRC_CLIENT_ID=).+/\1<set>/'
docker compose ps --format '{{.Name}} {{.Status}}' || sudo docker compose ps
