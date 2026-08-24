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
            if window.audio_rows:
                window.audio_rows[0]["lang"].setEditText("ita")
                self.assertEqual(window.collect_options().audio[0].language,
                                 "ita")
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
            self.assertTrue(window.tabs.isTabVisible(tab_index("Log")))
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

    def test_encoder_option_capabilities_follow_backend(self):
        window = AutoFfmpegGui()
        try:
            def disabled_options():
                return {
                    window.tbl_encoder_options.item(row, 1).text()
                    for row in range(window.tbl_encoder_options.rowCount())
                    if window.tbl_encoder_options.item(row, 1)
                    and window.tbl_encoder_options.cellWidget(row, 2)
                    and not window.tbl_encoder_options.cellWidget(row, 2).isEnabled()
                }

            self.assertEqual(window.tbl_encoder_options.columnCount(), 4)
            self.assertNotIn("stats", disabled_options())
            window.cmb_external_encoder.setCurrentText("x264 CLI (external)")
            self.assertIn("stats", disabled_options())
            window.cmb_external_encoder.setCurrentText("FFmpeg (internal)")
            self.assertNotIn("stats", disabled_options())
            window.cmb_preset.setCurrentText("H.265 - medium")
            self.assertIn("bitrate", disabled_options())
            window.cmb_external_encoder.setCurrentText("x265 CLI (external)")
            self.assertNotIn("bitrate", disabled_options())
        finally:
            window.close()
            self.app.processEvents()

    def test_log_keeps_user_scroll_position(self):
        window = AutoFfmpegGui()
        try:
            window.txt_log.setPlainText("\n".join(f"line {i}" for i in range(100)))
            scrollbar = window.txt_log.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            window.append_log("tail")
            self.assertEqual(scrollbar.value(), scrollbar.maximum())

            scrollbar.setValue(max(0, scrollbar.maximum() - 20))
            old_value = scrollbar.value()
            window.append_log("new message")
            self.assertEqual(scrollbar.value(), old_value)
        finally:
            window.close()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
