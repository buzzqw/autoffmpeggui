# AutoFFmpegGui

AutoFFmpegGui is a desktop front end for FFmpeg, built with Python and PyQt6.
It combines a friendly graphical workflow with direct access to FFmpeg's
encoding power: advanced video codecs, per-track audio encoding, subtitle
selection, HDR workflows, hardware acceleration, custom profiles, queues and
static FFmpeg downloads.

The application is designed for people who want reliable FFmpeg commands
without having to build them by hand for every movie, TV episode, archive,
phone or web delivery job.

## Highlights

- Modern cross-platform PyQt6 interface.
- Automatic `ffprobe` analysis of resolution, frame rate, duration, HDR data,
  audio tracks and subtitle tracks.
- H.264, H.265/HEVC, AV1, VP9, MPEG-4, Xvid, MPEG-2, WMV and lossless/archive
  workflows.
- Software encoding with quality, bitrate and two-pass modes.
- Hardware encoder detection for NVIDIA NVENC, Intel QSV, AMD AMF, VAAPI and
  Apple VideoToolbox when supported by the installed FFmpeg build.
- Individual audio-track checkboxes: include or remove each track separately.
- Individual audio codec, bitrate, channel and sampling-rate settings for
  every selected track.
- AAC, MP3, FLAC, Vorbis, AC-3 and stream-copy audio modes.
- Individual subtitle-track selection with MP4-compatible subtitle conversion
  to `mov_text`.
- Resize, crop, percentage scaling, aspect-ratio display and automatic
  `cropdetect`.
- Deinterlacing with `yadif`.
- HDR10, HLG, HDR10+, Dolby Vision source-RPU workflows and SDR tone mapping.
- HDR metadata controls for mastering display and MaxCLL/MaxFALL.
- Built-in profiles for scene-style encoding, TV playback, phones, tablets,
  web delivery, editing mezzanine formats and long-term archives.
- User-editable `profile.txt` custom profiles.
- Encoding queue with live progress, FPS, speed, ETA and complete FFmpeg log.
- Input playback and filtered preview through `ffplay`.
- FFmpeg tab with static-binary download, source URLs and installation status.
- Automatic `ffplay` fallback from the system or a separate static archive when
  the main FFmpeg archive does not contain it.
- Light and dark themes.
- Persistent settings stored in `config.ini`.
- PayPal support button for the project.

## Requirements

- Python 3.10 or newer is recommended.
- PyQt6.
- FFmpeg, FFprobe and FFplay in `PATH`, or in the local `applications/`
  directory.

If FFmpeg is not installed, use the **FFmpeg** tab inside the application. The
download manager installs the required binaries into `applications/` and gives
them priority over the system installation.

The automatic static-build workflow currently targets:

- Linux `x86_64` / `amd64`.
- Windows 64-bit.

Other platforms can still be used with manually installed FFmpeg binaries.

## Installation

Clone the repository and enter the project directory:

```bash
git clone <repository-url>
cd autoffmpeggui
```

Create and activate a virtual environment if desired:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install PyQt6:

```bash
python3 -m pip install PyQt6
```

Start the application:

```bash
python3 ffmpegx.py
```

On Windows, use:

```powershell
py ffmpegx.py
```

## First Run

1. Start AutoFFmpegGui.
2. If FFmpeg is missing, open the **FFmpeg** tab.
3. Review the displayed download source and URL.
4. Click **Download latest static FFmpeg**.
5. Follow the progress in the tab and in the **Log** tab.
6. Return to **Audio / Video** and open a media file.

The application analyzes the file with `ffprobe` and fills the available audio
and subtitle tracks automatically.

## User Manual

### Files

The **Files** panel is always visible at the top of the window.

- **Input**: select the source media file with **Browse...**.
- **Play**: open the input in `ffplay` without filters.
- **Preview**: preview the current resize, crop, deinterlace and HDR filter
  chain with `ffplay`.
- **Output**: enter an output path or select one with **Browse...**.

When no output path is selected, AutoFFmpegGui creates a default output beside
the input file. The extension is chosen from the selected video family when
possible.

### Audio / Video

The **Audio / Video** tab contains the main encoding controls.

#### Video encoding

- **Preset**: choose a built-in or custom video profile.
- **Mode**:
  - **Quality (CRF)** for quality-based encoding.
  - **1-pass bitrate** for a single bitrate-controlled pass.
  - **2-pass bitrate** for bitrate allocation over two passes.
  - **Copy video** to avoid re-encoding the video stream.
- **HW accel**: select a detected hardware encoder when available.
- **Quality**: adjust CRF or qscale depending on the codec family.
- **Bitrate**: target video bitrate in kbit/s.
- **Target MB**: calculate a video bitrate from a target file size and the
  selected audio bitrates.
- **FPS**: preserve the source rate or force a supported frame rate.
- **Frames**: limit the number of encoded frames.
- **Deinterlace**: enable the `yadif` filter for interlaced sources.

The application avoids using hardware encoders for HDR modes that require a
software 10-bit HEVC workflow. It also converts unsupported hardware two-pass
requests to a supported one-pass mode.

#### Audio tracks

Every detected audio stream appears as an independent row.

For each row:

1. Check or uncheck the track to include or remove it.
2. Select its codec.
3. Select or type its bitrate in kbit/s.
4. Select the output channel count, or keep `original`.
5. Select or type the sampling rate, or keep `auto`.

Available audio modes are AAC, MP3, FLAC, OGG/Vorbis, AC-3 and Copy.

This means one source can be converted, for example, to AAC stereo for a
phone, AC-3 5.1 for a TV and stream-copy for an additional original track in
the same output file.

The optional global audio controls are:

- **Normalize loudness**: apply FFmpeg's `loudnorm` filter to encoded audio
  tracks.
- **Gain**: apply a volume adjustment in dB to encoded audio tracks.

Copy-mode tracks are not filtered or resampled, because doing so would require
re-encoding them.

#### Subtitle tracks

Each detected subtitle stream has its own checkbox. Select only the subtitles
that should be included in the output.

- MP4 outputs use FFmpeg's `mov_text` subtitle codec.
- Other supported containers use subtitle stream copy where appropriate.
- If no subtitle is selected, subtitles are disabled with `-sn`.

#### Resize and crop

- Enable **Allow resize / crop** to activate video geometry controls.
- Enter a target width and height.
- Choose a dimension modulus such as 2, 4, 8, 16 or 32.
- Use **Size %** for proportional scaling.
- Enter crop values for left, right, top and bottom.
- Use **Auto crop** to let FFmpeg detect black borders.
- **DAR** displays the resulting display aspect ratio.

#### HDR / Color

Available modes include:

- Auto, matching the source when HDR metadata is detected.
- SDR tone mapping to BT.709.
- HDR10 with BT.2020/PQ metadata.
- HLG with BT.2020/HLG metadata.
- HDR10+ using a metadata JSON file.
- Dolby Vision using the source RPU when supported by the source and FFmpeg
  build.

For HDR workflows, the interface exposes:

- HDR10+ metadata file selection.
- Master display metadata.
- MaxCLL/MaxFALL metadata.

HDR10+ metadata requires a valid JSON file generated by a compatible tool. If
the metadata file is unavailable, the application falls back to static HDR10
metadata and reports this in the log.

### Queue

Use **Add to Queue** to store the current job without starting it.

The **Queue** tab allows you to:

- Review queued jobs.
- Remove selected jobs.
- Clear the queue.
- Start all queued jobs with **Start Queue**.

Queued jobs retain the FFmpeg command built when they were added.

### Encoding and progress

The **Encoding** panel shows:

- Overall progress.
- Current job.
- FPS.
- Encoding speed.
- Estimated time remaining.
- Current status.

Use **Cancel** to request process termination. The **Log** tab contains the
complete generated command and FFmpeg output for troubleshooting.

### FFmpeg download manager

The **FFmpeg** tab displays:

- The current platform.
- The main static-build source URL.
- The separate `ffplay` fallback source URL when available.
- Download progress.
- Extraction and installation status.

The download sequence is:

1. Download the main static FFmpeg archive.
2. Extract `ffmpeg` and `ffprobe`.
3. Extract `ffplay` if it exists in the main archive.
4. If `ffplay` is missing, try the system `ffplay`.
5. If no system `ffplay` is available, download and extract the fallback
   `ffplay` archive.
6. Fail with a clear error if `ffplay` cannot be found from any source.

All download, progress, extraction and fallback events are also written to the
**Log** tab.

Click **Open applications folder** to inspect the locally selected binaries.

### Info and Log

The **Info** tab shows FFmpeg version information and the analyzed media
streams.

The **Log** tab shows:

- Application messages.
- Generated FFmpeg commands.
- FFmpeg and FFprobe output.
- Crop detection output.
- Download progress and extraction messages.
- Hardware encoder detection messages.

Use **Clear log** to remove the current log contents.

### Themes and settings

The status bar contains the light/dark theme button. Settings are stored in
`config.ini`, including:

- Window geometry.
- Theme.
- Last directory.
- Video preset and encoding mode.
- Quality and bitrate values.
- HDR values.
- Resize and audio-processing preferences.

## Custom Profiles

Custom profiles are loaded from `profile.txt` in the project directory.

The basic format is:

```text
Profile name;FFmpeg video arguments
```

Example:

```text
Web H.264;-c:v libx264 -preset slow -profile:v high -pix_fmt yuv420p -movflags +faststart
```

The GUI adds the selected quality or bitrate settings only when appropriate for
the codec family. Fixed profile options such as a lossless `-crf 0`, explicit
pixel format or preset are preserved.

The included profiles cover:

- x264 scene and Web-DL style encodes.
- x265 8-bit and 10-bit encodes.
- AV1 and VP9 web encodes.
- Xvid and MPEG-4 legacy playback.
- TV and USB playback.
- Phones and tablets.
- YouTube/Vimeo-style web delivery.
- ProRes and DNxHR editing mezzanine files.
- FFV1, H.265 and AV1 archive encodes.

### Profile guidelines

- Keep video options in `profile.txt`; audio and subtitle options are managed
  by the GUI.
- Do not add a second `-crf` unless the profile is intentionally fixed-quality.
- Use a container compatible with the selected codec and device.
- Test device-specific profiles with a short sample before encoding a full
  library.
- Very slow presets and lossless codecs can require substantial CPU time and
  storage.

## Hardware Acceleration

Hardware acceleration is detected from the selected FFmpeg binary. The menu is
populated only when matching encoders are reported by `ffmpeg -encoders`.

Hardware encoding can be much faster, but it may provide different quality or
compression efficiency than software x264/x265/AV1 encoding. Use software
encoding when maximum compression efficiency or advanced HDR control matters
more than speed.

Hardware support also depends on:

- GPU model and driver.
- Operating-system permissions.
- FFmpeg build configuration.
- Input/output pixel format and codec.

## Troubleshooting

### `ffmpeg`, `ffprobe` or `ffplay` not found

Open the **FFmpeg** tab and download a static build. Alternatively, install
FFmpeg through the operating system and make sure all three commands work:

```bash
ffmpeg -version
ffprobe -version
ffplay -version
```

The **Info** tab and startup log show the exact paths selected by the
application.

### FFmpeg download fails

Check the **Log** tab for:

- The exact source URL.
- Network or TLS errors.
- Archive extraction errors.
- Missing required executables.

The application requires all three tools for the complete workflow, including
preview and playback. If the main archive has no `ffplay`, the application
tries the system binary and then the displayed fallback source.

### Hardware encoder is not listed

Confirm that the installed FFmpeg build exposes the encoder:

```bash
ffmpeg -hide_banner -encoders
```

Then verify the GPU driver and select `None` to use software encoding.

### HDR output is not as expected

- Confirm that the source contains HDR metadata.
- Use **Auto (match source)** for a source-preserving workflow.
- Use SDR tone mapping when the target device is SDR.
- Verify the master display and MaxCLL/MaxFALL values.
- For HDR10+, select a valid metadata JSON file.
- Review the generated command in the **Log** tab.

### A device cannot play the output

Use a device-oriented profile from `profile.txt`, such as:

- `TV H.264 1080p (USB)`.
- `Phone H.264 1080p (wide compatibility)`.
- `Web H.264 (YouTube/Vimeo)`.

Keep `yuv420p`, use a suitable H.264 level and avoid unsupported audio or
subtitle codecs for older devices.

### Encoding fails

Inspect the generated command and FFmpeg output in **Log**. Common causes are:

- An unavailable encoder in the selected FFmpeg build.
- An incompatible codec/container combination.
- An invalid HDR metadata file.
- Insufficient disk space.
- A source file with damaged streams.
- Unsupported hardware acceleration settings.

## Project Layout

```text
ffmpegx.py          Application source
profile.txt         Custom video profiles
config.ini          Persistent user settings
applications/       Optional local FFmpeg binaries
_paypal_logo.png    PayPal support button artwork
```

The original PureBasic sources are also included for reference:

```text
ffmpegx.pb
ffmpegx_include.pb
```

## FFmpeg and Licensing

AutoFFmpegGui is a front end and does not replace FFmpeg. FFmpeg binaries are
external components with their own licensing and build configuration. Review
the license information of the binary provider and the codecs/libraries used
by the selected build before redistribution.

When distributing AutoFFmpegGui together with downloaded FFmpeg binaries,
preserve the applicable FFmpeg license and source/build notices.

## Support

Use the **Log** tab when reporting a problem. Include:

- Operating system.
- FFmpeg version and selected binary paths.
- Input container and stream information from the **Info** tab.
- The generated command.
- The complete error output.

If AutoFFmpegGui is useful to you, the PayPal button in the status bar links to
the project's support page.
