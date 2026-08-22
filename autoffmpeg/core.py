# -*- coding: utf-8 -*-
# AutoFFmpegGui v2 - PyQt6
# SPDX-License-Identifier: EUPL-1.2
# Licensed under the EUPL v1.2 (see LICENSE file in the project root).
"""Pure, testable command-building logic for AutoFFmpegGui.

This module intentionally has no Qt dependency so that it can be unit tested
without a display or an installed FFmpeg. Every FFmpeg command is built as a
list of arguments (never through a shell) to avoid shell injection.
"""

import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .config import (
    CODECS,
    DEFAULT_CL,
    DEFAULT_MASTER,
    ENCODER_OPTION_CATALOG,
    HW_ACCELS,
    HW_ENCODERS,
    HW_INIT,
    HW_QUALITY_OPT,
    detect_vaapi_device,
)
from .bluray import BlurayOptions, bluray_input_options, bluray_url

TEXT_SUB_CODECS = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text",
                   "subtitle", "text", "eia_608", "microdvd", "sami"}
BITMAP_SUB_CODECS = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle",
                     "xsub", "pgssub"}

# Elementary (no-mux) output formats: family/codec -> (ffmpeg format, suffix).
VIDEO_RAW_FORMATS = {
    "x264": ("h264", ".h264"),
    "x265": ("hevc", ".hevc"),
    "vp9": ("ivf", ".ivf"),
    "av1": ("ivf", ".ivf"),
    "mpeg4": ("m4v", ".m4v"),
    "xvid": ("m4v", ".m4v"),
    "mpeg2": ("mpeg2video", ".m2v"),
    "wmv": ("asf", ".asf"),
    "prores": ("mov", ".mov"),
    "dnxhd": ("mxf", ".mxf"),
    "ffv1": ("matroska", ".mkv"),
    "x266": ("matroska", ".mkv"),
}
AUDIO_RAW_FORMATS = {
    "AAC": ("adts", ".aac"),
    "MP3": ("mp3", ".mp3"),
    "FLAC": ("flac", ".flac"),
    "OGG (Vorbis)": ("ogg", ".ogg"),
    "AC-3": ("ac3", ".ac3"),
}
SOURCE_AUDIO_FORMATS = {
    "aac": ("adts", ".aac"),
    "ac3": ("ac3", ".ac3"),
    "eac3": ("eac3", ".eac3"),
    "mp3": ("mp3", ".mp3"),
    "flac": ("flac", ".flac"),
    "opus": ("opus", ".opus"),
    "vorbis": ("ogg", ".ogg"),
    "dts": ("dts", ".dts"),
    "truehd": ("truehd", ".thd"),
    "pcm_s16le": ("s16le", ".pcm"),
    "pcm_s24le": ("s24le", ".pcm"),
}
# text subtitle codec -> (ffmpeg format, suffix, encoder)
TEXT_SUB_FORMATS = {
    "subrip": ("srt", ".srt", "srt"),
    "srt": ("srt", ".srt", "srt"),
    "mov_text": ("srt", ".srt", "srt"),
    "text": ("srt", ".srt", "srt"),
    "subtitle": ("srt", ".srt", "srt"),
    "microdvd": ("srt", ".srt", "srt"),
    "sami": ("srt", ".srt", "srt"),
    "webvtt": ("webvtt", ".vtt", "webvtt"),
    "ass": ("ass", ".ass", "ass"),
    "ssa": ("ass", ".ass", "ass"),
}


# --------------------------------------------------------------------------- #
# Data structures
# --------------------------------------------------------------------------- #


@dataclass
class Measure:
    """A loudness measurement to run before a job and its placeholder tokens."""
    cmd: List[str]
    tokens: dict  # token -> loudnorm key ('I', 'TP', 'LRA', 'TH', 'OFF')


@dataclass
class EncodeJob:
    label: str
    cmd: List[str]
    duration: float = 0.0
    measures: List[Measure] = field(default_factory=list)
    cleanup: List[str] = field(default_factory=list)
    is_video: bool = True
    # Optional argv-only pipeline for external tools.  Each item is an argv
    # list; workers connect stdout to stdin without invoking a shell.
    pipeline: List[List[str]] = field(default_factory=list)


@dataclass
class ProbeInfo:
    duration: float = 0.0
    vwidth: int = 0
    vheight: int = 0
    framerate: float = 0.0
    has_video: bool = False
    source_hdr_info: Optional[tuple] = None  # (primaries, transfer, colorspace)
    source_dv: bool = False
    dv_profile: Optional[int] = None
    audio_tracks: List[dict] = field(default_factory=list)
    subtitle_tracks: List[dict] = field(default_factory=list)


@dataclass
class AudioSelection:
    input_index: int
    enabled: bool = True
    codec: str = "AAC"
    bitrate: int = 128
    channels: str = "original"
    sampling: str = "auto"
    encoder: str = "ffmpeg"
    encoder_options: Dict[str, str] = field(default_factory=dict)


@dataclass
class SubtitleSelection:
    input_index: int
    enabled: bool = True
    burn: bool = False


@dataclass
class AvisynthOptions:
    """Configuration for an AviSynth+ video source/processing script."""
    enabled: bool = False
    script_path: str = ""
    script_text: str = ""
    source_filter: str = "FFVideoSource"
    plugin_paths: List[str] = field(default_factory=list)
    # script: AviSynth owns resize/crop/deinterlace; ffmpeg: keep current GUI
    # filters; both: apply both deliberately.
    filter_mode: str = "script"
    keep_generated_script: bool = True


@dataclass
class InputPlan:
    """Input indices used by generated FFmpeg commands."""
    inputs: List[str] = field(default_factory=list)
    video_index: int = 0
    audio_index: int = 0
    subtitle_index: int = 0
    generated_script: str = ""
    input_options: Dict[int, List[str]] = field(default_factory=dict)


def source_path(options: "EncodeOptions") -> str:
    return bluray_url(options.bluray) if options.bluray.enabled else options.inputfile


def source_exists(options: "EncodeOptions") -> bool:
    if options.bluray.enabled:
        return bool(options.bluray.path and os.path.exists(options.bluray.path))
    return bool(options.inputfile and os.path.exists(options.inputfile))


def _parse_rate(value) -> float:
    try:
        if isinstance(value, str) and "/" in value:
            num, den = value.split("/", 1)
            return float(num) / float(den) if float(den) else 0.0
        return float(value or 0)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def probe_duration(data: dict) -> float:
    """Return a useful duration even when ffprobe reports ``N/A``."""
    fmt = data.get("format", {}) or {}
    try:
        duration = float(fmt.get("duration", 0) or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration > 0:
        return duration
    for stream in data.get("streams", []):
        try:
            frames = float(stream.get("nb_frames", 0) or 0)
        except (TypeError, ValueError):
            frames = 0.0
        rate = _parse_rate(stream.get("avg_frame_rate") or
                           stream.get("r_frame_rate"))
        if frames > 0 and rate > 0:
            return frames / rate
    return 0.0


@dataclass
class EncodeOptions:
    inputfile: str = ""
    outputfile: str = ""
    # UI-facing output selection. outputfile remains the resolved final path.
    output_base: str = ""
    container: str = ""
    preset: dict = field(default_factory=lambda: {"family": "x264"})
    mode: str = "Quality (CRF)"
    hw: Optional[str] = None
    quality: int = 23
    bitrate: int = 2000
    hdr_mode: str = "Auto (match source)"
    masterdisplay: str = DEFAULT_MASTER
    maxcll: str = DEFAULT_CL
    hdr_meta: str = ""
    resize: bool = True
    width: int = 0
    height: int = 0
    mod: int = 16
    crop_l: int = 0
    crop_r: int = 0
    crop_t: int = 0
    crop_b: int = 0
    deinterlace: bool = False
    framerate: str = "automatic"
    vframes: str = ""
    normalize: bool = False
    gain: int = 0
    audio: List[AudioSelection] = field(default_factory=list)
    subs: List[SubtitleSelection] = field(default_factory=list)
    trim_start: str = ""
    trim_end: str = ""
    keep_chapters: bool = False
    keep_metadata: bool = False
    batch: bool = False
    nomux: bool = False
    available_encoders: set = field(default_factory=set)
    dovi_tool: Optional[str] = None
    avisynth: AvisynthOptions = field(default_factory=AvisynthOptions)
    # Overrides are FFmpeg output options (without the leading dash), e.g.
    # {"aq-mode": "3", "psy-rd": "2.0"}. Empty values represent flags.
    encoder_options: Dict[str, str] = field(default_factory=dict)
    video_encoder: str = ""
    audio_tools: Dict[str, str] = field(default_factory=dict)
    bluray: BlurayOptions = field(default_factory=BlurayOptions)


# --------------------------------------------------------------------------- #
# Preset / profile parsing
# --------------------------------------------------------------------------- #


def detect_family(args):
    a = (args or "").lower()
    if "x266" in a or "libvvenc" in a or "libx266" in a or "vvc" in a:
        return "x266"
    if "libsvtav1" in a or "libaom" in a or "av1" in a:
        return "av1"
    if "libvpx-vp9" in a or "vp9" in a:
        return "vp9"
    if "h265" in a or "x265" in a or "libx265" in a or "hevc" in a:
        return "x265"
    if "h264" in a or "x264" in a or "libx264" in a:
        return "x264"
    if "xvid" in a:
        return "xvid"
    if "mpeg2" in a:
        return "mpeg2"
    if "wmv" in a or "wmav2" in a or "vc1" in a:
        return "wmv"
    if "mpeg4" in a:
        return "mpeg4"
    if "prores" in a:
        return "prores"
    if "dnxhr" in a or "dnxhd" in a:
        return "dnxhd"
    if "ffv1" in a:
        return "ffv1"
    return "x264"


def pb_profile_parse(lines):
    out, seen = [], set()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(";")
        name = parts[0].strip()
        if not name or name in seen:
            continue
        args = parts[3].strip() if len(parts) > 3 and parts[3].strip() else (
            parts[1].strip() if len(parts) > 1 else "")
        out.append((name, args))
        seen.add(name)
    return out


# --------------------------------------------------------------------------- #
# HDR / family resolution
# --------------------------------------------------------------------------- #

HARD_HDR_MODES = (
    "HDR10 (BT.2020 / PQ)",
    "HLG (BT.2020 / HLG)",
    "HDR10+ (dynamic metadata)",
    "Dolby Vision (source RPU)",
)


def hdr_active(options: EncodeOptions, probe: ProbeInfo) -> bool:
    m = options.hdr_mode
    if m in HARD_HDR_MODES:
        return True
    if m == "Auto (match source)":
        return probe.source_hdr_info is not None
    return False


def effective_hw(options: EncodeOptions, probe: ProbeInfo) -> Optional[str]:
    if hdr_active(options, probe):
        return None
    return options.hw


def effective_family(options: EncodeOptions, probe: ProbeInfo) -> str:
    if hdr_active(options, probe):
        return "x265"
    return options.preset.get("family", "x264")


def family_supports_quality(family):
    return family in ("x264", "x265", "x266", "vp9", "av1", "mpeg4", "xvid",
                      "mpeg2", "wmv")


def family_supports_bitrate(family):
    return family in ("x264", "x265", "x266", "vp9", "av1", "mpeg4", "xvid",
                      "mpeg2", "wmv")


def encoder_option_catalog(family: str) -> Dict[str, str]:
    """Return a copy of the profile editor catalog for an encoder family."""
    return dict(ENCODER_OPTION_CATALOG.get(family, {}))


def _encoder_override_args(args: List[str], options: Dict[str, str]) -> List[str]:
    """Apply profile overrides once, replacing generated duplicate options."""
    out = list(args)
    for key, value in (options or {}).items():
        flag = str(key).strip()
        if not flag:
            continue
        if not flag.startswith("-"):
            flag = "-" + flag
        # Remove the previous flag and its value. FFmpeg options represented
        # as flags (empty/true) are also supported.
        cleaned = []
        i = 0
        while i < len(out):
            if out[i] == flag:
                i += 1
                if i < len(out) and (not out[i].startswith("-") or
                                     re.match(r"-\d", out[i])):
                    i += 1
                continue
            cleaned.append(out[i])
            i += 1
        out = cleaned
        value = "" if value is None else str(value).strip()
        out.append(flag)
        if value and value.lower() not in ("true", "yes"):
            out.append(value)
    return out


# --------------------------------------------------------------------------- #
# Filter chain
# --------------------------------------------------------------------------- #


def escape_filter_arg(path):
    """Escape a path for use inside an ffmpeg filter graph argument."""
    p = (path or "").replace("\\", "/")
    p = p.replace(":", "\\:")
    p = p.replace("'", "\\'")
    return p


def build_filter_args(options: EncodeOptions, probe: ProbeInfo) -> List[str]:
    if (options.avisynth.enabled and options.avisynth.filter_mode == "script") or \
            Path(options.inputfile).suffix.lower() == ".avs":
        return []
    if not options.resize and not options.deinterlace:
        return []
    vf = []
    if options.resize:
        l, r, t, b = (options.crop_l, options.crop_r,
                      options.crop_t, options.crop_b)
        cw = max(2, probe.vwidth - l - r)
        ch = max(2, probe.vheight - t - b)
        if l or r or t or b:
            vf.append(f"crop={cw}:{ch}:{l}:{t}")
        w, h = options.width, options.height
        if w and h and (w != probe.vwidth or h != probe.vheight):
            vf.append(f"scale={w}:{h}")
    if options.deinterlace:
        vf.append("yadif")
    return vf


def _avs_quote(path: str) -> str:
    """Quote a Windows/POSIX path for an AviSynth string literal."""
    return (path or "").replace("\\", "\\\\").replace('"', '\\"')


def _avisynth_filter_lines(options: EncodeOptions, probe: ProbeInfo) -> List[str]:
    """Translate the safe GUI resize/deinterlace controls to AviSynth calls."""
    if not options.resize and not options.deinterlace:
        return []
    lines = []
    l, r, t, b = options.crop_l, options.crop_r, options.crop_t, options.crop_b
    if options.resize and (l or r or t or b):
        cw = max(2, probe.vwidth - l - r)
        ch = max(2, probe.vheight - t - b)
        lines.append(f"src = src.Crop({l}, {t}, {cw}, {ch})")
    if options.resize and options.width and options.height and \
            (options.width != probe.vwidth or options.height != probe.vheight):
        lines.append(f"src = src.Spline36Resize({options.width}, {options.height})")
    if options.deinterlace:
        lines.append('src = src.QTGMC(preset="Fast")')
    return lines


def build_avisynth_script(options: EncodeOptions, probe: ProbeInfo) -> str:
    """Return a complete or templated AviSynth+ script for this encode."""
    av = options.avisynth
    template = av.script_text.strip()
    if not template:
        template = (
            '# AutoFFmpegGui AviSynth+ script\n'
            '# Edit this script to add any AviSynth filter or plugin.\n'
            '{{PLUGIN_LOADS}}\n'
            'src = {{SOURCE_FILTER}}("{{INPUT}}")\n'
            '{{VIDEO_FILTERS}}\n'
            'src\n')
    loads = "\n".join(
        f'LoadPlugin("{_avs_quote(p)}")' for p in av.plugin_paths if p)
    filters = ("\n".join(_avisynth_filter_lines(options, probe))
               if av.filter_mode in ("script", "both") else "")
    return (template.replace("{{PLUGIN_LOADS}}", loads)
            .replace("{{SOURCE_FILTER}}", av.source_filter or "FFVideoSource")
            .replace("{{INPUT}}", _avs_quote(source_path(options)))
            .replace("{{VIDEO_FILTERS}}", filters))


def avisynth_active(options: EncodeOptions) -> bool:
    return bool(options.avisynth.enabled or
                Path(options.inputfile).suffix.lower() == ".avs")


def build_input_plan(options: EncodeOptions, probe: ProbeInfo) -> InputPlan:
    """Materialize an AviSynth script and describe FFmpeg stream indices."""
    input_path = source_path(options)
    source_opts = ({0: bluray_input_options(options.bluray)}
                   if options.bluray.enabled else {})
    if not avisynth_active(options):
        return InputPlan(inputs=[input_path], input_options=source_opts)

    av = options.avisynth
    script_path = av.script_path.strip()
    if not script_path and Path(options.inputfile).suffix.lower() == ".avs":
        script_path = options.inputfile
    if script_path:
        if script_path != options.inputfile and \
                Path(options.inputfile).suffix.lower() != ".avs":
            # A script selected for a normal media file usually exposes video
            # only. Keep the original input for audio and subtitles.
            return InputPlan(inputs=[input_path, script_path],
                             video_index=1, audio_index=0, subtitle_index=0,
                             input_options=source_opts)
        # A standalone script is the only reliable source for both streams.
        return InputPlan(inputs=[script_path], video_index=0, audio_index=0,
                         subtitle_index=0)

    script = build_avisynth_script(options, probe)
    if options.outputfile:
        script_path = str(Path(options.outputfile).with_suffix(".avs"))
    else:
        script_path = str(Path(options.inputfile).with_suffix(".autoffmpeg.avs"))
    try:
        Path(script_path).write_text(script, encoding="utf-8")
    except OSError:
        # The eventual FFmpeg error is more useful than silently using an
        # incomplete source. Keep the path in the command for diagnostics.
        pass
    return InputPlan(inputs=[input_path, script_path], video_index=1,
                     audio_index=0, subtitle_index=0,
                     generated_script=script_path, input_options=source_opts)


def input_args(plan: InputPlan) -> List[str]:
    args = []
    for index, path in enumerate(plan.inputs):
        args += list(plan.input_options.get(index, []))
        if Path(path).suffix.lower() == ".avs":
            args += ["-f", "avisynth"]
        args += ["-i", path]
    return args


def stream_ref(plan: InputPlan, kind: str, index: str = "0") -> str:
    source = {"v": plan.video_index, "a": plan.audio_index,
              "s": plan.subtitle_index}[kind]
    return f"{source}:{kind}:{index}"


def build_burn_filter(options: EncodeOptions, probe: ProbeInfo):
    """Return a subtitles filter argument for text-subtitle burn-in, or None."""
    burned = [s for s in options.subs
              if s.enabled and s.burn and s.input_index < len(probe.subtitle_tracks)]
    if not burned:
        return None
    sub = burned[0]
    codec = (probe.subtitle_tracks[sub.input_index].get("codec_name") or "").lower()
    if codec in BITMAP_SUB_CODECS:
        return None  # handled by caller as an unsupported case
    return f"subtitles=filename='{escape_filter_arg(options.inputfile)}':si={sub.input_index}"


# --------------------------------------------------------------------------- #
# Video arguments
# --------------------------------------------------------------------------- #


def build_video_args(options: EncodeOptions, probe: ProbeInfo, passno: int = 0,
                     log: Callable[[str], None] = lambda m: None) -> List[str]:
    preset = options.preset
    family = effective_family(options, probe)
    mode = options.mode
    hw = effective_hw(options, probe)
    quality = options.quality
    bitrate = options.bitrate

    def finish(args):
        return _encoder_override_args(args, options.encoder_options)

    if mode == "Copy video" or mode == "Remux (copy all)" or family == "copy":
        return finish(["-c:v", "copy"])

    if hw:
        enc = HW_ENCODERS.get((family, hw))
        if enc and enc in options.available_encoders:
            args = ["-c:v", enc]
            if mode == "Quality (CRF)":
                args += [HW_QUALITY_OPT[hw], str(quality)]
            else:
                args += ["-b:v", f"{bitrate}k"]
            return finish(args)
        if enc:
            log(f"[info] {enc} not available: falling back to software "
                f"{CODECS.get(family, 'encoder')}")

    preset_family = preset.get("family", "x264")
    forced = preset_family in CODECS and family != preset_family
    if "rawargs" in preset and not forced:
        args = list(preset["rawargs"])
        if mode == "Quality (CRF)" and family_supports_quality(family):
            if family in ("x264", "x265", "vp9", "av1"):
                if "-crf" not in args:
                    args += ["-crf", str(quality)]
                if family == "vp9" and "-b:v" not in args:
                    args += ["-b:v", "0"]
            elif family == "x266" and "-qp" not in args:
                args += ["-qp", str(quality)]
            elif family in ("mpeg4", "xvid", "mpeg2", "wmv") and \
                    "-qscale:v" not in args:
                args += ["-qscale:v", str(quality)]
        elif (mode in ("1-pass bitrate", "2-pass bitrate") and
              family_supports_bitrate(family) and "-b:v" not in args
              and "-crf" not in args and "-qscale:v" not in args):
            args += ["-b:v", f"{bitrate}k"]
            if mode == "2-pass bitrate" and family != "av1":
                args += ["-pass", str(passno)]
        return finish(args)

    if mode == "Quality (CRF)":
        encoder = options.video_encoder or preset.get("encoder") or CODECS[family]
        if family in ("x264", "x265"):
            return finish(["-c:v", encoder,
                    "-preset", preset.get("xpreset", "medium"),
                    "-crf", str(quality)])
        if family == "x266":
            return finish(["-c:v", encoder, "-qp", str(quality)])
        if family == "av1":
            return finish(["-c:v", encoder, "-crf", str(quality)])
        if family == "vp9":
            # libvpx-vp9 needs an explicit zero bitrate to enable CRF mode.
            return finish(["-c:v", encoder, "-crf", str(quality),
                           "-b:v", "0"])
        return finish(["-c:v", CODECS[family], "-qscale:v", str(quality)])

    if mode in ("1-pass bitrate", "2-pass bitrate"):
        encoder = options.video_encoder or preset.get("encoder") or CODECS[family]
        if family in ("x264", "x265"):
            args = ["-c:v", encoder,
                    "-preset", preset.get("xpreset", "medium"),
                    "-b:v", f"{bitrate}k"]
            maxr = int(bitrate * 1.25)
            args += ["-maxrate", f"{maxr}k", "-bufsize", f"{maxr * 2}k"]
        else:
            args = ["-c:v", encoder, "-b:v", f"{bitrate}k"]
        if mode == "2-pass bitrate" and family != "av1":
            # SVT-AV1 has no 2-pass mode.
            args += ["-pass", str(passno)]
        return finish(args)
    return finish(["-c:v", "copy"])


# --------------------------------------------------------------------------- #
# Audio arguments
# --------------------------------------------------------------------------- #

AUDIO_ENCODER = {"AAC": "aac", "MP3": "libmp3lame", "FLAC": "flac",
                 "OGG (Vorbis)": "libvorbis", "AC-3": "ac3", "Copy": "copy"}
EXTERNAL_AUDIO_ENCODERS = {"lame": ("MP3", ".mp3"),
                           "faac": ("AAC", ".aac"),
                           "oggenc": ("OGG (Vorbis)", ".ogg")}


def _external_audio_args(row: AudioSelection, output: str) -> List[str]:
    """Build an argv-only command for LAME, FAAC or oggenc."""
    tool = row.encoder.lower()
    opts = row.encoder_options or {}
    raw = opts.get("__raw__", "")
    if raw:
        import shlex
        extra = shlex.split(raw, posix=os.name != "nt")
    else:
        extra = []
    bitrate = str(row.bitrate)
    if tool == "lame":
        return ["lame", "-b", bitrate] + extra + ["-", output]
    if tool == "faac":
        return ["faac", "-b", bitrate, "-o", output] + extra + ["-"]
    if tool == "oggenc":
        return ["oggenc", "-b", bitrate, "-o", output] + extra + ["-"]
    return []


def build_external_audio_jobs(options: EncodeOptions, probe: ProbeInfo,
                              input_plan: InputPlan, binaries=None,
                              output_dir: Optional[str] = None,
                              cleanup_outputs: bool = False):
    """Build external audio encoder jobs and return ``(jobs, files)``.

    ``files`` contains ``(output_audio_index, path)`` entries for the final
    mux. WAV is streamed through an argv-only subprocess pipeline, avoiding
    temporary PCM files and shell quoting problems.
    """
    ffmpeg = binaries.ffmpeg if binaries else "ffmpeg"
    selected = [r for r in options.audio if r.enabled]
    base_dir = output_dir or os.path.dirname(options.inputfile)
    stem = Path(options.outputfile or options.inputfile).stem
    jobs = []
    files = []
    for output_index, row in enumerate(selected):
        tool = (row.encoder or "ffmpeg").lower()
        if tool == "ffmpeg":
            continue
        fmt_ext = EXTERNAL_AUDIO_ENCODERS.get(tool)
        if not fmt_ext:
            continue
        codec, ext = fmt_ext
        out = os.path.join(base_dir, f"{stem}.autoffmpeg_audio{output_index}{ext}")
        external = _external_audio_args(row, out)
        if not external:
            continue
        tool_path = options.audio_tools.get(row.encoder,
                                            options.audio_tools.get(tool, tool))
        external[0] = tool_path
        extract = [ffmpeg, "-hide_banner"] + input_args(input_plan)
        if options.trim_start:
            extract += ["-ss", options.trim_start]
        if options.trim_end:
            extract += ["-to", options.trim_end]
        extract += ["-map", f"{input_plan.audio_index}:a:{row.input_index}",
                    "-vn", "-sn"]
        if row.channels in ("1", "2", "6", "8"):
            extract += ["-ac", row.channels]
        elif tool == "lame" and row.input_index < len(probe.audio_tracks):
            source_channels = probe.audio_tracks[row.input_index].get("channels", 0)
            try:
                if int(source_channels or 0) > 2:
                    extract += ["-ac", "2"]
            except (TypeError, ValueError):
                pass
        if row.sampling != "auto":
            extract += ["-ar", row.sampling]
        extract += ["-f", "wav", "-"]
        jobs.append(EncodeJob(
            f"Audio {output_index} -> {Path(out).name} ({row.encoder})",
            external, probe.duration, is_video=False,
            pipeline=[extract, external],
            cleanup=[out] if cleanup_outputs else []))
        files.append((output_index, out))
    return jobs, files


def compute_loudnorm(raw: str) -> dict:
    """Parse loudnorm JSON measurement and return computed filter values."""
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        input_i = float(data["input_i"])
        input_tp = float(data["input_tp"])
        input_lra = float(data["input_lra"])
        input_thresh = float(data["input_thresh"])
        target_offset = float(data["target_offset"])
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    return {
        "I": f"{input_i + target_offset:.2f}",
        "TP": f"{input_tp + target_offset:.2f}",
        "LRA": f"{input_lra:.2f}",
        "TH": f"{input_thresh:.2f}",
        "OFF": f"{target_offset:.2f}",
    }


def build_audio_plan(options: EncodeOptions, probe: ProbeInfo,
                     binaries=None, input_plan: Optional[InputPlan] = None,
                     external_files=None) -> (
                         List[str], List[str], List[Measure], List[str]):
    """Return (codec_args, filter_complex, measures, audio_maps).

    Audio filters (volume / loudnorm) are emitted through ``-filter_complex``
    with explicit ``[0:a:N]`` input labels instead of ``-af:a:N``, because the
    ``-af`` stream specifier does not index audio streams reliably when a video
    stream is present and would otherwise apply filters to ``copy`` tracks.
    """
    codec_args: List[str] = []
    filter_complex: List[str] = []
    measures: List[Measure] = []
    audio_maps: List[str] = []
    plan = input_plan or InputPlan(inputs=[options.inputfile])
    if options.batch:
        return (["-c:a", "copy"], [], [],
                ["-map", f"{plan.audio_index}:a?"])
    selected = [r for r in options.audio if r.enabled]
    if not selected:
        return (["-an"], [], [], [])

    external_by_output = {
        output_index: path for output_index, path in (external_files or [])}
    external_position = {
        output_index: position
        for position, (output_index, _path) in enumerate(external_files or [])}

    for output_index, row in enumerate(selected):
        codec = row.codec
        if (row.encoder or "ffmpeg").lower() != "ffmpeg":
            # External encoders are materialized by build_external_audio_jobs
            # and muxed as a copied pre-encoded input.
            if output_index in external_by_output:
                source_index = len(plan.inputs) + external_position[output_index]
                audio_maps += ["-map", f"{source_index}:a:0"]
                codec_args += [f"-c:a:{output_index}", "copy"]
            continue
        is_copy = codec == "Copy"
        label = f"a{output_index}"

        af = None
        if not is_copy:
            if options.gain:
                af = f"volume={options.gain}dB"
            elif options.normalize:
                tokens = {
                    f"__LN_I_{output_index}__": "I",
                    f"__LN_TP_{output_index}__": "TP",
                    f"__LN_LRA_{output_index}__": "LRA",
                    f"__LN_TH_{output_index}__": "TH",
                    f"__LN_OFF_{output_index}__": "OFF",
                }
                af = ("loudnorm=I=-16:TP=-1.5:LRA=11"
                      f":measured_I=__LN_I_{output_index}__"
                      f":measured_TP=__LN_TP_{output_index}__"
                      f":measured_LRA=__LN_LRA_{output_index}__"
                      f":measured_thresh=__LN_TH_{output_index}__"
                      f":offset=__LN_OFF_{output_index}__"
                      ":linear=true:print_format=summary")
                measure_cmd = [
                    binaries.ffmpeg if binaries else "ffmpeg",
                    "-hide_banner",
                ] + input_args(plan) + [
                    "-map", f"{plan.audio_index}:a:{row.input_index}",
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
                    "-f", "null", "-",
                ]
                measures.append(Measure(cmd=measure_cmd, tokens=tokens))

        if af:
            filter_complex.append(
                f"[{plan.audio_index}:a:{row.input_index}]{af}[{label}]")
            audio_maps += ["-map", f"[{label}]"]
        else:
            audio_maps += ["-map", f"{plan.audio_index}:a:{row.input_index}"]

        codec_args += [f"-c:a:{output_index}", AUDIO_ENCODER[codec]]
        if codec not in ("Copy", "FLAC"):
            codec_args += [f"-b:a:{output_index}", f"{row.bitrate}k"]
        if not is_copy:
            if row.channels in ("1", "2", "6", "8"):
                codec_args += [f"-ac:a:{output_index}", row.channels]
            if row.sampling != "auto":
                codec_args += [f"-ar:a:{output_index}", row.sampling]

    return codec_args, filter_complex, measures, audio_maps


# --------------------------------------------------------------------------- #
# Stream mapping
# --------------------------------------------------------------------------- #


def build_stream_args(options: EncodeOptions, probe: ProbeInfo,
                      out_is_mp4: bool,
                      input_plan: Optional[InputPlan] = None) -> (
                          List[str], List[str], List[str]):
    """Return (video_maps, sub_maps, sub_args).

    Audio mapping is handled by build_audio_plan so that filtered audio tracks
    can be routed through -filter_complex.
    """
    video_maps = []
    sub_maps = []
    sub_args = []
    plan = input_plan or InputPlan(inputs=[options.inputfile])
    if options.batch:
        if probe.has_video:
            video_maps += ["-map", f"{plan.video_index}:v:0"]
        sub_maps += ["-map", f"{plan.subtitle_index}:s?"]
        sub_args += ["-c:s", "copy"]
        return video_maps, sub_maps, sub_args
    if probe.has_video:
        video_maps += ["-map", f"{plan.video_index}:v:0"]

    burned = {s.input_index for s in options.subs if s.enabled and s.burn}
    selected_subs = [s for s in options.subs if s.enabled and s.input_index not in burned]
    if selected_subs:
        scodec = "mov_text" if out_is_mp4 else "copy"
        for output_index, row in enumerate(selected_subs):
            sub_maps += ["-map", f"{plan.subtitle_index}:s:{row.input_index}"]
            sub_args += [f"-c:s:{output_index}", scodec]
    elif not burned:
        sub_args += ["-sn"]
    return video_maps, sub_maps, sub_args


# --------------------------------------------------------------------------- #
# HDR parts
# --------------------------------------------------------------------------- #


def hdr_parts(options: EncodeOptions, probe: ProbeInfo, family: str,
              bitrate: int, dovi_x265_params: Optional[List[str]] = None) -> dict:
    m = options.hdr_mode
    out = {"pix": None, "opts": [], "vf": [], "note": None, "force": None}
    md = (options.masterdisplay or "").strip() or DEFAULT_MASTER
    cl = (options.maxcll or "").strip() or DEFAULT_CL

    if m == "Auto (match source)":
        if not probe.source_hdr_info:
            return out
        prim, trc, space = probe.source_hdr_info
        out["pix"] = "yuv420p10le"
        out["opts"] += ["-color_primaries", prim, "-color_trc", trc,
                        "-colorspace", space]
        if family == "x265":
            out["opts"] += ["-x265-params",
                            f"colorprim={prim}:transfer={trc}:colormatrix={space}"
                            f":master-display={md}:max-cll={cl}"]
        return out

    if m == "SDR (tone map to BT.709)":
        out["pix"] = "yuv420p"
        out["vf"] = ["format=gbrpf32le,zscale=transfer=linear:npl=100,"
                     "tonemap=hable,zscale=transfer=bt709:primaries=bt709,"
                     "format=yuv420p"]
        out["opts"] += ["-color_primaries", "bt709", "-color_trc", "bt709",
                        "-colorspace", "bt709"]
        return out

    if m in HARD_HDR_MODES:
        trc = "smpte2084" if m != "HLG (BT.2020 / HLG)" else "arib-std-b67"
        out["pix"] = "yuv420p10le"
        out["opts"] += ["-color_primaries", "bt2020", "-color_trc", trc,
                        "-colorspace", "bt2020nc"]
        if family != "x265":
            out["force"] = "x265"
            out["note"] = "HDR requires x265 (10-bit HEVC)."
        if m == "HDR10+ (dynamic metadata)":
            jf = (options.hdr_meta or "").strip()
            if jf and os.path.exists(jf) and os.path.getsize(jf) > 0:
                out["opts"] += ["-x265-params",
                                f"colorprim=bt2020:transfer=smpte2084:"
                                f"colormatrix=bt2020nc:master-display={md}:"
                                f"max-cll={cl}:dhdr10-info='{jf}':dhdr10-opt=1"]
            else:
                out["opts"] += ["-x265-params",
                                f"colorprim=bt2020:transfer=smpte2084:"
                                f"colormatrix=bt2020nc:master-display={md}:"
                                f"max-cll={cl}"]
                out["note"] = ("HDR10+ metadata file missing or empty: "
                               "encoding static HDR10 instead.")
        elif m == "Dolby Vision (source RPU)":
            b = max(bitrate, 1000)
            out["opts"] += ["-maxrate", f"{b}k", "-bufsize", f"{b * 2}k"]
            if dovi_x265_params:
                out["opts"] += ["-x265-params",
                                f"colorprim=bt2020:transfer=smpte2084:"
                                f"colormatrix=bt2020nc:master-display={md}:"
                                f"max-cll={cl}:"
                                + ":".join(dovi_x265_params)]
            else:
                out["opts"] += ["-x265-params",
                                f"colorprim=bt2020:transfer=smpte2084:"
                                f"colormatrix=bt2020nc:master-display={md}:"
                                f"max-cll={cl}"]
                out["note"] = ("Dolby Vision RPU not available: encoding "
                               "static HDR10 instead.")
        else:
            out["opts"] += ["-x265-params",
                            f"colorprim=bt2020:transfer={trc}:"
                            f"colormatrix=bt2020nc:master-display={md}:"
                            f"max-cll={cl}"]
    return out


# --------------------------------------------------------------------------- #
# Dolby Vision (dovi_tool) planning
# --------------------------------------------------------------------------- #


def plan_dovi(options: EncodeOptions, probe: ProbeInfo, binaries=None,
              log: Callable[[str], None] = lambda m: None):
    """Plan RPU extraction / conversion jobs and x265 params, or return None.

    Returns a dict with keys: pre_jobs, cleanup, x265_params.
    """
    empty = {"pre_jobs": [], "cleanup": [], "x265_params": []}
    if options.hdr_mode != "Dolby Vision (source RPU)":
        return empty
    if not probe.source_dv:
        log("[info] Dolby Vision: source has no DV RPU; encoding static HDR10")
        return empty
    dovi = options.dovi_tool
    if not dovi or not os.path.exists(dovi):
        log("[info] Dolby Vision: dovi_tool not found; encoding static HDR10. "
            "Use the FFmpeg tab to install it.")
        return empty

    profile = probe.dv_profile or 8
    ffmpeg = binaries.ffmpeg if binaries else "ffmpeg"
    token = uuid.uuid4().hex[:8]
    tmp = tempfile.gettempdir()
    hevc_path = os.path.join(tmp, f"autoffmpeg_dovi_{token}.hevc")
    rpu_path = os.path.join(tmp, f"autoffmpeg_dovi_{token}.bin")
    cleanup = [hevc_path, rpu_path]
    if options.bluray.enabled:
        source_input = (bluray_input_options(options.bluray) +
                        ["-i", bluray_url(options.bluray)])
    else:
        source_input = ["-i", options.inputfile]

    pre_jobs = [
        EncodeJob("Extract HEVC elementary stream",
                  [ffmpeg, "-y"] + source_input + ["-map", "0:v:0",
                   "-c:v", "copy", "-bsf:v", "hevc_mp4toannexb",
                   "-f", "hevc", hevc_path],
                  duration=0.0, is_video=False),
    ]

    # dovi_tool's conversion modes apply while extracting the RPU; ``convert``
    # itself expects a complete HEVC bitstream, not the binary RPU output.
    # Profiles 5 and 7 must be converted to an 8.1-compatible RPU for an
    # HDR10 base layer. Profile 8 is also signalled as 8.1 for x265.
    extract_cmd = [dovi]
    if profile in (5, 7):
        extract_cmd += ["--mode", "3" if profile == 5 else "2"]
    extract_cmd += ["extract-rpu", hevc_path, "-o", rpu_path]
    pre_jobs.append(EncodeJob(
        "Extract Dolby Vision RPU" +
        (" (convert to 8.1)" if profile in (5, 7) else ""),
        extract_cmd, duration=0.0, is_video=False))

    final_rpu = rpu_path
    final_profile = "8.1" if profile in (5, 7, 8) else str(profile)
    if profile in (5, 7):
        log(f"[info] Dolby Vision profile {profile}: converting RPU to 8.1 "
            "(HDR10 base)")

    x265_params = [f"dolby-vision-rpu={final_rpu}",
                   f"dolby-vision-profile={final_profile}"]
    log(f"[info] Dolby Vision: injecting RPU (profile {final_profile}) via dovi_tool")
    return {"pre_jobs": pre_jobs, "cleanup": cleanup,
            "x265_params": x265_params}


# --------------------------------------------------------------------------- #
# Job assembly
# --------------------------------------------------------------------------- #


def default_output(options: EncodeOptions, probe: ProbeInfo) -> str:
    stem = Path(options.bluray.path if options.bluray.enabled else options.inputfile).stem
    family = effective_family(options, probe)
    if options.mode == "Remux (copy all)":
        container = "mkv"
    elif options.mode == "Audio only":
        container = "mka"
    elif options.container:
        container = options.container.lower().lstrip(".")
    elif family in ("x264", "x265"):
        container = "mp4"
    elif family in ("x266", "vp9", "av1", "ffv1", "dnxhd"):
        container = "mkv"
    elif family == "prores":
        container = "mov"
    else:
        container = "avi"
    return os.path.join(os.path.dirname(options.inputfile),
                        "autoffmpeg_" + stem + "." + container)


def resolve_outputfile(options: EncodeOptions, probe: ProbeInfo) -> str:
    """Resolve the user-selected base name and container to one final path."""
    if not options.output_base and not options.outputfile:
        return default_output(options, probe)
    if options.output_base:
        base = options.output_base
    else:
        current = Path(options.outputfile)
        base = str(current.with_suffix("")) if current.suffix else str(current)
    container = options.container.lower().lstrip(".") if options.container else ""
    if not container and Path(options.outputfile).suffix:
        container = Path(options.outputfile).suffix.lstrip(".").lower()
    if not container:
        container = "mkv"
    return base + "." + container


def normalize_output(options: EncodeOptions, probe: ProbeInfo) -> str:
    options.outputfile = resolve_outputfile(options, probe)
    if not options.output_base:
        options.output_base = str(Path(options.outputfile).with_suffix(""))
    return options.outputfile


def _video_core(options: EncodeOptions, probe: ProbeInfo, binaries, family,
                hw, vf, passlog, hdr, video_args,
                input_plan: Optional[InputPlan] = None,
                extra_inputs: Optional[List[str]] = None) -> List[str]:
    """Common video-encoding prefix shared by muxed and raw outputs."""
    cmd = [binaries.ffmpeg if binaries else "ffmpeg", "-y",
           "-progress", "pipe:1", "-nostats"]
    init = HW_INIT.get(hw, []) if hw else []
    if init:
        cmd += init
    if hw == "vaapi":
        cmd += ["-vaapi_device", detect_vaapi_device()]
    cmd += input_args(input_plan or InputPlan(inputs=[options.inputfile]))
    for path in extra_inputs or []:
        cmd += ["-i", path]
    if options.trim_start:
        cmd += ["-ss", options.trim_start]
    if options.trim_end:
        cmd += ["-to", options.trim_end]

    all_vf = list(vf)
    if hw in ("vaapi", "qsv") and "hwupload" not in ",".join(all_vf):
        all_vf.append("format=nv12,hwupload")
    if all_vf:
        cmd += ["-vf", ",".join(all_vf)]
    if options.framerate != "automatic":
        cmd += ["-r", options.framerate]
    if options.vframes:
        cmd += ["-frames:v", options.vframes]
    cmd += video_args
    if hdr["opts"]:
        cmd += hdr["opts"]
    if passlog:
        cmd += ["-passlogfile", passlog]
    has_pix = any(a == "-pix_fmt" for a in video_args)
    pix = hdr["pix"]
    if not pix and not hw and not has_pix and \
            family in ("x264", "x265", "x266", "vp9", "av1"):
        pix = "yuv420p"
    if pix:
        cmd += ["-pix_fmt", pix]
    return cmd


def _base_cmd(options: EncodeOptions, probe: ProbeInfo, binaries,
              family, hw, mode, vf, passlog, hdr, video_args, audio_args,
              filter_complex, maps, sub_args, out_is_mp4,
              input_plan: Optional[InputPlan] = None,
              extra_inputs: Optional[List[str]] = None) -> List[str]:
    cmd = _video_core(options, probe, binaries, family, hw, vf, passlog,
                      hdr, video_args, input_plan, extra_inputs)
    if family == "x265" and out_is_mp4:
        cmd += ["-tag:v", "hvc1"]
    if filter_complex:
        cmd += ["-filter_complex", ";".join(filter_complex)]
    cmd += audio_args + sub_args + maps
    if out_is_mp4 and family != "copy":
        cmd += ["-movflags", "+faststart"]
    if options.keep_metadata:
        cmd += ["-map_metadata", "0"]
    if options.keep_chapters:
        cmd += ["-map_chapters", "0"]
    cmd += ["-threads", "0", "-y", options.outputfile]
    return cmd


def build_elementary_jobs(options: EncodeOptions, probe: ProbeInfo,
                          binaries=None, available_encoders: Optional[set] = None,
                          log: Callable[[str], None] = lambda m: None) -> List[EncodeJob]:
    """Build per-stream jobs (video/audio/subtitle) without muxing them."""
    if not source_exists(options):
        return []
    if available_encoders is not None:
        options.available_encoders = available_encoders
    ffmpeg = binaries.ffmpeg if binaries else "ffmpeg"
    input_plan = build_input_plan(options, probe)
    script_cleanup = ([input_plan.generated_script]
                      if input_plan.generated_script and
                      not options.avisynth.keep_generated_script else [])
    base_dir = os.path.dirname(options.outputfile or options.inputfile)
    stem = Path(options.outputfile or options.inputfile).stem
    jobs: List[EncodeJob] = []

    family = effective_family(options, probe)
    mode = options.mode
    hw = effective_hw(options, probe)
    bitrate = options.bitrate

    # --- video elementary stream ---
    if not probe.has_video:
        log("[info] no video stream; skipping video extraction")
    elif family == "copy" or mode == "Copy video":
        log("[info] copy video is not supported in elementary mode; "
            "re-encode or use Remux")
    else:
        vfmt, vext = VIDEO_RAW_FORMATS.get(family, ("matroska", ".mkv"))
        vout = os.path.join(base_dir, f"{stem}_video{vext}")
        dovi = plan_dovi(options, probe, binaries, log)
        hdr = hdr_parts(options, probe, family, bitrate, dovi["x265_params"])
        if hdr.get("note"):
            log(f"[info] HDR: {hdr['note']}")
        vf = build_filter_args(options, probe) + hdr["vf"]
        burn = build_burn_filter(options, probe)
        if burn:
            vf.append(burn)
        passlog = (os.path.join(tempfile.gettempdir(), "autoffmpeg2pass")
                   if mode == "2-pass bitrate" else None)
        cleanup = list(dovi["cleanup"])
        cleanup += script_cleanup
        if passlog:
            cleanup += [passlog + "-0.log", passlog + "-0.log.mbtree"]

        def vcmd(video_args):
            core = _video_core(options, probe, binaries, family, hw, vf,
                               passlog, hdr, video_args, input_plan)
            return core + ["-an", "-sn", "-f", vfmt, "-threads", "0",
                           "-y", vout]

        jobs = list(dovi["pre_jobs"])
        if mode == "2-pass bitrate":
            jobs.append(EncodeJob(
                f"Pass 1 -> {Path(vout).name}",
                vcmd(build_video_args(options, probe, 1, log)),
                probe.duration))
            jobs.append(EncodeJob(
                f"Pass 2 -> {Path(vout).name}",
                vcmd(build_video_args(options, probe, 2, log)),
                probe.duration, cleanup=cleanup))
        else:
            jobs.append(EncodeJob(
                f"Video -> {Path(vout).name}",
                vcmd(build_video_args(options, probe, 0, log)),
                probe.duration, cleanup=cleanup))

    external_jobs, _ = build_external_audio_jobs(
        options, probe, input_plan, binaries, output_dir=base_dir,
        cleanup_outputs=False)
    jobs.extend(external_jobs)

    # --- audio elementary streams ---
    for i, row in enumerate([r for r in options.audio if r.enabled]):
        if (row.encoder or "ffmpeg").lower() != "ffmpeg":
            continue
        codec = row.codec
        if codec == "Copy":
            src_codec = ""
            if row.input_index < len(probe.audio_tracks):
                src_codec = (probe.audio_tracks[row.input_index]
                             .get("codec_name", "") or "").lower()
            fmt, ext = SOURCE_AUDIO_FORMATS.get(src_codec, (None, None))
            if fmt is None:
                log(f"[info] audio {i}: cannot extract codec '{src_codec}'; "
                    "skipping")
                continue
            aargs = ["-c:a", "copy"]
        else:
            fmt, ext = AUDIO_RAW_FORMATS.get(codec, (None, None))
            if fmt is None:
                log(f"[info] audio {i}: unsupported codec '{codec}'; skipping")
                continue
            aargs = ["-c:a", AUDIO_ENCODER[codec]]
            if codec != "FLAC":
                aargs += ["-b:a", f"{row.bitrate}k"]
            if row.channels in ("1", "2", "6", "8"):
                aargs += ["-ac", row.channels]
            if row.sampling != "auto":
                aargs += ["-ar", row.sampling]

        aout = os.path.join(base_dir, f"{stem}_audio{i}{ext}")
        cmd = [ffmpeg, "-y", "-progress", "pipe:1", "-nostats"]
        cmd += input_args(input_plan)
        if options.trim_start:
            cmd += ["-ss", options.trim_start]
        if options.trim_end:
            cmd += ["-to", options.trim_end]
        cmd += ["-map", f"{input_plan.audio_index}:a:{row.input_index}"] + aargs
        measures: List[Measure] = []
        if codec != "Copy":
            if options.gain:
                cmd += ["-af", f"volume={options.gain}dB"]
            elif options.normalize:
                tokens = {
                    "__LN_I_0__": "I", "__LN_TP_0__": "TP",
                    "__LN_LRA_0__": "LRA", "__LN_TH_0__": "TH",
                    "__LN_OFF_0__": "OFF",
                }
                filt = ("loudnorm=I=-16:TP=-1.5:LRA=11"
                        ":measured_I=__LN_I_0__:measured_TP=__LN_TP_0__"
                        ":measured_LRA=__LN_LRA_0__"
                        ":measured_thresh=__LN_TH_0__"
                        ":offset=__LN_OFF_0__:linear=true:print_format=summary")
                cmd += ["-af", filt]
                measures.append(Measure(
                    cmd=[ffmpeg, "-hide_banner"] + input_args(input_plan) + [
                         "-map", f"{input_plan.audio_index}:a:{row.input_index}",
                         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:"
                                "print_format=json",
                         "-f", "null", "-"],
                    tokens=tokens))
        cmd += ["-f", fmt, "-threads", "0", "-y", aout]
        jobs.append(EncodeJob(f"Audio {i} -> {Path(aout).name}", cmd,
                              probe.duration, measures=measures,
                              is_video=False))

    # --- subtitle elementary streams ---
    for i, s in enumerate([s for s in options.subs if s.enabled]):
        if s.burn:
            continue
        src = {}
        if s.input_index < len(probe.subtitle_tracks):
            src = probe.subtitle_tracks[s.input_index]
        codec = (src.get("codec_name") or "").lower()
        if codec in TEXT_SUB_FORMATS:
            fmt, ext, sub_enc = TEXT_SUB_FORMATS[codec]
            sargs = ["-c:s", sub_enc]
        elif codec == "hdmv_pgs_subtitle":
            fmt, ext, sargs = "sup", ".sup", ["-c:s", "copy"]
        else:
            log(f"[info] subtitle {i}: cannot extract codec '{codec}'; skipping")
            continue
        sout = os.path.join(base_dir, f"{stem}_sub{i}{ext}")
        cmd = [ffmpeg, "-y", "-progress", "pipe:1", "-nostats"]
        cmd += input_args(input_plan) + [
               "-map", f"{input_plan.subtitle_index}:s:{s.input_index}",
               "-vn", "-an"] + sargs + ["-f", fmt, "-y", sout]
        jobs.append(EncodeJob(f"Subtitle {i} -> {Path(sout).name}", cmd,
                              is_video=False))
    return jobs


def _build_direct_jobs(options: EncodeOptions, probe: ProbeInfo, binaries=None,
                       available_encoders: Optional[set] = None,
                       log: Callable[[str], None] = lambda m: None) -> List[EncodeJob]:
    if not source_exists(options):
        return []
    if options.nomux:
        return build_elementary_jobs(options, probe, binaries,
                                     available_encoders, log)
    if not options.outputfile:
        options.outputfile = default_output(options, probe)
    if available_encoders is not None:
        options.available_encoders = available_encoders

    ffmpeg = binaries.ffmpeg if binaries else "ffmpeg"
    input_plan = build_input_plan(options, probe)
    script_cleanup = ([input_plan.generated_script]
                      if input_plan.generated_script and
                      not options.avisynth.keep_generated_script else [])

    # --- Remux (copy all streams) ---
    if options.mode == "Remux (copy all)":
        if avisynth_active(options):
            log("[warning] Remux is not compatible with AviSynth processing; "
                "choose an encoding mode instead.")
            return []
        out_is_mp4 = Path(options.outputfile).suffix.lower() == ".mp4"
        cmd = [ffmpeg, "-y", "-progress", "pipe:1", "-nostats",
               ] + input_args(input_plan) + ["-map", "0", "-c", "copy"]
        if out_is_mp4:
            cmd += ["-movflags", "+faststart"]
        cmd += ["-y", options.outputfile]
        return [EncodeJob(f"Remux -> {Path(options.outputfile).name}",
                          cmd, probe.duration)]

    # --- Audio only ---
    if options.mode == "Audio only":
        external_jobs, external_files = build_external_audio_jobs(
            options, probe, input_plan, binaries,
            output_dir=os.path.dirname(options.outputfile),
            cleanup_outputs=False)
        aargs, filter_complex, measures, audio_maps = build_audio_plan(
            options, probe, binaries, input_plan, external_files)
        extra_inputs = [path for _, path in external_files]
        cmd = [ffmpeg, "-y", "-progress", "pipe:1", "-nostats",
               ] + input_args(input_plan)
        for path in extra_inputs:
            cmd += ["-i", path]
        cmd += ["-vn"]
        if options.trim_start:
            cmd += ["-ss", options.trim_start]
        if options.trim_end:
            cmd += ["-to", options.trim_end]
        if filter_complex:
            cmd += ["-filter_complex", ";".join(filter_complex)]
        cmd += aargs
        cmd += audio_maps
        cmd += ["-sn"]
        cmd += ["-y", options.outputfile]
        cleanup = script_cleanup + extra_inputs
        return external_jobs + [EncodeJob(f"Audio -> {Path(options.outputfile).name}",
                          cmd, probe.duration, measures=measures,
                          cleanup=cleanup, is_video=False)]

    family0 = options.preset.get("family", "x264")
    family = effective_family(options, probe)
    mode = options.mode
    rawargs = options.preset.get("rawargs", [])
    if "-crf" in rawargs or "-qscale:v" in rawargs:
        mode = "Quality (CRF)"
    if "rawargs" in options.preset and not family_supports_bitrate(family) and \
            mode in ("1-pass bitrate", "2-pass bitrate"):
        log(f"[info] {family} profile: bitrate mode uses profile settings")
        mode = "Quality (CRF)"
    hw = effective_hw(options, probe)
    bitrate = options.bitrate

    if hw and hdr_active(options, probe):
        log("[info] HDR is not supported with hardware encoders: using software x265")
    if hw and family in ("x264", "x265") and mode == "2-pass bitrate":
        mode = "1-pass bitrate"
        log("[info] hardware encoders: 2-pass not supported, using 1-pass")
    if hdr_active(options, probe) and family != family0:
        log(f"[info] HDR requires 10-bit: switched encoder to {CODECS[family]}")

    dovi = plan_dovi(options, probe, binaries, log)
    hdr = hdr_parts(options, probe, family, bitrate, dovi["x265_params"])
    if hdr.get("note"):
        log(f"[info] HDR: {hdr['note']}")

    burn_filter = build_burn_filter(options, probe)
    if burn_filter is None and any(s.enabled and s.burn for s in options.subs):
        log("[info] burn-in of bitmap subtitles is not supported; "
            "select a text subtitle track")

    vf = build_filter_args(options, probe) + hdr["vf"]
    if burn_filter:
        vf.append(burn_filter)

    external_jobs, external_files = build_external_audio_jobs(
        options, probe, input_plan, binaries,
        output_dir=os.path.dirname(options.outputfile), cleanup_outputs=False)
    aargs, filter_complex, measures, audio_maps = build_audio_plan(
        options, probe, binaries, input_plan, external_files)
    extra_inputs = [path for _, path in external_files]
    out_is_mp4 = Path(options.outputfile).suffix.lower() == ".mp4"
    passlog = (os.path.join(tempfile.gettempdir(), "autoffmpeg2pass")
               if mode == "2-pass bitrate" else None)
    video_maps, sub_maps, sub_args = build_stream_args(
        options, probe, out_is_mp4, input_plan)
    maps = video_maps + audio_maps + sub_maps

    def base(video_args, audio_args):
        return _base_cmd(options, probe, binaries, family, hw, mode, vf,
                         passlog, hdr, video_args, audio_args, filter_complex,
                         maps, sub_args, out_is_mp4, input_plan, extra_inputs)

    jobs = list(dovi["pre_jobs"])
    jobs += external_jobs
    cleanup = list(dovi["cleanup"])
    cleanup += script_cleanup
    cleanup += extra_inputs
    if passlog:
        cleanup += [passlog + "-0.log", passlog + "-0.log.mbtree"]

    if mode == "2-pass bitrate":
        p1 = base(build_video_args(options, probe, 1, log), ["-an"])
        p2 = base(build_video_args(options, probe, 2, log), aargs)
        jobs.append(EncodeJob(
            f"Pass 1 -> {Path(options.outputfile).name}", p1, probe.duration,
            cleanup=[]))
        jobs.append(EncodeJob(
            f"Pass 2 -> {Path(options.outputfile).name}", p2, probe.duration,
            measures=measures, cleanup=cleanup))
    else:
        jobs.append(EncodeJob(
            f"Encode -> {Path(options.outputfile).name}",
            base(build_video_args(options, probe, 0, log), aargs),
            probe.duration, measures=measures, cleanup=cleanup))
    return jobs


def elementary_track_paths(options: EncodeOptions, probe: ProbeInfo) -> List[str]:
    """Return the raw track paths produced for an MKV encode."""
    base_dir = os.path.dirname(options.outputfile or options.inputfile)
    stem = Path(options.outputfile or options.inputfile).stem
    family = effective_family(options, probe)
    paths = []
    if probe.has_video and family != "copy" and options.mode != "Copy video":
        _fmt, ext = VIDEO_RAW_FORMATS.get(family, ("matroska", ".mkv"))
        paths.append(os.path.join(base_dir, f"{stem}_video{ext}"))
    selected = [row for row in options.audio if row.enabled]
    for output_index, row in enumerate(selected):
        tool = (row.encoder or "ffmpeg").lower()
        if tool != "ffmpeg":
            ext = EXTERNAL_AUDIO_ENCODERS.get(tool, ("", ""))[1]
        elif row.codec == "Copy":
            src = probe.audio_tracks[row.input_index] \
                if row.input_index < len(probe.audio_tracks) else {}
            ext = SOURCE_AUDIO_FORMATS.get(
                (src.get("codec_name") or "").lower(), ("", ""))[1]
        else:
            ext = AUDIO_RAW_FORMATS.get(row.codec, ("", ""))[1]
        if ext:
            if tool != "ffmpeg":
                name = f"{stem}.autoffmpeg_audio{output_index}{ext}"
            else:
                name = f"{stem}_audio{output_index}{ext}"
            paths.append(os.path.join(base_dir, name))
    for output_index, row in enumerate([s for s in options.subs if s.enabled]):
        if row.burn:
            continue
        src = probe.subtitle_tracks[row.input_index] \
            if row.input_index < len(probe.subtitle_tracks) else {}
        codec = (src.get("codec_name") or "").lower()
        if codec in TEXT_SUB_FORMATS:
            ext = TEXT_SUB_FORMATS[codec][1]
        elif codec == "hdmv_pgs_subtitle":
            ext = ".sup"
        else:
            continue
        paths.append(os.path.join(base_dir, f"{stem}_sub{output_index}{ext}"))
    return paths


def build_mkv_encode_jobs(options: EncodeOptions, probe: ProbeInfo,
                          binaries=None,
                          available_encoders: Optional[set] = None,
                          log: Callable[[str], None] = lambda m: None) -> List[EncodeJob]:
    """Encode elementary streams, then mux them into the selected MKV."""
    raw_jobs = build_elementary_jobs(options, probe, binaries,
                                     available_encoders, log)
    if not raw_jobs:
        return []
    produced = set()
    for job in raw_jobs:
        produced.update(job.cmd)
        for command in job.pipeline:
            produced.update(command)
    tracks = [{"path": path} for path in elementary_track_paths(options, probe)
              if path in produced]
    if not tracks:
        return raw_jobs
    if binaries and binaries.has("mkvmerge"):
        cmd = build_mkvmerge_command(tracks, options.outputfile,
                                     binaries.mkvmerge)
        tool = "mkvmerge"
    else:
        cmd = build_ffmpeg_mux_command(tracks, options.outputfile,
                                       binaries.ffmpeg if binaries else "ffmpeg")
        tool = "ffmpeg"
    cleanup = [track["path"] for track in tracks]
    raw_jobs.append(EncodeJob(
        f"Mux -> {Path(options.outputfile).name} ({tool})", cmd,
        probe.duration, cleanup=cleanup, is_video=False))
    return raw_jobs


def build_jobs(options: EncodeOptions, probe: ProbeInfo, binaries=None,
               available_encoders: Optional[set] = None,
               log: Callable[[str], None] = lambda m: None) -> List[EncodeJob]:
    normalize_output(options, probe)
    if (Path(options.outputfile).suffix.lower() == ".mkv" and
            options.mode not in ("Remux (copy all)", "Audio only",
                                 "Copy video") and
            effective_family(options, probe) != "copy" and not options.nomux):
        return build_mkv_encode_jobs(options, probe, binaries,
                                     available_encoders, log)
    return _build_direct_jobs(options, probe, binaries, available_encoders, log)


# --------------------------------------------------------------------------- #
# Bitrate calculator
# --------------------------------------------------------------------------- #


def calc_bitrate_mb(target_mb: float, duration: float,
                    audio_kbps: float) -> int:
    if duration <= 0:
        return 0
    video_kbps = (target_mb * 8192 / duration) * 0.95 - audio_kbps
    return max(64, int(video_kbps))


# --------------------------------------------------------------------------- #
# Preview / crop helpers (pure)
# --------------------------------------------------------------------------- #


def round_by(base, factor):
    return int(base / factor + 0.5) * factor


def cropdetect_command(ffmpeg, inputfile, duration, frames=120, limit=24):
    skip = (min(3.0, max(0.0, duration * 0.2)) if duration > 0 else 2.0)
    cmd = [ffmpeg]
    if skip > 0:
        cmd += ["-ss", f"{skip:.2f}"]
    cmd += ["-i", inputfile, "-vf", f"cropdetect=limit={limit}:round=2",
            "-frames:v", str(frames), "-f", "null", "-"]
    return cmd


def parse_cropdetect(raw: str):
    matches = re.findall(r"crop=(-?\d+):(-?\d+):(-?\d+):(-?\d+)", raw)
    return tuple(map(int, matches[-1])) if matches else None


def extract_frames_command(ffmpeg, inputfile, outdir, count=6):
    stem = Path(inputfile).stem
    return [ffmpeg, "-y", "-i", inputfile,
            "-vf", f"fps=1/{max(1, count)}",
            os.path.join(outdir, f"{stem}_thumb_%02d.jpg")]


# --------------------------------------------------------------------------- #
# Muxing (mkvmerge / ffmpeg)
# --------------------------------------------------------------------------- #


def build_mkvmerge_command(tracks, output, binary="mkvmerge") -> List[str]:
    """Build an `mkvmerge` command from a list of track dicts.

    Each track dict: {path, kind, language, forced, default, delay_ms}.
    """
    cmd = [binary, "-o", output]
    for t in tracks:
        opts = []
        if t.get("language"):
            opts += ["--language", f"0:{t['language']}"]
        if t.get("default"):
            opts += ["--default-track", "0:yes"]
        if t.get("forced"):
            opts += ["--forced-track", "0:yes"]
        if t.get("delay_ms"):
            opts += ["--sync", f"0:{int(t['delay_ms'])}"]
        cmd += opts + [t["path"]]
    return cmd


def build_ffmpeg_mux_command(tracks, output, binary="ffmpeg") -> List[str]:
    """Build an `ffmpeg -c copy` mux command from a list of track dicts."""
    cmd = [binary, "-y", "-hide_banner"]
    for t in tracks:
        delay = t.get("delay_ms")
        if delay:
            cmd += ["-itsoffset", f"{delay / 1000.0:.3f}"]
        cmd += ["-i", t["path"]]
    for i, t in enumerate(tracks):
        cmd += ["-map", f"{i}:0"]
    for i, t in enumerate(tracks):
        if t.get("language"):
            cmd += [f"-metadata:s:{i}", f"language={t['language']}"]
        disp = []
        if t.get("default"):
            disp.append("default")
        if t.get("forced"):
            disp.append("forced")
        if disp:
            cmd += [f"-disposition:{i}", "+".join(disp)]
    cmd += ["-c", "copy", "-y", output]
    return cmd


# --------------------------------------------------------------------------- #
# Queue serialization
# --------------------------------------------------------------------------- #


def job_to_dict(job: EncodeJob) -> dict:
    return {
        "schema": 2,
        "label": job.label,
        "cmd": list(job.cmd),
        "duration": job.duration,
        "measures": [{"cmd": list(m.cmd), "tokens": dict(m.tokens)}
                     for m in job.measures],
        "cleanup": list(job.cleanup),
        "is_video": job.is_video,
        "pipeline": [list(cmd) for cmd in job.pipeline],
    }


def job_from_dict(data: dict) -> EncodeJob:
    return EncodeJob(
        label=data.get("label", "Encode"),
        cmd=list(data.get("cmd", [])),
        duration=float(data.get("duration", 0.0) or 0.0),
        measures=[Measure(cmd=list(m.get("cmd", [])),
                          tokens=dict(m.get("tokens", {})))
                  for m in data.get("measures", [])],
        cleanup=list(data.get("cleanup", [])),
        is_video=bool(data.get("is_video", True)),
        pipeline=[list(cmd) for cmd in data.get("pipeline", [])],
    )
