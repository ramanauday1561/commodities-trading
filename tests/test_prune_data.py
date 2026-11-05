"""prune_data.py keeps the shared files and removes data of instruments no longer listed (no network)."""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")


class Prune(unittest.TestCase):
    def test_keeps_shared_files(self):
        with tempfile.TemporaryDirectory() as d:
            names = ["options-live", "options-nifty", "data-health", "paper-accounts", "nifty", "status", "live-nifty", "next-nifty",
                     "replay-2026-11-03", "gone-instrument"]
            for n in names:
                open(os.path.join(d, n + ".json"), "w").write("{}")
            subprocess.run([sys.executable, "scripts/prune_data.py", d], cwd=ROOT, check=True, capture_output=True)
            left = sorted(f[:-5] for f in os.listdir(d))
            self.assertEqual(left, sorted(n for n in names if n != "gone-instrument"))


if __name__ == "__main__":
    unittest.main()
