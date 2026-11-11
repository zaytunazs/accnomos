# Speech-to-text eval (2026-10-29T16:21:57+00:00)

| Provider | Model | Clips | Failures | Corpus WER | Mean WER | Numbers right | Amounts right | Latency mean / p50 / p95 |
|---|---|---|---|---|---|---|---|---|
| The speech-to-text model | `muse-voice-transcribe-1.0` | 14 | 0 | 0.1269 | 0.1669 | 50.0 % | n/a | 1.714 / 1.707 / 2.436 s |

Not configured, so not run: the local speech-to-text fallback.

## Number misses and failures

- `teaser/t1_08` muse: 'Echnomos launching November 2026.' (said: 'Accnomos. Launching November twenty twenty-six.')
- `teaser/t2_06` muse: 'Egnomos, launching November 2026.' (said: 'Accnomos. Launching November twenty twenty-six.')

Synthetic speech from an open-source voice model, one clean voice per clip: real phone audio will score worse. See harness/stt.py.
