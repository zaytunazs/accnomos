# Owner checklist: what only you can do before submitting

Deadline: **Wed 4 Nov 2026, 21:00 ET** (02:00 GMT on Thu 5 Nov; UK clocks went back on 25 Oct and US clocks on 1 Nov, so ET is EST, five hours behind). Do the items in order: the video depends on 1–4, and the repo check should be last before you flip anything public.
Refreshed 27 Oct 2026. `[x]` means done on 27 Oct according to the owner's status that day; the repo holds no log of these console and server steps (`docs/HONESTY.md`), so each ticked item says what to glance at if you want to be sure. `[ ]` is still yours.

## 1. Android: Play listing and sign-in

- [x] **Entra Android entry for the Play release** (done 27 Oct): the Play app-signing key's MSAL signature hash is registered under the Accnomos app's *Authentication* → *Android* platform. Build **0.3.1+4** onwards is built with that hash (`tools/build_release.ps1`; commit `d67527e`). Glance: Entra → *App registrations* → Accnomos → *Authentication* shows the Android entry.
- [x] **`flutter analyze` and `flutter test`** now run on every Android merge: **248 tests pass** (28 Oct gate figure).
- [x] **Current build:** `apps/mobile/pubspec.yaml` is **0.3.2+5** (adds *Add from phone*, the system contact picker).
- [ ] **Play listing status.** Play Console → your app → *Release* → *Production*. On 27 Oct the owner's note is "production track has build 1 in review". Write the real status into the form on the day (in review, live, or test-track only); do not write "published" unless the console says so.
- [ ] **Sign in on a release/Play build on a real phone** and note whether it worked. The repo has no record of a phone sign-in; until you have one, film the debug build or the 390 px PWA and say so. After a successful sign-in, set `broker_redirect_uri_registered` to `true` in `apps/mobile/assets/msal_config.json` only if you rebuild; otherwise leave the file alone.
- [ ] If you want to show *Add from phone*, run it once on a real phone first (the picker has not been run on one; `README.md` Contacts row).

## 2. Demo account and data

- [ ] **A throwaway personal Microsoft account** (outlook.com), never anyone's real books. Sign in once on onedrive.com so the drive exists (`docs/DEMO.md`, `tools/seed_demo.md`).
- [ ] **For the video:** use an *empty* account signed in at `https://accnomos.com`, finish *Connect*, empty `00 Inbox`, Settings → Autopilot **L1**, VAT **Quarterly, stagger 1** (`docs/DEMO.md`, "Set up before you go on").
- [ ] **For judges who want to click through six months:** a *separate* throwaway account with the sample books. **The judge account can be prepared with the button instead of the CLI:** sign in on accnomos.com, complete *Connect*, press **Load sample books** on Home and wait for it to reload (no token copying). Judges can also press it on their own account. The CLI route still works: `python tools/seed_demo.py --business "Bramblewood Joinery Ltd" --dry-run`, then without `--dry-run`; steps and the token handling are in `tools/seed_demo.md`. Neither route has **ever been run against a real OneDrive** (and how long the button takes there is unmeasured), so do it before relying on it. Do not seed the video account (it leaves 25 documents in `00 Inbox`). Put the judge account's sign-in details in the submission form's private field, not in the repo.
- [ ] **Model host:** on the DGX Spark `ollama list` shows `muse-glimmer:30b`; run one dummy scan to warm it. `curl https://api.accnomos.com/health` returns `"ok": true`. The live sites could not be reached from the sessions that wrote the docs, so this is unchecked.
- [ ] **Keep the DGX Spark on, and its network path up, through judging** (until the results are announced, not just until you submit). It is the only place Muse Glimmer 30B runs for the demo, and the Muse Spark Open extraction eval (`evals/runs/spark_open_200`) runs there. Disable sleep and automatic updates; check `curl https://api.accnomos.com/health` once a day.
- [x] **Server keys set** (done 27 Oct, per the owner): `ACTIONS_SIGNING_KEY` (chat-action cards no longer fail with 403 after a restart), the HMRC sandbox `HMRC_CLIENT_ID` / `HMRC_CLIENT_SECRET` on the relay, and `BASETEN_API_KEY` on the runtime. Glance: `docker compose config` on the server shows them non-empty (do not paste the values anywhere).
- [ ] Decide whether `META_API_KEY` is set on the server. In key mode with no key header the runtime falls back to it, so anyone could spend your key on Ask (`docs/HONESTY.md`, Models). Leave it unset on the public demo unless you accept that.

## 3. HMRC sandbox

- [x] **Relay configured for the sandbox** (27 Oct): credentials are on the relay server, and the owner has **connected once** (OAuth completed). **No end-to-end sandbox submission is recorded yet.**
- [ ] Confirm the HMRC application's redirect URI equals the relay's `HMRC_REDIRECT_URI` (compose default `https://api.accnomos.com/hmrc/callback`) and that `RELAY_ALLOWED_REDIRECTS` lists `https://accnomos.com`.
- [ ] **Test user:** `curl -X POST https://api.accnomos.com/hmrc/test-user` returns `userId`, `password`, `vrn` (`docs/HMRC.md`). Keep them on a card, off camera and out of the repo.
- [ ] **Run the whole flow once, off camera:** `/vat` → *Connect to HMRC (sandbox)* → *Show obligations* → declaration → *Submit to HMRC (sandbox)* → check `06 VAT returns/<periodKey>/` for the receipt in OneDrive (the folder is `06`, per `README.md`). If it works, tell the maintainers so `README.md` and `docs/HONESTY.md` can say so, and use the full flow in the video; if not, stop at the confirmation card as `VIDEO_SCRIPT.md` says.
- [ ] Confirm the relay is on **sandbox** (`HMRC_BASE=https://test-api.service.hmrc.gov.uk`). No production credentials exist or should be added.

## 4. Meta models

- [x] **Muse Spark Open on Baseten is wired as the Verifier for key-mode users** (27 Oct): Baseten's `/v1/models` lists `meta-models/muse-spark-open`, and one real call through the verifier code read a gold receipt correctly in 7 s. That is one call, not an eval.
- [x] **Spark Open extraction eval** landed 27 Oct (`evals/runs/spark_open_200`, `spark_open_messy_200`); numbers are in `META_MODELS.md` and `JUDGING.md`.
- [ ] `MODEL_API_KEY` in the root `.env` (git-ignored). If you have a Meta key, `cd evals && python -m harness.run_extraction --mode key --out runs/<name>` gives the first Muse Spark 1.3 numbers; nothing in the repo has them. Until then say "unit-tested only".
- [ ] Do **not** film the mic or turn on `SAM_CROP` unless you have tested each live and `docs/HONESTY.md` says so.

## 5. Docs hygiene (judges will read these)

- [x] ~~Remove the stale tables in `README.md`~~: done in the earlier review pass.
- [ ] **Test counts** on `main`, 28 Oct gates: runtime **1260 passed** (all Python under `check.sh`), evals **258**, relay **119**, Playwright **208**, Flutter **248**. `README.md`, `docs/HONESTY.md`, `docs/DEMO.md` and `docs/submission/*` now quote these; before submitting, re-run `uv run pytest -q`, `pnpm run e2e` and `flutter test` and change any figure that has moved.
- [ ] **Fill in the repo URL** on the video's end card (`VIDEO_SCRIPT.md`).
- [ ] Read `docs/submission/DESCRIPTION.md`; paste the 150- or 400-word text, whichever the form takes. Re-count words in the form's own counter.
- [ ] Re-read `docs/submission/JUDGING.md` against the official judging criteria once you have them and rename its headings.

## 6. Video

- [ ] Record per `docs/submission/VIDEO_SCRIPT.md` (web 1280 × 720; phone 390 px). Anything marked "film only if checked" stays out unless you have run it live first. Check for visible tokens, the test user's password, keys and your real mailbox before export.
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
- [ ] Check `git remote -v` and `git status`: `TASK_BRIEF.md` files are committed under `docs/reviews/*/` on purpose. The `claude/submission-refresh` branch commits a `REVIEW.md` at the repo root; move it to `docs/reviews/submission-refresh/` when merging, as with the other branches.
- [ ] Check the `LICENSE` (MIT) and that `README.md`'s first screen says what is and is not working.
- [ ] Merge `claude/submission-refresh` to `main` only after you have read it; **nothing has been pushed**.
- [ ] After going public, open the repo in a private window and click `README.md` → `docs/HONESTY.md`.

## 8. Last hour

- [ ] Re-run the demo path once on the real site. Check Home, Review scan, Approve and VAT return show the figures in `VIDEO_SCRIPT.md`.
- [ ] Make the form entries (project name, description text, video link, repo link, track: Indie, demo-account details in the private field). Where: the hackathon submission form.
- [ ] Spark still on, `api.accnomos.com/health` still `"ok": true`.
- [ ] Submit at least two hours early; time zone is ET.
