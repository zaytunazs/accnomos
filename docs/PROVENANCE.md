# Provenance: what existed before the hackathon, and when everything else was made

The hackathon FAQ asks that the repository holds only work done during the event, and that the demo video opens with one
line on anything that pre-existed. This page is the evidence for both. Every timestamp below was read from `git log` on a
full (unshallowed) clone and from `gh api repos/zaytunazs/accnomos` on 28 Oct 2026; the commands are at the end so anyone
can re-run them.

**The one line for the video:** *"Before the hackathon I had only my DGX Spark with Ollama installed. Every line of
Accnomos, and the Meta model set-up, was made after kickoff on 26 October."*

## Timeline (UTC; UK time was the same that week)

UK clocks went back on Sun 25 Oct, so London was on GMT (UTC+0). US clocks went back on Sun 1 Nov, so during the first
week Eastern Time was EDT (UTC−4).

| Event | Time (UTC) | After kickoff | Source |
|---|---|---|---|
| **Kickoff**: Mon 26 Oct 2026, 12:00 ET | 2026-10-26 16:00 | 0 | Hackathon schedule |
| **First commit** `58ee050` (*Accnomos: monorepo scaffold, Flutter shell, ledger + VAT engine, …*) | 2026-10-26 22:29:35 | +6 h 29 min | `git log --reverse` (author and committer date agree) |
| **GitHub repository created** (`zaytunazs/accnomos`) | 2026-10-26 22:30:57 | +6 h 31 min | `gh api repos/zaytunazs/accnomos` → `created_at` |
| First commit message naming a Meta coding tool and model, `d1ccaae` (*web: app shell + Review inbox … (Muse Code, muse-spark-1.3)*) | 2026-10-26 23:18:34 | +7 h 18 min | `git log -i --grep='Muse Code'` |
| First commit message reporting a live Glimmer run, `8023a01` (*F2: Choose-your-AI screen … tested live against Glimmer on the Spark*) | 2026-10-27 00:09:34 | +8 h 10 min | `git log` |
| Latest commit on `main` when this page was written, `206848c` | 2026-10-28 01:33:20 | +33 h 33 min | `git log -1 origin/main` |
| Submission deadline: Wed 4 Nov 2026, 21:00 ET (EST, UTC−5) | 2026-11-05 02:00 | | Hackathon schedule |

No commit on any branch of the remote has an author or committer date before kickoff; the earliest author date on any ref
is the first commit's, 2026-10-26T22:29:35Z (`git log --all --format='%aI %cI'`, checked 28 Oct).

## The first commit is large, and why

`58ee050` adds **7,146 lines in 70 files**. It was made in the first six hours with coding agents, from an empty folder,
and committed once before the GitHub repository existed (the repository was created 82 seconds later and the commit
pushed into it). What is in it:

- **5,369 of the 7,146 lines (75 %) are lockfiles** written by package managers: `apps/web/pnpm-lock.yaml` (4,172),
  `uv.lock` (992) and `apps/mobile/pubspec.lock` (205).
- 264 lines in 19 files are the Android platform folder from the Flutter project template.
- The rest (about 1,500 lines) is the scaffold the commit message lists: a Flutter shell with four tabs, a Next.js app
  scaffold, the ledger package with a VAT nine-box engine and its tests (`packages/ledger`), the connector interfaces with
  an in-memory fake (`packages/connectors`), and two FastAPI skeletons (`services/runtime` with `/health` and `/ai/test`,
  `services/hmrc-relay` with `/health`).

The commit carries a `Co-Authored-By: Claude` trailer. Its `/ai/test` stub already names the two modes (a Meta key or a
local Glimmer model), but no Meta model had been called by then: the first message reporting a live Glimmer run is
`8023a01`, 8 h 10 min after kickoff.

## What pre-existed

| Item | Pre-existing? | Notes |
|---|---|---|
| The owner's **NVIDIA DGX Spark** and its **Ollama** install | **Yes** | Hardware and a model runtime: infrastructure, not product code. Nothing from it is in the repository. |
| Meta models on that machine (Muse Glimmer 30B), and the Meta-model endpoints Accnomos calls (Meta Model API, Baseten, Modal) | No | Configured after kickoff. |
| Any Accnomos code, design, brand art, data or docs | No | The repository starts at `58ee050`. Brand art was made with Muse Image during the event (`tools/brand_muse.py`). |
| Evaluation data | No | Every gold document, bank statement and mailbox fixture under `evals/` is synthetic and was generated during the event (`evals/harness/`, Qwen on the Spark for some fictional names and text). |
| Third-party open-source libraries | Yes, as dependencies | Pulled in through the lockfiles above (Flutter, Next.js, FastAPI, Pillow and so on); not copied into the repository. |

## Commits per day on `main`

Up to `206848c` (2026-10-28 01:33:20 UTC). Dates are UTC, which was also UK time. "Lines" counts non-merge commits only.

| Day (UTC) | Commits | of which merges | Non-merge | Lines added | Lines removed | Author: Zohaib Sharif | Author: "Claude (Spark)" |
|---|---:|---:|---:|---:|---:|---:|---:|
| Mon 26 Oct (from 22:29) | 7 | 1 | 6 | 12,239 | 140 | 7 | 0 |
| Tue 27 Oct | 966 | 106 | 860 | 196,078 | 18,374 | 477 | 489 |
| Wed 28 Oct (to 01:33) | 29 | 5 | 24 | 1,800 | 167 | 29 | 0 |
| **Total** | **1,002** | **112** | **890** | **210,117** | **18,681** | **513** | **489** |

"Claude (Spark)" is the git identity of the coding agent that ran on the DGX Spark. Commits under Zohaib Sharif's name
include agent-written work too (their `Co-Authored-By` trailers say so; see the next section). Generated files
(lockfiles, eval reports and manifests) are part of the line counts. The table covers `main` only and
will grow until the deadline: re-run the commands below before quoting it.

## How each part was built

Every line was written during the event with coding assistants, directed and reviewed by the owner. The Meta models in
`docs/submission/META_MODELS.md` are what the product *runs*; the assistants below are what *wrote* it.

| Assistant | Used for | Trace in git |
|---|---|---|
| **Claude** (Claude Code, in cloud sessions and on the Spark) | The first scaffold, the runtime, ledger, relay, most tests, evals harness, docs, and the second-agent review of every branch | 655 commits on `main` carry a `Co-Authored-By: Claude` trailer; 57 merges of `claude/*` branches |
| **Muse Code** (Meta, model `muse-spark-1.3`) | Web and Android screens: the Review inbox and app shell, the VAT return page, the Android Review and Ask screens, and later web and Android feature branches | Commit messages naming Muse Code (first: `d1ccaae`, 23:18 on 26 Oct); 54 merges of `muse/*` branches |
| **Qwen** (Qwen3.8-27B, local on the Spark through vLLM) | Synthetic eval data (gold documents 061–200, the `ledger2` gold set) and a second reader in the Ask eval | 9 commit messages naming Qwen (first: `93f1d13`, 03:44 on 27 Oct) |

**Every merge was reviewed.** Each feature branch was read by a second agent before it was merged, and its review is
committed under `docs/reviews/<branch>/REVIEW.md` (54 reviews in 55 folders on 28 Oct; one folder holds only a task brief):
what was checked, what the reviewer fixed, and what remains. The gaps they leave open are collected in `docs/HONESTY.md`.

## Re-run the checks

```bash
git fetch --unshallow origin main 2>/dev/null || git fetch origin main
git log origin/main --reverse --format='%h %aI %cI %an | %s' | head -5            # first commits
gh api repos/zaytunazs/accnomos --jq .created_at                                   # repository creation
git log --all --format='%aI %cI %h' | awk '$1<"2026-10-26T16:00:00" || $2<"2026-10-26T16:00:00"'   # empty = nothing before kickoff
git show --stat 58ee050 | tail -1                                                  # 70 files, 7146 insertions
git show --numstat --format= 58ee050 | awk '$3 ~ /lock/ {a+=$1} END {print a}'     # 5369 lockfile lines
TZ=UTC git log origin/main --format=%cd --date=format-local:%F | sort | uniq -c    # commits per day
TZ=UTC git log origin/main --merges --format=%cd --date=format-local:%F | sort | uniq -c
git log origin/main -i --grep='Muse Code' --reverse --format='%cI %h %s' | head -1
ls docs/reviews/*/REVIEW.md | wc -l
```
