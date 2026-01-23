"""
Run complete Excel worker on AR8-0003 (all 7 steps)
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
print("RUN FULL EXCEL WORKER - AR8-0003 (ALL 7 STEPS)")
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

print("Starting all 7 steps...")
print("-" * 80)

try:
    # Run all steps
    result = generator.run_all_steps(
        project_dir=project_dir,
        code=project_code
    )

    elapsed = time.time() - start_time

    print()
    print("-" * 80)
    print(f"All steps completed in {elapsed:.1f}s ({elapsed/60:.1f} minutes)")
    print()

    if result:
        print("[OK] ALL STEPS SUCCESS!")

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

            # Check director_plan
            director_plan = workbook.get_director_plan()
            print(f"Total director_plan entries: {len(director_plan)}")

            if len(director_plan) > 0:
                # Check first entry has segment_id
                first_plan = director_plan[0]
                segment_id = first_plan.get('segment_id', 'MISSING')
                print(f"  First plan segment_id: {segment_id}")

                # Count segments
                seg1_count = sum(1 for p in director_plan if p.get('segment_id') == 1)
                seg2_count = sum(1 for p in director_plan if p.get('segment_id') == 2)
                seg3_count = sum(1 for p in director_plan if p.get('segment_id') > 2)
                print(f"  Segment 1: {seg1_count} entries")
                print(f"  Segment 2: {seg2_count} entries")
                print(f"  Segment 3+: {seg3_count} entries")

            print()

            # Show first 10 scenes
            print("First 10 scenes:")
            for i, scene in enumerate(scenes[:10]):
                video_note = getattr(scene, 'video_note', '')
                srt_start = getattr(scene, 'srt_start', '')
                print(f"  Scene {scene.scene_id:3d} | {srt_start} | video_note='{video_note:4s}'")

    else:
        print("[ERROR] Excel worker FAILED!")

except Exception as e:
    elapsed = time.time() - start_time
    print()
    print(f"[ERROR] Exception after {elapsed:.1f}s: {e}")
    import traceback
    traceback.print_exc()

print()
print("=" * 80)
