#!/usr/bin/env python3
"""
VE3 Tool - Chay 2 Chrome song song
==================================
Entry point duy nhat - chi can chay file nay.

Workflow:
1. Chrome 1: Excel -> nv/loc -> scenes chan -> doi Chrome 2 -> video -> VISUAL
2. Chrome 2: Doi Excel -> scenes le -> xong

Usage:
    python run_2chrome.py
"""

import subprocess
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).parent

print(f"""
{'='*60}
  VE3 TOOL - 2 CHROME PARALLEL MODE
{'='*60}

  Chrome 1: Excel + nv/loc + scenes chan + video + VISUAL
  Chrome 2: Scenes le (1,3,5,...)

{'='*60}
""")

# Tu dong mo 2 CMD tren Windows
if sys.platform == 'win32':
    print("Dang mo 2 CMD windows...")
    subprocess.Popen(f'start cmd /k "cd /d {TOOL_DIR} && python _run_chrome1.py"', shell=True)
    subprocess.Popen(f'start cmd /k "cd /d {TOOL_DIR} && python _run_chrome2.py"', shell=True)
    print("Done! 2 CMD windows da mo.")
    print("\nChi can doi - tat ca tu dong!")
else:
    print("Tren Linux/Mac, chay thu cong trong 2 terminal:")
    print(f"  Terminal 1: python {TOOL_DIR}/_run_chrome1.py")
    print(f"  Terminal 2: python {TOOL_DIR}/_run_chrome2.py")
