"""Independent regression for the R05 cross-review's Current schema gap."""

import copy
import json
import re
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError
from scripts.v250.route_derivation import derive_route
from tests.v268.test_current_promotion import route_facts


ROOT = Path(__file__).resolve().parents[2]


class TestCurrentRouteSchemaReceipt(unittest.TestCase):
    def validator(self):
        schema = json.loads((ROOT / 'schemas/v2.50/route-prompt.schema.json').read_text())
        return Draft202012Validator({
            '$schema': schema['$schema'], '$defs': schema['$defs'],
            '$ref': '#/$defs/derivedRouteReceipt',
        })

    def test_actual_v268_receipts_are_accepted_in_both_phases(self):
        for phase in ('development', 'release'):
            with self.subTest(phase=phase):
                receipt = derive_route(route_facts(phase), generation_id='V2.68')
                self.assertEqual('goal-teams-derived-route-receipt-v2.68', receipt['schema_version'])
                self.validator().validate(receipt)

    def test_unknown_receipt_generation_is_still_rejected(self):
        receipt = copy.deepcopy(derive_route(route_facts(), generation_id='V2.68'))
        receipt['schema_version'] = 'goal-teams-derived-route-receipt-v9.99'
        with self.assertRaises(ValidationError):
            self.validator().validate(receipt)

    def test_documented_release_commands_include_required_route_inputs(self):
        text = (ROOT / 'AGENTS.md').read_text()
        launch = text.split('python3 scripts/v268/runtime_host_adapter.py launch', 1)[1].split('python3 scripts/checks/check-v268.py', 1)[0]
        checker = text.split('python3 scripts/checks/check-v268.py', 1)[1].split('```', 1)[0]
        self.assertIn('--predecessor-observation-receipt', launch)
        for flag in ('--stage released', '--release-intent', '--implementation-scope-complete'):
            self.assertIn(flag, checker)


if __name__ == '__main__':
    unittest.main()
