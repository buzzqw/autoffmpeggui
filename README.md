# AutoFFmpegGui

AutoFFmpegGui is a PyQt6 desktop front end for FFmpeg. It provides a practical
workflow for converting, previewing and organizing media while keeping the
power of FFmpeg available through custom profiles and generated commands.

## Features

- H.264, H.265/HEVC, AV1, VP9, MPEG-4, Xvid, MPEG-2, WMV and archive codecs.
- Per-track audio selection and encoding.
- Per-track subtitle selection.
- Resize, crop, deinterlace and automatic black-border detection.
- HDR10, HLG, HDR10+, Dolby Vision RPU and SDR tone mapping workflows.
- Software, quality-based, bitrate and two-pass encoding modes.
- NVIDIA NVENC, Intel QSV, AMD AMF, VAAPI and VideoToolbox detection.
- TV, phone, web, editing and archive profiles in `profile.txt`.
- Encoding queue, live progress, ETA and full command log.
- `ffplay` playback and filtered preview.
- Static FFmpeg download manager with `ffplay` fallback handling.
- Light/dark theme and persistent settings.

## Quick Start

Requirements:

- Python 3.10 or newer.
- PyQt6.
- FFmpeg, FFprobe and FFplay in `PATH`, or in `applications/`.

```bash
python3 -m pip install PyQt6
python3 ffmpegx.py
```

If FFmpeg is not installed, start the application and use the **FFmpeg** tab to
download a static build. The application displays the source URL and reports
download and extraction progress in the **Log** tab.

## Documentation

Read the complete English user manual here:

**[MANUAL.md](MANUAL.md)**

The manual covers installation, the complete interface, audio and subtitle
selection, HDR workflows, custom profiles, hardware acceleration, FFmpeg
downloads and troubleshooting.

## Project Files

```text
ffmpegx.py       PyQt6 application
profile.txt      Custom video profiles
MANUAL.md        Complete user manual
config.ini       Persistent settings
applications/    Optional local FFmpeg binaries
```

The original PureBasic sources are included for reference in `ffmpegx.pb` and
`ffmpegx_include.pb`.

## License And FFmpeg

AutoFFmpegGui is a front end and does not replace FFmpeg. Downloaded FFmpeg
binaries and included codecs/libraries have their own licenses. Preserve the
applicable FFmpeg license and source/build notices when redistributing them.

## Support

Use the **Log** tab when reporting an issue. Include the operating system,
selected FFmpeg paths, media information, generated command and complete error
output.
