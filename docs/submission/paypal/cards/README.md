# Video cards (static)

| File | Scene | Length |
|---|---|---|
| `problem.svg` | pr: the problem and who it is for, straight after the presenter | 6 s |
| `how-it-works.svg` | hw: PayPal APIs → AI proposes → code calculates in pence → you approve → books in your own drive → VAT to HMRC | 7 s |

Both are 1920 × 1080, use the app's own colours, and carry no logos (PayPal is named as text only). Render to PNG
with any SVG renderer, for example:

```bash
rsvg-convert -w 1920 -h 1080 docs/submission/paypal/cards/how-it-works.svg -o how-it-works.png
# or: chromium --headless --screenshot=how-it-works.png --window-size=1920,1080 docs/submission/paypal/cards/how-it-works.svg
```

In the edit, build `how-it-works` up left to right over its 7 s (one box about every second), in step with the
narration "PayPal's data comes in, the AI proposes, code calculates to the penny, and the owner approves."
