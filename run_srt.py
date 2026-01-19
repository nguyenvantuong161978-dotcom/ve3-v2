#!/usr/bin/env python3
"""
VE3 Tool - Voice to SRT (Master Mode - SRT ONLY)
Tự động quét thư mục voice và tạo SRT.

QUAN TRỌNG: Script này CHỈ tạo SRT, KHÔNG tạo Excel.
Worker VMs (run_worker.py) sẽ tạo Excel bằng API.

Usage:
    python run_srt.py                     (quét D:\AUTO\voice mặc định)
    python run_srt.py D:\path\to\voice    (quét thư mục khác)

Cấu trúc input:
    D:\AUTO\voice\
    ├── AR47-T1\
    │   ├── AR47-0028.mp3
    │   └── AR47-0029.mp3
    └── AR48-T1\
        └── AR48-0023.mp3

Output trong PROJECTS\{voice_name}\:
    PROJECTS\AR47-0028\
    ├── AR47-0028.mp3
    ├── AR47-0028.txt (nếu có)
    └── AR47-0028.srt

Worker VMs sẽ:
    1. Copy project từ master
    2. Tạo Excel bằng API (hoặc fallback nếu API fail)
    3. Tạo ảnh/video
"""

import sys
import os
import shutil
import time
import threading
from pathlib import Path
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor

# Add current directory to path
TOOL_DIR = Path(__file__).parent
sys.path.insert(0, str(TOOL_DIR))

# Default input folder
DEFAULT_VOICE_DIR = Path("D:/AUTO/voice")

# Output folder
PROJECTS_DIR = TOOL_DIR / "PROJECTS"

# Scan interval (seconds)
SCAN_INTERVAL = 30

# Thread-safe print lock
_print_lock = threading.Lock()

def safe_print(*args, **kwargs):
    """Thread-safe print."""
    with _print_lock:
        print(*args, **kwargs)


def is_project_has_srt(project_dir: Path, name: str) -> bool:
    """Check if project has SRT file."""
    srt_path = project_dir / f"{name}.srt"
    return srt_path.exists()


def delete_voice_source(voice_path: Path):
    """
    Delete all files/folders related to this voice in the voice folder.

    Example: D:\\AUTO\\voice\\AR35-T1\\AR35-0001.mp3 -> delete all:
    - D:\\AUTO\\voice\\AR35-T1\\AR35-0001.mp3
    - D:\\AUTO\\voice\\AR35-T1\\AR35-0001.txt
    - D:\\AUTO\\voice\\AR35-T1\\AR35-0001-log.dgt
    - D:\\AUTO\\voice\\AR35-T1\\AR35-0001\\ (folder)
    - D:\\AUTO\\voice\\AR35-0001.txt (in parent folder)
    """
    try:
        name = voice_path.stem  # e.g., "AR35-0001"
        voice_dir = voice_path.parent  # e.g., D:\AUTO\voice\AR35-T1
        parent_dir = voice_dir.parent  # e.g., D:\AUTO\voice

        deleted_count = 0

        # 1. Delete all items starting with this name in channel folder
        for item in voice_dir.iterdir():
            if item.name.startswith(name):
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                    print(f"  [DEL] Deleted: {item.name}")
                    deleted_count += 1
                except Exception as e:
                    print(f"  [WARN] Cannot delete {item.name}: {e}")

        # 2. Delete txt file in parent folder (D:\AUTO\voice\AR35-0001.txt)
        parent_txt = parent_dir / f"{name}.txt"
        if parent_txt.exists():
            try:
                parent_txt.unlink()
                print(f"  [DEL] Deleted: {parent_dir.name}/{parent_txt.name}")
                deleted_count += 1
            except Exception as e:
                print(f"  [WARN] Cannot delete {parent_txt.name}: {e}")

        if deleted_count > 0:
            print(f"  [DEL] Cleaned up {deleted_count} items for {name}")

        # Delete channel folder if empty
        if voice_dir.exists():
            remaining = list(voice_dir.iterdir())
            if not remaining:
                voice_dir.rmdir()
                print(f"  [DEL] Deleted empty folder: {voice_dir.name}")

    except Exception as e:
        print(f"  [WARN] Cleanup warning: {e}")


def process_voice_to_srt(voice_path: Path) -> bool:
    """
    Process voice file to SRT (Step 0 + Step 1 only).
    Returns True if SRT exists/created successfully.

    Sau khi SRT xong, cleanup source voice file.
    """
    name = voice_path.stem

    # Check if voice is from source folder (not already in PROJECTS)
    is_from_source = PROJECTS_DIR not in voice_path.parents

    # Output directory = PROJECTS/{name}/
    output_dir = PROJECTS_DIR / name
    output_dir.mkdir(parents=True, exist_ok=True)

    # Paths
    voice_copy = output_dir / voice_path.name
    srt_path = output_dir / f"{name}.srt"

    # === STEP 0: Copy voice file and txt to project folder ===
    if not voice_copy.exists():
        safe_print(f"[SRT] {name}: Copying voice...")
        shutil.copy2(voice_path, voice_copy)

    # Copy .txt file if exists (same name as voice)
    txt_src = voice_path.parent / f"{name}.txt"
    txt_dst = output_dir / f"{name}.txt"
    if txt_src.exists() and not txt_dst.exists():
        shutil.copy2(txt_src, txt_dst)

    # === STEP 1: Voice to SRT ===
    if srt_path.exists():
        # Already done - cleanup source if needed
        if is_from_source:
            delete_voice_source(voice_path)
        return True

    safe_print(f"[SRT] {name}: Creating SRT (Whisper)...")
    try:
        # Load whisper settings from config
        import yaml
        whisper_cfg = {}
        cfg_file = TOOL_DIR / "config" / "settings.yaml"
        if cfg_file.exists():
            with open(cfg_file, "r", encoding="utf-8") as f:
                whisper_cfg = yaml.safe_load(f) or {}

        whisper_model = whisper_cfg.get('whisper_model', 'medium')
        whisper_lang = whisper_cfg.get('whisper_language', 'en')

        from modules.voice_to_srt import VoiceToSrt
        conv = VoiceToSrt(model_name=whisper_model, language=whisper_lang)
        conv.transcribe(str(voice_copy), str(srt_path))
        safe_print(f"[SRT] {name}: [OK] Done")

        # Cleanup source voice file after successful SRT
        if is_from_source:
            delete_voice_source(voice_path)

        return True
    except Exception as e:
        safe_print(f"[SRT] {name}: [FAIL] Error - {e}")
        return False


def scan_voice_folder(voice_dir: Path) -> list:
    """Scan voice folder for audio files (root + subdirectories)."""
    voice_extensions = {'.mp3', '.wav', '.m4a', '.flac', '.ogg'}
    voice_files = []

    # Scan files directly in voice_dir (root level)
    for f in voice_dir.iterdir():
        if f.is_file() and f.suffix.lower() in voice_extensions:
            voice_files.append(f)

    # Scan subdirectories (1 level deep)
    for subdir in voice_dir.iterdir():
        if subdir.is_dir():
            for f in subdir.iterdir():
                if f.is_file() and f.suffix.lower() in voice_extensions:
                    voice_files.append(f)

    return sorted(voice_files)


def get_pending_srt(voice_dir: Path) -> list:
    """Get voice files that need SRT generation."""
    pending = []

    # From voice folder
    voice_files = scan_voice_folder(voice_dir)
    for voice_path in voice_files:
        name = voice_path.stem
        project_dir = PROJECTS_DIR / name
        srt_path = project_dir / f"{name}.srt"
        if not srt_path.exists():
            pending.append(voice_path)

    # From PROJECTS folder (incomplete)
    if PROJECTS_DIR.exists():
        for project_dir in PROJECTS_DIR.iterdir():
            if not project_dir.is_dir():
                continue
            name = project_dir.name
            srt_path = project_dir / f"{name}.srt"
            if srt_path.exists():
                continue
            # Find voice file in project
            voice_extensions = {'.mp3', '.wav', '.m4a', '.flac', '.ogg'}
            for f in project_dir.iterdir():
                if f.is_file() and f.suffix.lower() in voice_extensions:
                    pending.append(f)
                    break

    # Deduplicate by name
    seen = set()
    result = []
    for v in pending:
        if v.stem not in seen:
            result.append(v)
            seen.add(v.stem)
    return result


def srt_worker(voice_dir: Path, stop_event: threading.Event):
    """Worker thread for SRT generation (runs continuously)."""
    safe_print("[SRT Worker] Started")

    while not stop_event.is_set():
        try:
            pending = get_pending_srt(voice_dir)

            if pending:
                safe_print(f"[SRT Worker] Found {len(pending)} voices needing SRT")
                for voice_path in pending:
                    if stop_event.is_set():
                        break
                    process_voice_to_srt(voice_path)

            # Short sleep between checks
            stop_event.wait(5)
        except Exception as e:
            safe_print(f"[SRT Worker] Error: {e}")
            stop_event.wait(10)

    safe_print("[SRT Worker] Stopped")


def run_scan_loop(voice_dir: Path):
    """Run SRT worker only (Excel sẽ do Worker VMs tạo)."""
    print(f"\n{'='*60}")
    print(f"  VE3 TOOL - VOICE TO SRT (SRT ONLY)")
    print(f"{'='*60}")
    print(f"  Input:  {voice_dir}")
    print(f"  Output: {PROJECTS_DIR}")
    print(f"  Mode:   SRT ONLY (không tạo Excel)")
    print(f"         Worker VMs sẽ tạo Excel bằng API")
    print(f"{'='*60}")

    stop_event = threading.Event()

    # Start SRT worker thread only
    srt_thread = threading.Thread(target=srt_worker, args=(voice_dir, stop_event), daemon=True)
    srt_thread.start()

    # Status monitor loop
    cycle = 0
    try:
        while True:
            cycle += 1
            time.sleep(SCAN_INTERVAL)

            # Print status
            pending_srt = get_pending_srt(voice_dir)

            safe_print(f"\n[STATUS {cycle}] SRT pending: {len(pending_srt)}")

            if not pending_srt:
                safe_print("  All voices have SRT! Worker VMs will create Excel.")

    except KeyboardInterrupt:
        safe_print("\n\nStopping worker...")
        stop_event.set()
        srt_thread.join(timeout=5)
        safe_print("Stopped.")


def main():
    # Determine voice directory
    if len(sys.argv) >= 2:
        voice_dir = Path(sys.argv[1])
    else:
        voice_dir = DEFAULT_VOICE_DIR

    if not voice_dir.exists():
        print(f"[ERROR] Voice directory not found: {voice_dir}")
        print(f"\nUsage: python run_srt.py [voice_folder]")
        print(f"Default: {DEFAULT_VOICE_DIR}")
        return

    # Ensure PROJECTS directory exists
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

    # Run scan loop
    run_scan_loop(voice_dir)


if __name__ == "__main__":
    main()
