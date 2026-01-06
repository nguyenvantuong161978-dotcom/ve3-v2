#!/usr/bin/env python3
"""
VE3 Tool - Voice to Excel (Master Mode)
Tạo SRT và Excel từ voice file.

Usage:
    python run_excel.py D:\AUTO\voice\AR41-T1\AR41-0029.mp3
    python run_excel.py D:\AUTO\voice\AR41-T1\  (scan folder)

Output sẽ được tạo trong PROJECTS\{voice_name}\:
    PROJECTS\AR41-0029\
    ├── AR41-0029.mp3         (copy từ input)
    ├── AR41-0029.srt
    └── AR41-0029_prompts.xlsx
"""

import sys
import os
import shutil
from pathlib import Path

# Add current directory to path
TOOL_DIR = Path(__file__).parent
sys.path.insert(0, str(TOOL_DIR))

# Output folder
PROJECTS_DIR = TOOL_DIR / "PROJECTS"


def process_voice_to_excel(voice_path: Path):
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
            from modules.voice_to_srt import VoiceToSrt
            conv = VoiceToSrt(model_name="base", language="vi")
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
                return True
            else:
                print(f"  Excel exists but missing prompts ({scenes_with_prompts}/{total_scenes})")
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
    return True


def scan_and_process(folder_path: Path):
    """Scan folder for voice files and process them."""
    voice_extensions = {'.mp3', '.wav', '.m4a', '.flac', '.ogg'}
    voice_files = []

    for f in folder_path.iterdir():
        if f.is_file() and f.suffix.lower() in voice_extensions:
            voice_files.append(f)

    if not voice_files:
        print(f"No voice files found in: {folder_path}")
        return

    print(f"Found {len(voice_files)} voice file(s) in {folder_path}")

    success = 0
    failed = 0

    for voice_file in sorted(voice_files):
        if process_voice_to_excel(voice_file):
            success += 1
        else:
            failed += 1

    print()
    print("="*60)
    print(f"SUMMARY: {success} success, {failed} failed")
    print(f"Output: {PROJECTS_DIR}")
    print("="*60)


def main():
    print()
    print("="*60)
    print("  VE3 TOOL - VOICE TO EXCEL (MASTER MODE)")
    print("="*60)
    print(f"  Output: {PROJECTS_DIR}")
    print()

    if len(sys.argv) < 2:
        # Interactive mode - ask for path
        print("Usage: python run_excel.py <voice_file_or_folder>")
        print()
        print("Examples:")
        print("  python run_excel.py D:\\AUTO\\voice\\AR41-T1\\AR41-0029.mp3")
        print("  python run_excel.py D:\\AUTO\\voice\\AR41-T1\\")
        print()

        user_input = input("Enter voice file or folder path: ").strip().strip('"')
        if not user_input:
            print("No path provided. Exiting.")
            return
        input_path = Path(user_input)
    else:
        input_path = Path(sys.argv[1])

    if not input_path.exists():
        print(f"[ERROR] Path not found: {input_path}")
        return

    if input_path.is_file():
        # Single file
        process_voice_to_excel(input_path)
    elif input_path.is_dir():
        # Folder - scan for voice files
        scan_and_process(input_path)
    else:
        print(f"[ERROR] Invalid path: {input_path}")


if __name__ == "__main__":
    main()
