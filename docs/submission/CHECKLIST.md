# Owner checklist: what only you can do before submitting

Deadline: **Wed 4 Nov 2026, 21:00 ET** = **02:00 UK time on Thu 5 Nov** (US clocks went back on 1 Nov, so ET is EST,
UTC−5; UK is on GMT). Aim to submit by **Wed 4 Nov, 18:00 UK time** so there is slack.
Refreshed 4 Nov 2026, 11:30 UK, by the final audit (`docs/reviews/final-audit-4nov/REPORT.md`). `[x]` = done with a record in
the repo or checked live by the audit; `[ ]` is still yours. Order: 8 (secrets), 9 (deploy and last checks), 5 (video), 7 (form).
**The repository is already public** (`gh api repos/zaytunazs/accnomos` → `"visibility": "public"`, checked 28 Oct), so
run the secrets check in section 8 now, not last.

## 1. Android: Play upload and a real-phone run

- [x] Entra holds the Play app-signing key's MSAL hash (27 Oct); release builds from 0.3.1+4 carry it.
- [x] `flutter analyze` and `flutter test` run green in CI on every push (`main` at `8debc2e9`, 4 Nov).
- [x] **APK 0.3.19+24 published** as a GitHub release (`android-0.3.19-24`, 4 Nov 13:20 UTC; the link in the README and
      JUDGING.md resolves). The audit installed 0.3.18+23 on the emulator and walked Welcome → Try the company demo → Home,
      Review, Ask, VAT, More › Bank, Settings; 0.3.19 adds the Home goals and AI cards, the duplicates card fix and Bank sync.
- [ ] **Play Console:** the listing is in Google's review. If you upload again, build from `apps/mobile/pubspec.yaml`
      (**0.3.19+24**; bump first) with `tools/build_release.ps1`, paste the "What's new" text from
      `apps/mobile/RELEASE_NOTES.md`. Not needed for the submission: the APK is the judges' path.
- [ ] **Write the real Play status into the form on the day** (in review, live, or testing track only). Do not write
      "published" unless the console says so. If it is live, copy the listing URL for the form.
- [x] **Run on a real phone:** the owner's own phone, 4 Nov 2026, with spoken questions to Ask (no log committed; README and
      HONESTY say so). Sign-in from a Play install is still untried (the APK is sideloaded).
- [x] The company demo's **VAT** tab on the phone opened on *Jan–Mar 2025* with every box at £0.00 (emulator, audit issue A1):
      fixed on the server side on 4 Nov (`/books/vat/periods` now names the period due next, which the released APK reads),
      so 0.3.19 opens on Jul–Sep 2026 once the API is deployed; no rebuild needed.

## 2. HMRC sandbox: one full run

- [x] Relay on the sandbox with sandbox credentials; the public relay makes test users (`POST /hmrc/test-user` → 201 on
      4 Nov; the live site's VAT card made one in the audit).
- [x] **Run end to end once** (4 Nov 2026, 05:53 UTC): test user → HMRC's sandbox sign-in → obligations → declaration →
      submit → HMRC's receipt (form bundle `409715423288`), `docs/HMRC_SANDBOX_DEMO.md`. README, JUDGING and HONESTY
      say so; the video's VAT scene shows the test user with the password blurred.
- [ ] Keep it that way: no production HMRC credentials exist or should (`HMRC_BASE=https://test-api.service.hmrc.gov.uk`).

## 3. Meta and the model hosts: billing and keys

- [ ] **Meta Model API billing.** dev.meta.ai → your app → billing: confirm the credit or spend cap covers judging (the
      live server answers first with `muse-spark-1.3-contributor` on the server's key: `GET https://api.accnomos.com/health`).
- [x] `META_API_KEY` is set on the server by decision (the demo and the Meta-first route need it); the per-IP rate limit
      and the demo's limits are the spend guard (`docs/HONESTY.md`, Models).
- [x] Muse Spark 1.3 numbers: `evals/runs/spark13_200`, `spark13_messy_200` (4 Nov 2026).
- [x] **The open-weights host** (Muse Spark Open) is off on the live server since 2 Nov 2026 (`docs/submission/OPEN_WEIGHTS.md`);
      nothing to pay for. The hosted GPU is not deployed; Glimmer runs on the owner's own server (`/health`: `spark`,
      `muse-glimmer:30b`).
- [x] Muse Voice Transcribe and SAM 3.1 have run live (`evals/runs/live_checks_2026-11-04`, `evals/runs/sam_crop_live`);
      `SAM_CROP=1` is set on the server for its next deploy.

## 4. Demo account, model host and judges' access

- [x] **Judges' path is the no-sign-in demo** (`https://accnomos.com/judges`, *Try the demo* on every public page; the
      guide is moving to `/demo` today, keep `/judges` working): the audit ran Home, Review approve, Ask, Talk card,
      Reports export, the VAT sandbox test user, the bank feed card, Settings › AI and the personal demo on the live site
      on 4 Nov. No judges' Microsoft account is needed; *Load sample books* stays as the signed-in route.
- [x] `curl https://api.accnomos.com/health` returned `"ok": true` with `demo.ready: true` at 11:00 UK on 4 Nov.
- [ ] **Keep the server up until results are announced**, not just until you submit: sleep and automatic updates off;
      check `/health` once a day; the demo seed rebuilds after midnight (the first visitor waits ~2 min).
- [ ] **Deploy what is on `main` but not yet on the server or site** before 02:00 (the web deploys itself on every push to
      `main`; the API is deployed by hand): after the last merge, redeploy the API and open `/judges` and `/demo` in a private
      window. The demo bank-feed cap, the `/demo` guide, the UI polish and the audit's doc fixes are on `main`.
- [x] Server keys set: `ACTIONS_SIGNING_KEY`, the HMRC sandbox client id and secret on the relay, `TRUELAYER_*` sandbox
      keys, `META_API_KEY`.

## 5. Video

- [x] Edited: v3, 2:55.9, opens with the provenance line, live takes from `accnomos.com` (`docs/video/V3_EDIT.md`,
      `docs/video/SCRIPT_V3.md`); the HMRC sandbox password is blurred while on screen.
- [ ] Watch the final render once end to end: no tokens, keys or real mail in any frame; the length at or under 3:00;
      the opening line says what pre-existed (only the owner's own AI server) and that everything else was built this week.
- [ ] Upload where the form asks (YouTube unlisted if allowed) and play it in a private window, signed out; paste the link
      into the form.

## 6. X post for Most Viral

- [ ] Read the hackathon's rules for the Most Viral prize first: the required hashtag, handle to tag, posting window and
      how they count engagement. Put the exact hashtag and handle into `docs/submission/X_THREAD.md` (it leaves
      placeholders; do not guess them).
- [ ] Post the thread from `docs/submission/X_THREAD.md` from your own account, with the video (or a 30–45 s cut) on
      post 1 and the repo link on the last post. Post it when the video is public, early enough in the window to gather
      engagement.
- [ ] Copy the post's URL for the submission form.
- [ ] Reply to questions honestly: the thread's claims are limited to what `docs/HONESTY.md` allows; anything else, link
      HONESTY.md.

## 7. Submission form fields

Check the form's own field list on the day; this is what the repo has for each likely field.

| Field | Where to take it from |
|---|---|
| Project name | Accnomos |
| Tagline | `docs/submission/DESCRIPTION.md` (Tagline) |
| Description | `DESCRIPTION.md`: the 150- or 400-word text (149 and 388 by `wc -w`; re-count in the form's own counter) |
| Track | Indie (solo: Zohaib Sharif) |
| Team / owner | Zohaib Sharif, Zaytuna Business Services Ltd |
| Repository | `https://github.com/zaytunazs/accnomos` (public) |
| Video link | https://youtu.be/gTZCC_gadEE (uploaded 4 Nov, unlisted, reachable logged out) |
| Live demo | `https://accnomos.com` (press *Try the demo*; guide at `https://accnomos.com/judges`, no sign-in) |
| Judge access | "No account needed: press Try the demo. HMRC and the bank feed are sandboxes." |
| Android app | the APK link from the README (`android-0.3.19-24`); Play: "submitted, in Google's review" unless the console says otherwise |
| Meta models / tools used | `docs/submission/META_MODELS.md`: Muse Spark 1.3 (the live server's first model, measured), Muse Glimmer 30B (open weights on our own server: fallback and local mode), Muse Spark Open (hosted open weights, evals only, off on the live server), Muse Voice Transcribe and SAM 3.1 (both run live), Muse Image (brand art); Muse Code as a coding assistant. Where the open weights run, with call records: `docs/submission/OPEN_WEIGHTS.md` |
| What pre-existed | `docs/PROVENANCE.md`: the owner's own AI server with a local model runtime, nothing else; first commit 6 h 29 min after kickoff |
| AI coding assistants | Muse Code and other AI tools; every merge reviewed (`docs/reviews/`) |
| X post (Most Viral) | from section 6 |
| Known limitations | link `docs/HONESTY.md` |

## 8. Secrets check (the repo is already public: do it now)

Run from the repo root on a **fresh clone**. The 4 Nov audit re-ran checks 1–3 and 5 on `main` at `8debc2e9`: only
expected hits (`.env.example`; a fake JWT-shaped token in `services/runtime/tests/test_mailboxes.py`; fake secrets in
test mode; the LAN address `192.168.1.176` in `.env.example` and the Android network security config). Check 4 (your real
values) only you can do.

```bash
# 1. Forbidden files, ever committed (working tree, then all history)
git ls-files | grep -E '(^|/)\.env($|\.)|\.jks$|\.keystore$|key\.properties|\.pem$|\.p12$|\.token$|hmrc-test-user'
git log --all --name-only --pretty=format: | sort -u | grep -E '(^|/)\.env($|\.)|\.jks$|\.keystore$|key\.properties|\.pem$|\.p12$|\.token$|hmrc-test-user'
# (.env.example is expected and fine)

# 2. Key-shaped strings in the working tree
git grep -n -E 'AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}' -- . ':(exclude)uv.lock' ':(exclude)*pnpm-lock.yaml'
git grep -n -i -E '(client_secret|api[_-]?key|secret|password|token)\s*[:=]\s*["'"'"'][A-Za-z0-9_.-]{20,}["'"'"']'
#    expected hit: services/hmrc-relay/tests/test_hardening.py:10 (a fake test token)

# 3. The same patterns across all history (slow; read every hit)
git log --all -p -G'AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9]{20,}|BEGIN [A-Z ]*PRIVATE KEY' --oneline | head -100
git log --all -p -G'(HMRC_CLIENT_SECRET|MODEL_API_KEY|META_API_KEY|BASETEN_API_KEY)=[^[:space:]]+' --oneline | head -100
#    expected hits: 86d7073 (a parser line) and 50424fb (a "…" placeholder); nothing else

# 4. Your own values: grep for them directly (paste the real strings, do not save this command)
git grep -n -F -e '<your HMRC client secret>' -e '<your Meta key>' -e '<your hosted-verifier key>'
git log --all -p -S'<your HMRC client secret>' --oneline | head

# 5. Personal details to decide on (not secrets)
git grep -n -E 'zohai|C:\\Users' -- tools          # tools/*.ps1 and brand_muse.py contain your Windows username and paths
git grep -n '192\.168\.1\.176'                      # your LAN address is the default AI URL in web, mobile and compose
```
- [ ] If any hit is real: **rotate that credential at once** (the repo is public, so assume it was copied): HMRC Developer
      Hub (client secret), Meta developer console (model key), the open-weights host (API key), the hosted GPU (token). Rewriting history does not
      un-publish it.
- [ ] Never commit `.env`, `key.properties`, a keystore, or a `.v`/`.venv` folder; check `git status` before every push.
- [ ] Open the repo in a private window: `README.md` → *For judges* → `docs/PROVENANCE.md` and `docs/HONESTY.md` load.

## 9. Docs hygiene and the last hour

- [x] Test figures refreshed 4 Nov (README "Current gates", JUDGING.md): CI green on `main`.
- [x] `docs/PROVENANCE.md` commits-per-day table re-run on 4 Nov (1,727 commits on `main` to `8debc2e9`).
- [x] `final-audit` (doc fixes) and the `/demo` guide merged into `main` (4 Nov afternoon); the `/help` footer shows
      the build hash of the deployed export.
- [ ] Last hour: run the demo path once on the real site (`/judges` → Start the demo → Review → Approve → VAT → Make a
      test user); `/health` is `"ok": true`; fill the form; **submit by 18:00 UK time on Wed 4 Nov** (the hard deadline
      is 02:00 UK time on Thu 5 Nov).
