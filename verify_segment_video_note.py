"""
Verify segment_id and video_note in scenes sheet
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
print("VERIFY SEGMENT_ID AND VIDEO_NOTE")
print("=" * 80)
print()

workbook = PromptWorkbook(str(excel_file))

# Check if Scene has segment_id attribute
scenes = workbook.get_scenes()
print(f"Total scenes: {len(scenes)}")
print()

if len(scenes) > 0:
    first_scene = scenes[0]
    print(f"First scene attributes: {dir(first_scene)}")
    print()

    # Check first 20 scenes
    print("First 20 scenes - segment_id and video_note:")
    print("-" * 80)

    for i, scene in enumerate(scenes[:20]):
        scene_id = scene.scene_id
        segment_id = getattr(scene, 'segment_id', 'MISSING')
        video_note = getattr(scene, 'video_note', 'MISSING')
        srt_start = getattr(scene, 'srt_start', '')

        # Show repr to see actual characters
        video_note_repr = repr(video_note)

        print(f"Scene {scene_id:3d} | segment_id={segment_id} | video_note={video_note_repr:20s} | {srt_start}")

    print()

    # Count by segment and video_note
    print("Summary by segment_id:")
    print("-" * 80)

    from collections import Counter

    segment_counts = Counter(getattr(s, 'segment_id', None) for s in scenes)
    for seg_id in sorted(segment_counts.keys()):
        count = segment_counts[seg_id]
        print(f"  Segment {seg_id}: {count} scenes")

    print()
    print("Summary by video_note:")
    print("-" * 80)

    video_note_counts = Counter(getattr(s, 'video_note', None) for s in scenes)
    for note in sorted(video_note_counts.keys(), key=lambda x: (x is None, x)):
        count = video_note_counts[note]
        note_repr = repr(note)
        print(f"  video_note={note_repr:20s}: {count} scenes")

    # Check logic: Segment 1 should have video_note='', others 'SKIP'
    print()
    print("Verify BASIC mode logic:")
    print("-" * 80)

    seg1_empty = sum(1 for s in scenes if getattr(s, 'segment_id', None) == 1 and getattr(s, 'video_note', None) == '')
    seg1_other = sum(1 for s in scenes if getattr(s, 'segment_id', None) == 1 and getattr(s, 'video_note', None) != '')

    seg2plus_skip = sum(1 for s in scenes if getattr(s, 'segment_id', None) > 1 and getattr(s, 'video_note', None) == 'SKIP')
    seg2plus_other = sum(1 for s in scenes if getattr(s, 'segment_id', None) > 1 and getattr(s, 'video_note', None) != 'SKIP')

    print(f"  Segment 1 with video_note='': {seg1_empty} ✅")
    print(f"  Segment 1 with other note: {seg1_other} ❌")
    print(f"  Segment 2+ with video_note='SKIP': {seg2plus_skip} ✅")
    print(f"  Segment 2+ with other note: {seg2plus_other} ❌")

print()
print("=" * 80)
