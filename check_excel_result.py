"""
Check Excel result - verify video_note field
"""
import sys
import io
from pathlib import Path

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add modules to path
sys.path.insert(0, str(Path(__file__).parent))

from modules.excel_manager import PromptWorkbook

excel_file = Path(__file__).parent / "PROJECTS" / "TEST-VIDEO-NOTE" / "TEST-VIDEO-NOTE_prompts.xlsx"

print("=" * 80)
print("CHECK EXCEL RESULT - VIDEO_NOTE FIELD")
print("=" * 80)
print()
print(f"Excel file: {excel_file}")
print()

if not excel_file.exists():
    print("[ERROR] Excel file not found!")
    sys.exit(1)

# Load scenes
workbook = PromptWorkbook(str(excel_file))
scenes = workbook.get_scenes()

print(f"Total scenes: {len(scenes)}")
print()

# Show all scenes with video_note
print("Scenes with video_note:")
print("-" * 80)

for scene in scenes:
    scene_id = scene.scene_id
    srt_start = getattr(scene, 'srt_start', '')
    video_note = getattr(scene, 'video_note', '')
    img_prompt = getattr(scene, 'img_prompt', '')[:60]

    # Determine segment based on time
    if srt_start < "00:00:15":
        segment = 1
    else:
        segment = 2

    note_display = f"'{video_note}'" if video_note else "''"

    print(f"Scene {scene_id:2d} | Seg {segment} | {srt_start} | video_note={note_display:6s}")
    print(f"         | {img_prompt}...")

print()
print("=" * 80)
