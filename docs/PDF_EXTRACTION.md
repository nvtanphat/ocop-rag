# OCOP PDF and OCR

## Fixed extraction path

- Digital PDFs use embedded text and native table geometry.
- Scanned or mixed pages use EasyOCR CRAFT to locate text, then VietOCR VGG Transformer to recognize each line crop. Skewed CRAFT quadrilaterals are perspective-rectified before recognition.
- Blank or short nonnumeric readings in a table's last column receive one 2x cell-crop retry. VietOCR reads both the CRAFT-localized crop and the direct cell crop; numeric results are stored separately as `score_ocr_candidates`, never overwrite the first OCR transcription, and always need source review.
- Tall CRAFT regions that span multiple ruled table rows are split at detected row boundaries. Boundaries within 10% of a region edge are ignored; this corpus threshold is covered by a regression case where a valid boundary lay 18.8% from the edge on QD26 page 29.
- OpenCV detects ruled table structure from the same raster. Candidate vertical rules are retained only when one contiguous segment spans at least 8% of the table component height (minimum 24 pixels). This threshold was selected from measured ruled and fragmented lines on eight 300 DPI pages from two source PDFs; it is an empirical corpus threshold, not a published constant. OCR text is assigned to detected cells by source geometry. Tables and OCR text remain unverified candidates for human review.
- Scans are deskewed only when the page contains enough consistent ruling lines. The inverse transform restores each OCR box and table cell to original PDF page coordinates.
- Native PDF tables use PyMuPDF `find_tables(strategy="lines_strict")`, which reads ruled lines only. The default strategy also treats thin filled rectangles and text edges as rules; on this corpus it split each logical row into one row per text line (ND 111/2021 page 17: 32 rows instead of 8) and invented three-column tables on plain prose (ND 15/2018: 65 tables, 18 with the strict strategy). A cell merged down several rows (`rowspan`) is repeated in the key-value text of every row it covers.
- Long CRAFT lines are cut into recognizer-sized pieces in the middle of the widest blank gap. Horizontal strokes longer than 1.5 line heights (table rules, underlines) are ignored when looking for that gap; before this, 9 of 20 long table lines on QD26 page 29 had no blank column and were cut through a glyph, which VietOCR read twice ("đún ông quy định", "lao độ ông"). At a cut in a blank gap the crop padding is blank, so a piece never shows a glyph of its neighbour (read as an extra syllable, e.g. "sản phẩm chí"); a forced cut through a glyph keeps the overlap so neither piece loses the split letter.
- A printed checkbox that starts an option line is blanked before recognition; VietOCR otherwise reads it as "Ở", "0", "9" or "a,". Only a hollow, roughly square outline with ink in all four corners qualifies, so a leading letter O or digit 0 is kept.
- Recognition crops that are tiny compared with the page's median crop and have low confidence are scan speckle and are dropped (`speckle_regions_dropped:N`); the raw reading stays in the debug trace.

### Layout regions and reading order

When the local PP-DocLayout_plus-L model is present (`OCOP_LAYOUT_MODEL_DIR`, default `~/.paddlex/official_models/PP-DocLayout_plus-L`; install with `pip install -e '.[layout]'`), each OCR block is assigned to the smallest detected layout region covering at least half of it, and the page is read region by region (regions that overlap vertically form a row, read left to right), then line by line inside a region. This keeps seal, received-stamp, signature and page-header text out of the body lines it sits beside. Without the model, OCR runs unchanged and the page records `layout_model_unavailable`. The model is never downloaded by the pipeline.

### Diacritic post-correction

VietOCR's dominant residual error is a wrong Vietnamese mark on a correct letter skeleton (phú/phủ, quân/quản, kêm/kèm). Recognition keeps the recognizer's own top-5 alternatives for every character where it weighed a second character (`uncertain_chars` on each OCR block). After the page cache, a noisy-channel step may replace a word only by a same-skeleton word whose differing characters the recognizer itself weighed at those positions; the decision adds the recognizer's log-odds to a bigram context score learned from the corpus's own native-text pages (pages classified `native_text`; OCR pages never train it). Digits are never changed, a word already attested next to its neighbours is kept, table cells take the corrected text of the blocks they contain, and every change keeps the raw OCR text in `ocr_raw_text` with a `postcorrections` list. Corrected text is still an unverified OCR candidate.

On QD1489 pages 1-4, checked by reading the page images, the step made 65 changes and 64 were right (13/13, 9/9, 30/31 and 12/12; the miss changed "tiêu chí" to "chỉ"). On the transcribed body of page 1 character recall rose from 0.977 to 0.987, and on page 2 from 0.984 to 0.994. A first version without the recognizer's alternatives changed correct words such as "đánh giá tại" to "tài" and "thể thức" to "thực"; requiring the recognizer's own alternatives removed those. This is a small, development-page check, not a corpus-wide accuracy figure.

Every citation retains source ID, source SHA-256, PDF page, evidence ID, and available source geometry. OCR scores, stars, and legal descriptions remain candidates until checked against the locked source PDF. A valid citation does not prove semantic support.

## Install and provision local models

```powershell
python -m pip install -e '.[easy_vietocr]'
```

EasyOCR needs its CRAFT detector file `craft_mlt_25k.pth` from the [official model configuration](https://github.com/JaidedAI/EasyOCR/blob/master/easyocr/config.py). Copy it to a local model directory. VietOCR needs its VGG Transformer checkpoint; its architecture configuration is stored in `ai_core/processing/ocop/vietocr_vgg_transformer.json`. OCR does not fetch models or configuration from the network.

```powershell
$env:OCOP_EASYOCR_MODEL_DIR = 'D:/models/easyocr'
$weightsDir = Join-Path $env:USERPROFILE '.cache/ocop/vietocr'
New-Item -ItemType Directory -Force -Path $weightsDir | Out-Null
Invoke-WebRequest 'https://vocr.vn/data/vietocr/vgg_transformer.pth' -OutFile (Join-Path $weightsDir 'vgg_transformer.pth')
$env:OCOP_VIETOCR_WEIGHTS = Join-Path $weightsDir 'vgg_transformer.pth'
```

If `OCOP_EASYOCR_MODEL_DIR` is unset, the adapter reads `~/.EasyOCR/model`. If `OCOP_VIETOCR_WEIGHTS` is unset, it reads `~/.cache/ocop/vietocr/vgg_transformer.pth`. EasyOCR detector configuration follows its [official API](https://www.jaided.ai/easyocr/documentation/), and the VietOCR checkpoint comes from the [VietOCR project](https://github.com/pbcquoc/vietocr). Production fingerprints include the CRAFT and VietOCR models.

The supported end-to-end command is `python tools/cli.py run`. For page-level extraction and inspection, use:

```powershell
python tools/cli.py debug process-ocop-pdf -- --dpi 300 --output data/processed/ocop/pages --cache data/processed/ocop/cache
```

Use `python tools/cli.py --help` and `python tools/cli.py debug process-ocop-pdf -- --help` for supported commands and options. Scan OCR runs sequentially to load one detector and recognizer pair. Source PDFs under `data/raw/ocop` are immutable.

## Check OCR quality

OCR quality is checked by an agent reading the page, not by gold-label scripts. Render the source page from the immutable PDF at about 110-130 DPI, read it, then compare each extracted block and table cell against the image: score cells (including blank ones, which may be intentional), legal-text wording, line order, and text under stamps. Run a single page with `extract_page` into a scratch directory outside the repository; generated output is never kept in the source tree.

Record what was read: source ID, PDF page, and the specific cells or lines that differ. Review-only candidates such as `score_ocr_candidates` and `image_marker_candidates` are confirmed or rejected against the image, never accepted because of OCR confidence. A visual check is not domain-expert verification, and OCR scores, stars, and legal descriptions remain unverified candidates that must not drive definitive ranking or dossier assessment. Published CRAFT or VietOCR benchmarks do not establish accuracy on OCOP documents.

CRAFT provides text-region detection and VietOCR provides Vietnamese line recognition. Published benchmark results for either component do not establish accuracy on OCOP documents. See the [CRAFT paper](https://openaccess.thecvf.com/content_CVPR_2019/html/Baek_Character_Region_Awareness_for_Text_Detection_CVPR_2019_paper.html), [VietOCR project](https://github.com/pbcquoc/vietocr), and [VietOCR training guide](https://pbcquoc.github.io/vietocr/).
