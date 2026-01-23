"""
Chạy THẬT Step 7 để quan sát và tối ưu
"""
import sys
import io
from pathlib import Path
import yaml
import time

# Fix encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent))

from modules.progressive_prompts import ProgressivePromptsGenerator

# Setup
project_code = "AR8-0003"
project_dir = Path(__file__).parent / "PROJECTS" / project_code

# Load config
config_file = Path(__file__).parent / "config" / "settings.yaml"
with open(config_file, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

print("=" * 80)
print("CHẠY STEP 7 - SCENE PROMPTS (AR8-0003)")
print("=" * 80)
print()
print(f"Project: {project_code}")
print(f"Mode: {config.get('excel_mode', 'full')}")
print(f"Max parallel API: {config.get('max_parallel_api', 6)}")
print()

# Create generator
generator = ProgressivePromptsGenerator(config=config)

# Monitor start time
start_time = time.time()

print("Starting Step 7...")
print("-" * 80)

try:
    # Get workbook and SRT
    from modules.excel_manager import PromptWorkbook
    from modules.srt_parser import parse_srt_file

    excel_file = project_dir / f"{project_code}_prompts.xlsx"
    srt_file = project_dir / f"{project_code}.srt"

    workbook = PromptWorkbook(str(excel_file))
    srt_entries = parse_srt_file(str(srt_file))

    result = generator.step_create_scene_prompts(
        project_dir=project_dir,
        code=project_code,
        workbook=workbook,
        srt_entries=srt_entries
    )

    elapsed = time.time() - start_time

    print()
    print("-" * 80)
    print(f"Step 7 completed in {elapsed:.1f}s ({elapsed/60:.1f} minutes)")
    print()

    if result:
        print("[OK] Step 7 SUCCESS!")

        # Check result
        from modules.excel_manager import PromptWorkbook
        excel_file = project_dir / f"{project_code}_prompts.xlsx"
        workbook = PromptWorkbook(str(excel_file))
        scenes = workbook.get_scenes()

        print()
        print(f"Total scenes created: {len(scenes)}")

        if len(scenes) > 0:
            # Count video_note
            create_count = sum(1 for s in scenes if getattr(s, 'video_note', '') == "")
            skip_count = sum(1 for s in scenes if getattr(s, 'video_note', '') == "SKIP")

            print(f"  video_note='': {create_count} (CREATE video)")
            print(f"  video_note='SKIP': {skip_count} (SKIP video)")
            print()

            # Show first 5 scenes
            print("First 5 scenes:")
            for i, scene in enumerate(scenes[:5]):
                video_note = getattr(scene, 'video_note', '')
                print(f"  Scene {scene.scene_id}: video_note='{video_note}'")

    else:
        print("[ERROR] Step 7 FAILED!")

except Exception as e:
    elapsed = time.time() - start_time
    print()
    print(f"[ERROR] Exception after {elapsed:.1f}s: {e}")
    import traceback
    traceback.print_exc()

print()
print("=" * 80)
