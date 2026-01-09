#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VE3 Tool - Edit Mode (Compose MP4 on Master)
Chạy trên máy chủ, quét VISUAL folder và ghép video.

Workflow:
    1. Quét D:\AUTO\VISUAL\ tìm project đã có đủ video/ảnh
    2. Ghép video theo kế hoạch Excel (dùng SmartEngine._compose_video)
       - Đọc srt_start từ Excel
       - Xử lý video clips + images
       - Ken Burns effect, fade transitions
    3. Copy kết quả về D:\AUTO\done\{code}\
       - Video MP4
       - Thumbnail
       - SRT file
    4. Cập nhật Google Sheet: "EDIT XONG"

Usage:
    python run_edit.py                     (quét và xử lý tự động)
    python run_edit.py AR47-0028           (chạy 1 project cụ thể)
    python run_edit.py --parallel 3        (chạy 3 project song song)
    python run_edit.py --scan-only         (chỉ quét, không xử lý)
"""

import sys
import os
import time
import shutil
import json
import re
import subprocess
import argparse
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add current directory to path
TOOL_DIR = Path(__file__).parent
sys.path.insert(0, str(TOOL_DIR))

# === PATHS ===
VISUAL_DIR = Path(r"D:\AUTO\VISUAL")
DONE_DIR = Path(r"D:\AUTO\done")
THUMB_DIR = Path(r"D:\AUTO\thumbnails")
CONFIG_FILE = TOOL_DIR / "config" / "config.json"

# Scan interval (seconds)
SCAN_INTERVAL = 60

# Default parallel workers
DEFAULT_PARALLEL = 2

# Google Sheet config
SOURCE_SHEET_NAME = "NGUON"
SOURCE_COL_CODE = 7    # G
SOURCE_COL_STATUS = 13 # M
STATUS_VALUE = "EDIT XONG"

# Retry config
MAX_RETRIES = 5
RETRY_BASE_DELAY = 2


def log(msg: str, level: str = "INFO"):
    """Print log with timestamp."""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [{level}] {msg}")


def normalize_code(code: str) -> str:
    """Normalize code string."""
    if not code:
        return ""
    s = str(code)
    s = s.replace("–", "-").replace("—", "-").replace("−", "-")
    s = re.sub(r"\s+", " ", s).strip()
    return s.upper()


# ============================================================================
# PROJECT DETECTION
# ============================================================================

def get_project_info(project_dir: Path) -> Dict:
    """Get project info from directory."""
    code = project_dir.name

    info = {
        "code": code,
        "path": project_dir,
        "has_srt": False,
        "has_audio": False,
        "has_excel": False,
        "video_count": 0,
        "image_count": 0,
        "media_count": 0,  # FIX: khởi tạo mặc định
        "total_scenes": 0,
        "ready_for_edit": False,
        "already_done": False,
    }

    # Check files
    srt_path = project_dir / f"{code}.srt"
    audio_path = project_dir / f"{code}.mp3"
    excel_path = project_dir / f"{code}_prompts.xlsx"

    info["has_srt"] = srt_path.exists()
    info["has_audio"] = audio_path.exists()
    info["has_excel"] = excel_path.exists()
    info["srt_path"] = srt_path if srt_path.exists() else None
    info["audio_path"] = audio_path if audio_path.exists() else None
    info["excel_path"] = excel_path if excel_path.exists() else None

    # Check img folder
    img_dir = project_dir / "img"
    if img_dir.exists():
        # Count scene videos and images (not nv/loc)
        videos = [f for f in img_dir.glob("*.mp4")
                  if not f.stem.startswith('nv') and not f.stem.startswith('loc')]
        images = [f for f in img_dir.glob("*.png")
                  if not f.stem.startswith('nv') and not f.stem.startswith('loc')]
        info["video_count"] = len(videos)
        info["image_count"] = len(images)
        info["media_count"] = len(videos) + len(images)

        # Count total scenes from Excel
        if excel_path.exists():
            try:
                from modules.excel_manager import PromptWorkbook
                wb = PromptWorkbook(str(excel_path))
                stats = wb.get_stats()
                info["total_scenes"] = stats.get('total_scenes', 0)
            except:
                # Fallback: count from videos + images
                all_ids = set()
                for v in videos:
                    all_ids.add(v.stem)
                for i in images:
                    all_ids.add(i.stem)
                info["total_scenes"] = len(all_ids)

    # Check if already done
    done_dir = DONE_DIR / code
    if done_dir.exists():
        mp4_files = list(done_dir.glob("*.mp4"))
        info["already_done"] = len(mp4_files) > 0

    # Ready for edit: has media (video or image) and audio
    if info["media_count"] > 0 and info["has_audio"] and info["has_excel"]:
        # Check if have enough media (at least 80% of scenes)
        if info["total_scenes"] > 0:
            coverage = info["media_count"] / info["total_scenes"]
            info["ready_for_edit"] = coverage >= 0.8
        else:
            info["ready_for_edit"] = True

    return info


def scan_visual_projects() -> List[Dict]:
    """Scan VISUAL folder for projects ready to edit."""
    projects = []

    if not VISUAL_DIR.exists():
        log(f"VISUAL folder not found: {VISUAL_DIR}", "WARN")
        return projects

    # List all folders
    all_folders = [item for item in VISUAL_DIR.iterdir() if item.is_dir()]
    log(f"  [DEBUG] Found {len(all_folders)} folders in VISUAL")

    for item in all_folders:
        info = get_project_info(item)
        code = info["code"]

        # Debug: show why project is/isn't ready
        if info["already_done"]:
            log(f"    - {code}: already done ✓")
        elif info["ready_for_edit"]:
            log(f"    - {code}: ready ({info['video_count']}v + {info['image_count']}i / {info['total_scenes']} scenes)")
            projects.append(info)
        else:
            # Show why not ready
            reasons = []
            if info["media_count"] == 0:
                reasons.append("no media")
            if not info["has_audio"]:
                reasons.append("no audio")
            if not info["has_excel"]:
                reasons.append("no excel")
            if info["total_scenes"] > 0 and info["media_count"] > 0:
                coverage = info["media_count"] / info["total_scenes"]
                if coverage < 0.8:
                    reasons.append(f"coverage {coverage:.0%} < 80%")
            log(f"    - {code}: NOT ready ({', '.join(reasons)})")

    return sorted(projects, key=lambda x: x["code"])


# ============================================================================
# VIDEO COMPOSITION (Using SmartEngine)
# ============================================================================

def compose_video(project_info: Dict, callback=None) -> Tuple[bool, Optional[Path], Optional[str]]:
    """
    Compose final video using SmartEngine._compose_video.

    Handles:
    - Reading Excel timeline (srt_start)
    - Video clips + images
    - Ken Burns effect, fade transitions
    - Audio merge

    Returns:
        Tuple[success, output_path, error]
    """
    code = project_info["code"]
    project_dir = project_info["path"]
    excel_path = project_info.get("excel_path")

    def plog(msg, level="INFO"):
        if callback:
            callback(msg, level)
        else:
            log(f"[{code}] {msg}", level)

    plog("Starting video composition (SmartEngine)...")

    if not excel_path or not excel_path.exists():
        return False, None, "Excel file not found"

    try:
        from modules.smart_engine import SmartEngine

        # Create engine instance
        engine = SmartEngine()
        engine.callback = lambda msg: plog(msg)  # SmartEngine callback chỉ gửi 1 arg

        # Call compose method
        output_path = engine._compose_video(project_dir, excel_path, code)

        if output_path and output_path.exists():
            plog(f"Video composed: {output_path.name}")
            return True, output_path, None
        else:
            return False, None, "Compose returned no output"

    except Exception as e:
        plog(f"Compose error: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return False, None, str(e)


# ============================================================================
# COPY TO DONE
# ============================================================================

def find_thumbnail(code: str) -> Optional[Path]:
    """Find thumbnail for project."""
    if not THUMB_DIR.exists():
        return None

    for ext in [".png", ".jpg", ".jpeg", ".webp"]:
        thumb = THUMB_DIR / f"{code}{ext}"
        if thumb.exists():
            return thumb

    return None


def copy_to_done(project_info: Dict, video_path: Path, callback=None) -> Tuple[bool, Optional[str]]:
    """
    Copy results to done folder.

    Returns:
        Tuple[success, error]
    """
    code = project_info["code"]
    project_dir = project_info["path"]

    def plog(msg, level="INFO"):
        if callback:
            callback(msg, level)
        else:
            log(f"[{code}] {msg}", level)

    # Create done folder
    done_folder = DONE_DIR / code

    # Remove old folder if exists
    if done_folder.exists():
        plog("Removing old done folder...")
        shutil.rmtree(done_folder)

    done_folder.mkdir(parents=True, exist_ok=True)
    plog(f"Created: {done_folder}")

    # Copy video
    dst_video = done_folder / video_path.name
    shutil.copy2(video_path, dst_video)
    plog(f"Copied video: {dst_video.name}")

    # Copy SRT
    srt_path = project_info.get("srt_path")
    if srt_path and srt_path.exists():
        dst_srt = done_folder / f"{code}.srt"
        shutil.copy2(srt_path, dst_srt)
        plog(f"Copied SRT: {dst_srt.name}")
    else:
        plog("SRT not found, skipping", "WARN")

    # Copy thumbnail
    thumb_path = find_thumbnail(code)
    if thumb_path:
        dst_thumb = done_folder / thumb_path.name
        shutil.copy2(thumb_path, dst_thumb)
        plog(f"Copied thumbnail: {dst_thumb.name}")
    else:
        plog("Thumbnail not found, skipping", "WARN")

    # Verify
    files = list(done_folder.iterdir())
    plog(f"Done folder has {len(files)} files")

    return True, None


def delete_visual_project(project_info: Dict, callback=None) -> bool:
    """
    Delete project from VISUAL folder after successful copy to DONE.

    Returns:
        True if deleted successfully
    """
    code = project_info["code"]
    project_dir = project_info["path"]

    def plog(msg, level="INFO"):
        if callback:
            callback(msg, level)
        else:
            log(f"[{code}] {msg}", level)

    if not project_dir.exists():
        return True  # Already deleted

    try:
        shutil.rmtree(project_dir)
        plog(f"Deleted VISUAL folder: {project_dir.name}")
        return True
    except Exception as e:
        plog(f"Cannot delete VISUAL folder: {e}", "WARN")
        return False


# ============================================================================
# GOOGLE SHEET UPDATE
# ============================================================================

def load_gsheet_client():
    """Load Google Sheet client."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        log("gspread not installed. Run: pip install gspread google-auth", "ERROR")
        return None, None, None

    if not CONFIG_FILE.exists():
        log(f"Config file not found: {CONFIG_FILE}", "WARN")
        return None, None, None

    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

        sa_path = (
            cfg.get("SERVICE_ACCOUNT_JSON") or
            cfg.get("service_account_json") or
            cfg.get("CREDENTIAL_PATH") or
            cfg.get("credential_path")
        )

        if not sa_path:
            log("Missing SERVICE_ACCOUNT_JSON in config", "WARN")
            return None, None, None

        spreadsheet_name = cfg.get("SPREADSHEET_NAME")
        if not spreadsheet_name:
            log("Missing SPREADSHEET_NAME in config", "WARN")
            return None, None, None

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.readonly",
        ]

        sa_file = Path(sa_path)
        if not sa_file.exists():
            sa_file = TOOL_DIR / "config" / sa_path

        if not sa_file.exists():
            log(f"Service account file not found: {sa_path}", "WARN")
            return None, None, None

        creds = Credentials.from_service_account_file(str(sa_file), scopes=scopes)
        gc = gspread.authorize(creds)

        return gc, spreadsheet_name, cfg

    except Exception as e:
        log(f"Error loading gsheet client: {e}", "ERROR")
        return None, None, None


def update_sheet_status(codes: List[str], callback=None) -> Tuple[int, int]:
    """
    Update Google Sheet status for completed projects.

    Returns:
        Tuple[found_count, updated_count]
    """
    if not codes:
        return 0, 0

    def plog(msg, level="INFO"):
        if callback:
            callback(msg, level)
        else:
            log(msg, level)

    gc, spreadsheet_name, cfg = load_gsheet_client()
    if not gc:
        plog("Google Sheet client not available", "WARN")
        return 0, 0

    try:
        from gspread.exceptions import APIError

        def do_update():
            ws = gc.open(spreadsheet_name).worksheet(SOURCE_SHEET_NAME)
            raw_g = ws.col_values(SOURCE_COL_CODE)
            raw_m = ws.col_values(SOURCE_COL_STATUS)

            # Build code to row mapping
            code_to_rows = {}
            for idx, val in enumerate(raw_g, start=1):
                norm = normalize_code(val)
                if norm:
                    code_to_rows.setdefault(norm, []).append(idx)

            targets = [normalize_code(c) for c in codes if c]
            targets = list(set(t for t in targets if t))

            plog(f"Updating {len(targets)} codes in sheet...")

            found, updates = 0, []
            for code in targets:
                rows = code_to_rows.get(code, [])
                if not rows:
                    plog(f"  Code '{code}' not found in sheet", "WARN")
                    continue

                found += len(rows)
                for r in rows:
                    current = raw_m[r-1] if r-1 < len(raw_m) else ""
                    if current.strip().upper() == STATUS_VALUE.upper():
                        continue  # Already done

                    plog(f"  Updating {code} @ row {r}: M{r} = {STATUS_VALUE}")
                    updates.append({"range": f"M{r}", "values": [[STATUS_VALUE]]})

            if not updates:
                plog("No updates needed")
                return found, 0

            ws.batch_update(updates, value_input_option="USER_ENTERED")
            plog(f"Updated {len(updates)} rows")
            return found, len(updates)

        # Retry with backoff
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                return do_update()
            except APIError as e:
                last_error = e
                if e.response.status_code in (429, 500, 502, 503, 504):
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    plog(f"API error {e.response.status_code}, retrying in {delay}s...", "WARN")
                    time.sleep(delay)
                else:
                    raise
            except Exception as e:
                last_error = e
                if "timeout" in str(e).lower() or "connection" in str(e).lower():
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    plog(f"Network error, retrying in {delay}s...", "WARN")
                    time.sleep(delay)
                else:
                    raise

        raise last_error

    except Exception as e:
        plog(f"Error updating sheet: {e}", "ERROR")
        return 0, 0


# ============================================================================
# PROCESS PROJECT
# ============================================================================

def process_project(project_info: Dict, callback=None) -> bool:
    """Process a single project: compose + copy + update sheet."""
    code = project_info["code"]

    def plog(msg, level="INFO"):
        if callback:
            callback(msg, level)
        else:
            log(f"[{code}] {msg}", level)

    plog("="*50)
    plog(f"Processing: {code}")
    plog("="*50)
    plog(f"Media: {project_info['video_count']} videos + {project_info['image_count']} images")
    plog(f"Scenes: {project_info['total_scenes']}")

    # Step 1: Compose video (using SmartEngine)
    success, video_path, error = compose_video(project_info, callback)
    if not success:
        plog(f"Compose failed: {error}", "ERROR")
        return False

    # Step 2: Copy to done
    success, error = copy_to_done(project_info, video_path, callback)
    if not success:
        plog(f"Copy failed: {error}", "ERROR")
        return False

    # Step 3: Delete from VISUAL (cleanup disk space)
    delete_visual_project(project_info, callback)

    # Step 4: Update sheet
    found, updated = update_sheet_status([code], callback)
    if updated > 0:
        plog(f"Sheet updated: {STATUS_VALUE}")

    plog(f"DONE: {code}")
    return True


# ============================================================================
# MAIN
# ============================================================================

def run_scan_loop(parallel: int = DEFAULT_PARALLEL):
    """Run continuous scan loop."""
    log("="*60)
    log("  VE3 TOOL - EDIT MODE (Compose MP4)")
    log("="*60)
    log(f"  VISUAL folder: {VISUAL_DIR}")
    log(f"  DONE folder:   {DONE_DIR}")
    log(f"  Parallel:      {parallel}")
    log(f"  Scan interval: {SCAN_INTERVAL}s")
    log("="*60)

    # Create folders if needed
    DONE_DIR.mkdir(parents=True, exist_ok=True)

    cycle = 0

    while True:
        cycle += 1
        log(f"\n[CYCLE {cycle}] Scanning VISUAL folder...")

        # Find pending projects
        pending = scan_visual_projects()

        if not pending:
            log("  No pending projects")
        else:
            log(f"  Found {len(pending)} projects ready to edit:")
            for p in pending[:5]:
                log(f"    - {p['code']} ({p['video_count']}v + {p['image_count']}i / {p['total_scenes']} scenes)")
            if len(pending) > 5:
                log(f"    ... and {len(pending) - 5} more")

            # Process projects in parallel
            batch = pending[:parallel]
            log(f"\n  Processing {len(batch)} projects...")

            with ThreadPoolExecutor(max_workers=parallel) as executor:
                futures = {
                    executor.submit(process_project, p): p
                    for p in batch
                }

                for future in as_completed(futures):
                    project = futures[future]
                    try:
                        success = future.result()
                        if success:
                            log(f"  {project['code']}: SUCCESS", "OK")
                        else:
                            log(f"  {project['code']}: FAILED", "ERROR")
                    except Exception as e:
                        log(f"  {project['code']}: EXCEPTION - {e}", "ERROR")

        # Wait before next scan
        log(f"\n  Waiting {SCAN_INTERVAL}s... (Ctrl+C to stop)")
        try:
            time.sleep(SCAN_INTERVAL)
        except KeyboardInterrupt:
            log("\n\nStopped by user.")
            break


def run_single_project(code: str):
    """Run a single project by code."""
    project_dir = VISUAL_DIR / code

    if not project_dir.exists():
        log(f"Project not found: {project_dir}", "ERROR")
        return

    info = get_project_info(project_dir)

    if info["already_done"]:
        log(f"Project already done: {code}", "WARN")
        return

    if not info["ready_for_edit"]:
        log(f"Project not ready: {code}", "WARN")
        log(f"  Media: {info['video_count']}v + {info['image_count']}i / {info['total_scenes']} scenes")
        log(f"  Audio: {info['has_audio']}")
        log(f"  Excel: {info['has_excel']}")
        return

    process_project(info)


def run_scan_only():
    """Scan and show status only."""
    log("="*60)
    log("  VE3 TOOL - EDIT MODE (Scan Only)")
    log("="*60)

    pending = scan_visual_projects()

    if not pending:
        log("No pending projects found")
        return

    log(f"\nFound {len(pending)} projects ready to edit:\n")

    for p in pending:
        log(f"  {p['code']}:")
        log(f"    Media:  {p['video_count']} videos + {p['image_count']} images / {p['total_scenes']} scenes")
        log(f"    Audio:  {'YES' if p['has_audio'] else 'NO'}")
        log(f"    Excel:  {'YES' if p['has_excel'] else 'NO'}")
        log(f"    SRT:    {'YES' if p['has_srt'] else 'NO'}")


def main():
    parser = argparse.ArgumentParser(description="VE3 Tool - Edit Mode (Compose MP4)")
    parser.add_argument("code", nargs="?", help="Process single project by code")
    parser.add_argument("--parallel", "-p", type=int, default=DEFAULT_PARALLEL,
                        help=f"Number of parallel workers (default: {DEFAULT_PARALLEL})")
    parser.add_argument("--scan-only", action="store_true",
                        help="Only scan and show status")
    args = parser.parse_args()

    if args.scan_only:
        run_scan_only()
    elif args.code:
        run_single_project(args.code)
    else:
        run_scan_loop(parallel=args.parallel)


if __name__ == "__main__":
    main()
