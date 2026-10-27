"""Glimmer 30B on Modal (L40S) behind Ollama's HTTP API, for running evals in parallel with the DGX Spark.

    modal deploy tools/modal_glimmer.py          # prints the URL; set OLLAMA_BASE to it for an eval run
    modal app stop accnomos-glimmer              # stop billing at once when the run is done

Not part of the app or its runtime: an operator tool for evals only. The model is pulled once from Ollama's public
registry into a Modal Volume and reused, so a cold start reads ~18 GB from the volume, not the internet. The
container shuts down after SCALEDOWN_S idle seconds, so an idle deployment costs nothing. Keep the workspace spend
limit at $0 (no card charges) and a usage limit on Modal's Usage & Billing page; this file sets no budget itself.
The URL is not secret (it is the workspace and app name), so the app is deployed only for an eval run and stopped
right after it; the workspace usage limit caps what a stranger could spend in that window.
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
@modal.web_server(PORT, startup_timeout=1800)
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
