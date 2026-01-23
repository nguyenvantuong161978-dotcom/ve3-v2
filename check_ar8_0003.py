"""
Check AR8-0003 Excel result
"""
import sys
import io
from pathlib import Path

# Fix encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add modules
sys.path.insert(0, str(Path(__file__).parent))

from modules.excel_manager import PromptWorkbook

excel_file = Path(__file__).parent / "PROJECTS" / "AR8-0003" / "AR8-0003_prompts.xlsx"

print("=" * 80)
print("CHECK AR8-0003 EXCEL - VIDEO_NOTE FIELD")
print("=" * 80)
print()
print(f"Excel file: {excel_file}")
print()

if not excel_file.exists():
    print("[ERROR] Excel file not found!")
    sys.exit(1)

# Load workbook
workbook = PromptWorkbook(str(excel_file))
scenes = workbook.get_scenes()

print(f"Total scenes: {len(scenes)}")
print()

if len(scenes) == 0:
    print("[WARN] No scenes yet - Excel worker still running...")
    sys.exit(0)

# Show scenes
print("Scenes (showing first 20):")
print("-" * 80)

seg1_create = 0
seg2_skip = 0

for i, scene in enumerate(scenes[:20]):
    scene_id = scene.scene_id
    srt_start = getattr(scene, 'srt_start', '')
    video_note = getattr(scene, 'video_note', '')
    img_prompt = getattr(scene, 'img_prompt', '')[:40]

    # Estimate segment
    if srt_start < "00:01:00":
        segment = 1
    else:
        segment = 2

    if video_note == "SKIP":
        seg2_skip += 1
        status = "SKIP ❌"
    else:
        seg1_create += 1
        status = "CREATE ✅"

    print(f"Scene {scene_id:3d} | Seg {segment} | {srt_start} | video_note='{video_note:4s}' → {status}")

print()
print(f"Summary: {seg1_create} CREATE, {seg2_skip} SKIP (of first 20)")
print("=" * 80)
