# Builds timeline_paypal_v5.json from the capture marks. Run in the media folder (raw/, raw5/, raw6/, cards/): python3 make_timeline_v5.py
import json, sys
C = {
 "h1": "PayPal Transaction Search · gross / fee / net · a sale with no invoice waits for your VAT choice",
 "ag": "AG Grid Community · Power grid: bulk approve, totals, plain-English filters",
 "h2": "AI search: the AI reads the question · code searches your books and PayPal · exact figures",
 "h3": "PayPal Balances API · PayPal's figure as of its last refresh",
 "h4": "PayPal Payouts API · you approve each payout · posts only when PayPal confirms",
 "h5": "PayPal Disputes API · SAMPLE dispute in the demo: nothing sent to PayPal",
 "ea": "Receipts: the AI reads the photo · code checks totals and VAT · you approve",
 "eb": "Bank feed by Open Banking (TrueLayer's test bank) · lines arrive · matched to your books",
 "ec": "Invoices from plain words · PayPal pay link",
 "ed": "VAT: nine boxes by code · filed to HMRC's sandbox · HMRC's receipt",
 "ee": "Reports: profit and loss, who owes you · export to your drive",
 "ef": "Talk to Accnomos: type or speak · you approve each card",
 "eg": "Jobs: costs, hours and margin",
 "eh": "Your books, in your own OneDrive or Google Drive",
}
def ph(name, **kw): return {"src": f"android/{name}.mp4", "name": name, **kw}
def V(src, i, d, cap=None, sp=None, tag=None, blur=None, phone=None):
    s = {"type": "video", "src": src, "in": i, "dur": d}
    if cap: s["caption"] = cap
    if sp: s["speed"] = sp
    if tag: s["tag"] = tag
    if blur: s["blur"] = blur
    if phone is not None: s["phone"] = phone
    return s
RECEIPT_BLUR = [{"x": 400, "y": 395, "w": 1360, "h": 140}]
segs = [
 {"id": "i0", "type": "group", "dur": 10.4, "vo": "i0", "pip": "presenter_intro.mp4", "pip_lead": 0.0, "children": [
   V("raw5/m-home.webm", 0.3, 3.4, phone=ph("a-home")),
   V("raw/pp-sync.webm", 11.0, 3.5),
   V("raw/m-review.webm", 1.4, 3.5, phone=ph("a-review"))]},
 {"id": "pr", "type": "still", "src": "cards/problem.png", "dur": 4.8, "vo": "pr"},
 {"id": "hw", "type": "stills", "srcs": [f"cards/how-it-works-{i}.png" for i in (1, 2, 3, 4)], "dur": 5.6, "vo": "hw"},
 {"id": "h1", "type": "group", "dur": 18, "vo": "h1", "children": [
   V("raw/pp-sync.webm", 0.0, 3.4, C["h1"], tag="PayPal sandbox", phone=ph("a-sync")),
   V("raw/pp-sync.webm", 10.4, 14.6, C["h1"], tag="PayPal sandbox", phone=ph("a-sync", **{"in": 3}))]},
 {"id": "ag", "type": "group", "dur": 9.5, "vo": "ag", "children": [
   V("raw/pp-grid.webm", 2.0, 4.0, C["ag"], sp=1.3, tag="Demo sample history"),
   V("raw/pp-grid.webm", 12.8, 1.3, C["ag"], tag="Demo sample history"),
   V("raw/pp-grid.webm", 21.2, 2.0, C["ag"], sp=2.5, tag="Typing sped up"),
   V("raw/pp-grid.webm", 34.1, 2.2, C["ag"], tag="Demo sample history")]},
 {"id": "h2", "type": "group", "dur": 14.5, "vo": "h2", "children": [
   V("raw/pp-ask.webm", 0.0, 3.7, C["h2"], sp=3.0, tag="Typing sped up", phone=ph("a-ask-arrears")),
   V("raw/pp-ask.webm", 16.4, 3.5, C["h2"], tag="Demo sample history", phone=ph("a-ask-arrears", **{"in": 3})),
   V("raw/pp-ask.webm", 20.5, 4.5, C["h2"], sp=3.0, tag="Typing sped up", phone=ph("a-ask-search")),
   V("raw/pp-ask.webm", 40.4, 2.8, C["h2"], tag="Demo sample history", phone=ph("a-ask-search", **{"in": 4}))]},
 {"id": "h3", "type": "video", "src": "raw/pp-tieout.webm", "in": 0.8, "dur": 8, "vo": "h3", "crop": [380, 300, 1520, 855], "caption": C["h3"], "tag": "PayPal sandbox"},
 {"id": "h4", "type": "group", "dur": 20, "vo": "h4", "children": [
   V("raw5/pp-billpay.webm", 0.5, 6.0, C["h4"], sp=1.25, tag="PayPal sandbox", phone=ph("a-billpay")),
   V("raw5/pp-billpay.webm", 8.0, 4.5, C["h4"], tag="PayPal sandbox", phone=ph("a-billpay", **{"in": 5})),
   V("raw5/pp-billpay.webm", 102.5, 5.0, C["h4"], tag="About 90 s later · sandbox payee has no PayPal account yet", phone=ph("a-billpay", **{"in": 10})),
   V("raw5/m-home.webm", 3.6, 4.5, C["h4"], tag="Home: upcoming PayPal payments", phone=ph("a-home"))]},
 {"id": "h5", "type": "group", "dur": 8, "vo": "h5", "children": [
   V("raw/pp-disputes.webm", 1.0, 2.5, C["h5"]),
   V("raw/pp-disputes.webm", 24.6, 5.5, C["h5"], sp=1.5)]},
 {"id": "ai", "type": "still", "src": "cards/ai-in-action.png", "zoom": 0.03, "dur": 5, "vo": "ai"},
 {"id": "ea", "type": "group", "dur": 8, "vo": "ea", "children": [
   V("raw6/f-receipt.webm", 0.5, 2.0, C["ea"], sp=2.0, phone=ph("a-capture")),
   V("raw6/f-receipt.webm", 9.9, 1.6, C["ea"], tag="Reading sped up", phone=ph("a-capture", **{"in": 3})),
   V("raw6/f-receipt.webm", 43.0, 2.6, C["ea"], phone=ph("a-review")),
   V("raw6/f-receipt.webm", 52.6, 1.8, C["ea"], phone=ph("a-review", **{"in": 3}))]},
 "BANK",
 {"id": "ec", "type": "group", "dur": 7, "vo": "ec", "children": [
   V("raw5/f-invoice.webm", 2.0, 2.2, C["ec"], sp=2.0, tag="Typing sped up"),
   V("raw5/f-invoice.webm", 62.4, 1.6, C["ec"]),
   V("raw5/f-invoice.webm", 66.2, 1.5, C["ec"], tag="Demo: email not really sent"),
   V("raw5/pp-invoice.webm", 6.3, 1.7, C["ec"], tag="PayPal sandbox")]},
 "VAT",
 {"id": "ee", "type": "group", "dur": 5, "vo": "ee", "children": [
   V("raw5/f-reports.webm", 2.8, 3.4, C["ee"]),
   V("raw5/f-reports.webm", 10.5, 1.6, C["ee"], blur=[{"x": 390, "y": 370, "w": 1440, "h": 60}])]},
 {"id": "ef", "type": "group", "dur": 6, "vo": "ef", "children": [
   V("raw5/f-talk.webm", 2.0, 2.8, C["ef"], sp=2.5, tag="Typed here; voice on the phone", phone=ph("a-talk")),
   V("raw5/f-talk.webm", 11.2, 1.7, C["ef"], phone=ph("a-talk", **{"in": 3})),
   V("raw5/f-talk.webm", 15.4, 1.5, C["ef"], phone=ph("a-talk", **{"in": 6}))]},
 {"id": "eg", "type": "video", "src": "raw/m-jobs.webm", "in": 0.0, "dur": 5, "speed": 0.6, "vo": "eg", "caption": C["eg"]},
 {"id": "eh", "type": "group", "dur": 5, "vo": "eh", "children": [
   V("raw5/f-files.webm", 0.5, 2.0, C["eh"]),
   V("raw5/f-files.webm", 5.5, 3.0, C["eh"])]},
 {"id": "fl", "type": "still", "src": "cards/features.png", "dur": 3},
 {"id": "o0", "type": "slate", "dur": 7.4, "vo": "o0", "pip": "presenter_outro.mp4", "pip_lead": 0.0, "color": "0x2c1c10",
  "text": "accnomos.com\nTry the demo, no sign-in\ngithub.com/zaytunazs/accnomos\nPayPal sandbox · no real money moved"},
]
# bank and vat groups are filled from their marks (see below)
bank = json.load(open("raw5/f-bank.marks.json"))["marks"] if len(sys.argv) < 2 else {}
vat = json.load(open("raw5/f-vat.marks.json"))["marks"]
B = lambda k, d: bank.get(k, d)
segs[segs.index("BANK")] = {"id": "eb", "type": "group", "dur": 8, "vo": "eb", "children": [
   V("raw5/f-bank.webm", 0.2, 1.8, C["eb"], tag="TrueLayer sandbox · test data", phone=ph("a-bank"),
     blur=[{"x": 420, "y": 440, "w": 1430, "h": 270}, {"x": 420, "y": 845, "w": 1430, "h": 60}]),
   V("raw5/f-bank.webm", B("fetched", 26) - 0.4, 2.2, C["eb"], tag="TrueLayer sandbox · test data", phone=ph("a-bank", **{"in": 3})),
   V("raw5/f-bankmatch.webm", 3.0, 4.0, C["eb"], tag="Exact match confirmed", phone=ph("a-bank", **{"in": 6}))]}
segs[segs.index("VAT")] = {"id": "ed", "type": "group", "dur": 8, "vo": "ed", "children": [
   V("raw5/f-vat.webm", 0.5, 2.0, C["ed"], sp=1.5, phone=ph("a-vat")),
   V("raw5/f-vat.webm", vat.get("back", 30) + 0.5, 1.5, C["ed"], tag="HMRC sandbox test user", phone=ph("a-vat", **{"in": 3})),
   V("raw5/f-vat.webm", vat.get("submit", 40) - 0.3, 1.2, C["ed"], phone=ph("a-vat", **{"in": 5})),
   V("raw5/f-vat.webm", vat.get("receipt", 45) + 0.3, 3.3, C["ed"], tag="HMRC sandbox receipt", phone=ph("a-vat", **{"in": 7}))]}
for s in segs:
    if s["type"] == "group":
        assert abs(sum(c["dur"] for c in s["children"]) - s["dur"]) < 1e-6, s["id"]
print("total", round(sum(s["dur"] for s in segs), 2))
json.dump({"media_root": ".", "width": 1920, "height": 1080, "fps": 30, "xfade": 0.25, "vo_lead": 0.3, "segments": segs},
          open("timeline_paypal_v5.json", "w"), indent=1, ensure_ascii=False)
