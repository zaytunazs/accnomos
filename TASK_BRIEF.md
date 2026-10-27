# Task: Security & robustness pass on the runtime and relay (no new features)

Accnomos monorepo (public; UK English; no secrets). Read `services/runtime/app/**`, `services/hmrc-relay/relay/**`, `deploy/**`,
`docs/HMRC.md`, `docs/ARCHITECTURE.md` (if present). Threat model: public API on api.accnomos.com fronted by nginx; per-request user tokens;
no server state; BYO AI key passed in headers.

## Deliverables (each with a test or a documented check)
1. Token handling: never log `X-Graph-Token`, `X-Meta-Api-Key`, `X-HMRC-Access-Token` (scrub in logging filters and error responses);
   reject tokens > 8 KB; require `Authorization`-style headers only over HTTPS when `X-Forwarded-Proto` is present.
2. Request limits: body size caps per route (uploads 25 MB, JSON 256 KB), per-IP rate limit (simple in-memory token bucket, e.g. 60/min,
   with `Retry-After`), timeouts on all outbound HTTP (Graph, Meta, Ollama, HMRC), and a global exception handler that returns a safe
   JSON error with a correlation id (no stack traces).
3. CORS: exact origins from env only; no wildcard; preflight cached. Security headers on the edge nginx (HSTS, nosniff, referrer policy,
   permissions policy) and on the static site `.htaccess`.
4. Input validation: VRN format, period keys, file names (no path traversal into the user's folder: reject `..`, control chars, absolute
   paths), JSON schema strictness on every POST.
5. Relay: state token TTL (10 min), one-time use, constant-time compare; redirect allow-list already exists — add tests for bypass attempts.
6. Docker: non-root user, read-only filesystem where possible, healthchecks, pinned base images; `deploy/README.md` with the hardening list.
7. `docs/SECURITY.md`: what is protected, what is out of scope for the hackathon, how to report.
Commit in small steps; do not push. Finish with `git log --oneline -8` and the list of findings you could not fix.
