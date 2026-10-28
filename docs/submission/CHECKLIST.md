# Owner checklist: what only you can do before submitting

Deadline: **Wed 4 Nov 2026, 21:00 ET** = **02:00 UK time on Thu 5 Nov** (US clocks went back on 1 Nov, so ET is EST,
UTC−5; UK is on GMT). Aim to submit by **Wed 4 Nov, 18:00 UK time** so there is slack.
Refreshed 28 Oct 2026. `[x]` = done according to the owner's status; the repo holds no log of console or server steps
(`docs/HONESTY.md`). `[ ]` is still yours. Order matters: the video depends on 1–4.
**The repository is already public** (`gh api repos/zaytunazs/accnomos` → `"visibility": "public"`, checked 28 Oct), so
run the secrets check in section 8 now, not last.

## 1. Android: Play upload and a real-phone run

- [x] Entra holds the Play app-signing key's MSAL hash (27 Oct); release builds from 0.3.1+4 carry it.
- [x] `flutter analyze` clean and `flutter test` 248 passed (28 Oct gate figure).
- [ ] **Build and upload the current version.** `apps/mobile/pubspec.yaml` is **0.3.5+10** (bump it first if you add
      anything). On your PC: `tools/build_release.ps1 -Tag 0.3.5-10` (analyses, builds the signed AAB with the Play hash).
      Play Console → Accnomos → *Production* (menu names vary between console versions) (or a testing track) → *Create new release* → upload
      the `.aab` → paste the "What's new" text from `apps/mobile/RELEASE_NOTES.md` → *Review release* → *Start rollout*.
- [ ] **Write the real Play status into the form on the day** (in review, live, or testing track only). Do not write
      "published" unless the console says so. If it is live, copy the listing URL for the form.
- [ ] **Install from Play on a real Android phone, sign in, photograph a receipt, and see it in web Review.** Nothing has
      run on a real device yet (`docs/HONESTY.md`, Android). This is shot 3 of the video; if it fails, film the 390 px
      web app in the phone's browser and change the caption, as `VIDEO_SCRIPT.md` says.
- [ ] Tell the maintainers what happened, so `docs/HONESTY.md` and `README.md` can say a real phone worked (or did not).

## 2. HMRC sandbox: one full run

- [x] Relay configured for the sandbox; the owner has connected once (27 Oct). **No end-to-end submission is recorded.**
- [ ] Relay is on the sandbox: `HMRC_BASE=https://test-api.service.hmrc.gov.uk`. No production credentials exist or should.
- [ ] The HMRC application's redirect URI equals the relay's `HMRC_REDIRECT_URI` (default
      `https://api.accnomos.com/hmrc/callback`), and `RELAY_ALLOWED_REDIRECTS` lists `https://accnomos.com`.
- [ ] Test user: `curl -X POST https://api.accnomos.com/hmrc/test-user` returns `userId`, `password`, `vrn`
      (`docs/HMRC.md`). Keep them on a card, off camera, out of the repo.
- [ ] **Run it once off camera:** `/vat` → *Connect to HMRC (sandbox)* → *Show obligations* → pick one → declaration →
      *Submit to HMRC (sandbox)* → check `06 VAT returns/<periodKey>/` in OneDrive for the receipt.
- [ ] If it worked: tell the maintainers (README and HONESTY change "not yet run end to end") and film the full flow
      (shot 7). If not: film up to the declaration card only, with the extra caption.

## 3. Meta, Baseten and Modal: billing and keys

- [ ] **Meta Model API billing.** dev.meta.ai → your app → billing: add a payment method or credit, set a monthly spend
      cap, and note the remaining balance. Without it, key mode (Muse Spark 1.3) fails for judges who choose it.
- [ ] Decide whether `META_API_KEY` is set on the server. In key mode with no key header the runtime falls back to it,
      so anyone could spend your key on Ask (`docs/HONESTY.md`, Models). Leave it unset on the public demo unless the
      spend cap makes that acceptable.
- [ ] Optional, if you have credit: the first Muse Spark 1.3 numbers,
      `cd evals && python -m harness.run_extraction --mode key --out runs/<name>`. Until a report exists say
      "unit-tested only".
- [ ] **Baseten** (`BASETEN_API_KEY` on the runtime, set 27 Oct): check the balance or a spend limit covers judging; the
      key-mode Verifier (Muse Spark Open) stops without it.
- [ ] **Modal**: the 27 Oct Glimmer evals record a Modal endpoint (`config.base_url` in
      `evals/runs/glimmer_200_v2/summary.json`). If the demo's Glimmer runs on Modal, check the workspace's spending
      limit and that the app does not scale to zero during judging (or that a cold start is acceptable); if it runs on the
      Spark, keep the Spark on (section 4).
- [ ] Do **not** film the mic or turn on `SAM_CROP`: neither has run live.

## 4. Demo account, model host and judges' access

- [ ] **Video account:** a throwaway personal Microsoft account, *Connect* done, `00 Inbox` empty, Autopilot **L1**, VAT
      **Quarterly, stagger 1** (`docs/DEMO.md`). A second throwaway mailbox to send it one receipt email (shot 8).
- [ ] **Judges' account:** a separate throwaway account with **Load sample books** pressed once (never run against a real
      OneDrive: do it and open every page before relying on it). If the no-sign-in `/judges` page is merged by then, open
      it in a private window and check it works signed out. Put any sign-in details in the form's private field, never
      in the repo.
- [ ] `curl https://api.accnomos.com/health` returns `"ok": true`; one dummy scan warms the model.
- [ ] **Keep the model host up until results are announced**, not just until you submit: the DGX Spark (sleep and
      automatic updates off) and/or the Modal app. Check `/health` once a day.
- [x] Server keys set (27 Oct): `ACTIONS_SIGNING_KEY`, the HMRC sandbox client id and secret on the relay,
      `BASETEN_API_KEY` on the runtime.

## 5. Video

- [ ] Record per `docs/submission/VIDEO_SCRIPT.md`: **it opens with the provenance line** (shot 1, from
      `docs/PROVENANCE.md`). Shots marked "not on `main`" are filmed only once merged and run; otherwise use the fallback rows.
- [ ] Check every frame for tokens, keys, the HMRC test user's password and real mail before export.
- [ ] Add `sped up` wherever a wait is cut; keep the length at or under 3:00.
- [ ] Upload where the form asks (YouTube unlisted if allowed) and play it in a private window, signed out.

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
| Video link | from section 5 |
| Live demo | `https://accnomos.com` (and `/judges` only if merged and checked) |
| Judge access | private field: the judges' account from section 4, or "press Load sample books on your own account" |
| Android app | Play listing URL and its real status from section 1 |
| Meta models / tools used | `docs/submission/META_MODELS.md`: Muse Glimmer 30B, Muse Spark 1.3 (unit-tested only), Muse Spark Open on Baseten, Muse Voice Transcribe and SAM 3.1 (unit-tested only), Muse Image; Muse Code as a coding assistant |
| What pre-existed | `docs/PROVENANCE.md`: the DGX Spark with Ollama, nothing else; first commit 6 h 29 min after kickoff |
| AI coding assistants | Claude, Muse Code, a local Qwen; every merge reviewed (`docs/reviews/`) |
| X post (Most Viral) | from section 6 |
| Known limitations | link `docs/HONESTY.md` |

## 8. Secrets check (the repo is already public: do it now)

Run from the repo root on a **fresh clone**. The 27 Oct review pass found only expected hits: `.env.example` (check 1),
the fake token in `services/hmrc-relay/tests/test_hardening.py:10` (check 2), a parser line in `86d7073` and a
`HMRC_CLIENT_SECRET=…` placeholder in `50424fb` (check 3). Check 4 (your real values) only you can do.

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
- [ ] If any hit is real: **rotate that credential at once** (the repo is public, so assume it was copied): HMRC Developer
      Hub (client secret), Meta developer console (model key), Baseten (API key), Modal (token). Rewriting history does not
      un-publish it.
- [ ] Never commit `.env`, `key.properties`, a keystore, or a `.v`/`.venv` folder; check `git status` before every push.
- [ ] Open the repo in a private window: `README.md` → *For judges* → `docs/PROVENANCE.md` and `docs/HONESTY.md` load.

## 9. Docs hygiene and the last hour

- [ ] Re-run the tests and update the figures if they moved: `uv run pytest -q`, `pnpm run e2e` in `apps/web`,
      `flutter test` in `apps/mobile` (28 Oct gates: runtime 1260, evals 258, relay 119, Playwright 208, Flutter 248).
- [ ] Re-run the commands at the end of `docs/PROVENANCE.md` and update its commits-per-day table.
- [ ] When the month-end close agent, profiles, the Modal models panel or `/judges` merge, ask the maintainers to add each
      to `DESCRIPTION.md`, `JUDGING.md` and `README.md` with how it was tested.
- [ ] Last hour: run the demo path once on the real site; `/health` is `"ok": true`; fill the form; **submit by 18:00 UK
      time on Wed 4 Nov** (the hard deadline is 02:00 UK time on Thu 5 Nov).
