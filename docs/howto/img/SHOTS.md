# How-to screenshots

**Web** (`<guide>-<n>.png`, 1280 × 800, light theme): made by
`apps/web/e2e/howto.spec.ts` against the test-mode build and runtime, in the
demo sandbox's fictional sample books — the company demo (Bramblewood Joinery
Ltd) and the personal demo (the Harrison household). The control a step names
has a brass outline. Test mode answers with a stub instead of a model, so the
stub's own labels ("Test stub", its name, and a note the stub cannot write)
are taken out of the frame; the live app names the AI model in those places. The PNGs are then reduced to 192
colours to keep them small.

```sh
cd apps/web
pnpm run e2e:build
LANG=en_GB.UTF-8 HOWTO_SHOTS=1 pnpm exec playwright test e2e/howto.spec.ts --project=desktop --workers=1
# one guide only: HOWTO_ONLY='^vat-return' (the whole flow still runs; only matching pictures are written)
```

**Android** (`android-<screen>.png`, 432 × 960, from 1080 × 2400): the debug
build on an emulator (`accnomos_pixel`), signed out in **Try the demo** (the
company demo) or **More › Switch to the personal demo**, with their labelled
sample data. `android-review.png` and `android-ask.png` are
`apps/mobile/screenshots/review.png` and `ask.png` scaled down.

**Landing page thumbnails** (`apps/web/public/howto/<guide>.webp`, 640 × 400):
one picture from each featured guide, cropped to the page beside the menu and scaled down.
