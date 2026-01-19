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
from pathlib import Path

TOOL_DIR = Path(__file__).parent

print(f"""
{'='*60}
  VE3 TOOL - 2 CHROME BASIC MODE
{'='*60}

  Mode:     BASIC (chi tiết phần đầu, giới hạn 8s)
  Chrome 1: Excel (basic) + nv/loc + scenes chẵn + video + VISUAL
  Chrome 2: Scenes lẻ (1,3,5,...)

{'='*60}
""")

# Tự động mở 2 CMD trên Windows
if sys.platform == 'win32':
    print("Đang mở 2 CMD windows...")
    subprocess.Popen(f'start cmd /k "cd /d {TOOL_DIR} && python _run_chrome1.py"', shell=True)
    subprocess.Popen(f'start cmd /k "cd /d {TOOL_DIR} && python _run_chrome2.py"', shell=True)
    print("Done! 2 CMD windows đã mở.")
    print("\nChỉ cần đợi - tất cả tự động!")
else:
    print("Trên Linux/Mac, chạy thủ công trong 2 terminal:")
    print(f"  Terminal 1: python {TOOL_DIR}/_run_chrome1.py")
    print(f"  Terminal 2: python {TOOL_DIR}/_run_chrome2.py")
