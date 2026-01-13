#!/usr/bin/env python3
"""
VE3 Tool - Worker PIC Mode (Image Generation ONLY)
Chỉ tạo ảnh, không tạo video.

Usage:
    python run_worker_pic.py                     (quét và xử lý tự động)
    python run_worker_pic.py AR47-0028           (chạy 1 project cụ thể)
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
    POSSIBLE_AUTO_PATHS,
    get_channel_from_folder,
    matches_channel,
    is_project_complete_on_master,
    has_excel_with_prompts,
    needs_api_completion,
    create_excel_with_api,
    complete_excel_with_api,
    copy_from_master,
    copy_to_visual,
    delete_local_project,
    SCAN_INTERVAL,
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

# Global worker settings
WORKER_ID = 0
TOTAL_WORKERS = 1


def is_local_pic_complete(project_dir: Path, name: str) -> bool:
    """Check if local project has images created (ignore videos)."""
    img_dir = project_dir / "img"
    if not img_dir.exists():
        return False

    # Count images only (png, jpg) - exclude videos
    img_files = list(img_dir.glob("*.png")) + list(img_dir.glob("*.jpg"))

    if len(img_files) == 0:
        return False

    # Check Excel to see expected scene count
    try:
        from modules.excel_manager import PromptWorkbook
        excel_path = project_dir / f"{name}_prompts.xlsx"
        if excel_path.exists():
            wb = PromptWorkbook(str(excel_path))
            scenes = wb.get_scenes()
            expected = len([s for s in scenes if s.img_prompt])

            if len(img_files) >= expected:
                print(f"    [{name}] Images: {len(img_files)}/{expected} - COMPLETE")
                return True
            else:
                print(f"    [{name}] Images: {len(img_files)}/{expected} - incomplete")
                return False
    except Exception as e:
        print(f"    [{name}] Warning: {e}")

    return len(img_files) > 0


def process_project_pic(code: str, callback=None) -> bool:
    """Process a single project - IMAGE ONLY (no video)."""

    def log(msg, level="INFO"):
        if callback:
            callback(msg, level)
        else:
            print(msg)

    log(f"\n{'='*60}")
    log(f"[PIC] Processing: {code}")
    log(f"{'='*60}")

    # Step 1: Check if already done on master
    if is_project_complete_on_master(code):
        log(f"  ⏭️ Already in VISUAL folder, skip!")
        return True

    # Step 2: Copy from master
    local_dir = copy_from_master(code)
    if not local_dir:
        return False

    # Step 3: Check/Create Excel
    excel_path = local_dir / f"{code}_prompts.xlsx"
    srt_path = local_dir / f"{code}.srt"

    if not excel_path.exists():
        if srt_path.exists():
            log(f"  📋 No Excel found, creating from SRT...")
            if not create_excel_with_api(local_dir, code):
                log(f"  ❌ Failed to create Excel, skip!")
                return False
        else:
            log(f"  ⏭️ No Excel and no SRT, skip!")
            return False
    elif not has_excel_with_prompts(local_dir, code):
        log(f"  📋 Excel empty/corrupt, recreating...")
        excel_path.unlink()
        if not create_excel_with_api(local_dir, code):
            log(f"  ❌ Failed to recreate Excel, skip!")
            return False
    elif needs_api_completion(local_dir, code):
        log(f"  📋 Excel has [FALLBACK] prompts, trying API...")
        complete_excel_with_api(local_dir, code)

    # Step 4: Create images ONLY (skip video)
    try:
        from modules.smart_engine import SmartEngine

        engine = SmartEngine(
            worker_id=WORKER_ID,
            total_workers=TOTAL_WORKERS
        )

        log(f"  📋 Excel: {excel_path.name}")
        log(f"  🖼️ MODE: Image ONLY (no video)")

        # Run engine - images only, skip video generation
        result = engine.run(str(excel_path), callback=callback, skip_compose=True, skip_video=True)

        if result.get('error'):
            log(f"  ❌ Error: {result.get('error')}", "ERROR")
            return False

    except Exception as e:
        log(f"  ❌ Exception: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return False

    # Step 5: Check completion and copy to VISUAL
    if is_local_pic_complete(local_dir, code):
        log(f"  ✅ Images complete!")
        # Don't copy to VISUAL yet - let run_worker_video handle videos
        # Or copy if user wants pic-only workflow
        return True
    else:
        log(f"  ⚠️ Images incomplete", "WARN")
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

        excel_path = item / f"{code}_prompts.xlsx"
        srt_path = item / f"{code}.srt"

        if has_excel_with_prompts(item, code):
            print(f"    - {code}: ready (has prompts)")
            pending.append(code)
        elif srt_path.exists():
            print(f"    - {code}: has SRT")
            pending.append(code)

    return sorted(pending)


def run_scan_loop():
    """Run continuous scan loop for IMAGE generation."""
    global AUTO_PATH, MASTER_PROJECTS, MASTER_VISUAL

    print(f"\n{'='*60}")
    print(f"  VE3 TOOL - WORKER PIC (Image Only)")
    print(f"{'='*60}")
    print(f"  Worker folder:   {TOOL_DIR.parent.name}")
    print(f"  Channel filter:  {WORKER_CHANNEL or 'ALL'}")
    print(f"  Mode:            IMAGE ONLY (no video)")
    print(f"{'='*60}")

    cycle = 0

    while True:
        cycle += 1
        print(f"\n[PIC CYCLE {cycle}] Scanning...")

        # Find incomplete local + pending master
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
                    success = process_project_pic(code)
                    if not success:
                        print(f"  ⏭️ Skipping {code}, moving to next...")
                        continue
                except KeyboardInterrupt:
                    print("\n\nStopped by user.")
                    return
                except Exception as e:
                    print(f"  ❌ Error processing {code}: {e}")
                    continue

            print(f"\n  ✅ Processed all pending projects!")
            print(f"  Waiting {SCAN_INTERVAL}s... (Ctrl+C to stop)")
            try:
                time.sleep(SCAN_INTERVAL)
            except KeyboardInterrupt:
                print("\n\nStopped by user.")
                break


def main():
    global WORKER_ID, TOTAL_WORKERS

    import argparse
    parser = argparse.ArgumentParser(description='VE3 Worker PIC - Image Generation Only')
    parser.add_argument('project', nargs='?', default=None, help='Project code')
    parser.add_argument('--worker-id', type=int, default=0, help='Worker ID')
    parser.add_argument('--total-workers', type=int, default=1, help='Total workers')
    args = parser.parse_args()

    WORKER_ID = args.worker_id
    TOTAL_WORKERS = args.total_workers

    if args.project:
        process_project_pic(args.project)
    else:
        run_scan_loop()


if __name__ == "__main__":
    main()
