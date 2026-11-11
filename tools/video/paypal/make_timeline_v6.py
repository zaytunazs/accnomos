# Builds timeline_paypal_v6.json from the capture marks. Run in the media folder (raw/, raw5/, raw6/, raw7/, cards/,
# android/): python3 make_timeline_v6.py
# v6 (12 Nov 2026, owner's review of draft 5): the presenter picture-in-picture only at the start ("pip_until"); one
# story "a week in the books" with PayPal as its spine; then three multi-feature slides that build up; a voice-only outro.
import json
C = {
 "w1": "Receipts: the AI reads the photo · code checks totals and VAT · you approve",
 "w2": "Bank feed by Open Banking (TrueLayer's test bank) · matches suggested · you confirm",
 "w3": "Invoice from plain words · PayPal Invoicing API: pay link",
 "w4": "PayPal Transaction Search API · gross / fee / net · a sale with no invoice waits for your VAT choice",
 "w5": "PayPal Balances API · PayPal's figure as of its last refresh",
 "w6": "AG Grid Community · Power grid: bulk approve, totals, plain-English filters",
 "w7": "PayPal Payouts API · you approve each payout · posts only when PayPal confirms",
 "w8": "PayPal Disputes API · SAMPLE dispute in the demo: nothing sent to PayPal",
 "w9": "AI search: the AI reads the question · code searches your books and PayPal · exact figures",
 "w10": "Talk to Accnomos: type or speak · every figure checked by code",
 "w11": "VAT: nine boxes by code · filed to HMRC's sandbox · HMRC's receipt",
 "w12": "Reports: profit and loss, who owes you · export to your drive",
 "w13": "Your books: plain files in your own OneDrive or Google Drive",
}
def ph(name, **kw): return {"src": f"android/{name}.mp4", "name": name, **kw}
def V(src, i, d, cap=None, sp=None, tag=None, blur=None, phone=None, crop=None):
    s = {"type": "video", "src": src, "in": i, "dur": d}
    if cap: s["caption"] = cap
    if sp: s["speed"] = sp
    if tag: s["tag"] = tag
    if blur: s["blur"] = blur
    if crop: s["crop"] = crop
    if phone is not None: s["phone"] = phone
    return s
def G(i, dur, kids, **kw): return {"id": i, "type": "group", "dur": dur, "vo": i, "children": kids, **kw}
bank = json.load(open("raw5/f-bank.marks.json"))["marks"]
vat = json.load(open("raw5/f-vat.marks.json"))["marks"]
talk = json.load(open("raw7/f-talkq.marks.json"))["marks"]
ANS = [380, 225, 1520, 855]  # the Ask answer, enlarged (web only: the phone clips show a raw link in their answers)
SB, DS = "PayPal sandbox", "Demo sample history"
segs = [
 # --- hook: the presenter picture-in-picture is on for these two lines only -------------------------------------
 {"id": "i0", "type": "group", "dur": 10.4, "vo": "i0", "pip": "presenter_intro.mp4", "pip_lead": 0.0, "children": [
   V("raw5/m-home.webm", 0.3, 3.4, phone=ph("a-home")),
   V("raw/pp-sync.webm", 11.0, 3.5),
   V("raw/m-review.webm", 1.4, 3.5, phone=ph("a-review"))]},
 {"id": "pr", "type": "still", "src": "cards/problem.png", "dur": 6.0, "vo": "pr", "pip_lead": 0.2, "vo_lead": 0.2},
 # --- a week in the books ----------------------------------------------------------------------------------------
 G("w1", 6.6, [
   V("raw6/f-receipt.webm", 0.5, 1.6, C["w1"], sp=2.0, phone=ph("a-capture")),
   V("raw6/f-receipt.webm", 9.9, 1.4, C["w1"], tag="Reading sped up", phone=ph("a-capture", **{"in": 3})),
   V("raw6/f-receipt.webm", 43.0, 2.0, C["w1"], phone=ph("a-review")),
   V("raw6/f-receipt.webm", 52.6, 1.6, C["w1"], phone=ph("a-review", **{"in": 3}))]),
 G("w2", 7.6, [
   V("raw5/f-bank.webm", 0.2, 1.6, C["w2"], tag="TrueLayer sandbox · test data", phone=ph("a-bank"),
     blur=[{"x": 420, "y": 440, "w": 1430, "h": 270}, {"x": 420, "y": 845, "w": 1430, "h": 60}]),
   V("raw5/f-bank.webm", bank.get("fetched", 26) - 0.4, 2.0, C["w2"], tag="TrueLayer sandbox · test data", phone=ph("a-bank", **{"in": 3})),
   V("raw5/f-bankmatch.webm", 3.0, 4.0, C["w2"], tag="Exact match confirmed", phone=ph("a-bank", **{"in": 6}))]),
 G("w3", 6.6, [
   V("raw5/f-invoice.webm", 2.0, 2.0, C["w3"], sp=2.2, tag="Typing sped up"),
   V("raw5/f-invoice.webm", 62.4, 1.4, C["w3"]),
   V("raw5/f-invoice.webm", 66.2, 1.4, C["w3"], tag="Demo: email not really sent"),
   V("raw5/pp-invoice.webm", 6.3, 1.8, C["w3"], tag=SB)]),
 G("w4", 12.0, [
   V("raw/pp-sync.webm", 0.0, 2.8, C["w4"], tag=SB, phone=ph("a-sync")),
   V("raw/pp-sync.webm", 10.4, 9.2, C["w4"], sp=1.5, tag=SB, phone=ph("a-sync", **{"in": 3}))]),
 {"id": "w5", "type": "video", "src": "raw/pp-tieout.webm", "in": 0.8, "dur": 4.8, "vo": "w5", "crop": [380, 300, 1520, 855], "caption": C["w5"], "tag": SB},
 G("w6", 8.2, [
   V("raw/pp-grid.webm", 2.0, 3.4, C["w6"], sp=1.5, tag=DS),
   V("raw/pp-grid.webm", 12.8, 1.2, C["w6"], tag=DS),
   V("raw/pp-grid.webm", 21.2, 1.8, C["w6"], sp=2.8, tag="Typing sped up"),
   V("raw/pp-grid.webm", 34.1, 1.8, C["w6"], tag=DS)]),
 G("w7", 11.0, [
   V("raw5/pp-billpay.webm", 0.5, 3.6, C["w7"], sp=2.0, tag=SB, phone=ph("a-billpay")),
   V("raw5/pp-billpay.webm", 8.0, 2.4, C["w7"], tag=SB, phone=ph("a-billpay", **{"in": 5})),
   V("raw5/pp-billpay.webm", 102.5, 2.6, C["w7"], tag="About 90 s later · the sandbox payee has not claimed it", phone=ph("a-billpay", **{"in": 10})),
   V("raw5/m-home.webm", 3.6, 2.4, C["w7"], tag="Home: upcoming PayPal payments", phone=ph("a-home", **{"in": 4}))]),
 G("w8", 6.6, [
   V("raw/pp-disputes.webm", 1.0, 2.0, C["w8"]),
   V("raw/pp-disputes.webm", 24.6, 4.6, C["w8"], sp=1.8)]),
 G("w9", 13.6, [
   V("raw/pp-ask.webm", 0.0, 3.2, C["w9"], sp=3.5, tag="Typing sped up", phone=ph("a-ask-arrears", speed=1.5)),
   V("raw/pp-ask.webm", 16.4, 3.6, C["w9"], tag=DS, crop=ANS),
   V("raw/pp-ask.webm", 20.5, 3.4, C["w9"], sp=4.0, tag="Typing sped up", phone=ph("a-ask-search", speed=2.5)),
   V("raw/pp-ask.webm", 40.4, 3.4, C["w9"], tag=DS, crop=ANS)]),
 G("w10", 5.6, [
   V("raw7/f-talkq.webm", 2.6, 1.9, C["w10"], sp=4.4, tag="Typed here · spoken on the phone", phone=ph("a-talk", **{"in": 2.5})),
   V("raw7/f-talkq.webm", talk.get("ready", 16.9) + 0.1, 3.7, C["w10"], phone=ph("a-talk", **{"in": 5}))]),
 G("w11", 9.0, [
   V("raw5/f-vat.webm", 0.5, 2.2, C["w11"], sp=1.5, phone=ph("a-vat")),
   V("raw5/f-vat.webm", vat.get("back", 30) + 0.5, 1.6, C["w11"], tag="HMRC sandbox test user", phone=ph("a-vat", **{"in": 3})),
   V("raw5/f-vat.webm", vat.get("submit", 40) - 0.3, 1.3, C["w11"], phone=ph("a-vat", **{"in": 5})),
   V("raw5/f-vat.webm", vat.get("receipt", 45) + 0.3, 3.9, C["w11"], tag="HMRC sandbox receipt", phone=ph("a-vat", **{"in": 7}))]),
 G("w12", 5.0, [
   V("raw5/f-reports.webm", 2.8, 3.4, C["w12"]),
   V("raw5/f-reports.webm", 10.5, 1.6, C["w12"], blur=[{"x": 390, "y": 370, "w": 1440, "h": 60}])]),
 G("w13", 4.2, [
   V("raw5/f-files.webm", 0.5, 1.8, C["w13"]),
   V("raw5/f-files.webm", 5.5, 2.4, C["w13"])]),
 # --- what makes it different: three slides, each building up point by point ---------------------------------------
 {"id": "d1", "type": "stills", "srcs": [f"cards/different-{i}.png" for i in range(8)], "weights": [1.3, 4.7, 4.3, 1.9, 0.7, 0.7, 0.7, 3.2], "dur": 17.5, "vo": "d1"},
 {"id": "d2", "type": "stills", "srcs": [f"cards/features-{i}.png" for i in range(1, 6)], "weights": [1.8, 1.2, 1.2, 1.2, 2.4], "dur": 7.8, "vo": "d2"},
 {"id": "d3", "type": "stills", "srcs": [f"cards/built-{i}.png" for i in range(1, 6)], "weights": [3.4, 1.2, 1.0, 1.0, 2.2], "dur": 8.8, "vo": "d3"},
 {"id": "o0", "type": "slate", "dur": 7.6, "vo": "o0", "color": "0x2c1c10",
  "text": "accnomos.com\nTry the demo, no sign-in\ngithub.com/zaytunazs/accnomos\nPayPal sandbox · no real money moved"},
]
for s in segs:
    if s["type"] == "group":
        assert abs(sum(c["dur"] for c in s["children"]) - s["dur"]) < 1e-6, s["id"]
total = round(sum(s["dur"] for s in segs), 2)
assert total <= 170, total
print("total", total)
json.dump({"media_root": ".", "width": 1920, "height": 1080, "fps": 30, "xfade": 0.25, "vo_lead": 0.3, "pip_until": 15.0, "segments": segs},
          open("timeline_paypal_v6.json", "w"), indent=1, ensure_ascii=False)
