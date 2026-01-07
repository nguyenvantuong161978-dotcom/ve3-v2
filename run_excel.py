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
from pathlib import Path

# Add current directory to path
TOOL_DIR = Path(__file__).parent
sys.path.insert(0, str(TOOL_DIR))

# Default input folder
DEFAULT_VOICE_DIR = Path("D:/AUTO/voice")

# Output folder
PROJECTS_DIR = TOOL_DIR / "PROJECTS"

# Scan interval (seconds)
SCAN_INTERVAL = 30


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
    """Delete original voice file and its txt after processing."""
    try:
        name = voice_path.stem
        voice_dir = voice_path.parent

        # Delete voice file
        if voice_path.exists():
            voice_path.unlink()
            print(f"  🗑️ Deleted source: {voice_path.name}")

        # Delete associated txt file
        txt_path = voice_dir / f"{name}.txt"
        if txt_path.exists():
            txt_path.unlink()
            print(f"  🗑️ Deleted source: {txt_path.name}")

        # Delete parent folder if empty
        if voice_dir.exists():
            remaining = list(voice_dir.iterdir())
            if not remaining:
                voice_dir.rmdir()
                print(f"  🗑️ Deleted empty folder: {voice_dir.name}")

    except Exception as e:
        print(f"  ⚠️ Cleanup warning: {e}")


def process_voice_to_excel(voice_path: Path) -> bool:
    """Process single voice file to Excel."""
    name = voice_path.stem

    print(f"\n{'='*60}")
    print(f"Processing: {voice_path.name}")
    print(f"{'='*60}")

    # Output directory = PROJECTS/{name}/
    output_dir = PROJECTS_DIR / name
    output_dir.mkdir(parents=True, exist_ok=True)

    # Paths
    voice_copy = output_dir / voice_path.name
    srt_path = output_dir / f"{name}.srt"
    excel_path = output_dir / f"{name}_prompts.xlsx"

    print(f"  Input:  {voice_path}")
    print(f"  Output: {output_dir}")
    print()

    # === STEP 0: Copy voice file and txt to project folder ===
    if not voice_copy.exists():
        print(f"[STEP 0] Copying voice to project folder...")
        shutil.copy2(voice_path, voice_copy)
        print(f"  ✅ Copied: {voice_copy.name}")
    else:
        print(f"[SKIP] Voice already in project: {voice_copy.name}")

    # Copy .txt file if exists (same name as voice)
    txt_src = voice_path.parent / f"{name}.txt"
    txt_dst = output_dir / f"{name}.txt"
    if txt_src.exists() and not txt_dst.exists():
        shutil.copy2(txt_src, txt_dst)
        print(f"  ✅ Copied: {txt_dst.name}")

    # === STEP 1: Voice to SRT ===
    if srt_path.exists():
        print(f"[SKIP] SRT already exists: {srt_path.name}")
    else:
        print("[STEP 1] Creating SRT from voice (Whisper)...")
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

            print(f"  Whisper model: {whisper_model}, language: {whisper_lang}")

            from modules.voice_to_srt import VoiceToSrt
            conv = VoiceToSrt(model_name=whisper_model, language=whisper_lang)
            conv.transcribe(str(voice_copy), str(srt_path))
            print(f"  ✅ SRT created: {srt_path.name}")
        except Exception as e:
            print(f"  ❌ Whisper error: {e}")
            return False

    # === STEP 2: SRT to Excel (Prompts) ===
    if excel_path.exists():
        # Check if Excel already has prompts
        try:
            from modules.excel_manager import PromptWorkbook
            wb = PromptWorkbook(str(excel_path))
            stats = wb.get_stats()
            total_scenes = stats.get('total_scenes', 0)
            scenes_with_prompts = stats.get('scenes_with_prompts', 0)

            if total_scenes > 0 and scenes_with_prompts >= total_scenes:
                print(f"[SKIP] Excel already has prompts: {excel_path.name}")
                print(f"       ({scenes_with_prompts}/{total_scenes} scenes)")
                print(f"  ✅ Done! Project ready for worker.")
                # Cleanup: delete source voice file
                delete_voice_source(voice_path)
                return True
            else:
                print(f"  Excel exists but missing prompts ({scenes_with_prompts}/{total_scenes})")
                # Delete incomplete Excel to regenerate
                excel_path.unlink()
                print(f"  Deleted incomplete Excel, regenerating...")
        except Exception as e:
            print(f"  Warning: {e}")

    print("[STEP 2] Creating prompts from SRT (AI API)...")
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
            print("  ❌ No API keys found in config/settings.yaml")
            print("     Please add: deepseek_api_key, groq_api_keys, or gemini_api_keys")
            return False

        # Prefer DeepSeek for prompts
        cfg['preferred_provider'] = 'deepseek' if deepseek_key else ('groq' if groq_keys else 'gemini')

        print(f"  Using AI: {cfg['preferred_provider']}")

        # Generate prompts
        from modules.prompts_generator import PromptGenerator
        gen = PromptGenerator(cfg)

        # Generate for project (uses SRT in output_dir)
        if gen.generate_for_project(output_dir, name):
            print(f"  ✅ Excel created: {excel_path.name}")
        else:
            print(f"  ❌ Failed to generate prompts")
            return False

    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

    print()
    print(f"✅ Done! Project ready for worker: {output_dir}")

    # Cleanup: delete source voice file
    delete_voice_source(voice_path)

    return True


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


def run_scan_loop(voice_dir: Path):
    """Run continuous scan loop."""
    print(f"\n{'='*60}")
    print(f"  VE3 TOOL - VOICE TO EXCEL (MASTER MODE)")
    print(f"{'='*60}")
    print(f"  Input:  {voice_dir}")
    print(f"  Output: {PROJECTS_DIR}")
    print(f"  Scan interval: {SCAN_INTERVAL}s")
    print(f"{'='*60}")

    cycle = 0

    while True:
        cycle += 1
        print(f"\n[CYCLE {cycle}] Scanning {voice_dir}...")

        # Find all voice files
        voice_files = scan_voice_folder(voice_dir)

        if not voice_files:
            print(f"  No voice files found in subdirectories")
        else:
            # Filter pending files
            pending = get_pending_files(voice_files)

            print(f"  Found: {len(voice_files)} total, {len(pending)} pending")

            if pending:
                # Process pending files
                success = 0
                failed = 0

                for voice_path in pending:
                    try:
                        if process_voice_to_excel(voice_path):
                            success += 1
                        else:
                            failed += 1
                    except Exception as e:
                        print(f"  ❌ Error processing {voice_path.name}: {e}")
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
