# Mountain Torq Porter Bill Reader

Local prototype: PaddleOCR → review → SQLite. Runs on your own computer in a browser at `http://127.0.0.1:8501`. No hosted OCR service. Real bills and database files are excluded from Git.

## Windows setup

1. Install **Python 3.11, 64-bit** from https://www.python.org/downloads/ (include the Python launcher).
2. Download this repository: **Code → Download ZIP**. Extract it to a writable folder.
3. Double-click **start.bat**. Initial setup requires internet to download packages; first OCR use downloads model files.
4. The browser opens the local application. Keep the terminal window open. Close it to stop the app.

If setup fails, preserve the terminal error. CPU inference is the default; no NVIDIA GPU is required. Speed depends on hardware. Package installation and actual handwriting accuracy must be tested on the target PC.

Manual setup (Python 3.11):

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

## How to use

Upload a JPG, PNG or PDF (one bill per selected PDF page). Rotate and crop to the bill edges, excluding the camera date watermark. Click **Scan with PaddleOCR**. The initial draft is saved. Compare every field against the image, edit rows and enter missing fields. Orange OCR boxes indicate scores below 0.85, not a guarantee that other boxes are correct.

- Fields include bill number (text, preserving zeroes), porter, permit, bill issue date, issuer/date-time, checker/date-time, totals, remarks and stamp review status.
- Dates and names currently require human review; no signature identity inference is attempted.
- Unit price is RM per KG. Quantity is not multiplied into the charge.
- For bracketed shared charges, enter the same group ID on all member rows. Enter group KG/rate/amount on the **first member only**. Continuation rows retain their individual quantities and descriptions.
- Repeated-rate marks and groups require manual confirmation. Numeric OCR failures remain blank; missing values are never treated as zero.
- The OCR adapter produces conservative item suggestions when table anchors are detected. It does not reliably understand arbitrary handwriting or perspective-distorted rows. It may miss rows or return an empty form; all OCR regions remain visible for manual transcription.
- Stamp presence is **manually reviewed** in this prototype; no automatic stamp detector is claimed.
- The source totals and calculated totals remain separate. Explain unresolved differences before verification. Verified-by is separate from the bill's checked-by.
- Same-file/page uploads and duplicate saved bill numbers are checked. Visually identical documents rephotographed with different bytes may still need manual duplicate identification.
- Save drafts or verify. Reopen bills from the sidebar. Revisions are appended in SQLite. Saving an edited verified record as draft changes its status back to draft.

## Corrections and learning

Structured field edits and original extraction are saved in bill JSON and revision history. For OCR training, open **Correct text regions**, inspect each crop, correct its exact text and explicitly approve it. Save and verify the bill. **Export training examples** produces image crops, PaddleOCR-compatible tab-separated `rec_gt.txt`, provenance manifest and structured bill records. Only approved regions from verified bills enter the labels.

This is **training-data collection**, not automatic model learning or a fine-tuning interface. Split datasets by bill/writer, train with PaddleOCR's recognition training tools, evaluate on held-out documents and compare against the baseline before deploying new weights. Field edits alone are not silently converted into crop labels because their alignment may be wrong.

## Storage and backups

`data/bills.sqlite3` contains records and revisions. Each document folder holds the original upload and prepared OCR image. **Create local backup** exports a consistent SQLite snapshot and documents. To restore, stop the application, retain a copy of current data, then extract the backup's `data` directory into the application folder. Treat backups/training ZIPs as sensitive local documents. No sample photos are committed to this public repository.

Local-only, single-operator prototype: no login, network sharing, encryption or production multiuser locking. Keep the server on 127.0.0.1. First model download needs internet; offline use requires those models to be cached.

## Tests

```sh
python -m unittest discover -s tests -v
```

Tests cover decimal calculations, shared charges, missing data, duplicates, verification and persistence. They do not measure handwriting accuracy. OCR failure is displayed explicitly and permits a manual draft.

Reference: https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/OCR.en.md

## Validation in this build

- Four calculation/persistence unit tests passed.
- Streamlit upload screen and review → verify → database workflow passed automated AppTest checks.
- PaddleOCR/PaddlePaddle installed successfully in the build environment.
- A real sample OCR attempt could not download model weights because model hosts were unreachable from that environment. Handwriting accuracy and Windows execution are **not yet verified**.
- Source published to the GitHub repository after repository access was enabled.
