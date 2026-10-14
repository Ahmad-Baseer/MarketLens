# Statement extractor baseline: is a classic pipeline good enough?

*A rule-based extractor (pdfplumber, pypdfium2 and RapidOCR only, with no layout or table models) was run on 40 PSX
report PDFs. Its unconsolidated balance-sheet and P&L values were compared with the AKD seed
(`data/seed/akd/statements.parquet`). A value "agrees" if it is within 0.5 %, or within one display unit
(Rs 1,000 for statement lines, Rs 0.01 for EPS). AKD is noisy, so the main measure is agreement rate, not accuracy.
Reproduce with `python -m mbf.extract.bakeoff sample|download|run`. Outputs go to `data/research/extract/`.*

## Bottom line

| question | answer |
|---|---|
| Balance sheet, PDFs with a text layer (25 of 40) | **Good enough.** Equity, assets, share capital, current/non-current totals and liabilities agreed with AKD on 25 of 25. Cash, short-term borrowings and long-term debt had no extraction errors. The one long-term-debt miss is an AKD definition, and the few gaps are missing labels. |
| Balance sheet, statement read by OCR (15 of 40) | **Usable with a gate.** Equity and assets agree on 14 of 15. The failures come from OCR digit and separator errors. The extractor's own consistency checks flag the large ones (MSOT, GATM); a 0.7 % digit error (INKL) passes them. |
| P&L | Extraction works: PBT is 100 % on text pages. Most disagreements come from the **ground truth's period basis**. AKD stores single quarters; PDFs print cumulative figures. |
| Heavier models? | **Not for text PDFs.** Consider them only for the OCR path: scanned filings and garbled text layers. Even there, try the cheap fixes listed below first. |

Headline, all 40 PDFs (equity / assets / share capital / cash / ST borrowings / LT debt together): **205 of the 217 AKD values
(94 %) matched**, and 205 of the 208 values that were extracted (99 %). For 36 of 40 reports, equity, assets and share capital
**all** agree with AKD.

## Method

`backend/mbf/extract/statements.py` handles one PDF in six steps:

1. **Page text and scan detection.** pypdfium2 reads page text in about 1 ms per page. A page counts as image-only if it has
   almost no text, or if its text is control characters from a font without a usable encoding (ADMM).
2. **Finding the statement.** Pages are scored on line-item vocabulary, figure density, and penalties for "consolidated",
   multi-year summaries ("six years at a glance", horizontal/vertical analysis) and notes. A page is only picked if a line
   in its **top third** *is* the title, optionally prefixed, e.g. "Unconsolidated condensed interim statement of financial
   position". This is necessary because notes pages share the vocabulary and mention "balance sheet" mid-sentence. Titles
   are matched with spaces removed ("STATEMENTOF FINANCIALPOSITION"), and with fuzzy matching for OCR
   ("STATEMENTOFRNANCIALPOSITION"). When no text page has a title, scanned pages are OCR'd in page order: first a 0.1 s
   layout check, then a few title boxes from the top quarter, and only then the first matching page at scale 2.5. A balance
   sheet continuing onto the next page is added automatically.
3. **Words to lines.** pdfplumber supplies words; RapidOCR boxes are split into words. Words are grouped into lines.
   Several layouts are split before parsing:
   - Facing-page spreads (AGIL has the BS and P&L on one landscape page) are split at the gutter.
   - Old-format sheets with liabilities on the left and assets on the right (PPVC) are split into two sides.
   - A wide single statement (TRIPF) is *not* split.
4. **Columns.** Figures are right-aligned, so value columns are clusters of number right edges. Note references are small
   numbers left of the first column. Centred EPS figures are placed by column span. The current period is the first column
   unless the header years say otherwise. A page with a garbled text layer, or a balance sheet that does not add up, is
   re-read with OCR and the better result is kept.
5. **Section state machine.** Section headers (equity, non-current and current liabilities and assets) drive a stack of
   figures, and labels map to fields through a synonym table. Most PSX statements print section totals as **unlabelled**
   numbers, so the machine resolves these:
   - A bare figure equal to the sum of the items above it is a subtotal. The last one in a section is the section total.
   - A sponsor or holding-company loan printed after the equity subtotal stays outside equity, as AKD counts it.
   - Items left after the last subtotal (PPE subtotalled, then investments listed bare) mean the section total is their sum.
   - Total assets is the bare figure equal to non-current plus current assets.
   - Missing totals are derived from the identities.
6. **Units.** "Rupees in '000", "Amounts in thousand", "Rs in million" or a bare "Rupees" header are normalised to thousands.
   EPS stays in rupees. If no unit is printed, it is guessed from figure size. A P&L whose unit was misread 1,000x is caught
   by comparing EPS with 10 × PAT / share capital, since EPS is unit-free.

Each extracted value carries `method` (text|ocr) and `how`:
- `label`: a mapped label.
- `subtotal`: an unlabelled figure verified by its sum.
- `subtotal?`: unverified.
- `sum`: the sum of the section's items.
- `derived`: computed from identities.

The `how` tag works as a confidence signal: verified subtotals agree 99 % (170 of 171), unverified `subtotal?` only 64 % (7 of 11).

## Sample

Seed 7, drawn from 9,872 eligible reports. A report was eligible if AKD has its period_end with equity, assets and share
capital, its period ends 2019–2025, and it is not from a bank, insurer, modaraba, fund, ETF, leasing company, investment
bank, REIT or debt issue. The draw was capped at 20 per report type, 3 per sector and 1 per company. A (symbol, period) with
several PDFs was skipped, since those are mostly annual reports split into parts. Annual reports are listed only by fiscal
year, so they were matched to AKD's Q4 period_end within that calendar year and before the posting date.

| | |
|---|---|
| reports | 40 (20 annual; 20 quarterly: 6 Q1, 8 half-year, 6 Q3), 40 companies |
| sectors | 21, from textiles, sugar, glass, power, chemicals, cement, refinery, fertilizer, autos, pharma, tech, … |
| period ends | 2019: 5, 2020: 9, 2021: 7, 2022: 7, 2023: 7, 2025: 5 (none in 2024, by chance) |
| PDFs by text layer | 23 text, 10 mixed (some pages image-only), 7 fully scanned |
| statement pages read as | balance sheet: 25 text, 15 OCR; P&L: 28 text, 12 OCR |

All 40 PDFs (217 MB) downloaded without errors or challenge pages, using `MBF-Signals/0.1 (personal research)` with one
request every 2 s. They are in `data/raw/reports/<report_id>.pdf`.

## Results

### Per field, all 40 PDFs

Column meanings:
- **coverage**: extracted at all.
- **agreement**: matches / extracted.
- **accuracy**: matches / AKD values.

| field | AKD has | extracted | matches | coverage | agreement | accuracy |
|---|---|---|---|---|---|---|
| equity | 40 | 40 | 39 | 100% | 98% | 98% |
| share_cap | 40 | 38 | 38 | 95% | 100% | 95% |
| assets | 40 | 40 | 39 | 100% | 98% | 98% |
| liabilities | 40 | 39 | 36 | 98% | 92% | 90% |
| nc_assets | 40 | 40 | 39 | 100% | 98% | 98% |
| c_assets | 40 | 40 | 39 | 100% | 98% | 98% |
| nc_liabilities | 32 | 32 | 31 | 100% | 97% | 97% |
| c_liabilities | 40 | 39 | 38 | 98% | 97% | 95% |
| cabb (cash & bank) | 40 | 38 | 38 | 95% | 100% | 95% |
| st_borr | 29 | 27 | 27 | 93% | 100% | 93% |
| lt_debt | 28 | 25 | 24 | 89% | 96% | 86% |
| reserves | 16 | 8 | 7 | 50% | 88% | 44% |
| sales | 37 | 33 | 31 | 89% | 94% | 84% |
| pbt | 39 | 39 | 37 | 100% | 95% | 95% |
| pat | 40 | 39 | 35 | 98% | 90% | 88% |
| eps | 40 | 39 | 34 | 98% | 87% | 85% |

`reserves` in AKD is one specific line, filled for only 16 of 40 reports, so low coverage is expected. Income values count as
a match if they agree with either the AKD quarter or the AKD year-to-date sum of quarters.

### Text layer vs OCR

Grouped by how the statement page was actually read. One "mixed" PDF can have a text P&L and a scanned balance sheet.

| field | text: extracted / AKD | text: agreement | OCR: extracted / AKD | OCR: agreement |
|---|---|---|---|---|
| equity | 25 / 25 | 100% | 15 / 15 | 93% |
| share_cap | 25 / 25 | 100% | 13 / 15 | 100% |
| assets | 25 / 25 | 100% | 15 / 15 | 93% |
| liabilities | 25 / 25 | 100% | 14 / 15 | 79% |
| nc_assets / c_assets | 25 / 25 | 100% / 100% | 15 / 15 | 93% / 93% |
| nc / c liabilities | 19 / 19, 25 / 25 | 100% / 100% | 13 / 13, 14 / 15 | 92% / 93% |
| cabb | 24 / 25 | 100% | 14 / 15 | 100% |
| st_borr | 16 / 17 | 100% | 11 / 12 | 100% |
| lt_debt | 15 / 16 | 93% | 10 / 12 | 100% |
| sales | 26 / 27 | 100% | 7 / 10 | 71% |
| pbt | 27 / 27 | 100% | 12 / 12 | 83% |
| pat | 28 / 28 | 93% | 11 / 12 | 82% |
| eps | 28 / 28 | 86% | 11 / 12 | 91% |

### Report type

Annual reports agree 95–100 % on every balance field. The only annual miss is MSOT, a scanned 156-page report. Quarterly
reports agree 89–100 % on balance fields: `liabilities` 89 % and `lt_debt` 90 % (the FRCL definition). Income agreement is
94–100 % for annual reports but lower for quarterlies (EPS 79 %, PAT 84 %), for the period-basis reasons below.

### Speed

Timed on an 8-core CPU, which was shared with other work during the final run.

| | PDFs | mean s | median s | max s |
|---|---|---|---|---|
| no OCR needed | 25 | 4.1 | 2.3 | 15.5 |
| OCR on statement pages | 15 | 50 | 40 | 125 |
| all | 40 | 21.2 | 7.0 | 125 |

An earlier run of nearly the same code on a less loaded machine averaged 14.5 s per PDF (median 4.6 s). Text-page work is
a few seconds even for 478-page annual reports. OCR costs about 10 s per full statement page, because recognition dominates.
The slowest PDFs are those with a garbled text layer that is read twice (POWER) and the 156-page scanned MSOT. Avoiding
wasted OCR passes matters most: scanning every page of a 156-page scanned report would take minutes.

## Typical failures

**Extraction errors (OCR path):**
- **MSOT annual 2023 (fully scanned):** OCR misreads thousand separators.
  - Non-current assets came out as 15,495 against AKD's 15,495,070 (1,000x); current liabilities as 33,936 against 32,984,890.
  - Total assets (55.2) and P&L figures are also off.
  - None of the section sums verify, so every subtotal is `subtotal?`, and the balance identities fail. The extractor knows
    this result is bad.
- **GATM Q3 FY22 (scanned):** OCR missed lines inside non-current liabilities. It found 836,675 against 22,164,360, flagged
  as `subtotal?` (partial sum). P&L figures are 1–6 % away from AKD's year-to-date. That could be OCR digits or AKD's
  quarter sums; it was not resolved.
- **INKL Q1 FY24 (scanned):** one wrong digit gave equity 177,757 against 176,598 (0.7 %).
- **Missed fields on OCR pages:** share capital on HUBC and CPHL, and sales on EXIDE and ADMM.

**Layouts that broke early versions and are now handled** (each is a pattern that will recur across the ~21k PDFs):
- Overprinted text layers ("218,,232488,,098495" in NRL; garbled in POWER) are detected by the share of unparseable figures
  and re-read with OCR.
- Fonts with no Unicode map come out of pdfplumber as `(cid:72)(cid:65)…` (HAFL). These decode to plain ASCII.
- A page header stored last in the content stream (PPVC) or after a rotated sidebar (DNCC) is handled by reading titles by
  position (top third), not text order.
- A title split across two scanned pages of one spread (AASM: "…STATEMENT OF" / "FINANCIAL POSITION").
- Net sales printed as a bare subtotal under "Less: sales tax" (CSAP), and gross vs net revenue in general.
- Profit "from refinery operations" followed by the year's total, with EPS split by segment (ATRL).
- "Revenue from contract with customer", singular (NCPL).
- Sections with no closing subtotal (SAZEW non-current liabilities; ATRL non-current assets after a PPE subtotal).
- Equity with a director/holding-company loan printed after its subtotal (DNCC, BGL).
- "(Amounts in thousand except EPS)" headers (EPQL), and a P&L unit misread on a scanned page (ADMM, caught by the EPS
  unit check).

**Not extraction errors (ground truth or definition):**
- **FRCL long-term debt.** AKD records 622,295, which is "Loan from related parties". The statement's "Long term financing"
  line is 20,852. AKD picks one non-current borrowing line, not always the same one.
- **Sales with no sales line.** AATM has rental income only and HAFL investment income only, yet AKD files these under
  `sales`. There is no "sales" label to map.
- **EPS and PAT for quarterlies (ITTEFAQ, KSTM, MIRKS).** See the ground-truth issues below.

## Ground-truth (AKD) issues found

1. **Income values are single quarters; Q4 is derived (annual minus nine months).** An annual PDF never matches AKD Q4
   directly (DNCC: PDF FY20 PAT −695,056 vs AKD Q4 −207,774). The bake-off therefore also compares with the sum of AKD's
   quarters. Every annual income match came from that year-to-date sum; none matched Q4 itself.
2. **AKD's quarters do not always add up to the company's own cumulative figure.** ITTEFAQ H1 FY26 PAT is −205,959 in the
   PDF. AKD has Q2 −124,373, which exactly matches the PDF's quarter column, but Q1 −86,770 gives a sum of −211,143. AKD's
   Q1 looks restated or wrong. KSTM is similar.
3. **Summed quarterly EPS ≠ cumulative EPS when the share count changes.** MIRKS FY23 EPS is 18.03 in the PDF. AKD's quarters
   (13.40 + 0.20 − 0.12 + 2.95) sum to 16.43, while PAT agrees. Some single AKD EPS values also look wrong, e.g. LUCK FY24
   Q3 = 3.37 although PAT/shares ≈ 16.8.
4. **Duplicate keys with different figures.** About 0.4 % of (symbol, period_end, field) keys appear twice, under two
   fiscal-year labels. For example, AGL 2022-03-31 has assets of 67.5 bn (year 2022) and 81.3 bn (year 2023, apparently a
   later period filed under this date). The bake-off keeps the majority year at the date. The PDF agrees with the 2022 row.
5. **Definitions differ by line.** In AKD:
   - `liabilities` = non-current + current, excluding sponsor loans printed under equity.
   - `equity` excludes such loans (DNCC: −1.80 bn, not the 0.73 bn line that includes the loan).
   - `lt_debt` is one borrowing line, not total long-term borrowing.

   The extractor mirrors these choices. Any new consumer of the data must pick its own definitions deliberately.

## Recommendation

- **Balance sheet from text-layer PDFs: use the baseline.** It is good enough for equity, assets, borrowings and cash.
  Coverage and agreement were 100 % on 25 of 25 statements, apart from one AKD definitional difference. It costs a few
  seconds per PDF with no ML dependencies. Gate each result on what the extractor already reports:
  - accept when the balance identities hold (`bs_quality`: nc + c assets = total assets, and equity + liabilities = total);
  - accept when the section totals are `subtotal` or `label`, not `subtotal?`;
  - send everything else to a review queue.
- **OCR path (scanned or garbled; 15 of 40 here, so not rare): heavier models are justified, but only here, and only after
  cheap fixes.** RapidOCR's baseline gets equity and assets right on 14 of 15. The identity checks catch the gross
  failures, but not a single wrong digit that still adds up.
  The residual errors are digit and separator misreads and dropped lines, which is where better OCR helps. Before adding
  PaddleOCR/PP-Structure, docling or a table model, try:
  1. re-OCR only the figure column, at higher scale, with a digits-only character set;
  2. retry a statement that fails the identities at scale 3–4;
  3. measure again on a larger sample (~200 reports) to size the residual.
  If more than ~5 % of OCR statements still fail the gate, a table-structure model for scanned pages is the next step.
- **P&L: the main gap is period labelling, not the model.** Extract both the cumulative and the quarter columns for
  quarterlies (the column positions are already found; the order varies, e.g. EPQL puts the quarter first) and store
  them with explicit period lengths read from the header. Then compare like with like. Do not treat AKD's derived Q4 or
  summed EPS as truth.
- **Coverage gaps worth a small rule each:**
  - "Revenue"-type labels for non-trading companies (rental or investment income);
  - long-term debt lines named after the lender ("Loan from related parties");
  - share-capital labels that OCR breaks.

## Files

- `backend/mbf/extract/statements.py`: the extractor. `extract(pdf) -> (tidy frame, DocInfo)`.
- `backend/mbf/extract/bakeoff.py`: sampling, polite download, scoring, and these tables.
- `backend/tests/test_extract.py`: tests for number parsing, units, label mapping, subtotal logic, layouts and the EPS unit check.
- `data/research/extract/{sample,extracted,scored,docs}.csv`: the outputs of this run.
