#!/usr/bin/env python3
"""
VE3 Tool - 2 Chrome FULL Mode
=============================
Chi tiết TOÀN BỘ scenes - chất lượng cao nhất.

Workflow:
1. Chrome 1: Excel (full) -> nv/loc -> scenes chẵn (ảnh+video) -> đợi Chrome 2 -> VISUAL
2. Chrome 2: Đợi Excel -> scenes lẻ (ảnh+video) -> xong

So sánh với BASIC:
- BASIC: Chi tiết phần đầu (8s), video chỉ Chrome 1
- FULL:  Chi tiết TOÀN BỘ, video 2 Chrome song song

Usage:
    python run_2chrome_full.py
"""

import subprocess
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).parent

print(f"""
{'='*60}
  VE3 TOOL - 2 CHROME FULL MODE
{'='*60}

  Mode:     FULL (chi tiết TOÀN BỘ scenes)

  Chrome 1: Excel (full) + nv/loc + scenes CHẴN (ảnh+video) + VISUAL
  Chrome 2: Scenes LẺ (ảnh+video)

  Video:    2 Chrome SONG SONG (nhanh gấp đôi!)

{'='*60}
""")

# Tự động mở 2 CMD trên Windows
if sys.platform == 'win32':
    print("Đang mở 2 CMD windows...")
    subprocess.Popen(f'start cmd /k "cd /d {TOOL_DIR} && python _run_chrome1_full.py"', shell=True)
    subprocess.Popen(f'start cmd /k "cd /d {TOOL_DIR} && python _run_chrome2_full.py"', shell=True)
    print("Done! 2 CMD windows đã mở.")
    print("\nChỉ cần đợi - tất cả tự động!")
else:
    print("Trên Linux/Mac, chạy thủ công trong 2 terminal:")
    print(f"  Terminal 1: python {TOOL_DIR}/_run_chrome1_full.py")
    print(f"  Terminal 2: python {TOOL_DIR}/_run_chrome2_full.py")
