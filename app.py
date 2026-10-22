from pathlib import Path
import io
import json
import zipfile
import sqlite3
import tempfile
import streamlit as st
from PIL import Image, ImageOps, ImageDraw
from core import Store, FIELDS, document_id, validate
from ocr import run_ocr, suggest

st.set_page_config(page_title='Mountain Torq • Porter Bills', page_icon='📄', layout='wide')
st.title('Porter Bill Reader')
st.caption('LOCAL WORKSPACE  •  Scan → Review → Verify')
store = Store()


def training_zip():
    buf = io.BytesIO()
    labels, manifest = [], []
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as archive:
        for doc_id, _, status, _ in store.list():
            if status != 'verified':
                continue
            doc = store.get(doc_id)
            source = Image.open(doc['image'])
            for t in doc['tokens']:
                if not t.get('approved') or not t.get('corrected', '').strip():
                    continue
                name = f'crops/{doc_id}_{t["id"]}.png'
                crop = source.crop(tuple(t['box']))
                content = io.BytesIO()
                crop.save(content, format='PNG')
                archive.writestr(name, content.getvalue())
                corrected = t['corrected'].replace('\t', ' ').replace('\n', ' ')
                labels.append(f'{name}\t{corrected}')
                manifest.append({'document_id': doc_id, **t})
            archive.writestr(f'bills/{doc_id}.json', json.dumps(doc, ensure_ascii=False, indent=2))
        archive.writestr('rec_gt.txt', '\n'.join(labels))
        archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr('README.txt', 'Only explicitly approved text crops from verified bills are included. Split train/evaluation by document or writer before training. Structured field edits remain in bill JSON and are not automatically text-crop labels. No model retraining has occurred.')
    return buf.getvalue()


with st.sidebar:
    st.header('Saved bills')
    records = store.list()
    if records:
        selected = st.selectbox('Open a record', [r[0] for r in records],
                                format_func=lambda id: next(f'{r[1] or "Unnumbered"} • {r[2]}' for r in records if r[0] == id))
        if st.button('Open selected bill'):
            st.session_state.doc = store.get(selected)
            st.session_state.editor_version = st.session_state.get('editor_version', 0)+1
            st.rerun()
        st.download_button('Export training examples', training_zip(), 'porter-training.zip', 'application/zip')
    if st.button('Create local backup'):
        # SQLite online backup gives a consistent database snapshot.
        buffer = io.BytesIO()
        with tempfile.TemporaryDirectory() as tmp:
            backup = Path(tmp)/'bills.sqlite3'
            with store.connect() as src, sqlite3.connect(backup) as dst:
                src.backup(dst)
            with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as z:
                z.write(backup, 'data/bills.sqlite3')
                for f in store.root.rglob('*'):
                    if f.is_file() and f.suffix != '.sqlite3':
                        z.write(f, str(f))
        st.download_button('Download backup ZIP', buffer.getvalue(), 'porter-backup.zip', 'application/zip')
    st.caption('Documents, database and training examples stay on this PC. Model files download on the first OCR run.')

with st.expander('Upload a new bill', expanded='doc' not in st.session_state):
    upload = st.file_uploader('Photo or scanned PDF', type=['jpg', 'jpeg', 'png', 'pdf'])
    if upload:
        content = upload.getvalue()
        if len(content) > 30*1024*1024:
            st.error('Maximum file size is 30 MB.')
            st.stop()
        page = 0
        try:
            if upload.name.lower().endswith('.pdf'):
                import pypdfium2 as pdfium
                pdf = pdfium.PdfDocument(content)
                page = int(st.number_input('PDF page (one bill per page)', 1, len(pdf), 1))-1
                image = pdf[page].render(scale=2).to_pil().convert('RGB')
            else:
                image = ImageOps.exif_transpose(Image.open(io.BytesIO(content))).convert('RGB')
            image.thumbnail((2400, 3200))
        except Exception as exc:
            st.error(f'Could not read this file: {exc}')
            st.stop()
        rotation = st.selectbox('Rotate image', [0, 90, 180, 270])
        image = image.rotate(rotation, expand=True)
        st.caption('Crop to the outside edges of the bill, excluding the photo timestamp. For angled photos, a straight scan gives better results.')
        x = st.slider('Keep horizontal area (%)', 0, 100, (0, 100))
        y = st.slider('Keep vertical area (%)', 0, 100, (0, 100))
        if x[0] == x[1] or y[0] == y[1]:
            st.error('Select a nonempty crop.')
            st.stop()
        prepared = image.crop((int(image.width*x[0]/100), int(image.height*y[0]/100), int(image.width*x[1]/100), int(image.height*y[1]/100)))
        st.image(prepared, width=380)
        scan, manual = st.columns(2)
        do_scan = scan.button('Scan with PaddleOCR', type='primary')
        do_manual = manual.button('Create manual draft')
        if do_scan or do_manual:
            doc_id = document_id(content+f':page:{page}'.encode())
            if store.get(doc_id):
                st.warning('This document/page already exists. Open it from Saved bills.')
            else:
                folder = store.root/doc_id
                folder.mkdir(exist_ok=True)
                (folder/('original'+Path(upload.name).suffix.lower())).write_bytes(content)
                path = folder/'prepared.png'
                prepared.save(path)
                tokens = []
                error = None
                if do_scan:
                    try:
                        with st.spinner('Reading handwriting on this PC. The first run downloads the models…'):
                            tokens = run_ocr(path)
                    except Exception as exc:
                        error = str(exc)
                fields, items = suggest(tokens, prepared.width, prepared.height)
                doc = {'id': doc_id, 'image': str(path), 'source_name': upload.name, 'page': page+1,
                       'fields': fields, 'items': items, 'tokens': tokens,
                       'original_extraction': {'fields': fields.copy(), 'items': [dict(r) for r in items]},
                       'stamp_status': 'Unclear', 'ocr_error': error, 'ocr_engine': 'PaddleOCR PP-OCRv5' if do_scan else 'manual',
                       'review_confirmed': False}
                st.session_state.doc = store.save(doc, '', verified=False)
                st.session_state.editor_version = st.session_state.get('editor_version', 0)+1
                st.rerun()

if 'doc' not in st.session_state:
    st.info('Upload a bill to begin. All extracted values are suggestions until you verify them.')
    st.stop()

doc = st.session_state.doc
key = doc['id']+str(st.session_state.get('editor_version', 0))
if doc.get('ocr_error'):
    st.warning('OCR did not complete. This is a manual draft, not a successful scan. '+doc['ocr_error'])
st.subheader(f'Bill {doc["fields"].get("bill_number") or "awaiting review"}')
left, right = st.columns([.9, 1.2])
with left:
    img = Image.open(doc['image']).convert('RGB')
    if st.checkbox('Show numbered OCR regions', value=True, key='boxes'+key):
        canvas = img.copy()
        draw = ImageDraw.Draw(canvas)
        for t in doc['tokens']:
            color = '#d97706' if t['confidence'] < .85 else '#16806a'
            draw.rectangle(t['box'], outline=color, width=2)
            draw.text((t['box'][0], max(0, t['box'][1]-12)), str(t['id']), fill='red')
        st.image(canvas, use_container_width=True)
    else:
        st.image(img, use_container_width=True)
    st.caption('Orange = OCR confidence below 85%. High confidence can still be wrong. Inspect every field.')
    if doc['tokens']:
        with st.expander('Correct text regions for future training'):
            st.caption('Approve only when the text exactly matches its numbered image region. Bill-form edits are saved separately.')
            token_id = st.selectbox('Inspect region', [t['id'] for t in doc['tokens']], key='region'+key)
            token = next(t for t in doc['tokens'] if t['id'] == token_id)
            st.image(img.crop(tuple(token['box'])))
            st.write('Original:', token['original'])
            corrected = st.text_input('Exact text in this crop', token['corrected'], key=f'correction{key}{token_id}')
            approved = st.checkbox('I checked this crop and approve this text', value=token['approved'], key=f'approval{key}{token_id}')
            if st.button('Apply region correction', key='apply'+key):
                token.update(corrected=corrected, approved=approved)
                st.success('Applied. Save the bill below to keep this correction.')
            st.dataframe([{'Region': t['id'], 'OCR text': t['original'], 'Confidence': round(t['confidence'], 3), 'Corrected': t['corrected'], 'Approved': t['approved']} for t in doc['tokens']], hide_index=True)
with right:
    st.caption('Enter dates as YYYY-MM-DD and date/time as YYYY-MM-DD HH:MM (Malaysia time). Leave missing source values blank.')
    fields = {}
    a, b = st.columns(2)
    for i, field in enumerate(FIELDS):
        with a if i % 2 == 0 else b:
            fields[field] = st.text_input(field.replace('_', ' ').title(), str(doc['fields'].get(field, '')), key=field+key)
    stamp = st.selectbox('Chop/stamp — visually confirmed by reviewer', ['Unclear', 'Present', 'Absent'],
                         index=['Unclear', 'Present', 'Absent'].index(doc.get('stamp_status', 'Unclear')), key='stamp'+key)
    st.caption('Stamp recognition is manual in this prototype. Presence does not establish authenticity.')
    st.markdown('**Items and shared charges**')
    st.caption('Use the same Group ID for bracketed items. Enter KG, Rate and Amount on the first row of each group only. Quantity is recorded separately. Add/delete rows to merge or split descriptions. Rates are RM per KG.')
    columns = ['description', 'quantity', 'group', 'kg', 'rate', 'amount']
    import pandas as pd
    rows = pd.DataFrame(doc['items'], columns=columns).fillna('').astype(str)
    edited = st.data_editor(rows, num_rows='dynamic', hide_index=True, use_container_width=True, key='items'+key)
    items = edited.fillna('').to_dict('records')
    items = [r for r in items if any(str(v).strip() for v in r.values())]
    try:
        result = validate(fields, items)
        st.info(f'Calculated totals: {result["kg"]} KG · RM {result["rm"]}')
        for warning in result['warnings']:
            st.warning(warning)
    except ValueError as exc:
        st.error(str(exc))
    reviewer = st.text_input('Verified by (your name)', doc.get('reviewer', ''), key='reviewer'+key)
    override = st.text_area('Explanation for unresolved calculation warnings', doc.get('override', ''), key='override'+key)
    confirmed = st.checkbox('I reviewed every field, the item grouping, dates, totals and stamp status.', key='confirmed'+key)
    save, verify = st.columns(2)
    draft = save.button('Save draft', key='save'+key)
    verified = verify.button('Verify & save', type='primary', key='verify'+key)
    if draft or verified:
        doc.update(fields=fields, items=items, stamp_status=stamp, review_confirmed=confirmed)
        try:
            st.session_state.doc = store.save(doc, reviewer, verified=verified, override=override)
            st.success('Verified bill saved.' if verified else 'Draft saved.')
        except ValueError as exc:
            st.error(str(exc))
    st.download_button('Download last saved record (JSON)', json.dumps(store.get(doc['id']), ensure_ascii=False, indent=2), 'porter-bill.json', 'application/json', key='json'+key)
