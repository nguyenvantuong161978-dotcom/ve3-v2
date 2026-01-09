#!/usr/bin/env python3
"""
VE3 Tool - Worker Mode (Image/Video Generation)
Chạy trên máy ảo, copy dữ liệu từ máy chủ qua RDP/VMware.

Workflow:
    1. Copy project từ MASTER\AUTO\ve3-tool-simple\PROJECTS\{code}
    2. Tạo ảnh (characters + scenes)
    3. Tạo video từ ảnh (VEO3)
    4. KHÔNG edit ra MP4 (máy chủ sẽ làm)
    5. Copy kết quả về MASTER\AUTO\VISUAL\{code}

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

# === AUTO-DETECT NETWORK PATH ===
# Các đường dẫn có thể có đến \AUTO (tùy máy chủ)
POSSIBLE_AUTO_PATHS = [
    r"\\tsclient\D\AUTO",                          # RDP từ Windows
    r"\\tsclient\C\AUTO",                          # RDP từ Windows (ổ C)
    r"\\vmware-host\Shared Folders\D\AUTO",        # VMware Workstation
    r"\\vmware-host\Shared Folders\AUTO",          # VMware Workstation (direct)
    r"\\VBOXSVR\AUTO",                             # VirtualBox
    r"Z:\AUTO",                                    # Mapped drive
    r"Y:\AUTO",                                    # Mapped drive
    r"D:\AUTO",                                    # Direct access (same machine)
]

def detect_auto_path() -> Path:
    """
    Auto-detect đường dẫn đến thư mục \AUTO trên máy chủ.
    Thử các đường dẫn có thể và trả về cái đầu tiên hoạt động.
    """
    for path_str in POSSIBLE_AUTO_PATHS:
        try:
            path = Path(path_str)
            if path.exists():
                print(f"  ✓ Found AUTO at: {path}")
                return path
        except Exception:
            continue
    return None

# Detect AUTO path lần đầu
AUTO_PATH = detect_auto_path()

if AUTO_PATH:
    MASTER_PROJECTS = AUTO_PATH / "ve3-tool-simple" / "PROJECTS"
    MASTER_VISUAL = AUTO_PATH / "VISUAL"
else:
    # Fallback to default (will fail if not accessible)
    MASTER_PROJECTS = Path(r"\\tsclient\D\AUTO\ve3-tool-simple\PROJECTS")
    MASTER_VISUAL = Path(r"\\tsclient\D\AUTO\VISUAL")

# Local PROJECTS folder (worker)
LOCAL_PROJECTS = TOOL_DIR / "PROJECTS"

# Scan interval (seconds)
SCAN_INTERVAL = 30


def get_channel_from_folder() -> str:
    """
    Auto-detect channel from parent folder name.
    Example: AR35-T1 -> AR35
             AR47-T2 -> AR47
    Returns None if cannot detect.
    """
    parent_name = TOOL_DIR.parent.name  # e.g., "AR35-T1"

    # Try to extract channel prefix (part before -T)
    if "-T" in parent_name:
        channel = parent_name.split("-T")[0]  # "AR35-T1" -> "AR35"
        return channel

    # Fallback: try splitting by last dash
    if "-" in parent_name:
        parts = parent_name.rsplit("-", 1)
        if parts[0]:
            return parts[0]

    return None


# Auto-detect channel for this worker
WORKER_CHANNEL = get_channel_from_folder()


def matches_channel(code: str) -> bool:
    """Check if project code matches this worker's channel."""
    if WORKER_CHANNEL is None:
        return True  # No filter if channel not detected

    # Project code format: AR35-0001
    # Check if starts with channel prefix
    return code.startswith(f"{WORKER_CHANNEL}-")


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


def needs_api_completion(project_dir: Path, name: str) -> bool:
    """
    Check if Excel has [FALLBACK] prompts that need API completion.
    Returns True if any prompt starts with [FALLBACK].
    """
    excel_path = project_dir / f"{name}_prompts.xlsx"
    if not excel_path.exists():
        return False

    try:
        from modules.excel_manager import PromptWorkbook
        wb = PromptWorkbook(str(excel_path))
        scenes = wb.get_scenes()

        for scene in scenes:
            img_prompt = scene.img_prompt or ""
            if img_prompt.startswith("[FALLBACK]"):
                return True
        return False
    except:
        return False


def complete_excel_with_api(project_dir: Path, name: str) -> bool:
    """
    Complete Excel prompts using API (V2 flow).
    Called when Excel has [FALLBACK] prompts from run_srt.py.
    """
    import yaml

    print(f"  🤖 Completing Excel with API (V2 flow)...")

    try:
        # Load config
        cfg = {}
        cfg_file = TOOL_DIR / "config" / "settings.yaml"
        if cfg_file.exists():
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

        # Collect API keys
        deepseek_key = cfg.get('deepseek_api_key', '')
        groq_keys = cfg.get('groq_api_keys', [])
        gemini_keys = cfg.get('gemini_api_keys', [])

        if deepseek_key:
            cfg['deepseek_api_keys'] = [deepseek_key]
        if not groq_keys and not gemini_keys and not deepseek_key:
            print(f"  ⚠️ No API keys configured, using fallback prompts")
            return True  # Continue with fallback

        # Prefer DeepSeek for prompts
        cfg['preferred_provider'] = 'deepseek' if deepseek_key else ('groq' if groq_keys else 'gemini')

        # Force V2 flow
        cfg['use_v2_flow'] = True

        # Delete existing Excel to regenerate
        excel_path = project_dir / f"{name}_prompts.xlsx"
        if excel_path.exists():
            excel_path.unlink()
            print(f"  🗑️ Deleted fallback Excel, regenerating with API...")

        # Generate prompts with API
        from modules.prompts_generator import PromptGenerator
        gen = PromptGenerator(cfg)

        if gen.generate_for_project(project_dir, name, overwrite=True):
            print(f"  ✅ Excel completed with API prompts")
            return True
        else:
            print(f"  ❌ Failed to generate API prompts")
            return False

    except Exception as e:
        print(f"  ❌ API completion error: {e}")
        import traceback
        traceback.print_exc()
        return False


def delete_master_source(code: str):
    """Delete project from master PROJECTS after copying to local."""
    try:
        src = MASTER_PROJECTS / code
        if src.exists():
            shutil.rmtree(src)
            print(f"  🗑️ Deleted from master PROJECTS: {code}")
    except Exception as e:
        print(f"  ⚠️ Cleanup master warning: {e}")


def delete_local_project(code: str):
    """Delete local project after copying to VISUAL."""
    try:
        local_dir = LOCAL_PROJECTS / code
        if local_dir.exists():
            shutil.rmtree(local_dir)
            print(f"  🗑️ Deleted local project: {code}")
    except Exception as e:
        print(f"  ⚠️ Cleanup local warning: {e}")


def copy_from_master(code: str) -> Path:
    """Copy project from master to local (or return local if already exists)."""
    src = MASTER_PROJECTS / code
    dst = LOCAL_PROJECTS / code

    # Create local PROJECTS dir
    LOCAL_PROJECTS.mkdir(parents=True, exist_ok=True)

    # If local already exists, use it (even if master was deleted)
    if dst.exists():
        print(f"  📂 Using existing local: {code}")
        # Try to update Excel from master if available
        if src.exists():
            excel_src = src / f"{code}_prompts.xlsx"
            excel_dst = dst / f"{code}_prompts.xlsx"
            if excel_src.exists():
                if not excel_dst.exists() or excel_src.stat().st_mtime > excel_dst.stat().st_mtime:
                    shutil.copy2(excel_src, excel_dst)
                    print(f"  📥 Updated Excel from master")
        return dst

    # Local doesn't exist, need to copy from master
    if not src.exists():
        print(f"  ❌ Source not found: {src}")
        return None

    print(f"  📥 Copying from master: {code}")
    shutil.copytree(src, dst)
    print(f"  ✅ Copied to: {dst}")
    # Cleanup: delete from master after successful copy
    delete_master_source(code)

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

        # Cleanup: delete local project after successful copy
        delete_local_project(code)

        return True
    except Exception as e:
        print(f"  ❌ Copy failed: {e}")
        return False


def is_local_complete(project_dir: Path, name: str) -> bool:
    """
    Check if local project has images AND videos created (if video enabled).

    Logic:
    1. Phải có ít nhất 1 ảnh
    2. Nếu video_count > 0: phải có đủ video tương ứng với ảnh
    """
    img_dir = project_dir / "img"
    if not img_dir.exists():
        return False

    # Count images (png, jpg) - exclude videos
    img_files = list(img_dir.glob("*.png")) + list(img_dir.glob("*.jpg"))

    # Count videos
    video_files = list(img_dir.glob("*.mp4"))

    # Cần ít nhất 1 file ảnh
    if len(img_files) == 0:
        return False

    # Check video_count from settings
    try:
        import yaml
        config_path = TOOL_DIR / "config" / "settings.yaml"
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            video_count_setting = config.get('video_count', 0)

            # Parse video_count
            if video_count_setting == 'full' or video_count_setting == "full":
                required_videos = len(img_files)  # Tất cả ảnh cần có video
            elif video_count_setting and int(video_count_setting) > 0:
                required_videos = min(int(video_count_setting), len(img_files))
            else:
                required_videos = 0  # Video tắt

            # Nếu cần video, kiểm tra đủ số lượng
            if required_videos > 0:
                if len(video_files) < required_videos:
                    print(f"    [{name}] Videos: {len(video_files)}/{required_videos} - NOT complete")
                    return False
                else:
                    print(f"    [{name}] Videos: {len(video_files)}/{required_videos} - OK")
    except Exception as e:
        print(f"    [{name}] Warning checking video: {e}")

    return True


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

    # Step 3: Check Excel - nếu không có thì tạo bằng API
    excel_path = local_dir / f"{code}_prompts.xlsx"
    srt_path = local_dir / f"{code}.srt"

    if not excel_path.exists():
        # Không có Excel - tạo mới bằng API
        if srt_path.exists():
            log(f"  📋 No Excel found, creating with API...")
            if not complete_excel_with_api(local_dir, code):
                log(f"  ❌ Failed to create Excel, skip!")
                return False
        else:
            log(f"  ⏭️ No Excel and no SRT, skip!")
            return False
    elif not has_excel_with_prompts(local_dir, code):
        # Excel exists but empty/corrupt - recreate
        log(f"  📋 Excel empty/corrupt, recreating with API...")
        excel_path.unlink()  # Delete corrupt Excel
        if not complete_excel_with_api(local_dir, code):
            log(f"  ❌ Failed to recreate Excel, skip!")
            return False

    # Step 3.5: Complete Excel with API if needed (fallback prompts)
    if needs_api_completion(local_dir, code):
        log(f"  📋 Excel has [FALLBACK] prompts, completing with API...")
        if not complete_excel_with_api(local_dir, code):
            log(f"  ⚠️ API completion failed, using fallback prompts", "WARN")
            # Continue with fallback prompts if API fails

    # Step 4: Create images/videos
    try:
        from modules.smart_engine import SmartEngine

        # Pass worker settings for window layout
        engine = SmartEngine(worker_id=WORKER_ID, total_workers=TOTAL_WORKERS)

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


def scan_incomplete_local_projects() -> list:
    """
    Scan local PROJECTS for incomplete projects (có Excel nhưng chưa có ảnh).
    Đây là các project đã copy về nhưng chưa xử lý xong.
    """
    incomplete = []

    if not LOCAL_PROJECTS.exists():
        return incomplete

    for item in LOCAL_PROJECTS.iterdir():
        if not item.is_dir():
            continue

        code = item.name

        # Skip if not matching channel
        if not matches_channel(code):
            continue

        # Skip if already in VISUAL
        if is_project_complete_on_master(code):
            continue

        # Skip if already has images (complete)
        if is_local_complete(item, code):
            continue

        # Check if has Excel with prompts OR has SRT (can create Excel)
        srt_path = item / f"{code}.srt"
        if has_excel_with_prompts(item, code):
            print(f"    - {code}: incomplete (has Excel, no images) → will continue")
            incomplete.append(code)
        elif srt_path.exists():
            # Có SRT nhưng không có Excel - worker sẽ tự tạo
            print(f"    - {code}: has SRT, no Excel → will create with API")
            incomplete.append(code)

    return sorted(incomplete)


def scan_master_projects() -> list:
    """Scan master PROJECTS folder for pending projects."""
    pending = []

    print(f"  [DEBUG] Checking: {MASTER_PROJECTS}")
    print(f"  [DEBUG] Worker channel: {WORKER_CHANNEL or 'ALL (no filter)'}")

    if not MASTER_PROJECTS.exists():
        print(f"  ⚠️ Master PROJECTS not accessible: {MASTER_PROJECTS}")
        return pending

    # List all folders
    all_folders = [item for item in MASTER_PROJECTS.iterdir() if item.is_dir()]
    print(f"  [DEBUG] Found {len(all_folders)} folders in MASTER_PROJECTS")

    for item in all_folders:
        code = item.name

        # Skip if not matching this worker's channel
        if not matches_channel(code):
            continue  # Silent skip - not our channel

        # Skip if already in VISUAL
        if is_project_complete_on_master(code):
            print(f"    - {code}: already in VISUAL ✓")
            continue

        # Check if has Excel or SRT
        excel_path = item / f"{code}_prompts.xlsx"
        srt_path = item / f"{code}.srt"

        if has_excel_with_prompts(item, code):
            print(f"    - {code}: ready (has prompts) ✓")
            pending.append(code)
        elif srt_path.exists():
            # Có SRT nhưng không có Excel - worker sẽ tự tạo
            print(f"    - {code}: has SRT, no Excel → will create with API")
            pending.append(code)
        elif excel_path.exists():
            print(f"    - {code}: Excel exists but no prompts yet")
        else:
            print(f"    - {code}: no Excel and no SRT")

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

        # Skip if not matching this worker's channel
        if not matches_channel(code):
            continue  # Silent skip - not our channel

        # Nếu đã có trong VISUAL thì xóa local (cleanup)
        if is_project_complete_on_master(code):
            print(f"    - {code}: already in VISUAL, cleaning up local...")
            delete_local_project(code)
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
    global AUTO_PATH, MASTER_PROJECTS, MASTER_VISUAL

    print(f"\n{'='*60}")
    print(f"  VE3 TOOL - WORKER MODE (Image/Video)")
    print(f"{'='*60}")
    print(f"  Worker folder:   {TOOL_DIR.parent.name}")
    print(f"  Channel filter:  {WORKER_CHANNEL or 'ALL (no filter)'}")

    # Re-detect AUTO path nếu chưa có
    if not AUTO_PATH:
        print(f"\n  🔍 Detecting network path to \\AUTO...")
        AUTO_PATH = detect_auto_path()
        if AUTO_PATH:
            MASTER_PROJECTS = AUTO_PATH / "ve3-tool-simple" / "PROJECTS"
            MASTER_VISUAL = AUTO_PATH / "VISUAL"

    if AUTO_PATH:
        print(f"  ✓ AUTO path:     {AUTO_PATH}")
    else:
        print(f"  ✗ AUTO path:     NOT FOUND")

    print(f"  Master PROJECTS: {MASTER_PROJECTS}")
    print(f"  Master VISUAL:   {MASTER_VISUAL}")
    print(f"  Local PROJECTS:  {LOCAL_PROJECTS}")
    print(f"  Scan interval:   {SCAN_INTERVAL}s")
    print(f"{'='*60}")

    # Check network paths
    if not AUTO_PATH or not MASTER_PROJECTS.exists():
        print(f"\n❌ Cannot access master PROJECTS!")
        print(f"   Tried paths:")
        for p in POSSIBLE_AUTO_PATHS:
            print(f"     - {p}")
        print(f"\n   Make sure:")
        print(f"     - RDP/VMware is connected")
        print(f"     - Drive is shared (D: or Shared Folders)")
        print(f"     - \\AUTO folder exists")
        print(f"\n   Press Ctrl+C to exit and fix the connection.")
        print(f"   Will retry every {SCAN_INTERVAL}s...")

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

        # Find incomplete local projects (đã copy về nhưng chưa xong)
        incomplete_local = scan_incomplete_local_projects()

        # Find pending projects from master
        pending_master = scan_master_projects()

        # Merge: incomplete local + pending master (loại bỏ duplicate)
        pending = list(dict.fromkeys(incomplete_local + pending_master))

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


# Global worker settings (set from command line)
WORKER_ID = 0
TOTAL_WORKERS = 1


def main():
    global WORKER_ID, TOTAL_WORKERS

    import argparse
    parser = argparse.ArgumentParser(description='VE3 Worker - Image/Video Generation')
    parser.add_argument('project', nargs='?', default=None, help='Project code to process')
    parser.add_argument('--worker-id', type=int, default=0, help='Worker ID (0-based, for window layout)')
    parser.add_argument('--total-workers', type=int, default=1, help='Total number of workers (1=full, 2=split, ...)')
    args = parser.parse_args()

    # Set global worker settings
    WORKER_ID = args.worker_id
    TOTAL_WORKERS = args.total_workers

    if TOTAL_WORKERS > 1:
        pos_name = ["FULL", "LEFT", "RIGHT", "TOP-LEFT", "TOP-RIGHT", "BOTTOM"][min(WORKER_ID, 5)]
        print(f"[WORKER {WORKER_ID}/{TOTAL_WORKERS}] Window: {pos_name}")

    if args.project:
        # Single project mode
        run_single_project(args.project)
    else:
        # Scan loop mode
        run_scan_loop()


if __name__ == "__main__":
    main()
