"""
Inspect Excel data để tìm issues
"""
import sys
import io
from pathlib import Path

# Fix encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent))

from modules.excel_manager import PromptWorkbook

excel_file = Path(__file__).parent / "PROJECTS" / "AR8-0003" / "AR8-0003_prompts.xlsx"

print("=" * 80)
print("INSPECT EXCEL DATA - AR8-0003")
print("=" * 80)
print()

workbook = PromptWorkbook(str(excel_file))
scenes = workbook.get_scenes()

print(f"Total scenes: {len(scenes)}")
print()

# Check first 10 scenes
print("First 10 scenes - Details:")
print("=" * 80)

for i, scene in enumerate(scenes[:10]):
    print(f"\nScene {scene.scene_id}:")
    print(f"  srt_start: {scene.srt_start}")
    print(f"  srt_end: {scene.srt_end}")
    print(f"  duration: {scene.duration}")
    print(f"  planned_duration: {scene.planned_duration}")
    print(f"  srt_text: {scene.srt_text[:60]}...")

    # Check location_used
    loc = scene.location_used
    print(f"  location_used: '{loc}'")
    if ',' in loc:
        print(f"    ⚠️ WARNING: Multiple locations? '{loc}'")

    # Check characters_used
    chars = scene.characters_used
    print(f"  characters_used: '{chars}'")

    # Check reference_files
    refs = scene.reference_files
    print(f"  reference_files: '{refs}'")

    # Parse reference files to check for issues
    if refs and refs != '[]':
        import json
        try:
            ref_list = json.loads(refs)
            print(f"    Parsed refs: {ref_list}")

            # Check for weird filenames
            for ref_file in ref_list:
                if 'loc_loc' in ref_file:
                    print(f"    ⚠️ WEIRD: {ref_file} (contains 'loc_loc')")
                if 'implied' in ref_file:
                    print(f"    ⚠️ WEIRD: {ref_file} (contains 'implied')")
                if ', ' in ref_file:
                    print(f"    ⚠️ WEIRD: {ref_file} (contains comma)")
        except:
            print(f"    ⚠️ ERROR parsing JSON: {refs}")

# Check director_plan
print("\n" + "=" * 80)
print("Director Plan - First 10:")
print("=" * 80)

director_plan = workbook.get_director_plan()
for i, plan in enumerate(director_plan[:10]):
    scene_id = plan.get('scene_id', '?')
    segment_id = plan.get('segment_id', '?')
    location_used = plan.get('location_used', '')

    print(f"\nPlan {scene_id} (Segment {segment_id}):")
    print(f"  location_used: '{location_used}'")

    if ',' in location_used:
        print(f"    ⚠️ WARNING: Multiple locations in director_plan!")

print()
print("=" * 80)
