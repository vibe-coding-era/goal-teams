import os
import subprocess
import sys
import tempfile
import unittest


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        proc = subprocess.run([sys.executable, "-m", "textkit.cli", *args], capture_output=True, text=True,
                              cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return proc.returncode, proc.stdout.strip()

    def test_count_words(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
            handle.write("one two three\n")
            path = handle.name
        try:
            self.assertEqual(self.run_cli("count", path), (0, "3"))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
