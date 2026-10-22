import tempfile
import unittest
from core import Store, validate, number

class BillTests(unittest.TestCase):
    def test_shared_charge_counted_once(self):
        rows = [dict(description='Bag',quantity='1',group='A',kg='1.6',rate='5.50',amount='8.80'), dict(description='Book',quantity='1',group='A',kg='',rate='',amount='')]
        self.assertEqual(validate(dict(total_kg='1.6',total_rm='8.80'), rows)['warnings'], [])
        rows[1]['kg'] = '1.6'
        self.assertTrue(validate(dict(total_kg='1.6',total_rm='8.80'), rows)['warnings'])

    def test_quantity_not_multiplied(self):
        rows = [dict(description='Sausage',quantity='5',kg='1.8',rate='5.5',amount='9.90')]
        self.assertEqual(validate(dict(total_kg='1.8',total_rm='9.90'), rows)['warnings'], [])

    def test_missing_and_invalid(self):
        self.assertTrue(validate({}, [dict(description='Food')])['warnings'])
        for v in ['nan', 'Infinity', '-1', 'fish']:
            with self.assertRaises(ValueError): number(v)

    def test_store_verification_revisions_and_duplicates(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            doc = dict(id='one',fields=dict(bill_number='00001',porter_name='Tester',total_kg='1',total_rm='5.50'),items=[dict(description='Item',kg='1',rate='5.5',amount='5.50')], review_confirmed=True)
            with self.assertRaises(ValueError): store.save(doc, '', True)
            store.save(doc, 'Reviewer', True)
            self.assertEqual(store.get('one')['status'], 'verified')
            self.assertEqual(store.get('one')['fields']['bill_number'], '00001')
            store.save(doc, 'Reviewer', False)
            with store.connect() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM revisions').fetchone()[0], 2)
            doc['id'] = 'two'
            with self.assertRaises(ValueError): store.save(doc, 'Reviewer')

if __name__ == '__main__': unittest.main()
