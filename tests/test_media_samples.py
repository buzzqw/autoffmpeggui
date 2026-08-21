# -*- coding: utf-8 -*-
"""Short integration checks against the media samples shipped with the repo."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from autoffmpeg.core import (
    AudioSelection,
    AvisynthOptions,
    EncodeOptions,
    InputPlan,
    ProbeInfo,
    build_external_audio_jobs,
    build_avisynth_script,
    build_jobs,
    build_input_plan,
)
from autoffmpeg.config import Binaries
from autoffmpeg.workers import EncodeThread


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg and ffprobe are required")
class TestMediaSamples(unittest.TestCase):
    def _probe(self, path):
        proc = subprocess.run(
            [FFPROBE, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, check=True)
        return json.loads(proc.stdout)

    def _run(self, command):
        return subprocess.run(command, capture_output=True, text=True,
                              timeout=120)

    def _run_jobs(self, jobs):
        codes = []
        for job in jobs:
            worker = EncodeThread([job])
            worker.job_done.connect(lambda _index, code: codes.append(code))
            worker.run()
        return codes

    def test_samples_probe_with_video(self):
        for name in ("test_multitrack.mkv", "aaa.vob"):
            data = self._probe(ROOT / name)
            self.assertTrue(any(s.get("codec_type") == "video"
                                for s in data.get("streams", [])), name)

    def test_mkv_short_x264_encode(self):
        output = os.devnull
        result = self._run([
            FFMPEG, "-v", "error", "-y", "-i",
            str(ROOT / "test_multitrack.mkv"), "-frames:v", "3",
            "-vf", "scale=320:180", "-an", "-c:v", "libx264",
            "-preset", "ultrafast", "-f", "null", output])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_vob_short_x265_encode(self):
        result = self._run([
            FFMPEG, "-v", "error", "-y", "-i", str(ROOT / "aaa.vob"),
            "-frames:v", "3", "-vf", "scale=320:240", "-an",
            "-c:v", "libx265", "-preset", "ultrafast", "-f", "null",
            os.devnull])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_builder_muxes_multitrack_sample(self):
        with tempfile.TemporaryDirectory() as td:
            output = os.path.join(td, "built.mp4")
            options = EncodeOptions(
                inputfile=str(ROOT / "test_multitrack.mkv"),
                outputfile=output, trim_end="1", width=320, height=180,
                audio=[AudioSelection(0, codec="AAC", bitrate=96)],
                preset={"family": "x264", "xpreset": "ultrafast"})
            probe = ProbeInfo(
                has_video=True, duration=1, vwidth=1920, vheight=1080,
                audio_tracks=[{"codec_name": "ac3"}],
                subtitle_tracks=[{"codec_name": "subrip"}])
            options.subs = []
            jobs = build_jobs(options, probe)
            self.assertEqual(len(jobs), 1)
            result = self._run(jobs[0].cmd)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = self._probe(output)
            types = [s.get("codec_type") for s in data.get("streams", [])]
            self.assertIn("video", types)
            self.assertIn("audio", types)

    def test_builder_avisynth_encode_when_runtime_is_complete(self):
        plugin = "/usr/lib/avisynth/libffms2.so"
        if not os.path.exists(plugin) or not os.path.exists("/usr/lib/libIL.so.1"):
            self.skipTest("AviSynth+ image plugin dependency is not installed")
        with tempfile.TemporaryDirectory() as td:
            source_path = Path(td) / "source.mkv"
            shutil.copyfile(ROOT / "test_multitrack.mkv", source_path)
            output = os.path.join(td, "built-avs.mkv")
            options = EncodeOptions(
                inputfile=str(source_path), outputfile=output, trim_end="1",
                width=320, height=180,
                audio=[AudioSelection(0, codec="AAC", bitrate=96)],
                preset={"family": "x264", "xpreset": "ultrafast"},
                avisynth=AvisynthOptions(
                    enabled=True, plugin_paths=[plugin]))
            jobs = build_jobs(options, ProbeInfo(
                has_video=True, duration=1, vwidth=1920, vheight=1080,
                audio_tracks=[{"codec_name": "ac3"}]))
            self.assertGreaterEqual(len(jobs), 3)
            codes = self._run_jobs(jobs)
            self.assertTrue(codes and all(code == 0 for code in codes), codes)
            data = self._probe(output)
            self.assertTrue(any(s.get("codec_type") == "video"
                                for s in data.get("streams", [])))
            self.assertTrue(any(s.get("codec_type") == "audio"
                                for s in data.get("streams", [])))

    def test_explicit_avs_keeps_original_audio_in_real_encode(self):
        plugin = "/usr/lib/avisynth/libffms2.so"
        if not os.path.exists(plugin) or not os.path.exists("/usr/lib/libIL.so.1"):
            self.skipTest("AviSynth+ image plugin dependency is not installed")
        if not shutil.which("lame"):
            self.skipTest("lame is not installed")
        with tempfile.TemporaryDirectory() as td:
            source_path = Path(td) / "source.vob"
            shutil.copyfile(ROOT / "aaa.vob", source_path)
            probe = ProbeInfo(
                has_video=True, duration=1, vwidth=720, vheight=576,
                audio_tracks=[{"codec_name": "ac3", "channels": 6},
                              {"codec_name": "mp2", "channels": 2}])
            script_options = AvisynthOptions(
                enabled=True, plugin_paths=[plugin])
            script_path = Path(td) / "explicit.avs"
            script_path.write_text(build_avisynth_script(
                EncodeOptions(inputfile=str(source_path), avisynth=script_options),
                probe), encoding="utf-8")
            output = Path(td) / "explicit-output.mkv"
            options = EncodeOptions(
                inputfile=str(source_path), outputfile=str(output),
                trim_end="1", preset={"family": "x264", "xpreset": "ultrafast"},
                width=320, height=256,
                audio=[AudioSelection(0, codec="MP3", encoder="lame", bitrate=96),
                       AudioSelection(1, codec="AAC", bitrate=96)],
                avisynth=AvisynthOptions(enabled=True,
                                         script_path=str(script_path)),
                audio_tools={"lame": shutil.which("lame")})
            jobs = build_jobs(options, probe, Binaries())
            codes = self._run_jobs(jobs)
            self.assertTrue(codes and all(code == 0 for code in codes), codes)
            self.assertTrue(output.exists() and output.stat().st_size > 0)
            streams = self._probe(output).get("streams", [])
            self.assertEqual(len([s for s in streams
                                  if s.get("codec_type") == "video"]), 1)
            self.assertEqual(len([s for s in streams
                                  if s.get("codec_type") == "audio"]), 2)

    def test_real_vob_video_audio_avisynth_matrix(self):
        """Exercise real builder/worker output for the supported combinations."""
        encoders = subprocess.run(
            [FFMPEG, "-hide_banner", "-encoders"],
            capture_output=True, text=True, check=True).stdout
        video_cases = [
            ("x264", {"family": "x264", "xpreset": "ultrafast"},
             "h264", {"crf": "28"}),
            ("x265", {"family": "x265", "xpreset": "ultrafast"},
             "hevc", {"crf": "30"}),
        ]
        if "libsvtav1" in encoders:
            video_cases.append(
                ("av1", {"family": "av1", "encoder": "libsvtav1"},
                 "av1", {"preset": "12", "crf": "35"}))
        audio_cases = [
            ("ffmpeg_aac", AudioSelection(0, codec="AAC", bitrate=96),
             "aac", {}),
        ]
        if shutil.which("lame"):
            audio_cases.append(
                ("lame_mp3", AudioSelection(0, codec="MP3", encoder="lame",
                                              bitrate=96), "mp3",
                                 {"lame": shutil.which("lame")}))
        if shutil.which("faac"):
            audio_cases.append(
                ("faac_aac", AudioSelection(0, codec="AAC", encoder="faac",
                                              bitrate=96, channels="2"), "aac",
                                 {"faac": shutil.which("faac")}))
        if shutil.which("oggenc"):
            audio_cases.append(
                ("oggenc_vorbis", AudioSelection(
                    0, codec="OGG (Vorbis)", encoder="oggenc", bitrate=96,
                    channels="2"), "vorbis", {"oggenc": shutil.which("oggenc")}))
        plugin = "/usr/lib/avisynth/libffms2.so"
        avs_modes = [("plain", AvisynthOptions(enabled=False))]
        if os.path.exists(plugin) and os.path.exists("/usr/lib/libIL.so.1"):
            avs_modes.append(("avs", AvisynthOptions(
                enabled=True, plugin_paths=[plugin])))
        source = ROOT / "aaa.vob"
        for video_name, preset, expected_video, video_options in video_cases:
            for audio_name, audio, expected_audio, audio_tools in audio_cases:
                for avs_name, avs in avs_modes:
                    case = f"{video_name}_{audio_name}_{avs_name}"
                    with self.subTest(case=case), tempfile.TemporaryDirectory() as td:
                        input_path = Path(td) / "source.vob"
                        shutil.copyfile(source, input_path)
                        output = Path(td) / f"{case}.mkv"
                        options = EncodeOptions(
                            inputfile=str(input_path), outputfile=str(output),
                            preset=preset, quality=30, bitrate=1200,
                            width=320, height=256, trim_end="1",
                            audio=[audio], avisynth=avs,
                            audio_tools=audio_tools,
                            encoder_options=video_options)
                        probe = ProbeInfo(
                            has_video=True, duration=1, vwidth=720, vheight=576,
                            audio_tracks=[{"codec_name": "ac3", "channels": 6}])
                        jobs = build_jobs(options, probe, Binaries())
                        codes = self._run_jobs(jobs)
                        self.assertTrue(codes and all(code == 0 for code in codes),
                                        f"{case}: job codes {codes}")
                        self.assertTrue(output.exists() and output.stat().st_size > 0,
                                        f"{case}: output was not created")
                        streams = self._probe(output).get("streams", [])
                        video = [s for s in streams if s.get("codec_type") == "video"]
                        audio_streams = [s for s in streams
                                         if s.get("codec_type") == "audio"]
                        self.assertTrue(video, f"{case}: no video stream")
                        self.assertTrue(audio_streams, f"{case}: no audio stream")
                        self.assertEqual(video[0].get("codec_name"), expected_video,
                                         case)
                        self.assertEqual(audio_streams[0].get("codec_name"),
                                         expected_audio, case)

    def test_sample_av1_encode_when_available(self):
        encoders = subprocess.run(
            [FFMPEG, "-hide_banner", "-encoders"],
            capture_output=True, text=True, check=True).stdout
        if "libsvtav1" not in encoders and "libaom-av1" not in encoders:
            self.skipTest("no software AV1 encoder in FFmpeg")
        encoder = "libsvtav1" if "libsvtav1" in encoders else "libaom-av1"
        result = self._run([
            FFMPEG, "-v", "error", "-y", "-i",
            str(ROOT / "test_multitrack.mkv"), "-frames:v", "2",
            "-vf", "scale=320:180", "-an", "-c:v", encoder,
            "-f", "null", os.devnull])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_avisynth_ffms2_source_when_runtime_is_complete(self):
        plugin = "/usr/lib/avisynth/libffms2.so"
        if not os.path.exists(plugin) or not os.path.exists("/usr/lib/libIL.so.1"):
            self.skipTest("AviSynth+ image plugin dependency is not installed")
        with tempfile.TemporaryDirectory() as td:
            source_path = Path(td) / "source.mkv"
            shutil.copyfile(ROOT / "test_multitrack.mkv", source_path)
            source = str(source_path)
            options = EncodeOptions(
                inputfile=source,
                outputfile=os.path.join(td, "avs-output.mkv"),
                avisynth=AvisynthOptions(
                    enabled=True, plugin_paths=[plugin]))
            plan = build_input_plan(
                options, ProbeInfo(has_video=True, vwidth=1920, vheight=1080))
            result = self._run([
                FFMPEG, "-v", "error", "-f", "avisynth", "-i",
                plan.inputs[1], "-frames:v", "1", "-f", "null", os.devnull])
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_external_lame_pipeline_on_sample(self):
        lame = shutil.which("lame")
        if not lame:
            self.skipTest("lame is not installed")
        with tempfile.TemporaryDirectory() as td:
            output = os.path.join(td, "sample.mp3")
            options = EncodeOptions(
                inputfile=str(ROOT / "test_multitrack.mkv"),
                trim_end="1",
                audio=[AudioSelection(0, codec="MP3", encoder="lame",
                                      bitrate=96)],
                audio_tools={"lame": lame})
            jobs, files = build_external_audio_jobs(
                options,
                ProbeInfo(duration=1, audio_tracks=[{"channels": 6}]),
                InputPlan(inputs=[options.inputfile]),
                output_dir=td)
            self.assertEqual(len(jobs), 1)
            first = subprocess.Popen(jobs[0].pipeline[0], stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL)
            second = subprocess.Popen(jobs[0].pipeline[1], stdin=first.stdout,
                                      stdout=subprocess.DEVNULL,
                                      stderr=subprocess.PIPE, text=True)
            first.stdout.close()
            _, stderr = second.communicate(timeout=120)
            first.wait(timeout=10)
            self.assertEqual(second.returncode, 0, stderr)
            self.assertTrue(os.path.exists(files[0][1]))

    def test_external_faac_and_oggenc_pipelines_on_sample(self):
        tools = [("faac", "AAC"), ("oggenc", "OGG (Vorbis)")]
        available = [(name, codec, shutil.which(name))
                     for name, codec in tools if shutil.which(name)]
        if not available:
            self.skipTest("neither faac nor oggenc is installed")
        with tempfile.TemporaryDirectory() as td:
            for name, codec, path in available:
                options = EncodeOptions(
                    inputfile=str(ROOT / "test_multitrack.mkv"),
                    trim_end="1",
                    audio=[AudioSelection(0, codec=codec, encoder=name,
                                          bitrate=96, channels="2")],
                    audio_tools={name: path})
                jobs, files = build_external_audio_jobs(
                    options, ProbeInfo(duration=1, audio_tracks=[{"channels": 6}]),
                    InputPlan(inputs=[options.inputfile]), output_dir=td)
                self.assertEqual(len(jobs), 1, name)
                first = subprocess.Popen(jobs[0].pipeline[0], stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL)
                second = subprocess.Popen(jobs[0].pipeline[1], stdin=first.stdout,
                                          stdout=subprocess.DEVNULL,
                                          stderr=subprocess.PIPE, text=True)
                first.stdout.close()
                _, stderr = second.communicate(timeout=120)
                first.wait(timeout=10)
                self.assertEqual(second.returncode, 0, f"{name}: {stderr}")
                self.assertTrue(os.path.exists(files[0][1]), name)


if __name__ == "__main__":
    unittest.main()
