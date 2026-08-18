# -*- coding: utf-8 -*-
# AutoFFmpegGui v2 - PyQt6
# SPDX-License-Identifier: EUPL-1.2
# Licensed under the EUPL v1.2 (see LICENSE file in the project root).
"""Worker threads (no blocking on the GUI thread)."""

import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from .config import BINARY_DIR, IS_WINDOWS, detect_hw_encoders, make_executable
from .core import compute_loudnorm, parse_cropdetect

_PROGRESS_KEYS = re.compile(
    r"^(out_time_us|out_time_ms|out_time|frame|fps|bitrate|total_size|"
    r"dup_frames|drop_frames|speed|progress)\s*=\s*(.*)$")


def _parse_seconds(value):
    """Parse an out_time_us/out_time_ms value into fractional seconds."""
    try:
        return float(value) / 1_000_000.0
    except (TypeError, ValueError):
        return None


class EncodeThread(QThread):
    log_line = pyqtSignal(str)
    progress = pyqtSignal(int, str)
    stats = pyqtSignal(str)
    job_started = pyqtSignal(int, str)
    job_done = pyqtSignal(int, int)
    all_done = pyqtSignal()

    def __init__(self, jobs, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self._proc = None
        self._cancel = False

    def cancel(self):
        self._cancel = True
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def _run_measure(self, measure):
        try:
            proc = subprocess.run(measure.cmd, capture_output=True, text=True,
                                  errors="replace", timeout=600)
            raw = (proc.stdout or "") + "\n" + (proc.stderr or "")
        except Exception:
            return {}
        return compute_loudnorm(raw)

    @staticmethod
    def _substitute(cmd, substitutions):
        if not substitutions:
            return cmd
        out = []
        for part in cmd:
            for token, value in substitutions.items():
                part = part.replace(token, value)
            out.append(part)
        return out

    @staticmethod
    def _cleanup(paths):
        for p in paths:
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                elif os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass

    def run(self):
        total = len(self.jobs)
        for i, job in enumerate(self.jobs):
            if self._cancel:
                break
            self.job_started.emit(i, job.label)

            cmd = job.cmd
            if job.measures:
                substitutions = {}
                for measure in job.measures:
                    values = self._run_measure(measure)
                    for token, kind in measure.tokens.items():
                        substitutions[token] = values.get(kind, "0")
                cmd = self._substitute(cmd, substitutions)

            try:
                self._proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, errors="replace")
            except OSError as e:
                self.log_line.emit(f"[error] cannot start process: {e}")
                self.job_done.emit(i, -1)
                continue

            start = time.time()
            last_emit = 0.0
            frac = 0.0
            best_frac = 0.0
            fps = speed = "-"
            for line in self._proc.stdout:
                line = line.rstrip("\n")
                m = _PROGRESS_KEYS.match(line.strip())
                if m:
                    key, value = m.group(1), m.group(2).strip()
                    if key in ("out_time_us", "out_time_ms", "out_time"):
                        secs = None
                        if key == "out_time":
                            mt = re.search(r"(\d+):(\d+):(\d+)(?:\.(\d+))?",
                                           value)
                            if mt:
                                h, mi, s = (int(mt.group(1)), int(mt.group(2)),
                                            int(mt.group(3)))
                                fs = mt.group(4) or ""
                                frac_s = float("0." + fs) if fs else 0.0
                                secs = h * 3600 + mi * 60 + s + frac_s
                        else:
                            secs = _parse_seconds(value)
                        if secs is not None and job.duration:
                            frac = min(1.0, secs / job.duration)
                            if frac > best_frac:
                                best_frac = frac
                            pct = int(((i + best_frac) / total) * 100)
                            self.progress.emit(pct, job.label)
                    elif key == "fps":
                        fps = value
                    elif key == "speed":
                        speed = value.rstrip("x") + "x"
                    now = time.time()
                    if now - last_emit >= 0.4:
                        last_emit = now
                        elapsed = now - start
                        bf = best_frac if best_frac > 0.01 else frac
                        eta = elapsed * (1 - bf) / bf if bf > 0.01 else elapsed
                        self.stats.emit(
                            f"fps {fps}  ·  {speed}  ·  "
                            f"ETA {int(eta // 60):02d}:{int(eta % 60):02d}")
                    continue
                if line:
                    self.log_line.emit(line)
                if self._cancel:
                    self._proc.terminate()
                    break

            self._proc.wait()
            self._cleanup(job.cleanup)
            self.job_done.emit(i, self._proc.returncode)
        self.all_done.emit()


class CropThread(QThread):
    finished_ok = pyqtSignal(object)  # (w, h, x, y) or None

    def __init__(self, cmd, parent=None):
        super().__init__(parent)
        self.cmd = cmd

    def run(self):
        try:
            proc = subprocess.Popen(self.cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, text=True,
                                    errors="replace")
            out = proc.stderr.read()
            proc.wait()
            self.finished_ok.emit(parse_cropdetect(out))
        except Exception:
            self.finished_ok.emit(None)


class HwDetectThread(QThread):
    result = pyqtSignal(set)

    def __init__(self, ffmpeg, parent=None):
        super().__init__(parent)
        self.ffmpeg = ffmpeg

    def run(self):
        self.result.emit(detect_hw_encoders(self.ffmpeg))


class DownloadThread(QThread):
    """Download + extract a static archive with required/optional binaries."""

    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, url, label, required, optional=(), fallbacks=(),
                 parent=None):
        super().__init__(parent)
        self.url = url
        self.label = label
        self.required = tuple(required)
        self.optional = tuple(optional)
        self.fallbacks = list(fallbacks)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    @staticmethod
    def binary_path(name):
        return os.path.join(BINARY_DIR, name + (".exe" if IS_WINDOWS else ""))

    @classmethod
    def has_binary(cls, name):
        return os.path.exists(cls.binary_path(name))

    def _download(self, url, dest):
        request = urllib.request.Request(
            url, headers={"User-Agent": "AutoFFmpegGui/2"})
        with urllib.request.urlopen(request, timeout=120) as response, \
                open(dest, "wb") as out:
            total = int(response.headers.get("Content-Length", 0) or 0)
            done = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if total:
                    self.progress.emit(min(95, int(done * 95 / total)))
                if self._cancel:
                    raise RuntimeError("download cancelled")

    def _extract(self, archive, names):
        installed = []
        if archive.endswith(".zip"):
            with zipfile.ZipFile(archive) as package:
                members = package.namelist()
                for name in names:
                    member = next((m for m in members
                                   if Path(m).name.lower() == name + ".exe"),
                                  None)
                    if not member:
                        continue
                    target = self.binary_path(name)
                    with package.open(member) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    installed.append(name)
        else:
            mode = "r:xz" if archive.endswith(".xz") else "r:gz"
            with tarfile.open(archive, mode=mode) as package:
                members = package.getmembers()
                for name in names:
                    member = next((m for m in members
                                   if Path(m.name).name == name), None)
                    if not member:
                        continue
                    source = package.extractfile(member)
                    if source is None:
                        continue
                    target = self.binary_path(name)
                    with source, open(target, "wb") as dst:
                        shutil.copyfileobj(source, dst)
                    make_executable(target)
                    installed.append(name)
        return installed

    def run(self):
        suffix = (".zip" if self.url.lower().endswith(".zip")
                  else ".tar.xz" if self.url.lower().endswith(".xz")
                  else ".tar.gz")
        archive = os.path.join(tempfile.gettempdir(),
                               "autoffmpeg-static-download" + suffix)
        try:
            self.status.emit(f"Downloading {self.label}...")
            self._download(self.url, archive)
            self.status.emit("Extracting binaries...")
            os.makedirs(BINARY_DIR, exist_ok=True)
            installed = self._extract(archive, self.required + self.optional)

            missing = [n for n in self.required if not self.has_binary(n)]
            if missing:
                raise RuntimeError(
                    f"required binary not found in archive: {', '.join(missing)}")

            for name in self.optional:
                if self.has_binary(name):
                    continue
                system = shutil.which(name)
                if system:
                    self.status.emit(f"Using system {name}: {system}")
                    shutil.copy2(system, self.binary_path(name))
                    make_executable(self.binary_path(name))
                    installed.append(f"{name} (system fallback)")
                    continue
                for fallback_url, fallback_label in self.fallbacks:
                    fsuffix = (".zip" if fallback_url.lower().endswith(".zip")
                               else ".tar.xz")
                    farchive = os.path.join(
                        tempfile.gettempdir(),
                        f"autoffmpeg-fallback-{name}{fsuffix}")
                    try:
                        self.status.emit(
                            f"Downloading {name} fallback: {fallback_label}...")
                        self._download(fallback_url, farchive)
                        self._extract(farchive, (name,))
                        if self.has_binary(name):
                            installed.append(f"{name} (fallback archive)")
                            break
                    except Exception as exc:
                        self.status.emit(f"{name} fallback failed: {exc}")
                    finally:
                        try:
                            os.remove(farchive)
                        except OSError:
                            pass
                if not self.has_binary(name):
                    raise RuntimeError(f"could not find {name} anywhere")

            self.status.emit(f"Extraction complete: {', '.join(installed)}")
            self.progress.emit(100)
            self.succeeded.emit(BINARY_DIR)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            try:
                os.remove(archive)
            except OSError:
                pass
