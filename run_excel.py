#!/usr/bin/env python3
"""
VE3 Tool - Voice to Excel (Master Mode)
Tự động quét thư mục voice và tạo SRT + Excel.

Usage:
    python run_excel.py                     (quét D:\AUTO\voice mặc định)
    python run_excel.py D:\path\to\voice    (quét thư mục khác)

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
    ├── AR47-0028.srt
    └── AR47-0028_prompts.xlsx
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


def is_project_complete(project_dir: Path, name: str) -> bool:
    """Check if project has Excel with all prompts filled."""
    excel_path = project_dir / f"{name}_prompts.xlsx"

    if not excel_path.exists():
        return False

    try:
        from modules.excel_manager import PromptWorkbook
        wb = PromptWorkbook(str(excel_path))
        stats = wb.get_stats()
        total_scenes = stats.get('total_scenes', 0)
        scenes_with_prompts = stats.get('scenes_with_prompts', 0)

        # Complete if all scenes have prompts
        return total_scenes > 0 and scenes_with_prompts >= total_scenes
    except:
        return False


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
                    print(f"  🗑️ Deleted: {item.name}")
                    deleted_count += 1
                except Exception as e:
                    print(f"  ⚠️ Cannot delete {item.name}: {e}")

        # 2. Delete txt file in parent folder (D:\AUTO\voice\AR35-0001.txt)
        parent_txt = parent_dir / f"{name}.txt"
        if parent_txt.exists():
            try:
                parent_txt.unlink()
                print(f"  🗑️ Deleted: {parent_dir.name}/{parent_txt.name}")
                deleted_count += 1
            except Exception as e:
                print(f"  ⚠️ Cannot delete {parent_txt.name}: {e}")

        if deleted_count > 0:
            print(f"  🗑️ Cleaned up {deleted_count} items for {name}")

        # Delete channel folder if empty
        if voice_dir.exists():
            remaining = list(voice_dir.iterdir())
            if not remaining:
                voice_dir.rmdir()
                print(f"  🗑️ Deleted empty folder: {voice_dir.name}")

    except Exception as e:
        print(f"  ⚠️ Cleanup warning: {e}")


def process_voice_to_srt(voice_path: Path) -> bool:
    """
    Process voice file to SRT (Step 0 + Step 1 only).
    Returns True if SRT exists/created successfully.
    """
    name = voice_path.stem

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
        return True  # Already done

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
        safe_print(f"[SRT] {name}: ✅ Done")
        return True
    except Exception as e:
        safe_print(f"[SRT] {name}: ❌ Error - {e}")
        return False


def process_srt_to_excel(project_dir: Path, voice_source: Path = None) -> bool:
    """
    Process SRT to Excel (Step 2 only).
    Requires SRT to exist already.
    Returns True if Excel created successfully.
    """
    name = project_dir.name
    srt_path = project_dir / f"{name}.srt"
    excel_path = project_dir / f"{name}_prompts.xlsx"

    # Must have SRT
    if not srt_path.exists():
        return False

    # Check if Excel already complete
    if excel_path.exists():
        try:
            from modules.excel_manager import PromptWorkbook
            wb = PromptWorkbook(str(excel_path))
            stats = wb.get_stats()
            total_scenes = stats.get('total_scenes', 0)
            scenes_with_prompts = stats.get('scenes_with_prompts', 0)

            if total_scenes > 0 and scenes_with_prompts >= total_scenes:
                # Already complete - cleanup source
                if voice_source:
                    delete_voice_source(voice_source)
                return True
            else:
                # Incomplete - delete and regenerate
                excel_path.unlink()
        except Exception as e:
            safe_print(f"[API] {name}: Warning - {e}")

    safe_print(f"[API] {name}: Creating prompts (AI API)...")
    try:
        # Load config
        import yaml
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
            safe_print(f"[API] {name}: ❌ No API keys configured")
            return False

        # Prefer DeepSeek for prompts
        cfg['preferred_provider'] = 'deepseek' if deepseek_key else ('groq' if groq_keys else 'gemini')

        # Generate prompts
        from modules.prompts_generator import PromptGenerator
        gen = PromptGenerator(cfg)

        if gen.generate_for_project(project_dir, name):
            safe_print(f"[API] {name}: ✅ Excel created")
            # Cleanup source voice file
            if voice_source:
                delete_voice_source(voice_source)
            return True
        else:
            safe_print(f"[API] {name}: ❌ Failed to generate prompts")
            return False

    except Exception as e:
        safe_print(f"[API] {name}: ❌ Error - {e}")
        import traceback
        traceback.print_exc()
        return False


def process_voice_to_excel(voice_path: Path) -> bool:
    """Process single voice file to Excel (legacy sequential mode)."""
    name = voice_path.stem
    output_dir = PROJECTS_DIR / name

    # Step 1: Voice to SRT
    if not process_voice_to_srt(voice_path):
        return False

    # Step 2: SRT to Excel
    return process_srt_to_excel(output_dir, voice_path)


def scan_voice_folder(voice_dir: Path) -> list:
    """Scan voice folder for mp3 files in subdirectories."""
    voice_extensions = {'.mp3', '.wav', '.m4a', '.flac', '.ogg'}
    voice_files = []

    # Scan subdirectories (1 level deep)
    for subdir in voice_dir.iterdir():
        if subdir.is_dir():
            for f in subdir.iterdir():
                if f.is_file() and f.suffix.lower() in voice_extensions:
                    voice_files.append(f)

    return sorted(voice_files)


def get_pending_files(voice_files: list) -> list:
    """Filter voice files that need processing."""
    pending = []

    for voice_path in voice_files:
        name = voice_path.stem
        project_dir = PROJECTS_DIR / name

        # Check if project is complete
        if not is_project_complete(project_dir, name):
            pending.append(voice_path)

    return pending


def scan_incomplete_projects() -> list:
    """
    Scan PROJECTS folder for incomplete projects.
    Returns list of project folders that have voice but incomplete Excel.
    """
    incomplete = []

    if not PROJECTS_DIR.exists():
        return incomplete

    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue

        name = project_dir.name

        # Skip if already complete
        if is_project_complete(project_dir, name):
            continue

        # Check if project has voice file (mp3/wav/etc.)
        voice_extensions = {'.mp3', '.wav', '.m4a', '.flac', '.ogg'}
        has_voice = any(
            f.suffix.lower() in voice_extensions
            for f in project_dir.iterdir()
            if f.is_file()
        )

        if has_voice:
            # Find the voice file
            for f in project_dir.iterdir():
                if f.is_file() and f.suffix.lower() in voice_extensions:
                    incomplete.append(f)
                    break

    return sorted(incomplete, key=lambda x: x.stem)


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


def get_pending_api() -> list:
    """Get projects that have SRT but need Excel."""
    pending = []

    if not PROJECTS_DIR.exists():
        return pending

    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        name = project_dir.name
        srt_path = project_dir / f"{name}.srt"
        excel_path = project_dir / f"{name}_prompts.xlsx"

        # Must have SRT
        if not srt_path.exists():
            continue

        # Check if Excel complete
        if is_project_complete(project_dir, name):
            continue

        pending.append(project_dir)

    return pending


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


def api_worker(voice_dir: Path, stop_event: threading.Event):
    """Worker thread for API/Excel generation (runs continuously)."""
    safe_print("[API Worker] Started")

    # Build voice source mapping for cleanup
    def get_voice_source(name: str) -> Path:
        """Find original voice file for a project."""
        # Check voice folder
        for subdir in voice_dir.iterdir():
            if subdir.is_dir():
                for ext in ['.mp3', '.wav', '.m4a', '.flac', '.ogg']:
                    voice_path = subdir / f"{name}{ext}"
                    if voice_path.exists():
                        return voice_path
        return None

    while not stop_event.is_set():
        try:
            pending = get_pending_api()

            if pending:
                safe_print(f"[API Worker] Found {len(pending)} projects needing Excel")
                for project_dir in pending:
                    if stop_event.is_set():
                        break
                    voice_source = get_voice_source(project_dir.name)
                    process_srt_to_excel(project_dir, voice_source)

            # Short sleep between checks
            stop_event.wait(5)
        except Exception as e:
            safe_print(f"[API Worker] Error: {e}")
            stop_event.wait(10)

    safe_print("[API Worker] Stopped")


def run_scan_loop(voice_dir: Path):
    """Run parallel processing with SRT and API workers."""
    print(f"\n{'='*60}")
    print(f"  VE3 TOOL - VOICE TO EXCEL (PARALLEL MODE)")
    print(f"{'='*60}")
    print(f"  Input:  {voice_dir}")
    print(f"  Output: {PROJECTS_DIR}")
    print(f"  Mode:   SRT + API workers running in parallel")
    print(f"{'='*60}")

    stop_event = threading.Event()

    # Start worker threads
    srt_thread = threading.Thread(target=srt_worker, args=(voice_dir, stop_event), daemon=True)
    api_thread = threading.Thread(target=api_worker, args=(voice_dir, stop_event), daemon=True)

    srt_thread.start()
    api_thread.start()

    # Status monitor loop
    cycle = 0
    try:
        while True:
            cycle += 1
            time.sleep(SCAN_INTERVAL)

            # Print status
            pending_srt = get_pending_srt(voice_dir)
            pending_api = get_pending_api()

            safe_print(f"\n[STATUS {cycle}] SRT pending: {len(pending_srt)}, API pending: {len(pending_api)}")

            if not pending_srt and not pending_api:
                safe_print("  All projects complete!")

    except KeyboardInterrupt:
        safe_print("\n\nStopping workers...")
        stop_event.set()
        srt_thread.join(timeout=5)
        api_thread.join(timeout=5)
        safe_print("Stopped.")


def main():
    # Determine voice directory
    if len(sys.argv) >= 2:
        voice_dir = Path(sys.argv[1])
    else:
        voice_dir = DEFAULT_VOICE_DIR

    if not voice_dir.exists():
        print(f"[ERROR] Voice directory not found: {voice_dir}")
        print(f"\nUsage: python run_excel.py [voice_folder]")
        print(f"Default: {DEFAULT_VOICE_DIR}")
        return

    # Ensure PROJECTS directory exists
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

    # Run scan loop
    run_scan_loop(voice_dir)


if __name__ == "__main__":
    main()
