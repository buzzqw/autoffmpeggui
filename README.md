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
- **No-mux mode**: export video/audio/subtitle streams as separate files to
  mux them yourself (mkvmerge/mp4box/ffmpeg).
- Clip trimming, chapter and metadata preservation.
- NVIDIA NVENC, Intel QSV, AMD AMF, VAAPI and VideoToolbox detection (offered
  only when the hardware is actually present and working).
- Batch processing: add a whole folder to the queue.
- **Muxing tab**: merge video/audio/subtitle files into one MKV (mkvmerge or
  ffmpeg stream copy) with per-track language, forced/default and delay.
- Encoding queue with live progress, ETA, persistence and post-encode actions.
- Editable command preview and one-off custom command execution.
- In-app `profile.txt` editor.
- `ffplay` playback, filtered preview and thumbnail extraction.
- Drag & drop files and folders onto the window.
- Static FFmpeg + `dovi_tool` download manager.
- Light/dark theme, persistent settings and log-to-file.

## Quick Start

Requirements:

- Python 3.10 or newer.
- PyQt6.
- FFmpeg, FFprobe and FFplay in `PATH`, or in `applications/`.
- Optional: `dovi_tool` for Dolby Vision RPU processing.

```bash
python3 -m pip install PyQt6
python3 ffmpegx.py
```

If FFmpeg is not installed, start the application and use the **FFmpeg** tab to
download a static build. The same tab can download `dovi_tool` for Dolby Vision.

## Documentation

Read the complete user manual here:

**[MANUAL.md](MANUAL.md)**

## Tests

The command-building logic lives in `autoffmpeg/core.py` and has no Qt
dependency, so it can be unit tested without a display or an installed FFmpeg:

```bash
python3 -m unittest discover -s tests -v
```

## Project Layout

```text
ffmpegx.py              Launcher
autoffmpeg/             Application package
  config.py             Constants, binaries, download sources, themes
  core.py               Pure command-building logic (testable)
  workers.py            Worker threads (encode, download, crop, hw detect)
  ui.py                 Main window
  app.py                Entry point
profile.txt             Custom video profiles
MANUAL.md               User manual
tests/                  Unit tests
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
