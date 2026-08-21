# -*- coding: utf-8 -*-
"""Blu-ray source discovery and libbluray command helpers."""

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BlurayOptions:
    enabled: bool = False
    path: str = ""
    playlist: int = -1
    angle: int = 0
    chapter: int = 1


def is_bluray_path(path: str) -> bool:
    p = Path(path or "")
    return p.suffix.lower() == ".iso" or (p.is_dir() and
                                          (p / "BDMV").is_dir()) or \
        (p.is_dir() and p.name.upper() == "BDMV")


def bluray_root(path: str) -> str:
    p = Path(path)
    if p.is_dir() and p.name.upper() == "BDMV":
        return str(p.parent)
    return str(p)


def bluray_url(options: BlurayOptions) -> str:
    return "bluray:" + bluray_root(options.path)


def bluray_input_options(options: BlurayOptions):
    args = []
    if options.playlist >= 0:
        args += ["-playlist", str(options.playlist)]
    if options.angle > 0:
        args += ["-angle", str(options.angle)]
    if options.chapter > 1:
        args += ["-chapter", str(options.chapter)]
    return args


def scan_bluray(path: str, tool="bd_info"):
    """Return raw libbluray metadata for diagnostics and future title parsing."""
    try:
        proc = subprocess.run([tool, bluray_root(path)], capture_output=True,
                              text=True, errors="replace", timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc), "raw": ""}
    raw = proc.stdout or proc.stderr or ""
    return {"ok": proc.returncode == 0, "error": (proc.stderr or "").strip(),
            "raw": raw, "titles": parse_bluray_info(raw)}


def parse_bluray_info(raw: str):
    """Parse common bd_info playlist lines without depending on one version."""
    titles = []
    current = None
    for line in (raw or "").splitlines():
        text = line.strip()
        playlist = re.search(r"(?:playlist|mpls)\s*[:=]\s*(\d{3,5})",
                             text, re.I)
        if playlist:
            if current:
                titles.append(current)
            current = {"playlist": int(playlist.group(1))}
            continue
        if current is None:
            continue
        duration = re.search(r"duration\s*[:=]\s*([0-9:.]+)", text, re.I)
        if duration:
            current["duration"] = duration.group(1)
        chapters = re.search(r"chapters?\s*[:=]\s*(\d+)", text, re.I)
        if chapters:
            current["chapters"] = int(chapters.group(1))
        angles = re.search(r"angles?\s*[:=]\s*(\d+)", text, re.I)
        if angles:
            current["angles"] = int(angles.group(1))
    if current:
        titles.append(current)
    return titles
