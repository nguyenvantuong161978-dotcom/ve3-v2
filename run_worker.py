#!/usr/bin/env python3
"""
VE3 Tool - Worker Mode (Image/Video Generation)
Quét PROJECTS folder và tạo ảnh/video từ Excel.

Usage:
    python run_worker.py                     (quét PROJECTS mặc định)
    python run_worker.py D:\path\to\PROJECTS (quét thư mục khác)
    python run_worker.py AR47-0028           (chạy 1 project cụ thể)

Cấu trúc input (từ master):
    PROJECTS\AR47-0028\
    ├── AR47-0028.mp3
    ├── AR47-0028.srt
    └── AR47-0028_prompts.xlsx

Output:
    PROJECTS\AR47-0028\
    ├── img\             (scene images)
    ├── nv\              (character images)
    └── AR47-0028.mp4    (final video)
"""

import sys
import os
import time
from pathlib import Path

# Add current directory to path
TOOL_DIR = Path(__file__).parent
sys.path.insert(0, str(TOOL_DIR))

# Default PROJECTS folder
PROJECTS_DIR = TOOL_DIR / "PROJECTS"

# Scan interval (seconds)
SCAN_INTERVAL = 30


def is_project_complete(project_dir: Path, name: str) -> bool:
    """Check if project has final video."""
    video_path = project_dir / f"{name}.mp4"
    return video_path.exists()


def has_excel_with_prompts(project_dir: Path, name: str) -> bool:
    """Check if project has Excel with prompts (ready for worker)."""
    # Check flat structure first
    excel_path = project_dir / f"{name}_prompts.xlsx"
    if not excel_path.exists():
        # Check nested structure
        excel_path = project_dir / "prompts" / f"{name}_prompts.xlsx"

    if not excel_path.exists():
        return False

    try:
        from modules.excel_manager import PromptWorkbook
        wb = PromptWorkbook(str(excel_path))
        stats = wb.get_stats()
        total_scenes = stats.get('total_scenes', 0)
        scenes_with_prompts = stats.get('scenes_with_prompts', 0)

        # Ready if has at least some scene prompts
        return total_scenes > 0 and scenes_with_prompts > 0
    except:
        return False


def process_project(project_dir: Path, callback=None) -> bool:
    """Process a single project (create images + video)."""
    name = project_dir.name

    def log(msg, level="INFO"):
        if callback:
            callback(msg, level)
        else:
            print(msg)

    log(f"\n{'='*60}")
    log(f"Processing: {name}")
    log(f"{'='*60}")

    try:
        from modules.smart_engine import SmartEngine

        # Create engine
        engine = SmartEngine()

        # Find Excel path (flat or nested)
        excel_path_flat = project_dir / f"{name}_prompts.xlsx"
        excel_path_nested = project_dir / "prompts" / f"{name}_prompts.xlsx"

        if excel_path_flat.exists():
            excel_path = excel_path_flat
        elif excel_path_nested.exists():
            excel_path = excel_path_nested
        else:
            log(f"  ❌ Excel not found!", "ERROR")
            return False

        log(f"  Excel: {excel_path.name}")

        # Run engine with Excel as input
        result = engine.run(str(excel_path), callback=callback)

        if result.get('error'):
            log(f"  ❌ Error: {result.get('error')}", "ERROR")
            return False

        if result.get('skipped'):
            log(f"  ⏭️ Skipped: {result.get('skipped')}")
            return True

        log(f"  ✅ Done!")
        return True

    except Exception as e:
        log(f"  ❌ Exception: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return False


def scan_projects_folder(projects_dir: Path) -> list:
    """Scan PROJECTS folder for project directories."""
    projects = []

    for item in projects_dir.iterdir():
        if item.is_dir():
            # Check if it's a valid project (has Excel)
            name = item.name
            if has_excel_with_prompts(item, name):
                projects.append(item)

    return sorted(projects)


def get_pending_projects(projects: list) -> list:
    """Filter projects that need processing."""
    pending = []

    for project_dir in projects:
        name = project_dir.name
        if not is_project_complete(project_dir, name):
            pending.append(project_dir)

    return pending


def run_scan_loop(projects_dir: Path):
    """Run continuous scan loop."""
    print(f"\n{'='*60}")
    print(f"  VE3 TOOL - WORKER MODE (Image/Video)")
    print(f"{'='*60}")
    print(f"  PROJECTS: {projects_dir}")
    print(f"  Scan interval: {SCAN_INTERVAL}s")
    print(f"{'='*60}")

    cycle = 0

    while True:
        cycle += 1
        print(f"\n[CYCLE {cycle}] Scanning {projects_dir}...")

        # Find all valid projects
        projects = scan_projects_folder(projects_dir)

        if not projects:
            print(f"  No projects with Excel found")
        else:
            # Filter pending projects
            pending = get_pending_projects(projects)

            print(f"  Found: {len(projects)} total, {len(pending)} pending")

            if pending:
                # Process pending projects
                success = 0
                failed = 0

                for project_dir in pending:
                    try:
                        if process_project(project_dir):
                            success += 1
                        else:
                            failed += 1
                    except Exception as e:
                        print(f"  ❌ Error processing {project_dir.name}: {e}")
                        failed += 1

                print(f"\n[CYCLE {cycle} DONE] {success} success, {failed} failed")
            else:
                print(f"  All projects complete!")

        # Wait before next scan
        print(f"\n  Waiting {SCAN_INTERVAL}s before next scan... (Ctrl+C to stop)")
        try:
            time.sleep(SCAN_INTERVAL)
        except KeyboardInterrupt:
            print("\n\nStopped by user.")
            break


def run_single_project(project_name: str, projects_dir: Path):
    """Run a single project by name."""
    project_dir = projects_dir / project_name

    if not project_dir.exists():
        print(f"[ERROR] Project not found: {project_dir}")
        return

    if not has_excel_with_prompts(project_dir, project_name):
        print(f"[ERROR] Project has no Excel with prompts: {project_name}")
        return

    process_project(project_dir)


def main():
    # Determine mode and path
    if len(sys.argv) >= 2:
        arg = sys.argv[1]
        arg_path = Path(arg)

        # Check if argument is a directory path or project name
        if arg_path.is_dir():
            # Full path to PROJECTS folder
            projects_dir = arg_path
            run_scan_loop(projects_dir)
        elif (PROJECTS_DIR / arg).exists():
            # Single project name
            run_single_project(arg, PROJECTS_DIR)
        else:
            print(f"[ERROR] Not found: {arg}")
            print(f"\nUsage:")
            print(f"  python run_worker.py                 (scan PROJECTS)")
            print(f"  python run_worker.py AR47-0028       (single project)")
            print(f"  python run_worker.py D:\\PROJECTS    (custom folder)")
            return
    else:
        # Default: scan PROJECTS folder
        if not PROJECTS_DIR.exists():
            print(f"[ERROR] PROJECTS folder not found: {PROJECTS_DIR}")
            print(f"\nUsage: python run_worker.py [project_name | projects_folder]")
            return

        run_scan_loop(PROJECTS_DIR)


if __name__ == "__main__":
    main()
