# -*- coding: utf-8 -*-
# AutoFFmpegGui v2
# SPDX-License-Identifier: EUPL-1.2
"""Unit tests for the pure command-building logic (no Qt / no ffmpeg)."""

import os
import tempfile
import unittest

from autoffmpeg.core import (
    AudioSelection,
    EncodeJob,
    EncodeOptions,
    ProbeInfo,
    SubtitleSelection,
    build_audio_plan,
    build_ffmpeg_mux_command,
    build_jobs,
    build_mkvmerge_command,
    build_stream_args,
    build_video_args,
    calc_bitrate_mb,
    compute_loudnorm,
    detect_family,
    hdr_parts,
    job_from_dict,
    job_to_dict,
    parse_cropdetect,
    pb_profile_parse,
    plan_dovi,
)


class TestDetectFamily(unittest.TestCase):
    def test_families(self):
        self.assertEqual(detect_family("-c:v libx264 -preset medium"), "x264")
        self.assertEqual(detect_family("-c:v libx265"), "x265")
        self.assertEqual(detect_family("-c:v libsvtav1"), "av1")
        self.assertEqual(detect_family("-c:v libvpx-vp9"), "vp9")
        self.assertEqual(detect_family("-c:v libxvid"), "xvid")
        self.assertEqual(detect_family("-c:v prores_ks"), "prores")
        self.assertEqual(detect_family("-c:v ffv1"), "ffv1")
        self.assertEqual(detect_family(""), "x264")


class TestProfileParse(unittest.TestCase):
    def test_parse(self):
        lines = [
            "# comment",
            "Web H.264;-c:v libx264 -preset slow",
            "TV HEVC;-c:v libx265",
            "dup;-c:v mpeg4",
            "dup;-c:v libxvid",
        ]
        out = pb_profile_parse(lines)
        self.assertEqual(out[0], ("Web H.264", "-c:v libx264 -preset slow"))
        self.assertEqual(out[1], ("TV HEVC", "-c:v libx265"))
        self.assertEqual(out[2], ("dup", "-c:v mpeg4"))
        self.assertEqual(len(out), 3)


class TestVideoArgs(unittest.TestCase):
    def _opts(self, **kw):
        o = EncodeOptions()
        for k, v in kw.items():
            setattr(o, k, v)
        return o

    def test_crf_x264(self):
        o = self._opts(preset={"family": "x264", "xpreset": "medium"},
                       mode="Quality (CRF)", quality=20)
        args = build_video_args(o, ProbeInfo(has_video=True))
        self.assertEqual(args, ["-c:v", "libx264", "-preset", "medium",
                                "-crf", "20"])

    def test_bitrate_x264(self):
        o = self._opts(preset={"family": "x264", "xpreset": "fast"},
                       mode="1-pass bitrate", bitrate=3000)
        args = build_video_args(o, ProbeInfo(has_video=True))
        self.assertIn("-b:v", args)
        self.assertIn("3000k", args)

    def test_copy_video(self):
        o = self._opts(preset={"family": "x264"}, mode="Copy video")
        args = build_video_args(o, ProbeInfo(has_video=True))
        self.assertEqual(args, ["-c:v", "copy"])

    def test_hw_nvenc(self):
        o = self._opts(preset={"family": "x264"}, mode="Quality (CRF)",
                       hw="nvenc", quality=24,
                       available_encoders={"h264_nvenc"})
        args = build_video_args(o, ProbeInfo(has_video=True))
        self.assertEqual(args, ["-c:v", "h264_nvenc", "-cq", "24"])


class TestHdrParts(unittest.TestCase):
    def test_sdr_tone_map(self):
        o = EncodeOptions(hdr_mode="SDR (tone map to BT.709)")
        p = hdr_parts(o, ProbeInfo(source_hdr_info=("bt2020", "smpte2084", "bt2020nc")),
                      "x265", 5000)
        self.assertEqual(p["pix"], "yuv420p")
        self.assertTrue(any("tonemap" in v for v in p["vf"]))

    def test_hdr10(self):
        o = EncodeOptions(hdr_mode="HDR10 (BT.2020 / PQ)")
        p = hdr_parts(o, ProbeInfo(), "x265", 5000)
        self.assertEqual(p["pix"], "yuv420p10le")
        self.assertIn("-color_primaries", p["opts"])


class TestLoudnorm(unittest.TestCase):
    def test_compute(self):
        raw = ('{ "input_i" : "-18.00", "input_tp" : "-3.00", '
               '"input_lra" : "9.00", "input_thresh" : "-30.00", '
               '"target_offset" : "2.00" }')
        v = compute_loudnorm(raw)
        self.assertEqual(v["I"], "-16.00")
        self.assertEqual(v["TP"], "-1.00")
        self.assertEqual(v["OFF"], "2.00")

    def test_invalid(self):
        self.assertEqual(compute_loudnorm("no json here"), {})


class TestAudioArgs(unittest.TestCase):
    def test_normalize_measures(self):
        o = EncodeOptions(inputfile="/tmp/in.mkv", normalize=True,
                          audio=[AudioSelection(input_index=0, codec="AAC",
                                                bitrate=128)])
        codec_args, filter_complex, measures, audio_maps = build_audio_plan(
            o, ProbeInfo())
        self.assertEqual(len(measures), 1)
        self.assertEqual(len(filter_complex), 1)
        self.assertIn("[0:a:0]", filter_complex[0])
        self.assertIn("__LN_I_0__", filter_complex[0])
        self.assertEqual(audio_maps, ["-map", "[a0]"])

    def test_no_audio(self):
        o = EncodeOptions(audio=[])
        codec_args, filter_complex, measures, audio_maps = build_audio_plan(
            o, ProbeInfo())
        self.assertEqual(codec_args, ["-an"])

    def test_gain_skips_copy(self):
        o = EncodeOptions(inputfile="/tmp/in.mkv", gain=6,
                          audio=[AudioSelection(input_index=0, codec="Copy"),
                                 AudioSelection(input_index=1, codec="AAC",
                                                bitrate=128)])
        codec_args, filter_complex, measures, audio_maps = build_audio_plan(
            o, ProbeInfo())
        self.assertEqual(len(filter_complex), 1)
        self.assertIn("[0:a:1]", filter_complex[0])
        self.assertIn("volume=6dB", filter_complex[0])
        self.assertEqual(audio_maps, ["-map", "0:a:0", "-map", "[a1]"])


class TestStreamArgs(unittest.TestCase):
    def test_batch(self):
        o = EncodeOptions(batch=True)
        video_maps, sub_maps, sub_args = build_stream_args(
            o, ProbeInfo(has_video=True), False)
        self.assertIn("0:v:0", video_maps)
        self.assertIn("0:s?", sub_maps)
        self.assertEqual(sub_args, ["-c:s", "copy"])

    def test_burn_excludes_sub(self):
        o = EncodeOptions(subs=[SubtitleSelection(0, enabled=True, burn=True)])
        video_maps, sub_maps, sub_args = build_stream_args(
            o, ProbeInfo(has_video=True), False)
        self.assertNotIn("0:s:0", sub_maps)
        self.assertEqual(sub_args, [])

    def test_no_subs_selected_sn(self):
        o = EncodeOptions(subs=[SubtitleSelection(0, enabled=False)])
        video_maps, sub_maps, sub_args = build_stream_args(
            o, ProbeInfo(has_video=True), False)
        self.assertEqual(sub_args, ["-sn"])


class TestDovi(unittest.TestCase):
    def test_plan_dovi(self):
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as fh:
            dovi_path = fh.name
        try:
            o = EncodeOptions(inputfile="/tmp/in.mkv",
                              hdr_mode="Dolby Vision (source RPU)",
                              dovi_tool=dovi_path)
            probe = ProbeInfo(source_dv=True, dv_profile=8)
            logs = []
            plan = plan_dovi(o, probe, None, logs.append)
            self.assertEqual(len(plan["pre_jobs"]), 2)
            self.assertEqual(len(plan["cleanup"]), 2)
            self.assertTrue(any("dolby-vision-rpu=" in x
                                for x in plan["x265_params"]))
        finally:
            os.unlink(dovi_path)

    def test_plan_dovi_missing_tool(self):
        o = EncodeOptions(inputfile="/tmp/in.mkv",
                          hdr_mode="Dolby Vision (source RPU)",
                          dovi_tool="/nonexistent/dovi_tool")
        probe = ProbeInfo(source_dv=True, dv_profile=8)
        plan = plan_dovi(o, probe, None)
        self.assertEqual(plan["pre_jobs"], [])


class TestBitrate(unittest.TestCase):
    def test_calc(self):
        kbps = calc_bitrate_mb(700, 3600, 192)
        self.assertGreater(kbps, 0)


class TestCropdetect(unittest.TestCase):
    def test_parse(self):
        raw = ("x=0 y=0 crop=1920:800:0:140\n"
               "x=0 y=0 crop=1920:804:0:138")
        self.assertEqual(parse_cropdetect(raw), (1920, 804, 0, 138))

    def test_none(self):
        self.assertIsNone(parse_cropdetect("no crop lines"))


class TestJobSerialize(unittest.TestCase):
    def test_roundtrip(self):
        job = EncodeJob("label", ["ffmpeg", "-i", "x"], 12.5,
                        cleanup=["/tmp/a", "/tmp/b"])
        data = job_to_dict(job)
        back = job_from_dict(data)
        self.assertEqual(back.label, "label")
        self.assertEqual(back.cmd, job.cmd)
        self.assertEqual(back.cleanup, job.cleanup)


class TestBuildJobs(unittest.TestCase):
    def test_simple_encode(self):
        with tempfile.NamedTemporaryFile(suffix=".mkv", delete=False) as fh:
            inputfile = fh.name
        try:
            o = EncodeOptions(inputfile=inputfile,
                              outputfile="/tmp/out.mp4",
                              preset={"family": "x264", "xpreset": "medium"},
                              mode="Quality (CRF)", quality=21)
            probe = ProbeInfo(has_video=True, duration=10.0)
            jobs = build_jobs(o, probe)
            self.assertEqual(len(jobs), 1)
            cmd = jobs[0].cmd
            self.assertIn("-progress", cmd)
            self.assertIn("libx264", cmd)
            self.assertIn("-crf", cmd)
            self.assertIn("-movflags", cmd)  # mp4 -> faststart
        finally:
            os.unlink(inputfile)

    def test_remux(self):
        with tempfile.NamedTemporaryFile(suffix=".mkv", delete=False) as fh:
            inputfile = fh.name
        try:
            o = EncodeOptions(inputfile=inputfile,
                              outputfile="/tmp/out.mkv",
                              mode="Remux (copy all)")
            jobs = build_jobs(o, ProbeInfo(duration=5.0))
            self.assertEqual(len(jobs), 1)
            self.assertIn("-c", jobs[0].cmd)
            self.assertIn("copy", jobs[0].cmd)
        finally:
            os.unlink(inputfile)

    def test_two_pass(self):
        with tempfile.NamedTemporaryFile(suffix=".mkv", delete=False) as fh:
            inputfile = fh.name
        try:
            o = EncodeOptions(inputfile=inputfile,
                              outputfile="/tmp/out.mp4",
                              preset={"family": "x264", "xpreset": "medium"},
                              mode="2-pass bitrate", bitrate=2000)
            jobs = build_jobs(o, ProbeInfo(has_video=True, duration=10.0))
            self.assertEqual(len(jobs), 2)
            self.assertIn("-pass", jobs[0].cmd)
        finally:
            os.unlink(inputfile)


class TestElementaryJobs(unittest.TestCase):
    def test_separate_streams(self):
        with tempfile.NamedTemporaryFile(suffix=".mkv", delete=False) as fh:
            inputfile = fh.name
        try:
            o = EncodeOptions(inputfile=inputfile, nomux=True,
                              mode="Quality (CRF)",
                              preset={"family": "x265", "xpreset": "slow"},
                              quality=20,
                              audio=[AudioSelection(0, codec="AAC", bitrate=128),
                                     AudioSelection(1, codec="Copy")],
                              subs=[SubtitleSelection(0)])
            probe = ProbeInfo(has_video=True, duration=10.0,
                              vwidth=1920, vheight=1080,
                              audio_tracks=[{"codec_name": "aac"},
                                            {"codec_name": "ac3"}],
                              subtitle_tracks=[{"codec_name": "subrip"}])
            jobs = build_jobs(o, probe)
            labels = [j.label for j in jobs]
            self.assertIn("Video -> ", labels[0])
            self.assertIn("Audio 0 -> ", labels[1])
            self.assertIn("Audio 1 -> ", labels[2])
            self.assertIn("Subtitle 0 -> ", labels[3])
            # video is a re-encode, not a copy
            self.assertIn("-c:v", jobs[0].cmd)
            self.assertIn("libx265", jobs[0].cmd)
            self.assertIn("-f", jobs[0].cmd)
            # copy audio uses the source codec format
            self.assertIn("-c:a", jobs[2].cmd)
            self.assertIn("copy", jobs[2].cmd)
        finally:
            os.unlink(inputfile)

    def test_copy_video_skipped(self):
        with tempfile.NamedTemporaryFile(suffix=".mkv", delete=False) as fh:
            inputfile = fh.name
        try:
            o = EncodeOptions(inputfile=inputfile, nomux=True,
                              mode="Copy video",
                              preset={"family": "x264"})
            probe = ProbeInfo(has_video=True, duration=5.0)
            logs = []
            jobs = build_jobs(o, probe, log=logs.append)
            self.assertEqual(jobs, [])
            self.assertTrue(any("copy video" in m for m in logs))
        finally:
            os.unlink(inputfile)


class TestMuxCommands(unittest.TestCase):
    def _tracks(self):
        return [
            {"path": "/x/video.mkv", "kind": "video", "language": "ita",
             "forced": False, "default": True, "delay_ms": 0},
            {"path": "/x/audio.ac3", "kind": "audio", "language": "eng",
             "forced": False, "default": True, "delay_ms": 150},
            {"path": "/x/sub.srt", "kind": "subtitle", "language": "ita",
             "forced": True, "default": False, "delay_ms": 0},
        ]

    def test_mkvmerge(self):
        cmd = build_mkvmerge_command(self._tracks(), "/x/out.mkv")
        self.assertEqual(cmd[0], "mkvmerge")
        self.assertIn("--language", cmd)
        self.assertIn("0:ita", cmd)
        self.assertIn("--sync", cmd)
        self.assertIn("0:150", cmd)
        self.assertIn("--forced-track", cmd)
        self.assertIn("/x/out.mkv", cmd)

    def test_ffmpeg_mux(self):
        cmd = build_ffmpeg_mux_command(self._tracks(), "/x/out.mkv")
        self.assertIn("-map", cmd)
        self.assertIn("0:0", cmd)
        self.assertIn("language=eng", cmd)
        self.assertIn("-itsoffset", cmd)
        self.assertIn("0.150", cmd)
        self.assertIn("forced", cmd)
        self.assertIn("-c", cmd)
        self.assertIn("copy", cmd)


if __name__ == "__main__":
    unittest.main()
