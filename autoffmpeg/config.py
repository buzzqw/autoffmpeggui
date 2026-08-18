# -*- coding: utf-8 -*-
# AutoFFmpegGui v2 - PyQt6
# SPDX-License-Identifier: EUPL-1.2
# Licensed under the EUPL v1.2 (see LICENSE file in the project root).
"""Configuration, constants and binary discovery for AutoFFmpegGui."""

import os
import shutil
import stat
import subprocess
import platform

from PyQt6.QtCore import QSettings

APP_VERSION = "2.1.0"

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IS_WINDOWS = os.name == "nt"
CONFIG_FILE = os.path.join(APP_DIR, "config.ini")
BINARY_DIR = os.path.join(APP_DIR, "applications")
LOG_FILE = os.path.join(APP_DIR, "autoffmpeg.log")
PAYPAL_URL = ("https://www.paypal.com/cgi-bin/webscr"
              "?cmd=_s-xclick&hosted_button_id=4278562")

EUPL_BANNER = (
    "Licensed under the EUPL v1.2. See the LICENSE file in the project root "
    "for the full licence text."
)

# --------------------------------------------------------------------------- #
# Static binary download sources
# --------------------------------------------------------------------------- #


def static_ffmpeg_source():
    """Return (url, label) for the main static FFmpeg archive, or (None, reason)."""
    if IS_WINDOWS:
        return ("https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/"
                "ffmpeg-master-latest-win64-gpl.zip", "Windows 64-bit ZIP")
    if platform.system() == "Linux" and platform.machine().lower() in (
            "x86_64", "amd64"):
        return ("https://johnvansickle.com/ffmpeg/releases/"
                "ffmpeg-release-amd64-static.tar.xz", "Linux amd64 TAR.XZ")
    return None, "unsupported platform"


def static_ffplay_sources():
    """Return list of (url, label) fallback archives containing ffplay."""
    if IS_WINDOWS:
        return [
            ("https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
             "Windows stable essentials ZIP"),
        ]
    if platform.system() == "Linux" and platform.machine().lower() in (
            "x86_64", "amd64"):
        return [
            ("https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/"
             "ffmpeg-master-latest-linux64-gpl.tar.xz",
             "Linux amd64 GPL TAR.XZ fallback"),
        ]
    return []


def static_dovi_source():
    """Return (url, label) for the dovi_tool archive, or (None, reason)."""
    base = "https://github.com/quietvoid/dovi_tool/releases/latest/download/"
    if IS_WINDOWS:
        return (base + "dovi_tool-x86_64-pc-windows-msvc.zip",
                "dovi_tool Windows x64 ZIP")
    if platform.system() == "Darwin":
        return (base + "dovi_tool-universal-macOS.zip", "dovi_tool macOS ZIP")
    machine = platform.machine().lower()
    if platform.system() == "Linux" and machine in ("x86_64", "amd64"):
        return (base + "dovi_tool-x86_64-unknown-linux-musl.tar.gz",
                "dovi_tool Linux x64 TAR.GZ")
    if platform.system() == "Linux" and machine in ("aarch64", "arm64"):
        return (base + "dovi_tool-aarch64-unknown-linux-musl.tar.gz",
                "dovi_tool Linux ARM64 TAR.GZ")
    return None, "unsupported platform"


def app_settings():
    return QSettings(CONFIG_FILE, QSettings.Format.IniFormat)


# --------------------------------------------------------------------------- #
# Codec / encoder tables
# --------------------------------------------------------------------------- #

CODECS = {
    "x264": "libx264", "x265": "libx265",
    "vp9": "libvpx-vp9", "av1": "libsvtav1",
    "mpeg4": "mpeg4", "xvid": "libxvid",
    "mpeg2": "mpeg2video", "wmv": "wmv2", "prores": "prores_ks",
    "dnxhd": "dnxhd", "ffv1": "ffv1",
}
X_PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast",
             "medium", "slow", "slower", "veryslow"]
BUILTIN_PRESETS = (
    ["H.264 - " + p for p in X_PRESETS]
    + ["H.265 - " + p for p in X_PRESETS]
    + ["H.264 - CRF", "H.265 - CRF", "MPEG-4", "Xvid", "MPEG-2", "WMV",
       "H.264 - Copy video"]
)
HW_ACCELS = {
    "None": None,
    "NVIDIA NVENC": "nvenc",
    "Intel QSV": "qsv",
    "AMD AMF": "amf",
    "VAAPI": "vaapi",
    "Apple VideoToolbox": "videotoolbox",
}
HW_ENCODERS = {
    ("x264", "nvenc"): "h264_nvenc", ("x264", "qsv"): "h264_qsv",
    ("x264", "amf"): "h264_amf", ("x264", "vaapi"): "h264_vaapi",
    ("x264", "videotoolbox"): "h264_videotoolbox",
    ("x265", "nvenc"): "hevc_nvenc", ("x265", "qsv"): "hevc_qsv",
    ("x265", "amf"): "hevc_amf", ("x265", "vaapi"): "hevc_vaapi",
    ("x265", "videotoolbox"): "hevc_videotoolbox",
    ("vp9", "vaapi"): "vp9_vaapi",
    ("av1", "nvenc"): "av1_nvenc", ("av1", "qsv"): "av1_qsv",
    ("av1", "vaapi"): "av1_vaapi",
}
HW_QUALITY_OPT = {"nvenc": "-cq", "qsv": "-global_quality",
                  "amf": "-qp", "vaapi": "-qp",
                  "videotoolbox": "-q:v"}
# QSV/VAAPI require an explicit hardware device and upload filter.
HW_INIT = {
    "qsv": ["-init_hw_device", "qsv=hw", "-filter_hw_device", "hw"],
}
AUDIO_CODECS = ["AAC", "MP3", "FLAC", "OGG (Vorbis)", "AC-3", "Copy"]
AUDIO_BITRATES = ["320", "256", "224", "192", "160", "128", "96", "64", "48"]
AUDIO_DOWNMIX_PRESETS = [
    ("original", ""),
    ("mono (1)", "1"),
    ("stereo (2)", "2"),
    ("5.1 (6)", "6"),
    ("7.1 (8)", "8"),
    ("5.1 -> stereo", "2"),
]

HDR_MODES = [
    "Auto (match source)",
    "SDR (tone map to BT.709)",
    "HDR10 (BT.2020 / PQ)",
    "HLG (BT.2020 / HLG)",
    "HDR10+ (dynamic metadata)",
    "Dolby Vision (source RPU)",
]
DEFAULT_MASTER = ("G(13250,34500)B(7500,3000)R(34000,16000)"
                  "WP(15635,16450)L(10000000,1)")
DEFAULT_CL = "1000,400"

LANG_NAMES = {
    "eng": "English", "ita": "Italian", "fra": "French", "fre": "French",
    "spa": "Spanish", "deu": "German", "ger": "German", "por": "Portuguese",
    "jpn": "Japanese", "kor": "Korean", "chi": "Chinese", "zho": "Chinese",
    "rus": "Russian", "ara": "Arabic", "hin": "Hindi", "tur": "Turkish",
    "pol": "Polish", "nld": "Dutch", "dut": "Dutch", "swe": "Swedish",
    "nor": "Norwegian", "dan": "Danish", "fin": "Finnish", "ces": "Czech",
    "cze": "Czech", "ell": "Greek", "gre": "Greek", "heb": "Hebrew",
    "tha": "Thai", "vie": "Vietnamese", "ind": "Indonesian",
    "msa": "Malay", "may": "Malay", "cat": "Catalan", "ron": "Romanian",
    "rum": "Romanian", "hun": "Hungarian", "ukr": "Ukrainian",
    "bul": "Bulgarian", "hrv": "Croatian", "srp": "Serbian",
    "slk": "Slovak", "slo": "Slovak", "slv": "Slovenian",
    "est": "Estonian", "lav": "Latvian", "lit": "Lithuanian",
    "isl": "Icelandic", "afr": "Afrikaans", "lat": "Latin",
    "mul": "Multiple", "und": "Unknown", "zxx": "No linguistic content",
}


def lang_name(code):
    code = (code or "").strip().lower().split("-")[0]
    return LANG_NAMES.get(code, code.capitalize() if code else "")


THEMES = {
    "dark": {
        "bg": "#1e1e2e", "panel": "#181825", "field": "#313244",
        "border": "#45475a", "hover": "#585b70", "pressed": "#313244",
        "disabled": "#292c3c", "accent": "#89b4fa", "accent_hover": "#a6adc8",
        "accent_fg": "#11111b", "danger": "#f38ba8", "danger_hover": "#eba0ac",
        "text": "#cdd6f4", "muted": "#a6adc8", "dim": "#6c7086",
        "success": "#a6e3a1", "slider_track": "#313244",
    },
    "light": {
        "bg": "#eef1f6", "panel": "#ffffff", "field": "#ffffff",
        "border": "#c9d2e0", "hover": "#e3e9f2", "pressed": "#d5deea",
        "disabled": "#e6eaf0", "accent": "#2563eb", "accent_hover": "#1d4ed8",
        "accent_fg": "#ffffff", "danger": "#dc2626", "danger_hover": "#b91c1c",
        "text": "#1f2430", "muted": "#4b5563", "dim": "#8a94a6",
        "success": "#16a34a", "slider_track": "#d5deea",
    },
}


def make_style(p):
    return f"""
* {{ outline: none; }}
QMainWindow, QWidget {{ background-color: {p['bg']}; color: {p['text']}; font-size: 13px; }}
QGroupBox {{ border: 1px solid {p['border']}; border-radius: 8px; margin-top: 0.9em;
            padding-top: 0.3em; background: {p['panel']}; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; color: {p['accent']}; }}
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QListWidget {{
    background: {p['field']}; border: 1px solid {p['border']}; border-radius: 6px;
    padding: 2px 5px; color: {p['text']}; selection-background-color: {p['accent']};
    selection-color: {p['accent_fg']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {p['accent']}; }}
QLineEdit:disabled, QComboBox:disabled {{ color: {p['dim']}; background: {p['disabled']}; }}
QPushButton {{ background: {p['field']}; border: 1px solid {p['border']}; border-radius: 6px;
              padding: 3px 10px; color: {p['text']}; }}
QPushButton:hover {{ background: {p['hover']}; }}
QPushButton:pressed {{ background: {p['pressed']}; }}
QPushButton:disabled {{ background: {p['disabled']}; color: {p['dim']}; border-color: {p['border']}; }}
QPushButton#primary {{ background: {p['accent']}; color: {p['accent_fg']}; font-weight: 600; }}
QPushButton#primary:hover {{ background: {p['accent_hover']}; }}
QPushButton#danger {{ background: {p['danger']}; color: {p['accent_fg']}; }}
QPushButton#danger:hover {{ background: {p['danger_hover']}; }}
QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: 6px; background: {p['panel']}; }}
QTabBar::tab {{ background: {p['field']}; color: {p['muted']}; padding: 4px 12px;
               border-top-left-radius: 6px; border-top-right-radius: 6px;
               margin-right: 2px; }}
QTabBar::tab:selected {{ background: {p['accent']}; color: {p['accent_fg']}; font-weight: 600; }}
QSlider::groove:horizontal {{ height: 6px; background: {p['slider_track']}; border-radius: 3px; }}
QSlider::handle:horizontal {{ width: 14px; margin: -5px 0; border-radius: 7px;
                             background: {p['accent']}; }}
QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px;
                       border: 1px solid {p['border']}; background: {p['field']}; }}
QCheckBox::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; }}
QProgressBar {{ border: 1px solid {p['border']}; border-radius: 6px; background: {p['field']};
               text-align: center; color: {p['text']}; }}
QProgressBar::chunk {{ background: {p['success']}; border-radius: 5px; }}
QStatusBar {{ background: {p['panel']}; color: {p['muted']}; }}
QStatusBar::item {{ border: none; }}
QComboBox QAbstractItemView {{ background: {p['field']}; color: {p['text']};
                              selection-background-color: {p['accent']}; }}
QToolTip {{ background: {p['field']}; color: {p['text']}; border: 1px solid {p['border']}; }}
"""


# --------------------------------------------------------------------------- #
# Binary discovery
# --------------------------------------------------------------------------- #


def find_binary(name):
    local = os.path.join(BINARY_DIR, name + (".exe" if IS_WINDOWS else ""))
    if os.path.exists(local):
        return local
    found = shutil.which(name)
    return found if found else name


class Binaries:
    """Resolved paths for the external tools used by the application."""

    def __init__(self, ffmpeg=None, ffprobe=None, ffplay=None, dovi=None):
        self.ffmpeg = ffmpeg or find_binary("ffmpeg")
        self.ffprobe = ffprobe or find_binary("ffprobe")
        self.ffplay = ffplay or find_binary("ffplay")
        self.dovi = dovi or find_binary("dovi_tool")

    def refresh(self):
        self.ffmpeg = find_binary("ffmpeg")
        self.ffprobe = find_binary("ffprobe")
        self.ffplay = find_binary("ffplay")
        self.dovi = find_binary("dovi_tool")

    def has(self, name):
        path = getattr(self, name, None)
        return bool(path and os.path.exists(path))

    def all_ffmpeg_tools(self):
        return (self.has("ffmpeg") and self.has("ffprobe")
                and self.has("ffplay"))


def probe_encoder(ffmpeg_bin, encoder, accel):
    """Return True if *encoder* actually works on this machine.

    Merely being listed by ``ffmpeg -encoders`` only means the encoder is
    compiled in; the underlying device (GPU / DRM node) must also be present.
    A short real encode validates that the hardware is truly usable.
    """
    cmd = [ffmpeg_bin, "-hide_banner", "-y"]
    if accel == "qsv":
        cmd += ["-init_hw_device", "qsv=hw", "-filter_hw_device", "hw"]
    elif accel == "vaapi":
        cmd += ["-vaapi_device", detect_vaapi_device()]
    cmd += ["-f", "lavfi", "-i", "color=black:s=320x240:d=0.2"]
    if accel == "qsv":
        cmd += ["-vf", "format=nv12,hwupload=extra_hw_frames=64"]
    elif accel == "vaapi":
        cmd += ["-vf", "format=nv12,hwupload"]
    cmd += ["-c:v", encoder, "-b:v", "200k", "-f", "null", "-"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           errors="replace", timeout=20)
        return p.returncode == 0
    except Exception:
        return False


def detect_hw_encoders(ffmpeg_bin):
    """Return the set of hardware encoders actually usable on this machine.

    Each encoder is probed individually: being compiled into FFmpeg is not
    enough, and different codecs on the same device are not all guaranteed to
    work (for example AMD Vega supports H.264/HEVC VAAPI but not AV1).
    """
    compiled = set()
    try:
        p = subprocess.run([ffmpeg_bin, "-hide_banner", "-encoders"],
                           capture_output=True, text=True, errors="replace",
                           timeout=15)
        for line in p.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] == "V":
                compiled.add(parts[1])
    except Exception:
        return set()

    result = set()
    for accel in ("nvenc", "qsv", "amf", "vaapi", "videotoolbox"):
        candidates = [HW_ENCODERS[(f, accel)]
                      for f in ("x264", "x265", "vp9", "av1")
                      if (f, accel) in HW_ENCODERS]
        for encoder in candidates:
            if encoder in compiled and probe_encoder(ffmpeg_bin, encoder, accel):
                result.add(encoder)
    return result


def detect_vaapi_device():
    """Return the first usable VAAPI render node, or the default path."""
    candidates = []
    try:
        for entry in sorted(os.listdir("/dev/dri")):
            if entry.startswith("renderD"):
                candidates.append(os.path.join("/dev/dri", entry))
    except OSError:
        pass
    for dev in candidates:
        if os.path.exists(dev):
            return dev
    return "/dev/dri/renderD128"


def make_executable(path):
    if path and os.path.exists(path) and not IS_WINDOWS:
        try:
            os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        except OSError:
            pass
