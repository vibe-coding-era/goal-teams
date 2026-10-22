import io
import os
import tempfile
import unittest

from inventory.cli import main


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "inventory.json")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        code = main(["--db", self.db, *args], out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def test_add_then_list(self):
        self.assertEqual(self.run_cli("add", "A-1", "扳手", "--quantity", "3")[0], 0)
        code, output, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("A-1\t3\t扳手", output)

    def test_adjust_unknown_sku_fails(self):
        code, _, error = self.run_cli("adjust", "NOPE", "1")
        self.assertEqual(code, 1)
        self.assertIn("unknown SKU", error)


if __name__ == "__main__":
    unittest.main()
