# Source-backed PDF extraction and acceptance

Processing all pages is a completeness check, not an OCR accuracy gate. In particular,
`manifest.complete=true` does not verify legal text, scores, stars, or merged cells.
Never advance acceptance on that flag alone.

## Reproduce without writing generated files into the release

Install the project OCR/dev dependencies and Tesseract with Vietnamese and English
traineddata. Set `TESSDATA_PREFIX` to the actual language-data directory. The cell
experiment below used official `tessdata_best/eng.traineddata` and
`tessdata_best/vie.traineddata`, not just the `pytesseract` Python package.

```powershell
$ocopAudit = Join-Path $env:TEMP 'ocop-pdf-audit'
python tools/cli.py debug audit-ocop -- --output "$ocopAudit/source_audit.json"
python tools/cli.py debug process-ocop-pdf -- --engine tesseract --table-engine opencv --workers 3 --output "$ocopAudit/pages" --cache "$ocopAudit/cache"
python tools/audit_pdf_quality.py --gold tests/fixtures/ocop_pdf_table_gold.jsonl --output "$ocopAudit/table_quality.json"
python tools/evaluate_pdf_cells.py --artifacts "$ocopAudit/pages" --split dev --output "$ocopAudit/cells_dev.json"
# Run the held-out split once after development decisions are frozen.
python tools/evaluate_pdf_cells.py --artifacts "$ocopAudit/pages" --split test --output "$ocopAudit/cells_test.json"
$env:OCOP_PDF_ARTIFACT_DIR = "$ocopAudit/pages"
python -m pytest tests/ocop -q
```

The explicit artifact directory makes missing/incomplete integration inputs fail,
rather than silently skipping the real-corpus test. Source-only installations may
still skip that optional test when no artifact directory is supplied.

## Root fixes and their evidence

**Problem:** native colspan owners were always emitted with `colspan=1`; rotated
native text could be quarantined or attached to incorrect coordinates; artifacts
did not independently identify their source bytes; changing Tesseract traineddata
did not change the old cache key; page OCR omitted scoring-column text.

**Root cause:** native table slots encode ownership by sorted cell left edges;
`get_text()` returns unrotated coordinates while raster/OCR use rendered page
coordinates; source identity and runtime model bytes were only partially represented
in cache lineage. Page segmentation and table rulings interfere with isolated digits.

**Evidence from original data:** the locked corpus contains 12 PDFs / 583 pages,
315 OCR candidates. QD26/2026 PDF page 28 (printed page 12), independently rendered
with Poppler, contains 25 numeric score cells and two deliberately empty score cells.
The initial page OCR retained none of those 25 scores. Native corpus inspection also
found geometric horizontal merges whose spans were absent from emitted metadata.
Synthetic real-PDF regressions separately reproduce rotations 90/180/270 and colspan
ownership without OCR mocks. Malformed overlapping HTML spans are rejected.

**Official documentation:**
[PyMuPDF coordinates](https://pymupdf.readthedocs.io/en/latest/page.html),
[Tesseract segmentation, borders and table limitations](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html),
[Tesseract model families](https://tesseract-ocr.github.io/tessdoc/Data-Files.html).
The installed PyMuPDF 1.27.2.2 table implementation was inspected directly to verify
the slot ordering. Tesseract engine 5.4.0 and pytesseract 0.3.13 were exercised.

**Similar implementations:**
[OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF/blob/main/src/ocrmypdf/builtin_plugins/tesseract_ocr.py)
uses explicit OCR timeouts;
[Camelot Lattice](https://github.com/camelot-dev/camelot/blob/master/camelot/parsers/lattice.py)
separates raster rulings and cell structure. Neither establishes score correctness
for the OCOP corpus merely by finding a table.

**Relevant paper:**
[PubTables-1M](https://arxiv.org/abs/2110.00061) motivates independent cell structure,
location and content evaluation, including merged-cell ambiguity. Its scientific
article dataset does not establish Vietnamese legal OCR performance. The
[GriTS implementation](https://github.com/microsoft/table-transformer/blob/main/src/grits.py)
was inspected; this repository's small coordinate-anchored score check is not GriTS.

**Candidate solutions:** whole-page line removal; isolated-cell OCR; PaddleOCR
mobile/medium inference; geometry fixes without changing OCR models.

**Selected solution:** transform native text into rendered page coordinates; derive
native colspan from actual slot geometry; retain per-page source SHA-256; hash the
engine and resolved Vietnamese/English/orientation traineddata for cache identity;
use border removal plus raw-line OCR for missing/invalid numeric cells. No numeric
whitelist is used. Ambiguous readings cannot populate primary cell text. Original
OCR remains in `text_original` when a crop reading is adopted. Every added reading
and recovered cell remains `needs_review`, never a verified score.

**Regression risks:** narrow non-score columns, digits touching rulings, skewed
row geometry, merged scan cells, valid-looking but incorrect numeric OCR, and
description text omitted by whole-page segmentation. Glyph-level border removal
damaged Vietnamese descriptions in experiments and was excluded from the fix.
Unwarping/orientation-changing model output must not be treated as source coordinates
without an inverse mapping. General raster rowspan/colspan recovery remains unverified.

**Measured results:** the 5-page existing table-presence fixture found 4/4 table pages,
1/1 non-table page and the expected column counts on 4/4 tables. The isolated-cell
development experiment on QD26 page 28 recovered 25/25 numeric cells and retained
2/2 empty cells in 8.64 seconds, versus 0/25 numeric cells in 4.09 seconds initially.
These runs also changed from the initial language models to `tessdata_best`, so this
is not a preprocessing-only ablation. The first held-out run on page 29 recovered
29/32 numeric cells; three invalid OCR strings prevented acceptance. Later fixes
must be reported with their own parser/model signatures and separate regression results.
The fixtures explicitly identify agent visual transcription and lack of domain-expert
verification; two pages do not establish whole-corpus quality or full acceptance.

## Model experiments and remaining acceptance work

PaddleOCR 3.7.0 / PaddlePaddle 3.3.1 CPU inference reproduced the upstream
[oneDNN attribute-conversion failure](https://github.com/PaddlePaddle/Paddle/issues/79749).
The mobile model ran with oneDNN acceleration disabled, but many Vietnamese diacritics
were missing on the inspected page. It was not selected as a production accuracy fix.
Global line removal and whole-cell border component removal did not safely recover
all legal descriptions. A successful numeric fixture is insufficient while those
critical descriptions remain missing or corrupted.

Acceptance still requires independent legal-description/CER and merged-cell labels
covering the actual source families, successful held-out critical-cell checks,
and a final source-locked full-corpus run with no relevant integration skips.
Model weights, PDF renderings, caches and JSON reports stay outside the release.

## Optional PaddleOCR-VL document parsing

PaddleOCR-VL is an optional local candidate extractor for scanned text and table
layout. Install `.[paddle_vl]`, provision the VL recognition and layout model
directories separately, then set `OCOP_PADDLE_VL_MODEL_DIR` and
`OCOP_PADDLE_VL_LAYOUT_MODEL_DIR` to those directories. The pipeline requires
both directories before it starts and passes them to the native backend, so it
does not fetch weights or send page images to a remote inference service. It
hashes every model file into the page-cache signature; changing weights forces
fresh page artifacts. `OCOP_PADDLE_VL_VERSION` supports `v1.5` or `v1.6`.

```powershell
python -m pip install -e '.[paddle_vl]'
$env:OCOP_PADDLE_VL_VERSION = 'v1.6'
$env:OCOP_PADDLE_VL_MODEL_DIR = 'D:/models/PaddleOCR-VL-1.6'
$env:OCOP_PADDLE_VL_LAYOUT_MODEL_DIR = 'D:/models/PP-DocLayoutV3'
$ocopVlAudit = Join-Path $env:TEMP 'ocop-paddle-vl'
python tools/cli.py debug process-ocop-pdf -- --engine paddle_vl --table-engine paddle_vl --workers 1 --output "$ocopVlAudit/pages" --cache "$ocopVlAudit/cache"
```

The adapter uses fixed low-variance decoding and preserves PaddleOCR-VL's block
reading order. A block without usable geometry is retained with `bbox: null` and
a warning; it is never assigned a guessed location. HTML tables keep their
source HTML and parsed cells, with individual cell boxes left null when the
model does not return them. OCR/VLM text, including numbers, stars and table
descriptions, remains `needs_review`; the model does not supply a legal
verification or a usable confidence score. Check critical text and table cells
against the source PDF before relying on them. Evidence spans and citations
carry the PDF page, block/table box, evidence unit ID and source SHA-256. The
[PaddleOCR-VL output contract](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/PaddleOCR-VL.en.md)
documents the block boxes and reading-order fields consumed by this adapter.

## Optional EasyOCR and VietOCR

Install `.[easyocr]` for EasyOCR 1.7.2 and VietOCR 0.3.13. Both adapters run on CPU.
Provision EasyOCR's official CRAFT and Latin recognition models in its external
model directory before extraction; runtime downloads are disabled. For the hybrid,
set `OCOP_VIETOCR_WEIGHTS` to a local official `vgg_seq2seq.pth` checkpoint. Set
`OCOP_VIETOCR_MODEL=vgg_transformer` with its matching `vgg_transformer.pth` to
select the alternative upstream recognizer. Checkpoints and architectures must match. The
inference configuration is derived from the upstream VietOCR base/seq2seq configs;
ImageNet pretraining is disabled because the complete checkpoint is loaded.
No model bytes belong in the repository. Missing models fail preflight explicitly.

```powershell
$env:OCOP_VIETOCR_WEIGHTS = 'C:/models/vietocr/vgg_seq2seq.pth'
$env:OMP_NUM_THREADS = '1'
python tools/cli.py debug process-ocop-pdf -- --engine easyocr_vietocr --table-engine opencv --workers 1 --output "$ocopAudit/easy-viet-pages" --cache "$ocopAudit/easy-viet-cache"
# --engine easyocr uses EasyOCR recognition as well as detection.
# --refine-score-cells additionally requires Tesseract and its language models.
```

**Problem/root cause:** EasyOCR's detector can join vertically adjacent table
digits. On the original QD26 page 28, one detected region spanned two separately
ruled score rows. Recognition returned a single digit and midpoint assignment
placed it in the wrong row. Horizontal and free-form detections also arrive in
different groups; their raw list order is not document reading order.

**Original-data evidence:** the independent Poppler rendering shows distinct
scores in those rows. Eight additional development descriptions were transcribed
directly from that image into `ocop_pdf_table_text.json`, including percentages,
conditions and criterion titles; they were not generated from parser output.

**Official documentation/similar implementation:**
[EasyOCR detection/cropping contracts](https://www.jaided.ai/easyocr/documentation/),
[EasyOCR 1.7.2 crop implementation](https://github.com/JaidedAI/EasyOCR/blob/v1.7.2/easyocr/utils.py),
[VietOCR predictor/configuration](https://github.com/pbcquoc/vietocr).
Horizontal detector coordinates are `[xmin,xmax,ymin,ymax]`; free regions are
quadrilaterals. The adapter uses the upstream crop rectification implementation,
then maps each recognition region back to the source PDF in points.

**Relevant papers:** [CRAFT](https://arxiv.org/abs/1904.01941) separates character
regions and affinities for detection; [CRNN](https://arxiv.org/abs/1507.05717)
describes image sequence recognition. Neither paper demonstrates exact Vietnamese
legal-table transcription on these scans or establishes handwriting accuracy.

**Candidates/selected solution:** compare standalone EasyOCR against CRAFT plus
VietOCR; split tall regions at observed table-row boundaries before recognition.
Keep ordinary horizontal lines intact: splitting all regions damaged descriptions
on skewed scans, reproduced by a regression test. Order the recognized regions
before assigning table snippets. Store source-coordinate polygons, reject invalid
geometry/confidence, hash actual model bytes/configuration in page-cache identity,
and retain `needs_review` for every OCR reading. These remain explicit optional
engines; neither replaces the default based on the small development experiment.
Group fragments by vertical center rather than quantized top edges, which vary
with Vietnamese diacritics. Merge adjacent fragments before recognition while
keeping detected table columns separate. Preserve that reading order when building
page text. This also restores context for handwritten date recognition. The model
object cache includes checkpoint hashes: changing files must reload the in-memory
model, rather than labeling old predictions with new model hashes. Both failure
modes have regression tests. Preflight loads the selected recognizer to reject an
incompatible checkpoint before processing pages. Adapter code bytes are included
in extraction cache identity.

**Measured results/regression risk:** on QD26 PDF page 28, standalone EasyOCR took
43.04 seconds for inference. EasyOCR plus VietOCR initially scored 16/25 numeric
cells in 55.89 seconds; row splitting restricted to tall regions scored 24/25 in
55.19 seconds. Both retained only 3/8 exact description anchors before the reading
order fix. Splitting all
regions had reduced descriptions to 1/8 and was rejected. The hybrid still failed
the independently transcribed handwritten date on QD148 PDF page 1 (1/2 first-page
anchors, 38.92 seconds). Correcting reading order raised description anchors to
7/8; Seq2Seq plus explicit Tesseract numeric refinement scored 25/25 numeric cells
in 56.43 seconds. The remaining description error changes `tỉnh` to `tinh`.
Standalone EasyOCR's captured real inference, mapped through the current adapter,
scored 17/25 numeric cells and 0/8 descriptions.

VietOCR Transformer read the handwritten date correctly on independent full-line
crops at 260 and 350 DPI, but initially failed on fragmented full-page detections.
Merging adjacent regions before recognition restored 2/2 QD148 first-page anchors
in an actual full-page run (63.07 seconds). The final Transformer/CRAFT page 28 run
with explicit Tesseract numeric refinement scored 25/25 numeric cells and 7/8
descriptions in 75.50 seconds. It still failed to transcribe the table's asterisk
markers. Increasing crop resolution to 350/450 DPI did not recover the remaining
Vietnamese tone mark. Tesseract PSM 6 recovered that phrase in a separate crop
experiment, but a calibrated, independently validated text-fusion policy has not
been established; that candidate is not silently substituted into production text.
These single-page CPU timings are not latency percentiles. Missing detections,
skew, legal-text errors, and footnote-marker preservation remain open.

The completed Tesseract corpus run processed all 583 pages / 315 OCR pages without
quarantine, with 385 table candidates in 901.25 seconds. It scored 57/57 numeric
cells across the two score pages, 23/24 first-page legal anchors, and 3/8 newly
added table-description anchors. The once-held-out score page was already inspected
during debugging; its final result is a regression check, not a fresh held-out
estimate. Observed peak process-tree RSS was 1,890,926,592 bytes, sampled only during
the last 619.13 seconds; summing RSS can count shared memory more than once.
These results **do not pass PDF/OCR acceptance** or establish whole-corpus accuracy.
