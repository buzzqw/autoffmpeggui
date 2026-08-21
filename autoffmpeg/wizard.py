# -*- coding: utf-8 -*-
"""Guided job setup using the same controls as the main window."""

import os

from PyQt6.QtWidgets import (
    QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QVBoxLayout, QWizard, QWizardPage, QComboBox,
    QWidget,
)

from .config import AUDIO_BITRATES, AUDIO_CODECS, AUDIO_ENCODERS

CHANNEL_CHOICES = [
    ("original", "original"), ("mono (1)", "1"),
    ("stereo (2)", "2"), ("5.1 (6)", "6"), ("7.1 (8)", "8"),
]


class SourcePage(QWizardPage):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setTitle("Source")
        self.setSubTitle("Choose a media file or an AviSynth script.")
        layout = QFormLayout(self)
        row = QHBoxLayout()
        self.path = QLineEdit(window.inputfile)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self.choose)
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        layout.addRow("Input:", row)
        self.info = QLabel("The source will be analyzed before the next step.")
        self.info.setWordWrap(True)
        layout.addRow(self.info)

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose input", self.window.lastdir,
            "Media (*.mkv *.mp4 *.avi *.mov *.ts *.m2ts *.vob *.avs);;"
            "All files (*.*)")
        if path:
            self.path.setText(path)

    def validatePage(self):
        path = self.path.text().strip()
        if not path or not os.path.exists(path):
            self.info.setText("Choose an existing input file.")
            return False
        self.window.load_file(path)
        if not self.window.probe.has_video and not self.window.audio_tracks:
            self.info.setText("The source could not be analyzed.")
            return False
        self.info.setText(
            f"{self.window.probe.vwidth}x{self.window.probe.vheight}, "
            f"{len(self.window.audio_tracks)} audio, "
            f"{len(self.window.subtitle_tracks)} subtitles")
        return True


class VideoPage(QWizardPage):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setTitle("Video")
        self.setSubTitle("Select the profile and quality mode.")
        layout = QFormLayout(self)
        self.profile = QComboBox()
        self.profile.addItems([window.cmb_preset.itemText(i)
                               for i in range(window.cmb_preset.count())])
        self.mode = QComboBox()
        self.mode.addItems([window.cmb_mode.itemText(i)
                            for i in range(window.cmb_mode.count())])
        self.quality_label = QLabel("Quality:")
        self.quality = QSpinBox()
        self.quality.setRange(0, 63)
        self.quality.setValue(window.sld_quality.value())
        self.bitrate_label = QLabel("Video bitrate:")
        self.bitrate = QSpinBox()
        self.bitrate.setRange(0, 1000000)
        self.bitrate.setSuffix(" kbit/s")
        self.bitrate.setValue(window.get_int(window.inp_bitrate, 2000))
        self.target_label = QLabel("Target size:")
        self.target = QSpinBox()
        self.target.setRange(0, 1000000)
        self.target.setSuffix(" MB")
        self.target.setSpecialValueText("Not set")
        layout.addRow("Profile:", self.profile)
        layout.addRow("Mode:", self.mode)
        layout.addRow(self.quality_label, self.quality)
        layout.addRow(self.bitrate_label, self.bitrate)
        layout.addRow(self.target_label, self.target)
        self.mode.currentTextChanged.connect(self.update_mode_controls)
        self.update_mode_controls(self.mode.currentText())

    def initializePage(self):
        self.profile.setCurrentText(self.window.cmb_preset.currentText())
        self.mode.setCurrentText(self.window.cmb_mode.currentText())
        self.quality.setValue(self.window.sld_quality.value())
        self.bitrate.setValue(self.window.get_int(self.window.inp_bitrate, 2000))
        self.target.setValue(self.window.get_int(self.window.inp_cds, 0))
        self.update_mode_controls(self.mode.currentText())

    def update_mode_controls(self, mode):
        quality_mode = mode == "Quality (CRF)"
        bitrate_mode = "bitrate" in mode
        self.quality_label.setVisible(quality_mode)
        self.quality.setVisible(quality_mode)
        self.bitrate_label.setVisible(bitrate_mode)
        self.bitrate.setVisible(bitrate_mode)
        self.target_label.setVisible(bitrate_mode)
        self.target.setVisible(bitrate_mode)

    def validatePage(self):
        self.window.cmb_preset.setCurrentText(self.profile.currentText())
        self.window.cmb_mode.setCurrentText(self.mode.currentText())
        self.window.sld_quality.setValue(self.quality.value())
        self.window.inp_bitrate.setText(str(self.bitrate.value()))
        self.window.inp_cds.setText(str(self.target.value()))
        return True


class TracksPage(QWizardPage):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setTitle("Audio and subtitles")
        self.setSubTitle("Select the tracks to keep in the output.")
        self.layout = QVBoxLayout(self)
        self.rows = QVBoxLayout()
        self.layout.addLayout(self.rows)
        self.layout.addStretch(1)
        self.audio_checks = []
        self.audio_rows = []
        self.subtitle_checks = []

    def initializePage(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.audio_checks = []
        self.audio_rows = []
        self.subtitle_checks = []
        self.rows.addWidget(QLabel("Audio tracks"))
        for index, stream in enumerate(self.window.audio_tracks):
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 2, 0, 2)
            check = QCheckBox()
            check.setChecked(True)
            row.addWidget(check)
            row.addWidget(QLabel(
                f"{index}: {stream.get('codec_name', '?')} "
                f"{stream.get('channels', '')}ch"), 1)
            codec = QComboBox()
            codec.addItems(AUDIO_CODECS)
            codec.setCurrentText("AAC")
            encoder = QComboBox()
            encoder.addItems(AUDIO_ENCODERS)
            bitrate = QComboBox()
            bitrate.setEditable(True)
            bitrate.addItems(AUDIO_BITRATES)
            bitrate.setCurrentText("128")
            channels = QComboBox()
            for label, value in CHANNEL_CHOICES:
                channels.addItem(label, value)
            sampling = QComboBox()
            sampling.setEditable(True)
            sampling.addItems(["auto", "44100", "48000", "96000"])
            encoder.currentTextChanged.connect(
                lambda value, combo=codec: combo.setCurrentText({
                    "LAME": "MP3", "FAAC": "AAC",
                    "oggenc": "OGG (Vorbis)"}.get(value, combo.currentText())))
            row.addWidget(codec)
            row.addWidget(encoder)
            row.addWidget(bitrate)
            row.addWidget(channels)
            row.addWidget(sampling)
            self.audio_rows.append({
                "input_index": index, "check": check, "codec": codec,
                "encoder": encoder, "bitrate": bitrate,
                "channels": channels, "sampling": sampling,
            })
            self.rows.addWidget(row_widget)
        self.rows.addWidget(QLabel("Subtitle tracks"))
        for index, stream in enumerate(self.window.subtitle_tracks):
            check = QCheckBox(f"{index}: {stream.get('codec_name', '?')}")
            check.setChecked(False)
            self.subtitle_checks.append((index, check))
            self.rows.addWidget(check)

    def validatePage(self):
        selected_audio = {row["input_index"] for row in self.audio_rows
                          if row["check"].isChecked()}
        selected_subs = {index for index, check in self.subtitle_checks
                         if check.isChecked()}
        for row in self.window.audio_rows:
            index = row["input_index"]
            source = next((item for item in self.audio_rows
                           if item["input_index"] == index), None)
            row["check"].setChecked(index in selected_audio)
            if source:
                row["codec"].setCurrentText(source["codec"].currentText())
                row["encoder"].setCurrentText(source["encoder"].currentText())
                row["bitrate"].setCurrentText(source["bitrate"].currentText())
                row["sampling"].setCurrentText(source["sampling"].currentText())
                channel = source["channels"].currentData() or "original"
                channel_index = row["channels"].findData(channel)
                if channel_index >= 0:
                    row["channels"].setCurrentIndex(channel_index)
        for row in self.window.subtitle_rows:
            row["check"].setChecked(row["input_index"] in selected_subs)
        return True


class OutputPage(QWizardPage):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setTitle("Output and filters")
        self.setSubTitle("Choose the destination and optional AviSynth processing.")
        layout = QFormLayout(self)
        self.output = QLineEdit()
        layout.addRow("Output:", self.output)
        self.container = QComboBox()
        for label in ("MP4", "MKV", "MOV", "AVI"):
            self.container.addItem(label, label.lower())
        layout.addRow("Container:", self.container)
        self.avisynth = QCheckBox("Enable AviSynth+")
        self.avisynth.setChecked(window.chk_avisynth.isChecked())
        layout.addRow("Video filters:", self.avisynth)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addRow(self.summary)

    def initializePage(self):
        self.output.setText(self.window.output_base)
        if not self.output.text() and self.window.inputfile:
            self.output.setText(os.path.join(
                os.path.dirname(self.window.inputfile),
                "autoffmpeg_" + os.path.splitext(
                    os.path.basename(self.window.inputfile))[0]))
        index = self.container.findData(self.window.container)
        if index >= 0:
            self.container.setCurrentIndex(index)
        self.summary.setText(
            "Review the generated command after finishing. Preflight will stop "
            "unsupported codec/container combinations before encoding.")

    def validatePage(self):
        self.window.cmb_container.setCurrentIndex(
            self.window.cmb_container.findData(self.container.currentData()))
        self.window.set_output_base(self.output.text().strip())
        self.window.chk_avisynth.setChecked(self.avisynth.isChecked())
        if self.window.get_int(self.window.inp_cds, 0) > 0:
            self.window.calc_bitrate()
        self.window.preview_command(silent=True)
        return True


class QuickEncodeWizard(QWizard):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("AutoFFmpeg Quick Encode")
        self.setMinimumSize(640, 480)
        self.source_page = SourcePage(window)
        self.video_page = VideoPage(window)
        self.tracks_page = TracksPage(window)
        self.output_page = OutputPage(window)
        for page in (self.source_page, self.video_page, self.tracks_page,
                     self.output_page):
            self.addPage(page)
        self.finished.connect(lambda *_: window.schedule_command_refresh())
