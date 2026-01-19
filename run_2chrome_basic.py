#!/usr/bin/env python3
"""
VE3 Tool - 2 Chrome BASIC Mode
==============================
Chi tiết PHẦN ĐẦU (giới hạn 8s) - nhanh hơn, ít chi phí API hơn.

Workflow:
1. Chrome 1: Excel (basic) -> nv/loc -> scenes chẵn -> đợi Chrome 2 -> video (phần đầu) -> VISUAL
2. Chrome 2: Đợi Excel -> scenes lẻ -> xong

Usage:
    python run_2chrome_basic.py
"""

import subprocess
import sys
import os
from pathlib import Path

# Fix Windows encoding
if sys.platform == "win32":
    if sys.stdout:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    os.environ['PYTHONIOENCODING'] = 'utf-8'

TOOL_DIR = Path(__file__).parent

print(f"""
{'='*60}
  VE3 TOOL - 2 CHROME BASIC MODE
{'='*60}

  Mode:     BASIC (chi tiet phan dau, gioi han 8s)
  Chrome 1: Excel (basic) + nv/loc + scenes chan + video + VISUAL
  Chrome 2: Scenes le (1,3,5,...)

{'='*60}
""")

# Tự động mở 2 CMD trên Windows
if sys.platform == 'win32':
    import time
    print("Đang mở Chrome 1...")
    subprocess.Popen(f'start cmd /k "cd /d {TOOL_DIR} && python _run_chrome1.py"', shell=True)
    print("Đợi 30 giây để Chrome 1 khởi động...")
    time.sleep(30)
    print("Đang mở Chrome 2...")
    subprocess.Popen(f'start cmd /k "cd /d {TOOL_DIR} && python _run_chrome2.py"', shell=True)
    print("Done! 2 CMD windows đã mở.")
    print("\nChỉ cần đợi - tất cả tự động!")
else:
    print("Trên Linux/Mac, chạy thủ công trong 2 terminal:")
    print(f"  Terminal 1: python {TOOL_DIR}/_run_chrome1.py")
    print(f"  Terminal 2: python {TOOL_DIR}/_run_chrome2.py")
