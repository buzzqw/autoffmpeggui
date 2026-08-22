# AutoFFmpegGui

AutoFFmpegGui is a PyQt6 desktop front end for FFmpeg. It provides a practical
workflow for converting, previewing and organizing media while keeping the
power of FFmpeg available through custom profiles and generated commands.

## License

AutoFFmpegGui is licensed under the **European Union Public Licence v1.2**
(EUPL-1.2). See the [LICENSE](LICENSE) file for the full licence text.

```
SPDX-License-Identifier: EUPL-1.2
```

## Features

- H.264, H.265/HEVC, AV1, VP9, MPEG-4, Xvid, MPEG-2, WMV and archive codecs.
- Per-track audio selection and encoding with channel downmix presets.
- Per-track subtitle selection, MP4 `mov_text` conversion and subtitle burn-in.
- Resize, crop, deinterlace and automatic black-border detection.
- HDR10, HLG, HDR10+, SDR tone mapping and Dolby Vision RPU workflows.
- **Dolby Vision via `dovi_tool`** (RPU extraction + x265 injection).
- Two-pass `loudnorm` loudness normalization.
- Software, quality-based, bitrate and two-pass encoding modes.
- Full stream-copy remux mode and audio-only extraction.
- Output selection uses a filename without extension plus an explicit container
  selector; MP4 is muxed directly by FFmpeg.
- MKV encoding writes raw video/audio/subtitle streams first, then uses
  `mkvmerge` when available or FFmpeg stream copy as a fallback.
- **No-mux mode**: export video/audio/subtitle streams as separate files to
  mux them yourself (mkvmerge/mp4box/ffmpeg).
- Clip trimming, chapter and metadata preservation.
- NVIDIA NVENC, Intel QSV, AMD AMF, VAAPI and VideoToolbox detection (offered
  only when the hardware is actually present and working).
- Batch processing: add a whole folder to the queue.
- **Tools - Muxing tab**: merge video/audio/subtitle files into one MKV
  (mkvmerge or ffmpeg stream copy) with per-track language, forced/default and
  delay.
- Encoding queue with live progress, ETA, persistence and post-encode actions.
- Editable command preview and one-off custom command execution.
- In-app `profile.txt` editor.
- `ffplay` playback, filtered preview and thumbnail extraction.
- AviSynth+ script processing with FFMS2 source support, plugin paths, template
  editor, editable filter list and AviSynth-aware FFmpeg command generation.
- Encoder option profiles for x264, x265, VVC/x266 (`libvvenc` when available)
  and AV1 backends, including custom FFmpeg options.
- Optional external audio pipelines using LAME, FAAC and `oggenc`.
- Drag & drop files and folders onto the window.
- Guided Quick Encode wizard with preflight validation and progressive expert
  options.
- Blu-ray ISO/BDMV source selection through libbluray, with playlist, angle and
  chapter controls when the system provides libbluray.
- Static FFmpeg + `dovi_tool` download manager.
- Light/dark theme, persistent settings and log-to-file.

## Quick Start

Requirements:

- Python 3.10 or newer.
- PyQt6.
- FFmpeg, FFprobe and FFplay in `PATH`, or in `applications/`.
- Optional: `dovi_tool` for Dolby Vision RPU processing.
- Optional: AviSynth+ and source plugins such as FFMS2 for script processing.
- Optional: LAME, FAAC and `vorbis-tools` (`oggenc`) for external audio paths.
- Optional: `mkvtoolnix-cli` for preferred MKV muxing with `mkvmerge`.
- Optional: `libbluray` and `bd_info` for ISO/BDMV playlist sources.

```bash
python3 -m pip install PyQt6
python3 ffmpegx.py
```

If FFmpeg is not installed, start the application and use the **FFmpeg** tab to
download a static build. The same tab can download `dovi_tool` for Dolby Vision.

On Arch Linux, the relevant packages are:

```bash
sudo pacman -S --needed ffmpeg avisynthplus ffms2 devil vorbis-tools lame faac mkvtoolnix-cli
```

For Blu-ray source scanning also install:

```bash
sudo pacman -S --needed libbluray
```

`devil` supplies `libIL.so.1`, required by the optional image-sequence plugin
that ships with the Arch AviSynth+ package. The FFmpeg build must expose the
`avisynth` demuxer; x266/VVC requires an FFmpeg build with `libvvenc` or
`libx266`, which is not guaranteed by the standard Arch repositories.

## Main Workflow

The main window places the **Video processing** selector between **Source File**
and **Video Encoding**. Choose **FFmpeg** for the normal FFmpeg filter chain, or
choose **AviSynth+** to reveal the **AviSynth+** tab. That tab provides generated
or external `.avs` scripts, source filters, plugin paths, filter templates and
an editable **Insert filter** list. Type a filter name such as
`TemporalDegrain2` or a complete call such as `TemporalDegrain2()`, then click
**Insert** to add it to the script and the list.

The **Encoder options** tab is always available for codec-specific x264, x265,
x266/VVC and AV1 settings. The **Tools - Muxing** tab follows it and merges
separate video, audio and subtitle files without re-encoding. Other specialist
tools, such as Blu-ray handling, profiles, binary downloads and logs, remain
available through **Advanced options**.

## Documentation

Read the complete user manual here:

**[MANUAL.md](MANUAL.md)**

## Tests

The command-building logic lives in `autoffmpeg/core.py` and has no Qt
dependency, so it can be unit tested without a display or an installed FFmpeg:

```bash
python3 -m unittest discover -s tests -v
```

The real-media matrix uses `test_multitrack.mkv` and writes a complete JSON and
Markdown report under `test_reports/`. It creates each output in a temporary
directory, runs the actual `EncodeThread`/FFmpeg pipeline, probes the result and
checks every expected video, audio and subtitle stream:

```bash
python3 tests/run_media_suite.py
```

Use `--limit 10` for a short development run. The opt-in unittest wrapper is:

```bash
AUTOFFMPEG_FULL_MATRIX=1 python3 -m unittest tests.test_multitrack_matrix -v
```

The matrix records unavailable capabilities such as x266 when the installed
FFmpeg lacks `libvvenc`/`libx266` instead of silently pretending to test them.
The current full matrix covers 288 real encode combinations, including the
worker's sequential two-pass path, raw-track MKV muxing and subtitle burn-in.

## Project Layout

```text
ffmpegx.py              Launcher
autoffmpeg/             Application package
  config.py             Constants, binaries, download sources, themes
  core.py               Pure command-building logic (testable)
  bluray.py             Blu-ray source and libbluray helpers
  validation.py         Preflight compatibility rules
  wizard.py             Guided Quick Encode workflow
  workers.py            Worker threads (encode, download, crop, hw detect)
  ui.py                 Main window
  app.py                Entry point
profile.txt             Custom video profiles
MANUAL.md               User manual
tests/                  Unit tests
  run_media_suite.py    Real multitrack encode matrix and report generator
test_reports/            JSON/Markdown media regression reports
applications/           Optional local FFmpeg binaries
```

The original PureBasic sources are included for reference in `ffmpegx.pb` and
`ffmpegx_include.pb`.

## FFmpeg, dovi_tool and third-party licensing

AutoFFmpegGui is a front end and does not replace FFmpeg. FFmpeg binaries and
`dovi_tool` are external components with their own licenses and build
configuration. Review the license information of each binary provider and the
codecs/libraries used by the selected build before redistribution, and preserve
the applicable licenses and source/build notices.

## Support

Use the **Log** tab when reporting an issue. Include the operating system,
selected FFmpeg paths, media information, generated command and complete error
output.
