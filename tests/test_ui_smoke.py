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
        settings = app_settings()
        old_container = settings.value("container", "MP4")
        old_avisynth = settings.value("avisynth_enabled", False, type=bool)
        try:
            window.cmb_processor.setCurrentText("FFmpeg (filters and encoding)")
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
            settings.setValue("container", old_container)
            settings.setValue("avisynth_enabled", old_avisynth)

    def test_processing_engine_controls_avisynth_tab(self):
        window = AutoFfmpegGui()
        settings = app_settings()
        old_avisynth = settings.value("avisynth_enabled", False, type=bool)

        def tab_index(title):
            return next(i for i in range(window.tabs.count())
                        if window.tabs.tabText(i) == title)

        try:
            window.cmb_processor.setCurrentText("FFmpeg (filters and encoding)")
            self.assertTrue(
                window.tabs.isTabVisible(tab_index("Tools - Muxing")))
            self.assertTrue(
                window.tabs.isTabVisible(tab_index("Encoder options")))
            self.assertLess(tab_index("Encoder options"),
                            tab_index("Tools - Muxing"))
            self.assertFalse(window.tabs.isTabVisible(tab_index("AviSynth+")))

            window.cmb_processor.setCurrentText(
                "AviSynth+ (script and filters)")
            self.assertTrue(window.chk_avisynth.isChecked())
            self.assertTrue(window.tabs.isTabVisible(tab_index("AviSynth+")))

            window.cmb_avs_filter.setEditText("TemporalDegrain2")
            window.insert_avs_filter()
            self.assertGreaterEqual(
                window.cmb_avs_filter.findText("TemporalDegrain2"), 0)
            self.assertIn("src = src.TemporalDegrain2()",
                          window.txt_avs.toPlainText())
        finally:
            window.cmb_processor.setCurrentText("FFmpeg (filters and encoding)")
            window.close()
            self.app.processEvents()
            settings.setValue("avisynth_enabled", old_avisynth)


if __name__ == "__main__":
    unittest.main()
