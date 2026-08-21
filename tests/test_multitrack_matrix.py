# -*- coding: utf-8 -*-
"""Opt-in full real-media matrix test.

The default unit suite stays short. Run the full matrix and report with:

    AUTOFFMPEG_FULL_MATRIX=1 python3 -m unittest tests.test_multitrack_matrix -v
"""

import os
import unittest

try:
    from tests.run_media_suite import run_suite
except ModuleNotFoundError:
    from run_media_suite import run_suite


@unittest.skipUnless(os.environ.get("AUTOFFMPEG_FULL_MATRIX"),
                     "set AUTOFFMPEG_FULL_MATRIX=1 for the full media matrix")
class TestFullMultitrackMatrix(unittest.TestCase):
    def test_all_real_combinations(self):
        report = run_suite()
        self.assertEqual(report["summary"]["failed"], 0,
                         "see test_reports/multitrack_media_report.md")
