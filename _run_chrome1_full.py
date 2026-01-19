#!/usr/bin/env python3
"""
VE3 Tool - Worker FULL Mode - CHROME 1
======================================
Chi tiết TOÀN BỘ scenes - chất lượng cao nhất.

Khác với BASIC:
- Excel: Chi tiết TẤT CẢ scenes (không giới hạn 8s)
- Video: 2 Chrome song song (Chrome 1 làm video chẵn)

Usage:
    python _run_chrome1_full.py
"""

import sys
import os

# Fix Windows encoding issues
if sys.platform == "win32":
    if sys.stdout:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if sys.stderr:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    os.environ['PYTHONIOENCODING'] = 'utf-8'
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
    copy_to_visual,
    delete_local_project,
    SCAN_INTERVAL,
    create_excel_with_api,  # FULL version - không phải basic
)


def safe_path_exists(path: Path) -> bool:
    """
    Safely check if a path exists, handling network disconnection errors.
    Returns False if path doesn't exist OR if network is disconnected.
    """
    try:
        return path.exists()
    except (OSError, PermissionError) as e:
        # WinError 1167: The device is not connected
        # WinError 53: The network path was not found
        # WinError 64: The specified network name is no longer available
        print(f"  [WARN] Network error checking path: {e}")
        return False


def safe_iterdir(path: Path) -> list:
    """
    Safely iterate over a directory, handling network disconnection errors.
    Returns empty list if path doesn't exist OR if network is disconnected.
    """
    try:
        if not path.exists():
            return []
        return list(path.iterdir())
    except (OSError, PermissionError) as e:
        print(f"  [WARN] Network error listing directory: {e}")
        return []

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


def is_local_pic_complete(project_dir: Path, name: str) -> bool:
    """Check if local project has ALL images created (both Chrome 1 and 2)."""
    img_dir = project_dir / "img"
    if not img_dir.exists():
        return False

    img_files = list(img_dir.glob("*.png")) + list(img_dir.glob("*.jpg"))

    if len(img_files) == 0:
        return False

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


def wait_for_all_images(project_dir: Path, name: str, timeout: int = 600) -> bool:
    """Đợi tất cả ảnh hoàn thành (Chrome 1 + Chrome 2). Timeout mặc định 10 phút."""
    start = time.time()
    while time.time() - start < timeout:
        if is_local_pic_complete(project_dir, name):
            return True
        print(f"    Đợi Chrome 2 hoàn thành... ({int(time.time() - start)}s)")
        time.sleep(10)
    return False


def create_videos_for_project_parallel(project_dir: Path, code: str, callback=None) -> bool:
    """
    Tạo video cho project - PARALLEL MODE (Chrome 1 làm video chẵn).
    Chrome 2 sẽ làm video lẻ song song.
    """
    def log(msg, level="INFO"):
        if callback:
            callback(msg, level)
        else:
            print(msg)

    try:
        from modules.smart_engine import SmartEngine

        excel_path = project_dir / f"{code}_prompts.xlsx"
        if not excel_path.exists():
            log(f"  No Excel found for video creation!", "ERROR")
            return False

        log(f"\n[VIDEO] Creating videos PARALLEL (Chrome 1 = chẵn)...")

        # Chrome 1: worker_id=0, total_workers=2 → video chẵn (2,4,6...)
        engine = SmartEngine(worker_id=0, total_workers=2)

        result = engine.run(
            str(excel_path),
            callback=callback,
            skip_compose=True,
            skip_video=False  # Tạo video
        )

        if result.get('error'):
            log(f"  Video error: {result.get('error')}", "ERROR")
            return False

        log(f"  [OK] Videos (chẵn) created!")
        return True

    except Exception as e:
        log(f"  Video exception: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return False


def is_local_video_complete(project_dir: Path, name: str) -> bool:
    """Check if ALL videos are created."""
    img_dir = project_dir / "img"
    if not img_dir.exists():
        return False

    video_files = list(img_dir.glob("*.mp4"))

    try:
        from modules.excel_manager import PromptWorkbook
        excel_path = project_dir / f"{name}_prompts.xlsx"
        if excel_path.exists():
            wb = PromptWorkbook(str(excel_path))
            scenes = wb.get_scenes()
            # Đếm scenes cần video (có video_prompt hoặc có img và video_count > 0)
            expected_videos = len([s for s in scenes if s.img_prompt])  # Mỗi scene 1 video

            if len(video_files) >= expected_videos:
                print(f"    [{name}] Videos: {len(video_files)}/{expected_videos} - COMPLETE")
                return True
            else:
                print(f"    [{name}] Videos: {len(video_files)}/{expected_videos} - incomplete")
                return False
    except Exception as e:
        print(f"    [{name}] Video check warning: {e}")

    return len(video_files) > 0


def wait_for_all_videos(project_dir: Path, name: str, timeout: int = 1800) -> bool:
    """Đợi tất cả video hoàn thành (Chrome 1 + Chrome 2). Timeout 30 phút."""
    start = time.time()
    while time.time() - start < timeout:
        if is_local_video_complete(project_dir, name):
            return True
        print(f"    Đợi Chrome 2 hoàn thành video... ({int(time.time() - start)}s)")
        time.sleep(15)
    return False


def process_project_full(code: str, callback=None) -> bool:
    """Process a single project - FULL mode (chi tiết toàn bộ)."""

    def log(msg, level="INFO"):
        if callback:
            callback(msg, level)
        else:
            print(msg)

    log(f"\n{'='*60}")
    log(f"[FULL MODE - Chrome 1] Processing: {code}")
    log(f"{'='*60}")

    # Step 1: Check if already done on master
    if is_project_complete_on_master(code):
        log(f"  Already in VISUAL folder, skip!")
        return True

    # Step 2: Copy from master
    local_dir = copy_from_master(code)
    if not local_dir:
        return False

    # Step 3: Check/Create Excel (FULL mode - chi tiết toàn bộ)
    excel_path = local_dir / f"{code}_prompts.xlsx"
    srt_path = local_dir / f"{code}.srt"

    if not excel_path.exists():
        if srt_path.exists():
            log(f"  No Excel found, creating (FULL mode - all scenes)...")
            if not create_excel_with_api(local_dir, code):
                log(f"  Failed to create Excel, skip!", "ERROR")
                return False
        else:
            log(f"  No Excel and no SRT, skip!")
            return False
    elif not has_excel_with_prompts(local_dir, code):
        log(f"  Excel empty/corrupt, recreating (FULL mode)...")
        excel_path.unlink()
        if not create_excel_with_api(local_dir, code):
            log(f"  Failed to recreate Excel, skip!", "ERROR")
            return False

    # Step 4: Create images using SmartEngine
    try:
        from modules.smart_engine import SmartEngine

        # Chrome 1: worker_id=0, total_workers=2 (chia scenes với Chrome 2)
        engine = SmartEngine(
            worker_id=0,
            total_workers=2
        )

        log(f"  Excel: {excel_path.name}")
        log(f"  Mode: CHROME 1 FULL (scenes chẵn: 2,4,6,... + nv/loc)")

        result = engine.run(str(excel_path), callback=callback, skip_compose=True, skip_video=True)

        if result.get('error'):
            log(f"  Error: {result.get('error')}", "ERROR")
            return False

    except Exception as e:
        log(f"  Exception: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return False

    # Step 5: Đợi tất cả ảnh hoàn thành
    log(f"\n[STEP 5] Waiting for all images...")
    if not is_local_pic_complete(local_dir, code):
        log(f"  Chrome 2 chưa xong ảnh, đợi tối đa 10 phút...")
        if not wait_for_all_images(local_dir, code, timeout=600):
            log(f"  Timeout! Chrome 2 chưa hoàn thành ảnh", "WARN")

    # Step 6: Tạo video PARALLEL (Chrome 1 làm video chẵn)
    if is_local_pic_complete(local_dir, code):
        log(f"\n[STEP 6] Creating videos (PARALLEL - Chrome 1 = chẵn)...")
        if create_videos_for_project_parallel(local_dir, code, callback):
            log(f"  [OK] Videos (chẵn) done!")
        else:
            log(f"  [WARN] Video creation failed", "WARN")

        # Step 7: Đợi Chrome 2 xong video
        log(f"\n[STEP 7] Waiting for Chrome 2 videos...")
        if not is_local_video_complete(local_dir, code):
            if not wait_for_all_videos(local_dir, code, timeout=1800):
                log(f"  Timeout! Chrome 2 chưa hoàn thành video", "WARN")

        # Step 8: Copy to VISUAL
        log(f"\n[STEP 8] Copying to VISUAL...")
        if copy_to_visual(code, local_dir):
            log(f"  [OK] Copied to VISUAL!")
            return True
        else:
            log(f"  [WARN] Failed to copy to VISUAL", "WARN")
            return True

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

    if not safe_path_exists(MASTER_PROJECTS):
        return pending

    for item in safe_iterdir(MASTER_PROJECTS):
        try:
            if not item.is_dir():
                continue

            code = item.name

            if not matches_channel(code):
                continue

            if is_project_complete_on_master(code):
                continue

            excel_path = item / f"{code}_prompts.xlsx"
            srt_path = item / f"{code}.srt"

            # Wrap network path checks in try-except
            try:
                if has_excel_with_prompts(item, code):
                    print(f"    - {code}: ready (has prompts)")
                    pending.append(code)
                elif srt_path.exists():
                    print(f"    - {code}: has SRT")
                    pending.append(code)
            except (OSError, PermissionError) as e:
                print(f"  [WARN] Network error checking {code}: {e}")
                continue

        except (OSError, PermissionError) as e:
            # Network disconnected while iterating
            print(f"  [WARN] Network error scanning: {e}")
            break

    return sorted(pending)


def run_scan_loop():
    """Run continuous scan loop - FULL mode."""
    print(f"\n{'='*60}")
    print(f"  VE3 TOOL - CHROME 1 FULL MODE")
    print(f"{'='*60}")
    print(f"  Worker folder:   {TOOL_DIR.parent.name}")
    print(f"  Channel filter:  {WORKER_CHANNEL or 'ALL'}")
    print(f"  Mode:            FULL (chi tiết toàn bộ)")
    print(f"  Images:          Scenes chẵn (2,4,6,...) + nv/loc")
    print(f"  Videos:          Scenes chẵn (2,4,6,...)")
    print(f"{'='*60}")

    cycle = 0

    while True:
        cycle += 1
        print(f"\n[FULL CYCLE {cycle}] Scanning...")

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
                    success = process_project_full(code)
                    if not success:
                        print(f"  Skipping {code}, moving to next...")
                        continue
                except KeyboardInterrupt:
                    print("\n\nStopped by user.")
                    return
                except Exception as e:
                    print(f"  Error processing {code}: {e}")
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
    parser = argparse.ArgumentParser(description='VE3 Chrome 1 FULL Mode')
    parser.add_argument('project', nargs='?', default=None, help='Project code')
    args = parser.parse_args()

    if args.project:
        process_project_full(args.project)
    else:
        run_scan_loop()


if __name__ == "__main__":
    main()
