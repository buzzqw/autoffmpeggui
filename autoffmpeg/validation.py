# -*- coding: utf-8 -*-
"""Pure preflight validation for media jobs.

The GUI and the wizard both use this module so they cannot drift into
generating different notions of a valid job.
"""

import os
import re
import shutil
import subprocess
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


def _missing_avisynth_dependency(plugin_paths):
    """Return ``(library, plugin)`` for a missing Linux plugin dependency."""
    if not plugin_paths or not shutil.which("ldd") or os.name != "posix":
        return None
    candidates = set()
    for path in plugin_paths:
        if not os.path.isfile(path):
            continue
        candidates.add(path)
        # AviSynth+ may autoload other plugins from the same directory.
        candidates.update(str(item) for item in Path(path).parent.glob("*.so"))
    for plugin in sorted(candidates):
        try:
            result = subprocess.run(["ldd", plugin], capture_output=True,
                                    text=True, errors="replace", timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            continue
        for line in result.stdout.splitlines():
            match = re.search(r"^\s*(\S+)\s+=>\s+not found\s*$", line)
            if match:
                return match.group(1), Path(plugin).name
    return None


def preflight(options: EncodeOptions, probe: ProbeInfo,
              ffmpeg_encoders=None, dovi_encoder_supported=None) -> List[PreflightIssue]:
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
    if (options.hdr_mode == "Dolby Vision (source RPU)" and probe.source_dv and
            options.dovi_tool and os.path.exists(options.dovi_tool) and
            dovi_encoder_supported is False):
        issues.append(PreflightIssue(
            "error", "unsupported-dovi-x265",
            "The selected FFmpeg/libx265 build cannot inject a Dolby Vision RPU.",
            "Install a Dolby Vision-enabled x265 build or use static HDR10."))
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
        else:
            dependency = _missing_avisynth_dependency(
                options.avisynth.plugin_paths)
            if dependency:
                library, plugin = dependency
                issues.append(PreflightIssue(
                    "error", "missing-avs-dependency",
                    f"AviSynth plugin {plugin} needs missing library {library}.",
                    "Install the package providing the library or remove the "
                    "plugin from the AviSynth directory."))
    encoders = ffmpeg_encoders or set()
    selected_encoder = (options.video_encoder or
                        options.preset.get("encoder", ""))
    if selected_encoder and encoders and selected_encoder not in encoders:
        issues.append(PreflightIssue(
            "error", "missing-video-encoder",
            f"Video encoder {selected_encoder} is not available in FFmpeg."))
    if options.external_video_encoder:
        external = options.external_video_binary or options.external_video_encoder
        if not _tool_available(external):
            issues.append(PreflightIssue(
                "error", "missing-external-video-encoder",
                f"External video encoder {options.external_video_encoder} "
                "is not installed.",
                "Install it or select FFmpeg (internal)."))
        if options.mode == "2-pass bitrate":
            issues.append(PreflightIssue(
                "warning", "external-two-pass-fallback",
                "The external encoder selection is not used for FFmpeg two-pass "
                "mode; this job will use FFmpeg."))
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
            kind = "Blu-ray PGS" if codec == "hdmv_pgs_subtitle" else "bitmap"
            issues.append(PreflightIssue(
                "error", "bitmap-burn",
                f"{kind} subtitle track {row.input_index + 1} cannot be "
                "burned into the video.",
                "Choose a text subtitle or use OCR first."))
        elif options.bluray.enabled and row.burn:
            issues.append(PreflightIssue(
                "error", "bluray-burn",
                f"Blu-ray subtitle track {row.input_index + 1} cannot be "
                "burned into the video by this pipeline.",
                "Choose a text subtitle or extract/OCR it first."))
        if suffix == ".mp4" and not row.burn and codec in BITMAP_SUB_CODECS:
            kind = "Blu-ray PGS" if codec == "hdmv_pgs_subtitle" else "bitmap"
            issues.append(PreflightIssue(
                "error", "bitmap-mp4",
                f"{kind} subtitle track {row.input_index + 1} cannot be "
                "stored in an MP4 container.",
                "Select MKV, or deselect this subtitle track before encoding."))
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
