"""
Debug director_plan để tìm lỗi NoneType
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
print("DEBUG DIRECTOR_PLAN")
print("=" * 80)
print()

if not excel_file.exists():
    print("[ERROR] Excel file not found!")
    sys.exit(1)

workbook = PromptWorkbook(str(excel_file))
director_plan = workbook.get_director_plan()

print(f"Total director_plan entries: {len(director_plan)}")
print()

if len(director_plan) > 0:
    # Check first 5 entries
    print("First 5 director_plan entries:")
    print("-" * 80)

    for i, scene in enumerate(director_plan[:5]):
        print(f"\nEntry {i+1}:")
        print(f"  Type: {type(scene)}")
        print(f"  scene_id: {scene.get('scene_id') if scene else 'NONE'}")
        print(f"  segment_id: {scene.get('segment_id') if scene else 'NONE'}")
        print(f"  srt_start: {scene.get('srt_start') if scene else 'NONE'}")
        print(f"  visual_moment: {scene.get('visual_moment', 'MISSING') if scene else 'NONE'}")
        print(f"  characters_used: {scene.get('characters_used', 'MISSING') if scene else 'NONE'}")
        print(f"  location_used: {scene.get('location_used', 'MISSING') if scene else 'NONE'}")

        # Check if any value is None
        if scene is None:
            print("  [ERROR] Scene is None!")
        else:
            for key, value in scene.items():
                if value is None:
                    print(f"  [WARN] Key '{key}' has None value")

    # Check if any entry is None
    none_count = sum(1 for s in director_plan if s is None)
    print()
    print(f"None entries: {none_count} / {len(director_plan)}")

    # Check missing keys
    print()
    print("Checking for missing keys in director_plan entries:")
    required_keys = ['scene_id', 'visual_moment', 'characters_used', 'location_used']

    for key in required_keys:
        missing_count = sum(1 for s in director_plan if s and key not in s)
        print(f"  Missing '{key}': {missing_count} entries")

print()
print("=" * 80)
