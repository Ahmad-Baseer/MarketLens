"""Page-1 text for every index recomposition notice (OCR when the PDF is a scan)."""
import sys, io, time, os
sys.path.insert(0, "backend")
import pandas as pd, pdfplumber, pypdfium2 as pdfium
from mbf.psx.client import PSXClient
n = pd.read_parquet("data/events/psx_notices.parquet")
pat = r"(?:RE.?COMPOSITION|REPLACEMENT|INCLUSION|EXCLUSION).*(?:KSE\W*100|KSE\W*30|KMI\W*30|KSE\W*MEEZAN)|(?:KSE\W*100|KSE\W*30|KMI\W*30).*(?:REPLACEMENT|INCLUSION|EXCLUSION)"
m = n[n.title.str.contains(pat, case=False, regex=True) & n.pdf_url.str.contains(".pdf", na=False) & (n.announced_at >= "2013-06-01")].copy()
m = m[~m.title.str.contains("REVOKED", case=False)]
c = PSXClient(); c.refresh_key()
ocr = None
out = []
for r in m.itertuples():
    fn = f"data/raw/notices/{r.doc_id}.pdf"
    if not os.path.exists(fn):
        time.sleep(0.8)
        resp = c._http.get("https://dps.psx.com.pk" + r.pdf_url)
        if resp.status_code != 200:
            print("fail", r.pdf_url); continue
        open(fn, "wb").write(resp.content)
    tf = f"data/raw/notices/{r.doc_id}.txt"
    if not os.path.exists(tf):
        with pdfplumber.open(fn) as pdf:
            t = pdf.pages[0].extract_text(layout=True) or ""
        if len(t.strip()) < 100:
            if ocr is None:
                from rapidocr_onnxruntime import RapidOCR
                ocr = RapidOCR()
            img = pdfium.PdfDocument(fn)[0].render(scale=3).to_pil()
            res, _ = ocr(img)
            # rebuild lines: group boxes by y, then sort by x, keep big x gaps as wide spaces
            boxes = sorted(((b[0][1], b[0][0], txt) for b, txt, _ in (res or [])))
            lines, cur, cy = [], [], None
            for y, x, txt in boxes:
                if cy is None or abs(y - cy) > 18:
                    if cur: lines.append(cur)
                    cur, cy = [], y
                cur.append((x, txt))
            if cur: lines.append(cur)
            t = "\n".join("".join(" " * max(1, int(x / 25) - len(s)) + txt if False else f"{'':{max(0,int(x/22))}}"[: max(0, int(x/22) - 0)] and txt for x, txt in []) for _ in [])
            t = "\n".join(" | ".join(txt for x, txt in sorted(l)) for l in lines)
            t = "[OCR]\n" + t
        open(tf, "w", encoding="utf-8").write(t)
    out.append((r.announced_at, r.doc_id, r.title))
pd.DataFrame(out, columns=["announced_at", "doc_id", "title"]).to_parquet("data/raw/notices/index_notices.parquet")
print(len(out))
