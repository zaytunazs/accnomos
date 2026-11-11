# Re-taking the Android screenshots

The Android pictures cannot be taken in the cloud build (there is no emulator
there), so they are re-taken by hand on a PC with the Android emulator. They
must show no AI vendor or model name: since 11 Nov 2026 the app's strings are
neutral ("the hosted model", "the local open-weights model", "the AI"), so a
fresh debug build of `main` gives clean pictures. Old pictures that still show
a model name are listed at the end.

## What you need

- The repo at `main`, Flutter and the Android SDK (`adb` on your PATH).
- An emulator with a 1080 × 2400 screen (a Pixel 7-class device, light theme,
  English (UK), 24-hour clock off), booted, with animations off:

  ```sh
  adb shell settings put global window_animation_scale 0
  adb shell settings put global transition_animation_scale 0
  adb shell settings put global animator_duration_scale 0
  ```

- Python 3 with Pillow, and Tesseract for the check at the end.

## 1. Build and start the app

```sh
cd apps/mobile
flutter build apk --debug
adb install -r build/app/outputs/flutter-apk/app-debug.apk
adb shell am force-stop com.accnomos.app
adb shell am start -n com.accnomos.app/com.accnomos.accnomos_mobile.MainActivity
```

Sign out if you are signed in, then press **Try the demo** (the company demo,
Bramblewood Joinery Ltd, with the SAMPLE — FICTIONAL COMPANY bar). Wait until
Review shows its waiting documents.

## 2. Take each screen

Take every picture with the on-device capture and `adb pull`, which is
byte-for-byte safe in any shell (redirecting `adb exec-out screencap -p` in
Windows PowerShell corrupts the PNG):

```sh
shot() { adb shell screencap -p "/sdcard/$1.png" && adb pull "/sdcard/$1.png" "apps/mobile/screenshots/$1.png"; }
```

In PowerShell:

```powershell
function shot($n) { adb shell screencap -p "/sdcard/$n.png"; adb pull "/sdcard/$n.png" "apps/mobile/screenshots/$n.png" }
```

Clear the status bar of notifications first. Then, in the company demo:

| File (`apps/mobile/screenshots/`) | Screen and state |
|---|---|
| `home.png` | **Home** tab, scrolled to the top |
| `review.png` | **Review** tab, the first waiting document (Fictional Plastics Ltd, £126.00) with its "Read by …" chip |
| `ask.png` | **Ask** tab after asking "How much VAT do I owe?" (wait for the answer and its figures) |
| `vat.png` | **VAT** tab, Jul–Sep 2026 |
| `more.png` | **More** tab, scrolled to the top |
| `files.png` | **More › Files** |
| `contacts.png` | **More › Contacts** |
| `settings.png` | **More › Settings**, the AI section (it should read "the hosted model" / "the local open-weights model", no model id) |

For the how-to guides, take these too (save them to `apps/mobile/screenshots/howto/`,
then scale them as in step 3):

| How-to picture (`docs/howto/img/`) | Screen and state |
|---|---|
| `android-home.png` | Home, company demo |
| `android-more.png` | More, company demo |
| `android-vat.png` | VAT, Jul–Sep 2026 |
| `android-contacts.png` | More › Contacts |
| `android-contacts-import.png` | More › Contacts › Import contacts (phone address book choice) |
| `android-goals.png` | More › Goals, with the written progress note |
| `android-talk.png` | The **Talk** button pressed, after "How much VAT do I owe?" |
| `android-personal-home.png` | More › **Switch to the personal demo**, then Home |
| `android-personal-budget.png` | Personal demo, **Budget** tab |
| `android-review.png`, `android-ask.png` | Made from `review.png` and `ask.png` in step 3 |

If a note on screen names a test or stand-in model, wait for the real answer or
ask again; never edit a picture.

## 3. Make the smaller copies

From the repo root:

```sh
python - <<'EOF'
from pathlib import Path
from PIL import Image
src, out = Path("apps/mobile/screenshots"), Path("docs/howto/img")
def small(png, name):
    Image.open(png).convert("RGB").resize((432, 960), Image.Resampling.LANCZOS).save(out / f"{name}.png", optimize=True)
small(src / "review.png", "android-review")
small(src / "ask.png", "android-ask")
for png in sorted((src / "howto").glob("android-*.png")):
    small(png, png.stem)
EOF
python apps/web/scripts/marketing-images.py   # apps/web/public/shots/android-review.webp and android-ask.webp
```

Delete `apps/mobile/screenshots/howto/` afterwards (the guides use the small
copies only).

## 4. Check before committing

No picture may name an AI vendor or model. Read every Android picture with OCR:

```sh
for f in apps/mobile/screenshots/*.png docs/howto/img/android-*.png apps/web/public/shots/android-*.webp; do
  python -c "import sys; from PIL import Image; Image.open(sys.argv[1]).convert('RGB').save('/tmp/ocr.png')" "$f"
  tesseract /tmp/ocr.png - 2>/dev/null | grep -iqE '\bmeta\b|\bmuse\b|glimmer|spark|llama|qwen|whisper|\bSAM\b' && echo "STILL NAMES A MODEL: $f"
done
```

Nothing should be printed. Commit the PNGs and WebPs together.

## Pictures that still name a model (as of 11 Nov 2026)

OCR found a model or vendor name in these, all taken before the app's strings
were made neutral:

- `apps/mobile/screenshots/home.png`: the old welcome line naming the model vendor
- `apps/mobile/screenshots/settings.png`: the old AI choices naming the local and hosted models
- `apps/mobile/screenshots/ask.png`: an answer footnote with the hosted model's id
- `apps/mobile/screenshots/review.png`: the "Read by …" chip with the hosted model's name
- `apps/web/public/shots/android-review.webp` and `android-ask.webp` (made from the two above; shown on the landing page)
- `docs/howto/img/android-review.png`, `android-ask.png`, `android-home.png`, `android-goals.png`, `android-talk.png`, `android-personal-home.png`

The store listing's phone screenshots are not kept in the repo; take them the
same way (step 2) and check them with step 4 before uploading.
