#!/usr/bin/env python3
"""
VE3 Tool - Worker PIC BASIC Mode - CHROME 2
============================================
Giống hệt run_worker_pic_basic.py nhưng dùng Chrome 2:
- chrome_portable_2 (GoogleChromePortable - Copy)
- worker_id=1, total_workers=2
- profile: pic2

Chạy SONG SONG với run_worker_pic_basic.py:
- Terminal 1: python run_worker_pic_basic.py
- Terminal 2: python run_worker_pic_basic_chrome2.py

Usage:
    python run_worker_pic_basic_chrome2.py                     (quét và xử lý tự động)
    python run_worker_pic_basic_chrome2.py AR47-0028           (chạy 1 project cụ thể)
"""

import sys
import os
import time
import shutil
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
else:
    MASTER_PROJECTS = Path(r"\\tsclient\D\AUTO\ve3-tool-simple\PROJECTS")

LOCAL_PROJECTS = TOOL_DIR / "PROJECTS"
WORKER_CHANNEL = get_channel_from_folder()


def load_chrome2_path() -> str:
    """Load chrome_portable_2 from settings.yaml."""
    import yaml
    settings_path = TOOL_DIR / "config" / "settings.yaml"
    if not settings_path.exists():
        return None

    with open(settings_path, 'r', encoding='utf-8') as f:
        settings = yaml.safe_load(f) or {}

    chrome2 = settings.get('chrome_portable_2', '')

    # Auto-detect if not configured
    if not chrome2:
        copy_chrome = TOOL_DIR / "GoogleChromePortable - Copy" / "GoogleChromePortable.exe"
        if copy_chrome.exists():
            chrome2 = str(copy_chrome)

    return chrome2


def process_project_pic_basic_chrome2(code: str, callback=None) -> bool:
    """Process a single project - Chrome 2."""

    def log(msg, level="INFO"):
        if callback:
            callback(msg, level)
        else:
            print(f"[Chrome2] {msg}")

    log(f"\n{'='*60}")
    log(f"Processing: {code}")
    log(f"{'='*60}")

    # Load Chrome 2 path
    chrome2 = load_chrome2_path()
    if not chrome2:
        log("ERROR: chrome_portable_2 not configured!", "ERROR")
        return False

    log(f"Chrome: {chrome2}")

    # Step 1: Check if already done on master
    if is_project_complete_on_master(code):
        log(f"Already in VISUAL folder, skip!")
        return True

    # Step 2: Copy from master
    local_dir = copy_from_master(code)
    if not local_dir:
        return False

    # Step 3: Check/Create Excel (Chrome 1 sẽ tạo, Chrome 2 chỉ đợi)
    excel_path = local_dir / f"{code}_prompts.xlsx"

    # Đợi Chrome 1 tạo Excel (tối đa 60s)
    wait_count = 0
    while not excel_path.exists() and wait_count < 12:
        log(f"Waiting for Excel... ({wait_count * 5}s)")
        time.sleep(5)
        wait_count += 1

    if not excel_path.exists():
        log("No Excel after 60s, skip!")
        return False

    # Step 4: Create images using SmartEngine
    try:
        from modules.smart_engine import SmartEngine

        # Chrome 2: worker_id=1, total_workers=2, dùng chrome_portable_2
        engine = SmartEngine(
            worker_id=1,
            total_workers=2,
            chrome_portable=chrome2,
            assigned_profile="pic2"
        )

        log(f"Excel: {excel_path.name}")
        log(f"Mode: CHROME 2 (scenes lẻ: 1,3,5,...)")

        # Run engine - skip nv/loc (Chrome 1 làm), skip video
        result = engine.run(
            str(excel_path),
            callback=lambda msg, lvl: log(msg, lvl),
            skip_compose=True,
            skip_video=True,
            skip_references=True  # Chrome 1 tạo nv/loc
        )

        if result.get('error'):
            log(f"Error: {result.get('error')}", "ERROR")
            return False

    except Exception as e:
        log(f"Exception: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return False

    # Step 5: Check completion
    if is_local_pic_complete(local_dir, code):
        log(f"Images complete!")
        return True
    else:
        log(f"Images incomplete", "WARN")
        return False


def scan_projects() -> list:
    """Scan for pending projects."""
    pending = []

    # Scan local first
    if LOCAL_PROJECTS.exists():
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
            if has_excel_with_prompts(item, code) or (item / f"{code}.srt").exists():
                print(f"    - {code}")
                pending.append(code)

    # Scan master
    if MASTER_PROJECTS.exists():
        for item in MASTER_PROJECTS.iterdir():
            if not item.is_dir():
                continue
            code = item.name
            if code in pending:
                continue
            if not matches_channel(code):
                continue
            if is_project_complete_on_master(code):
                continue
            if has_excel_with_prompts(item, code) or (item / f"{code}.srt").exists():
                print(f"    - {code}")
                pending.append(code)

    return sorted(pending)


def run_scan_loop():
    """Run continuous scan loop."""
    chrome2 = load_chrome2_path()

    print(f"\n{'='*60}")
    print(f"  VE3 TOOL - WORKER PIC BASIC - CHROME 2")
    print(f"{'='*60}")
    print(f"  Chrome 2:  {chrome2 or 'NOT CONFIGURED'}")
    print(f"  Channel:   {WORKER_CHANNEL or 'ALL'}")
    print(f"  Mode:      Scenes lẻ (1,3,5,...)")
    print(f"{'='*60}")

    if not chrome2:
        print("ERROR: chrome_portable_2 not configured!")
        return

    # Đợi Chrome 1 khởi động trước
    print("\n[Chrome2] Waiting 10s for Chrome 1 to start...")
    time.sleep(10)

    cycle = 0

    while True:
        cycle += 1
        print(f"\n[Chrome2 CYCLE {cycle}] Scanning...")

        pending = scan_projects()

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
                    success = process_project_pic_basic_chrome2(code)
                    if not success:
                        print(f"  [Chrome2] Skipping {code}, moving to next...")
                        continue
                except KeyboardInterrupt:
                    print("\n\nStopped by user.")
                    return
                except Exception as e:
                    print(f"  [Chrome2] Error processing {code}: {e}")
                    continue

            print(f"\n  [Chrome2] Processed all pending projects!")
            print(f"  Waiting {SCAN_INTERVAL}s... (Ctrl+C to stop)")
            try:
                time.sleep(SCAN_INTERVAL)
            except KeyboardInterrupt:
                print("\n\nStopped by user.")
                break


def main():
    import argparse
    parser = argparse.ArgumentParser(description='VE3 Worker PIC BASIC - Chrome 2')
    parser.add_argument('project', nargs='?', default=None, help='Project code')
    args = parser.parse_args()

    if args.project:
        process_project_pic_basic_chrome2(args.project)
    else:
        run_scan_loop()


if __name__ == "__main__":
    main()
