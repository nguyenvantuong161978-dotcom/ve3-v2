"""
CHẠY THẬT AR8-0003 - Steps 1-7 hoàn chỉnh
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
print(f"CHẠY THẬT EXCEL WORKER - {project_code}")
print("=" * 80)
print()
print(f"Mode: {config.get('excel_mode', 'full')}")
print(f"Max parallel API: {config.get('max_parallel_api', 6)}")
print()
print("Sẽ chạy tất cả 7 steps (skip steps đã xong)")
print("=" * 80)
print()

# Create generator
generator = ProgressivePromptsGenerator(config=config)

# Monitor start
start_time = time.time()

try:
    # Run all steps
    result = generator.run_all_steps(
        project_dir=project_dir,
        code=project_code
    )

    elapsed = time.time() - start_time

    print()
    print("=" * 80)
    print(f"HOÀN THÀNH sau {elapsed:.1f}s ({elapsed/60:.1f} phút)")
    print("=" * 80)
    print()

    if result:
        print("[✓] THÀNH CÔNG!")
        print()

        # Check Excel result
        from modules.excel_manager import PromptWorkbook
        excel_file = project_dir / f"{project_code}_prompts.xlsx"
        workbook = PromptWorkbook(str(excel_file))

        # Count data
        scenes = workbook.get_scenes()
        characters = workbook.get_characters()

        print("Kết quả:")
        print("-" * 80)
        print(f"Characters: {len(characters)}")
        print(f"Scenes: {len(scenes)}")
        print()

        if len(scenes) > 0:
            # Count video_note
            create_count = 0
            skip_count = 0
            no_note = 0

            for s in scenes:
                note = getattr(s, 'video_note', None)
                if note is None:
                    no_note += 1
                elif note == "SKIP":
                    skip_count += 1
                else:
                    create_count += 1

            print("Video note distribution:")
            print(f"  video_note='' (CREATE): {create_count}")
            print(f"  video_note='SKIP': {skip_count}")
            if no_note > 0:
                print(f"  Missing video_note: {no_note}")
            print()

            # Sample scenes
            print("Sample scenes (first 10):")
            for i, scene in enumerate(scenes[:10]):
                note = getattr(scene, 'video_note', 'N/A')
                srt = getattr(scene, 'srt_start', '')
                status = "CREATE ✓" if note == "" else "SKIP ✗" if note == "SKIP" else f"?({note})"
                print(f"  Scene {scene.scene_id:3d} | {srt} | {status}")

    else:
        print("[✗] THẤT BẠI!")
        print()
        print("Check logs để xem lỗi ở đâu")

except Exception as e:
    elapsed = time.time() - start_time
    print()
    print("=" * 80)
    print(f"[ERROR] Exception sau {elapsed:.1f}s")
    print("=" * 80)
    print()
    print(f"Error: {e}")
    print()
    import traceback
    traceback.print_exc()

print()
print("=" * 80)
