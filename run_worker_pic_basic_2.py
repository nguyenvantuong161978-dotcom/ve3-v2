#!/usr/bin/env python3
"""
VE3 Tool - Worker PIC BASIC 2 Chrome Mode
==========================================
Chạy 2 Chrome SONG SONG để tạo ảnh nhanh hơn.
Dùng subprocess như run_worker đã làm.

Config trong settings.yaml:
  chrome_portable: "path/to/GoogleChromePortable/GoogleChromePortable.exe"
  chrome_portable_2: "path/to/GoogleChromePortable - Copy/GoogleChromePortable.exe"

Usage:
    python run_worker_pic_basic_2.py                     (quét và xử lý tự động)
    python run_worker_pic_basic_2.py AR47-0028           (chạy 1 project cụ thể)
    python run_worker_pic_basic_2.py --chrome2           (chạy Chrome 2 - internal)
"""

import sys
import os
import time
import threading
import subprocess
from pathlib import Path

# Add current directory to path
TOOL_DIR = Path(__file__).parent
sys.path.insert(0, str(TOOL_DIR))

# Import từ run_worker (dùng chung logic)
from run_worker import (
    detect_auto_path,
    get_channel_from_folder,
    matches_channel,
    is_project_complete_on_master,
    has_excel_with_prompts,
    copy_from_master,
    SCAN_INTERVAL,
)

# Import từ run_worker_pic_basic
from run_worker_pic_basic import (
    create_excel_with_api_basic,
    is_local_pic_complete,
)

# Detect paths
AUTO_PATH = detect_auto_path()
if AUTO_PATH:
    MASTER_PROJECTS = AUTO_PATH / "ve3-tool-simple" / "PROJECTS"
    MASTER_VISUAL = AUTO_PATH / "VISUAL"
else:
    MASTER_PROJECTS = Path(r"\\tsclient\D\AUTO\ve3-tool-simple\PROJECTS")
    MASTER_VISUAL = Path(r"\\tsclient\D\AUTO\VISUAL")

LOCAL_PROJECTS = TOOL_DIR / "PROJECTS"
WORKER_CHANNEL = get_channel_from_folder()


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


def run_chrome2_worker(excel_path: str):
    """
    Chạy Chrome 2 worker (gọi từ subprocess).
    Đọc chrome_portable_2 từ settings.yaml.
    """
    print(f"[Chrome2] Starting worker...")

    chrome1, chrome2 = load_chrome_paths()

    if not chrome2:
        print(f"[Chrome2] ERROR: chrome_portable_2 not configured!")
        return

    print(f"[Chrome2] Using Chrome: {chrome2}")
    print(f"[Chrome2] Excel: {excel_path}")

    try:
        from modules.smart_engine import SmartEngine

        # Create engine with worker_id=1 (Chrome 2)
        # Truyền chrome_portable vào constructor để KHÔNG bị override
        engine = SmartEngine(
            worker_id=1,
            total_workers=2,
            chrome_portable=chrome2  # Override settings.yaml
        )

        print(f"[Chrome2] Running engine...")

        # Run engine - images only
        result = engine.run(excel_path, skip_compose=True, skip_video=True)

        print(f"[Chrome2] Done! Result: {result}")

    except Exception as e:
        print(f"[Chrome2] ERROR: {e}")
        import traceback
        traceback.print_exc()


def process_project_pic_basic_2(code: str, callback=None) -> bool:
    """Process a single project using 2 Chrome instances in parallel (subprocess)."""

    def log(msg, level="INFO"):
        if callback:
            callback(msg, level)
        else:
            print(msg)

    log(f"\n{'='*60}")
    log(f"[PIC BASIC 2-CHROME] Processing: {code}")
    log(f"{'='*60}")

    # Load Chrome paths
    chrome1, chrome2 = load_chrome_paths()

    if not chrome1:
        log("Chrome 1 path not configured!", "ERROR")
        return False

    if not chrome2:
        log("Chrome 2 path not configured! Set chrome_portable_2 in settings.yaml", "WARN")
        log("Falling back to single Chrome mode...", "WARN")
        # Fallback to single chrome - just run pic_basic
        from run_worker_pic_basic import process_project_pic_basic
        return process_project_pic_basic(code, callback)

    log(f"Chrome1: {chrome1}")
    log(f"Chrome2: {chrome2}")

    # Step 1: Check if already done on master
    if is_project_complete_on_master(code):
        log(f"  Already in VISUAL folder, skip!")
        return True

    # Step 2: Copy from master
    local_dir = copy_from_master(code)
    if not local_dir:
        return False

    # Step 3: Check/Create Excel (BASIC mode)
    excel_path = local_dir / f"{code}_prompts.xlsx"
    srt_path = local_dir / f"{code}.srt"

    if not excel_path.exists():
        if srt_path.exists():
            log(f"  No Excel found, creating (BASIC mode)...")
            if not create_excel_with_api_basic(local_dir, code, callback):
                log(f"  Failed to create Excel, skip!", "ERROR")
                return False
        else:
            log(f"  No Excel and no SRT, skip!")
            return False
    elif not has_excel_with_prompts(local_dir, code):
        log(f"  Excel empty/corrupt, recreating (BASIC mode)...")
        excel_path.unlink()
        if not create_excel_with_api_basic(local_dir, code, callback):
            log(f"  Failed to recreate Excel, skip!", "ERROR")
            return False

    # Step 4: Run 2 Chrome in parallel using subprocess (like run_worker)
    log(f"\n{'='*60}")
    log(f"  Starting 2 Chrome instances in PARALLEL")
    log(f"{'='*60}")

    # === START CHROME 2 AS SUBPROCESS (như run_worker làm) ===
    chrome2_cmd = [
        sys.executable,
        str(TOOL_DIR / "run_worker_pic_basic_2.py"),
        "--chrome2",
        "--excel", str(excel_path)
    ]

    log(f"\n[PARALLEL] Starting Chrome2 subprocess...")
    log(f"[PARALLEL] Cmd: {' '.join(chrome2_cmd)}")

    chrome2_process = subprocess.Popen(
        chrome2_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    log(f"[PARALLEL] Chrome2 PID: {chrome2_process.pid}")

    # Thread to print Chrome2 output
    def print_chrome2_output():
        try:
            for line in chrome2_process.stdout:
                # Safe print - handle encoding errors
                try:
                    print(line.rstrip())
                except UnicodeEncodeError:
                    print(line.encode('ascii', 'replace').decode('ascii').rstrip())
        except Exception as e:
            print(f"[Chrome2 Output Error] {e}")

    chrome2_thread = threading.Thread(target=print_chrome2_output, daemon=True)
    chrome2_thread.start()

    # === RUN CHROME 1 IN MAIN PROCESS ===
    log(f"\n[PARALLEL] Starting Chrome1 (main process)...")

    try:
        from modules.smart_engine import SmartEngine

        # Create engine with worker_id=0 (Chrome 1)
        engine = SmartEngine(
            worker_id=0,
            total_workers=2
        )

        # chrome_portable đã được load từ settings.yaml trong SmartEngine
        # Nếu muốn override, uncomment dòng dưới:
        # engine.chrome_portable = chrome1

        log(f"[Chrome1] Running engine...")

        # Run engine - images only
        result = engine.run(str(excel_path), callback=log, skip_compose=True, skip_video=True)

        log(f"[Chrome1] Done! Result: {result}")

    except Exception as e:
        log(f"[Chrome1] ERROR: {e}", "ERROR")
        import traceback
        traceback.print_exc()

    # Wait for Chrome 2 to finish
    log(f"\n[PARALLEL] Chrome1 done. Waiting for Chrome2...")
    try:
        chrome2_process.wait(timeout=600)  # 10 min timeout
        log(f"[PARALLEL] Chrome2 exit code: {chrome2_process.returncode}")
    except subprocess.TimeoutExpired:
        log(f"Chrome2 timeout, terminating...", "WARN")
        chrome2_process.terminate()

    log(f"\n{'='*60}")
    log(f"  Both Chrome finished!")
    log(f"{'='*60}")

    # Step 5: Check completion
    if is_local_pic_complete(local_dir, code):
        log(f"  Images complete!")
        return True
    else:
        log(f"  Images incomplete", "WARN")
        return False


def scan_incomplete_local_projects() -> list:
    """Scan local PROJECTS for incomplete projects."""
    incomplete = []

    if not LOCAL_PROJECTS.exists():
        return incomplete

    for item in LOCAL_PROJECTS.iterdir():
        if not item.is_dir():
            continue

        code = item.name

        if not matches_channel(code):
            continue

        if is_project_complete_on_master(code):
            continue

        if is_local_pic_complete(item, code):
            continue

        srt_path = item / f"{code}.srt"
        if has_excel_with_prompts(item, code):
            print(f"    - {code}: incomplete (has Excel, no images)")
            incomplete.append(code)
        elif srt_path.exists():
            print(f"    - {code}: has SRT, no Excel")
            incomplete.append(code)

    return sorted(incomplete)


def scan_master_projects() -> list:
    """Scan master PROJECTS folder for pending projects."""
    pending = []

    if not MASTER_PROJECTS.exists():
        return pending

    for item in MASTER_PROJECTS.iterdir():
        if not item.is_dir():
            continue

        code = item.name

        if not matches_channel(code):
            continue

        if is_project_complete_on_master(code):
            continue

        srt_path = item / f"{code}.srt"

        if has_excel_with_prompts(item, code):
            print(f"    - {code}: ready (has prompts)")
            pending.append(code)
        elif srt_path.exists():
            print(f"    - {code}: has SRT")
            pending.append(code)

    return sorted(pending)


def run_scan_loop():
    """Run continuous scan loop for IMAGE generation (2-Chrome mode)."""
    print(f"\n{'='*60}")
    print(f"  VE3 TOOL - WORKER PIC BASIC 2-CHROME")
    print(f"{'='*60}")
    print(f"  Worker folder:   {TOOL_DIR.parent.name}")
    print(f"  Channel filter:  {WORKER_CHANNEL or 'ALL'}")
    print(f"  Mode:            2-CHROME PARALLEL (subprocess)")
    print(f"{'='*60}")

    chrome1, chrome2 = load_chrome_paths()
    print(f"  Chrome1: {chrome1 or 'NOT CONFIGURED'}")
    print(f"  Chrome2: {chrome2 or 'NOT CONFIGURED'}")
    print(f"{'='*60}")

    cycle = 0

    while True:
        cycle += 1
        print(f"\n[2-CHROME CYCLE {cycle}] Scanning...")

        incomplete_local = scan_incomplete_local_projects()
        pending_master = scan_master_projects()
        pending = list(dict.fromkeys(incomplete_local + pending_master))

        if not pending:
            print(f"  No pending projects")
            print(f"\n  Waiting {SCAN_INTERVAL}s... (Ctrl+C to stop)")
            try:
                time.sleep(SCAN_INTERVAL)
            except KeyboardInterrupt:
                print("\n\nStopped by user.")
                break
        else:
            print(f"  Found: {len(pending)} pending projects")

            for code in pending:
                try:
                    success = process_project_pic_basic_2(code)
                    if not success:
                        print(f"  Skipping {code}, moving to next...")
                        continue
                except KeyboardInterrupt:
                    print("\n\nStopped by user.")
                    return
                except Exception as e:
                    print(f"  Error processing {code}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue

            print(f"\n  Processed all pending projects!")
            print(f"  Waiting {SCAN_INTERVAL}s... (Ctrl+C to stop)")
            try:
                time.sleep(SCAN_INTERVAL)
            except KeyboardInterrupt:
                print("\n\nStopped by user.")
                break


def main():
    import argparse
    parser = argparse.ArgumentParser(description='VE3 Worker PIC BASIC 2-Chrome')
    parser.add_argument('project', nargs='?', default=None, help='Project code')
    parser.add_argument('--chrome2', action='store_true', help='Run as Chrome2 worker (internal)')
    parser.add_argument('--excel', type=str, default=None, help='Excel path (internal)')
    args = parser.parse_args()

    # Internal mode: run Chrome2 worker (called by subprocess)
    if args.chrome2 and args.excel:
        run_chrome2_worker(args.excel)
        return

    # Normal mode
    if args.project:
        process_project_pic_basic_2(args.project)
    else:
        run_scan_loop()


if __name__ == "__main__":
    main()
