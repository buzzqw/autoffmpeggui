# AutoFFmpegGui

AutoFFmpegGui is a desktop front end for FFmpeg, built with Python and PyQt6.
It combines a friendly graphical workflow with direct access to FFmpeg's
encoding power: advanced video codecs, per-track audio encoding, subtitle
selection, HDR workflows, hardware acceleration, custom profiles, queues and
static FFmpeg downloads.

The application is designed for people who want reliable FFmpeg commands
without having to build them by hand for every movie, TV episode, archive,
phone or web delivery job.

## License

AutoFFmpegGui is licensed under the **European Union Public Licence v1.2**
(EUPL-1.2). See the `LICENSE` file in the project root for the full text.

## Highlights

- Modern cross-platform PyQt6 interface.
- Guided Quick Encode wizard for the common workflow, with specialist options
  hidden until requested.
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
- Dolby Vision RPU processing through `dovi_tool` (extract + x265 injection
  when a Dolby Vision-enabled x265 build is available).
- HDR metadata controls for mastering display and MaxCLL/MaxFALL.
- Two-pass `loudnorm` loudness normalization.
- Subtitle burn-in, clip trimming, chapter and metadata preservation.
- Full stream-copy remux mode and audio-only extraction.
- Batch folder processing, queue persistence and post-encode actions.
- Editable command preview and in-app `profile.txt` editor.
- Drag & drop files and folders, and thumbnail extraction.
- Built-in profiles for scene-style encoding, TV playback, phones, tablets,
  web delivery, editing mezzanine formats and long-term archives.
- User-editable `profile.txt` custom profiles.
- Encoding queue with live progress, FPS, speed, ETA and complete FFmpeg log.
- Input playback and filtered preview through `ffplay`.
- AviSynth+ tab with generated or external `.avs` scripts, FFMS2 templates,
  plugin loading, editable filter insertion and AviSynth-aware video/audio
  stream mapping.
- Encoder options tab for x264, x265, x266/VVC and AV1 profile overrides.
- External audio pipelines for LAME, FAAC and `oggenc` when installed.
- Blu-ray ISO/BDMV source selection through libbluray, including playlist,
  angle and chapter input options.
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

For Linux AviSynth+ processing, install a native AviSynth+ runtime and a source
plugin. On Arch Linux:

```bash
sudo pacman -S --needed avisynthplus ffms2 devil
```

The Arch `ffms2` package installs `/usr/lib/avisynth/libffms2.so`. The `devil`
package is needed by the optional `libimageseq.so` plugin shipped with
`avisynthplus`. Also install `lame`, `faac`, `vorbis-tools` and
`mkvtoolnix-cli` when testing external audio and muxing workflows.
Install `libbluray` for Blu-ray ISO/BDMV scanning. Commercial encrypted discs
are not decrypted by AutoFFmpeg; use a legally obtained decrypted folder or
playlist source.

If FFmpeg is not installed, use the **FFmpeg** tab inside the application. The
download manager installs the required binaries into `applications/` and gives
them priority over the system installation.

Dolby Vision RPU encoding additionally requires an x265/FFmpeg build that
supports the `dolby-vision-rpu` x265 parameter. A standard x265 build may
support HDR10 but not RPU injection; AutoFFmpeg detects this and stops with an
actionable error instead of silently producing HDR10.

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

The **Source File** panel is always visible at the top of the window.

- **Input**: select the source media file with **Browse...** (or drag & drop).
- **Play**: open the input in `ffplay` without filters.
- **Preview**: preview the current resize, crop, deinterlace and HDR filter
  chain with `ffplay`.
- **Shots**: extract preview thumbnails with ffmpeg and open the folder.
- **Add folder**: add every media file in a folder to the queue.
- **Output name**: enter the final path without an extension, or choose the base
  name with **Browse...**.
- **Container**: select `MP4`, `MKV`, `MOV` or `AVI` independently from the
  output name.

When no output name is selected, AutoFFmpegGui creates a default output beside
the input file. The selected container supplies the final extension. MP4 is the
default container for normal H.264/H.265 encoding.

#### Output containers and MKV muxing

MP4 output is encoded and muxed directly by FFmpeg. For normal MKV encoding,
AutoFFmpegGui deliberately separates the operations:

1. Encode the video to an elementary stream.
2. Encode each selected audio track to its raw/container stream.
3. Encode each selected subtitle track separately when supported.
4. Mux the resulting streams into the final MKV.

The final mux uses `mkvmerge` from MKVToolNix when it is installed. If
`mkvmerge` is unavailable, FFmpeg performs the same final operation with stream
copy. This is separate from **Export separate streams (no mux)**, which stops
after the elementary files and does not create a final container.

### Quick Encode wizard

Use **Quick wizard** for the normal workflow. It asks for the source, encoder
profile, quality mode, audio/subtitle tracks and output in a short sequence.
The final page applies the settings to the main window and runs the same
preflight checks as expert mode. The **Video processing** selector between
Source File and Video Encoding chooses FFmpeg or AviSynth+. Selecting
AviSynth+ reveals its tab with the script editor, plugin paths and filter
helpers. Muxing and Encoder options are always available; Advanced options is
reserved for Blu-ray, profiles, binary downloads and logs.

### Blu-ray sources

Click **Blu-ray...** or use the **Blu-ray** tab to select an ISO image or a
folder containing `BDMV`. AutoFFmpeg passes the source to FFmpeg's `bluray`
protocol and exposes:

- automatic playlist selection or an explicit playlist number;
- angle selection;
- starting chapter;
- libbluray scan output for diagnostics.

After **Use and analyze**, the normal audio, subtitle, AviSynth and encoder
workflow is used. Playlist-aware handling is preferred over manually joining
`.m2ts` files, because a Blu-ray title can use seamless branching. Commercial
encrypted media is not decrypted by the application.

### Audio / Video

The **Audio / Video** tab contains the video encoding, resize/crop and HDR
controls. The audio and subtitle track selection lives in the separate
**Tracks** tab.

#### Video encoding

- **Preset**: choose a built-in or custom video profile.
- **Mode**:
  - **Quality (CRF)** for quality-based encoding.
  - **1-pass bitrate** for a single bitrate-controlled pass.
- **2-pass bitrate** for bitrate allocation over two passes.
  - **Copy video** to avoid re-encoding the video stream.
  - **Remux (copy all)** to copy every stream into a new container.
  - **Audio only** to extract the selected audio tracks.
- **Export separate streams (no mux)**: instead of muxing everything into one
  file, write each stream to its own elementary file next to the input
  (for example `name_video.hevc`, `name_audio0.aac`, `name_sub0.srt`). You can
  then mux them yourself with `mkvmerge`, `mp4box` or `ffmpeg`. This option is
  available for the quality and bitrate modes.
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

For software two-pass encoding, pass 1 and pass 2 are executed sequentially by
the worker. The encoder passlog is retained between the two jobs and cleaned
only after pass 2 finishes.

#### Encoder options

The **Encoder options** tab exposes a catalog of common x264, x265, x266/VVC
and AV1 options for the selected profile. Values entered there override the
automatically generated FFmpeg option once, so a profile's `preset`, `crf`,
rate-control or tuning values can be changed without editing the command.
Common choices use drop-down lists, numeric fields reject invalid values, and
boolean options use three-state checkboxes: checked enables the option,
unchecked disables it, and partially checked leaves the encoder default.
The final `custom-option` row accepts options introduced by newer FFmpeg
versions. Empty values are ignored. x266 is represented by `libvvenc` when the
installed FFmpeg provides it; the standard Arch build may not include it.

#### AviSynth+

The **AviSynth+** tab supports two workflows:

- Leave **External script** empty to generate a stable `.avs` file beside the
  output. The template supports `{{INPUT}}`, `{{SOURCE_FILTER}}`,
  `{{PLUGIN_LOADS}}` and `{{VIDEO_FILTERS}}`.
- Select an existing `.avs` file to use it as the complete source.

The **Insert filter** list contains common filters and is editable. Type a
filter name such as `TemporalDegrain2`, or a complete call such as
`TemporalDegrain2()`, then click **Insert**. Custom entries are added to the
list for reuse during the session.

When a script is generated from a normal media file, FFmpeg receives two
inputs: AviSynth supplies the processed video and the original file supplies
audio/subtitles. This prevents AviSynth video processing from removing the
original tracks. Remux-copy mode is intentionally disabled for AviSynth jobs.

On Linux the FFmpeg binary must include the `avisynth` demuxer and the runtime,
source plugin and plugin dependencies must be ABI-compatible. Loading an `.avs`
executes its script and plugins, so only use scripts you trust.

#### Audio tracks

Every detected audio stream appears as an independent row.

For each row:

1. Check or uncheck the track to include or remove it.
2. Select its codec.
3. Select or type its bitrate in kbit/s.
4. Select the output channel count (with downmix presets such as `5.1 ->
   stereo`), or keep `original`.
5. Select or type the sampling rate, or keep `auto`.

Available audio modes are AAC, MP3, FLAC, OGG/Vorbis, AC-3 and Copy.

The **Encoder** selector can use FFmpeg or an external tool. LAME is used for
MP3, FAAC for AAC and `oggenc` for Ogg/Vorbis. External tools receive WAV over
an internal process pipeline, never through a shell. The **extra args** field
passes additional argv options to the selected tool. For LAME, multichannel
source audio is downmixed to stereo automatically unless an explicit channel
count is selected.

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
- Blu-ray PGS and other bitmap subtitles cannot be stored in MP4. Select `MKV`
  or deselect the bitmap subtitle track.
- If no subtitle is selected, subtitles are disabled with `-sn`.
- Tick **Burn** on a text subtitle track to hardcode it into the video.
  Bitmap subtitles (e.g. PGS) cannot be burned in this way.

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
- HDR10 using BT.2020/PQ metadata.
- HLG with BT.2020/HLG metadata.
- HDR10+ using a metadata JSON file.
- Dolby Vision using the source RPU when the source carries a DV RPU and
  `dovi_tool` is available (see "Dolby Vision" below).

For HDR workflows, the interface exposes:

- HDR10+ metadata file selection.
- Master display metadata.
- MaxCLL/MaxFALL metadata.

HDR10+ metadata requires a valid JSON file generated by a compatible tool. If
the metadata file is unavailable, the application falls back to static HDR10
metadata and reports this in the log.

#### Dolby Vision

The **Dolby Vision (source RPU)** mode re-encodes the video as 10-bit HEVC and
injects the source Dolby Vision RPU using `dovi_tool`:

1. Extract the HEVC elementary stream from the source.
2. Extract the RPU with `dovi_tool extract-rpu`.
3. For profile 5 sources, convert the RPU to profile 8.1.
4. Encode with x265 and inject the RPU via `dolby-vision-rpu` /
   `dolby-vision-profile`.

`dovi_tool` can be downloaded from the **FFmpeg** tab. If it is missing, the
application falls back to static HDR10 and reports this in the log.

### Tools - Muxing

The **Tools - Muxing** tab follows **Encoder options** and merges separate video,
audio and subtitle files into a single MKV (in the style of MKVToolNix GUI):

1. Add video, audio and subtitle files with the **Add video / audio /
   subtitle** buttons.
2. For each track, optionally set the language, the `forced` and `default`
   flags, and a delay in milliseconds.
3. Choose an output file.
4. Click **Mux with mkvmerge** (MKVToolNix, preferred for delay support) or
   **Mux with ffmpeg** (fallback, stream copy).

No re-encoding happens: the streams are copied as-is.

### Queue

Use **Add to Queue** to store the current job without starting it.

The **Queue** tab allows you to:

- Review queued jobs.
- Remove selected jobs.
- Clear the queue.
- Move jobs up or down.
- Duplicate a job.
- Inspect the exact command or external pipeline for a selected job.
- Save and load the queue (`autoffmpeg_queue.json`).
- Start all queued jobs with **Start Queue**.

Queued jobs retain the FFmpeg command built when they were added.

#### Batch processing

Use **Add folder** in the Files panel (or drop a folder onto the window) to add
every supported media file in a folder to the queue. Batch jobs reuse the
current video settings and copy the audio and subtitle streams.

#### Post-encode actions

The **After** selector in the Encoding panel runs an action when the queue
finishes: show a notification, open the output folder, or schedule a shutdown.

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

#### Command preview

The **Generated command** panel shows the exact FFmpeg command for the current
settings. Use **Preview command** to refresh it, edit it, and **Run edited
command** to execute a custom one-off command.

#### Profiles editor

The **Profiles** tab edits `profile.txt` directly. Save to persist the changes
and reload the preset list, or reload from disk to discard changes.

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

For MKV jobs the log also shows the raw stream commands followed by the final
`mkvmerge` or FFmpeg mux command. A failed pass or mux job marks the complete
job as failed and prevents the normal post-encode action.

Use **Clear log** to remove the current log contents.

All log messages are also appended to `autoffmpeg.log` in the project
directory. The file is rotated automatically when it grows above 2 MB.

### Real media regression suite

Run the complete multitrack regression suite from the repository root:

```bash
python3 tests/run_media_suite.py
```

The suite uses `test_multitrack.mkv`, which contains one HEVC video, four audio
tracks and three subtitle tracks. It executes real output jobs for x264, x265
and available AV1, all installed FFmpeg and external audio encoders, three
subtitle modes, and AviSynth enabled/disabled. Each case creates an output in a
temporary directory and checks its size and `ffprobe` stream list. Reports are
written to:

- `test_reports/multitrack_media_report.json` for machine-readable details;
- `test_reports/multitrack_media_report.md` for a human-readable summary.

The checked matrix currently contains 288 real combinations and includes the
GUI-independent worker path for raw MKV muxing, two-pass sequencing and
subtitle burn-in. A separate headless GUI smoke test verifies output-base and
container selection before a first job is built.

Use `python3 tests/run_media_suite.py --limit 10` during development. The full
matrix can also be run through unittest with
`AUTOFFMPEG_FULL_MATRIX=1 python3 -m unittest tests.test_multitrack_matrix -v`.
Unavailable encoders are listed explicitly in the report.

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
- Output container preference.
- AviSynth enabled state, script template and plugin paths.

The selected processing engine is restored on startup. If a previous AviSynth
job should not affect a normal encode, select **FFmpeg** in Video processing
and confirm that the generated command does not contain an `.avs` input.

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

Hardware acceleration is detected from the selected FFmpeg binary and only
offered when the hardware is truly usable. The application:

1. Lists the hardware encoders compiled into the FFmpeg build
   (`ffmpeg -encoders`).
2. Probes each candidate with a short real encode so that the device (GPU or
   DRM node) must actually be present and working.

An encoder that is compiled in but has no working device (for example a build
with NVENC support running on a machine without an NVIDIA GPU) is not offered
in the menu.

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

Confirm that the installed FFmpeg build exposes the encoder and that the
device works:

```bash
ffmpeg -hide_banner -encoders
```

The menu only offers an accelerator after a short real encode succeeds, so an
encoder compiled into FFmpeg but without a working GPU/device is never shown.
Verify the GPU driver and select `None` to use software encoding.

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
ffmpegx.py          Launcher
autoffmpeg/         Application package (core, validation, wizard, bluray, ui)
profile.txt         Custom video profiles
config.ini          Persistent user settings
applications/       Optional local FFmpeg binaries
tests/              Unit and real-media regression tests
test_reports/       JSON/Markdown media matrix reports
_paypal_logo.png    PayPal support button artwork
```

The original PureBasic sources are also included for reference:

```text
ffmpegx.pb
ffmpegx_include.pb
```

## FFmpeg and Licensing

AutoFFmpegGui is licensed under the EUPL v1.2. It is a front end and does not
replace FFmpeg. FFmpeg binaries and `dovi_tool` are external components with
their own licensing and build configuration. Review the license information of
the binary provider and the codecs/libraries used by the selected build before
redistribution.

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
