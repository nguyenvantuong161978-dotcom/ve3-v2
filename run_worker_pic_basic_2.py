#!/usr/bin/env python3
"""
VE3 Tool - Worker PIC BASIC 2 Chrome Mode
==========================================
Chạy 2 Chrome SONG SONG - ĐƠN GIẢN: 2 subprocess độc lập.

Mỗi subprocess chạy run_worker_pic_basic.py với:
- Chrome 1: chrome_portable (mặc định), worker_id=0
- Chrome 2: chrome_portable_2, worker_id=1

Config trong settings.yaml:
  chrome_portable: "path/to/GoogleChromePortable/GoogleChromePortable.exe"
  chrome_portable_2: "path/to/GoogleChromePortable - Copy/GoogleChromePortable.exe"

Usage:
    python run_worker_pic_basic_2.py                     (quét và xử lý tự động)
    python run_worker_pic_basic_2.py AR47-0028           (chạy 1 project cụ thể)
"""

import sys
import os
import time
import subprocess
import threading
from pathlib import Path

TOOL_DIR = Path(__file__).parent
sys.path.insert(0, str(TOOL_DIR))


def load_chrome_paths() -> tuple:
    """Load 2 Chrome portable paths from settings.yaml."""
    import yaml

    settings_path = TOOL_DIR / "config" / "settings.yaml"
    if not settings_path.exists():
        return None, None

    with open(settings_path, 'r', encoding='utf-8') as f:
        settings = yaml.safe_load(f) or {}

    chrome1 = settings.get('chrome_portable', '')
    chrome2 = settings.get('chrome_portable_2', '')

    # Auto-detect if not configured
    if not chrome1:
        default_chrome = TOOL_DIR / "GoogleChromePortable" / "GoogleChromePortable.exe"
        if default_chrome.exists():
            chrome1 = str(default_chrome)

    if not chrome2:
        copy_chrome = TOOL_DIR / "GoogleChromePortable - Copy" / "GoogleChromePortable.exe"
        if copy_chrome.exists():
            chrome2 = str(copy_chrome)

    return chrome1, chrome2


def run_parallel_pic(project: str = None):
    """
    Chạy 2 subprocess run_worker_pic_basic.py độc lập.

    - Chrome 1: Scenes chẵn (2,4,6,...) + nv/loc
    - Chrome 2: Scenes lẻ (1,3,5,...)
    """
    chrome1, chrome2 = load_chrome_paths()

    print(f"\n{'='*60}")
    print(f"  VE3 TOOL - PIC BASIC 2-CHROME (Subprocess Mode)")
    print(f"{'='*60}")
    print(f"  Chrome 1: {chrome1 or 'NOT CONFIGURED'}")
    print(f"  Chrome 2: {chrome2 or 'NOT CONFIGURED'}")
    print(f"{'='*60}")

    if not chrome1:
        print("ERROR: Chrome 1 not configured!")
        return

    if not chrome2:
        print("WARNING: Chrome 2 not configured, running single Chrome mode...")
        # Fallback to single chrome
        cmd = [sys.executable, str(TOOL_DIR / "run_worker_pic_basic.py")]
        if project:
            cmd.append(project)
        subprocess.run(cmd)
        return

    # Build commands
    # Chrome 1: worker 0, scenes chẵn + nv/loc
    cmd1 = [sys.executable, str(TOOL_DIR / "run_worker_pic_basic.py")]
    if project:
        cmd1.append(project)

    # Chrome 2: worker 1, scenes lẻ
    cmd2 = [sys.executable, str(TOOL_DIR / "run_worker_pic_basic.py")]
    if project:
        cmd2.append(project)

    # Environment variables for parallel mode
    env1 = os.environ.copy()
    env1['CHROME_WORKER_ID'] = '0'
    env1['CHROME_TOTAL_WORKERS'] = '2'
    env1['CHROME_PORTABLE'] = chrome1

    env2 = os.environ.copy()
    env2['CHROME_WORKER_ID'] = '1'
    env2['CHROME_TOTAL_WORKERS'] = '2'
    env2['CHROME_PORTABLE'] = chrome2
    env2['CHROME_PORT_OFFSET'] = '100'  # Port 9322 thay vì 9222

    print(f"\n[PARALLEL] Starting Chrome 1 (worker 0)...")
    print(f"[PARALLEL] Starting Chrome 2 (worker 1)...")

    # Start both processes
    proc1 = subprocess.Popen(
        cmd1,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding='utf-8',
        errors='replace',
        env=env1
    )

    # Delay before starting Chrome 2
    time.sleep(5)

    proc2 = subprocess.Popen(
        cmd2,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding='utf-8',
        errors='replace',
        env=env2
    )

    print(f"[PARALLEL] Chrome 1 PID: {proc1.pid}")
    print(f"[PARALLEL] Chrome 2 PID: {proc2.pid}")

    # Threads to print output
    def print_output(proc, prefix):
        try:
            for line in proc.stdout:
                try:
                    print(f"{prefix} {line.rstrip()}")
                except:
                    pass
        except:
            pass

    t1 = threading.Thread(target=print_output, args=(proc1, "[Chrome1]"), daemon=True)
    t2 = threading.Thread(target=print_output, args=(proc2, "[Chrome2]"), daemon=True)
    t1.start()
    t2.start()

    # Wait for both to finish
    try:
        proc1.wait()
        proc2.wait()
    except KeyboardInterrupt:
        print("\n\n[PARALLEL] Stopping...")
        proc1.terminate()
        proc2.terminate()
        try:
            proc1.wait(timeout=5)
            proc2.wait(timeout=5)
        except:
            proc1.kill()
            proc2.kill()

    print(f"\n[PARALLEL] Both Chrome finished!")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='VE3 Worker PIC BASIC 2-Chrome')
    parser.add_argument('project', nargs='?', default=None, help='Project code')
    args = parser.parse_args()

    run_parallel_pic(args.project)


if __name__ == "__main__":
    main()
