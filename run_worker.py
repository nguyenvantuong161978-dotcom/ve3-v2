#!/usr/bin/env python3
"""
VE3 Tool - Worker Mode (Image/Video Generation)
Chạy trên máy ảo, copy dữ liệu từ máy chủ qua RDP.

Workflow:
    1. Copy project từ \\tsclient\D\AUTO\ve3-tool-simple\PROJECTS\{code}
    2. Tạo ảnh (characters + scenes)
    3. Tạo video từ ảnh (VEO3)
    4. KHÔNG edit ra MP4 (máy chủ sẽ làm)
    5. Copy kết quả về \\tsclient\D\AUTO\VISUAL\{code}

Usage:
    python run_worker.py                     (quét và xử lý tự động)
    python run_worker.py AR47-0028           (chạy 1 project cụ thể)
"""

import sys
import os
import time
import shutil
from pathlib import Path

# Add current directory to path
TOOL_DIR = Path(__file__).parent
sys.path.insert(0, str(TOOL_DIR))

# === NETWORK PATHS (qua RDP tsclient) ===
# Máy chủ share qua RDP: \\tsclient\D\...
MASTER_PROJECTS = Path(r"\\tsclient\D\AUTO\ve3-tool-simple\PROJECTS")
MASTER_VISUAL = Path(r"\\tsclient\D\AUTO\VISUAL")

# Local PROJECTS folder (worker)
LOCAL_PROJECTS = TOOL_DIR / "PROJECTS"

# Scan interval (seconds)
SCAN_INTERVAL = 30


def is_project_complete_on_master(code: str) -> bool:
    """Check if project already exists in VISUAL folder on master."""
    visual_dir = MASTER_VISUAL / code
    if not visual_dir.exists():
        return False

    # Check if has ANY images (*.png, *.mp4, *.jpg)
    img_dir = visual_dir / "img"
    if img_dir.exists():
        img_files = list(img_dir.glob("*.png")) + list(img_dir.glob("*.mp4")) + list(img_dir.glob("*.jpg"))
        return len(img_files) > 0

    return False


def has_excel_with_prompts(project_dir: Path, name: str) -> bool:
    """Check if project has Excel with prompts (ready for worker)."""
    # Check flat structure
    excel_path = project_dir / f"{name}_prompts.xlsx"
    if not excel_path.exists():
        return False

    try:
        from modules.excel_manager import PromptWorkbook
        wb = PromptWorkbook(str(excel_path))
        stats = wb.get_stats()
        total_scenes = stats.get('total_scenes', 0)
        scenes_with_prompts = stats.get('scenes_with_prompts', 0)
        return total_scenes > 0 and scenes_with_prompts > 0
    except:
        return False


def copy_from_master(code: str) -> Path:
    """Copy project from master to local."""
    src = MASTER_PROJECTS / code
    dst = LOCAL_PROJECTS / code

    if not src.exists():
        print(f"  ❌ Source not found: {src}")
        return None

    # Create local PROJECTS dir
    LOCAL_PROJECTS.mkdir(parents=True, exist_ok=True)

    # Copy if not exists or update
    if not dst.exists():
        print(f"  📥 Copying from master: {code}")
        shutil.copytree(src, dst)
        print(f"  ✅ Copied to: {dst}")
    else:
        # Check if Excel updated on master
        excel_src = src / f"{code}_prompts.xlsx"
        excel_dst = dst / f"{code}_prompts.xlsx"
        if excel_src.exists():
            if not excel_dst.exists() or excel_src.stat().st_mtime > excel_dst.stat().st_mtime:
                shutil.copy2(excel_src, excel_dst)
                print(f"  📥 Updated Excel from master")

    return dst


def copy_to_visual(code: str, local_dir: Path) -> bool:
    """Copy completed project to VISUAL folder on master."""
    dst = MASTER_VISUAL / code

    print(f"  📤 Copying to VISUAL: {code}")

    try:
        # Create VISUAL dir on master
        MASTER_VISUAL.mkdir(parents=True, exist_ok=True)

        if dst.exists():
            shutil.rmtree(dst)

        # Copy entire project folder
        shutil.copytree(local_dir, dst)
        print(f"  ✅ Copied to: {dst}")
        return True
    except Exception as e:
        print(f"  ❌ Copy failed: {e}")
        return False


def is_local_complete(project_dir: Path, name: str) -> bool:
    """Check if local project has images/videos created."""
    img_dir = project_dir / "img"
    if not img_dir.exists():
        return False

    # Check for ANY image/video files (*.png, *.mp4, *.jpg)
    # Ảnh có thể tên: scene_1.png, 1.0.png, image_1.png, etc.
    img_files = list(img_dir.glob("*.png")) + list(img_dir.glob("*.mp4")) + list(img_dir.glob("*.jpg"))

    # Cần ít nhất 1 file ảnh/video
    return len(img_files) > 0


def process_project(code: str, callback=None) -> bool:
    """Process a single project (create images + video only, NO MP4 edit)."""

    def log(msg, level="INFO"):
        if callback:
            callback(msg, level)
        else:
            print(msg)

    log(f"\n{'='*60}")
    log(f"Processing: {code}")
    log(f"{'='*60}")

    # Step 1: Check if already done on master
    if is_project_complete_on_master(code):
        log(f"  ⏭️ Already in VISUAL folder, skip!")
        return True

    # Step 2: Copy from master
    local_dir = copy_from_master(code)
    if not local_dir:
        return False

    # Step 3: Check Excel
    if not has_excel_with_prompts(local_dir, code):
        log(f"  ⏭️ Excel not ready (no prompts), skip!")
        return False

    # Step 4: Create images/videos
    try:
        from modules.smart_engine import SmartEngine

        engine = SmartEngine()

        # Find Excel path
        excel_path = local_dir / f"{code}_prompts.xlsx"

        log(f"  📋 Excel: {excel_path.name}")

        # Run engine - create images and videos only (no MP4 compose)
        result = engine.run(str(excel_path), callback=callback, skip_compose=True)

        if result.get('error'):
            log(f"  ❌ Error: {result.get('error')}", "ERROR")
            return False

    except Exception as e:
        log(f"  ❌ Exception: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return False

    # Step 5: Copy to VISUAL on master
    if is_local_complete(local_dir, code):
        if copy_to_visual(code, local_dir):
            log(f"  ✅ Done! Project copied to VISUAL")
            return True
        else:
            log(f"  ⚠️ Images created but copy failed", "WARN")
            return False
    else:
        log(f"  ⚠️ No images created", "WARN")
        return False


def scan_master_projects() -> list:
    """Scan master PROJECTS folder for pending projects."""
    pending = []

    print(f"  [DEBUG] Checking: {MASTER_PROJECTS}")

    if not MASTER_PROJECTS.exists():
        print(f"  ⚠️ Master PROJECTS not accessible: {MASTER_PROJECTS}")
        return pending

    # List all folders
    all_folders = [item for item in MASTER_PROJECTS.iterdir() if item.is_dir()]
    print(f"  [DEBUG] Found {len(all_folders)} folders in MASTER_PROJECTS")

    for item in all_folders:
        code = item.name

        # Skip if already in VISUAL
        if is_project_complete_on_master(code):
            print(f"    - {code}: already in VISUAL ✓")
            continue

        # Check if has Excel (có thể chưa có prompts)
        excel_path = item / f"{code}_prompts.xlsx"
        if not excel_path.exists():
            print(f"    - {code}: no Excel file")
            continue

        # Check if has prompts
        if has_excel_with_prompts(item, code):
            print(f"    - {code}: ready (has prompts) ✓")
            pending.append(code)
        else:
            print(f"    - {code}: Excel exists but no prompts yet")

    return sorted(pending)


def sync_local_to_visual() -> int:
    """
    Scan local PROJECTS và copy các project đã có ảnh sang VISUAL.
    Chạy khi bắt đầu để sync các project đã hoàn thành trước đó.

    Returns:
        Số lượng projects đã copy
    """
    print(f"  [DEBUG] Checking local: {LOCAL_PROJECTS}")

    if not LOCAL_PROJECTS.exists():
        print(f"  [DEBUG] Local PROJECTS folder does not exist")
        return 0

    # List all folders
    all_folders = [item for item in LOCAL_PROJECTS.iterdir() if item.is_dir()]
    print(f"  [DEBUG] Found {len(all_folders)} local project folders")

    copied = 0

    for item in all_folders:
        code = item.name

        # Skip nếu đã có trong VISUAL
        if is_project_complete_on_master(code):
            print(f"    - {code}: already in VISUAL ✓")
            continue

        # Check local có ảnh không
        if is_local_complete(item, code):
            print(f"  📤 Found local project with images: {code}")
            if copy_to_visual(code, item):
                copied += 1
        else:
            print(f"    - {code}: no images yet")

    return copied


def run_scan_loop():
    """Run continuous scan loop."""
    print(f"\n{'='*60}")
    print(f"  VE3 TOOL - WORKER MODE (Image/Video)")
    print(f"{'='*60}")
    print(f"  Master PROJECTS: {MASTER_PROJECTS}")
    print(f"  Master VISUAL:   {MASTER_VISUAL}")
    print(f"  Local PROJECTS:  {LOCAL_PROJECTS}")
    print(f"  Scan interval:   {SCAN_INTERVAL}s")
    print(f"{'='*60}")

    # Check network paths
    if not MASTER_PROJECTS.exists():
        print(f"\n⚠️ Cannot access master PROJECTS!")
        print(f"   Make sure RDP is connected and D: drive is shared.")
        print(f"   Path: {MASTER_PROJECTS}")

    # === SYNC: Copy local projects đã có ảnh sang VISUAL ===
    print(f"\n[SYNC] Checking local projects to sync to VISUAL...")
    synced = sync_local_to_visual()
    if synced > 0:
        print(f"  ✅ Synced {synced} projects to VISUAL")
    else:
        print(f"  No local projects to sync")

    cycle = 0

    while True:
        cycle += 1
        print(f"\n[CYCLE {cycle}] Scanning...")

        # === SYNC: Copy local projects đã có ảnh sang VISUAL ===
        synced = sync_local_to_visual()
        if synced > 0:
            print(f"  📤 Synced {synced} local projects to VISUAL")

        # Find pending projects from master
        pending = scan_master_projects()

        if not pending:
            print(f"  No pending projects")
            # Wait before next scan
            print(f"\n  Waiting {SCAN_INTERVAL}s... (Ctrl+C to stop)")
            try:
                time.sleep(SCAN_INTERVAL)
            except KeyboardInterrupt:
                print("\n\nStopped by user.")
                break
        else:
            print(f"  Found: {len(pending)} pending projects")
            for p in pending[:5]:
                print(f"    - {p}")
            if len(pending) > 5:
                print(f"    ... and {len(pending) - 5} more")

            # === XỬ LÝ TẤT CẢ PROJECTS LIÊN TỤC ===
            for code in pending:
                try:
                    success = process_project(code)

                    # Sync lại sau mỗi project
                    sync_local_to_visual()

                    if not success:
                        print(f"  ⏭️ Skipping {code}, moving to next...")
                        continue

                except KeyboardInterrupt:
                    print("\n\nStopped by user.")
                    return
                except Exception as e:
                    print(f"  ❌ Error processing {code}: {e}")
                    continue

            # Sau khi xử lý hết, đợi 1 chút rồi scan lại
            print(f"\n  ✅ Processed all pending projects!")
            print(f"  Waiting {SCAN_INTERVAL}s for new projects... (Ctrl+C to stop)")
            try:
                time.sleep(SCAN_INTERVAL)
            except KeyboardInterrupt:
                print("\n\nStopped by user.")
                break


def run_single_project(code: str):
    """Run a single project by name."""
    process_project(code)


def main():
    if len(sys.argv) >= 2:
        # Single project mode
        code = sys.argv[1]
        run_single_project(code)
    else:
        # Scan loop mode
        run_scan_loop()


if __name__ == "__main__":
    main()
