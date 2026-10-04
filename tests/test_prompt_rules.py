"""Protect the boundary that operator selections cannot remove factual safeguards."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from prompt_rules import BASELINE, SKU_PROTECTION, required_components, prepare_seed_task


class ProtectionRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import csv
        with (ROOT / 'config/prompt-components.csv').open(encoding='utf-8-sig', newline='') as f:
            cls.catalog = {c['组件编号']: c for c in csv.DictReader(f)}
        cls.prompts = json.loads((ROOT / 'tests/fixtures/seed-prompts.json').read_text())['prompts']

    def test_empty_operator_selection_still_has_all_protection(self):
        for sku in ['484330', '488726']:
            selected = required_components(sku, [], self.catalog)
            self.assertEqual(set(selected), set(BASELINE + SKU_PROTECTION[sku] + ('R02',)))

    def test_operator_scene_is_retained_with_protection(self):
        selected = required_components('484330', ['C01', 'S02', 'S02'], self.catalog)
        self.assertEqual(selected.count('S02'), 1)
        self.assertTrue(set(BASELINE + SKU_PROTECTION['484330']).issubset(selected))
        self.assertNotIn('P05', selected)

    def test_no_material_sku_cannot_be_assembled(self):
        with self.assertRaises(ValueError):
            required_components('482295', [], self.catalog)
        for p in self.prompts:
            if p['sku'] == '482295':
                with self.assertRaises(ValueError): prepare_seed_task(p, self.catalog)

    def test_unknown_or_protection_component_cannot_be_operator_choice(self):
        for choice in [['missing'], ['P05']]:
            with self.assertRaises(ValueError): required_components('484330', choice, self.catalog)

    def test_approved_drafts_are_preserved_with_no_snapshot(self):
        for p in self.prompts:
            if p['testable_draft']:
                result = prepare_seed_task(p, self.catalog)
                self.assertEqual(result['draft'], p['prompt_text'])
                self.assertEqual(result['target_count'], 3)
                self.assertIsNone(result['snapshot'])
                self.assertEqual(result['state'], '待准备')

    def test_missing_guard_and_wrong_quantity_are_rejected(self):
        p = next(p for p in self.prompts if p['testable_draft'])
        wrong = dict(p, components=[c for c in p['components'] if c != 'P01'])
        with self.assertRaises(ValueError): prepare_seed_task(wrong, self.catalog)
        with self.assertRaises(ValueError): prepare_seed_task(dict(p, candidate_count=1), self.catalog)


if __name__ == '__main__':
    unittest.main()
