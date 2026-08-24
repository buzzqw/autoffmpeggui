# -*- coding: utf-8 -*-
# AutoFFmpegGui v2 - PyQt6
# SPDX-License-Identifier: EUPL-1.2
# Licensed under the EUPL v1.2 (see LICENSE file in the project root).
"""Main application window for AutoFFmpegGui."""

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QTimer, QSettings, QSize, QUrl, pyqtSignal
from PyQt6.QtGui import (QDesktopServices, QFont, QIcon, QIntValidator,
                          QDoubleValidator)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QPushButton, QLineEdit, QLabel,
    QGroupBox, QTabWidget, QComboBox, QSlider, QCheckBox, QSpinBox,
    QPlainTextEdit, QListWidget, QListWidgetItem, QFileDialog,
    QMessageBox, QProgressBar, QTextBrowser, QHBoxLayout, QVBoxLayout,
    QGridLayout, QFormLayout, QTableWidget, QTableWidgetItem, QHeaderView,
)

from .config import (
    APP_DIR,
    APP_VERSION,
    BINARY_DIR,
    CONFIG_FILE,
    CODECS,
    EUPL_BANNER,
    ENCODER_OPTION_SPECS,
    HW_ACCELS,
    HW_ENCODERS,
    HDR_MODES,
    LOG_FILE,
    PAYPAL_URL,
    AUDIO_CODECS,
    AUDIO_BITRATES,
    AUDIO_ENCODERS,
    BUILTIN_PRESETS,
    THEMES,
    app_settings,
    lang_name,
    make_style,
    static_dovi_source,
    static_ffmpeg_source,
    static_ffplay_sources,
    default_avisynth_plugin_paths,
    dovi_x265_supported,
    Binaries,
)
from .core import (
    AudioSelection,
    AvisynthOptions,
    EncodeJob,
    EncodeOptions,
    Measure,
    ProbeInfo,
    SubtitleSelection,
    build_filter_args,
    build_avisynth_script,
    build_input_plan,
    build_ffmpeg_mux_command,
    build_jobs,
    build_mkvmerge_command,
    calc_bitrate_mb,
    cropdetect_command,
    detect_family,
    encoder_option_catalog,
    extract_frames_command,
    job_from_dict,
    job_to_dict,
    normalize_output,
    pb_profile_parse,
    probe_duration,
    round_by,
    estimate_audio_bitrate_kbps,
    estimate_subtitle_bitrate_kbps,
    stream_language,
)
from .workers import (
    CropThread,
    DownloadThread,
    EncodeThread,
    HwDetectThread,
)
from .validation import preflight
from .wizard import QuickEncodeWizard
from .bluray import (BlurayOptions, bluray_input_options, bluray_root,
                     bluray_url, is_bluray_path, scan_bluray)

CHANNEL_CHOICES = [
    ("original", "original"),
    ("mono (1)", "1"),
    ("stereo (2)", "2"),
    ("5.1 (6)", "6"),
    ("7.1 (8)", "8"),
]
POST_ACTIONS = ["None", "Notify when done", "Open output folder", "Shut down"]
AVS_FILTERS = [
    ("FFVideoSource", 'src = FFVideoSource("{{INPUT}}")'),
    ("LWLibavVideoSource", 'src = LWLibavVideoSource("{{INPUT}}")'),
    ("QTGMC Fast", 'src = src.QTGMC(preset="Fast")'),
    ("Spline36 resize", "src = src.Spline36Resize(1280, 720)"),
    ("AssumeFPS 23.976", "src = src.AssumeFPS(24000, 1001)"),
    ("Trim frames", "src = src.Trim(0, 1000)"),
    ("Sharpen", "src = src.LimitedSharpenFaster()"),
    ("RemoveGrain", "src = src.RemoveGrain(mode=17)"),
    ("KNLMeansCL", "src = src.KNLMeansCL(d=1, a=2, s=4)"),
]
QUEUE_FILE = os.path.join(APP_DIR, "autoffmpeg_queue.json")
MEDIA_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".ts", ".mts", ".m2ts", ".vob", ".mpg",
    ".mpeg", ".wmv", ".flv", ".webm", ".ogm", ".m2v", ".m2t", ".vro",
    ".m4v", ".3gp", ".3g2", ".mka", ".mp3", ".flac", ".wav", ".aac",
    ".ogg", ".ac3", ".dts", ".avs",
}


def quick_duration(ffprobe, path):
    try:
        p = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, text=True, errors="replace", timeout=30)
        data = json.loads(p.stdout)
        return probe_duration(data)
    except Exception:
        return 0.0


def quick_track_language(ffprobe, path, kind):
    """Read the first matching audio/subtitle language tag for muxing."""
    codec_type = "subtitle" if kind == "subtitle" else kind
    try:
        p = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_streams", path], capture_output=True, text=True,
            errors="replace", timeout=10)
        data = json.loads(p.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == codec_type:
                language = stream_language(stream)
                if language:
                    return language
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        pass
    return ""


class AutoFfmpegGui(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"AutoFFmpegGui v{APP_VERSION}")
        self.theme = "dark"
        self.apply_theme(self.theme)
        self.setMinimumSize(920, 770)
        self.resize(1060, 810)
        self.setAcceptDrops(True)

        self.binaries = Binaries()
        self.available_encoders = set()
        self.inputfile = ""
        self.outputfile = ""
        self.output_base = ""
        self.container = "mp4"
        self.lastdir = ""
        self.auto_output = True
        self.bluray_enabled = False
        self.advanced_mode = False
        self.probe = ProbeInfo()
        self.audio_tracks = []
        self.audio_rows = []
        self.subtitle_tracks = []
        self.subtitle_rows = []
        self.thread = None
        self.download_thread = None
        self.crop_worker = None
        self.hw_thread = None
        self.mux_thread = None
        self.mux_rows = []
        self._had_failure = False
        self.encoder_profile_overrides = {}
        self._encoder_profile_name = ""

        self._rotate_log()
        self.build_ui()
        self.update_track_heights()
        self.fit_edit_to_content(self.txt_cmd)
        self.fit_edit_to_content(self.txt_mux_cmd, 30, 100)
        self._cmd_timer = QTimer(self)
        self._cmd_timer.setSingleShot(True)
        self._cmd_timer.setInterval(400)
        self._cmd_timer.timeout.connect(self._auto_refresh_command)
        self._wire_command_signals()
        self.load_presets()
        self.load_settings()
        self.load_queue()
        self.show_initial_info()
        self.start_hw_detection()

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #
    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        root.addWidget(self.build_files_group())

        self.tabs = QTabWidget()
        self.tabs.addTab(self.build_video_tab(), "Video")
        self.tabs.addTab(self.build_avisynth_tab(), "AviSynth+")
        self.tabs.addTab(self.build_bluray_tab(), "Blu-ray")
        self.tabs.addTab(self.build_tracks_tab(), "Tracks")
        self.tabs.addTab(self.build_info_tab(), "Info")
        self.tabs.addTab(self.build_queue_tab(), "Queue")
        self.tabs.addTab(self.build_ffmpeg_tab(), "FFmpeg")
        self.tabs.addTab(self.build_profiles_tab(), "Profiles")
        self.tabs.addTab(self.build_encoder_options_tab(), "Encoder options")
        self.tabs.addTab(self.build_mux_tab(), "Tools - Muxing")
        self.tabs.addTab(self.build_manual_tab(), "Manual")
        self.tabs.addTab(self.build_log_tab(), "Log")
        self.set_advanced_mode(False)
        root.addWidget(self.tabs, 1)

        root.addWidget(self.build_command_group())
        root.addWidget(self.build_encoding_group())

        self.build_statusbar()
        self.connect_signals()

    def build_files_group(self):
        fg = QGroupBox("Source File")
        grid = QGridLayout(fg)
        grid.addWidget(QLabel("Input:"), 0, 0)
        self.inp_input = QLineEdit()
        self.inp_input.setReadOnly(True)
        self.inp_input.setToolTip("Source media file to convert")
        grid.addWidget(self.inp_input, 0, 1)
        self.btn_open = QPushButton("Browse...")
        self.btn_open.setToolTip("Select the input media file")
        grid.addWidget(self.btn_open, 0, 2)
        self.btn_folder = QPushButton("Add folder")
        self.btn_folder.setToolTip("Add every media file in a folder to the queue")
        grid.addWidget(self.btn_folder, 0, 3)
        self.btn_play = QPushButton("Play")
        self.btn_play.setToolTip("Play the input file with ffplay")
        grid.addWidget(self.btn_play, 0, 4)
        self.btn_preview = QPushButton("Preview")
        self.btn_preview.setToolTip("Preview with resize/crop/deinterlace filters applied")
        grid.addWidget(self.btn_preview, 0, 5)
        self.btn_shots = QPushButton("Shots")
        self.btn_shots.setToolTip("Extract preview thumbnails with ffmpeg")
        grid.addWidget(self.btn_shots, 0, 6)
        self.btn_wizard = QPushButton("Quick wizard")
        self.btn_wizard.setToolTip("Guided setup for a complete encode job")
        grid.addWidget(self.btn_wizard, 0, 7)
        self.btn_bluray = QPushButton("Blu-ray...")
        self.btn_bluray.setToolTip("Open a Blu-ray ISO or BDMV folder")
        grid.addWidget(self.btn_bluray, 0, 8)
        self.btn_advanced = QPushButton("Advanced options")
        self.btn_advanced.setToolTip(
            "Show Blu-ray, profiles, FFmpeg and log tabs")
        grid.addWidget(self.btn_advanced, 1, 7, 1, 2)

        grid.addWidget(QLabel("Output name:"), 1, 0)
        self.inp_output = QLineEdit()
        self.inp_output.setToolTip(
            "Final output path without extension; choose the container next")
        grid.addWidget(self.inp_output, 1, 1)
        self.cmb_container = QComboBox()
        for label in ("MP4", "MKV", "MOV", "AVI"):
            self.cmb_container.addItem(label, label.lower())
        self.cmb_container.setToolTip(
            "MP4 is muxed directly by FFmpeg; MKV uses mkvmerge when available")
        grid.addWidget(self.cmb_container, 1, 2)
        self.btn_save = QPushButton("Browse...")
        self.btn_save.setToolTip("Choose the output base name")
        grid.addWidget(self.btn_save, 1, 3)
        self.lbl_drop = QLabel("Drag & drop a file or folder here")
        self.lbl_drop.setStyleSheet("color: #6c7086;")
        grid.addWidget(self.lbl_drop, 1, 4, 1, 5)
        return fg

    def build_command_group(self):
        g = QGroupBox("Generated command")
        lay = QVBoxLayout(g)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(2)
        self.txt_cmd = QPlainTextEdit()
        self.txt_cmd.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.txt_cmd.setPlaceholderText(
            "The generated ffmpeg command appears here automatically. "
            "You can edit it and run it directly.")
        self.txt_cmd.setFont(QFont("monospace", 9))
        self.txt_cmd.setToolTip(
            "The generated ffmpeg command. It updates automatically as you "
            "change options; you can edit it and run it directly.")
        self.txt_cmd.textChanged.connect(
            lambda: self.fit_edit_to_content(self.txt_cmd))
        lay.addWidget(self.txt_cmd)
        row = QHBoxLayout()
        self.lbl_cmd_info = QLabel("")
        self.btn_preview_cmd = QPushButton("Preview command")
        self.btn_preview_cmd.setToolTip("Regenerate the command preview now")
        self.btn_run_edited = QPushButton("Run edited command")
        self.btn_run_edited.setToolTip("Run the command exactly as edited above")
        row.addWidget(self.lbl_cmd_info)
        row.addStretch(1)
        row.addWidget(self.btn_preview_cmd)
        row.addWidget(self.btn_run_edited)
        lay.addLayout(row)
        return g

    def build_encoding_group(self):
        pg = QGroupBox("Encoding")
        prow = QHBoxLayout(pg)
        vcol = QVBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.lbl_stats = QLabel("")
        self.lbl_stats.setStyleSheet(
            f"color: {THEMES[self.theme]['success']}; font-family: monospace;")
        vcol.addWidget(self.progress)
        vcol.addWidget(self.lbl_stats)
        prow.addLayout(vcol, 1)
        self.lbl_status = QLabel("Ready")
        prow.addWidget(self.lbl_status)
        self.cmb_after = QComboBox()
        self.cmb_after.addItems(POST_ACTIONS)
        self.cmb_after.setToolTip("Action to run when the queue finishes")
        prow.addWidget(self.cmb_after)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("danger")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setToolTip("Cancel the running jobs")
        self.btn_encode = QPushButton("Encode")
        self.btn_encode.setObjectName("primary")
        self.btn_encode.setShortcut("Ctrl+E")
        self.btn_encode.setToolTip("Start encoding the current file (Ctrl+E)")
        self.btn_addqueue = QPushButton("Add to Queue")
        self.btn_addqueue.setToolTip("Add the current job to the queue without starting it")
        self.btn_startqueue = QPushButton("Start Queue")
        self.btn_startqueue.setToolTip("Start all the queued jobs")
        prow.addWidget(self.btn_cancel)
        prow.addWidget(self.btn_encode)
        prow.addWidget(self.btn_addqueue)
        prow.addWidget(self.btn_startqueue)
        return pg

    def build_statusbar(self):
        self.statusBar().showMessage("Ready")
        self.paypal_btn = QPushButton()
        logo = os.path.join(APP_DIR, "_paypal_logo.png")
        if os.path.exists(logo):
            self.paypal_btn.setIcon(QIcon(logo))
            self.paypal_btn.setIconSize(QSize(85, 25))
            self.paypal_btn.setFixedSize(105, 35)
        else:
            self.paypal_btn.setText("Donate")
        self.paypal_btn.setToolTip("Support AutoFFmpegGui with PayPal")
        self.statusBar().addPermanentWidget(self.paypal_btn)
        self.paypal_btn.clicked.connect(self.open_paypal)
        self.theme_btn = QPushButton()
        self.theme_btn.setFixedSize(58, 24)
        self.theme_btn.setToolTip("Toggle light / dark theme")
        self.statusBar().addPermanentWidget(self.theme_btn)
        self.theme_btn.clicked.connect(self.toggle_theme)
        self.update_theme_button()

    def connect_signals(self):
        self.btn_open.clicked.connect(self.openinputfile)
        self.btn_save.clicked.connect(self.savefile)
        self.btn_play.clicked.connect(self.play)
        self.btn_preview.clicked.connect(self.preview)
        self.btn_shots.clicked.connect(self.screenshots)
        self.btn_wizard.clicked.connect(self.open_wizard)
        self.btn_bluray.clicked.connect(self.choose_bluray_source)
        self.btn_advanced.clicked.connect(
            lambda: self.set_advanced_mode(not self.advanced_mode))
        self.btn_folder.clicked.connect(self.add_folder)
        self.btn_encode.clicked.connect(self.do_encode)
        self.btn_addqueue.clicked.connect(self.addtoqueue)
        self.btn_startqueue.clicked.connect(self.startqueue)
        self.btn_cancel.clicked.connect(self.cancel_encode)
        self.btn_preview_cmd.clicked.connect(lambda: self.preview_command())
        self.btn_run_edited.clicked.connect(self.run_edited)
        self.cmb_processor.currentIndexChanged.connect(
            lambda *_: self.on_processor_changed())
        self.cmb_preset.currentIndexChanged.connect(self.on_preset_changed)
        self.cmb_mode.currentIndexChanged.connect(self.on_mode_changed)
        self.cmb_external_encoder.currentIndexChanged.connect(
            lambda *_: self.on_external_encoder_changed())
        self.cmb_hw.currentIndexChanged.connect(self.on_mode_changed)
        self.cmb_hdr.currentIndexChanged.connect(self.on_hdr_changed)
        self.btn_hdr_meta.clicked.connect(self.choose_hdr_meta)
        self.sld_quality.valueChanged.connect(self.on_quality_changed)
        self.spin_quality.valueChanged.connect(self.sld_quality.setValue)
        self.chk_resize.toggled.connect(self.on_resize_toggled)
        self.btn_autocrop.clicked.connect(self.autocrop)
        self.btn_calc.clicked.connect(self.calc_bitrate)
        self.inp_cds.returnPressed.connect(self.calc_bitrate)
        self.chk_nomux.toggled.connect(self.on_nomux_toggled)
        self.inp_output.textEdited.connect(
            self.on_output_base_changed)
        self.cmb_container.currentIndexChanged.connect(
            lambda *_: self.on_container_changed())
        self.sld_trackwidth.valueChanged.connect(lambda _: self.on_size_pct())
        self.inp_width.textEdited.connect(lambda _: self.silentscale())
        self.tbl_encoder_options.cellChanged.connect(
            lambda *_: self.schedule_command_refresh())

    def _wire_command_signals(self):
        """Regenerate the command preview whenever a relevant option changes."""
        for w in (self.cmb_preset, self.cmb_mode, self.cmb_hw, self.cmb_hdr,
                  self.cmb_framerate, self.cmb_mod):
            w.currentIndexChanged.connect(
                lambda *_: self.schedule_command_refresh())
        self.cmb_framerate.currentTextChanged.connect(
            lambda *_: self.schedule_command_refresh())
        for w in (self.sld_quality, self.sld_trackwidth, self.spin_gain,
                  self.spin_quality):
            w.valueChanged.connect(lambda *_: self.schedule_command_refresh())
        for w in (self.inp_bitrate, self.inp_vframes, self.inp_trim_start,
                  self.inp_trim_end, self.inp_width, self.inp_height,
                  self.inp_leftcrop, self.inp_rightcrop, self.inp_topcrop,
                  self.inp_bottomcrop, self.inp_masterdisplay, self.inp_maxcll):
            w.textEdited.connect(lambda *_: self.schedule_command_refresh())
        self.inp_hdr_meta.textChanged.connect(
            lambda *_: self.schedule_command_refresh())
        self.cmb_avs_source.currentTextChanged.connect(
            lambda *_: self.schedule_command_refresh())
        self.cmb_avs_filter_mode.currentTextChanged.connect(
            lambda *_: self.schedule_command_refresh())
        self.inp_avs_plugins.textChanged.connect(
            lambda *_: self.schedule_command_refresh())
        for w in (self.chk_deinterlace, self.chk_nomux, self.chk_chapters,
                  self.chk_metadata, self.chk_keep_generated, self.chk_resize,
                  self.chk_normalize):
            w.toggled.connect(lambda *_: self.schedule_command_refresh())

    def schedule_command_refresh(self):
        if hasattr(self, "_cmd_timer"):
            self._cmd_timer.start()

    def _auto_refresh_command(self):
        if self.inputfile:
            self.preview_command(silent=True)

    def open_paypal(self):
        QMessageBox.information(
            self, "Thanks For Your Support!",
            "Without your donation AutoFFmpegGui will be never a better application!")
        QDesktopServices.openUrl(QUrl(PAYPAL_URL))

    def open_wizard(self):
        self.wizard = QuickEncodeWizard(self)
        self.wizard.show()

    def set_advanced_mode(self, enabled):
        self.advanced_mode = bool(enabled)
        # Muxing and encoder options are part of the normal encode workflow.
        # Only tools that are not needed for every job remain advanced.
        for title in ("Blu-ray", "Profiles", "FFmpeg"):
            index = next((i for i in range(self.tabs.count())
                          if self.tabs.tabText(i) == title), -1)
            if index >= 0:
                self.tabs.setTabVisible(index, self.advanced_mode)
        self.update_avisynth_tab_visibility(
            hasattr(self, "chk_avisynth") and self.chk_avisynth.isChecked())
        if hasattr(self, "btn_advanced"):
            self.btn_advanced.setText(
                "Hide advanced options" if self.advanced_mode
                else "Advanced options")

    # ------------------------------------------------------------------ #
    # Tabs
    # ------------------------------------------------------------------ #
    def build_video_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(10)
        columns = QHBoxLayout()
        columns.setSpacing(8)
        left = QVBoxLayout()
        left.setSpacing(10)
        right = QVBoxLayout()
        right.setSpacing(8)

        vg = QGroupBox("Video encoding")
        vg.setMinimumHeight(390)
        gl = QGridLayout(vg)
        gl.setContentsMargins(8, 8, 8, 8)
        gl.setVerticalSpacing(2)
        gl.setHorizontalSpacing(6)
        gl.addWidget(QLabel("Process with:"), 0, 0)
        self.cmb_processor = QComboBox()
        self.cmb_processor.addItem("FFmpeg (filters and encoding)", "ffmpeg")
        self.cmb_processor.addItem("AviSynth+ (script and filters)", "avisynth")
        self.cmb_processor.setToolTip(
            "Choose the video processing engine. AviSynth+ enables the "
            "AviSynth+ tab with its script editor and filters.")
        gl.addWidget(self.cmb_processor, 0, 1, 1, 3)

        gl.addWidget(QLabel("Video encoder:"), 1, 0)
        self.cmb_external_encoder = QComboBox()
        self.cmb_external_encoder.addItem("FFmpeg (internal)", "")
        self.cmb_external_encoder.addItem("x264 CLI (external)", "x264")
        self.cmb_external_encoder.addItem("x265 CLI (external)", "x265")
        self.cmb_external_encoder.setToolTip(
            "Explicitly select an external encoder. FFmpeg/AviSynth decode "
            "the video and pipe Y4M frames to the selected CLI encoder.")
        gl.addWidget(self.cmb_external_encoder, 1, 1, 1, 3)

        gl.addWidget(QLabel("Preset:"), 2, 0)
        self.cmb_preset = QComboBox()
        self.cmb_preset.setToolTip("Video encoding preset / profile")
        gl.addWidget(self.cmb_preset, 2, 1, 1, 3)

        gl.addWidget(QLabel("Mode:"), 3, 0)
        self.cmb_mode = QComboBox()
        self.cmb_mode.setToolTip(
            "Quality (CRF) targets a visual quality, bitrate modes target a "
            "size, and copy/remux/audio-only avoid re-encoding")
        self.cmb_mode.addItems(
            ["Quality (CRF)", "1-pass bitrate", "2-pass bitrate",
             "Copy video", "Remux (copy all)", "Audio only"])
        gl.addWidget(self.cmb_mode, 3, 1, 1, 3)

        gl.addWidget(QLabel("HW accel:"), 4, 0)
        self.cmb_hw = QComboBox()
        self.cmb_hw.setToolTip(
            "Hardware accelerated encoders actually present in your ffmpeg build")
        gl.addWidget(self.cmb_hw, 4, 1, 1, 3)
        self.populate_hw()

        self.lbl_quality = QLabel("Quality:")
        gl.addWidget(self.lbl_quality, 5, 0)
        self.sld_quality = QSlider(Qt.Orientation.Horizontal)
        self.sld_quality.setRange(0, 51)
        self.sld_quality.setValue(23)
        gl.addWidget(self.sld_quality, 5, 1, 1, 2)
        self.spin_quality = QSpinBox()
        self.spin_quality.setRange(0, 51)
        self.spin_quality.setValue(23)
        gl.addWidget(self.spin_quality, 5, 3)

        gl.addWidget(QLabel("Bitrate:"), 6, 0)
        self.inp_bitrate = QLineEdit("2000")
        self.inp_bitrate.setValidator(QIntValidator(0, 100000, self))
        self.inp_bitrate.setToolTip("Target video bitrate in kbit/s")
        gl.addWidget(self.inp_bitrate, 6, 1)
        gl.addWidget(QLabel("kbit/s"), 6, 2, 1, 2)

        gl.addWidget(QLabel("Target MB:"), 7, 0)
        self.inp_cds = QLineEdit("700")
        self.inp_cds.setValidator(QIntValidator(0, 100000, self))
        self.inp_cds.setToolTip("Desired total file size in MB")
        gl.addWidget(self.inp_cds, 7, 1)
        self.btn_calc = QPushButton("Calculate")
        self.btn_calc.setToolTip(
            "Compute the video bitrate from the target size and audio bitrates")
        gl.addWidget(self.btn_calc, 7, 2, 1, 2)

        gl.addWidget(QLabel("FPS:"), 8, 0)
        self.cmb_framerate = QComboBox()
        self.cmb_framerate.setEditable(True)
        self.cmb_framerate.setToolTip(
            "Output frame rate (\"automatic\" keeps the source rate)")
        self.cmb_framerate.addItems(
            ["automatic", "23.976", "24", "25", "29.97", "30", "50",
             "59.94", "60"])
        self.cmb_framerate.setCurrentIndex(0)
        gl.addWidget(self.cmb_framerate, 8, 1)
        gl.addWidget(QLabel("Frames:"), 8, 2)
        self.inp_vframes = QLineEdit()
        self.inp_vframes.setValidator(QIntValidator(0, 999999999, self))
        self.inp_vframes.setToolTip(
            "Maximum number of frames to encode (empty = all frames)")
        gl.addWidget(self.inp_vframes, 8, 3)

        gl.addWidget(QLabel("Trim:"), 9, 0)
        self.inp_trim_start = QLineEdit()
        self.inp_trim_start.setPlaceholderText("start (HH:MM:SS)")
        self.inp_trim_start.setToolTip("Start time (HH:MM:SS or seconds)")
        gl.addWidget(self.inp_trim_start, 9, 1)
        self.inp_trim_end = QLineEdit()
        self.inp_trim_end.setPlaceholderText("end (HH:MM:SS)")
        self.inp_trim_end.setToolTip("End time (HH:MM:SS or seconds)")
        gl.addWidget(self.inp_trim_end, 9, 2, 1, 2)

        self.chk_deinterlace = QCheckBox("Deinterlace (yadif)")
        self.chk_deinterlace.setToolTip("Deinterlace interlaced video (yadif)")
        gl.addWidget(self.chk_deinterlace, 10, 0, 1, 2)
        self.chk_chapters = QCheckBox("Keep chapters")
        self.chk_chapters.setToolTip("Copy the chapters from the source")
        gl.addWidget(self.chk_chapters, 10, 2)
        self.chk_metadata = QCheckBox("Keep metadata")
        self.chk_metadata.setToolTip("Copy the global metadata from the source")
        gl.addWidget(self.chk_metadata, 10, 3)

        self.chk_nomux = QCheckBox("Export separate streams (no mux)")
        self.chk_nomux.setToolTip(
            "Write each stream (video, per-track audio, per-track subtitle) "
            "to its own file instead of muxing them into one container")
        gl.addWidget(self.chk_nomux, 11, 0, 1, 4)
        self.chk_keep_generated = QCheckBox("Keep generated stream files")
        self.chk_keep_generated.setToolTip(
            "Keep generated video, audio, subtitle and intermediate files in "
            "a folder named after the input file")
        gl.addWidget(self.chk_keep_generated, 12, 0, 1, 4)

        self.lbl_mode_warning = QLabel("")
        self.lbl_mode_warning.setWordWrap(True)
        gl.addWidget(self.lbl_mode_warning, 13, 0, 1, 4)

        self.source_box = QGroupBox("Source file")
        source_layout = QVBoxLayout(self.source_box)
        source_layout.setContentsMargins(8, 4, 8, 4)
        source_layout.setSpacing(2)
        self.source_box.setMaximumHeight(95)
        self.lbl_source_summary = QLabel("No file loaded")
        self.lbl_source_summary.setWordWrap(True)
        source_layout.addWidget(self.lbl_source_summary)
        left.addWidget(self.source_box)

        left.addWidget(vg)

        rg = QGroupBox("Resize / crop")
        rl = QGridLayout(rg)
        rl.setContentsMargins(10, 10, 10, 10)
        rl.setVerticalSpacing(4)
        rl.setHorizontalSpacing(8)
        rg.setMinimumHeight(200)
        self.chk_resize = QCheckBox("Allow resize / crop")
        self.chk_resize.setChecked(True)
        self.chk_resize.setToolTip("Enable resize and crop of the video")
        rl.addWidget(self.chk_resize, 0, 0, 1, 3)

        self.inp_width = QLineEdit()
        self.inp_width.setValidator(QIntValidator(1, 99999, self))
        self.inp_width.setToolTip("Target width in pixels")
        self.inp_height = QLineEdit()
        self.inp_height.setValidator(QIntValidator(1, 99999, self))
        self.inp_height.setToolTip("Target height in pixels")
        self.cmb_mod = QComboBox()
        self.cmb_mod.addItems(["2", "4", "8", "16", "32"])
        self.cmb_mod.setCurrentText("16")
        self.cmb_mod.setToolTip("Dimension modulus used to round the size")
        wrow = QHBoxLayout()
        wrow.setSpacing(4)
        wrow.addWidget(QLabel("Size:"))
        wrow.addWidget(self.inp_width)
        wrow.addWidget(QLabel("x"))
        wrow.addWidget(self.inp_height)
        wrow.addWidget(QLabel("MOD:"))
        wrow.addWidget(self.cmb_mod)
        rl.addLayout(wrow, 1, 0, 1, 3)

        self.sld_trackwidth = QSlider(Qt.Orientation.Horizontal)
        self.sld_trackwidth.setRange(10, 200)
        self.sld_trackwidth.setValue(100)
        self.sld_trackwidth.setToolTip("Resize percentage (100% = original size)")
        rl.addWidget(QLabel("Size %:"), 2, 0)
        rl.addWidget(self.sld_trackwidth, 2, 1, 1, 2)

        self.btn_autocrop = QPushButton("Auto crop")
        self.btn_autocrop.setToolTip("Detect black borders with ffmpeg cropdetect")
        rl.addWidget(self.btn_autocrop, 3, 0, 1, 3)

        self.inp_leftcrop = QLineEdit("0")
        self.inp_rightcrop = QLineEdit("0")
        self.inp_topcrop = QLineEdit("0")
        self.inp_bottomcrop = QLineEdit("0")
        for e, tip in ((self.inp_leftcrop, "Crop pixels from the left"),
                       (self.inp_rightcrop, "Crop pixels from the right"),
                       (self.inp_topcrop, "Crop pixels from the top"),
                       (self.inp_bottomcrop, "Crop pixels from the bottom")):
            e.setValidator(QIntValidator(0, 99999, self))
            e.setToolTip(tip)
        croprow = QHBoxLayout()
        croprow.setSpacing(3)
        croprow.addWidget(QLabel("Crop:"))
        croprow.addWidget(self.inp_leftcrop)
        croprow.addWidget(QLabel("L"))
        croprow.addWidget(self.inp_rightcrop)
        croprow.addWidget(QLabel("R"))
        croprow.addWidget(self.inp_topcrop)
        croprow.addWidget(QLabel("T"))
        croprow.addWidget(self.inp_bottomcrop)
        croprow.addWidget(QLabel("B"))
        rl.addLayout(croprow, 4, 0, 1, 3)

        self.inp_dar = QLineEdit()
        self.inp_dar.setReadOnly(True)
        self.inp_dar.setToolTip("Display aspect ratio of the output size")
        rl.addWidget(QLabel("DAR:"), 5, 0)
        rl.addWidget(self.inp_dar, 5, 1, 1, 2)
        right.addWidget(rg)

        hg = QGroupBox("HDR / Color")
        hl = QGridLayout(hg)
        hl.setContentsMargins(10, 10, 10, 10)
        hl.setVerticalSpacing(4)
        hl.setHorizontalSpacing(8)
        hg.setMinimumHeight(200)
        hl.addWidget(QLabel("Mode:"), 0, 0)
        self.cmb_hdr = QComboBox()
        self.cmb_hdr.addItems(HDR_MODES)
        self.cmb_hdr.setToolTip(
            "HDR10 / HLG: 10-bit BT.2020 with PQ/HLG.\n"
            "HDR10+: needs a JSON metadata file.\n"
            "Dolby Vision: re-encodes using the source DV RPU (dovi_tool).")
        hl.addWidget(self.cmb_hdr, 0, 1, 1, 2)

        hl.addWidget(QLabel("HDR10+ file:"), 1, 0)
        self.inp_hdr_meta = QLineEdit()
        self.inp_hdr_meta.setToolTip("HDR10+ JSON metadata file")
        self.btn_hdr_meta = QPushButton("...")
        self.btn_hdr_meta.setFixedWidth(36)
        self.btn_hdr_meta.setToolTip("Browse for the HDR10+ JSON file")
        row = QHBoxLayout()
        row.addWidget(self.inp_hdr_meta)
        row.addWidget(self.btn_hdr_meta)
        hl.addLayout(row, 1, 1, 1, 2)

        hl.addWidget(QLabel("Master display:"), 2, 0)
        self.inp_masterdisplay = QLineEdit()
        self.inp_masterdisplay.setToolTip("x265 master-display metadata (BT.2020/P3)")
        hl.addWidget(self.inp_masterdisplay, 2, 1, 1, 2)

        hl.addWidget(QLabel("MaxCLL/FALL:"), 3, 0)
        self.inp_maxcll = QLineEdit()
        self.inp_maxcll.setToolTip("MaxCLL,MaxFALL in nits, e.g. 1000,400")
        hl.addWidget(self.inp_maxcll, 3, 1, 1, 2)

        self.lbl_hdrinfo = QLabel("")
        self.lbl_hdrinfo.setWordWrap(True)
        hl.addWidget(self.lbl_hdrinfo, 4, 0, 1, 3)
        right.addWidget(hg)
        right.addStretch(1)

        columns.addLayout(left, 4)
        columns.addLayout(right, 6)
        columns.setStretch(0, 4)
        columns.setStretch(1, 6)
        lay.addLayout(columns, 0)
        lay.addStretch(1)
        return w

    def build_avisynth_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(7)
        info = QLabel(
            "AviSynth+ is an executable video source. AutoFFmpeg keeps audio "
            "and subtitles from the original file when it generates a script; "
            "an external .avs script is used as the complete source.")
        info.setWordWrap(True)
        lay.addWidget(info)

        cfg = QGroupBox("AviSynth source")
        gl = QGridLayout(cfg)
        self.chk_avisynth = QCheckBox("Enable AviSynth+ processing")
        self.chk_avisynth.setToolTip(
            "Generate/use an .avs video source before the FFmpeg encoder")
        gl.addWidget(self.chk_avisynth, 0, 0, 1, 3)
        gl.addWidget(QLabel("Source filter:"), 1, 0)
        self.cmb_avs_source = QComboBox()
        self.cmb_avs_source.addItems(
            ["FFVideoSource", "LWLibavVideoSource", "AviSource"])
        self.cmb_avs_source.setToolTip(
            "Function used by the generated template; its plugin must be installed")
        gl.addWidget(self.cmb_avs_source, 1, 1)
        gl.addWidget(QLabel("Filter ownership:"), 1, 2)
        self.cmb_avs_filter_mode = QComboBox()
        self.cmb_avs_filter_mode.addItem("AviSynth script", "script")
        self.cmb_avs_filter_mode.addItem("FFmpeg GUI filters", "ffmpeg")
        self.cmb_avs_filter_mode.addItem("Both (advanced)", "both")
        self.cmb_avs_filter_mode.setToolTip(
            "Avoid duplicate resize/deinterlace processing unless Both is intentional")
        gl.addWidget(self.cmb_avs_filter_mode, 1, 3)
        gl.addWidget(QLabel("External script:"), 2, 0)
        self.inp_avs_path = QLineEdit()
        self.inp_avs_path.setToolTip(
            "Optional existing .avs file. Leave empty to generate one from the editor")
        self.btn_avs_browse = QPushButton("Browse...")
        gl.addWidget(self.inp_avs_path, 2, 1, 1, 2)
        gl.addWidget(self.btn_avs_browse, 2, 3)
        gl.addWidget(QLabel("Plugin paths:"), 3, 0)
        self.inp_avs_plugins = QLineEdit()
        self.inp_avs_plugins.setPlaceholderText("path1.dll;path2.dll")
        self.inp_avs_plugins.setToolTip("Optional DLL paths, separated by ;")
        self.inp_avs_plugins.setText(";".join(default_avisynth_plugin_paths()))
        gl.addWidget(self.inp_avs_plugins, 3, 1, 1, 3)
        lay.addWidget(cfg)

        self.txt_avs = QPlainTextEdit()
        self.txt_avs.setFont(QFont("monospace", 9))
        self.txt_avs.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.txt_avs.setPlaceholderText(
            "Use {{INPUT}}, {{SOURCE_FILTER}}, {{PLUGIN_LOADS}} and "
            "{{VIDEO_FILTERS}} in a generated script")
        lay.addWidget(self.txt_avs, 1)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Insert filter:"))
        self.cmb_avs_filter = QComboBox()
        self.cmb_avs_filter.setEditable(True)
        self.cmb_avs_filter.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.cmb_avs_filter.lineEdit().setPlaceholderText(
            "Filter name or AviSynth line")
        self.cmb_avs_filter.setToolTip(
            "Choose a preset or type a custom filter, for example "
            "TemporalDegrain2 or TemporalDegrain2()")
        for name, snippet in AVS_FILTERS:
            self.cmb_avs_filter.addItem(name, snippet)
        self.btn_avs_insert_filter = QPushButton("Insert")
        filter_row.addWidget(self.cmb_avs_filter, 1)
        filter_row.addWidget(self.btn_avs_insert_filter)
        lay.addLayout(filter_row)
        row = QHBoxLayout()
        self.btn_avs_template = QPushButton("Generate template")
        self.btn_avs_load = QPushButton("Load script")
        self.btn_avs_save = QPushButton("Save script")
        self.btn_avs_validate = QPushButton("Validate")
        self.btn_avs_preview = QPushButton("Preview")
        for button in (self.btn_avs_template, self.btn_avs_load,
                       self.btn_avs_save, self.btn_avs_validate,
                       self.btn_avs_preview, self.cmb_avs_filter,
                       self.btn_avs_insert_filter):
            row.addWidget(button)
        row.addStretch(1)
        self.lbl_avs_status = QLabel("Disabled")
        row.addWidget(self.lbl_avs_status)
        lay.addLayout(row)
        self.btn_avs_browse.clicked.connect(self.choose_avs_script)
        self.btn_avs_template.clicked.connect(self.generate_avs_template)
        self.btn_avs_load.clicked.connect(self.load_avs_script)
        self.btn_avs_save.clicked.connect(self.save_avs_script)
        self.btn_avs_validate.clicked.connect(self.validate_avs)
        self.btn_avs_preview.clicked.connect(self.preview)
        self.btn_avs_insert_filter.clicked.connect(self.insert_avs_filter)
        self.chk_avisynth.toggled.connect(self.on_avisynth_toggled)
        self.txt_avs.textChanged.connect(lambda: self.schedule_command_refresh())
        self.inp_avs_path.textChanged.connect(lambda: self.schedule_command_refresh())
        self.generate_avs_template()
        self.on_avisynth_toggled(False)
        return w

    def insert_avs_filter(self):
        name = self.cmb_avs_filter.currentText().strip()
        snippet = self.cmb_avs_filter.currentData() or ""
        current_index = self.cmb_avs_filter.currentIndex()
        current_name = (self.cmb_avs_filter.itemText(current_index)
                        if current_index >= 0 else "")
        if name != current_name:
            snippet = ""
        if not snippet and name:
            if name.startswith("src ="):
                snippet = name
            elif name.startswith("src."):
                snippet = "src = " + name
            elif "(" in name and name.endswith(")"):
                snippet = "src = src." + name
            else:
                snippet = f"src = src.{name}()"
            self.cmb_avs_filter.addItem(name, snippet)
            self.cmb_avs_filter.setCurrentIndex(
                self.cmb_avs_filter.count() - 1)
        if snippet:
            self.txt_avs.insertPlainText("\n" + snippet + "\n")
            self.lbl_avs_status.setText("Filter inserted")

    def generate_avs_template(self):
        if not self.txt_avs.toPlainText().strip() or \
                self.sender() == self.btn_avs_template:
            self.txt_avs.setPlainText(
                '# AutoFFmpegGui AviSynth+ script\n'
                '# Replace/add filters below as needed.\n'
                '{{PLUGIN_LOADS}}\n'
                'src = {{SOURCE_FILTER}}("{{INPUT}}")\n'
                '{{VIDEO_FILTERS}}\n'
                'src\n')
        self.lbl_avs_status.setText("Template ready")

    def on_avisynth_toggled(self, enabled):
        for widget in (self.cmb_avs_source, self.cmb_avs_filter_mode,
                       self.inp_avs_path, self.btn_avs_browse,
                       self.inp_avs_plugins, self.txt_avs,
                       self.btn_avs_template, self.btn_avs_load,
                       self.btn_avs_save, self.btn_avs_validate,
                       self.btn_avs_preview):
            widget.setEnabled(enabled)
        self.lbl_avs_status.setText("Enabled" if enabled else "Disabled")
        if hasattr(self, "cmb_processor"):
            target = "avisynth" if enabled else "ffmpeg"
            index = self.cmb_processor.findData(target)
            if index >= 0 and self.cmb_processor.currentIndex() != index:
                self.cmb_processor.blockSignals(True)
                self.cmb_processor.setCurrentIndex(index)
                self.cmb_processor.blockSignals(False)
        self.update_avisynth_tab_visibility(enabled)
        self.schedule_command_refresh()

    def update_avisynth_tab_visibility(self, enabled):
        """Show AviSynth controls only when AviSynth is the selected engine."""
        if not hasattr(self, "tabs"):
            return
        index = next((i for i in range(self.tabs.count())
                      if self.tabs.tabText(i) == "AviSynth+"), -1)
        if index < 0:
            return
        self.tabs.setTabVisible(index, bool(enabled))
        if not enabled and self.tabs.currentIndex() == index:
            self.tabs.setCurrentIndex(0)

    def on_processor_changed(self):
        enabled = self.cmb_processor.currentData() == "avisynth"
        if self.chk_avisynth.isChecked() != enabled:
            self.chk_avisynth.setChecked(enabled)
        else:
            self.update_avisynth_tab_visibility(enabled)
            self.schedule_command_refresh()

    def choose_avs_script(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Open AviSynth script", self.lastdir,
            "AviSynth scripts (*.avs);;All files (*.*)")
        if f:
            self.inp_avs_path.setText(f)
            self.load_avs_script()

    def load_avs_script(self):
        path = self.get_text(self.inp_avs_path).strip()
        if not path:
            return
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                self.txt_avs.setPlainText(fh.read())
            self.lbl_avs_status.setText(f"Loaded {Path(path).name}")
        except OSError as exc:
            QMessageBox.warning(self, "AviSynth+", f"Could not load script: {exc}")

    def save_avs_script(self):
        path = self.get_text(self.inp_avs_path).strip()
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save AviSynth script", self.lastdir,
                "AviSynth scripts (*.avs);;All files (*.*)")
        if not path:
            return
        try:
            Path(path).write_text(self.txt_avs.toPlainText(), encoding="utf-8")
            self.inp_avs_path.setText(path)
            self.lbl_avs_status.setText(f"Saved {Path(path).name}")
        except OSError as exc:
            QMessageBox.warning(self, "AviSynth+", f"Could not save script: {exc}")

    def validate_avs(self):
        if not self.chk_avisynth.isChecked():
            self.lbl_avs_status.setText("Disabled")
            return
        text = self.txt_avs.toPlainText().strip()
        path = self.get_text(self.inp_avs_path).strip()
        if path and not os.path.exists(path):
            self.lbl_avs_status.setText("Script path does not exist")
            return
        if not text and not path:
            self.lbl_avs_status.setText("Script is empty")
            return
        self.lbl_avs_status.setText(
            "Syntax is evaluated by AviSynth/FFmpeg at preview or encode time")
        self.log("[avisynth] script structure accepted; runtime validation deferred")

    def build_bluray_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        info = QLabel(
            "Blu-ray sources use FFmpeg's libbluray protocol. Choose an ISO or "
            "BDMV folder, then select a playlist/title before analyzing it.")
        info.setWordWrap(True)
        lay.addWidget(info)
        form = QFormLayout()
        row = QHBoxLayout()
        self.inp_bluray_path = QLineEdit()
        self.inp_bluray_path.setToolTip("ISO image or folder containing BDMV")
        self.btn_bluray_choose = QPushButton("Browse...")
        row.addWidget(self.inp_bluray_path, 1)
        row.addWidget(self.btn_bluray_choose)
        form.addRow("Source:", row)
        self.cmb_bluray_titles = QComboBox()
        self.cmb_bluray_titles.addItem("Automatic playlist", -1)
        self.cmb_bluray_titles.currentIndexChanged.connect(
            lambda *_: hasattr(self, "spin_bluray_playlist") and
            self.spin_bluray_playlist.setValue(
                self.cmb_bluray_titles.currentData() or -1))
        form.addRow("Detected title:", self.cmb_bluray_titles)
        self.spin_bluray_playlist = QSpinBox()
        self.spin_bluray_playlist.setRange(-1, 99999)
        self.spin_bluray_playlist.setValue(-1)
        self.spin_bluray_playlist.setSpecialValueText("Automatic")
        form.addRow("Playlist:", self.spin_bluray_playlist)
        self.spin_bluray_angle = QSpinBox()
        self.spin_bluray_angle.setRange(0, 254)
        self.spin_bluray_angle.setSpecialValueText("Default")
        form.addRow("Angle:", self.spin_bluray_angle)
        self.spin_bluray_chapter = QSpinBox()
        self.spin_bluray_chapter.setRange(1, 65534)
        self.spin_bluray_chapter.setValue(1)
        form.addRow("Chapter:", self.spin_bluray_chapter)
        lay.addLayout(form)
        buttons = QHBoxLayout()
        self.btn_bluray_scan = QPushButton("Scan playlists")
        self.btn_bluray_analyze = QPushButton("Use and analyze")
        buttons.addWidget(self.btn_bluray_scan)
        buttons.addWidget(self.btn_bluray_analyze)
        buttons.addStretch(1)
        lay.addLayout(buttons)
        self.txt_bluray_info = QPlainTextEdit()
        self.txt_bluray_info.setReadOnly(True)
        self.txt_bluray_info.setPlaceholderText(
            "Playlist scan details and libbluray diagnostics appear here.")
        lay.addWidget(self.txt_bluray_info, 1)
        self.btn_bluray_choose.clicked.connect(self.choose_bluray_source)
        self.btn_bluray_scan.clicked.connect(self.scan_bluray_source)
        self.btn_bluray_analyze.clicked.connect(self.use_bluray_source)
        return w

    def choose_bluray_source(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Blu-ray ISO", self.lastdir,
            "Blu-ray image (*.iso);;All files (*.*)")
        if not path:
            path = QFileDialog.getExistingDirectory(
                self, "Open Blu-ray BDMV folder", self.lastdir)
        if path:
            self.set_bluray_source(path)

    def set_bluray_source(self, path):
        if not is_bluray_path(path):
            QMessageBox.warning(self, "Blu-ray",
                                "Select an ISO or a folder containing BDMV.")
            return
        self.bluray_enabled = True
        self.set_advanced_mode(True)
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == "Blu-ray":
                self.tabs.setCurrentIndex(index)
                break
        self.inp_bluray_path.setText(path)
        self.inp_input.setText(f"Blu-ray: {path}")
        self.inputfile = path
        self.lastdir = os.path.dirname(path) if os.path.isfile(path) else path
        self.scan_bluray_source()

    def scan_bluray_source(self):
        path = self.get_text(self.inp_bluray_path).strip()
        if not path:
            return
        result = scan_bluray(path)
        text = result.get("raw") or result.get("error") or "No metadata returned."
        self.txt_bluray_info.setPlainText(text)
        self.cmb_bluray_titles.clear()
        self.cmb_bluray_titles.addItem("Automatic playlist", -1)
        for title in result.get("titles", []):
            label = f"Playlist {title['playlist']}"
            if title.get("duration"):
                label += f" ({title['duration']})"
            if title.get("chapters"):
                label += f", {title['chapters']} chapters"
            self.cmb_bluray_titles.addItem(label, title["playlist"])
        if result.get("ok"):
            self.log("[bluray] libbluray scan completed")
        else:
            self.log(f"[bluray] scan failed: {result.get('error', 'unknown error')}")

    def use_bluray_source(self):
        path = self.get_text(self.inp_bluray_path).strip()
        if not path:
            self.choose_bluray_source()
            return
        self.set_bluray_source(path)
        self.analyze()

    def build_encoder_options_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        info = QLabel(
            "Options are attached to the selected video profile. Empty rows are "
            "ignored; custom option names are accepted for newer encoder builds.")
        info.setWordWrap(True)
        lay.addWidget(info)
        row = QHBoxLayout()
        row.addWidget(QLabel("Profile family:"))
        self.cmb_encoder_family = QComboBox()
        self.cmb_encoder_family.addItems(["x264", "x265", "x266", "av1"])
        self.cmb_encoder_family.setEnabled(False)
        self.cmb_encoder_family.setToolTip(
            "Selected automatically from the active video profile")
        row.addWidget(self.cmb_encoder_family)
        self.btn_encoder_catalog = QPushButton("Load catalog")
        self.btn_encoder_clear = QPushButton("Clear overrides")
        row.addWidget(self.btn_encoder_catalog)
        row.addWidget(self.btn_encoder_clear)
        row.addStretch(1)
        lay.addLayout(row)
        self.tbl_encoder_options = QTableWidget(0, 3)
        self.tbl_encoder_options.setHorizontalHeaderLabels(
            ["Option", "Value", "Description"])
        self.tbl_encoder_options.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_encoder_options.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.tbl_encoder_options.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self.tbl_encoder_options.setToolTip(
            "FFmpeg encoder options without the leading dash")
        lay.addWidget(self.tbl_encoder_options, 1)
        self.cmb_encoder_family.currentTextChanged.connect(
            lambda *_: self.load_encoder_catalog())
        self.btn_encoder_catalog.clicked.connect(self.load_encoder_catalog)
        self.btn_encoder_clear.clicked.connect(self.clear_encoder_overrides)
        self.load_encoder_catalog()
        return w

    def load_encoder_catalog(self):
        family = self.get_text(self.cmb_encoder_family)
        current = self.encoder_profile_overrides.get(self._encoder_profile_name)
        if current is None:
            preset = self.current_preset()
            current = {}
            if preset.get("xpreset"):
                current["preset"] = preset["xpreset"]
            raw = list(preset.get("rawargs", []))
            for index, token in enumerate(raw):
                if not token.startswith("-") or token in ("-c:v", "-c"):
                    continue
                key = token.lstrip("-")
                if index + 1 < len(raw) and not raw[index + 1].startswith("-"):
                    current[key] = raw[index + 1]
        catalog = encoder_option_catalog(family)
        self.tbl_encoder_options.setRowCount(0)
        for key, hint in catalog.items():
            row = self.tbl_encoder_options.rowCount()
            self.tbl_encoder_options.insertRow(row)
            self.tbl_encoder_options.setItem(row, 0, QTableWidgetItem(key))
            spec = ENCODER_OPTION_SPECS.get(family, {}).get(key, {})
            self.tbl_encoder_options.setCellWidget(
                row, 1, self.encoder_option_widget(
                    spec, current.get(key, "")))
            self.tbl_encoder_options.setItem(
                row, 2, QTableWidgetItem(
                    self.encoder_option_help(key, hint)))
        self.tbl_encoder_options.insertRow(self.tbl_encoder_options.rowCount())
        row = self.tbl_encoder_options.rowCount() - 1
        custom_key = QTableWidgetItem("custom-option")
        custom_key.setToolTip("Replace this name with any FFmpeg option")
        self.tbl_encoder_options.setItem(row, 0, custom_key)
        custom_value = QLineEdit()
        custom_value.setPlaceholderText("value")
        custom_value.textChanged.connect(lambda *_: self.schedule_command_refresh())
        self.tbl_encoder_options.setCellWidget(row, 1, custom_value)
        self.tbl_encoder_options.setItem(row, 2, QTableWidgetItem("Add any FFmpeg option"))

    def encoder_option_help(self, key, hint):
        help_text = {
            "preset": "Speed versus compression efficiency",
            "tune": "Optimize for content or latency",
            "profile:v": "Decoder compatibility profile",
            "crf": "Constant quality; lower is higher quality",
            "bframes": "Maximum consecutive B-frames",
            "ref": "Reference frame count",
            "keyint": "Maximum GOP length in frames",
            "min-keyint": "Minimum GOP length in frames",
            "aq-mode": "Adaptive quantization mode",
            "aq-strength": "Adaptive quantization intensity",
            "cabac": "Enable CABAC entropy coding",
            "sao": "Enable sample adaptive offset",
            "me": "Motion estimation algorithm",
            "subme": "Sub-pixel motion estimation effort",
            "qp": "Constant quantizer value",
            "usage": "AV1 usage mode",
            "cpu-used": "AV1 speed versus quality preset",
            "film-grain": "AV1 film grain synthesis strength",
        }
        return help_text.get(key, f"Encoder option; profile hint: {hint or 'default'}")

    def encoder_option_widget(self, spec, value):
        kind = spec.get("type", "text")
        value = "" if value is None else str(value)
        if kind == "choice":
            widget = QComboBox()
            for choice in spec.get("choices", []):
                widget.addItem(choice or "Profile default", choice)
            idx = widget.findData(value)
            widget.setCurrentIndex(idx if idx >= 0 else 0)
            widget.currentIndexChanged.connect(
                lambda *_: self.schedule_command_refresh())
            return widget
        if kind == "bool":
            widget = QCheckBox("Enabled")
            widget.setTristate(True)
            if value in ("1", "true", "yes", "on"):
                widget.setCheckState(Qt.CheckState.Checked)
            elif value in ("0", "false", "no", "off"):
                widget.setCheckState(Qt.CheckState.Unchecked)
            else:
                widget.setCheckState(Qt.CheckState.PartiallyChecked)
            widget.setToolTip("Partially checked = profile/FFmpeg default")
            widget.stateChanged.connect(lambda *_: self.schedule_command_refresh())
            return widget
        widget = QLineEdit(value)
        widget.setPlaceholderText("Profile default")
        if kind == "int":
            widget.setValidator(QIntValidator(
                int(spec.get("min", -999999)), int(spec.get("max", 999999)),
                widget))
        elif kind == "float":
            widget.setValidator(QDoubleValidator(
                float(spec.get("min", -999999)), float(spec.get("max", 999999)),
                3, widget))
        widget.textChanged.connect(lambda *_: self.schedule_command_refresh())
        return widget

    def clear_encoder_overrides(self):
        for row in range(self.tbl_encoder_options.rowCount()):
            widget = self.tbl_encoder_options.cellWidget(row, 1)
            if isinstance(widget, QComboBox):
                idx = widget.findData("")
                if idx >= 0:
                    widget.setCurrentIndex(idx)
            elif isinstance(widget, QCheckBox):
                widget.setCheckState(Qt.CheckState.PartiallyChecked)
            elif isinstance(widget, QLineEdit):
                widget.clear()
        self.schedule_command_refresh()

    def encoder_options_from_table(self):
        values = {}
        for row in range(self.tbl_encoder_options.rowCount()):
            key = self.tbl_encoder_options.item(row, 0)
            widget = self.tbl_encoder_options.cellWidget(row, 1)
            if not key or not widget or not key.text().strip():
                continue
            value = ""
            if isinstance(widget, QComboBox):
                value = str(widget.currentData() or "")
            elif isinstance(widget, QCheckBox):
                if widget.checkState() == Qt.CheckState.Checked:
                    value = "1"
                elif widget.checkState() == Qt.CheckState.Unchecked:
                    value = "0"
            elif isinstance(widget, QLineEdit):
                value = widget.text().strip()
            if value:
                values[key.text().strip()] = value
        return values

    def build_tracks_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)
        info = QLabel(
            "Select the audio and subtitle tracks to keep. For each audio "
            "track you can choose the codec, bitrate, channels and sampling "
            "rate; copy leaves the stream untouched.")
        info.setWordWrap(True)
        lay.addWidget(info)

        ag = QGroupBox("Tracks")
        gl2 = QGridLayout(ag)
        gl2.setVerticalSpacing(2)
        gl2.setHorizontalSpacing(6)
        tracks_label = QLabel("Audio:")
        tracks_label.setFixedWidth(52)
        gl2.addWidget(tracks_label, 0, 0, Qt.AlignmentFlag.AlignTop)
        self.audio_list = QListWidget()
        self.audio_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.audio_list.setToolTip(
            "Audio tracks: tick to include, then choose codec, bitrate, "
            "channels and sampling rate")
        gl2.addWidget(self.audio_list, 0, 1, 1, 3)

        subs_label = QLabel("Subs:")
        subs_label.setFixedWidth(52)
        gl2.addWidget(subs_label, 1, 0, Qt.AlignmentFlag.AlignTop)
        self.subtitle_list = QListWidget()
        self.subtitle_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.subtitle_list.setToolTip(
            "Subtitle tracks: tick to include, or tick \"Burn\" to hardcode "
            "a text subtitle into the video")
        gl2.addWidget(self.subtitle_list, 1, 1, 1, 3)

        self.chk_normalize = QCheckBox("Normalize loudness (loudnorm)")
        self.chk_normalize.setToolTip(
            "Normalize loudness with a two-pass loudnorm filter")
        gl2.addWidget(self.chk_normalize, 2, 0, 1, 2)
        gl2.addWidget(QLabel("Gain:"), 2, 2)
        self.spin_gain = QSpinBox()
        self.spin_gain.setRange(-30, 30)
        self.spin_gain.setValue(0)
        self.spin_gain.setSuffix(" dB")
        self.spin_gain.setToolTip("Volume adjustment applied to encoded audio")
        gl2.addWidget(self.spin_gain, 2, 3)
        gl2.setColumnStretch(0, 0)
        gl2.setColumnStretch(1, 1)
        gl2.setColumnStretch(2, 0)
        gl2.setColumnStretch(3, 1)
        lay.addWidget(ag)
        return w

    def build_mux_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(6)
        info = QLabel(
            "Mux separate video, audio and subtitle files into one MKV. Set "
            "language, forced/default flag and delay (ms) per track. Streams "
            "are copied, not re-encoded.")
        info.setWordWrap(True)
        lay.addWidget(info)

        self.mux_video_list = QListWidget()
        self.mux_audio_list = QListWidget()
        self.mux_sub_list = QListWidget()
        self.mux_lists = {"video": self.mux_video_list,
                          "audio": self.mux_audio_list,
                          "subtitle": self.mux_sub_list}

        def make_group(title, kind, lst):
            g = QGroupBox(title)
            gl = QVBoxLayout(g)
            gl.setContentsMargins(6, 6, 6, 6)
            gl.setSpacing(4)
            h = QHBoxLayout()
            btn = QPushButton("Add " + kind)
            btn.setToolTip(f"Add a {kind} file as a track")
            h.addWidget(btn)
            h.addStretch(1)
            gl.addLayout(h)
            lst.setMinimumHeight(130)
            lst.setToolTip(f"Loaded {kind} tracks")
            gl.addWidget(lst)
            cols.addWidget(g, 1)
            return btn

        cols = QHBoxLayout()
        cols.setSpacing(8)
        self.btn_mux_video = make_group("Video", "video", self.mux_video_list)
        self.btn_mux_audio = make_group("Audio", "audio", self.mux_audio_list)
        self.btn_mux_sub = make_group("Subtitles", "subtitle",
                                      self.mux_sub_list)
        lay.addLayout(cols, 1)

        arow = QHBoxLayout()
        self.btn_mux_remove = QPushButton("Remove selected")
        self.btn_mux_remove.setToolTip("Remove the selected tracks")
        self.btn_mux_clear = QPushButton("Clear")
        self.btn_mux_clear.setToolTip("Remove all tracks")
        arow.addWidget(self.btn_mux_remove)
        arow.addWidget(self.btn_mux_clear)
        arow.addStretch(1)
        lay.addLayout(arow)

        outrow = QHBoxLayout()
        outrow.addWidget(QLabel("Output:"))
        self.inp_mux_output = QLineEdit()
        self.inp_mux_output.setToolTip("Output MKV file path")
        self.btn_mux_save = QPushButton("Browse...")
        self.btn_mux_save.setToolTip("Choose the output MKV file")
        outrow.addWidget(self.inp_mux_output, 1)
        outrow.addWidget(self.btn_mux_save)
        lay.addLayout(outrow)

        lay.addWidget(QLabel("Generated mux command:"))
        self.txt_mux_cmd = QPlainTextEdit()
        self.txt_mux_cmd.setReadOnly(True)
        self.txt_mux_cmd.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.txt_mux_cmd.setFont(QFont("monospace", 9))
        self.txt_mux_cmd.setToolTip(
            "The mkvmerge / ffmpeg command used to mux the selected tracks")
        self.txt_mux_cmd.textChanged.connect(
            lambda: self.fit_edit_to_content(self.txt_mux_cmd, 30, 100))
        lay.addWidget(self.txt_mux_cmd)

        muxrow = QHBoxLayout()
        self.btn_mux_mkvmerge = QPushButton("Mux with mkvmerge")
        self.btn_mux_mkvmerge.setObjectName("primary")
        self.btn_mux_mkvmerge.setToolTip(
            "Mux with mkvmerge (MKVToolNix), best delay support")
        self.btn_mux_ffmpeg = QPushButton("Mux with ffmpeg")
        self.btn_mux_ffmpeg.setToolTip("Mux with ffmpeg stream copy")
        self.lbl_mux_status = QLabel("")
        muxrow.addWidget(self.btn_mux_mkvmerge)
        muxrow.addWidget(self.btn_mux_ffmpeg)
        muxrow.addWidget(self.lbl_mux_status, 1)
        lay.addLayout(muxrow)

        self.btn_mux_video.clicked.connect(lambda: self.add_mux_file("video"))
        self.btn_mux_audio.clicked.connect(lambda: self.add_mux_file("audio"))
        self.btn_mux_sub.clicked.connect(lambda: self.add_mux_file("subtitle"))
        self.btn_mux_remove.clicked.connect(self.remove_mux_item)
        self.btn_mux_clear.clicked.connect(self.clear_mux)
        self.btn_mux_save.clicked.connect(self.choose_mux_output)
        self.btn_mux_mkvmerge.clicked.connect(lambda: self.do_mux("mkvmerge"))
        self.btn_mux_ffmpeg.clicked.connect(lambda: self.do_mux("ffmpeg"))
        self.inp_mux_output.textChanged.connect(
            lambda *_: self.update_mux_command())

        self.mkvmerge = shutil.which("mkvmerge")
        if not self.mkvmerge:
            self.btn_mux_mkvmerge.setEnabled(False)
            self.btn_mux_mkvmerge.setToolTip(
                "mkvmerge (MKVToolNix) not found in PATH")
        return w

    def build_queue_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.list_queue = QListWidget()
        lay.addWidget(self.list_queue, 1)
        row = QHBoxLayout()
        self.btn_remove_queue = QPushButton("Remove selected")
        self.btn_clear_queue = QPushButton("Clear")
        self.btn_queue_up = QPushButton("Move up")
        self.btn_queue_down = QPushButton("Move down")
        self.btn_queue_duplicate = QPushButton("Duplicate")
        self.btn_queue_inspect = QPushButton("Inspect command")
        self.btn_save_queue = QPushButton("Save queue")
        self.btn_load_queue = QPushButton("Load queue")
        row.addWidget(self.btn_remove_queue)
        row.addWidget(self.btn_clear_queue)
        row.addWidget(self.btn_queue_up)
        row.addWidget(self.btn_queue_down)
        row.addWidget(self.btn_queue_duplicate)
        row.addWidget(self.btn_queue_inspect)
        row.addWidget(self.btn_save_queue)
        row.addWidget(self.btn_load_queue)
        row.addStretch(1)
        lay.addLayout(row)
        self.btn_remove_queue.clicked.connect(self.remove_queue_item)
        self.btn_clear_queue.clicked.connect(self.list_queue.clear)
        self.btn_queue_up.clicked.connect(lambda: self.move_queue_item(-1))
        self.btn_queue_down.clicked.connect(lambda: self.move_queue_item(1))
        self.btn_queue_duplicate.clicked.connect(self.duplicate_queue_item)
        self.btn_queue_inspect.clicked.connect(self.inspect_queue_item)
        self.btn_save_queue.clicked.connect(self.save_queue)
        self.btn_load_queue.clicked.connect(self.load_queue)
        return w

    def build_info_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.txt_info = QPlainTextEdit()
        self.txt_info.setReadOnly(True)
        lay.addWidget(self.txt_info, 1)
        return w

    def build_manual_tab(self):
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setOpenLinks(True)
        readme = os.path.join(APP_DIR, "MANUAL.md")
        try:
            with open(readme, encoding="utf-8", errors="replace") as fh:
                browser.setMarkdown(fh.read())
        except OSError as exc:
            browser.setPlainText(f"Unable to load the manual:\n{exc}")
        return browser

    def build_log_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(3000)
        lay.addWidget(self.txt_log, 1)
        row = QHBoxLayout()
        btn = QPushButton("Clear log")
        btn.clicked.connect(self.txt_log.clear)
        row.addStretch(1)
        row.addWidget(btn)
        lay.addLayout(row)
        return w

    def build_ffmpeg_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)
        title = QLabel("Static binaries")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        lay.addWidget(title)
        info = QLabel(
            "Download the latest static FFmpeg build and the optional "
            "dovi_tool for Dolby Vision RPU processing. Binaries are stored "
            "in applications/ and take priority over the system installation.")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.ffmpeg_info = QTextBrowser()
        self.ffmpeg_info.setOpenExternalLinks(True)
        self.ffmpeg_info.setMinimumHeight(140)
        lay.addWidget(self.ffmpeg_info, 1)
        self.ffmpeg_progress = QProgressBar()
        self.ffmpeg_progress.setRange(0, 100)
        self.ffmpeg_progress.setValue(0)
        lay.addWidget(self.ffmpeg_progress)
        self.ffmpeg_status = QLabel("Ready")
        lay.addWidget(self.ffmpeg_status)
        row = QHBoxLayout()
        self.btn_download_ffmpeg = QPushButton("Download static FFmpeg")
        self.btn_download_ffmpeg.setObjectName("primary")
        self.btn_download_dovi = QPushButton("Download dovi_tool")
        self.btn_open_ffmpeg_dir = QPushButton("Open applications folder")
        row.addWidget(self.btn_download_ffmpeg)
        row.addWidget(self.btn_download_dovi)
        row.addWidget(self.btn_open_ffmpeg_dir)
        row.addStretch(1)
        lay.addLayout(row)

        self.btn_download_ffmpeg.clicked.connect(self.download_ffmpeg)
        self.btn_download_dovi.clicked.connect(self.download_dovi)
        self.btn_open_ffmpeg_dir.clicked.connect(self.open_ffmpeg_dir)
        self.update_ffmpeg_info()
        return w

    def update_ffmpeg_info(self):
        url, label = static_ffmpeg_source()
        dovi_url, dovi_label = static_dovi_source()
        lines = []
        lines.append("## Download sources")
        lines.append(f"- FFmpeg ({label}):\n  {url if url else 'not available'}")
        for source_url, source_label in static_ffplay_sources():
            lines.append(f"- ffplay fallback ({source_label}):\n  {source_url}")
        lines.append(f"- dovi_tool ({dovi_label}):\n  "
                     f"{dovi_url if dovi_url else 'not available'}")
        lines.append("")
        lines.append("## Detected binaries")
        for name in ("ffmpeg", "ffprobe", "ffplay", "dovi", "mkvmerge",
                     "lame", "faac", "oggenc"):
            path = getattr(self.binaries, name, None)
            ok = bool(path and os.path.exists(path))
            state = "OK" if ok else "missing"
            lines.append(f"- {name}: {state} ({path if ok else path or 'not found'})")
        if not self.binaries.has("dovi"):
            lines.append("\nDolby Vision needs `dovi_tool`: download it above "
                         "or put it in applications/.")
        lines.append("\nMKV muxing uses mkvmerge when available; otherwise FFmpeg "
                     "muxes with stream copy.")
        lines.append("External audio encoders are optional: LAME, FAAC and oggenc.")
        self.ffmpeg_info.setMarkdown("\n".join(lines))
        self.btn_download_ffmpeg.setEnabled(bool(url))
        self.btn_download_dovi.setEnabled(bool(dovi_url))

    def build_profiles_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.lbl_profile_summary = QLabel()
        self.lbl_profile_summary.setWordWrap(True)
        lay.addWidget(self.lbl_profile_summary)
        lay.addWidget(QLabel(
            "Edit profile.txt directly. One profile per line: "
            "Name;ffmpeg video arguments"))
        self.txt_profiles = QPlainTextEdit()
        lay.addWidget(self.txt_profiles, 1)
        row = QHBoxLayout()
        btn_save = QPushButton("Save & reload")
        btn_reload = QPushButton("Reload from disk")
        row.addWidget(btn_save)
        row.addWidget(btn_reload)
        row.addStretch(1)
        lay.addLayout(row)
        btn_save.clicked.connect(self.save_profiles)
        btn_reload.clicked.connect(self.reload_profiles)
        self.reload_profiles_text()
        self.update_profile_summary()
        return w

    def update_profile_summary(self):
        if not hasattr(self, "lbl_profile_summary"):
            return
        preset = self.current_preset()
        family = preset.get("family", "x264")
        encoder = preset.get("encoder") or CODECS.get(family, family)
        intent = {
            "x264": "compatibility and broad device support",
            "x265": "high quality and efficient HEVC compression",
            "x266": "next-generation VVC compression",
            "av1": "modern web and archival delivery",
            "ffv1": "lossless archival video",
            "prores": "editing mezzanine media",
        }.get(family, "general-purpose conversion")
        self.lbl_profile_summary.setText(
            f"Active profile: {self.get_text(self.cmb_preset)}\n"
            f"Encoder: {encoder}    Goal: {intent}\n"
            "Use Encoder options only when you need to override the profile.")

    # ------------------------------------------------------------------ #
    # Logging
    # ------------------------------------------------------------------ #
    def _rotate_log(self):
        try:
            if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 2_000_000:
                os.replace(LOG_FILE, LOG_FILE + ".old")
        except OSError:
            pass

    def _write_log(self, msg):
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as fh:
                fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
        except OSError:
            pass

    def log(self, msg):
        self._append_log_line(msg)
        self.statusBar().showMessage(msg)
        self._write_log(msg)

    def _append_log_line(self, text):
        """Append a log line without interrupting upward scrolling."""
        scrollbar = self.txt_log.verticalScrollBar()
        old_value = scrollbar.value()
        follow_tail = old_value >= scrollbar.maximum() - 2
        self.txt_log.appendPlainText(text)
        if follow_tail:
            scrollbar.setValue(scrollbar.maximum())
        else:
            scrollbar.setValue(old_value)

    # ------------------------------------------------------------------ #
    # Theme
    # ------------------------------------------------------------------ #
    def apply_theme(self, name):
        self.theme = name if name in THEMES else "dark"
        self.setStyleSheet(make_style(THEMES[self.theme]))
        p = THEMES[self.theme]
        if hasattr(self, "lbl_stats"):
            self.lbl_stats.setStyleSheet(
                f"color: {p['success']}; font-family: monospace;")
        if hasattr(self, "lbl_hdrinfo"):
            self.lbl_hdrinfo.setStyleSheet(f"color: {p['muted']};")
        if hasattr(self, "lbl_drop"):
            self.lbl_drop.setStyleSheet(f"color: {p['dim']};")
        if hasattr(self, "lbl_mode_warning"):
            self.lbl_mode_warning.setStyleSheet(f"color: {p['danger']};")
        self.update_theme_button()

    def toggle_theme(self):
        self.apply_theme("light" if self.theme == "dark" else "dark")
        app_settings().setValue("theme", self.theme)

    def update_theme_button(self):
        if not hasattr(self, "theme_btn"):
            return
        self.theme_btn.setText("Dark" if self.theme == "dark" else "Light")

    def show_initial_info(self):
        ok = True
        for name in ("ffmpeg", "ffprobe", "ffplay"):
            if not self.binaries.has(name):
                ok = False
                self.log(f"[warning] {name} not found. "
                         "Install it or put it in applications/.")
        if not self.binaries.has("dovi"):
            self.log("[info] dovi_tool not found (optional, for Dolby Vision)")
        first = "ffmpeg"
        if ok:
            try:
                p = subprocess.run([self.binaries.ffmpeg, "-version"],
                                   capture_output=True, text=True,
                                   errors="replace", timeout=10)
                first = p.stdout.splitlines()[0]
            except Exception:
                pass
        self.txt_info.setPlainText(
            f"AutoFFmpegGui v{APP_VERSION} (PyQt6)\n\n"
            "1. Open a file with Browse (or drag & drop)\n"
            "2. Choose a preset, HDR mode and settings\n"
            "3. Press Encode, or add the job to the queue\n\n"
            "Live progress, ETA and full ffmpeg output are shown.\n"
            "HDR: HDR10, HLG, HDR10+ (JSON), Dolby Vision (dovi_tool).\n\n"
            f"{EUPL_BANNER}\n\n"
            f"Using: {first}\n"
            f"ffmpeg  : {self.binaries.ffmpeg}\n"
            f"ffprobe : {self.binaries.ffprobe}\n"
            f"ffplay  : {self.binaries.ffplay}\n"
            f"dovi_tool: {self.binaries.dovi}\n")

    # ------------------------------------------------------------------ #
    # Hardware detection (async)
    # ------------------------------------------------------------------ #
    def start_hw_detection(self):
        self.hw_thread = HwDetectThread(self.binaries.ffmpeg, self)
        self.hw_thread.result.connect(self.on_hw_detected)
        self.hw_thread.start()

    def on_hw_detected(self, encoders):
        self.available_encoders = encoders or set()
        self.populate_hw()
        self.on_mode_changed()
        detected = [HW_ENCODERS[(f, k)] for (f, k) in HW_ENCODERS
                    if HW_ENCODERS[(f, k)] in self.available_encoders]
        if detected:
            self.log(f"[info] detected hardware encoders: {', '.join(sorted(detected))}")

    def populate_hw(self):
        self.cmb_hw.clear()
        self.cmb_hw.addItem("None")
        for label, key in HW_ACCELS.items():
            if not key:
                continue
            if any(HW_ENCODERS.get((f, key)) in self.available_encoders
                   for f in ("x264", "x265", "vp9", "av1")):
                self.cmb_hw.addItem(label)
        if len(self.cmb_hw) == 1:
            self.cmb_hw.setToolTip(
                "No hardware encoder detected in this ffmpeg build")

    # ------------------------------------------------------------------ #
    # Presets
    # ------------------------------------------------------------------ #
    def refresh_preset_filter(self, preferred=None):
        """Show only profiles compatible with the selected video encoder."""
        encoder = self.cmb_external_encoder.currentData() or ""
        preferred = preferred or self.get_text(self.cmb_preset)
        names = [name for name, source in self.preset_sources.items()
                 if not encoder or source.get("family") == encoder]
        self.cmb_preset.blockSignals(True)
        self.cmb_preset.clear()
        self.cmb_preset.addItems(names)
        if names:
            index = self.cmb_preset.findText(preferred)
            self.cmb_preset.setCurrentIndex(index if index >= 0 else 0)
        self.cmb_preset.blockSignals(False)
        self.on_preset_changed()

    def on_external_encoder_changed(self):
        if hasattr(self, "preset_sources"):
            self.refresh_preset_filter()
        self.schedule_command_refresh()

    def load_presets(self):
        self.preset_sources = {}
        self.cmb_preset.clear()
        for name, src in BUILTIN_PRESETS:
            self.preset_sources[name] = src

        profile_file = os.path.join(APP_DIR, "profile.txt")
        if os.path.exists(profile_file):
            with open(profile_file, encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
            added = 0
            for name, args in pb_profile_parse(lines):
                family = detect_family(args)
                src = {"family": family, "rawargs": args.split()}
                self.preset_sources["[custom] " + name] = src
                added += 1
            if added:
                self.log(f"[info] loaded {added} custom presets from profile.txt")
        self.refresh_preset_filter("H.264 - medium")
        self.on_mode_changed()
        self.on_hdr_changed()

    def current_preset(self):
        name = self.get_text(self.cmb_preset)
        return getattr(self, "preset_sources", {}).get(name, {"family": "x264"})

    def reload_profiles_text(self):
        profile_file = os.path.join(APP_DIR, "profile.txt")
        try:
            with open(profile_file, encoding="utf-8", errors="replace") as fh:
                self.txt_profiles.setPlainText(fh.read())
        except OSError:
            pass

    def save_profiles(self):
        profile_file = os.path.join(APP_DIR, "profile.txt")
        try:
            with open(profile_file, "w", encoding="utf-8") as fh:
                fh.write(self.txt_profiles.toPlainText())
            self.load_presets()
            self.log("[info] profile.txt saved and reloaded")
        except OSError as exc:
            QMessageBox.warning(self, "AutoFFmpegGui", f"Could not save: {exc}")

    def reload_profiles(self):
        self.reload_profiles_text()
        self.load_presets()
        self.log("[info] profile.txt reloaded")

    # ------------------------------------------------------------------ #
    # Widget helpers
    # ------------------------------------------------------------------ #
    def get_text(self, widget):
        if isinstance(widget, QComboBox):
            return widget.currentText()
        return widget.text()

    def set_text(self, widget, value):
        if isinstance(widget, QComboBox):
            if widget.isEditable():
                widget.setEditText(str(value))
            else:
                idx = widget.findText(str(value))
                if idx >= 0:
                    widget.setCurrentIndex(idx)
        else:
            widget.setText(str(value))

    def on_output_base_changed(self, value):
        self.auto_output = False
        self.output_base = value.strip()
        self.outputfile = (self.output_base + "." + self.container
                           if self.output_base else "")
        self.schedule_command_refresh()

    def on_container_changed(self):
        self.container = self.cmb_container.currentData() or "mp4"
        if self.output_base:
            self.outputfile = self.output_base + "." + self.container
        self.schedule_command_refresh()

    def set_output_base(self, path):
        """Set a base path, accepting a recognized extension for convenience."""
        path = str(path or "").strip()
        suffix = Path(path).suffix.lower().lstrip(".")
        if suffix in {"mp4", "mkv", "mov", "avi"}:
            idx = self.cmb_container.findData(suffix)
            if idx >= 0:
                self.cmb_container.setCurrentIndex(idx)
            path = str(Path(path).with_suffix(""))
        self.output_base = path
        self.outputfile = (path + "." + self.container if path else "")
        self.inp_output.setText(path)
        self.auto_output = False
        self.schedule_command_refresh()

    def get_int(self, widget, default=0):
        if isinstance(widget, QComboBox):
            try:
                return int(float(str(widget.currentText()).strip() or default))
            except ValueError:
                return default
        try:
            return int(float(str(widget.text()).strip() or default))
        except ValueError:
            return default

    def _update_audio_row_enabled(self, codec, bitrate, channels, sampling):
        c = codec.currentText()
        is_copy = c == "Copy"
        bitrate.setEnabled(not is_copy and c != "FLAC")
        channels.setEnabled(not is_copy)
        sampling.setEnabled(not is_copy)

    def add_audio_row(self, stream_index, label):
        item = QListWidgetItem(self.audio_list)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setSpacing(5)
        check = QCheckBox()
        check.setChecked(True)
        check.setToolTip("Include this audio track")
        text = QLabel(label)
        codec = QComboBox()
        codec.addItems(AUDIO_CODECS)
        codec.setToolTip("Encoding for this audio track")
        encoder = QComboBox()
        encoder.addItems(AUDIO_ENCODERS)
        encoder.setToolTip("FFmpeg or an external audio encoder")
        encoder.setFixedWidth(78)
        encoder_options = QLineEdit()
        encoder_options.setPlaceholderText("extra args")
        encoder_options.setToolTip(
            "Optional external encoder arguments, for example --quality 5")
        encoder_options.setFixedWidth(112)
        bitrate = QComboBox()
        bitrate.setEditable(True)
        bitrate.addItems(AUDIO_BITRATES)
        bitrate.setToolTip("Bitrate for this audio track in kbit/s")
        channels = QComboBox()
        for label_text, value in CHANNEL_CHOICES:
            channels.addItem(label_text, value)
        channels.setToolTip("Output channel count (original or downmix)")
        sampling = QComboBox()
        sampling.setEditable(True)
        sampling.addItems(["auto", "22050", "44100", "48000", "96000"])
        sampling.setToolTip("Output sampling rate in Hz")
        codec.setFixedWidth(105)
        bitrate.setFixedWidth(68)
        channels.setFixedWidth(96)
        sampling.setFixedWidth(78)
        layout.addWidget(check)
        layout.addWidget(text, 1)
        layout.addWidget(codec)
        layout.addWidget(encoder)
        layout.addWidget(encoder_options)
        layout.addWidget(bitrate)
        layout.addWidget(channels)
        layout.addWidget(sampling)
        item.setSizeHint(row.sizeHint())
        self.audio_list.setItemWidget(item, row)
        self.audio_rows.append({
            "input_index": stream_index,
            "check": check,
            "codec": codec,
            "encoder": encoder,
            "encoder_options": encoder_options,
            "bitrate": bitrate,
            "channels": channels,
            "sampling": sampling,
        })
        # Gray out bitrate/channels/sampling when the track is stream-copied.
        codec.currentIndexChanged.connect(
            lambda *_, b=bitrate, ch=channels, s=sampling:
            self._update_audio_row_enabled(codec, b, ch, s))
        for w in (codec, bitrate, channels, sampling):
            w.currentIndexChanged.connect(
                lambda *_: self.schedule_command_refresh())
        bitrate.currentTextChanged.connect(
            lambda *_: self.schedule_command_refresh())
        sampling.currentTextChanged.connect(
            lambda *_: self.schedule_command_refresh())
        encoder.currentIndexChanged.connect(
            lambda *_: self.on_audio_encoder_changed(
                codec, encoder, bitrate, channels, sampling))
        encoder_options.textChanged.connect(
            lambda *_: self.schedule_command_refresh())
        check.toggled.connect(lambda *_: self.schedule_command_refresh())
        self._update_audio_row_enabled(codec, bitrate, channels, sampling)

    def on_audio_encoder_changed(self, codec, encoder, bitrate, channels,
                                 sampling):
        forced = {"LAME": "MP3", "FAAC": "AAC",
                  "oggenc": "OGG (Vorbis)"}.get(encoder.currentText())
        if forced:
            idx = codec.findText(forced)
            if idx >= 0:
                codec.setCurrentIndex(idx)
        self._update_audio_row_enabled(codec, bitrate, channels, sampling)
        self.schedule_command_refresh()

    def add_subtitle_row(self, stream_index, label):
        item = QListWidgetItem(self.subtitle_list)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(2, 0, 2, 0)
        check = QCheckBox()
        check.setChecked(True)
        check.setToolTip("Include this subtitle track")
        burn = QCheckBox("Burn")
        burn.setToolTip("Burn this subtitle into the video (text subs only)")
        layout.addWidget(check)
        layout.addWidget(QLabel(label), 1)
        layout.addWidget(burn)
        item.setSizeHint(row.sizeHint())
        self.subtitle_list.setItemWidget(item, row)
        self.subtitle_rows.append({"input_index": stream_index, "check": check,
                                   "burn": burn})
        check.toggled.connect(lambda *_: self.schedule_command_refresh())
        burn.toggled.connect(lambda *_: self.schedule_command_refresh())

    def update_track_heights(self):
        """Size the audio/subtitle lists to fit their track count.

        Fewer tracks free vertical space for the resize/crop and HDR panels,
        which keeps those panels from being compressed on smaller windows.
        """
        audio_n = len(self.audio_rows)
        sub_n = len(self.subtitle_rows)
        self.audio_list.setFixedHeight(min(max(audio_n, 1), 8) * 34 + 8)
        self.subtitle_list.setFixedHeight(min(max(sub_n, 1), 7) * 26 + 6)

    def fit_edit_to_content(self, edit, min_h=34, max_h=200):
        """Resize a QPlainTextEdit to fit the lines it currently contains."""
        text = edit.toPlainText()
        n_lines = text.count("\n") + 1 if text.strip() else 1
        line_h = edit.fontMetrics().lineSpacing()
        doc = edit.document()
        extra = 2 * int(doc.documentMargin()) + 2 * edit.frameWidth() + 4
        h = n_lines * line_h + extra
        edit.setFixedHeight(max(min_h, min(max_h, int(h))))

    # ------------------------------------------------------------------ #
    # Analysis
    # ------------------------------------------------------------------ #
    def analyze(self):
        self.audio_tracks = []
        self.subtitle_tracks = []
        self.probe = ProbeInfo()
        if not os.path.exists(self.inputfile):
            if not self.bluray_enabled or not os.path.exists(
                    self.get_text(self.inp_bluray_path)):
                return False
        probe_input = [self.inputfile]
        if self.bluray_enabled:
            av = BlurayOptions(
                enabled=True,
                path=self.get_text(self.inp_bluray_path),
                playlist=self.spin_bluray_playlist.value(),
                angle=self.spin_bluray_angle.value(),
                chapter=self.spin_bluray_chapter.value())
            probe_input = bluray_input_options(av) + [bluray_url(av)]
        try:
            p = subprocess.run(
                [self.binaries.ffprobe, "-v", "quiet", "-print_format", "json",
                 "-show_format", "-show_streams"] + probe_input,
                capture_output=True, text=True, errors="replace", timeout=60)
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            self.log(f"[error] ffprobe failed: {e}")
            return False
        if p.returncode != 0 or not p.stdout.strip():
            self.log(f"[error] ffprobe returned {p.returncode}: "
                     f"{(p.stderr or '').strip()[:300]}")
            return False
        try:
            data = json.loads(p.stdout)
        except json.JSONDecodeError:
            self.log("[error] could not parse ffprobe output")
            return False

        self.probe.duration = probe_duration(data)

        self.audio_list.clear()
        self.subtitle_list.clear()
        self.audio_tracks = self.probe.audio_tracks
        self.audio_rows = []
        self.subtitle_tracks = self.probe.subtitle_tracks
        self.subtitle_rows = []
        aidx = 0
        sidx = 0
        for s in data.get("streams", []):
            if s.get("codec_type") == "video":
                self.probe.has_video = True
                self.probe.vwidth = int(s.get("width", 0) or 0)
                self.probe.vheight = int(s.get("height", 0) or 0)
                rfr = s.get("r_frame_rate") or s.get("avg_frame_rate") or ""
                try:
                    num, den = map(int, str(rfr).split("/"))
                    self.probe.framerate = num / den if den else 0.0
                except ValueError:
                    self.probe.framerate = 0.0
                trc = s.get("color_transfer")
                self.probe.dv_profile = None
                for sd in s.get("side_data_list", []):
                    if sd.get("side_data_type") == "DOVI configuration record":
                        self.probe.source_dv = True
                        try:
                            self.probe.dv_profile = int(sd.get("dv_profile", 0))
                        except (TypeError, ValueError):
                            self.probe.dv_profile = None
                        break
                if not self.probe.source_dv:
                    tags = s.get("tags", {}) or {}
                    tagstr = str(s.get("codec_tag_string", ""))
                    if ("dovi" in tagstr.lower() or "dvhe" in tagstr.lower()
                            or any(k.lower().startswith("dv_") for k in tags)
                            or "dolby" in str(tags).lower()):
                        self.probe.source_dv = True
                        try:
                            self.probe.dv_profile = int(tags.get("dv_profile", 0))
                        except (TypeError, ValueError):
                            self.probe.dv_profile = None
                if trc in ("smpte2084", "arib-std-b67"):
                    self.probe.source_hdr_info = (
                        s.get("color_primaries") or "bt2020",
                        trc,
                        s.get("color_space") or "bt2020nc")
                elif self.probe.source_dv and self.probe.dv_profile == 5:
                    self.probe.source_hdr_info = ("bt2020", "smpte2084",
                                                  "bt2020nc")
            elif s.get("codec_type") == "audio":
                tags = s.get("tags", {}) or {}
                lang = tags.get("language") or tags.get("LANGUAGE") or ""
                title = tags.get("title") or tags.get("Title") or ""
                label = (f"Track {aidx}: {s.get('codec_name', '?')} "
                         f"{s.get('channel_layout', '')} "
                         f"{s.get('sample_rate', '')} Hz")
                if lang:
                    label += f"  [{lang_name(lang)}]"
                if title:
                    label += f"  -  {title}"
                self.add_audio_row(aidx, label)
                self.audio_tracks.append(s)
                aidx += 1
            elif s.get("codec_type") == "subtitle":
                tags = s.get("tags", {}) or {}
                lang = tags.get("language") or tags.get("LANGUAGE") or ""
                title = tags.get("title") or tags.get("Title") or ""
                label = f"Track {sidx}: {s.get('codec_name', '?')}"
                if lang:
                    label += f"  [{lang_name(lang)}]"
                if title:
                    label += f"  -  {title}"
                self.add_subtitle_row(sidx, label)
                self.subtitle_tracks.append(s)
                sidx += 1
        self.update_track_heights()
        self.update_size_from_source()
        self.update_info()
        self.update_source_summary()
        self.log(f"[info] analyzed {Path(self.inputfile).name}: "
                 f"{self.probe.vwidth}x{self.probe.vheight} @ "
                 f"{self.probe.framerate:.2f} fps, {self.probe.duration:.1f}s, "
                 f"{len(self.audio_tracks)} audio, {len(self.subtitle_tracks)} subs")
        return True

    def update_info(self):
        if not self.probe.has_video and not self.audio_tracks:
            self.txt_info.setPlainText(
                f"File      : {self.inputfile}\n"
                f"Duration  : {self.probe.duration:.2f} s\n")
        else:
            lines = [f"File      : {self.inputfile}",
                     f"Duration  : {self.probe.duration:.2f} s"]
            for s in (self.probe.audio_tracks or []):
                tags = s.get("tags", {}) or {}
                lang = tags.get("language") or tags.get("LANGUAGE") or ""
                lines.append(
                    f"Audio     : {s.get('codec_name')} "
                    f"{s.get('channel_layout', '')} "
                    f"{s.get('sample_rate', '')} Hz"
                    + (f"  [{lang_name(lang)}]" if lang else ""))
            self.txt_info.setPlainText("\n".join(lines))
        if self.probe.has_video:
            if self.probe.source_dv:
                prof = (f" profile {self.probe.dv_profile}"
                        if self.probe.dv_profile else "")
                label = (f"Source: Dolby Vision{prof} detected. "
                         f"Select \"Dolby Vision\" to re-encode with RPU.")
            elif self.probe.source_hdr_info:
                trc = self.probe.source_hdr_info[1]
                label = (f"Source: HDR detected ({trc}). "
                         f"\"Auto\" will preserve HDR.")
            else:
                label = "Source: SDR (no HDR metadata)."
        else:
            label = "No video stream."
        self.lbl_hdrinfo.setText(label)

    def update_source_summary(self):
        if not self.probe.has_video:
            self.lbl_source_summary.setText(
                self.inputfile or "No file loaded")
            self._fit_source_box(1)
            return
        if self.probe.duration >= 3600:
            duration = f"{self.probe.duration / 3600:.1f} h"
        elif self.probe.duration >= 60:
            duration = f"{self.probe.duration / 60:.1f} min"
        else:
            duration = f"{self.probe.duration:.1f} s"
        video = (f"{self.probe.vwidth}x{self.probe.vheight} @ "
                 f"{self.probe.framerate:.2f} fps")
        if self.probe.source_dv:
            color = "Dolby Vision" + (
                f" profile {self.probe.dv_profile}" if self.probe.dv_profile else "")
        elif self.probe.source_hdr_info:
            color = f"HDR ({self.probe.source_hdr_info[1]})"
        else:
            color = "SDR"
        self.lbl_source_summary.setText(
            f"{Path(self.inputfile).name}\n"
            f"Video: {video}    Duration: {duration}\n"
            f"Audio: {len(self.audio_tracks)}    Subtitles: "
            f"{len(self.subtitle_tracks)}    Color: {color}")
        self._fit_source_box(3)

    def _fit_source_box(self, n_lines):
        line_h = self.lbl_source_summary.fontMetrics().lineSpacing()
        h = n_lines * line_h + 24  # group title + margins
        self.source_box.setMaximumHeight(max(40, min(120, h)))

    def update_size_from_source(self):
        if self.probe.vwidth and self.probe.vheight:
            self.inp_width.setText(str(self.probe.vwidth))
            self.inp_height.setText(str(self.probe.vheight))
            self.silentscale()

    # ------------------------------------------------------------------ #
    # HDR / hardware helpers
    # ------------------------------------------------------------------ #
    def on_hdr_changed(self):
        m = self.get_text(self.cmb_hdr)
        enable_meta = (m == "HDR10+ (dynamic metadata)")
        self.inp_hdr_meta.setEnabled(enable_meta)
        self.btn_hdr_meta.setEnabled(enable_meta)
        hard_hdr = m in ("HDR10 (BT.2020 / PQ)", "HLG (BT.2020 / HLG)",
                         "HDR10+ (dynamic metadata)",
                         "Dolby Vision (source RPU)")
        if hard_hdr and self.get_text(self.cmb_hw) != "None":
            self.set_text(self.cmb_hw, "None")
        self.cmb_hw.setEnabled(not hard_hdr)

    def choose_hdr_meta(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "HDR10+ JSON metadata", self.lastdir,
            "JSON (*.json);;All files (*.*)")
        if f:
            self.inp_hdr_meta.setText(f)

    # ------------------------------------------------------------------ #
    # Resize / crop
    # ------------------------------------------------------------------ #
    def silentscale(self):
        if not self.probe.vwidth or not self.probe.vheight:
            return
        width = self.get_int(self.inp_width)
        height = self.get_int(self.inp_height)
        if not width or not height:
            return
        if width != self.probe.vwidth or height != self.probe.vheight:
            mod = max(2, self.get_int(self.cmb_mod, 16))
            height = round_by(width / (self.probe.vwidth / self.probe.vheight),
                              mod)
            if height <= 0:
                height = mod
            self.inp_height.setText(str(height))
        if height > 0 and width > 0:
            self.inp_dar.setText(f"{width / height:.4f}")

    def on_size_pct(self):
        if not self.probe.vwidth:
            return
        pct = self.sld_trackwidth.value()
        width = round_by(self.probe.vwidth * pct / 100, 2)
        self.inp_width.setText(str(width))
        self.silentscale()

    def on_resize_toggled(self, enabled):
        for wd in (self.inp_width, self.inp_height, self.cmb_mod,
                   self.sld_trackwidth, self.inp_leftcrop, self.inp_rightcrop,
                   self.inp_topcrop, self.inp_bottomcrop):
            wd.setEnabled(enabled)

    def on_preset_changed(self):
        if hasattr(self, "tbl_encoder_options") and self._encoder_profile_name:
            self.encoder_profile_overrides[self._encoder_profile_name] = \
                self.encoder_options_from_table()
        family = self.current_preset().get("family", "x264")
        if family in ("x264", "x265", "x266"):
            lo, hi, label = 0, 51, "Quality:"
            tooltip = "CRF quality; lower values mean higher quality"
        elif family in ("vp9", "av1"):
            lo, hi, label = 0, 63, "Quality:"
            tooltip = "CRF quality; lower values mean higher quality"
        else:
            lo, hi, label = 2, 31, "Quality:"
            tooltip = "Qscale quality; lower values mean higher quality"
        self.sld_quality.setRange(lo, hi)
        self.spin_quality.setRange(lo, hi)
        self.lbl_quality.setText(label)
        self.lbl_quality.setToolTip(tooltip)
        if family == "copy":
            self.cmb_mode.setCurrentIndex(
                self.cmb_mode.findText("Copy video"))
        if hasattr(self, "cmb_encoder_family") and \
                family in ("x264", "x265", "x266", "av1"):
            self._encoder_profile_name = self.get_text(self.cmb_preset)
            self.cmb_encoder_family.setCurrentText(family)
            self.load_encoder_catalog()
        self.update_profile_summary()

    def on_quality_changed(self):
        self.spin_quality.setValue(self.sld_quality.value())

    def on_mode_changed(self):
        mode = self.get_text(self.cmb_mode)
        hw = HW_ACCELS.get(self.get_text(self.cmb_hw))
        is_copy = mode in ("Copy video", "Remux (copy all)", "Audio only")
        is_reencode = mode in ("Quality (CRF)", "1-pass bitrate",
                               "2-pass bitrate")
        hw_mode = bool(hw) and not is_copy
        self.cmb_preset.setEnabled(not is_copy)
        self.sld_quality.setEnabled(not is_copy)
        self.spin_quality.setEnabled(not is_copy)
        self.lbl_quality.setEnabled(not is_copy)
        self.inp_bitrate.setEnabled("bitrate" in mode)
        self.cmb_hw.setEnabled(not is_copy)
        # "No mux" only makes sense when re-encoding; disable it for the
        # copy/remux/audio-only modes.
        if not is_reencode and self.chk_nomux.isChecked():
            self.chk_nomux.setChecked(False)
        self.chk_nomux.setEnabled(is_reencode)
        self.update_mode_warning()

    def update_mode_warning(self):
        mode = self.get_text(self.cmb_mode)
        hw = self.get_text(self.cmb_hw)
        if mode == "2-pass bitrate" and hw != "None":
            self.lbl_mode_warning.setText(
                "Hardware encoders do not support 2-pass: a single pass "
                "will be used.")
        else:
            self.lbl_mode_warning.setText("")

    def on_nomux_toggled(self, enabled):
        # In no-mux mode there is no single output path, and chapter/metadata
        # flags are left to the user's muxing step.
        self.chk_chapters.setEnabled(not enabled)
        self.chk_metadata.setEnabled(not enabled)
        self.inp_output.setEnabled(not enabled)
        self.btn_save.setEnabled(not enabled)
        if enabled:
            self.inp_output.setText("")
            self.output_base = ""
            self.outputfile = ""
            self.inp_output.setPlaceholderText(
                "One file per stream is written next to the input")
            self.lbl_status.setText(
                "No mux: video/audio/subs written as separate files")
        else:
            self.inp_output.setPlaceholderText("")

    # ------------------------------------------------------------------ #
    # Encode options
    # ------------------------------------------------------------------ #
    def collect_options(self):
        o = EncodeOptions()
        o.inputfile = self.inputfile
        o.outputfile = self.outputfile
        o.output_base = self.output_base or self.get_text(self.inp_output).strip()
        o.container = self.container
        o.preset = self.current_preset()
        o.mode = self.get_text(self.cmb_mode)
        o.external_video_encoder = self.cmb_external_encoder.currentData() or ""
        if o.external_video_encoder:
            name = o.external_video_encoder + (".exe" if os.name == "nt" else "")
            o.external_video_binary = shutil.which(o.external_video_encoder) or \
                os.path.join(BINARY_DIR, name)
        o.hw = HW_ACCELS.get(self.get_text(self.cmb_hw))
        o.quality = self.sld_quality.value()
        o.bitrate = self.get_int(self.inp_bitrate, 2000)
        o.hdr_mode = self.get_text(self.cmb_hdr)
        o.masterdisplay = self.get_text(self.inp_masterdisplay)
        o.maxcll = self.get_text(self.inp_maxcll)
        o.hdr_meta = self.get_text(self.inp_hdr_meta)
        o.resize = self.chk_resize.isChecked()
        o.width = self.get_int(self.inp_width)
        o.height = self.get_int(self.inp_height)
        o.mod = self.get_int(self.cmb_mod, 16)
        o.crop_l = self.get_int(self.inp_leftcrop)
        o.crop_r = self.get_int(self.inp_rightcrop)
        o.crop_t = self.get_int(self.inp_topcrop)
        o.crop_b = self.get_int(self.inp_bottomcrop)
        o.deinterlace = self.chk_deinterlace.isChecked()
        o.framerate = self.get_text(self.cmb_framerate)
        o.vframes = self.get_text(self.inp_vframes)
        o.normalize = self.chk_normalize.isChecked()
        o.gain = self.spin_gain.value()
        o.audio = [
            AudioSelection(
                input_index=r["input_index"],
                enabled=r["check"].isChecked(),
                codec=r["codec"].currentText(),
                bitrate=self.get_int(r["bitrate"], 128),
                channels=r["channels"].currentData() or "original",
                sampling=r["sampling"].currentText(),
                encoder=r["encoder"].currentText().lower(),
                encoder_options={"__raw__": r["encoder_options"].text()}
                if r["encoder_options"].text().strip() else {})
            for r in self.audio_rows]
        o.subs = [
            SubtitleSelection(
                input_index=r["input_index"],
                enabled=r["check"].isChecked(),
                burn=r["burn"].isChecked())
            for r in self.subtitle_rows]
        o.trim_start = self.get_text(self.inp_trim_start)
        o.trim_end = self.get_text(self.inp_trim_end)
        o.keep_chapters = self.chk_chapters.isChecked()
        o.keep_metadata = self.chk_metadata.isChecked()
        o.keep_generated_files = self.chk_keep_generated.isChecked()
        o.nomux = self.chk_nomux.isChecked()
        o.available_encoders = self.available_encoders
        o.dovi_tool = self.binaries.dovi
        o.encoder_options = self.encoder_options_from_table()
        o.avisynth = AvisynthOptions(
            enabled=self.chk_avisynth.isChecked(),
            script_path=self.get_text(self.inp_avs_path).strip(),
            script_text=self.txt_avs.toPlainText(),
            source_filter=self.get_text(self.cmb_avs_source),
            plugin_paths=[p.strip() for p in
                          self.get_text(self.inp_avs_plugins).split(";")
                          if p.strip()],
            filter_mode=self.cmb_avs_filter_mode.currentData() or "script")
        o.audio_tools = {
            "lame": self.binaries.lame,
            "faac": self.binaries.faac,
            "oggenc": self.binaries.oggenc,
        }
        o.bluray = BlurayOptions(
            enabled=self.bluray_enabled,
            path=self.get_text(self.inp_bluray_path).strip(),
            playlist=self.spin_bluray_playlist.value(),
            angle=self.spin_bluray_angle.value(),
            chapter=self.spin_bluray_chapter.value())
        return o

    def prepare_jobs(self, log=None, silent=False):
        options = self.collect_options()
        had_output = bool(options.output_base or options.outputfile)
        normalize_output(options, self.probe)
        dovi_supported = None
        if (options.hdr_mode == "Dolby Vision (source RPU)" and
                self.probe.source_dv and self.binaries.has("dovi")):
            dovi_supported = dovi_x265_supported(self.binaries.ffmpeg)
            if not dovi_supported:
                self.log("[error] selected FFmpeg/libx265 cannot inject "
                         "Dolby Vision RPU")
        issues = preflight(options, self.probe, self.available_encoders,
                           dovi_supported)
        errors = [issue for issue in issues if issue.severity == "error"]
        for issue in issues:
            prefix = issue.severity.upper()
            (log or self.log)(f"[preflight:{prefix}] {issue.message}"
                              + (f" Fix: {issue.fix}" if issue.fix else ""))
        if errors:
            if not silent:
                details = []
                for issue in errors:
                    text = issue.message
                    if issue.fix:
                        text += f"\nFix: {issue.fix}"
                    details.append(text)
                QMessageBox.warning(
                    self, "Preflight failed",
                    "\n\n".join(details))
            return options, []
        jobs = build_jobs(options, self.probe, self.binaries,
                          self.available_encoders, log or self.log)
        if not had_output and options.outputfile:
            self.set_output_base(options.outputfile)
        return options, jobs

    # ------------------------------------------------------------------ #
    # Encoding / queue
    # ------------------------------------------------------------------ #
    def preview_command(self, jobs=None, silent=False):
        if jobs is None:
            _, jobs = self.prepare_jobs(
                log=(lambda m: None) if silent else None, silent=silent)
        if not jobs:
            self.txt_cmd.setPlainText("")
            self.lbl_cmd_info.setText("")
            return
        lines = []
        for job in jobs:
            if job.pipeline:
                lines.append("\n  | ".join(" ".join(part)
                                              for part in job.pipeline))
            else:
                lines.append(" ".join(job.cmd))
        self.txt_cmd.setPlainText("\n".join(lines))
        self.lbl_cmd_info.setText(
            f"{len(jobs)} command(s)" if len(jobs) > 1 else "")

    def run_jobs(self, jobs):
        if not jobs:
            QMessageBox.warning(self, "AutoFFmpegGui",
                                "Open a valid input file first.")
            return
        if self.thread and self.thread.isRunning():
            return
        for j in jobs:
            if j.pipeline:
                self.log("[pipeline] " + " | ".join(" ".join(part)
                                                      for part in j.pipeline))
            else:
                self.log("[cmd] " + " ".join(j.cmd))
        self.thread = EncodeThread(jobs, self)
        self.thread.log_line.connect(self.append_log)
        self.thread.progress.connect(self.on_progress)
        self.thread.stats.connect(self.lbl_stats.setText)
        self.thread.job_started.connect(self.on_job_started)
        self.thread.job_done.connect(self.on_job_done)
        self.thread.all_done.connect(self.on_all_done)
        self._had_failure = False
        self.btn_encode.setEnabled(False)
        self.btn_addqueue.setEnabled(False)
        self.btn_startqueue.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress.setValue(0)
        self.lbl_stats.setText("")
        self.thread.start()

    def append_log(self, s):
        self._append_log_line(s)

    def do_encode(self):
        _, jobs = self.prepare_jobs()
        self.preview_command(jobs)
        self.run_jobs(jobs)

    def addtoqueue(self):
        _, jobs = self.prepare_jobs()
        if not jobs:
            QMessageBox.warning(self, "AutoFFmpegGui",
                                "Open a valid input file first.")
            return
        for j in jobs:
            self.list_queue.addItem(self.queue_item(j))
        self.log(f"[queue] added {len(jobs)} job(s)")

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Add folder to queue",
                                             self.lastdir)
        if not d:
            return
        files = [os.path.join(d, f) for f in sorted(os.listdir(d))
                 if Path(f).suffix.lower() in MEDIA_EXTENSIONS]
        if not files:
            QMessageBox.information(self, "AutoFFmpegGui",
                                    "No media files found in this folder.")
            return
        count = 0
        for f in files:
            options = self.collect_options()
            options.inputfile = f
            options.outputfile = ""
            options.batch = True
            options.nomux = False
            dur = quick_duration(self.binaries.ffprobe, f)
            jobs = build_jobs(options, ProbeInfo(duration=dur),
                              self.binaries, self.available_encoders, self.log)
            for j in jobs:
                self.list_queue.addItem(self.queue_item(j))
                count += 1
        self.log(f"[queue] added {count} job(s) from folder")

    def queue_item(self, job):
        item = QListWidgetItem(job.label)
        item.setData(Qt.ItemDataRole.UserRole, job_to_dict(job))
        return item

    def startqueue(self):
        jobs = []
        for i in range(self.list_queue.count()):
            data = self.list_queue.item(i).data(Qt.ItemDataRole.UserRole)
            if data:
                jobs.append(job_from_dict(data))
        if not jobs:
            QMessageBox.information(self, "AutoFFmpegGui", "Queue is empty.")
            return
        self.list_queue.clear()
        self.run_jobs(jobs)

    def remove_queue_item(self):
        for item in self.list_queue.selectedItems():
            self.list_queue.takeItem(self.list_queue.row(item))

    def move_queue_item(self, direction):
        row = self.list_queue.currentRow()
        target = row + direction
        if row < 0 or target < 0 or target >= self.list_queue.count():
            return
        item = self.list_queue.takeItem(row)
        self.list_queue.insertItem(target, item)
        self.list_queue.setCurrentRow(target)

    def duplicate_queue_item(self):
        item = self.list_queue.currentItem()
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            clone = self.queue_item(job_from_dict(data))
            self.list_queue.insertItem(self.list_queue.row(item) + 1, clone)
            self.list_queue.setCurrentItem(clone)

    def inspect_queue_item(self):
        item = self.list_queue.currentItem()
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        job = job_from_dict(data)
        if job.pipeline:
            text = "\n  | ".join(" ".join(part) for part in job.pipeline)
        else:
            text = " ".join(job.cmd)
        self.txt_cmd.setPlainText(text)

    def save_queue(self):
        jobs = []
        for i in range(self.list_queue.count()):
            data = self.list_queue.item(i).data(Qt.ItemDataRole.UserRole)
            if data:
                jobs.append(data)
        try:
            with open(QUEUE_FILE, "w", encoding="utf-8") as fh:
                json.dump(jobs, fh, indent=2)
            self.log(f"[queue] saved {len(jobs)} job(s)")
        except OSError as exc:
            QMessageBox.warning(self, "AutoFFmpegGui", f"Could not save: {exc}")

    def load_queue(self):
        if not os.path.exists(QUEUE_FILE):
            return
        try:
            with open(QUEUE_FILE, encoding="utf-8") as fh:
                jobs = json.load(fh)
            for data in jobs:
                self.list_queue.addItem(self.queue_item(job_from_dict(data)))
            self.log(f"[queue] loaded {len(jobs)} job(s)")
        except (OSError, ValueError, TypeError) as exc:
            self.log(f"[queue] could not load saved queue: {exc}")

    def cancel_encode(self):
        if self.thread:
            self.thread.cancel()
            self.log("[info] cancel requested...")

    def on_progress(self, pct, label):
        self.progress.setValue(pct)
        self.lbl_status.setText(f"{label} ... {pct}%")

    def on_job_started(self, idx, label):
        self.lbl_status.setText(f"[{idx + 1}] {label} ...")
        self.log(f"[job] {label}")

    def on_job_done(self, idx, code):
        self.log(f"[job] finished (exit code {code})")
        if code != 0:
            self._had_failure = True
            self.lbl_status.setText(f"Job {idx + 1} failed (exit {code})")

    def on_all_done(self):
        self.btn_encode.setEnabled(True)
        self.btn_addqueue.setEnabled(True)
        self.btn_startqueue.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.lbl_stats.setText("")
        if self.thread and self.thread._cancel:
            self.lbl_status.setText("Cancelled")
        elif self._had_failure:
            self.lbl_status.setText("Completed with errors")
        else:
            self.lbl_status.setText("Done")
            self.progress.setValue(100)
            self.run_post_action()
        self.thread = None

    def run_post_action(self):
        action = self.get_text(self.cmb_after)
        if action == "Notify when done":
            QMessageBox.information(self, "AutoFFmpegGui",
                                    "Encoding queue finished.")
        elif action == "Open output folder":
            d = os.path.dirname(self.outputfile) or self.lastdir
            QDesktopServices.openUrl(QUrl.fromLocalFile(d))
        elif action == "Shut down":
            try:
                if os.name == "nt":
                    subprocess.Popen(["shutdown", "/s", "/t", "60"])
                else:
                    subprocess.Popen(["shutdown", "-h", "+1"])
                self.log("[info] shutdown scheduled")
            except Exception as exc:
                self.log(f"[error] could not schedule shutdown: {exc}")

    def run_edited(self):
        text = self.txt_cmd.toPlainText().strip()
        if not text:
            return
        try:
            cmd = shlex.split(text, posix=os.name != "nt")
        except ValueError as exc:
            QMessageBox.warning(self, "AutoFFmpegGui",
                                f"Invalid command: {exc}")
            return
        job = EncodeJob("Custom command", cmd, self.probe.duration)
        self.run_jobs([job])

    # ------------------------------------------------------------------ #
    # Muxing
    # ------------------------------------------------------------------ #
    def add_mux_file(self, kind):
        filters = {
            "video": ("Video (*.mkv *.mp4 *.avi *.mov *.ts *.m2ts *.m4v "
                      "*.webm *.h264 *.hevc *.m2v *.vob *.ivf);;"
                      "All files (*.*)"),
            "audio": ("Audio (*.aac *.ac3 *.eac3 *.mp3 *.flac *.ogg *.opus "
                      "*.wav *.mka *.dts *.thd *.m4a);;All files (*.*)"),
            "subtitle": ("Subtitles (*.srt *.ass *.ssa *.vtt *.sup *.sub "
                         "*.idx);;All files (*.*)"),
        }[kind]
        f, _ = QFileDialog.getOpenFileName(self, f"Add {kind} track",
                                           self.lastdir, filters)
        if f:
            self.add_mux_row(f, kind)
            if not self.get_text(self.inp_mux_output).strip():
                self.inp_mux_output.setText(
                    os.path.join(os.path.dirname(f), "muxed.mkv"))

    def add_mux_row(self, path, kind):
        lst = self.mux_lists[kind]
        item = QListWidgetItem(lst)
        row = QWidget()
        outer = QVBoxLayout(row)
        outer.setContentsMargins(4, 3, 4, 3)
        outer.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(4)
        check = QCheckBox()
        check.setChecked(True)
        check.setToolTip("Include this track")
        name = QLabel(Path(path).name)
        name.setToolTip(path)
        top.addWidget(check)
        top.addWidget(name, 1)
        outer.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(3)
        lang = QComboBox()
        lang.setEditable(True)
        lang.addItems(["", "und", "ita", "eng", "fra", "deu", "spa", "por",
                       "jpn", "kor", "zho", "rus", "ara", "hin", "tur",
                       "pol", "nld", "swe", "dan", "fin", "ell", "heb",
                       "ces", "ron", "hun", "ukr", "bul", "hrv", "srp"])
        lang.setEditText(quick_track_language(self.binaries.ffprobe, path, kind))
        lang.setFixedWidth(66)
        lang.setToolTip("Track language (ISO 639-2 code, e.g. ita, eng)")
        forced = QCheckBox("forced")
        forced.setToolTip("Mark the track as forced")
        default = QCheckBox("default")
        default.setToolTip("Mark the track as the default track")
        delay = QSpinBox()
        delay.setRange(-3600000, 3600000)
        delay.setValue(0)
        delay.setSuffix(" ms")
        delay.setFixedWidth(96)
        delay.setToolTip("Track delay in milliseconds (positive = later)")
        bottom.addWidget(QLabel("lang"))
        bottom.addWidget(lang)
        bottom.addWidget(forced)
        bottom.addWidget(default)
        bottom.addWidget(delay)
        bottom.addStretch(1)
        outer.addLayout(bottom)

        item.setSizeHint(row.sizeHint())
        lst.setItemWidget(item, row)
        self.mux_rows.append({"path": path, "kind": kind, "list": lst,
                              "item": item, "check": check, "lang": lang,
                              "forced": forced, "default": default,
                              "delay": delay})
        check.toggled.connect(lambda *_: self.update_mux_command())
        lang.currentTextChanged.connect(lambda *_: self.update_mux_command())
        forced.toggled.connect(lambda *_: self.update_mux_command())
        default.toggled.connect(lambda *_: self.update_mux_command())
        delay.valueChanged.connect(lambda *_: self.update_mux_command())
        self.update_mux_command()

    def clear_mux(self):
        for lst in self.mux_lists.values():
            lst.clear()
        self.mux_rows.clear()
        self.update_mux_command()

    def remove_mux_item(self):
        for r in self.mux_rows[:]:
            if r["item"].isSelected():
                r["list"].takeItem(r["list"].row(r["item"]))
                self.mux_rows.remove(r)
        self.update_mux_command()

    def choose_mux_output(self):
        default = self.get_text(self.inp_mux_output) or os.path.join(
            self.lastdir or "", "muxed.mkv")
        f, _ = QFileDialog.getSaveFileName(self, "Save mux output", default,
                                           "MKV (*.mkv);;All files (*.*)")
        if f:
            self.inp_mux_output.setText(f)

    def collect_mux_tracks(self):
        order = {"video": 0, "audio": 1, "subtitle": 2}
        rows = sorted((r for r in self.mux_rows if r["check"].isChecked()),
                      key=lambda r: order.get(r["kind"], 9))
        return [{
            "path": r["path"],
            "kind": r["kind"],
            "language": r["lang"].currentText().strip() or None,
            "forced": r["forced"].isChecked(),
            "default": r["default"].isChecked(),
            "delay_ms": r["delay"].value(),
        } for r in rows]

    def update_mux_command(self):
        tracks = self.collect_mux_tracks()
        output = self.get_text(self.inp_mux_output).strip()
        if not tracks or not output:
            self.txt_mux_cmd.setPlainText("")
            return
        lines = []
        if self.mkvmerge:
            lines.append("mkvmerge: " +
                         " ".join(build_mkvmerge_command(tracks, output)))
        lines.append("ffmpeg: " +
                     " ".join(build_ffmpeg_mux_command(tracks, output)))
        self.txt_mux_cmd.setPlainText("\n".join(lines))

    def do_mux(self, engine):
        tracks = self.collect_mux_tracks()
        if not tracks:
            QMessageBox.information(self, "Muxing", "Add at least one file.")
            return
        output = self.get_text(self.inp_mux_output).strip()
        if not output:
            QMessageBox.information(self, "Muxing", "Choose an output file.")
            return
        if engine == "mkvmerge":
            cmd = build_mkvmerge_command(tracks, output)
        else:
            cmd = build_ffmpeg_mux_command(tracks, output)
        self.log("[mux] " + " ".join(cmd))
        job = EncodeJob(f"Mux -> {Path(output).name}", cmd, 0.0, is_video=False)
        self.mux_thread = EncodeThread([job], self)
        self.mux_thread.log_line.connect(self.append_log)
        self.mux_thread.job_done.connect(
            lambda i, c: self.log(f"[mux] finished (exit {c})"))
        self.mux_thread.all_done.connect(self.on_mux_done)
        self.btn_mux_mkvmerge.setEnabled(False)
        self.btn_mux_ffmpeg.setEnabled(False)
        self.lbl_mux_status.setText("Muxing...")
        self.mux_thread.start()

    def on_mux_done(self):
        self.btn_mux_mkvmerge.setEnabled(bool(self.mkvmerge))
        self.btn_mux_ffmpeg.setEnabled(True)
        self.lbl_mux_status.setText("Done")
        self.mux_thread = None

    # ------------------------------------------------------------------ #
    # Auto crop
    # ------------------------------------------------------------------ #
    def autocrop(self):
        if not self.inputfile or not os.path.exists(self.inputfile):
            QMessageBox.warning(self, "AutoFFmpegGui", "Open a file first.")
            return
        self.btn_autocrop.setEnabled(False)
        self.lbl_status.setText("Detecting crop ...")
        self.log("[crop] running cropdetect ...")
        cmd = cropdetect_command(self.binaries.ffmpeg, self.inputfile,
                                 self.probe.duration)
        worker = CropThread(cmd, self)
        worker.finished_ok.connect(self._autocrop_done)
        worker.start()
        self.crop_worker = worker

    def _autocrop_done(self, result):
        self.btn_autocrop.setEnabled(True)
        if not result:
            self.lbl_status.setText("cropdetect did not report a crop")
            self.log("[crop] cropdetect did not report a crop region")
            return
        w, h, x, y = result
        if w <= 0 or h <= 0:
            for e in (self.inp_leftcrop, self.inp_rightcrop,
                      self.inp_topcrop, self.inp_bottomcrop):
                e.setText("0")
            self.lbl_status.setText("No black borders found")
            return
        self.inp_leftcrop.setText(str(x))
        self.inp_topcrop.setText(str(y))
        self.inp_rightcrop.setText(str(max(0, self.probe.vwidth - x - w)))
        self.inp_bottomcrop.setText(str(max(0, self.probe.vheight - y - h)))
        self.lbl_status.setText(f"Crop: {w}x{h}+{x}+{y}")
        self.log(f"[crop] detected {w}x{h}+{x}+{y}")
        self.silentscale()

    # ------------------------------------------------------------------ #
    # Bitrate calculator
    # ------------------------------------------------------------------ #
    def effective_video_duration(self, options):
        duration = self.probe.duration
        if not (options.avisynth.enabled or
                Path(options.inputfile).suffix.lower() == ".avs"):
            return duration
        try:
            plan = build_input_plan(options, self.probe)
            script = plan.inputs[plan.video_index]
            if Path(script).suffix.lower() != ".avs":
                return duration
            measured = quick_duration(self.binaries.ffprobe, script)
            if measured > 0:
                return measured
        except (OSError, ValueError, IndexError):
            pass
        return duration

    def _load_packet_stats(self, ffprobe, selector, input_args, tracks):
        if not tracks:
            return
        cmd = [ffprobe, "-v", "error", "-select_streams", selector,
               "-show_entries", "packet=stream_index,size,duration_time",
               "-of", "json"] + input_args
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    errors="replace", timeout=120)
            data = json.loads(result.stdout) if result.returncode == 0 else {}
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return
        stats = {}
        for packet in data.get("packets", []):
            try:
                index = int(packet.get("stream_index"))
                size = float(packet.get("size") or 0)
                packet_duration = float(packet.get("duration_time") or 0)
            except (TypeError, ValueError):
                continue
            entry = stats.setdefault(index, {"size": 0.0, "duration": 0.0})
            entry["size"] += max(0.0, size)
            entry["duration"] += max(0.0, packet_duration)
        for stream in tracks:
            entry = stats.get(stream.get("index"))
            if entry:
                stream["_packet_size"] = entry["size"]
                stream["_packet_duration"] = entry["duration"]

    def calc_bitrate(self):
        if not self.probe.duration:
            QMessageBox.information(self, "AutoFFmpegGui",
                                    "Open a file first to analyze it.")
            return
        mb = self.get_int(self.inp_cds, 700)
        options = self.collect_options()
        duration = self.effective_video_duration(options)
        probe_input = [self.inputfile]
        if options.bluray.enabled:
            probe_input = (bluray_input_options(options.bluray) +
                           [bluray_url(options.bluray)])
        self._load_packet_stats(self.binaries.ffprobe, "a", probe_input,
                                self.probe.audio_tracks)
        self._load_packet_stats(self.binaries.ffprobe, "s", probe_input,
                                self.probe.subtitle_tracks)
        audio = estimate_audio_bitrate_kbps(options.audio,
                                            self.probe.audio_tracks, duration)
        subtitles = estimate_subtitle_bitrate_kbps(options.subs,
                                                   self.probe.subtitle_tracks,
                                                   duration)
        non_video = audio + subtitles
        video_kbps = calc_bitrate_mb(mb, duration, non_video)
        self.inp_bitrate.setText(str(video_kbps))
        target_kbps = mb * 8192 / duration if duration > 0 else 0
        if non_video >= target_kbps * 0.95:
            self.log("[warning] target size is too small for the selected "
                     f"audio/subtitles ({non_video:.0f} kbit/s)")
        self.log(f"[calc] target {mb} MB over {duration:.2f}s; "
                 f"audio {audio:.0f} + subtitles {subtitles:.0f} kbit/s "
                 f"-> video bitrate {video_kbps} kbit/s")

    # ------------------------------------------------------------------ #
    # Play / preview / screenshots
    # ------------------------------------------------------------------ #
    def run_ffplay(self, args):
        if not self.inputfile:
            return
        if not self.binaries.has("ffplay"):
            QMessageBox.warning(self, "AutoFFmpegGui", "ffplay not found.")
            return
        try:
            subprocess.Popen([self.binaries.ffplay] + args)
        except OSError as e:
            QMessageBox.warning(self, "AutoFFmpegGui", str(e))

    def play(self):
        self.run_ffplay(["-i", self.inputfile])

    def preview(self):
        o = self.collect_options()
        vf = build_filter_args(o, self.probe)
        args = []
        if vf:
            args += ["-vf", ",".join(vf)]
        if o.avisynth.enabled or Path(self.inputfile).suffix.lower() == ".avs":
            plan = build_input_plan(o, self.probe)
            source = plan.inputs[plan.video_index]
            if Path(source).suffix.lower() == ".avs":
                args += ["-f", "avisynth"]
            args += ["-autoexit", "-i", source]
        else:
            args += ["-autoexit", "-i", self.inputfile]
        self.run_ffplay(args)

    def screenshots(self):
        if not self.inputfile:
            QMessageBox.warning(self, "AutoFFmpegGui", "Open a file first.")
            return
        outdir = os.path.join(tempfile.gettempdir(), "autoffmpeg_thumbs")
        os.makedirs(outdir, exist_ok=True)
        cmd = extract_frames_command(self.binaries.ffmpeg, self.inputfile, outdir)
        self.log("[shots] extracting thumbnails...")

        class _Shots(QThread):
            done = pyqtSignal(str)

            def run(self):
                subprocess.run(self.cmd, capture_output=True, text=True,
                               errors="replace")
                self.done.emit(self.outdir)

        worker = _Shots(self)
        worker.cmd = cmd
        worker.outdir = outdir
        worker.done.connect(self._shots_done)
        worker.start()
        self.shots_worker = worker

    def _shots_done(self, outdir):
        self.log(f"[shots] thumbnails saved to {outdir}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(outdir))

    # ------------------------------------------------------------------ #
    # File dialogs + drag & drop
    # ------------------------------------------------------------------ #
    def openinputfile(self):
        filters = ("Media (*.mp4 *.mkv *.avi *.mov *.ts *.mts *.m2ts *.vob "
                   "*.mpg *.mpeg *.wmv *.flv *.webm *.ogm *.m2v *.m2t *.vro "
                   "*.d2v *.dga *.avs *.grf *.mka *.mp3 *.flac *.wav *.aac *.iso);;"
                   "All files (*.*)")
        f, _ = QFileDialog.getOpenFileName(self, "Open File to Encode",
                                           self.lastdir, filters)
        if f:
            self.load_file(f)

    def load_file(self, f):
        self.lastdir = os.path.dirname(f)
        self.inp_input.setText(f)
        self.inputfile = f
        self.bluray_enabled = False
        self.inp_bluray_path.clear()
        if Path(f).suffix.lower() == ".avs":
            self.chk_avisynth.setChecked(True)
            self.inp_avs_path.setText(f)
            self.load_avs_script()
        if self.auto_output:
            self.inp_output.setText("")
            self.output_base = ""
            self.outputfile = ""
        self.analyze()
        self.silentscale()

    def savefile(self):
        if self.inputfile:
            default = os.path.join(os.path.dirname(self.inputfile),
                                   Path(self.inputfile).stem + "_autoff")
        else:
            default = os.path.join(self.lastdir or "", "output")
        f, _ = QFileDialog.getSaveFileName(
            self, "Save output file", default,
            "Output base name (*);;All files (*.*)")
        if f:
            self.set_output_base(f)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        for url in urls:
            path = url.toLocalFile()
            if not path:
                continue
            if os.path.isdir(path):
                if is_bluray_path(path):
                    self.set_bluray_source(path)
                    self.analyze()
                else:
                    self.add_folder_from_path(path)
            elif os.path.isfile(path):
                self.load_file(path)
                break

    def add_folder_from_path(self, path):
        files = [os.path.join(path, f) for f in sorted(os.listdir(path))
                 if Path(f).suffix.lower() in MEDIA_EXTENSIONS]
        count = 0
        for f in files:
            options = self.collect_options()
            options.inputfile = f
            options.outputfile = ""
            options.batch = True
            options.nomux = False
            dur = quick_duration(self.binaries.ffprobe, f)
            jobs = build_jobs(options, ProbeInfo(duration=dur),
                              self.binaries, self.available_encoders, self.log)
            for j in jobs:
                self.list_queue.addItem(self.queue_item(j))
                count += 1
        if count:
            self.log(f"[queue] added {count} job(s) from dropped folder")

    # ------------------------------------------------------------------ #
    # FFmpeg / dovi_tool download
    # ------------------------------------------------------------------ #
    def open_ffmpeg_dir(self):
        os.makedirs(BINARY_DIR, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(BINARY_DIR))

    def download_ffmpeg(self):
        url, label = static_ffmpeg_source()
        if not url:
            return
        self._start_download(url, label, required=("ffmpeg", "ffprobe"),
                             optional=("ffplay",),
                             fallbacks=static_ffplay_sources(),
                             done_msg="FFmpeg installed")

    def download_dovi(self):
        url, label = static_dovi_source()
        if not url:
            return
        self._start_download(url, label, required=("dovi_tool",),
                             optional=(), fallbacks=(),
                             done_msg="dovi_tool installed")

    def _start_download(self, url, label, required, optional, fallbacks,
                        done_msg):
        if self.download_thread and self.download_thread.isRunning():
            return
        self.btn_download_ffmpeg.setEnabled(False)
        self.btn_download_dovi.setEnabled(False)
        self.ffmpeg_progress.setValue(0)
        self.ffmpeg_status.setText("Starting download...")
        self.log(f"[download] started: {url}")
        self.download_thread = DownloadThread(
            url, label, required, optional, fallbacks, self)
        self.download_thread.progress.connect(self.ffmpeg_download_progress)
        self.download_thread.status.connect(self.ffmpeg_download_status)
        self.download_thread.succeeded.connect(self.ffmpeg_download_done)
        self.download_thread.failed.connect(self.ffmpeg_download_failed)
        self.download_thread.start()

    def ffmpeg_download_progress(self, value):
        self.ffmpeg_progress.setValue(value)

    def ffmpeg_download_status(self, message):
        self.ffmpeg_status.setText(message)
        self.log(f"[download] {message}")

    def ffmpeg_download_done(self, directory):
        self.binaries.refresh()
        self.ffmpeg_status.setText(f"Installed in {directory}")
        self.update_ffmpeg_info()
        self.log(f"[download] installed in {directory}")
        self.log(f"[info] selected ffmpeg: {self.binaries.ffmpeg}")
        self.log(f"[info] selected ffprobe: {self.binaries.ffprobe}")
        self.log(f"[info] selected ffplay: {self.binaries.ffplay}")
        self.log(f"[info] selected dovi_tool: {self.binaries.dovi}")
        if not self.available_encoders:
            self.start_hw_detection()

    def ffmpeg_download_failed(self, message):
        self.ffmpeg_status.setText(f"Download failed: {message}")
        self.update_ffmpeg_info()
        self.log(f"[error] download failed: {message}")

    # ------------------------------------------------------------------ #
    # Settings persistence
    # ------------------------------------------------------------------ #
    def load_settings(self):
        s = app_settings()
        if s.contains("theme"):
            self.apply_theme(str(s.value("theme")))
        self.lastdir = s.value("lastdir", "")

        def restore_combo(cmb, key):
            if s.contains(key):
                v = s.value(key)
                if cmb.isEditable():
                    cmb.setEditText(v)
                else:
                    idx = cmb.findText(v)
                    if idx >= 0:
                        cmb.setCurrentIndex(idx)
        restore_combo(self.cmb_preset, "preset")
        restore_combo(self.cmb_mode, "mode")
        restore_combo(self.cmb_external_encoder, "external_encoder")
        restore_combo(self.cmb_hw, "hw")
        restore_combo(self.cmb_hdr, "hdr")
        restore_combo(self.cmb_framerate, "framerate")
        restore_combo(self.cmb_after, "after")
        restore_combo(self.cmb_container, "container")
        self.container = self.cmb_container.currentData() or "mp4"
        if s.contains("quality"):
            self.sld_quality.setValue(int(s.value("quality")))
        if s.contains("bitrate"):
            self.inp_bitrate.setText(str(s.value("bitrate")))
        if s.contains("cds"):
            self.inp_cds.setText(str(s.value("cds")))
        if s.contains("masterdisplay"):
            self.inp_masterdisplay.setText(str(s.value("masterdisplay")))
        if s.contains("maxcll"):
            self.inp_maxcll.setText(str(s.value("maxcll")))
        if s.contains("hdr_meta"):
            self.inp_hdr_meta.setText(str(s.value("hdr_meta")))
        if s.contains("vframes"):
            self.inp_vframes.setText(str(s.value("vframes")))
        if s.contains("trim_start"):
            self.inp_trim_start.setText(str(s.value("trim_start")))
        if s.contains("trim_end"):
            self.inp_trim_end.setText(str(s.value("trim_end")))
        if s.contains("resize"):
            self.chk_resize.setChecked(s.value("resize", True, type=bool))
        if s.contains("deinterlace"):
            self.chk_deinterlace.setChecked(
                s.value("deinterlace", False, type=bool))
        if s.contains("normalize"):
            self.chk_normalize.setChecked(
                s.value("normalize", False, type=bool))
        if s.contains("gain"):
            self.spin_gain.setValue(int(s.value("gain")))
        if s.contains("chapters"):
            self.chk_chapters.setChecked(s.value("chapters", False, type=bool))
        if s.contains("metadata"):
            self.chk_metadata.setChecked(
                s.value("metadata", False, type=bool))
        if s.contains("keep_generated"):
            self.chk_keep_generated.setChecked(
                s.value("keep_generated", False, type=bool))
        if s.contains("avisynth_enabled"):
            self.chk_avisynth.setChecked(
                s.value("avisynth_enabled", False, type=bool))
        if s.contains("avisynth_source"):
            self.set_text(self.cmb_avs_source, s.value("avisynth_source"))
        if s.contains("avisynth_filter_mode"):
            value = str(s.value("avisynth_filter_mode"))
            idx = self.cmb_avs_filter_mode.findData(value)
            if idx >= 0:
                self.cmb_avs_filter_mode.setCurrentIndex(idx)
        if s.contains("avisynth_path"):
            self.inp_avs_path.setText(str(s.value("avisynth_path")))
        if s.contains("avisynth_plugins"):
            self.inp_avs_plugins.setText(str(s.value("avisynth_plugins")))
        if s.contains("avisynth_script") and not self.inp_avs_path.text():
            self.txt_avs.setPlainText(str(s.value("avisynth_script")))
        if s.contains("encoder_profile_overrides"):
            try:
                data = json.loads(str(s.value("encoder_profile_overrides")))
                if isinstance(data, dict):
                    self.encoder_profile_overrides = {
                        str(name): {str(k): str(v) for k, v in values.items()}
                        for name, values in data.items()
                        if isinstance(values, dict)}
            except (TypeError, ValueError, json.JSONDecodeError):
                self.log("[warning] invalid saved encoder profile overrides")
        self.on_preset_changed()
        self.on_mode_changed()
        self.on_hdr_changed()

    def closeEvent(self, e):
        # Stop background threads before Qt tears down the widget tree.
        if self.thread and self.thread.isRunning():
            self.thread.cancel()
            self.thread.wait(5000)
        if self.crop_worker and self.crop_worker.isRunning():
            self.crop_worker.wait(3000)
        if self.hw_thread and self.hw_thread.isRunning():
            self.hw_thread.wait(3000)
        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.cancel()
            self.download_thread.wait(5000)
        if self.mux_thread and self.mux_thread.isRunning():
            self.mux_thread.wait(5000)

        s = app_settings()
        s.setValue("theme", self.theme)
        s.setValue("lastdir", self.lastdir)
        s.setValue("preset", self.get_text(self.cmb_preset))
        s.setValue("mode", self.get_text(self.cmb_mode))
        s.setValue("external_encoder", self.cmb_external_encoder.currentData() or "")
        s.setValue("hw", self.get_text(self.cmb_hw))
        s.setValue("hdr", self.get_text(self.cmb_hdr))
        s.setValue("after", self.get_text(self.cmb_after))
        s.setValue("container", self.get_text(self.cmb_container))
        s.setValue("quality", self.sld_quality.value())
        s.setValue("bitrate", self.get_text(self.inp_bitrate))
        s.setValue("cds", self.get_text(self.inp_cds))
        s.setValue("masterdisplay", self.get_text(self.inp_masterdisplay))
        s.setValue("maxcll", self.get_text(self.inp_maxcll))
        s.setValue("hdr_meta", self.get_text(self.inp_hdr_meta))
        s.setValue("framerate", self.get_text(self.cmb_framerate))
        s.setValue("normalize", self.chk_normalize.isChecked())
        s.setValue("gain", self.spin_gain.value())
        s.setValue("vframes", self.get_text(self.inp_vframes))
        s.setValue("trim_start", self.get_text(self.inp_trim_start))
        s.setValue("trim_end", self.get_text(self.inp_trim_end))
        s.setValue("resize", self.chk_resize.isChecked())
        s.setValue("deinterlace", self.chk_deinterlace.isChecked())
        s.setValue("chapters", self.chk_chapters.isChecked())
        s.setValue("metadata", self.chk_metadata.isChecked())
        s.setValue("keep_generated", self.chk_keep_generated.isChecked())
        s.setValue("avisynth_enabled", self.chk_avisynth.isChecked())
        s.setValue("avisynth_source", self.get_text(self.cmb_avs_source))
        s.setValue("avisynth_filter_mode",
                   self.cmb_avs_filter_mode.currentData() or "script")
        s.setValue("avisynth_path", self.get_text(self.inp_avs_path))
        s.setValue("avisynth_plugins", self.get_text(self.inp_avs_plugins))
        s.setValue("avisynth_script", self.txt_avs.toPlainText())
        if self._encoder_profile_name:
            self.encoder_profile_overrides[self._encoder_profile_name] = \
                self.encoder_options_from_table()
        s.setValue("encoder_profile_overrides",
                   json.dumps(self.encoder_profile_overrides, sort_keys=True))
        self.save_queue()
        super().closeEvent(e)
