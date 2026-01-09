#!/usr/bin/env python3
"""
VE3 Tool - Fix Invalid Prompts
==============================
Kiểm tra và sửa các prompts bị lỗi (chỉ có template, không có nội dung).

Usage:
    python run_fix_prompts.py path/to/excel.xlsx       # Kiểm tra
    python run_fix_prompts.py path/to/excel.xlsx --fix # Sửa bằng AI
"""

import sys
import argparse
from pathlib import Path

# Add current directory to path
TOOL_DIR = Path(__file__).parent
sys.path.insert(0, str(TOOL_DIR))

from modules.excel_manager import PromptWorkbook


def check_prompts(excel_path: Path, fix: bool = False):
    """
    Kiểm tra prompts và báo cáo các prompts bị lỗi.
    """
    print(f"\n{'='*60}")
    print(f"  VE3 TOOL - CHECK PROMPTS")
    print(f"{'='*60}")
    print(f"  File: {excel_path.name}")
    print(f"{'='*60}\n")

    if not excel_path.exists():
        print(f"❌ File không tồn tại: {excel_path}")
        return

    try:
        workbook = PromptWorkbook(str(excel_path))
        workbook.load_or_create()
    except Exception as e:
        print(f"❌ Không đọc được Excel: {e}")
        return

    # Detect invalid prompts
    invalid_scenes = workbook.detect_invalid_prompts()
    stats = workbook.get_stats()

    print(f"📊 THỐNG KÊ:")
    print(f"   Total scenes: {stats['total_scenes']}")
    print(f"   Scenes có prompts: {stats['scenes_with_prompts']}")
    print(f"   Images done: {stats['images_done']}")
    print(f"   Images error: {stats['images_error']}")
    print()

    if not invalid_scenes:
        print(f"✅ Tất cả prompts đều hợp lệ!")
        return

    print(f"⚠️ PHÁT HIỆN {len(invalid_scenes)} PROMPTS BỊ LỖI:")
    print()

    for scene in invalid_scenes[:20]:  # Hiển thị tối đa 20
        prompt_preview = (scene.img_prompt or "")[:80]
        print(f"   Scene {scene.scene_id}:")
        print(f"      Prompt: {prompt_preview}...")
        print(f"      SRT: {scene.srt_text[:60]}..." if scene.srt_text else "      SRT: (empty)")
        print()

    if len(invalid_scenes) > 20:
        print(f"   ... và {len(invalid_scenes) - 20} scenes khác\n")

    # Các scene IDs bị lỗi
    invalid_ids = [s.scene_id for s in invalid_scenes]
    print(f"📝 SCENE IDs BỊ LỖI: {invalid_ids}")
    print()

    if fix:
        print(f"\n🔧 ĐANG SỬA {len(invalid_scenes)} PROMPTS TỪ BACKUP...\n")

        # Ưu tiên: Dùng backup từ director_plan (đã có sẵn trong Excel)
        result = workbook.fix_invalid_prompts_from_backup()

        print(f"\n📊 KẾT QUẢ:")
        print(f"   ✅ Fixed từ backup: {result['fixed']}")
        print(f"   ⏭️ Skipped (backup cũng lỗi): {result['skipped']}")
        print(f"   ❌ Không có backup: {result['no_backup']}")

        # Nếu còn scenes không fix được, dùng fallback
        remaining = result['skipped'] + result['no_backup']
        if remaining > 0:
            print(f"\n🔧 CÒN {remaining} SCENES KHÔNG CÓ BACKUP, ĐANG TẠO FALLBACK...")
            fix_prompts_fallback(workbook)
    else:
        print(f"\n💡 ĐỂ SỬA, CHẠY:")
        print(f"   python run_fix_prompts.py \"{excel_path}\" --fix")
        print()
        print(f"   Tool sẽ tự động:")
        print(f"   1. Lấy backup từ director_plan (theo timestamp)")
        print(f"   2. Nếu không có backup, tạo fallback từ SRT text")


def fix_prompts_fallback(workbook: PromptWorkbook):
    """
    Fallback: Sửa prompts bị lỗi bằng cách tạo prompt mới từ SRT text.
    Chỉ dùng khi không có backup trong director_plan.
    """
    invalid_scenes = workbook.detect_invalid_prompts()
    if not invalid_scenes:
        print("   ✅ Không còn prompts lỗi!")
        return
    import yaml
    from modules.prompts_generator import PromptGenerator

    # Load config
    config = {}
    config_file = TOOL_DIR / "config" / "settings.yaml"
    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    # Load API keys from accounts.json
    accounts_file = TOOL_DIR / "config" / "accounts.json"
    if accounts_file.exists():
        import json
        with open(accounts_file, "r", encoding="utf-8") as f:
            accounts = json.load(f)

        # Add API keys
        config['gemini_api_keys'] = [k.get('value') for k in accounts.get('gemini_keys', [])
                                      if k.get('status') != 'exhausted']
        config['groq_api_keys'] = [k.get('value') for k in accounts.get('groq_keys', [])
                                    if k.get('status') != 'exhausted']
        config['deepseek_api_keys'] = [k.get('value') for k in accounts.get('deepseek_keys', [])
                                        if k.get('status') != 'exhausted']

    # Get characters and locations
    characters = workbook.get_characters()
    locations = workbook.get_locations()

    # Create simple prompts from SRT text
    fixed_count = 0
    for scene in invalid_scenes:
        srt_text = scene.srt_text or ""

        if not srt_text:
            print(f"   Scene {scene.scene_id}: Skip (no SRT text)")
            continue

        # Detect characters in text
        chars_in_scene = []
        srt_lower = srt_text.lower()
        for char in characters:
            if char.name and char.name.lower() in srt_lower:
                chars_in_scene.append(char.id)
        if not chars_in_scene:
            chars_in_scene = ["nvc"]  # Default to narrator

        # Detect location
        location = ""
        for loc in locations:
            if loc.name and loc.name.lower() in srt_lower:
                location = loc.id
                break

        # Detect shot type from text
        shot_type = "medium shot"
        if any(kw in srt_lower for kw in ['said', 'asked', 'whisper', 'nói', 'hỏi']):
            shot_type = "close-up shot, emotional expression"
        elif any(kw in srt_lower for kw in ['walk', 'run', 'đi', 'chạy']):
            shot_type = "tracking shot"
        elif any(kw in srt_lower for kw in ['look', 'gaze', 'nhìn']):
            shot_type = "contemplative shot"

        # Detect mood
        mood = "natural expression"
        if any(kw in srt_lower for kw in ['sad', 'cry', 'buồn', 'khóc']):
            mood = "melancholic, emotional"
        elif any(kw in srt_lower for kw in ['happy', 'smile', 'vui', 'cười']):
            mood = "joyful, warm"
        elif any(kw in srt_lower for kw in ['angry', 'giận']):
            mood = "intense, dramatic"

        # Build new prompt
        # Use visual description instead of SRT text to avoid AI drawing text
        visual_desc = f"Person in scene, {mood}"
        new_prompt = (
            f"Cinematic, 4K photorealistic, {shot_type}, {visual_desc}, "
            f"natural lighting, subtle film grain (reference: {chars_in_scene[0]}.png)"
        )

        # Update scene
        workbook.update_scene(
            scene.scene_id,
            img_prompt=new_prompt
        )
        fixed_count += 1
        print(f"   ✓ Scene {scene.scene_id}: Fixed")

    workbook.save()
    print(f"\n✅ Đã sửa {fixed_count}/{len(invalid_scenes)} prompts!")
    print(f"   Các prompts mới dựa trên SRT text và character/location detection.")


def main():
    parser = argparse.ArgumentParser(description="VE3 Tool - Check and Fix Invalid Prompts")
    parser.add_argument("excel_path", help="Path to Excel file")
    parser.add_argument("--fix", action="store_true", help="Fix invalid prompts")
    args = parser.parse_args()

    excel_path = Path(args.excel_path)
    check_prompts(excel_path, fix=args.fix)


if __name__ == "__main__":
    main()
