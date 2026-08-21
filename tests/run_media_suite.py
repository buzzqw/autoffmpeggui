# -*- coding: utf-8 -*-
"""Run the real multitrack encode matrix and write a reproducible report.

Run from the repository root with::

    python3 tests/run_media_suite.py

Use ``--limit N`` while developing the application. Every executed case writes
an actual output file in a temporary directory, probes it, and records the
command, return codes, size and resulting streams in ``test_reports/``.
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from autoffmpeg.config import Binaries
from autoffmpeg.core import (AudioSelection, AvisynthOptions, EncodeOptions,
                             ProbeInfo, SubtitleSelection, build_avisynth_script,
                             build_jobs)
from autoffmpeg.workers import EncodeThread


REPORT_DIR = ROOT / "test_reports"
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def ffmpeg_encoders():
    if not FFMPEG:
        return set()
    proc = subprocess.run([FFMPEG, "-hide_banner", "-encoders"],
                          capture_output=True, text=True, check=False)
    return {line.split()[1] for line in proc.stdout.splitlines()
            if len(line.split()) >= 2 and len(line.split()[0]) == 6
            and line.split()[0][0] in "VAS"}


def probe(path):
    if not FFPROBE or not Path(path).exists():
        return {"error": "ffprobe or output missing"}
    proc = subprocess.run(
        [FFPROBE, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=False)
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        data = {"error": (proc.stderr or proc.stdout)[-2000:]}
    if proc.returncode:
        data["probe_error"] = (proc.stderr or "")[-2000:]
    return data


def stream_summary(data):
    return [{key: stream.get(key) for key in (
        "index", "codec_type", "codec_name", "width", "height",
        "channels", "duration") if key in stream}
            for stream in data.get("streams", [])]


def video_cases(encoders):
    cases = [
        {"name": "x264", "preset": {"family": "x264", "xpreset": "ultrafast"},
         "expected": "h264", "options": {"crf": "28"},
         "required": "libx264"},
        {"name": "x265", "preset": {"family": "x265", "xpreset": "ultrafast"},
         "expected": "hevc", "options": {"crf": "30"},
         "required": "libx265"},
        {"name": "av1", "preset": {"family": "av1", "encoder": "libsvtav1"},
         "expected": "av1", "options": {"preset": "12", "crf": "35"},
         "required": "libsvtav1"},
    ]
    vvc = next((name for name in ("libvvenc", "libx266") if name in encoders), None)
    cases.append({"name": "x266", "preset": {"family": "x266", "encoder": vvc or "libvvenc"},
                  "expected": "vvc", "options": {"qp": "35"},
                  "required": vvc or "libvvenc"})
    return cases


def audio_cases(tools):
    cases = [
        ("aac_ffmpeg", [AudioSelection(0, codec="AAC", bitrate=96)], "aac", {}),
        ("mp3_ffmpeg", [AudioSelection(0, codec="MP3", bitrate=96)], "mp3", {}),
        ("flac_ffmpeg", [AudioSelection(2, codec="FLAC")], "flac", {}),
        ("vorbis_ffmpeg", [AudioSelection(3, codec="OGG (Vorbis)", bitrate=96)],
         "vorbis", {}),
        ("ac3_ffmpeg", [AudioSelection(0, codec="AC-3", bitrate=192)], "ac3", {}),
        ("copy_ac3", [AudioSelection(0, codec="Copy")], "ac3", {}),
        ("copy_eac3", [AudioSelection(3, codec="Copy")], "eac3", {}),
    ]
    if tools.get("lame"):
        cases.append(("lame_mp3", [AudioSelection(
            0, codec="MP3", encoder="lame", bitrate=96)], "mp3",
                          {"lame": tools["lame"]}))
    if tools.get("faac"):
        cases.append(("faac_aac", [AudioSelection(
            0, codec="AAC", encoder="faac", bitrate=96, channels="2")], "aac",
                          {"faac": tools["faac"]}))
    if tools.get("oggenc"):
        cases.append(("oggenc_vorbis", [AudioSelection(
            3, codec="OGG (Vorbis)", encoder="oggenc", bitrate=96,
            channels="2")], "vorbis", {"oggenc": tools["oggenc"]}))
    cases += [
        ("mixed_ffmpeg", [
            AudioSelection(0, codec="AAC", bitrate=96),
            AudioSelection(1, codec="MP3", bitrate=96),
            AudioSelection(2, codec="Copy")], "mixed", {}),
    ]
    if tools.get("lame") and tools.get("faac") and tools.get("oggenc"):
        cases.append(("mixed_external", [
            AudioSelection(0, codec="MP3", encoder="lame", bitrate=96),
            AudioSelection(1, codec="AAC", encoder="faac", bitrate=96,
                           channels="2"),
            AudioSelection(2, codec="OGG (Vorbis)", encoder="oggenc",
                           bitrate=96, channels="2")], "mixed", {
                               "lame": tools["lame"],
                               "faac": tools["faac"],
                               "oggenc": tools["oggenc"]}))
    return cases


def subtitle_cases():
    return [
        ("no_subtitles", [], 0, False),
        ("embedded_two", [SubtitleSelection(0), SubtitleSelection(1)], 2, False),
        ("embedded_all", [SubtitleSelection(0), SubtitleSelection(1),
                           SubtitleSelection(2)], 3, False),
        ("burn_italian", [SubtitleSelection(0, burn=True)], 0, True),
    ]


def run_worker_jobs(jobs):
    codes = []
    logs = []
    for job in jobs:
        worker = EncodeThread([job])
        worker.job_done.connect(lambda _index, code: codes.append(code))
        worker.log_line.connect(logs.append)
        worker.run()
    return codes, logs


def run_case(case, source, probe_info, binaries, avs_mode):
    with tempfile.TemporaryDirectory(prefix="autoffmpeg_matrix_") as td:
        input_path = Path(td) / "source.mkv"
        shutil.copyfile(source, input_path)
        output = Path(td) / f"{case['name']}.mkv"
        avs = AvisynthOptions(enabled=avs_mode)
        if avs_mode:
            avs.plugin_paths = ["/usr/lib/avisynth/libffms2.so"]
        options = EncodeOptions(
            inputfile=str(input_path), outputfile=str(output),
            preset=case["video"]["preset"], encoder_options=case["video"]["options"],
            quality=30, bitrate=1200, width=320, height=180, trim_end="1",
            audio=case["audio"][1], subs=case["subs"][1], avisynth=avs,
            audio_tools=case["audio"][3], gain=3 if case["audio"][0] == "mixed_ffmpeg" else 0)
        probe_info = ProbeInfo(
            has_video=True, duration=1, vwidth=1920, vheight=1080,
            audio_tracks=[{"codec_name": "ac3", "channels": 6},
                          {"codec_name": "mp2", "channels": 2},
                          {"codec_name": "eac3", "channels": 6},
                          {"codec_name": "eac3", "channels": 2}],
            subtitle_tracks=[{"codec_name": "subrip"},
                             {"codec_name": "subrip"},
                             {"codec_name": "subrip"}])
        if avs_mode:
            probe_info.source_hdr_info = None
        jobs = build_jobs(options, probe_info, binaries)
        codes, logs = run_worker_jobs(jobs)
        data = probe(output)
        streams = stream_summary(data)
        video = [s for s in streams if s.get("codec_type") == "video"]
        audios = [s for s in streams if s.get("codec_type") == "audio"]
        subtitles = [s for s in streams if s.get("codec_type") == "subtitle"]
        expected_subs = case["subs"][2]
        passed = (bool(codes) and all(code == 0 for code in codes) and
                  output.exists() and output.stat().st_size > 0 and
                  video and audios and
                  video[0].get("codec_name") == case["video"]["expected"] and
                  (case["audio"][2] == "mixed" or
                   audios[0].get("codec_name") == case["audio"][2]) and
                  len(subtitles) == expected_subs)
        return {
            "name": case["name"],
            "video": case["video"]["name"],
            "audio": case["audio"][0],
            "subtitles": case["subs"][0],
            "avisynth": avs_mode,
            "commands": [
                [shlex.join(part) for part in job.pipeline]
                if job.pipeline else shlex.join(job.cmd) for job in jobs],
            "job_codes": codes,
            "output_exists": output.exists(),
            "output_size": output.stat().st_size if output.exists() else 0,
            "streams": streams,
            "expected_subtitles": expected_subs,
            "passed": passed,
            "log_tail": logs[-20:],
        }


def write_report(report):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORT_DIR / "multitrack_media_report.json"
    md_path = REPORT_DIR / "multitrack_media_report.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True),
                         encoding="utf-8")
    lines = ["# AutoFFmpeg Media Matrix Report", "",
             f"- Source: `{report['source']}`",
             f"- Cases: {report['summary']['total']}",
             f"- Passed: {report['summary']['passed']}",
             f"- Failed: {report['summary']['failed']}",
             f"- Runtime: {report['elapsed_seconds']:.1f} seconds",
             f"- Skipped capabilities: {', '.join(report['skipped_capabilities']) or 'none'}",
             "", "| Case | Video | Audio | Subs | AviSynth | Size | Status |",
             "|---|---|---|---:|---|---:|---|"]
    for result in report["results"]:
        lines.append("| {name} | {video} | {audio} | {subs} | {avs} | {size} | {status} |".format(
            name=result["name"], video=result["video"], audio=result["audio"],
            subs=result["subtitles"], avs="yes" if result["avisynth"] else "no",
            size=result["output_size"], status="PASS" if result["passed"] else "FAIL"))
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def run_suite(limit=None, include_avisynth=True):
    if not FFMPEG or not FFPROBE:
        raise RuntimeError("ffmpeg and ffprobe are required")
    source = ROOT / "test_multitrack.mkv"
    started = time.monotonic()
    encoders = ffmpeg_encoders()
    tools = {name: shutil.which(name) for name in ("lame", "faac", "oggenc")}
    available_video = [case for case in video_cases(encoders)
                       if case["required"] in encoders]
    skipped = [f"{case['name']} ({case['required']})"
               for case in video_cases(encoders) if case["required"] not in encoders]
    avs_ready = (Path("/usr/lib/avisynth/libffms2.so").exists() and
                 Path("/usr/lib/libIL.so.1").exists())
    if include_avisynth and not avs_ready:
        skipped.append("AviSynth+ (runtime/plugin unavailable)")
        include_avisynth = False
    cases = []
    for video in available_video:
        for audio in audio_cases(tools):
            for subtitles in subtitle_cases():
                for avs_mode in ((False, True) if include_avisynth else (False,)):
                    cases.append({"name": f"{video['name']}_{audio[0]}_"
                                           f"{subtitles[0]}_{'avs' if avs_mode else 'plain'}",
                                  "video": video, "audio": audio,
                                  "subs": subtitles})
    if limit:
        cases = cases[:limit]
    binaries = Binaries()
    results = [run_case(case, source,
                        ProbeInfo(), binaries, avs_mode)
               for case in cases
               for avs_mode in [case["name"].endswith("_avs")]]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "source_streams": stream_summary(probe(source)),
        "capabilities": sorted(encoders),
        "skipped_capabilities": skipped,
        "matrix_definition": {
            "video_encoders": [case["name"] for case in available_video],
            "audio_profiles": [case[0] for case in audio_cases(tools)],
            "subtitle_profiles": [case[0] for case in subtitle_cases()],
            "avisynth_modes": ["plain", "avs"] if include_avisynth else ["plain"],
        },
        "results": results,
        "summary": {
            "total": len(results),
            "passed": sum(1 for result in results if result["passed"]),
            "failed": sum(1 for result in results if not result["passed"]),
        },
        "elapsed_seconds": time.monotonic() - started,
    }
    write_report(report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0,
                        help="run only the first N matrix cases")
    parser.add_argument("--no-avisynth", action="store_true",
                        help="run only the plain FFmpeg half of the matrix")
    args = parser.parse_args()
    report = run_suite(args.limit or None, not args.no_avisynth)
    print(json.dumps(report["summary"], indent=2))
    print(f"Report: {REPORT_DIR / 'multitrack_media_report.md'}")
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
