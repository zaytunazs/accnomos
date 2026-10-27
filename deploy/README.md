# deploy/

Demo deployment of the two stateless services behind one hostname, `api.accnomos.com`:

```
Internet ─TLS─▶ front proxy (Plesk nginx or cloudflared) ─▶ tunnel ─▶ 127.0.0.1:8790 ─▶ edge (nginx :8080)
                                                                         ├─ /hmrc/*, /vat/*  ─▶ relay   :8787
                                                                         └─ everything else  ─▶ runtime :8780
```

```sh
docker compose -f deploy/docker-compose.yml --env-file .env up -d --build
docker compose -f deploy/docker-compose.yml ps        # all three should show (healthy)
```

`.env` holds the HMRC credentials and is never committed. What the services do with requests (token
handling, limits, validation) is in [`docs/SECURITY.md`](../docs/SECURITY.md).

## Hardening checklist

Each item is checked by `services/runtime/tests/test_deploy_hardening.py` unless marked *manual*.

**Containers** (`docker-compose.yml`, `Dockerfile.*`)
- [x] Pinned base images: `python:3.12.7-slim-bookworm`, `nginxinc/nginx-unprivileged:1.27.2-alpine`.
      *Manual:* also pin by digest (`image@sha256:…`) when you deploy, and bump on security releases.
- [x] Non-root: the Python images run as uid 10001 (`USER 10001:10001`); the edge uses nginx-unprivileged.
- [x] Read-only root filesystem everywhere; writable `tmpfs` `/tmp` only (runtime 256 MB for upload spooling and
      ffmpeg, relay 16 MB, edge 64 MB for nginx buffers and its pid file).
- [x] `cap_drop: [ALL]`, `no-new-privileges`, `pids_limit: 256`.
- [x] Healthchecks: runtime and relay `GET /health`; edge `GET /nginx-health`. The edge starts only once both
      services are healthy.
- [x] Ports bound to `127.0.0.1` only; the public path is the tunnel. Never port-forward.
- [x] Relay runs one uvicorn worker (one-time OAuth state uses an in-memory spent set).
- [x] `--no-server-header`; nginx `server_tokens off`, upstream `Server` / `X-Powered-By` hidden.

**Edge nginx** (`nginx.conf`)
- [x] On every response, errors included: `Strict-Transport-Security` (1 year, subdomains), `X-Content-Type-Options:
      nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy` (camera, microphone, geolocation, payment, usb
      off), `X-Frame-Options: DENY`, `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`.
- [x] No `add_header` inside a `location` (it would silently drop the server-level headers there).
- [x] Body caps: 256 KB everywhere, 25 MB on `/extract`, `/books/ask/voice`, `/books/bank/import`. The services
      enforce the same caps themselves.
- [x] Client address: the **last** `X-Forwarded-For` hop (the one the front proxy appended), never the raw
      client-supplied chain and never `CF-Connecting-IP`, which the edge strips. Used for HMRC fraud headers and rate limits.
- [x] `X-Forwarded-Proto` passed through from the front proxy (absent → `https`), so the services can refuse
      credentials sent over plain HTTP.
- [x] Timeouts: connect 5 s; read 60 s (relay) / 300 s (runtime, model calls); client header 15 s, body 30 s.

**Static site** (`apps/web/public/.htaccess`)
- [x] HSTS (only when served over TLS), `nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`,
      `Permissions-Policy` (camera and microphone for the app itself only), `X-Frame-Options: DENY`,
      `Content-Security-Policy: frame-ancestors 'none'; base-uri 'self'; object-src 'none'`.
- [x] `Cache-Control`: `public, max-age=31536000, immutable` for `/_next/static/` (content-hashed); `no-cache`
      for HTML and everything else, so a deploy is seen at once.

**Configuration** (environment)
- [x] `CORS_ORIGINS` (runtime) and `RELAY_ALLOWED_REDIRECTS` (relay): exact origins, no wildcards; the runtime
      refuses to start with `*` or a path in `CORS_ORIGINS`.
- [x] `AI_ALLOWED_BASE_URLS`: the only AI endpoints a browser may point the runtime at (besides `OLLAMA_BASE` and
      `MODEL_API_BASE`).
- [x] `RATE_LIMIT_PER_MIN` (both services, default 60 per IP).
- *Manual:* the front proxy must append the client address to `X-Forwarded-For` (Plesk: `$proxy_add_x_forwarded_for`)
  and set `X-Forwarded-Proto`; it must also redirect HTTP to HTTPS.

## Checking a running deployment (*manual*)

```sh
curl -sI https://api.accnomos.com/health | grep -iE 'strict-transport|nosniff|referrer|permissions|x-correlation-id'
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://api.accnomos.com/ai/test \
  -H 'Content-Type: application/json' --data-binary @<(head -c 300000 /dev/zero | tr '\0' ' ')   # 413
docker inspect --format '{{.Config.User}} {{.HostConfig.ReadonlyRootfs}}' $(docker compose -f deploy/docker-compose.yml ps -q)
```
