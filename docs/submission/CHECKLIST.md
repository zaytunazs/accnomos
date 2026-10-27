# Owner checklist: what only you can do before submitting

Deadline: **Wed 4 Nov 2026, 21:00 ET** (02:00 GMT on Thu 5 Nov; UK clocks went back on 25 Oct and US clocks on 1 Nov, so ET is EST, five hours behind). Do the items in order: the video depends on 1–4, and the repo check should be last before you flip anything public.
`docs/HONESTY.md` says what the maintainers' status is for several items below and that **nothing in the repo records it**, so each item says where to look.
Tick boxes are yours; nothing here was checked against a live console.

## 1. Android: Play listing and sign-in

- [ ] **Play listing status.** Google Play Console → your app → *Release* → *Testing* or *Production*. Note which track the 0.2.0+2 build is on (`apps/mobile/pubspec.yaml` version), and whether it is live, in review or only in a test track. The repo has no record of the listing's state. Write the real status into the submission form; do not write "published" unless the console says so.
- [ ] **Entra redirect URI for the Play release.** Microsoft Entra admin centre → *App registrations* → the Accnomos app → *Authentication* → add an *Android* platform entry with package name and the **Play App Signing** SHA-1 (Play Console → *Setup* → *App signing*), converted to the base64 signature hash MSAL uses. Without it a release or Play build may not sign in (`docs/HONESTY.md`, Android).
- [ ] After registering it, set `broker_redirect_uri_registered` in `apps/mobile/assets/msal_config.json` (currently `false`), rebuild with `tools/build_release.ps1 -Tag <version>` (bump `pubspec.yaml` first), and **sign in on a release build on a real device or emulator**. Until then film the debug build only and say so.
- [ ] Run `flutter analyze` and `flutter test` in `apps/mobile` once. They have never been run; the README and HONESTY.md say so. If they fail, either fix or keep the Android claims in the submission as they are (built for the emulator, not tested).

## 2. Demo account and data

- [ ] **A throwaway personal Microsoft account** (outlook.com), never anyone's real books. Sign in once on onedrive.com so the drive exists (`docs/DEMO.md`, `tools/seed_demo.md`).
- [ ] **For the video:** use an *empty* account signed in at `https://accnomos.com`, finish *Connect*, empty `00 Inbox`, Settings → Autopilot **L1**, VAT **Quarterly, stagger 1** (`docs/DEMO.md`, "Set up before you go on").
- [ ] **For judges who want to click through six months:** a *separate* throwaway account seeded with `python tools/seed_demo.py --business "Bramblewood Joinery Ltd" --dry-run`, then without `--dry-run`. Steps and the token handling are in `tools/seed_demo.md`. The seed has **never been run against a real OneDrive**, so run it before relying on it. Do not seed the video account (it leaves 25 documents in `00 Inbox`). Put the judge account's sign-in details in the submission form's private field, not in the repo.
- [ ] **Model host:** on the DGX Spark `ollama list` shows `muse-glimmer:30b`; run one dummy scan to warm it. `curl https://api.accnomos.com/health` returns `"ok": true`. The live sites could not be reached from the sessions that wrote the docs, so this is unchecked.
- [ ] Set `ACTIONS_SIGNING_KEY` on the runtime server (`deploy/docker-compose.yml` passes it through, empty by default), otherwise a restart makes chat-action cards fail with 403 (`docs/HONESTY.md`).
- [ ] Decide whether `META_API_KEY` is set on the server. In key mode with no key header the runtime falls back to it, so anyone could spend your key on Ask (`docs/HONESTY.md`, Models). Leave it unset on the public demo unless you accept that.

## 3. HMRC sandbox

- [ ] **Credentials.** HMRC Developer Hub (`developer.service.hmrc.gov.uk`) → *Applications* → your sandbox application: copy the client ID and secret into `HMRC_CLIENT_ID` and `HMRC_CLIENT_SECRET` in the **relay server's** `.env` (never the repo; `deploy/docker-compose.yml` reads them). `.env.example` shows the other `HMRC_*` names.
- [ ] **Redirect URI** on the HMRC application must equal the relay's `HMRC_REDIRECT_URI` (compose default `https://api.accnomos.com/hmrc/callback`); `RELAY_ALLOWED_REDIRECTS` must list `https://accnomos.com`.
- [ ] **Test user:** `curl -X POST https://api.accnomos.com/hmrc/test-user` returns `userId`, `password`, `vrn` (`docs/HMRC.md`). Keep them on a card, off camera and out of the repo.
- [ ] **Run the whole flow once, off camera:** `/vat` → *Connect to HMRC (sandbox)* → *Show obligations* → declaration → *Submit to HMRC (sandbox)* → check `05 VAT returns/<periodKey>/receipt.json` in OneDrive. **It has never been run end to end.** If it works, update `README.md` and `docs/HONESTY.md` and use the full flow in the video; if not, stop at the confirmation card as `VIDEO_SCRIPT.md` says.
- [ ] Confirm the relay is on **sandbox** (`HMRC_BASE=https://test-api.service.hmrc.gov.uk`). No production credentials exist or should be added.

## 4. Meta keys (optional, but they change what you can say)

- [ ] `MODEL_API_KEY` in the root `.env` (git-ignored). If you have a Meta key, run `cd evals && python -m harness.run_extraction --mode key --out runs/<name>` to get the first real Muse Spark 1.3 numbers; nothing in the repo has them. Until then say "unit-tested only".
- [ ] `BASETEN_API_KEY` (and a confirmed slug in `VERIFIER_MODEL`) to make the Spark Open verifier real. The default slug is unconfirmed. Without a key the demo's verifier is Glimmer.
- [ ] Do **not** film the mic or turn on `SAM_CROP` unless you have tested each live and updated `docs/HONESTY.md`.

## 5. Docs hygiene (judges will read these)

- [x] ~~Remove the stale tables in `README.md`~~: done in the review pass (`REVIEW.md`). If you edit the README again, run `services/runtime/tests/test_docs.py`, which checks the files it cites.
- [ ] **Test counts:** README, HONESTY.md and DEMO.md now agree with a run on 27 Oct (runtime 642 + 1 skipped, relay 102, ledger 33, connectors 34, evals 153; e2e 44 counted, not run). Re-run `uv run pytest -q` and `pnpm run e2e` if anything merges after this branch, and update all three.
- [ ] **Fill in the repo URL** on the video's end card (`VIDEO_SCRIPT.md`).
- [ ] Read `docs/submission/DESCRIPTION.md`; paste the 150- or 400-word text, whichever the form takes. Re-count words in the form's own counter.

## 6. Video

- [ ] Record per `docs/submission/VIDEO_SCRIPT.md` (web 1280 × 720; phone 390 px). Check for visible tokens, the test user's password, keys and your real mailbox before export.
- [ ] Add the "sped up" caption wherever the scan wait is cut.
- [ ] Upload (YouTube unlisted or the form's own uploader; **check what the hackathon form requires**) and open the link in a private window to make sure it plays signed out. Where: the hackathon submission form (not in the repo).
- [ ] Keep the 30-second cut ready in case the form asks for one.

## 7. Make the repo public: secrets check (last)

Run from the repo root on a **fresh clone** as well as this checkout. Where: the terminal, then GitHub → *Settings* → *General* → *Danger Zone* → *Change visibility*.
The review pass (27 Oct, this checkout, all local refs) ran checks 1–3 below. The only hits were `.env.example` (check 1), the fake token in `test_hardening.py:10` (check 2), and in check 3 a parser line in `86d7073` (`if line.startswith("MODEL_API_KEY=")`) and a `HMRC_CLIENT_SECRET=…` placeholder in `50424fb`. None is a real secret. Check 4 (your real values) only you can do. Re-run all of them on a fresh clone of the remote:

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
git grep -n -F -e '<your HMRC client secret>' -e '<your Meta key>' -e '<your Baseten key>'
git log --all -p -S'<your HMRC client secret>' --oneline | head

# 5. Personal details to decide on (not secrets)
git grep -n -E 'zohai|C:\\Users' -- tools          # tools/*.ps1 and brand_muse.py contain your Windows username and paths
git grep -n '192\.168\.1\.176'                      # your LAN address is the default AI URL in web, mobile and compose
```

- [ ] If any history hit is real: **rotate that credential first**, then clean history (a fresh public repo is simpler than rewriting). Rotation: HMRC Developer Hub (client secret), Meta developer console (model key), Baseten settings (API key), Entra (no secret: public client).
- [ ] Check `git remote -v` and `git status`: `TASK_BRIEF.md` files are committed under `docs/reviews/*/` on purpose. This branch commits `TASK_BRIEF.md` and `REVIEW.md` at the repo root; move them to `docs/reviews/submission-pack/` when merging, as with the other branches.
- [ ] Check the `LICENSE` (MIT) and that `README.md`'s first screen says what is and is not working.
- [ ] Merge `claude/submission-pack` to `main` only after you have read it; **nothing has been pushed**.
- [ ] After going public, open the repo in a private window and click `README.md` → `docs/HONESTY.md`.

## 8. Last hour

- [ ] Re-run the demo path once on the real site. Check Home, Review scan, Approve and VAT return show the figures in `VIDEO_SCRIPT.md`.
- [ ] Submit at least two hours early; time zone is ET.
