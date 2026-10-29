# Image prompts: title, section and thumbnail art (Muse Image)

`tools/video/muse_images.py` reads this file and asks Muse Image (`muse-image-1.0`, Meta Model API) for one picture
per `## <id>` section, saving `docs/video/cards/<id>.png` plus `<id>.json` (model, prompt, size, date). Existing files
are skipped. `tools/video/assemble.sh` draws every word on top of these pictures itself, so the text stays crisp and
correct; a missing picture falls back to a plain brand-colour card.

Format: each card is a `## <id>` heading, a `size:` line (the aspect ratio to ask for; the saved file is cropped to
exactly this size) and a `use:` line, then the prompt paragraph. The `## style` block is put in front of every prompt.

Credit wherever this art appears: **Title art: Muse Image (Meta).**

## style

size: none
use: prepended to every prompt below

Flat, clean vector illustration with soft geometric shapes and gentle depth, calm and trustworthy, for a UK
small-business bookkeeping app. Palette from the app's design tokens only: deep teal #0F6E63, dark teal #0A4F47,
deep ledger green #073B35, teal tint #E6F1EF, warm paper off-white #F4F3EE, charcoal #1B1F24, and a small brass accent
#D9B55A. No text, no letters, no numbers, no words, no logos or brand marks of any real company, no real people and no
faces, no screenshots of real software, no flags, no currency symbols. Leave a wide calm area of plain colour where a
title will be added later.

## judges-title

size: 1920x1080
use: opening provenance card of the judges' video (shot 1) and its fallback card

A quiet workbench seen from slightly above at dusk: a closed notebook, a paper receipt and a phone lying face down on
deep ledger green, a small warm brass desk lamp glow in the lower right corner. The left two thirds stay almost empty
dark teal for the title.

## section-impact

size: 1920x1080
use: background for Impact cards (shots 2–3) when a shot is a card

A British high street of small independent shops drawn as simple flat shapes: a joiner's workshop, a café and a
corner shop with plain blank signs, morning light, warm paper off-white sky. The top half is open sky for a title.

## section-meta-ai

size: 1920x1080
use: background for the measured-numbers card (shot 5) and other Meta AI tooling cards

Abstract: paper receipts drifting from the left turn into tidy rows of a ledger grid on the right, a soft teal glow
where they pass through a simple lens shape. Dark teal background, off-white paper shapes. The centre stays calm and
dark so a table of figures can sit on it.

## section-depth

size: 1920x1080
use: background for Technical depth cards (shots 6–7)

An isometric stack of neat paper ledger sheets on the left, each sealed with a small brass wax-seal shape, beside a
simple folder icon shape on the right; clean lines, teal and off-white on charcoal. Middle third left empty.

## section-demo

size: 1920x1080
use: background for Demo quality cards (shots 8–11) and the end card

A single paper receipt following a dotted path across the frame: from a phone on the left, through an inbox tray, to
a ledger book and a sealed envelope on the right. Deep ledger green background, off-white and brass shapes, wide empty
band across the middle.

## thumb-judges

size: 1280x720
use: thumbnail of the judges' video

Bold, simple composition: one large off-white paper receipt tilted slightly, a deep teal check-mark shape stamped on
it, brass corner accent, deep teal background, the right half empty for a title.

## clip-01-title

size: 1080x1920
use: title card of clip 1 (email and photo intake)

Tall composition: an envelope and a phone at the top, paper receipts falling gently down into an open inbox tray at
the bottom; teal and off-white on deep ledger green; the middle third left empty.

## clip-02-title

size: 1080x1920
use: title card of clip 2 (dashboard and summary)

Tall composition: simple dashboard tiles drawn as rounded rectangles with abstract bars and a small line chart, no
numbers; off-white tiles on dark teal; the middle third left empty.

## clip-03-title

size: 1080x1920
use: title card of clip 3 (VAT return)

Tall composition: nine neat rounded boxes in a three by three grid at the bottom, a paper form with a brass seal at the
top; off-white and teal on deep ledger green; the middle third left empty.

## clip-04-title

size: 1080x1920
use: title card of clip 4 (self-employment and landlords)

Tall composition: a small terraced British house and a toolbox side by side at the bottom, a calendar page with four
quarter marks at the top; flat teal and off-white shapes; the middle third left empty.

## clip-05-title

size: 1080x1920
use: title card of clip 5 (Construction Industry Scheme)

Tall composition: simple scaffolding and a stack of timber planks at the bottom, a clipboard with blank lines at the
top; teal, off-white and brass on charcoal; the middle third left empty.

## clip-06-title

size: 1080x1920
use: title card of clip 6 (payroll and pensions)

Tall composition: three simple payslip shapes fanned out at the bottom, a small glass savings jar shape at
the top; flat teal and off-white on deep ledger green; the middle third left empty.

## clip-07-title

size: 1080x1920
use: title card of clip 7 (voice and chat)

Tall composition: two rounded speech bubbles with abstract wavy lines (no letters) at the top, a single approval card
with a check mark at the bottom; teal and off-white on charcoal; the middle third left empty.

## clip-08-title

size: 1080x1920
use: title card of clip 8 (accountant portal and exports)

Tall composition: two desks facing each other across a shared open folder, drawn as simple shapes with no people, a
small stack of exported sheets at the bottom; teal and off-white on dark teal; the middle third left empty.

## thumb-clip-01

size: 1280x720
use: thumbnail of clip 1

An envelope and a phone sending a paper receipt into a tray, flat shapes on deep teal, the right half empty.

## thumb-clip-02

size: 1280x720
use: thumbnail of clip 2

Rounded dashboard tiles with abstract bars, flat off-white on dark teal, the right half empty.

## thumb-clip-03

size: 1280x720
use: thumbnail of clip 3

A three by three grid of neat boxes beside a sealed paper form, off-white and brass on deep ledger green, the right
half empty.

## thumb-clip-04

size: 1280x720
use: thumbnail of clip 4

A small terraced house and a toolbox, flat teal shapes on paper off-white, the right half empty.

## thumb-clip-05

size: 1280x720
use: thumbnail of clip 5

Scaffolding and timber planks as simple shapes, teal and brass on charcoal, the right half empty.

## thumb-clip-06

size: 1280x720
use: thumbnail of clip 6

Three payslip shapes fanned out, off-white on deep ledger green, the right half empty.

## thumb-clip-07

size: 1280x720
use: thumbnail of clip 7

Two speech bubbles with wavy lines turning into a card with a check mark, teal on charcoal, the right half empty.

## thumb-clip-08

size: 1280x720
use: thumbnail of clip 8

Two desks sharing one open folder, no people, teal and off-white on dark teal, the right half empty.

## howto-connect-books

size: 1280x720
use: cover of docs/howto/connect-books.md

An open folder with neatly numbered tabs (no digits shown, just tab shapes) beside a cloud shape, off-white on dark
teal, the left half empty for the guide title.

## howto-add-mailbox

size: 1280x720
use: cover of docs/howto/add-mailbox.md

An envelope opening and a paper receipt sliding out into a tray, teal and off-white on charcoal, the left half empty.

## howto-review-approve

size: 1280x720
use: cover of docs/howto/review-approve.md

A paper receipt on a card with a large check-mark button shape below it, off-white and teal on deep ledger green, the
left half empty.

## howto-reconcile-bank

size: 1280x720
use: cover of docs/howto/reconcile-bank.md

Two columns of short lines joined by thin matching threads, one column paper, one column teal, on charcoal, the left
half empty.

## howto-vat-return

size: 1280x720
use: cover of docs/howto/vat-return.md

Nine neat boxes in a grid beside a paper form with a brass seal, on deep ledger green, the left half empty.

## howto-income-tax-update

size: 1280x720
use: cover of docs/howto/income-tax-update.md

A calendar page with four quarter marks beside a small terraced house and a toolbox, teal on paper off-white, the left
half empty.

## howto-payroll-paye

size: 1280x720
use: cover of docs/howto/payroll-paye.md

Three payslip shapes fanned out beside a small envelope, off-white and brass on dark teal, the left half empty.

## howto-invite-accountant

size: 1280x720
use: cover of docs/howto/invite-accountant.md

A folder being passed across a desk to an empty chair, simple shapes, no people, teal on paper off-white, the left
half empty.

## howto-export-accountant

size: 1280x720
use: cover of docs/howto/export-accountant.md

A neat stack of exported sheets flowing out of a folder into a tray, off-white on charcoal, the left half empty.

## howto-voice-chat

size: 1280x720
use: cover of docs/howto/voice-chat.md

Two rounded speech bubbles with abstract wavy lines (no letters) becoming a card with a check mark, teal and
off-white on deep ledger green, the left half empty.
