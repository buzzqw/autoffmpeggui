# -*- coding: utf-8 -*-
# AutoFFmpegGui v2 - PyQt6
# SPDX-License-Identifier: EUPL-1.2
# Licensed under the EUPL v1.2 (see LICENSE file in the project root).
"""Application entry point."""

import os
import sys

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from .config import APP_DIR
from .ui import AutoFfmpegGui


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("AutoFFmpegGui")
    mono = os.path.join(APP_DIR, "DejaVuSansMono.ttf")
    app.setFont(QFont(mono, 9) if os.path.exists(mono) else QFont("DejaVu Sans", 9))
    win = AutoFfmpegGui()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
