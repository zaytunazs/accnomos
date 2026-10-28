"""Glimmer 30B on Modal (L40S) behind Ollama's HTTP API: the runtime's first AI provider, and an eval backend.

    modal deploy tools/modal_glimmer.py          # prints the URL
    modal app stop accnomos-glimmer              # stop billing at once

Two uses:

* Production / the live demo: the first provider in the runtime's chain (`AI_PROVIDERS=modal,meta,spark`,
  app/ai/providers.py). Set MODAL_GLIMMER_URL on the runtime to the printed URL (shape:
  https://<workspace>--accnomos-glimmer-serve.<region>.modal.run). Deploy it with proxy auth (below) so only the
  runtime can call it, and set MODAL_PROXY_TOKEN_ID / MODAL_PROXY_TOKEN_SECRET on the runtime.
* Evals: set OLLAMA_BASE to the URL for an eval run (evals/runs/glimmer_200_v2 ran this way).

The model is pulled once from Ollama's public registry into a Modal Volume and reused, so a cold start reads ~18 GB
from the volume, not the internet (60-120 s before the first reply; the runtime allows MODAL_FIRST_TOKEN_S=150 for
it). The container shuts down after SCALEDOWN_S idle seconds, so an idle deployment costs nothing. Keep a usage
limit on Modal's Usage & Billing page; this file sets no budget itself.

Deploy-time options (environment of the `modal deploy` command, not of the runtime):

* MODAL_PROXY_AUTH=1  -> `requires_proxy_auth=True`: every request needs a Modal proxy-auth token (create one under
  the workspace's Settings -> Proxy Auth Tokens), sent as the `Modal-Key` and `Modal-Secret` headers; without them
  Modal answers 401 before any GPU starts. Without this option the URL is open to anyone who knows it (it is the
  workspace and app name, not a secret), so deploy without it only for a short eval run.
* MODAL_KEEP_WARM=08:00-18:00 -> keep one container up (min_containers=1) inside that daily window, so nobody waits
  for a cold start; outside it the app scales to zero as usual. MODAL_KEEP_WARM_TZ (default Europe/London) and
  MODAL_KEEP_WARM_DAYS (cron day-of-week, default `*`; e.g. `1-5` for weekdays) refine it. Two scheduled CPU-only
  functions switch the floor with `Function.autoscaler.update(min_containers=...)` (Modal's documented pattern for a
  time-of-day warm pool, modal.com/docs/guide/scale). A redeploy resets the floor to 0 until the next switch-on.
  Cost while warm: the L40S is $0.000542/s = $1.95/h on Modal's price list (modal.com/pricing, checked 28 Oct 2026),
  plus CPU at $0.0000131/core/s and memory at $0.00000222/GiB/s, a few cents an hour for this container: about
  $2.00/h, so a 10-hour window is about $20 a day. Requests inside the window are not charged extra (the container
  is already billed); the runtime's POST /ai/warm is the cheaper alternative (one cold start when someone opens the
  app, then SCALEDOWN_S of idle billing).
"""

from __future__ import annotations

import os
import subprocess
import time

import modal

APP = "accnomos-glimmer"
MODEL = "muse-glimmer:30b"
OLLAMA_VERSION = os.environ.get("OLLAMA_VERSION", "0.40.8")  # as on the DGX Spark; the model needs 0.32.8 or newer
GPU = "L40S"  # 48 GB: the 18 GB Q4_K_M model plus room for 4 parallel requests
PARALLEL = 4
SCALEDOWN_S = 300
PORT = 11434
PROXY_AUTH = os.environ.get("MODAL_PROXY_AUTH") == "1"
KEEP_WARM = os.environ.get("MODAL_KEEP_WARM", "").strip()  # "HH:MM-HH:MM", or empty for scale-to-zero only
KEEP_WARM_TZ = os.environ.get("MODAL_KEEP_WARM_TZ", "Europe/London")
KEEP_WARM_DAYS = os.environ.get("MODAL_KEEP_WARM_DAYS", "*")


def keep_warm_crons(window: str, days: str = "*") -> tuple[str, str]:
    """("start cron", "stop cron") for an "HH:MM-HH:MM" window, e.g. ("0 8 * * *", "0 18 * * *")."""
    start, _, stop = window.partition("-")
    out = []
    for hhmm in (start, stop):
        h, _, m = hhmm.strip().partition(":")
        if not (h.isdigit() and m.isdigit() and int(h) < 24 and int(m) < 60):
            raise ValueError(f"MODAL_KEEP_WARM must look like 08:00-18:00, not {window!r}")
        out.append(f"{int(m)} {int(h)} * * {days}")
    return out[0], out[1]


volume = modal.Volume.from_name("accnomos-ollama-models", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("curl", "ca-certificates", "zstd")
    .run_commands(f"curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION={OLLAMA_VERSION} sh")
    .env(
        {
            "OLLAMA_MODELS": "/models",
            "OLLAMA_HOST": f"0.0.0.0:{PORT}",
            "OLLAMA_NUM_PARALLEL": str(PARALLEL),
            "OLLAMA_KEEP_ALIVE": "-1",
            "OLLAMA_MAX_LOADED_MODELS": "1",
        }
    )
)
app = modal.App(APP, image=image)


@app.function(
    gpu=GPU,
    volumes={"/models": volume},
    scaledown_window=SCALEDOWN_S,
    timeout=24 * 3600,
    max_containers=1,
)
@modal.concurrent(max_inputs=64)
@modal.web_server(PORT, startup_timeout=1800, requires_proxy_auth=PROXY_AUTH)
def serve() -> None:
    subprocess.Popen(["ollama", "serve"])
    for _ in range(120):  # wait for the server
        try:
            subprocess.run(["ollama", "list"], check=True, capture_output=True)
            break
        except subprocess.CalledProcessError:
            time.sleep(1)
    listed = subprocess.run(["ollama", "list"], capture_output=True, text=True).stdout
    if MODEL not in listed:
        subprocess.run(["ollama", "pull", MODEL], check=True)
        volume.commit()
    # Load it into GPU memory before the first request arrives.
    subprocess.run(["ollama", "run", MODEL, "--keepalive", "-1", "ok"], check=False, capture_output=True)


def _set_floor(n: int) -> None:
    fn = modal.Function.from_name(APP, "serve")
    if hasattr(fn, "autoscaler"):  # current SDK (modal.com/docs/guide/scale)
        fn.autoscaler.update(min_containers=n)
    else:  # older SDKs
        fn.update_autoscaler(min_containers=n)


if KEEP_WARM:
    _on, _off = keep_warm_crons(KEEP_WARM, KEEP_WARM_DAYS)

    @app.function(schedule=modal.Cron(_on, timezone=KEEP_WARM_TZ), gpu=None)
    def keep_warm_on() -> None:
        """Start of the window: one Glimmer container stays up (about $2.00/h, see the module doc)."""
        _set_floor(1)

    @app.function(schedule=modal.Cron(_off, timezone=KEEP_WARM_TZ), gpu=None)
    def keep_warm_off() -> None:
        """End of the window: back to scale-to-zero."""
        _set_floor(0)
