"""PaddleOCR adapter; conservative position-based suggestions, never verified output."""
import json
import re
from core import FIELDS


def run_ocr(path):
    from paddleocr import PaddleOCR
    # Keep coordinates aligned to the prepared page for correction crops.
    engine = PaddleOCR(lang='en', ocr_version='PP-OCRv5', device='cpu',
                       use_doc_orientation_classify=False, use_doc_unwarping=False,
                       use_textline_orientation=False)
    result = next(iter(engine.predict(str(path))))
    raw = result.json
    if isinstance(raw, str):
        raw = json.loads(raw)
    raw = raw.get('res', raw)
    tokens = []
    for i, (text, score, box) in enumerate(zip(raw['rec_texts'], raw['rec_scores'], raw['rec_boxes'])):
        tokens.append({'id': i, 'original': text, 'corrected': text, 'confidence': float(score),
                       'box': [int(v) for v in box], 'approved': False})
    return tokens


def suggest(tokens, width, height):
    fields = dict.fromkeys(FIELDS, '')
    items = []
    def zone(x1, y1, x2, y2):
        return [t for t in tokens if x1 <= (t['box'][0]+t['box'][2])/2/width <= x2
                and y1 <= (t['box'][1]+t['box'][3])/2/height <= y2]
    def text(ts):
        return ' '.join(t['original'] for t in sorted(ts, key=lambda t: (t['box'][1], t['box'][0])))
    # User crops to the outside edges of the printed bill first.
    header = text(zone(.55, 0, 1, .13))
    match = re.search(r'\b(\d{5})\b', header)
    if match:
        fields['bill_number'] = match.group(1)
    # Locate table header / footer through labels rather than fixed row heights.
    headings = {name: next((t for t in tokens if t['original'].strip().upper() == name), None)
                for name in ['ITEM', 'QTY', 'KG', 'UNIT/PRICE']}
    remarks = next((t for t in tokens if t['original'].lower().startswith('remarks')), None)
    if all(headings.values()) and remarks:
        centers = [(headings[k]['box'][0]+headings[k]['box'][2])/2 for k in headings]
        boundaries = [(centers[i]+centers[i+1])/2 for i in range(3)]
        total_head = next((t for t in tokens if 'TOTAL' in t['original'].upper() and abs(t['box'][1]-headings['KG']['box'][1]) < height*.04), None)
        boundaries.append((centers[3]+(total_head['box'][0]+total_head['box'][2])/2)/2 if total_head else width*.86)
        top = max(t['box'][3] for t in headings.values())
        bottom = remarks['box'][1]
        row_height = (bottom-top)/15
        for row in range(15):
            parts = [[] for _ in range(5)]
            for t in tokens:
                x, y = (t['box'][0]+t['box'][2])/2, (t['box'][1]+t['box'][3])/2
                if top+row*row_height <= y < top+(row+1)*row_height and x > width*.07:
                    col = sum(x > b for b in boundaries)
                    parts[col].append(t)
            if not any(parts):
                continue
            values = [text(p) for p in parts]
            numeric = [v if re.fullmatch(r'\d+(?:\.\d+)?', v) else '' for v in values[1:]]
            items.append(dict(zip(['description', 'quantity', 'kg', 'rate', 'amount'], [values[0]]+numeric), group=''))
    # Extract only same-line label/value candidates; uncertain handwriting is left for review.
    labels = [('porter_name', r'porter\s*\(name\)\s*:?'),
              ('permit_number', r'permit\s*no\s*:?'),
              ('bill_date', r'date\s*issued\s*:?'),
              ('issued_by', r'issued\s*by.*?sign\)?\s*:?'),
              ('checked_by', r'received\s*checked\s*by.*?sign\)?\s*:?')]
    for field, pattern in labels:
        for t in tokens:
            found = re.search(pattern, t['original'], re.I)
            if not found:
                continue
            suffix = t['original'][found.end():].strip(' :;')
            cy = (t['box'][1]+t['box'][3])/2
            neighbors = [n for n in tokens if n['id'] != t['id'] and n['box'][0] >= t['box'][2]-3
                         and abs((n['box'][1]+n['box'][3])/2-cy) < height*.012]
            candidate = (suffix+' '+text(neighbors)).strip()
            candidate = re.split(r'Permit|Authorised|Date/Time', candidate, flags=re.I)[0].strip()
            fields[field] = candidate
            break
    return fields, items
