"""
Verify video_note values in Excel - check for whitespace issues
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
print("VERIFY VIDEO_NOTE VALUES")
print("=" * 80)
print()

if not excel_file.exists():
    print(f"[ERROR] Excel not found: {excel_file}")
    sys.exit(1)

workbook = PromptWorkbook(str(excel_file))
scenes = workbook.get_scenes()

print(f"Total scenes: {len(scenes)}")
print()

# Count video_note values
video_note_counts = {}
for scene in scenes:
    note = scene.video_note
    # Show actual representation
    note_repr = repr(note)
    if note_repr not in video_note_counts:
        video_note_counts[note_repr] = 0
    video_note_counts[note_repr] += 1

print("Video Note Distribution (using repr):")
for note_repr, count in sorted(video_note_counts.items()):
    print(f"  {note_repr}: {count} scenes")
print()

# Check first 20 scenes in detail
print("First 20 scenes - Detailed video_note check:")
print("=" * 80)

for i, scene in enumerate(scenes[:20], 1):
    note = scene.video_note
    segment_id = getattr(scene, 'segment_id', 'MISSING')

    # Show multiple representations
    note_str = f"'{note}'"
    note_repr = repr(note)
    note_len = len(note) if note else 0
    note_bytes = note.encode('utf-8') if note else b''

    print(f"Scene {scene.scene_id} (Segment {segment_id}):")
    print(f"  video_note str: {note_str}")
    print(f"  video_note repr: {note_repr}")
    print(f"  Length: {note_len}")
    print(f"  Bytes: {note_bytes}")
    print(f"  Is empty string: {note == ''}")
    print(f"  Is 'SKIP': {note == 'SKIP'}")
    print()

# Summary by segment
print("=" * 80)
print("Summary by Segment:")
print("=" * 80)

segment_stats = {}
for scene in scenes:
    segment_id = getattr(scene, 'segment_id', 0)
    note_repr = repr(scene.video_note)

    if segment_id not in segment_stats:
        segment_stats[segment_id] = {}
    if note_repr not in segment_stats[segment_id]:
        segment_stats[segment_id][note_repr] = 0
    segment_stats[segment_id][note_repr] += 1

for segment_id in sorted(segment_stats.keys()):
    print(f"\nSegment {segment_id}:")
    for note_repr, count in sorted(segment_stats[segment_id].items()):
        print(f"  {note_repr}: {count} scenes")

print()
print("=" * 80)
print("VERIFICATION COMPLETE")
print("=" * 80)
