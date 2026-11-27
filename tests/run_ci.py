"""Full Linux CI gate: no empty test suite, skips or expected failures."""
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
if os.environ.get("THIRTYNA_REAL_SSH") != "1":
    raise SystemExit("CI requires THIRTYNA_REAL_SSH=1")
suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
result = unittest.TextTestRunner(verbosity=2).run(suite)
print(f"CI_GATE tests={result.testsRun} failures={len(result.failures)} "
      f"errors={len(result.errors)} skipped={len(result.skipped)} "
      f"expected_failures={len(result.expectedFailures)}", flush=True)
sys.exit(0 if result.testsRun and result.wasSuccessful() and
         not result.skipped and not result.expectedFailures else 1)
