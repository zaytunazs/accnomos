# X launch thread (Most Viral)

Five posts for the owner's account, written 28 Oct 2026. Every claim is one `docs/HONESTY.md` allows; the numbers are from
`docs/submission/META_MODELS.md` and `evals/runs/*/summary.json`. Post it when the video is public (`CHECKLIST.md` section 6).

**Before posting:** replace `[HASHTAG]` and `[HANDLE]` with the hashtag and account the hackathon's Most Viral rules name
(not guessed here), attach the video or a 30–45 s cut to post 1, and re-count each post in X's composer. The counts below
are characters with the placeholders in place, a link counted as 23 and the emoji as 2; each post must stay at or under 280
once the real hashtag and handle go in.

**Post 1 says "snap a receipt on your phone"**: post it only after the real-phone run in `CHECKLIST.md` section 1 has worked (nothing has run on a real device yet). If it has not, change it to "Upload a receipt".

Do not add: "0 false posts", "files with HMRC" (it is the sandbox), "works on iPhone", "tested on real phones", time or
money saved, or any number not in `META_MODELS.md`. If the month-end close agent, profiles or `/judges` are merged and run
by launch day, a sixth post may name them; until then leave them out.

## 1/5 (256 characters)

```text
I built Accnomos for the Meta Global AI Developer Hackathon: bookkeeping and MTD VAT for UK small businesses.

Snap a receipt on your phone, a Meta model reads it, you approve, and code works out the VAT.

Your books stay in your own OneDrive. 🧵 [HASHTAG]
```

## 2/5 (247 characters)

```text
AI proposes, you approve, code calculates.

Muse Glimmer 30B (Meta's open-weights model) reads the receipt. A second reading with a different prompt checks six fields. If they differ, it goes to "Needs a look". Nothing posts until you tap Approve.
```

## 3/5 (258 characters)

```text
The nine VAT boxes are plain code, never a model. Submission is built against HMRC's Making Tax Digital sandbox; no live filing yet.

Ask a question in plain English: every figure in the answer is checked against your books. An invented number gets replaced.
```

## 4/5 (241 characters)

```text
Measured on 200 synthetic documents, every field right:
• Muse Spark Open: 91% clean, 93% messy
• Muse Glimmer 30B: 85% clean, 80% messy

Real phone photos will score lower. Ask: 32 of 32 figures exact. Every known gap is listed in the repo.
```

## 5/5 (240 characters)

```text
Built from scratch during the hackathon with Claude, Muse Code and a local Qwen; every merge reviewed. Only my DGX Spark with Ollama existed before.

Android now, iPhone coming. Open source (MIT):
github.com/zaytunazs/accnomos

[HANDLE] [HASHTAG]
```

## Replies to have ready

- *Does it file with HMRC?* "Not for real yet: the Making Tax Digital flow is built against HMRC's sandbox. Production filing is the next step."
- *How accurate is it?* "On 200 synthetic documents, every field right on 91–93 % for Muse Spark Open and 80–85 % for Glimmer. Real photos will be lower, which is why you approve every entry."
- *Where is my data?* "In your own OneDrive. Accnomos keeps no database; disconnect and the files are still yours."
- *What existed before the hackathon?* "Only my DGX Spark with Ollama. The timeline is in docs/PROVENANCE.md."
- Anything else: link `docs/HONESTY.md`.
