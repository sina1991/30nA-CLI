#!/usr/bin/env python3
"""CLI harness for tests whose scope excludes real SSH enrollment.

Enrollment behavior is covered independently by test_onboarding. Worker and
tunnel processes still run normally, using each test's isolated environment.
"""
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from thirtyna.core import main

with patch("thirtyna.onboarding.enroll"):
    raise SystemExit(main(sys.argv[1:]))
