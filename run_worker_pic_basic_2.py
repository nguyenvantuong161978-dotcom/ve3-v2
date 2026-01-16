#!/usr/bin/env python3
"""
VE3 Tool - Chạy 2 Chrome song song
==================================
Mở 2 terminal và chạy:
- Terminal 1: python run_worker_pic_basic.py
- Terminal 2: python run_worker_pic_basic_chrome2.py
"""

import subprocess
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).parent

print(f"""
{'='*60}
  CHẠY 2 CHROME SONG SONG
{'='*60}

Mở 2 CMD/Terminal riêng biệt:

=== Terminal 1 (Chrome 1) ===
python run_worker_pic_basic.py

=== Terminal 2 (Chrome 2) ===
python run_worker_pic_basic_chrome2.py

{'='*60}
""")

# Tự động mở 2 CMD trên Windows
if sys.platform == 'win32':
    print("Đang mở 2 CMD windows...")
    subprocess.Popen(f'start cmd /k "cd /d {TOOL_DIR} && python run_worker_pic_basic.py"', shell=True)
    subprocess.Popen(f'start cmd /k "cd /d {TOOL_DIR} && python run_worker_pic_basic_chrome2.py"', shell=True)
    print("Done! 2 CMD windows đã mở.")
