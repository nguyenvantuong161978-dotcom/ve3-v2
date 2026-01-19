#!/usr/bin/env python3
"""
VE3 Tool - Worker PIC BASIC Mode with Agent Protocol
=====================================================
Chrome Worker 1 - Xử lý scenes chẵn (2, 4, 6, ...)

Tích hợp Agent Protocol để:
- Báo cáo trạng thái cho VM Manager
- Ghi log chi tiết
- Báo cáo kết quả thành công/thất bại

Usage:
    python _run_chrome1.py                     (quét và xử lý tự động)
    python _run_chrome1.py AR47-0028           (chạy 1 project cụ thể)
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
from datetime import datetime

# Add current directory to path
TOOL_DIR = Path(__file__).parent
sys.path.insert(0, str(TOOL_DIR))

# ================================================================================
# AGENT PROTOCOL
# ================================================================================

# Worker ID for this Chrome worker
WORKER_ID = "chrome_1"

# Agent Protocol - giao tiếp với VM Manager
try:
    from modules.agent_protocol import AgentWorker, ErrorType
    AGENT_ENABLED = True
except ImportError:
    AGENT_ENABLED = False
    AgentWorker = None

# Global agent instance
_agent = None


def init_agent():
    """Khởi tạo Agent Protocol."""
    global _agent
    if AGENT_ENABLED and _agent is None:
        _agent = AgentWorker(WORKER_ID)
        _agent.start_status_updater(interval=5)
        _agent.update_status(state="idle")
        print(f"[{WORKER_ID}] Agent Protocol enabled")
    return _agent


def close_agent():
    """Đóng Agent Protocol."""
    global _agent
    if _agent:
        _agent.close()
        _agent = None


def safe_str(s) -> str:
    """Convert any value to a safe ASCII-friendly string."""
    try:
        text = str(s)
        # Replace non-ASCII characters with '?'
        return text.encode('ascii', errors='replace').decode('ascii')
    except:
        return "[encoding error]"


def agent_log(msg: str, level: str = "INFO"):
    """Log và gửi đến Agent."""
    global _agent
    safe_msg = safe_str(msg)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {safe_msg}")
    if _agent:
        if level == "ERROR":
            _agent.log_error(safe_msg)
        else:
            _agent.log(safe_msg, level)

# Import từ run_worker (dùng chung logic)
from run_worker import (
    detect_auto_path,
    POSSIBLE_AUTO_PATHS,
    get_channel_from_folder,
    matches_channel,
    is_project_complete_on_master,
    has_excel_with_prompts,
    needs_api_completion,
    copy_from_master,
    copy_to_visual,
    delete_local_project,
    SCAN_INTERVAL,
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


def create_excel_with_api_basic(project_dir: Path, code: str, callback=None) -> bool:
    """
    Create Excel with prompts using API - BASIC mode.
    Uses segment-based image counts (no 8s limit).
    """
    def log(msg, level="INFO"):
        if callback:
            callback(msg, level)
        else:
            print(msg)

    try:
        import yaml
        from modules.progressive_prompts import ProgressivePromptsGenerator
        from modules.excel_manager import PromptWorkbook
        from modules.utils import parse_srt_file

        # Load config from settings.yaml
        config = {}
        config_path = TOOL_DIR / "config" / "settings.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}

        # Collect API keys
        deepseek_key = config.get('deepseek_api_key', '')
        if deepseek_key:
            config['deepseek_api_keys'] = [deepseek_key]

        # Check SRT file
        srt_path = project_dir / f"{code}.srt"
        txt_path = project_dir / f"{code}.txt"

        if not srt_path.exists():
            log(f"  ERROR: No SRT file found!", "ERROR")
            return False

        srt_entries = parse_srt_file(srt_path)
        txt_content = txt_path.read_text(encoding='utf-8') if txt_path.exists() else ""

        # Create workbook
        excel_path = project_dir / f"{code}_prompts.xlsx"
        workbook = PromptWorkbook(str(excel_path))

        # Create generator
        generator = ProgressivePromptsGenerator(config)
        generator.log_callback = callback

        # Run steps - BASIC mode (segment-based)
        log(f"\n[STEP 1] Analyzing story...")
        result = generator.step_analyze_story(project_dir, code, workbook, srt_entries, txt_content)
        if result.status.value == "failed":
            log(f"  FAILED: {result.message}", "ERROR")
            return False

        log(f"\n[STEP 1.5] Analyzing story segments...")
        result = generator.step_analyze_story_segments(project_dir, code, workbook, srt_entries)
        if result.status.value == "failed":
            log(f"  FAILED: {result.message}", "ERROR")
            return False

        log(f"\n[STEP 2] Creating characters...")
        result = generator.step_create_characters(project_dir, code, workbook, srt_entries, txt_content)
        if result.status.value == "failed":
            log(f"  FAILED: {result.message}", "ERROR")
            return False

        log(f"\n[STEP 3] Creating locations...")
        result = generator.step_create_locations(project_dir, code, workbook, srt_entries, txt_content)
        if result.status.value == "failed":
            log(f"  FAILED: {result.message}", "ERROR")
            return False

        # BASIC MODE: Use segment-based director plan
        log(f"\n[STEP 4] Creating director's plan (BASIC - segment-based)...")
        result = generator.step_create_director_plan_basic(project_dir, code, workbook, srt_entries)
        if result.status.value == "failed":
            log(f"  FAILED: {result.message}", "ERROR")
            return False

        # Skip Step 4.5 in basic mode - not needed

        log(f"\n[STEP 5] Creating scene prompts...")
        result = generator.step_create_scene_prompts(project_dir, code, workbook)
        if result.status.value == "failed":
            log(f"  FAILED: {result.message}", "ERROR")
            return False

        log(f"\n[OK] Excel created successfully (BASIC mode)!")
        return True

    except Exception as e:
        log(f"  ERROR: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return False


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
    """
    Đợi tất cả ảnh hoàn thành (Chrome 1 + Chrome 2).
    Timeout mặc định 10 phút.
    """
    import time
    start = time.time()
    while time.time() - start < timeout:
        if is_local_pic_complete(project_dir, name):
            return True
        print(f"    Đợi Chrome 2 hoàn thành... ({int(time.time() - start)}s)")
        time.sleep(10)
    return False


def create_videos_for_project(project_dir: Path, code: str, callback=None) -> bool:
    """Tạo video cho project đã có ảnh."""
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

        log(f"\n[VIDEO] Creating videos for {code}...")
        engine = SmartEngine(worker_id=0, total_workers=1)

        # Run với skip_video=False để tạo video
        # SmartEngine sẽ tự động skip ảnh đã tồn tại
        result = engine.run(
            str(excel_path),
            callback=callback,
            skip_compose=True,
            skip_video=False  # Tạo video
        )

        if result.get('error'):
            log(f"  Video error: {result.get('error')}", "ERROR")
            return False

        log(f"  [OK] Videos created!")
        return True

    except Exception as e:
        log(f"  Video exception: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return False


def process_project_pic_basic(code: str, callback=None) -> bool:
    """Process a single project - BASIC mode (no IP rotation)."""

    def log(msg, level="INFO"):
        if callback:
            callback(msg, level)
        else:
            print(msg)

    log(f"\n{'='*60}")
    log(f"[PIC BASIC] Processing: {code}")
    log(f"{'='*60}")

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

    # Step 4: Create images using SmartEngine (same as worker_pic)
    # Basic mode just means we created Excel with segment-based approach
    # Image generation uses the same SmartEngine
    try:
        from modules.smart_engine import SmartEngine

        # Chrome 1: worker_id=0, total_workers=2 (để chia scenes với Chrome 2)
        engine = SmartEngine(
            worker_id=0,
            total_workers=2  # Chia scenes chẵn/lẻ với Chrome 2
        )

        log(f"  Excel: {excel_path.name}")
        log(f"  Mode: CHROME 1 (scenes chẵn: 2,4,6,... + nv/loc)")

        # Run engine - images only, skip video generation
        result = engine.run(str(excel_path), callback=callback, skip_compose=True, skip_video=True)

        if result.get('error'):
            log(f"  Error: {result.get('error')}", "ERROR")
            return False

    except Exception as e:
        log(f"  Exception: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return False

    # Step 5: Đợi tất cả ảnh hoàn thành (Chrome 2 có thể chưa xong)
    log(f"\n[STEP 5] Checking all images...")
    if not is_local_pic_complete(local_dir, code):
        log(f"  Chrome 2 chưa xong, đợi tối đa 10 phút...")
        if not wait_for_all_images(local_dir, code, timeout=600):
            log(f"  Timeout! Chrome 2 chưa hoàn thành, tiếp tục...", "WARN")
            # Không return False, để có thể retry sau

    # Step 6: Tạo video (sau khi có đủ ảnh)
    if is_local_pic_complete(local_dir, code):
        log(f"\n[STEP 6] Creating videos...")
        if create_videos_for_project(local_dir, code, callback):
            log(f"  [OK] Videos created!")
        else:
            log(f"  [WARN] Video creation failed, nhưng ảnh đã xong", "WARN")

        # Step 7: Copy to VISUAL
        log(f"\n[STEP 7] Copying to VISUAL...")
        if copy_to_visual(code, local_dir):
            log(f"  [OK] Copied to VISUAL!")
            return True
        else:
            log(f"  [WARN] Failed to copy to VISUAL", "WARN")
            return True  # Vẫn return True vì ảnh đã xong

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
    """Run continuous scan loop for IMAGE generation (BASIC mode)."""
    print(f"\n{'='*60}")
    print(f"  VE3 TOOL - WORKER PIC BASIC")
    print(f"{'='*60}")
    print(f"  Worker folder:   {TOOL_DIR.parent.name}")
    print(f"  Channel filter:  {WORKER_CHANNEL or 'ALL'}")
    print(f"  Mode:            BASIC (no IP rotation)")
    print(f"  Duration:        Segment-based (no 8s limit)")
    print(f"{'='*60}")

    cycle = 0

    while True:
        cycle += 1
        print(f"\n[BASIC CYCLE {cycle}] Scanning...")

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
                    success = process_project_pic_basic(code)
                    if not success:
                        print(f"  Skipping {code}, moving to next...")
                        continue
                except KeyboardInterrupt:
                    print("\n\nStopped by user.")
                    return
                except Exception as e:
                    print(f"  Error processing {code}: {safe_str(e)}")
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
    parser = argparse.ArgumentParser(description='VE3 Worker PIC BASIC - Chrome 1')
    parser.add_argument('project', nargs='?', default=None, help='Project code')
    args = parser.parse_args()

    # Khởi tạo Agent Protocol
    init_agent()

    try:
        if args.project:
            # Single project mode
            success = process_project_with_agent(args.project)
            sys.exit(0 if success else 1)
        else:
            # Loop mode
            run_scan_loop_with_agent()
    finally:
        # Cleanup
        close_agent()


def process_project_with_agent(code: str) -> bool:
    """Process project với Agent Protocol."""
    global _agent

    task_id = f"image_{code}_{datetime.now().strftime('%H%M%S')}"
    start_time = time.time()

    # Get total scenes for progress tracking
    total_scenes = 0
    current_scene = [0]  # Use list to allow modification in callback

    try:
        from modules.excel_manager import PromptWorkbook
        local_dir = LOCAL_PROJECTS / code
        excel_path = local_dir / f"{code}_prompts.xlsx"
        if excel_path.exists():
            wb = PromptWorkbook(str(excel_path))
            total_scenes = len(wb.get_scenes())
    except:
        pass

    # Update agent status
    if _agent:
        _agent.update_status(
            state="working",
            current_project=code,
            current_task=task_id,
            current_scene=0,
            total_scenes=total_scenes,
            progress=0
        )

    # Callback to track progress
    def progress_callback(msg, level="INFO"):
        """Callback that also updates agent with scene progress."""
        print(msg)

        # Try to extract scene number from message
        if _agent and "Scene" in msg:
            import re
            match = re.search(r'Scene\s*(\d+)', msg, re.IGNORECASE)
            if match:
                scene_num = int(match.group(1))
                current_scene[0] = scene_num
                progress = int((scene_num / total_scenes * 100) if total_scenes > 0 else 0)
                _agent.update_status(
                    current_scene=scene_num,
                    progress=progress
                )

    # Process
    try:
        success = process_project_pic_basic(code, callback=progress_callback)
        duration = time.time() - start_time

        # Report result
        if _agent:
            if success:
                _agent.report_success(
                    task_id=task_id,
                    project_code=code,
                    task_type="image",
                    duration=duration
                )
            else:
                _agent.report_failure(
                    task_id=task_id,
                    project_code=code,
                    task_type="image",
                    error="Processing failed",
                    duration=duration
                )
            _agent.update_status(
                state="idle",
                current_project="",
                current_task="",
                current_scene=0,
                total_scenes=0,
                progress=0
            )

        return success

    except Exception as e:
        duration = time.time() - start_time
        if _agent:
            _agent.report_failure(
                task_id=task_id,
                project_code=code,
                task_type="image",
                error=str(e),
                duration=duration
            )
            _agent.update_status(
                state="error",
                current_project="",
                current_task="",
                current_scene=0,
                total_scenes=0,
                progress=0
            )
        raise


def run_scan_loop_with_agent():
    """Run scan loop với Agent Protocol."""
    global _agent

    print(f"\n{'='*60}")
    print(f"  CHROME WORKER 1 - PIC BASIC MODE")
    print(f"  Agent: {'Enabled' if _agent else 'Disabled'}")
    print(f"{'='*60}\n")

    cycle = 0
    try:
        while True:
            cycle += 1
            print(f"\n[CYCLE {cycle}] Scanning...")

            # Tìm projects cần xử lý (từ local và master)
            projects = scan_incomplete_local_projects()
            if not projects:
                projects = scan_master_projects()

            if projects:
                for code in projects:
                    try:
                        process_project_with_agent(code)
                    except KeyboardInterrupt:
                        raise
                    except Exception as e:
                        agent_log(f"Error processing {code}: {e}", "ERROR")

            print(f"\nWaiting {SCAN_INTERVAL}s... (Ctrl+C to stop)")
            time.sleep(SCAN_INTERVAL)

    except KeyboardInterrupt:
        print("\n\nStopped by user.")


if __name__ == "__main__":
    main()
