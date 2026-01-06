#!/usr/bin/env python3
"""
VE3 Tool - Installation Script
==============================
Script cai dat tu dong cho VE3 Tool.

Usage:
    python install.py
    python install.py --dev    # Cai them dev dependencies
"""

import subprocess
import sys
import os
from pathlib import Path


def run_command(cmd, check=True):
    """Chay lenh va in output."""
    print(f"\n> {cmd}")
    result = subprocess.run(cmd, shell=True, check=check)
    return result.returncode == 0


def main():
    print("""
╔════════════════════════════════════════════════════════════╗
║              VE3 TOOL - INSTALLATION                       ║
╠════════════════════════════════════════════════════════════╣
║  Tool tu dong tao anh/video tu voice                       ║
║  Su dung browser automation (khong can API key)            ║
╚════════════════════════════════════════════════════════════╝
""")

    # Check Python version
    print(f"[1/5] Kiem tra Python version...")
    py_version = sys.version_info
    if py_version < (3, 8):
        print(f"  ERROR: Can Python 3.8+, hien tai: {py_version.major}.{py_version.minor}")
        sys.exit(1)
    print(f"  OK: Python {py_version.major}.{py_version.minor}.{py_version.micro}")

    # Install core dependencies
    print(f"\n[2/5] Cai dat core dependencies...")
    if not run_command(f"{sys.executable} -m pip install --upgrade pip", check=False):
        print("  WARNING: Khong upgrade duoc pip")

    requirements_file = Path(__file__).parent / "requirements.txt"
    if requirements_file.exists():
        run_command(f"{sys.executable} -m pip install -r {requirements_file}")
    else:
        # Fallback: install manually
        packages = [
            "pyyaml>=6.0",
            "openpyxl>=3.1.0",
            "requests>=2.31.0",
            "pillow>=10.0.0",
            "selenium>=4.15.0",
            "undetected-chromedriver>=3.5.0",
        ]
        run_command(f"{sys.executable} -m pip install {' '.join(packages)}")

    print("  OK: Core dependencies installed")

    # Check Chrome
    print(f"\n[3/5] Kiem tra Chrome...")
    chrome_paths = [
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]

    chrome_found = False
    for path in chrome_paths:
        if os.path.exists(path):
            print(f"  OK: Chrome found at {path}")
            chrome_found = True
            break

    if not chrome_found:
        print("  WARNING: Khong tim thay Chrome.")
        print("  Vui long cai dat Google Chrome truoc khi su dung.")
        print("  Download: https://www.google.com/chrome/")

    # Create directories
    print(f"\n[4/5] Tao cac thu muc can thiet...")
    base_dir = Path(__file__).parent

    dirs_to_create = [
        base_dir / "chrome_profiles",
        base_dir / "output",
        base_dir / "output" / "images",
        base_dir / "output" / "videos",
        base_dir / "PROJECTS",
    ]

    for d in dirs_to_create:
        d.mkdir(parents=True, exist_ok=True)
        print(f"  Created: {d}")

    # Test import
    print(f"\n[5/5] Kiem tra import modules...")
    try:
        sys.path.insert(0, str(base_dir))
        from modules.smart_engine import SmartEngine
        from modules.google_flow_api import GoogleFlowAPI
        from modules.excel_manager import PromptWorkbook
        from modules.prompts_generator import PromptGenerator
        from modules.utils import get_logger
        print("  OK: All modules imported successfully")
    except ImportError as e:
        print(f"  WARNING: Import error: {e}")
        print("  Mot so chuc nang co the khong hoat dong")

    # Done
    print(f"""
╔════════════════════════════════════════════════════════════╗
║              CAI DAT HOAN TAT!                              ║
╠════════════════════════════════════════════════════════════╣
║                                                            ║
║  BUOC TIEP THEO:                                           ║
║                                                            ║
║  1. Cau hinh config/settings.yaml:                         ║
║     - chrome_path: duong dan Chrome                        ║
║     - chrome_profile: duong dan Profile (chrome://version) ║
║     - Them API keys: groq, deepseek, gemini (tuy chon)     ║
║                                                            ║
║  2. Chay tool:                                             ║
║     python ve3_pro.py                                      ║
║                                                            ║
║  3. Trong GUI:                                             ║
║     - Chon file voice (.mp3, .wav)                         ║
║     - Click BAT DAU                                        ║
║     - Tool tu dong: Voice -> SRT -> Prompts -> Images      ║
║                                                            ║
╚════════════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    main()
