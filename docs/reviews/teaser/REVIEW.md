# Review: teaser video pipeline (`claude/teaser`)

Reviewed by the integrator on 28 Oct 2026 before merging (the branch came without a review). One commit:
`tools/teaser/build.py` renders a 44 s teaser in 16:9 and 1:1, as a *social* cut ("Launching November 2026", two
"coming soon" beats) and a *submission* cut (only what runs today, ending on "Try the demo"), from the committed app
screenshots, Muse Image brand art, music synthesised in code (`music.py`) and a Kokoro TTS voice-over (Apache-2.0, the
WAVs in `tools/teaser/vo/`). `docs/submission/teaser/` holds the four MP4s, a thumbnail and ready-to-paste posts.

## Fixed while merging

The script had never been through the repo's ruff (0.17.3): one line over 120 characters, an unused import, `zip()`
without `strict=`, unused loop variables, `not … ==`, a `try/except/pass`, an ambiguous `l`, and formatting. All
fixed without changing behaviour (`strict=False` is what `zip` did; the rest are renames and rewrites);
`build.py --stills-only --frames 5,12` still renders the same frames here.

## Checked

- Every screen is sample data and labelled so; the posts keep HONESTY.md's rules (HMRC sandbox only, "MTD-ready", code
  calculates, nothing posts without approval), and the submission cut drops the "coming soon" beats.
- Credits name the voice (Kokoro, Apache-2.0), the music (own code) and Muse Image.

## For the owner

- **Voice.** The video and the YouTube text say "hands-free voice commands" / "Voice commands are built in too";
  `docs/HONESTY.md` says Muse Voice Transcribe has never been called live. Either run it once live before posting or
  soften the line.
- **Size.** The MP4s, WAVs and thumbnail are about 35 MiB, now in git history for good; later renders would be better
  attached to a release or uploaded straight to the platforms.
