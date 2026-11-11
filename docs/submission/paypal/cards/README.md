# Video cards (static)

| File | Scene | Length |
|---|---|---|
| `problem.svg` | pr: the problem and who it is for, straight after the presenter | 6 s |
| `how-it-works.svg` | hw: PayPal APIs → AI proposes → code calculates in pence → you approve → books in your own drive → VAT to HMRC | 7 s |
| `ai-in-action.html` → `ai-in-action.png` | ai: six real screenshots (crops in `ai/`) with what the AI did and what code or the owner did | 6 s |
| `features.html` → `features.png` | fl: every feature, grouped (only features with a screen or a README section) | 5 s |

All are 1920 × 1080, use the app's own colours, and carry no logos (PayPal is named as text only). Render to PNG
with any SVG renderer, for example:

```bash
rsvg-convert -w 1920 -h 1080 docs/submission/paypal/cards/how-it-works.svg -o how-it-works.png
# or: chromium --headless --screenshot=how-it-works.png --window-size=1920,1080 docs/submission/paypal/cards/how-it-works.svg
```

In the edit, build `how-it-works` up left to right over its 7 s (one box about every second), in step with the
narration "PayPal's data comes in, the AI proposes, code calculates to the penny, and the owner approves."

The two HTML slides are rendered with headless Chromium (the PNGs in this folder were made this way):

```bash
cd docs/submission/paypal/cards
CHROME=/opt/pw-browsers/chromium-1243/chrome-linux64/chrome   # or any Chromium / Chrome
for n in ai-in-action features; do
  "$CHROME" --headless --no-sandbox --hide-scrollbars --force-device-scale-factor=1 --window-size=1920,1080 \
    --screenshot="$PWD/$n.png" "file://$PWD/$n.html"
done
```

## The AI-in-action crops (`ai/`)

Real screenshots from the how-to guides, cropped with no other change. Each was checked by eye for model names,
email addresses and real company names: none is visible, and every business named in them is fictional sample data.

| Crop | Source | Box (x0, y0, x1, y1) | Shows |
|---|---|---|---|
| `ai-receipt.png` | `docs/howto/img/review-approve-4.png` | 240, 62, 1270, 570 | A receipt read into a proposed entry, with the code checks |
| `ai-ask.png` | `docs/howto/img/paypal-ask-1.png` | 830, 0, 1280, 500 | "How much is sitting in PayPal?" answered by code from the books |
| `ai-paypal-coding.png` | `docs/howto/img/paypal-sync-4.png` | 270, 348, 1240, 620 | A PayPal purchase coded "suggested by AI", flagged "No receipt", waiting for approval |
| `ai-grid-filter.png` | `docs/howto/img/power-grid-3.png` | 262, 230, 1250, 600 | Ledger explorer: plain words become a checked grid filter |
| `ai-calendar.png` | `docs/howto/img/notes-tasks-2.png` | 836, 8, 1276, 640 | Talk: a note and a calendar event proposed, waiting for approval |
| `ai-support.png` | `apps/web/public/help/support-1.webp` | 262, 190, 840, 800 | The support assistant answering from the Sync PayPal guide |

Not used: the dispute-evidence screenshots (`paypal-disputes-2/3.png`). Their preview shows a customer email address,
and it is the code-written fallback ("None of the server's AI providers answered"), not an AI draft.
