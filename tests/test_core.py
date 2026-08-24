# -*- coding: utf-8 -*-
# AutoFFmpegGui v2
# SPDX-License-Identifier: EUPL-1.2
"""Unit tests for the pure command-building logic (no Qt / no ffmpeg)."""

import os
import tempfile
import unittest

from autoffmpeg.core import (
    AudioSelection,
    AvisynthOptions,
    InputPlan,
    EncodeJob,
    EncodeOptions,
    ProbeInfo,
    SubtitleSelection,
    build_audio_plan,
    build_elementary_jobs,
    build_ffmpeg_mux_command,
    build_jobs,
    build_external_audio_jobs,
    build_input_plan,
    encoder_option_catalog,
    build_mkvmerge_command,
    build_stream_args,
    build_video_args,
    calc_bitrate_mb,
    estimate_audio_bitrate_kbps,
    estimate_subtitle_bitrate_kbps,
    compute_loudnorm,
    detect_family,
    hdr_parts,
    job_from_dict,
    job_to_dict,
    normalize_output,
    parse_cropdetect,
    pb_profile_parse,
    plan_dovi,
    probe_duration,
    stream_language,
)
from autoffmpeg.validation import preflight
from autoffmpeg.bluray import (BlurayOptions, bluray_input_options,
                               bluray_url, is_bluray_path, parse_bluray_info)


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
        self.assertEqual(detect_family("-c:v libvvenc"), "x266")


class TestAdvancedOptions(unittest.TestCase):
    def test_encoder_override_replaces_default(self):
        o = EncodeOptions(
            preset={"family": "x264", "xpreset": "medium"},
            encoder_options={"preset": "slow", "aq-mode": "3"})
        args = build_video_args(o, ProbeInfo(has_video=True))
        self.assertEqual(args.count("-preset"), 1)
        self.assertIn("slow", args)
        self.assertIn(["-aq-mode", "3"], [args[i:i + 2]
                                             for i in range(len(args) - 1)])

    def test_encoder_catalog_has_vvc_and_av1(self):
        self.assertIn("qp", encoder_option_catalog("x266"))
        self.assertIn("crf", encoder_option_catalog("av1"))

    def test_probe_duration_frame_fallback(self):
        data = {"format": {"duration": "N/A"}, "streams": [
            {"codec_type": "video", "nb_frames": "50",
             "avg_frame_rate": "25/1"}]}
        self.assertEqual(probe_duration(data), 2.0)

    def test_preflight_rejects_invalid_combinations(self):
        with tempfile.NamedTemporaryFile(suffix=".mkv", delete=False) as fh:
            inputfile = fh.name
        try:
            o = EncodeOptions(
                inputfile=inputfile, outputfile="/tmp/out.mp4",
                preset={"family": "x266"},
                audio=[AudioSelection(0, codec="OGG (Vorbis)", encoder="oggenc",
                                      bitrate=96)],
                subs=[SubtitleSelection(0)],
                audio_tools={"oggenc": "/missing/oggenc"})
            issues = preflight(
                o, ProbeInfo(has_video=True,
                             subtitle_tracks=[{"codec_name": "hdmv_pgs_subtitle"}]),
                set())
            codes = {issue.code for issue in issues}
            self.assertIn("missing-x266", codes)
            self.assertIn("vorbis-mp4", codes)
            self.assertIn("missing-audio-tool", codes)
            subtitle_issue = next(issue for issue in issues
                                  if issue.code == "bitmap-mp4")
            self.assertIn("Blu-ray PGS subtitle track 1", subtitle_issue.message)
            self.assertIn("Select MKV", subtitle_issue.fix)
        finally:
            os.unlink(inputfile)

    def test_bluray_source_protocol_options(self):
        with tempfile.TemporaryDirectory() as td:
            os.mkdir(os.path.join(td, "BDMV"))
            self.assertTrue(is_bluray_path(td))
            options = BlurayOptions(enabled=True, path=td, playlist=42,
                                    angle=2, chapter=3)
            self.assertEqual(bluray_url(options), "bluray:" + td)
            self.assertEqual(bluray_input_options(options),
                             ["-playlist", "42", "-angle", "2",
                              "-chapter", "3"])

    def test_bluray_playlist_metadata_parser(self):
        titles = parse_bluray_info(
            "playlist: 00800\nduration: 01:32:10\nchapters: 24\n"
            "playlist=00801\nduration=00:02:00\n")
        self.assertEqual(titles[0]["playlist"], 800)
        self.assertEqual(titles[0]["chapters"], 24)
        self.assertEqual(titles[1]["playlist"], 801)


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

    def test_hw_ignores_software_profile_overrides(self):
        o = self._opts(preset={"family": "x264", "xpreset": "medium"},
                       mode="1-pass bitrate", hw="vaapi", bitrate=786,
                       available_encoders={"h264_vaapi"},
                       encoder_options={"preset": "medium"})
        args = build_video_args(o, ProbeInfo(has_video=True))
        self.assertEqual(args, ["-c:v", "h264_vaapi", "-b:v", "786k"])


class TestNewPresets(unittest.TestCase):
    def _opts(self, **kw):
        o = EncodeOptions()
        for k, v in kw.items():
            setattr(o, k, v)
        return o

    def test_vp9_crf_adds_zero_bitrate(self):
        o = self._opts(preset={"family": "vp9",
                               "rawargs": "-c:v libvpx-vp9 -deadline good".split()},
                       mode="Quality (CRF)", quality=30)
        args = build_video_args(o, ProbeInfo(has_video=True))
        self.assertEqual(args, ["-c:v", "libvpx-vp9", "-deadline", "good",
                                "-crf", "30", "-b:v", "0"])

    def test_av1_crf(self):
        o = self._opts(preset={"family": "av1",
                               "rawargs": "-c:v libsvtav1 -preset 8".split()},
                       mode="Quality (CRF)", quality=30)
        args = build_video_args(o, ProbeInfo(has_video=True))
        self.assertEqual(args, ["-c:v", "libsvtav1", "-preset", "8",
                                "-crf", "30"])

    def test_av1_2pass_no_pass_opt(self):
        o = self._opts(preset={"family": "av1",
                               "rawargs": "-c:v libsvtav1 -preset 8".split()},
                       mode="2-pass bitrate", bitrate=3000)
        args = build_video_args(o, ProbeInfo(has_video=True), passno=1)
        self.assertIn("-b:v", args)
        self.assertNotIn("-pass", args)

    def test_prores_profile(self):
        o = self._opts(preset={"family": "prores",
                               "rawargs": "-c:v prores_ks "
                                          "-profile:v hq".split()},
                       mode="Quality (CRF)", quality=16)
        args = build_video_args(o, ProbeInfo(has_video=True))
        self.assertEqual(args, ["-c:v", "prores_ks", "-profile:v", "hq"])

    def test_dnxhr_profile(self):
        o = self._opts(preset={"family": "dnxhd",
                               "rawargs": "-c:v dnxhd "
                                          "-profile:v dnxhr_hq".split()},
                       mode="Quality (CRF)", quality=16)
        args = build_video_args(o, ProbeInfo(has_video=True))
        self.assertEqual(args, ["-c:v", "dnxhd", "-profile:v", "dnxhr_hq"])


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

    def test_plan_dovi_converts_profiles_5_and_7_during_extraction(self):
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as fh:
            dovi_path = fh.name
        try:
            for profile, mode in ((5, "3"), (7, "2")):
                o = EncodeOptions(inputfile="/tmp/in.mkv",
                                  hdr_mode="Dolby Vision (source RPU)",
                                  dovi_tool=dovi_path)
                plan = plan_dovi(o, ProbeInfo(source_dv=True,
                                              dv_profile=profile), None)
                extract = plan["pre_jobs"][1].cmd
                self.assertEqual(extract[:3], [dovi_path, "--mode", mode])
                self.assertIn("extract-rpu", extract)
                self.assertNotIn("convert", extract)
                self.assertIn("dolby-vision-profile=8.1",
                              plan["x265_params"])
        finally:
            os.unlink(dovi_path)

    def test_plan_dovi_missing_tool(self):
        o = EncodeOptions(inputfile="/tmp/in.mkv",
                          hdr_mode="Dolby Vision (source RPU)",
                          dovi_tool="/nonexistent/dovi_tool")
        probe = ProbeInfo(source_dv=True, dv_profile=8)
        plan = plan_dovi(o, probe, None)
        self.assertEqual(plan["pre_jobs"], [])

    def test_preflight_rejects_dovi_without_rpu_encoder_support(self):
        with tempfile.NamedTemporaryFile(suffix=".mkv") as source, \
                tempfile.NamedTemporaryFile(suffix=".dovi") as dovi:
            o = EncodeOptions(inputfile=source.name, outputfile="/tmp/out.mkv",
                              hdr_mode="Dolby Vision (source RPU)",
                              dovi_tool=dovi.name)
            issues = preflight(o, ProbeInfo(has_video=True, source_dv=True),
                               dovi_encoder_supported=False)
            self.assertIn("unsupported-dovi-x265",
                          {issue.code for issue in issues})


class TestBitrate(unittest.TestCase):
    def test_calc(self):
        kbps = calc_bitrate_mb(700, 3600, 192)
        self.assertGreater(kbps, 0)

    def test_calc_includes_copied_audio_tracks(self):
        selections = [AudioSelection(0, codec="Copy"),
                      AudioSelection(1, codec="Copy"),
                      AudioSelection(2, codec="AAC", bitrate=128)]
        tracks = [{"codec_name": "ac3", "bit_rate": "384000"},
                  {"codec_name": "eac3", "bit_rate": "768000"},
                  {"codec_name": "mp2", "bit_rate": "192000"}]
        self.assertEqual(estimate_audio_bitrate_kbps(selections, tracks),
                         1280.0)

    def test_calc_scales_short_audio_to_target_duration(self):
        selections = [AudioSelection(0, codec="Copy")]
        tracks = [{"codec_name": "ac3", "bit_rate": "384000",
                   "_packet_duration": 10.0}]
        self.assertAlmostEqual(
            estimate_audio_bitrate_kbps(selections, tracks, 100.0), 38.4)

    def test_calc_includes_unburned_subtitles(self):
        selections = [SubtitleSelection(0), SubtitleSelection(1, burn=True)]
        tracks = [{"codec_name": "subrip"},
                  {"codec_name": "hdmv_pgs_subtitle"}]
        self.assertEqual(estimate_subtitle_bitrate_kbps(selections, tracks),
                         0.25)

    def test_calc_uses_subtitle_packet_size_over_video_duration(self):
        selections = [SubtitleSelection(0)]
        tracks = [{"codec_name": "subrip", "_packet_size": 216.0}]
        self.assertAlmostEqual(
            estimate_subtitle_bitrate_kbps(selections, tracks, 100.0), 0.01728)


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
                        cleanup=["/tmp/a", "/tmp/b"],
                        pipeline=[["ffmpeg", "-i", "x"], ["lame", "-", "y"]])
        data = job_to_dict(job)
        back = job_from_dict(data)
        self.assertEqual(back.label, "label")
        self.assertEqual(back.cmd, job.cmd)
        self.assertEqual(back.cleanup, job.cleanup)
        self.assertEqual(back.pipeline, job.pipeline)


class TestBuildJobs(unittest.TestCase):
    def test_elementary_avs_only_opens_script_for_video(self):
        with tempfile.TemporaryDirectory() as td:
            inputfile = os.path.join(td, "source.mkv")
            with open(inputfile, "wb"):
                pass
            output = os.path.join(td, "encoded.mkv")
            options = EncodeOptions(
                inputfile=inputfile, outputfile=output, hw="vaapi",
                preset={"family": "x264", "xpreset": "medium"},
                mode="1-pass bitrate", bitrate=786,
                available_encoders={"h264_vaapi"},
                encoder_options={"preset": "medium"},
                audio=[AudioSelection(0, codec="Copy")],
                subs=[SubtitleSelection(0)],
                avisynth=AvisynthOptions(enabled=True))
            probe = ProbeInfo(
                has_video=True, duration=1,
                audio_tracks=[{"codec_name": "ac3"}],
                subtitle_tracks=[{"codec_name": "subrip"}])
            jobs = build_elementary_jobs(options, probe)
            video = next(job for job in jobs if job.is_video)
            streams = [job for job in jobs if not job.is_video]
            self.assertIn("-f", video.cmd)
            self.assertIn("avisynth", video.cmd)
            self.assertNotIn("-preset", video.cmd)
            self.assertEqual(len(streams), 2)
            for job in streams:
                self.assertNotIn("avisynth", job.cmd)
                self.assertNotIn(".avs", " ".join(job.cmd))

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

    def test_direct_encode_tags_audio_and_subtitle_languages(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fh:
            inputfile = fh.name
        try:
            options = EncodeOptions(
                inputfile=inputfile, outputfile="/tmp/tagged.mp4",
                preset={"family": "x264", "xpreset": "medium"},
                audio=[AudioSelection(0, codec="AAC")],
                subs=[SubtitleSelection(0)])
            probe = ProbeInfo(
                has_video=True,
                audio_tracks=[{"tags": {"language": "ita"}}],
                subtitle_tracks=[{"tags": {"language": "eng"}}])
            cmd = build_jobs(options, probe)[0].cmd
            self.assertIn("-metadata:s:a:0", cmd)
            self.assertIn("language=ita", cmd)
            self.assertIn("-metadata:s:s:0", cmd)
            self.assertIn("language=eng", cmd)
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
            self.assertEqual(jobs[0].cleanup, [])
            self.assertTrue(any("autoffmpeg2pass" in p
                                for p in jobs[1].cleanup))
        finally:
            os.unlink(inputfile)

    def test_output_base_resolves_selected_container(self):
        o = EncodeOptions(inputfile="/tmp/source.mkv",
                          output_base="/tmp/final-name", container="mkv")
        self.assertEqual(normalize_output(o, ProbeInfo()),
                         "/tmp/final-name.mkv")

    def test_mkv_encoding_builds_raw_tracks_and_ffmpeg_mux_fallback(self):
        with tempfile.NamedTemporaryFile(suffix=".mkv", delete=False) as fh:
            inputfile = fh.name
        try:
            output = os.path.join(os.path.dirname(inputfile), "final.mkv")
            o = EncodeOptions(
                inputfile=inputfile, outputfile=output,
                preset={"family": "x264", "xpreset": "ultrafast"},
                audio=[AudioSelection(0, codec="AAC", bitrate=96)])
            probe = ProbeInfo(has_video=True, duration=1,
                              audio_tracks=[{"codec_name": "ac3"}])
            from autoffmpeg.config import Binaries
            binaries = Binaries(ffmpeg="ffmpeg", mkvmerge="missing-mkvmerge")
            jobs = build_jobs(o, probe, binaries)
            self.assertEqual(len(jobs), 3)
            self.assertIn("-f", jobs[0].cmd)
            self.assertEqual(jobs[-1].cmd[0], "ffmpeg")
            self.assertIn("-c", jobs[-1].cmd)
            self.assertIn("copy", jobs[-1].cmd)
            self.assertIn(output, jobs[-1].cmd)
        finally:
            os.unlink(inputfile)

    def test_avisynth_video_audio_input_plan(self):
        with tempfile.TemporaryDirectory() as td:
            inputfile = os.path.join(td, "source.mkv")
            with open(inputfile, "wb"):
                pass
            output = os.path.join(td, "encoded.mp4")
            o = EncodeOptions(
                inputfile=inputfile, outputfile=output,
                preset={"family": "x264"},
                audio=[AudioSelection(0, codec="AAC")],
                avisynth=AvisynthOptions(
                    enabled=True,
                    plugin_paths=["/usr/lib/avisynth/libffms2.so"]))
            jobs = build_jobs(o, ProbeInfo(has_video=True, duration=3))
            self.assertEqual(len(jobs), 1)
            self.assertIn("avisynth", jobs[0].cmd)
            generated = os.path.join(td, "source.autoffmpeg", "encoded.avs")
            self.assertIn(generated, jobs[0].cmd)
            self.assertIn("-map", jobs[0].cmd)
            self.assertIn("0:a:0", jobs[0].cmd)
            self.assertTrue(os.path.exists(generated))

    def test_external_lame_is_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            inputfile = os.path.join(td, "source.mkv")
            with open(inputfile, "wb"):
                pass
            o = EncodeOptions(
                inputfile=inputfile,
                audio=[AudioSelection(0, codec="MP3", encoder="lame")],
                audio_tools={"lame": "/usr/bin/lame"})
            jobs, files = build_external_audio_jobs(
                o, ProbeInfo(duration=1), InputPlan(inputs=[inputfile]),
                output_dir=td)
            self.assertEqual(len(jobs), 1)
            self.assertEqual(files[0][0], 0)
            self.assertEqual(jobs[0].pipeline[-1][0], "/usr/bin/lame")


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

    def test_source_language_tags_are_normalized(self):
        self.assertEqual(stream_language(
            {"tags": {"LANGUAGE": "ITA-IT"}}), "ita-it")
        self.assertIsNone(stream_language({}))

    def test_mkv_encode_mux_keeps_audio_and_subtitle_languages(self):
        with tempfile.NamedTemporaryFile(suffix=".mkv", delete=False) as fh:
            inputfile = fh.name
        try:
            output = os.path.join(os.path.dirname(inputfile), "tagged.mkv")
            options = EncodeOptions(
                inputfile=inputfile, outputfile=output,
                preset={"family": "x264", "xpreset": "ultrafast"},
                audio=[AudioSelection(0, codec="AAC", bitrate=96)],
                subs=[SubtitleSelection(0)])
            probe = ProbeInfo(
                has_video=True, duration=1,
                audio_tracks=[{"codec_name": "ac3", "tags": {"language": "ita"}}],
                subtitle_tracks=[{"codec_name": "subrip",
                                  "tags": {"language": "eng"}}])
            from autoffmpeg.config import Binaries
            binaries = Binaries(ffmpeg="ffmpeg", mkvmerge="missing-mkvmerge")
            jobs = build_jobs(options, probe, binaries)
            cmd = jobs[-1].cmd
            self.assertIn("language=ita", cmd)
            self.assertIn("language=eng", cmd)
        finally:
            os.unlink(inputfile)

    def test_external_x264_uses_profile_and_input_relative_workdir(self):
        with tempfile.TemporaryDirectory() as td:
            inputfile = os.path.join(td, "source.mkv")
            open(inputfile, "wb").close()
            output = os.path.join(td, "encoded.mkv")
            options = EncodeOptions(
                inputfile=inputfile, outputfile=output,
                preset={"family": "x264", "xpreset": "slow"}, quality=19,
                external_video_encoder="x264", external_video_binary="/bin/true")
            jobs = build_jobs(options, ProbeInfo(has_video=True, duration=1))
            self.assertTrue(jobs[0].pipeline)
            self.assertIn("yuv4mpegpipe", jobs[0].pipeline[0])
            self.assertIn("--preset", jobs[0].pipeline[1])
            self.assertIn("--crf", jobs[0].pipeline[1])
            self.assertIn(os.path.join(td, "source.autoffmpeg"),
                          " ".join(jobs[0].pipeline[1]))
            self.assertIn(os.path.join(td, "source.autoffmpeg"),
                          jobs[-1].cleanup)

    def test_external_keep_generated_files_leaves_workdir(self):
        with tempfile.TemporaryDirectory() as td:
            inputfile = os.path.join(td, "source.mkv")
            open(inputfile, "wb").close()
            options = EncodeOptions(
                inputfile=inputfile, outputfile=os.path.join(td, "encoded.mkv"),
                preset={"family": "x265"}, external_video_encoder="x265",
                external_video_binary="/bin/true", keep_generated_files=True)
            jobs = build_jobs(options, ProbeInfo(has_video=True, duration=1))
            self.assertEqual(jobs[-1].cleanup, [])

    def test_selected_x264_overrides_x265_profile_and_uses_two_pass_cli(self):
        with tempfile.TemporaryDirectory() as td:
            inputfile = os.path.join(td, "source.mkv")
            open(inputfile, "wb").close()
            options = EncodeOptions(
                inputfile=inputfile, outputfile=os.path.join(td, "encoded.mkv"),
                preset={"family": "x265", "xpreset": "faster"},
                mode="2-pass bitrate", bitrate=500,
                external_video_encoder="x264", external_video_binary="/bin/true")
            jobs = build_jobs(options, ProbeInfo(has_video=True, duration=1))
            self.assertEqual(len([job for job in jobs if job.is_video]), 2)
            self.assertEqual(jobs[0].pipeline[1][0], "/bin/true")
            self.assertIn("--pass", jobs[0].pipeline[1])
            self.assertIn("--pass", jobs[1].pipeline[1])
            self.assertIn("--output", jobs[1].pipeline[1])
            self.assertNotIn("libx265", jobs[0].pipeline[1])


if __name__ == "__main__":
    unittest.main()
