"""
Check scenes 117-124 không có reference
"""
import sys
import io
from pathlib import Path

# Fix encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent))

from modules.excel_manager import PromptWorkbook

excel_file = Path(__file__).parent / "PROJECTS" / "AR8-0003" / "AR8-0003_prompts.xlsx"

workbook = PromptWorkbook(str(excel_file))
scenes = workbook.get_scenes()

print("=" * 80)
print("CHECK SCENES 117-124")
print("=" * 80)
print()

# Find scenes 117-124
target_scenes = [s for s in scenes if 117 <= s.scene_id <= 124]

if not target_scenes:
    print(f"[WARN] Không tìm thấy scenes 117-124 trong {len(scenes)} scenes")
    print(f"Scene ID range: {scenes[0].scene_id} - {scenes[-1].scene_id}")
else:
    print(f"Found {len(target_scenes)} scenes:")
    print()

    for scene in target_scenes:
        print(f"Scene {scene.scene_id}:")
        print(f"  characters_used: '{scene.characters_used}'")
        print(f"  location_used: '{scene.location_used}'")
        print(f"  reference_files: '{scene.reference_files}'")
        print(f"  img_prompt: {scene.img_prompt[:80]}...")
        print()

print("=" * 80)
