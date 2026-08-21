# -*- coding: utf-8 -*-
"""Pure preflight validation for media jobs.

The GUI and the wizard both use this module so they cannot drift into
generating different notions of a valid job.
"""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .core import BITMAP_SUB_CODECS, EncodeOptions, ProbeInfo, avisynth_active
from .bluray import is_bluray_path


@dataclass
class PreflightIssue:
    severity: str  # error, warning, info
    code: str
    message: str
    fix: str = ""


def _tool_available(path: Optional[str]) -> bool:
    return bool(path and (os.path.exists(path) or shutil.which(path)))


def preflight(options: EncodeOptions, probe: ProbeInfo,
              ffmpeg_encoders=None) -> List[PreflightIssue]:
    """Return actionable issues without starting an external process."""
    issues = []
    if options.bluray.enabled:
        if not options.bluray.path or not os.path.exists(options.bluray.path):
            issues.append(PreflightIssue("error", "missing-input",
                                         "The Blu-ray source does not exist."))
        if not options.bluray.path or not is_bluray_path(options.bluray.path):
            issues.append(PreflightIssue(
                "error", "invalid-bluray",
                "Choose a Blu-ray ISO or a folder containing BDMV."))
        if options.avisynth.enabled and not options.avisynth.script_path:
            issues.append(PreflightIssue(
                "error", "bluray-generated-avs",
                "AviSynth cannot generate a source automatically from a Blu-ray playlist.",
                "Select a script that opens a concrete playlist stream."))
    elif not options.inputfile or not os.path.exists(options.inputfile):
        issues.append(PreflightIssue("error", "missing-input",
                                     "The input file does not exist."))
        return issues
    if not options.nomux and not options.outputfile:
        issues.append(PreflightIssue("error", "missing-output",
                                     "Choose an output file before encoding."))
    if not probe.has_video and options.mode not in ("Audio only",):
        issues.append(PreflightIssue("error", "missing-video",
                                     "The selected mode needs a video stream."))
    if options.mode == "Remux (copy all)" and avisynth_active(options):
        issues.append(PreflightIssue(
            "error", "avisynth-remux",
            "AviSynth changes the video and cannot be used with remux-copy.",
            "Choose an encoding mode."))
    if options.avisynth.script_path and not os.path.exists(options.avisynth.script_path):
        issues.append(PreflightIssue(
            "error", "missing-avs",
            "The selected AviSynth script does not exist."))
    if avisynth_active(options) and options.avisynth.plugin_paths:
        missing = [p for p in options.avisynth.plugin_paths
                   if not os.path.exists(p)]
        if missing:
            issues.append(PreflightIssue(
                "error", "missing-avs-plugin",
                f"AviSynth plugin missing: {Path(missing[0]).name}",
                "Install it or remove it from the plugin list."))
    encoders = ffmpeg_encoders or set()
    selected_encoder = (options.video_encoder or
                        options.preset.get("encoder", ""))
    if selected_encoder and encoders and selected_encoder not in encoders:
        issues.append(PreflightIssue(
            "error", "missing-video-encoder",
            f"Video encoder {selected_encoder} is not available in FFmpeg."))
    if options.preset.get("family") == "x266" and not any(
            name in encoders for name in ("libvvenc", "libx266")):
        issues.append(PreflightIssue(
            "error", "missing-x266",
            "The x266/VVC profile needs libvvenc or libx266 in FFmpeg."))
    suffix = Path(options.outputfile).suffix.lower()
    for row in options.audio:
        if not row.enabled:
            continue
        tool = (row.encoder or "ffmpeg").lower()
        if tool != "ffmpeg" and not _tool_available(
                options.audio_tools.get(row.encoder) or
                options.audio_tools.get(tool) or tool):
            issues.append(PreflightIssue(
                "error", "missing-audio-tool",
                f"External audio encoder {tool} is not installed."))
        if suffix == ".mp4" and row.codec == "OGG (Vorbis)":
            issues.append(PreflightIssue(
                "error", "vorbis-mp4",
                "Ogg/Vorbis audio is not compatible with MP4.",
                "Use MKV or choose AAC."))
    for row in options.subs:
        if not row.enabled or row.input_index >= len(probe.subtitle_tracks):
            continue
        codec = (probe.subtitle_tracks[row.input_index].get("codec_name") or "").lower()
        if row.burn and codec in BITMAP_SUB_CODECS:
            issues.append(PreflightIssue(
                "error", "bitmap-burn",
                "Bitmap subtitles cannot be burned with the current pipeline.",
                "Choose a text subtitle or use OCR first."))
        if options.bluray.enabled and row.burn:
            issues.append(PreflightIssue(
                "error", "bluray-burn",
                "Blu-ray subtitle burn-in needs a separate OCR/source extraction step."))
        if suffix == ".mp4" and not row.burn and codec in BITMAP_SUB_CODECS:
            issues.append(PreflightIssue(
                "error", "bitmap-mp4",
                "PGS/DVD subtitles cannot be stored in MP4.",
                "Use MKV or deselect the bitmap subtitle."))
    if options.mode == "2-pass bitrate" and options.hw:
        issues.append(PreflightIssue(
            "warning", "hardware-two-pass",
            "Hardware encoding will be reduced to one pass."))
    if options.hdr_mode in ("HDR10 (BT.2020 / PQ)", "HLG (BT.2020 / HLG)",
                            "HDR10+ (dynamic metadata)",
                            "Dolby Vision (source RPU)") and options.hw:
        issues.append(PreflightIssue(
            "warning", "hardware-hdr",
            "This HDR workflow will use software x265 instead of hardware."))
    if not any(row.enabled for row in options.audio) and options.mode != "Audio only":
        issues.append(PreflightIssue("info", "no-audio",
                                     "The output will contain no audio."))
    return issues
