# -*- coding: utf-8 -*-
"""Headless GUI path checks for settings and first-job construction."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from autoffmpeg.config import app_settings
from autoffmpeg.ui import AutoFfmpegGui


class TestGuiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.app.quit()
        cls.app.processEvents()

    def test_output_base_container_and_default_job(self):
        window = AutoFfmpegGui()
        old_container = app_settings().value("container", "MP4")
        try:
            window.cmb_container.setCurrentText("MP4")
            window.set_output_base("/tmp/gui-smoke")
            options = window.collect_options()
            self.assertEqual(options.outputfile, "/tmp/gui-smoke.mp4")

            window.inputfile = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "aaa.vob")
            window.inp_input.setText(window.inputfile)
            self.assertTrue(window.analyze())
            window.output_base = ""
            window.outputfile = ""
            window.inp_output.clear()
            options, jobs = window.prepare_jobs(silent=True)
            self.assertTrue(options.outputfile.endswith(".mp4"))
            self.assertTrue(jobs)
            self.assertFalse(any(".avs" in arg for arg in jobs[0].cmd))
        finally:
            window.close()
            self.app.processEvents()
            app_settings().setValue("container", old_container)


if __name__ == "__main__":
    unittest.main()
