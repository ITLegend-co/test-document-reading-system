"""Local persistence and Decimal-based charge validation."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

FIELDS = ['bill_number', 'porter_name', 'permit_number', 'bill_date', 'issued_by',
          'issued_at', 'checked_by', 'checked_at', 'total_kg', 'total_rm', 'remarks']


def number(value):
    if value is None or str(value).strip() == '':
        return None
    try:
        n = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValueError(f'Invalid number: {value}')
    if not n.is_finite() or n < 0:
        raise ValueError(f'Use a finite, nonnegative number: {value}')
    return n


def validate(fields, items):
    groups, errors = {}, []
    for i, row in enumerate(items, 1):
        if not str(row.get('description', '')).strip():
            errors.append(f'Row {i}: item description required.')
        number(row.get('quantity'))
        key = str(row.get('group', '')).strip() or f'row-{i}'
        charge = tuple(number(row.get(k)) for k in ('kg', 'rate', 'amount'))
        if key in groups:
            # Group values are entered on one row only, preventing double counting.
            if any(v is not None for v in charge):
                errors.append(f'Group {key}: enter KG, rate and amount on its first row only.')
        else:
            groups[key] = charge
    kg = Decimal(0)
    rm = Decimal(0)
    for key, (weight, rate, amount) in groups.items():
        if any(v is None for v in (weight, rate, amount)):
            errors.append(f'{key}: weight, rate and amount are required.')
            continue
        kg += weight
        rm += amount
        expected = (weight * rate).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        if expected != amount:
            errors.append(f'{key}: KG × rate = RM{expected}, entered amount = RM{amount}.')
    for field, computed in [('total_kg', kg), ('total_rm', rm)]:
        entered = number(fields.get(field))
        if entered is None or entered != computed:
            errors.append(f'{field}: entered {entered}; calculated {computed}.')
    return {'kg': str(kg), 'rm': str(rm), 'warnings': errors}


class Store:
    def __init__(self, root='data'):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS bills (id TEXT PRIMARY KEY, bill_number TEXT, status TEXT, payload TEXT, updated TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS revisions (id INTEGER PRIMARY KEY, bill_id TEXT, payload TEXT, created TEXT)')

    def connect(self):
        return sqlite3.connect(self.root / 'bills.sqlite3')

    def save(self, doc, reviewer, verified=False, override=''):
        doc = json.loads(json.dumps(doc))
        result = validate(doc['fields'], doc['items'])
        if verified:
            if not reviewer.strip() or not doc['fields']['bill_number'].strip() or not doc['fields']['porter_name'].strip() or not doc['items']:
                raise ValueError('Reviewer, bill number, porter name and at least one item are required.')
            if result['warnings'] and not override.strip():
                raise ValueError('Resolve calculation warnings or record an explanation.')
            if not doc.get('review_confirmed'):
                raise ValueError('Confirm that you reviewed every field and the stamp status.')
        now = datetime.now(timezone.utc).isoformat()
        doc.update(reviewer=reviewer, verified_at=now if verified else None,
                   status='verified' if verified else 'draft', validation=result, override=override)
        payload = json.dumps(doc, ensure_ascii=False)
        with self.connect() as db:
            duplicate = db.execute('SELECT id FROM bills WHERE bill_number=? AND id<>?', (doc['fields']['bill_number'], doc['id'])).fetchone()
            if duplicate and doc['fields']['bill_number']:
                raise ValueError('Another saved document already uses this bill number. Open that record instead.')
            db.execute('INSERT OR REPLACE INTO bills VALUES (?,?,?,?,?)', (doc['id'], doc['fields']['bill_number'], doc['status'], payload, now))
            db.execute('INSERT INTO revisions(bill_id,payload,created) VALUES (?,?,?)', (doc['id'], payload, now))
        return doc

    def list(self):
        with self.connect() as db:
            return db.execute('SELECT id,bill_number,status,updated FROM bills ORDER BY updated DESC').fetchall()

    def get(self, doc_id):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM bills WHERE id=?', (doc_id,)).fetchone()
        return json.loads(row[0]) if row else None


def document_id(content):
    return hashlib.sha256(content).hexdigest()
