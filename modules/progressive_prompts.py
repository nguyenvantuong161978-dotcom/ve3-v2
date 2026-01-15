"""
VE3 Tool - Progressive Prompts Generator
=========================================
Tạo prompts theo từng step, mỗi step lưu vào Excel ngay.
API có thể đọc context từ Excel để học từ những gì đã làm.

Flow (Top-Down Planning):
    Step 1:   Phân tích story → Excel (story_analysis)
    Step 1.5: Phân tích nội dung con → Excel (story_segments)
              - Chia câu chuyện thành các phần
              - Mỗi phần cần bao nhiêu ảnh để truyền tải
    Step 2:   Tạo characters → Excel (characters)
    Step 3:   Tạo locations → Excel (characters với loc_xxx)
    Step 4:   Tạo director_plan → Excel (director_plan)
              - Dựa vào segments để phân bổ scenes
    Step 4.5: Lên kế hoạch chi tiết từng scene → Excel (scene_planning)
              - Ý đồ nghệ thuật cho mỗi scene
              - Góc máy, cảm xúc, ánh sáng
    Step 5:   Tạo scene prompts → Excel (scenes)
              - Đọc planning để viết prompt chính xác

Lợi ích:
    - Fail recovery: Resume từ step bị fail
    - Debug: Xem Excel biết step nào sai
    - Kiểm soát: Có thể sửa Excel giữa chừng
    - Chất lượng: API đọc context từ Excel
    - Top-down: Lên kế hoạch trước, prompt sau
"""

import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Callable
from dataclasses import dataclass
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed

from modules.utils import (
    get_logger,
    parse_srt_file,
)
from modules.excel_manager import (
    PromptWorkbook,
    Character,
    Location,
    Scene
)


class StepStatus(Enum):
    """Trạng thái của mỗi step."""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class StepResult:
    """Kết quả của mỗi step."""
    step_name: str
    status: StepStatus
    message: str = ""
    data: Any = None


class ProgressivePromptsGenerator:
    """
    Generator tạo prompts theo từng step.
    Mỗi step đọc context từ Excel và lưu kết quả vào Excel.
    """

    DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

    def __init__(self, config: dict):
        """
        Args:
            config: Config chứa API keys và settings
        """
        self.config = config
        self.logger = get_logger("progressive_prompts")

        # API keys
        self.deepseek_keys = [k for k in config.get("deepseek_api_keys", []) if k and k.strip()]
        self.deepseek_index = 0

        # Callback for logging
        self.log_callback: Optional[Callable] = None

        # Test API key
        if self.deepseek_keys:
            self._test_api_keys()

    def _test_api_keys(self):
        """Test API keys và loại bỏ keys không hoạt động."""
        import requests

        working_keys = []
        for i, key in enumerate(self.deepseek_keys):
            try:
                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                data = {
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": "Say OK"}],
                    "max_tokens": 5
                }
                resp = requests.post(self.DEEPSEEK_URL, headers=headers, json=data, timeout=15)
                if resp.status_code == 200:
                    working_keys.append(key)
                    self._log(f"  DeepSeek key #{i+1}: OK")
                else:
                    self._log(f"  DeepSeek key #{i+1}: SKIP (status {resp.status_code})")
            except Exception as e:
                self._log(f"  DeepSeek key #{i+1}: SKIP ({e})")

        self.deepseek_keys = working_keys
        if not working_keys:
            self._log("  WARNING: No working API keys!")

    def _log(self, msg: str, level: str = "INFO"):
        """Log message."""
        if self.log_callback:
            self.log_callback(msg, level)
        else:
            print(msg)

    def _call_api(self, prompt: str, temperature: float = 0.7, max_tokens: int = 8192) -> Optional[str]:
        """
        Gọi DeepSeek API.

        Returns:
            Response text hoặc None nếu fail
        """
        import requests

        if not self.deepseek_keys:
            self._log("  ERROR: No API keys available!", "ERROR")
            return None

        key = self.deepseek_keys[self.deepseek_index % len(self.deepseek_keys)]
        self.deepseek_index += 1

        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }

        data = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        try:
            resp = requests.post(self.DEEPSEEK_URL, headers=headers, json=data, timeout=120)
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            else:
                self._log(f"  API error: {resp.status_code} - {resp.text[:200]}", "ERROR")
                return None
        except Exception as e:
            self._log(f"  API exception: {e}", "ERROR")
            return None

    def _extract_json(self, text: str) -> Optional[dict]:
        """Extract JSON từ response text."""
        import re

        # Loại bỏ <think>...</think> tags (DeepSeek)
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)

        # Thử parse trực tiếp
        try:
            return json.loads(text.strip())
        except:
            pass

        # Tìm JSON trong code block
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if match:
            try:
                return json.loads(match.group(1))
            except:
                pass

        # Tìm JSON object
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group(0))
            except:
                pass

        return None

    def _split_long_scene_cinematically(
        self,
        scene: dict,
        char_locks: list,
        loc_locks: list
    ) -> list:
        """
        Chia một scene dài (> 8s) thành multiple shots một cách nghệ thuật.
        Gọi API để quyết định cách chia dựa trên nội dung, không phải công thức.

        Returns:
            List of split scenes, or None if failed
        """
        duration = scene.get("duration", 0)
        srt_text = scene.get("srt_text", "")
        visual_moment = scene.get("visual_moment", "")
        characters_used = scene.get("characters_used", "")
        location_used = scene.get("location_used", "")
        srt_start = scene.get("srt_start", "")
        srt_end = scene.get("srt_end", "")

        # Tính số shots cần thiết (target 5-7s mỗi shot)
        min_shots = max(2, int(duration / 7))
        max_shots = max(2, int(duration / 4))

        prompt = f"""You are a FILM DIRECTOR. This scene is {duration:.1f} seconds - TOO LONG for one shot (max 8s).
Split it into {min_shots}-{max_shots} DISTINCT cinematic shots.

ORIGINAL SCENE:
- Duration: {duration:.1f}s (from {srt_start} to {srt_end})
- Narration: "{srt_text}"
- Visual concept: "{visual_moment}"
- Characters: {characters_used}
- Location: {location_used}

AVAILABLE CHARACTERS:
{chr(10).join(char_locks) if char_locks else 'None'}

AVAILABLE LOCATIONS:
{chr(10).join(loc_locks) if loc_locks else 'None'}

RULES FOR SPLITTING:
1. Each shot MUST be 3-8 seconds (divide the {duration:.1f}s total)
2. Each shot must show DIFFERENT aspect: angle, focus, emotion
3. All shots together must cover the FULL narration
4. Use EXACT character/location IDs from the lists above
5. Think cinematically - what sequence of shots tells this story best?

Examples of good splits:
- Character making decision: Close-up face → Insert object → Wide shot reaction
- Two people talking: Speaker close-up → Listener reaction → Two-shot
- Action sequence: Wide establishing → Medium action → Close-up detail

Return JSON only:
{{
    "shots": [
        {{
            "shot_number": 1,
            "duration": 5.0,
            "srt_text": "portion of narration for this shot",
            "visual_moment": "what viewer sees - specific and purposeful",
            "shot_purpose": "why this shot at this moment",
            "characters_used": "{characters_used}",
            "location_used": "{location_used}",
            "camera": "shot type and movement"
        }}
    ]
}}"""

        response = self._call_api(prompt, temperature=0.5, max_tokens=2000)
        if not response:
            return None

        data = self._extract_json(response)
        if not data or "shots" not in data:
            return None

        shots = data["shots"]
        if not shots or len(shots) < 2:
            return None

        # Validate total duration roughly matches original
        total_split_duration = sum(s.get("duration", 0) for s in shots)
        if abs(total_split_duration - duration) > duration * 0.3:  # Allow 30% variance
            # Adjust durations proportionally
            ratio = duration / total_split_duration if total_split_duration > 0 else 1
            for shot in shots:
                shot["duration"] = round(shot.get("duration", 5) * ratio, 2)

        # Convert shots to scene format
        split_scenes = []
        for shot in shots:
            split_scene = {
                "scene_id": 0,  # Will be assigned later
                "srt_indices": scene.get("srt_indices", []),
                "srt_start": srt_start,  # Keep original timing reference
                "srt_end": srt_end,
                "duration": shot.get("duration", 5.0),
                "srt_text": shot.get("srt_text", srt_text),
                "visual_moment": shot.get("visual_moment", ""),
                "shot_purpose": shot.get("shot_purpose", ""),
                "characters_used": shot.get("characters_used", characters_used),
                "location_used": shot.get("location_used", location_used),
                "camera": shot.get("camera", ""),
                "lighting": scene.get("lighting", "")
            }
            split_scenes.append(split_scene)

        return split_scenes

    # =========================================================================
    # STEP 1: PHÂN TÍCH STORY
    # =========================================================================

    def step_analyze_story(
        self,
        project_dir: Path,
        code: str,
        workbook: PromptWorkbook,
        srt_entries: list,
        txt_content: str = ""
    ) -> StepResult:
        """
        Step 1: Phân tích story và lưu vào Excel.

        Output sheet: story_analysis
        - setting: Bối cảnh (thời đại, địa điểm)
        - themes: Chủ đề chính
        - visual_style: Phong cách visual
        - context_lock: Prompt context chung
        """
        self._log("\n" + "="*60)
        self._log("[STEP 1] Phân tích story...")
        self._log("="*60)

        # Check if already done
        try:
            existing = workbook.get_story_analysis()
            if existing and existing.get("setting"):
                self._log("  -> Đã có story_analysis, skip!")
                return StepResult("analyze_story", StepStatus.COMPLETED, "Already done")
        except:
            pass

        # Prepare story text
        if txt_content:
            story_text = txt_content
        else:
            story_text = " ".join([e.text for e in srt_entries])

        # Build prompt
        prompt = f"""Analyze this story and extract key information for visual production.

STORY:
{story_text[:15000]}

Return JSON only:
{{
    "setting": {{
        "era": "time period (e.g., 1950s, medieval, modern day)",
        "location": "primary location type",
        "atmosphere": "overall mood/atmosphere"
    }},
    "themes": ["theme1", "theme2", "theme3"],
    "visual_style": {{
        "cinematography": "visual style description",
        "color_palette": "dominant colors",
        "lighting": "lighting style"
    }},
    "context_lock": "A single sentence describing the visual world (used as prefix for all image prompts)"
}}
"""

        # Call API
        response = self._call_api(prompt, temperature=0.5)
        if not response:
            self._log("  ERROR: API call failed!", "ERROR")
            return StepResult("analyze_story", StepStatus.FAILED, "API call failed")

        # Parse response
        data = self._extract_json(response)
        if not data:
            self._log("  ERROR: Could not parse JSON!", "ERROR")
            return StepResult("analyze_story", StepStatus.FAILED, "JSON parse failed")

        # Save to Excel
        try:
            workbook.save_story_analysis(data)
            workbook.save()
            self._log(f"  -> Saved story_analysis to Excel")
            self._log(f"     Setting: {data.get('setting', {}).get('era', 'N/A')}, {data.get('setting', {}).get('location', 'N/A')}")
            self._log(f"     Context: {data.get('context_lock', 'N/A')[:80]}...")
            return StepResult("analyze_story", StepStatus.COMPLETED, "Success", data)
        except Exception as e:
            self._log(f"  ERROR: Could not save to Excel: {e}", "ERROR")
            return StepResult("analyze_story", StepStatus.FAILED, str(e))

    # =========================================================================
    # STEP 1.5: PHÂN TÍCH NỘI DUNG CON (STORY SEGMENTS)
    # =========================================================================

    def step_analyze_story_segments(
        self,
        project_dir: Path,
        code: str,
        workbook: PromptWorkbook,
        srt_entries: list,
        txt_content: str = ""
    ) -> StepResult:
        """
        Step 1.5: Phân tích câu chuyện thành các nội dung con (segments).

        Logic top-down:
        1. Xác định các phần nội dung chính trong câu chuyện
        2. Mỗi phần cần truyền tải thông điệp gì
        3. Mỗi phần cần bao nhiêu ảnh để thể hiện đầy đủ
        4. Ước tính thời gian từ SRT

        Output sheet: story_segments
        """
        self._log("\n" + "="*60)
        self._log("[STEP 1.5] Phân tích nội dung con (story segments)...")
        self._log("="*60)

        # Check if already done
        try:
            existing = workbook.get_story_segments()
            if existing and len(existing) > 0:
                self._log(f"  -> Đã có {len(existing)} segments, skip!")
                return StepResult("analyze_story_segments", StepStatus.COMPLETED, "Already done")
        except:
            pass

        # Read context from previous step
        story_analysis = {}
        try:
            story_analysis = workbook.get_story_analysis() or {}
        except:
            pass

        context_lock = story_analysis.get("context_lock", "")
        themes = story_analysis.get("themes", [])

        # Prepare story text
        if txt_content:
            story_text = txt_content
        else:
            story_text = " ".join([e.text for e in srt_entries])

        # Tính tổng thời gian từ SRT
        total_duration = 0
        if srt_entries:
            try:
                # Parse end time của entry cuối
                last_entry = srt_entries[-1]
                end_time = last_entry.end_time  # Format: "00:01:30,500"
                parts = end_time.replace(',', ':').split(':')
                total_duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]) + int(parts[3]) / 1000
            except:
                total_duration = len(srt_entries) * 3  # Ước tính 3s/entry

        self._log(f"  Tổng thời gian SRT: {total_duration:.1f}s ({len(srt_entries)} entries)")

        # Build prompt
        prompt = f"""Analyze this story and divide it into content segments for video creation.

STORY CONTEXT:
{context_lock}

THEMES: {', '.join(themes) if themes else 'Not specified'}

TOTAL DURATION: {total_duration:.1f} seconds
TOTAL SRT ENTRIES: {len(srt_entries)}

STORY CONTENT:
{story_text[:20000]}

TASK: Divide the story into logical segments. Each segment is a distinct part of the narrative.

For each segment, determine:
1. What is the main message/purpose of this segment?
2. How many images are needed to fully convey this segment visually?
   - Consider: 1 image = 3-8 seconds of video
   - More complex/important segments need more images
   - Simple transitions may need only 1 image

GUIDELINES:
- Total images across all segments should roughly equal: {int(total_duration / 5)} (assuming ~5s per image)
- Each segment should have at least 1 image, typically 2-5 images
- Important emotional moments may need more images
- Action sequences need more images than dialogue

Return JSON only:
{{
    "segments": [
        {{
            "segment_id": 1,
            "segment_name": "Opening/Introduction",
            "message": "What this segment conveys to the viewer",
            "key_elements": ["element1", "element2"],
            "image_count": 3,
            "estimated_duration": 15.0,
            "srt_range_start": 1,
            "srt_range_end": 5,
            "importance": "high/medium/low"
        }}
    ],
    "total_images": 20,
    "summary": "Brief overview of the story structure"
}}
"""

        # Call API
        response = self._call_api(prompt, temperature=0.3, max_tokens=4096)
        if not response:
            self._log("  ERROR: API call failed!", "ERROR")
            return StepResult("analyze_story_segments", StepStatus.FAILED, "API call failed")

        # Parse response
        data = self._extract_json(response)
        if not data or "segments" not in data:
            self._log("  ERROR: Could not parse segments!", "ERROR")
            return StepResult("analyze_story_segments", StepStatus.FAILED, "JSON parse failed")

        # Save to Excel
        try:
            workbook.save_story_segments(data["segments"], data.get("total_images", 0), data.get("summary", ""))
            workbook.save()

            total_images = sum(s.get("image_count", 0) for s in data["segments"])
            self._log(f"  -> Saved {len(data['segments'])} segments ({total_images} total images)")
            for seg in data["segments"][:5]:
                self._log(f"     - {seg.get('segment_name')}: {seg.get('image_count')} images")

            return StepResult("analyze_story_segments", StepStatus.COMPLETED, "Success", data)
        except Exception as e:
            self._log(f"  ERROR: Could not save to Excel: {e}", "ERROR")
            return StepResult("analyze_story_segments", StepStatus.FAILED, str(e))

    # =========================================================================
    # STEP 2: TẠO CHARACTERS
    # =========================================================================

    def step_create_characters(
        self,
        project_dir: Path,
        code: str,
        workbook: PromptWorkbook,
        srt_entries: list,
        txt_content: str = ""
    ) -> StepResult:
        """
        Step 2: Tạo characters dựa trên story_analysis.

        Input: Đọc story_analysis từ Excel
        Output sheet: characters
        """
        self._log("\n" + "="*60)
        self._log("[STEP 2] Tạo characters...")
        self._log("="*60)

        # Check if already done
        existing_chars = workbook.get_characters()
        if existing_chars and len(existing_chars) > 0:
            self._log(f"  -> Đã có {len(existing_chars)} characters, skip!")
            return StepResult("create_characters", StepStatus.COMPLETED, "Already done")

        # Read story_analysis from Excel
        story_analysis = {}
        try:
            story_analysis = workbook.get_story_analysis() or {}
        except:
            pass

        context_lock = story_analysis.get("context_lock", "")
        setting = story_analysis.get("setting", {})

        # Prepare story text
        if txt_content:
            story_text = txt_content
        else:
            story_text = " ".join([e.text for e in srt_entries])

        # Build prompt with context from previous step
        prompt = f"""Based on this story, identify all characters and create visual descriptions.

STORY CONTEXT (from previous analysis):
- Era: {setting.get('era', 'Not specified')}
- Location: {setting.get('location', 'Not specified')}
- Visual style: {context_lock}

STORY:
{story_text[:15000]}

For each character, provide:
1. portrait_prompt: Full description for generating a reference portrait (white background, portrait style)
2. character_lock: Short 10-15 word description to use in scene prompts (for consistency)
3. is_minor: TRUE if character is under 18 years old (child, teenager, baby, infant, etc.)

IMPORTANT: Identify minors accurately based on context clues:
- Age mentions (e.g., "5-year-old", "teenager", "16 years old")
- Role descriptions (e.g., "son", "daughter", "child", "kid", "baby", "infant", "toddler")
- School context (e.g., "student", "high school", "elementary")
- Any character described as young, minor, underage, or child-like

Return JSON only:
{{
    "characters": [
        {{
            "id": "char_id",
            "name": "Character Name",
            "role": "protagonist/antagonist/supporting/narrator",
            "portrait_prompt": "detailed portrait description for image generation, white background",
            "character_lock": "short description for scene prompts (10-15 words)",
            "vietnamese_description": "Optional alternate description",
            "is_minor": false
        }}
    ]
}}
"""

        # Call API
        response = self._call_api(prompt, temperature=0.5)
        if not response:
            self._log("  ERROR: API call failed!", "ERROR")
            return StepResult("create_characters", StepStatus.FAILED, "API call failed")

        # Parse response
        data = self._extract_json(response)
        if not data or "characters" not in data:
            self._log("  ERROR: Could not parse characters!", "ERROR")
            return StepResult("create_characters", StepStatus.FAILED, "JSON parse failed")

        # Save to Excel
        try:
            minor_count = 0
            for char_data in data["characters"]:
                char_id = char_data.get("id", "")
                # Đảm bảo id bắt đầu bằng "nv_"
                if not char_id.startswith("nv_"):
                    char_id = f"nv_{char_id}"

                # Detect trẻ vị thành niên (dưới 18 tuổi)
                is_minor = char_data.get("is_minor", False)
                if isinstance(is_minor, str):
                    is_minor = is_minor.lower() in ("true", "yes", "1")

                char = Character(
                    id=char_id,
                    name=char_data.get("name", ""),
                    role=char_data.get("role", "supporting"),
                    english_prompt=char_data.get("portrait_prompt", ""),
                    character_lock=char_data.get("character_lock", ""),
                    vietnamese_prompt=char_data.get("vietnamese_description", ""),
                    image_file=f"{char_id}.png",
                    is_child=is_minor,
                    status="skip" if is_minor else "pending",  # Skip tạo ảnh cho trẻ em
                )
                workbook.add_character(char)

                if is_minor:
                    minor_count += 1

            workbook.save()
            self._log(f"  -> Saved {len(data['characters'])} characters to Excel")
            if minor_count > 0:
                self._log(f"  -> ⚠️ {minor_count} characters là trẻ em (sẽ KHÔNG tạo ảnh)")
            for c in data["characters"][:3]:
                minor_tag = " [MINOR]" if c.get("is_minor") else ""
                self._log(f"     - {c.get('name', 'N/A')} ({c.get('role', 'N/A')}){minor_tag}")
            if len(data["characters"]) > 3:
                self._log(f"     ... và {len(data['characters']) - 3} characters khác")

            return StepResult("create_characters", StepStatus.COMPLETED, "Success", data)
        except Exception as e:
            self._log(f"  ERROR: Could not save to Excel: {e}", "ERROR")
            return StepResult("create_characters", StepStatus.FAILED, str(e))

    # =========================================================================
    # STEP 3: TẠO LOCATIONS
    # =========================================================================

    def step_create_locations(
        self,
        project_dir: Path,
        code: str,
        workbook: PromptWorkbook,
        srt_entries: list,
        txt_content: str = ""
    ) -> StepResult:
        """
        Step 3: Tạo locations dựa trên story_analysis + characters.

        Input: Đọc story_analysis, characters từ Excel
        Output sheet: locations
        """
        self._log("\n" + "="*60)
        self._log("[STEP 3] Tạo locations...")
        self._log("="*60)

        # Check if already done
        existing_locs = workbook.get_locations()
        if existing_locs and len(existing_locs) > 0:
            self._log(f"  -> Đã có {len(existing_locs)} locations, skip!")
            return StepResult("create_locations", StepStatus.COMPLETED, "Already done")

        # Read context from Excel
        story_analysis = {}
        try:
            story_analysis = workbook.get_story_analysis() or {}
        except:
            pass

        characters = workbook.get_characters()
        char_names = [c.name for c in characters] if characters else []

        context_lock = story_analysis.get("context_lock", "")
        setting = story_analysis.get("setting", {})

        # Prepare story text
        if txt_content:
            story_text = txt_content
        else:
            story_text = " ".join([e.text for e in srt_entries])

        # Build prompt
        prompt = f"""Based on this story, identify all locations and create visual descriptions.

STORY CONTEXT:
- Era: {setting.get('era', 'Not specified')}
- Location type: {setting.get('location', 'Not specified')}
- Visual style: {context_lock}
- Characters: {', '.join(char_names[:5])}

STORY:
{story_text[:15000]}

For each location, provide:
1. location_prompt: Full description for generating a reference image
2. location_lock: Short description to use in scene prompts

Return JSON only:
{{
    "locations": [
        {{
            "id": "loc_id",
            "name": "Location Name",
            "location_prompt": "detailed location description for image generation",
            "location_lock": "short description for scene prompts (10-15 words)",
            "lighting_default": "default lighting for this location"
        }}
    ]
}}
"""

        # Call API
        response = self._call_api(prompt, temperature=0.5)
        if not response:
            self._log("  ERROR: API call failed!", "ERROR")
            return StepResult("create_locations", StepStatus.FAILED, "API call failed")

        # Parse response
        data = self._extract_json(response)
        if not data or "locations" not in data:
            self._log("  ERROR: Could not parse locations!", "ERROR")
            return StepResult("create_locations", StepStatus.FAILED, "JSON parse failed")

        # Save to Excel - LƯU VÀO SHEET CHARACTERS với id loc_xxx
        try:
            for loc_data in data["locations"]:
                loc_id = loc_data.get("id", "")
                # Đảm bảo id bắt đầu bằng "loc_"
                if not loc_id.startswith("loc_"):
                    loc_id = f"loc_{loc_id}"

                # Tạo Character với role="location" thay vì Location riêng
                loc_char = Character(
                    id=loc_id,
                    name=loc_data.get("name", ""),
                    role="location",  # Đánh dấu là location
                    english_prompt=loc_data.get("location_prompt", ""),
                    character_lock=loc_data.get("location_lock", ""),
                    vietnamese_prompt=loc_data.get("lighting_default", ""),  # Dùng field này cho lighting
                    image_file=f"{loc_id}.png",
                    status="pending",
                )
                workbook.add_character(loc_char)  # Thêm vào characters sheet

            workbook.save()
            self._log(f"  -> Saved {len(data['locations'])} locations to characters sheet")
            for loc in data["locations"][:3]:
                self._log(f"     - {loc.get('name', 'N/A')}")

            return StepResult("create_locations", StepStatus.COMPLETED, "Success", data)
        except Exception as e:
            self._log(f"  ERROR: Could not save to Excel: {e}", "ERROR")
            return StepResult("create_locations", StepStatus.FAILED, str(e))

    # =========================================================================
    # STEP 4: TẠO DIRECTOR'S PLAN
    # =========================================================================

    def step_create_director_plan(
        self,
        project_dir: Path,
        code: str,
        workbook: PromptWorkbook,
        srt_entries: list
    ) -> StepResult:
        """
        Step 4: Tạo director's plan - chia SRT thành scenes.

        Input: Đọc story_analysis, characters, locations từ Excel
        Output sheet: director_plan

        Xử lý SRT dài bằng cách chia batch để không bị cắt.
        """
        self._log("\n" + "="*60)
        self._log("[STEP 4] Tạo director's plan...")
        self._log("="*60)

        # Check if already done
        try:
            existing_plan = workbook.get_director_plan()
            if existing_plan and len(existing_plan) > 0:
                self._log(f"  -> Đã có {len(existing_plan)} scenes trong plan, skip!")
                return StepResult("create_director_plan", StepStatus.COMPLETED, "Already done")
        except:
            pass

        # Read context from Excel
        story_analysis = {}
        try:
            story_analysis = workbook.get_story_analysis() or {}
        except:
            pass

        characters = workbook.get_characters()
        locations = workbook.get_locations()

        # Đọc story segments để hướng dẫn số lượng scenes
        story_segments = []
        total_planned_images = 0
        try:
            story_segments = workbook.get_story_segments() or []
            total_planned_images = sum(s.get("image_count", 0) for s in story_segments)
            self._log(f"  Story segments: {len(story_segments)} segments, {total_planned_images} planned images")
        except:
            pass

        context_lock = story_analysis.get("context_lock", "")

        # Build segments info for prompt
        segments_info = ""
        if story_segments:
            segments_info = "\nSTORY SEGMENTS (use this to guide scene distribution):\n"
            for seg in story_segments:
                segments_info += f"- Segment {seg.get('segment_id')}: {seg.get('segment_name')} - {seg.get('image_count')} images (SRT {seg.get('srt_range_start')}-{seg.get('srt_range_end')})\n"
                segments_info += f"  Message: {seg.get('message', '')[:100]}...\n"

        # Build character locks for prompt
        char_locks = []
        for c in characters:
            if c.character_lock:
                char_locks.append(f"- {c.id}: {c.character_lock}")

        # Build location locks for prompt
        loc_locks = []
        for loc in locations:
            if hasattr(loc, 'location_lock') and loc.location_lock:
                loc_locks.append(f"- {loc.id}: {loc.location_lock}")

        # Chia SRT entries thành batches dựa vào độ dài ký tự
        MAX_BATCH_CHARS = 6000  # Giảm xuống ~6000 ký tự để API tạo đủ scenes
        all_scenes = []
        scene_id_counter = 1

        total_entries = len(srt_entries)
        self._log(f"  Total SRT entries: {total_entries}")

        # Tạo batches dựa vào độ dài ký tự
        batches = []
        current_batch = []
        current_chars = 0

        for i, entry in enumerate(srt_entries):
            # Tính độ dài của entry này
            entry_text = f"[{i+1}] {entry.start_time} --> {entry.end_time}\n{entry.text}\n\n"
            entry_len = len(entry_text)

            # Nếu thêm entry này vượt quá limit và batch hiện tại không rỗng
            if current_chars + entry_len > MAX_BATCH_CHARS and current_batch:
                batches.append(current_batch)
                current_batch = []
                current_chars = 0

            current_batch.append((i, entry))
            current_chars += entry_len

        # Thêm batch cuối cùng
        if current_batch:
            batches.append(current_batch)

        self._log(f"  Split into {len(batches)} batches based on content length")

        for batch_idx, batch_entries in enumerate(batches):
            batch_start = batch_entries[0][0]  # Index đầu tiên
            batch_end = batch_entries[-1][0]   # Index cuối cùng

            self._log(f"  Processing batch {batch_idx+1}/{len(batches)}: entries {batch_start+1}-{batch_end+1}/{total_entries}")

            # Format SRT entries cho batch này
            # batch_entries là list của tuples (original_index, entry)
            srt_text = ""
            for original_idx, entry in batch_entries:
                # original_idx là 0-based, cần +1 cho 1-based
                srt_text += f"[{original_idx+1}] {entry.start_time} --> {entry.end_time}\n{entry.text}\n\n"

            # Build prompt
            # Tính số ảnh dự kiến cho batch này dựa trên segments và thời gian
            batch_duration = 0
            for _, entry in batch_entries:
                try:
                    # Parse duration từ timestamps
                    start = entry.start_time.replace(',', ':').split(':')
                    end = entry.end_time.replace(',', ':').split(':')
                    start_sec = int(start[0])*3600 + int(start[1])*60 + int(start[2]) + int(start[3])/1000
                    end_sec = int(end[0])*3600 + int(end[1])*60 + int(end[2]) + int(end[3])/1000
                    batch_duration = max(batch_duration, end_sec)
                except:
                    pass

            # Không tính số scenes - để API quyết định theo nội dung
            expected_images_hint = f"""
SCENE GUIDELINES:
- This batch spans approximately {batch_duration:.0f} seconds
- Duration should FIT THE CONTENT - not rigid numbers
- Target around 8 seconds per scene, but let content guide you
- Avoid extremes: not too long (>12s) or too short (<3s)"""

            prompt = f"""You are a FILM DIRECTOR creating a shot list. Each scene = ONE CINEMATIC SHOT.

DURATION GUIDANCE (flexible, based on content):
- Target: around 8 seconds per scene
- Let the CONTENT determine the duration - some moments need more time, some less
- Avoid extremes: scenes >12s feel too long, scenes <3s feel too rushed
- A complete thought/moment = one scene

CORE PRINCIPLE: Each shot must SUPPORT and ENHANCE the narration. The viewer sees this image while hearing the audio.
Ask yourself: "What visual would make this moment IMPACTFUL for the audience?"

STORY CONTEXT:
{context_lock}
{segments_info}
CHARACTERS (use EXACT IDs in scenes):
{chr(10).join(char_locks) if char_locks else 'No characters defined'}

LOCATIONS (use EXACT IDs in scenes):
{chr(10).join(loc_locks) if loc_locks else 'No locations defined'}

SRT ENTRIES (indices {batch_start+1} to {batch_end+1}):
{srt_text}
{expected_images_hint}

DIRECTOR'S MINDSET:
1. Each scene = 1 SHOT (max 8 seconds) that SUPPORTS the content being narrated
2. Choose the shot that BEST conveys the emotion/message of that moment
3. Think cinematically:
   - Narration about someone's feelings → Close-up on their face/expression
   - Narration about a place/situation → Establishing wide shot
   - Narration about interaction → Two-shot or over-shoulder
   - Narration building tension → Dramatic angle, shadows
   - Narration revealing information → Focus on the key element

SHOT TYPES TO CONSIDER:
- Close-up: emotion, detail, intimacy (face, hands, object)
- Medium shot: action, body language, conversation
- Wide/Establishing: location, context, scale, isolation
- Over-shoulder: dialogue, perspective, connection
- Insert/Detail: important object, symbol, emphasis

THINK LIKE A MOVIE DIRECTOR:
1. Each scene = one shot in a film, serving the story
2. Duration fits the content naturally (target ~8s, flexible based on moment)
3. characters_used: EXACT IDs like "nv_john, nv_sarah" from list above
4. location_used: EXACT ID like "loc_office" from list above
5. visual_moment: What viewer sees - be specific and purposeful
6. camera: Shot type that serves the emotion (close-up for intimacy, wide for scale)
7. scene_id starts from {scene_id_counter}

CINEMATIC APPROACH:
- Pacing varies like a real film: slow moments, quick cuts, breathing room
- Match shot duration to content: emotional beats need time, action can be quicker
- When narration spans long time, use multiple angles (like film editing)
- Create visual rhythm: vary shot types, don't repeat same angle

Return JSON only:
{{
    "scenes": [
        {{
            "scene_id": {scene_id_counter},
            "srt_indices": [{batch_start+1}, ...],
            "srt_start": "00:00:00,000",
            "srt_end": "00:00:05,000",
            "duration": 5.0,
            "srt_text": "the narration text",
            "visual_moment": "Close-up on John's worried face, sweat on forehead - showing his anxiety about the decision",
            "shot_purpose": "Convey internal struggle as narration describes his dilemma",
            "characters_used": "nv_john",
            "location_used": "loc_office",
            "camera": "Close-up, static, shallow depth of field",
            "lighting": "Harsh overhead light creating shadows under eyes"
        }}
    ]
}}
"""

            # Call API with retry logic
            MAX_RETRIES = 3
            data = None

            for retry in range(MAX_RETRIES):
                response = self._call_api(prompt, temperature=0.5, max_tokens=8192)
                if not response:
                    self._log(f"     Retry {retry+1}/{MAX_RETRIES}: API call failed", "WARNING")
                    time.sleep(2 ** retry)  # Exponential backoff
                    continue

                # Parse response
                data = self._extract_json(response)
                if data and "scenes" in data:
                    break  # Success!
                else:
                    self._log(f"     Retry {retry+1}/{MAX_RETRIES}: JSON parse failed", "WARNING")
                    time.sleep(2 ** retry)

            if not data or "scenes" not in data:
                # FALLBACK: Tạo basic scenes từ SRT entries khi API fail
                self._log(f"  WARNING: Batch {batch_idx+1} failed, creating fallback scenes...", "WARNING")

                batch_scenes = []
                # Nhóm ~5 entries thành 1 scene
                entries_per_scene = 5
                for i in range(0, len(batch_entries), entries_per_scene):
                    group = batch_entries[i:i + entries_per_scene]
                    if not group:
                        continue

                    first_idx, first_entry = group[0]
                    last_idx, last_entry = group[-1]

                    # Tính duration
                    try:
                        def parse_ts(ts):
                            parts = ts.replace(',', ':').split(':')
                            return int(parts[0])*3600 + int(parts[1])*60 + int(parts[2]) + int(parts[3])/1000
                        duration = parse_ts(last_entry.end_time) - parse_ts(first_entry.start_time)
                    except:
                        duration = len(group) * 3  # ~3s per entry

                    fallback_scene = {
                        "scene_id": scene_id_counter + len(batch_scenes),
                        "srt_indices": [idx + 1 for idx, _ in group],
                        "srt_start": first_entry.start_time,
                        "srt_end": last_entry.end_time,
                        "duration": round(duration, 2),
                        "srt_text": " ".join([e.text for _, e in group]),
                        "visual_moment": f"[Auto-generated] Scene covering SRT {first_idx+1}-{last_idx+1}",
                        "characters_used": "",
                        "location_used": "",
                        "camera": "Medium shot",
                        "lighting": "Natural lighting"
                    }
                    batch_scenes.append(fallback_scene)

                self._log(f"     -> Created {len(batch_scenes)} fallback scenes")

            else:
                # Thêm scenes từ API
                batch_scenes = data["scenes"]
                self._log(f"     -> Got {len(batch_scenes)} scenes from API")

            # POST-PROCESS: Chia scenes quá dài một cách nghệ thuật
            # Target ~8s, nhưng linh hoạt - chỉ split khi thực sự cần
            SPLIT_THRESHOLD = 10  # Chỉ split khi > 10s (cho phép linh hoạt)
            processed_scenes = []
            for scene in batch_scenes:
                duration = scene.get("duration", 0)
                if duration and duration > SPLIT_THRESHOLD:
                    # Gọi API để chia scene này thành multiple shots
                    split_scenes = self._split_long_scene_cinematically(scene, char_locks, loc_locks)
                    if split_scenes:
                        self._log(f"     🎬 Scene {scene.get('scene_id')}: {duration:.1f}s → split into {len(split_scenes)} cinematic shots")
                        processed_scenes.extend(split_scenes)
                    else:
                        # Fallback: giữ nguyên nếu split fail
                        self._log(f"     ⚠️ Scene {scene.get('scene_id')}: {duration:.1f}s (kept as-is)")
                        processed_scenes.append(scene)
                else:
                    processed_scenes.append(scene)

            # Cập nhật scene_id để liên tục
            for scene in processed_scenes:
                scene["scene_id"] = scene_id_counter
                all_scenes.append(scene)
                scene_id_counter += 1

            # Delay giữa các batch để tránh rate limit
            if batch_idx < len(batches) - 1:
                time.sleep(1)

        # Kiểm tra có scenes không
        if not all_scenes:
            self._log("  ERROR: No scenes created!", "ERROR")
            return StepResult("create_director_plan", StepStatus.FAILED, "No scenes created")

        # Save to Excel
        try:
            workbook.save_director_plan(all_scenes)
            workbook.save()
            self._log(f"  -> Saved {len(all_scenes)} scenes to director_plan")
            self._log(f"     Total duration: {sum(s.get('duration', 0) for s in all_scenes):.1f}s")

            return StepResult("create_director_plan", StepStatus.COMPLETED, "Success", {"scenes": all_scenes})
        except Exception as e:
            self._log(f"  ERROR: Could not save to Excel: {e}", "ERROR")
            return StepResult("create_director_plan", StepStatus.FAILED, str(e))

    # =========================================================================
    # STEP 4 BASIC: TẠO DIRECTOR'S PLAN (SEGMENT-BASED, NO 8s LIMIT)
    # =========================================================================

    def step_create_director_plan_basic(
        self,
        project_dir: Path,
        code: str,
        workbook: PromptWorkbook,
        srt_entries: list,
    ) -> StepResult:
        """
        Step 4 BASIC: Tạo director's plan dựa trên story segments.

        Khác với phiên bản thường:
        - KHÔNG giới hạn 8s
        - Số scenes = tổng image_count từ tất cả segments
        - Duration = segment_duration / image_count
        - Dựa hoàn toàn vào kế hoạch từ Step 1.5

        Input: story_segments, characters, locations, SRT
        Output: director_plan với số scenes = planned images
        """
        self._log("\n" + "="*60)
        self._log("[STEP 4 BASIC] Creating director's plan (segment-based)...")
        self._log("="*60)

        # Check if already done
        try:
            existing_plan = workbook.get_director_plan()
            if existing_plan and len(existing_plan) > 0:
                self._log(f"  -> Already has {len(existing_plan)} scenes, skip!")
                return StepResult("create_director_plan_basic", StepStatus.COMPLETED, "Already done")
        except:
            pass

        # Read story segments (REQUIRED for basic mode)
        story_segments = workbook.get_story_segments() or []
        if not story_segments:
            self._log("  ERROR: No story segments! Run step 1.5 first.", "ERROR")
            return StepResult("create_director_plan_basic", StepStatus.FAILED, "No story segments")

        total_planned_images = sum(s.get("image_count", 0) for s in story_segments)
        self._log(f"  Story segments: {len(story_segments)} segments, {total_planned_images} planned images")

        # Read context
        story_analysis = workbook.get_story_analysis() or {}
        characters = workbook.get_characters()
        locations = workbook.get_locations()

        context_lock = story_analysis.get("context_lock", "")

        # Build character/location info
        char_locks = []
        for c in characters:
            if c.character_lock:
                char_locks.append(f"- {c.id}: {c.character_lock}")

        loc_locks = []
        for loc in locations:
            if hasattr(loc, 'location_lock') and loc.location_lock:
                loc_locks.append(f"- {loc.id}: {loc.location_lock}")

        # Process each segment
        all_scenes = []
        scene_id_counter = 1

        for seg in story_segments:
            seg_id = seg.get("segment_id", 0)
            seg_name = seg.get("segment_name", "")
            image_count = seg.get("image_count", 1)
            srt_start = seg.get("srt_range_start", 1)
            srt_end = seg.get("srt_range_end", len(srt_entries))
            message = seg.get("message", "")

            self._log(f"  Segment {seg_id}: {seg_name} ({image_count} images, SRT {srt_start}-{srt_end})")

            # Get SRT entries for this segment
            seg_entries = [e for i, e in enumerate(srt_entries, 1) if srt_start <= i <= srt_end]

            if not seg_entries:
                self._log(f"     -> No SRT entries for this segment, skip")
                continue

            # Calculate segment duration
            try:
                first_entry = seg_entries[0]
                last_entry = seg_entries[-1]

                # Parse timestamps
                def parse_time(ts):
                    parts = ts.replace(',', ':').split(':')
                    return int(parts[0])*3600 + int(parts[1])*60 + int(parts[2]) + int(parts[3])/1000

                seg_start_time = parse_time(first_entry.start_time)
                seg_end_time = parse_time(last_entry.end_time)
                seg_duration = seg_end_time - seg_start_time
            except:
                seg_duration = len(seg_entries) * 5  # Fallback: 5s per entry

            # SEGMENT 1 SPECIAL: Tuân thủ 8s limit như bản worker_pic
            # Các segment khác: dùng image_count từ Step 1.5
            if seg_id == 1:
                # Segment 1: tính số scenes theo 8s limit
                original_image_count = image_count
                image_count = max(1, int(seg_duration / 8) + 1)  # Target ~8s per scene
                self._log(f"     -> Segment 1 special: {original_image_count} planned -> {image_count} scenes (8s limit)")

            # Calculate duration per scene
            scene_duration = seg_duration / image_count if image_count > 0 else seg_duration

            # Distribute SRT entries among scenes
            entries_per_scene = len(seg_entries) / image_count if image_count > 0 else len(seg_entries)

            # Build SRT text for API prompt
            srt_text = ""
            for i, entry in enumerate(seg_entries):
                idx = srt_start + i
                srt_text += f"[{idx}] {entry.start_time} --> {entry.end_time}\n{entry.text}\n\n"

            # Call API to create scenes for this segment
            prompt = f"""You are a FILM DIRECTOR. Create exactly {image_count} cinematic shots for this story segment.

SEGMENT INFO:
- Name: "{seg_name}"
- Message: "{message}"
- Duration: {seg_duration:.1f} seconds total
- Required: EXACTLY {image_count} scenes (each ~{scene_duration:.1f}s)

STORY CONTEXT:
{context_lock}

CHARACTERS:
{chr(10).join(char_locks) if char_locks else 'No characters defined'}

LOCATIONS:
{chr(10).join(loc_locks) if loc_locks else 'No locations defined'}

SRT CONTENT FOR THIS SEGMENT:
{srt_text}

INSTRUCTIONS:
1. Create EXACTLY {image_count} scenes - no more, no less
2. Each scene should be ~{scene_duration:.1f} seconds
3. Distribute the SRT content evenly across all {image_count} scenes
4. Each scene = one cinematic shot that supports the narration
5. Use EXACT character/location IDs from the lists above
6. Think like a film director - what shot best conveys each moment?

Return JSON only:
{{
    "scenes": [
        {{
            "scene_id": {scene_id_counter},
            "srt_indices": [list of SRT indices covered],
            "srt_start": "timestamp",
            "srt_end": "timestamp",
            "duration": {scene_duration:.1f},
            "srt_text": "narration text for this scene",
            "visual_moment": "what viewer sees - specific and purposeful",
            "characters_used": "nv_xxx, nv_yyy",
            "location_used": "loc_xxx",
            "camera": "shot type (close-up, wide, medium, etc.)",
            "lighting": "lighting description"
        }}
    ]
}}
Create exactly {image_count} scenes!"""

            # Call API with retry logic
            MAX_RETRIES = 3
            data = None

            for retry in range(MAX_RETRIES):
                response = self._call_api(prompt, temperature=0.5, max_tokens=8192)
                if not response:
                    self._log(f"     Retry {retry+1}/{MAX_RETRIES}: API call failed", "WARNING")
                    time.sleep(2 ** retry)
                    continue

                data = self._extract_json(response)
                if data and "scenes" in data:
                    break  # Success!
                else:
                    self._log(f"     Retry {retry+1}/{MAX_RETRIES}: JSON parse failed", "WARNING")
                    time.sleep(2 ** retry)

            # If all retries failed, create fallback scenes
            if not data or "scenes" not in data:
                self._log(f"     -> All retries failed, creating {image_count} fallback scenes", "WARNING")
                for i in range(image_count):
                    start_idx = int(i * entries_per_scene)
                    end_idx = min(int((i + 1) * entries_per_scene), len(seg_entries))
                    scene_entries = seg_entries[start_idx:end_idx] if seg_entries else []

                    fallback_scene = {
                        "scene_id": scene_id_counter,
                        "srt_indices": list(range(srt_start + start_idx, srt_start + end_idx)),
                        "srt_start": scene_entries[0].start_time if scene_entries else "",
                        "srt_end": scene_entries[-1].end_time if scene_entries else "",
                        "duration": scene_duration,
                        "srt_text": " ".join([e.text for e in scene_entries]) if scene_entries else "",
                        "visual_moment": f"[Auto] Scene {i+1}/{image_count} from: {seg_name}",
                        "characters_used": "",
                        "location_used": "",
                        "camera": "Medium shot",
                        "lighting": "Natural lighting"
                    }
                    all_scenes.append(fallback_scene)
                    scene_id_counter += 1
                continue

            # Add scenes from API response
            api_scenes = data["scenes"]
            self._log(f"     -> Got {len(api_scenes)} scenes from API")

            # Ensure correct scene count
            if len(api_scenes) != image_count:
                self._log(f"     -> Warning: Expected {image_count}, got {len(api_scenes)}")

            # Update scene IDs to be continuous
            for scene in api_scenes:
                scene["scene_id"] = scene_id_counter
                all_scenes.append(scene)
                scene_id_counter += 1

            # Delay between segments
            time.sleep(0.5)

        # Verify total scene count
        if len(all_scenes) != total_planned_images:
            self._log(f"  Note: Created {len(all_scenes)} scenes (planned: {total_planned_images})")

        if not all_scenes:
            self._log("  ERROR: No scenes created!", "ERROR")
            return StepResult("create_director_plan_basic", StepStatus.FAILED, "No scenes created")

        # Save to Excel
        try:
            workbook.save_director_plan(all_scenes)
            workbook.save()
            self._log(f"  -> Saved {len(all_scenes)} scenes to director_plan")
            self._log(f"     Total duration: {sum(s.get('duration', 0) for s in all_scenes):.1f}s")

            return StepResult("create_director_plan_basic", StepStatus.COMPLETED, "Success", {"scenes": all_scenes})
        except Exception as e:
            self._log(f"  ERROR: Could not save to Excel: {e}", "ERROR")
            return StepResult("create_director_plan_basic", StepStatus.FAILED, str(e))

    # =========================================================================
    # STEP 4.5: LÊN KẾ HOẠCH CHI TIẾT TỪNG SCENE
    # =========================================================================

    def step_plan_scenes(
        self,
        project_dir: Path,
        code: str,
        workbook: PromptWorkbook,
    ) -> StepResult:
        """
        Step 4.5: Lên kế hoạch chi tiết cho từng scene TRƯỚC KHI viết prompt.

        Mục đích: Xác định ý đồ nghệ thuật cho mỗi scene
        - Scene này muốn truyền tải gì?
        - Góc máy nên thế nào?
        - Nhân vật đang làm gì, cảm xúc ra sao?
        - Ánh sáng, màu sắc, mood?

        Input: director_plan, story_segments, characters, locations
        Output: scene_planning sheet
        """
        self._log("\n" + "="*60)
        self._log("[STEP 4.5] Lên kế hoạch chi tiết từng scene...")
        self._log("="*60)

        # Check if already done
        try:
            existing = workbook.get_scene_planning()
            if existing and len(existing) > 0:
                self._log(f"  -> Đã có {len(existing)} scene plans, skip!")
                return StepResult("plan_scenes", StepStatus.COMPLETED, "Already done")
        except:
            pass

        # Read director plan
        director_plan = workbook.get_director_plan()
        if not director_plan:
            self._log("  ERROR: No director plan! Run step 4 first.", "ERROR")
            return StepResult("plan_scenes", StepStatus.FAILED, "No director plan")

        # Read context
        story_analysis = workbook.get_story_analysis() or {}
        story_segments = workbook.get_story_segments() or []
        characters = workbook.get_characters()
        locations = workbook.get_locations()

        context_lock = story_analysis.get("context_lock", "")

        # Build character info
        char_info = "\n".join([f"- {c.id}: {c.character_lock}" for c in characters if c.character_lock])
        loc_info = "\n".join([f"- {loc.id}: {loc.location_lock}" for loc in locations if hasattr(loc, 'location_lock') and loc.location_lock])

        # Build segments info
        segments_info = ""
        for seg in story_segments:
            segments_info += f"- Segment {seg.get('segment_id')}: {seg.get('segment_name')} ({seg.get('message', '')[:100]})\n"

        self._log(f"  Director plan: {len(director_plan)} scenes")
        self._log(f"  Story segments: {len(story_segments)}")

        # Process in batches - PARALLEL processing
        BATCH_SIZE = 15
        MAX_PARALLEL = self.config.get("max_parallel_api", 6)  # From settings.yaml
        all_plans = []

        # Prepare all batches
        batches = []
        for batch_start in range(0, len(director_plan), BATCH_SIZE):
            batch = director_plan[batch_start:batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1
            batches.append((batch_num, batch_start, batch))

        total_batches = len(batches)
        self._log(f"  Processing {total_batches} batches in parallel (max {MAX_PARALLEL} concurrent)")

        def process_single_batch(batch_info):
            """Process a single batch - called in parallel"""
            batch_num, batch_start, batch = batch_info

            # Format scenes for prompt
            scenes_text = ""
            for scene in batch:
                scenes_text += f"""
Scene {scene.get('scene_id')}:
- Time: {scene.get('srt_start')} → {scene.get('srt_end')} ({scene.get('duration', 0):.1f}s)
- Text: {scene.get('srt_text', '')[:200]}
- Visual moment: {scene.get('visual_moment', '')}
- Characters: {scene.get('characters_used', '')}
- Location: {scene.get('location_used', '')}
"""

            prompt = f"""You are a film director planning each scene's artistic vision.

STORY CONTEXT:
{context_lock}

STORY SEGMENTS (narrative structure):
{segments_info if segments_info else 'Not specified'}

CHARACTERS:
{char_info if char_info else 'Not specified'}

LOCATIONS:
{loc_info if loc_info else 'Not specified'}

SCENES TO PLAN:
{scenes_text}

For EACH scene, create an artistic plan that includes:
1. artistic_intent: What emotion/message should this scene convey?
2. shot_type: Camera angle and framing (close-up, medium, wide, etc.)
3. character_action: What are characters doing? Their body language, expression?
4. mood: Overall feeling (tense, warm, melancholic, hopeful, etc.)
5. lighting: Type of lighting (soft, harsh, dramatic, natural, etc.)
6. color_palette: Dominant colors for the scene
7. key_focus: What should viewer's eye be drawn to?

Return JSON only:
{{
    "scene_plans": [
        {{
            "scene_id": 1,
            "artistic_intent": "Show the protagonist's isolation and loneliness",
            "shot_type": "Wide shot, slowly pushing in",
            "character_action": "Sitting alone, shoulders slumped, staring at window",
            "mood": "Melancholic, contemplative",
            "lighting": "Soft diffused light from window, shadows on face",
            "color_palette": "Cool blues and grays, muted tones",
            "key_focus": "Character's face and empty space around them"
        }}
    ]
}}
"""

            # Call API with retry logic
            MAX_RETRIES = 3
            data = None

            for retry in range(MAX_RETRIES):
                response = self._call_api(prompt, temperature=0.4, max_tokens=8192)
                if not response:
                    time.sleep(2 ** retry)  # Exponential backoff
                    continue

                # Parse response
                data = self._extract_json(response)
                if data and "scene_plans" in data:
                    break  # Success!
                else:
                    time.sleep(2 ** retry)

            if not data or "scene_plans" not in data:
                # Fallback: create basic plans for this batch
                fallback_plans = []
                for scene in batch:
                    fallback_plan = {
                        "scene_id": scene.get("scene_id"),
                        "artistic_intent": f"Convey the moment: {scene.get('visual_moment', '')[:100]}",
                        "shot_type": scene.get("camera", "Medium shot"),
                        "character_action": "As described in visual moment",
                        "mood": "Matches the narration tone",
                        "lighting": scene.get("lighting", "Natural lighting"),
                        "color_palette": "Neutral tones",
                        "key_focus": "Main subject of the scene"
                    }
                    fallback_plans.append(fallback_plan)
                return (batch_num, fallback_plans, True)  # True = fallback used

            return (batch_num, data["scene_plans"], False)  # False = API success

        # Execute batches in parallel
        batch_results = {}
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as executor:
            future_to_batch = {executor.submit(process_single_batch, b): b[0] for b in batches}

            for future in as_completed(future_to_batch):
                batch_num = future_to_batch[future]
                try:
                    result_batch_num, plans, used_fallback = future.result()
                    batch_results[result_batch_num] = plans
                    status = "fallback" if used_fallback else "OK"
                    self._log(f"     Batch {result_batch_num}/{total_batches}: {len(plans)} plans [{status}]")
                except Exception as e:
                    self._log(f"     Batch {batch_num} error: {e}", "ERROR")
                    batch_results[batch_num] = []

        # Combine results in order
        for batch_num in sorted(batch_results.keys()):
            all_plans.extend(batch_results[batch_num])

        if not all_plans:
            self._log("  ERROR: No scene plans created!", "ERROR")
            return StepResult("plan_scenes", StepStatus.FAILED, "No plans created")

        # Save to Excel
        try:
            workbook.save_scene_planning(all_plans)
            workbook.save()
            self._log(f"  -> Saved {len(all_plans)} scene plans to Excel")
            return StepResult("plan_scenes", StepStatus.COMPLETED, "Success", {"plans": all_plans})
        except Exception as e:
            self._log(f"  ERROR: Could not save: {e}", "ERROR")
            return StepResult("plan_scenes", StepStatus.FAILED, str(e))

    # =========================================================================
    # STEP 5: TẠO SCENE PROMPTS (BATCH)
    # =========================================================================

    def step_create_scene_prompts(
        self,
        project_dir: Path,
        code: str,
        workbook: PromptWorkbook,
        batch_size: int = 10
    ) -> StepResult:
        """
        Step 5: Tạo prompts cho từng scene (theo batch).

        Input: Đọc director_plan, characters, locations từ Excel
        Output: Thêm scenes vào sheet scenes
        """
        self._log("\n" + "="*60)
        self._log("[STEP 5] Tạo scene prompts...")
        self._log("="*60)

        # Read director plan
        try:
            director_plan = workbook.get_director_plan()
            if not director_plan:
                self._log("  ERROR: No director plan found! Run step 4 first.", "ERROR")
                return StepResult("create_scene_prompts", StepStatus.FAILED, "No director plan")
        except Exception as e:
            self._log(f"  ERROR: Could not read director plan: {e}", "ERROR")
            return StepResult("create_scene_prompts", StepStatus.FAILED, str(e))

        # Check existing scenes
        existing_scenes = workbook.get_scenes()
        existing_ids = {s.scene_id for s in existing_scenes} if existing_scenes else set()

        # Find scenes that need prompts
        pending_scenes = [s for s in director_plan if s.get("scene_id") not in existing_ids]

        if not pending_scenes:
            self._log(f"  -> Đã có {len(existing_scenes)} scenes, skip!")
            return StepResult("create_scene_prompts", StepStatus.COMPLETED, "Already done")

        self._log(f"  -> Cần tạo prompts cho {len(pending_scenes)} scenes...")

        # Read context
        story_analysis = {}
        try:
            story_analysis = workbook.get_story_analysis() or {}
        except:
            pass

        characters = workbook.get_characters()
        locations = workbook.get_locations()

        # Đọc scene planning (kế hoạch chi tiết từ step 4.5)
        scene_planning = {}
        try:
            plans = workbook.get_scene_planning() or []
            for plan in plans:
                scene_planning[plan.get("scene_id")] = plan
            self._log(f"  Loaded {len(scene_planning)} scene plans from step 4.5")
        except:
            pass

        context_lock = story_analysis.get("context_lock", "")

        # Build character/location lookup - bao gồm cả image_file cho reference
        char_lookup = {}
        char_image_lookup = {}  # id -> image_file (nvc.png, nvp1.png...)
        for c in characters:
            if c.character_lock:
                char_lookup[c.id] = c.character_lock
            # Lấy image_file, mặc định là {id}.png
            img_file = c.image_file if c.image_file else f"{c.id}.png"
            char_image_lookup[c.id] = img_file

        loc_lookup = {}
        loc_image_lookup = {}  # id -> image_file (loc_xxx.png)
        for loc in locations:
            if hasattr(loc, 'location_lock') and loc.location_lock:
                loc_lookup[loc.id] = loc.location_lock
            # Lấy image_file, mặc định là {id}.png
            img_file = loc.image_file if hasattr(loc, 'image_file') and loc.image_file else f"{loc.id}.png"
            loc_image_lookup[loc.id] = img_file

        # Process in batches - PARALLEL API calls
        total_created = 0
        MAX_PARALLEL = self.config.get("max_parallel_api", 6)  # From settings.yaml

        # Prepare all batches
        all_batches = []
        for batch_start in range(0, len(pending_scenes), batch_size):
            batch = pending_scenes[batch_start:batch_start + batch_size]
            batch_num = batch_start // batch_size + 1
            all_batches.append((batch_num, batch))

        total_batches = len(all_batches)
        self._log(f"  Processing {total_batches} batches in parallel (max {MAX_PARALLEL} concurrent)")

        def process_single_batch(batch_info):
            """Process a single batch - called in parallel"""
            batch_num, batch = batch_info

            # Build scenes text for prompt
            scenes_text = ""
            for scene in batch:
                char_ids = [cid.strip() for cid in scene.get("characters_used", "").split(",") if cid.strip()]
                char_desc_parts = []
                char_refs = []
                for cid in char_ids:
                    desc = char_lookup.get(cid, cid)
                    img = char_image_lookup.get(cid, f"{cid}.png")
                    char_desc_parts.append(f"{desc} ({img})")
                    char_refs.append(img)
                char_desc = ", ".join(char_desc_parts)

                loc_id = scene.get("location_used", "")
                loc_desc = loc_lookup.get(loc_id, loc_id)
                loc_img = loc_image_lookup.get(loc_id, f"{loc_id}.png") if loc_id else ""
                if loc_desc and loc_img:
                    loc_desc = f"{loc_desc} ({loc_img})"

                scene_id = scene.get('scene_id')
                plan = scene_planning.get(scene_id, {})
                plan_info = ""
                if plan:
                    plan_info = f"""
- [ARTISTIC PLAN from Step 4.5]:
  * Intent: {plan.get('artistic_intent', '')}
  * Shot type: {plan.get('shot_type', '')}
  * Action: {plan.get('character_action', '')}
  * Mood: {plan.get('mood', '')}
  * Lighting: {plan.get('lighting', '')}
  * Colors: {plan.get('color_palette', '')}
  * Focus: {plan.get('key_focus', '')}"""

                scenes_text += f"""
Scene {scene_id}:
- Time: {scene.get('srt_start')} --> {scene.get('srt_end')}
- Text: {scene.get('srt_text', '')}
- Visual moment: {scene.get('visual_moment', '')}
- Characters: {char_desc}
- Location: {loc_desc}
- Camera: {scene.get('camera', '')}
- Lighting: {scene.get('lighting', '')}
- Reference files: {', '.join(char_refs + ([loc_img] if loc_img else []))}
{plan_info}
"""

            prompt = f"""Create detailed image prompts for these {len(batch)} scenes.

VISUAL CONTEXT (use as prefix):
{context_lock}

IMPORTANT - REFERENCE FILE ANNOTATIONS:
- Each character MUST have their reference file in parentheses: "a man (nv_john.png)"
- Location MUST have reference file: "in the room (loc_office.png)"
- Format: "Description of person (nv_xxx.png) doing action in location (loc_xxx.png)"
- Character files always start with "nv_", location files always start with "loc_"

SCENES TO PROCESS ({len(batch)} scenes - create EXACTLY {len(batch)} prompts):
{scenes_text}

CRITICAL REQUIREMENTS:
1. Create EXACTLY {len(batch)} scene prompts - one for EACH scene listed above
2. Each img_prompt MUST be UNIQUE - do NOT copy/repeat prompts between scenes
3. Each prompt should reflect the specific visual_moment and text of that scene
4. Use the exact scene_id from the input

For each scene, create:
1. img_prompt: UNIQUE detailed image generation prompt with REFERENCE ANNOTATIONS
2. video_prompt: Motion/video prompt if this becomes a video clip

Example img_prompt:
"Close-up shot, 85mm lens, a 35-year-old man with tired eyes (nv_john.png) sitting at a desk, looking worried, soft window light, in a modern office (loc_office.png), cinematic, 4K"

Return JSON only with EXACTLY {len(batch)} scenes:
{{
    "scenes": [
        {{
            "scene_id": 1,
            "img_prompt": "UNIQUE detailed prompt with (character.png) and (location.png) annotations...",
            "video_prompt": "camera movement and action description..."
        }}
    ]
}}
"""

            # Call API with retry
            MAX_RETRIES = 3
            for retry in range(MAX_RETRIES):
                response = self._call_api(prompt, temperature=0.5, max_tokens=8192)
                if response:
                    data = self._extract_json(response)
                    if data and "scenes" in data:
                        return (batch_num, batch, data["scenes"], None)  # Success
                time.sleep(2 ** retry)

            return (batch_num, batch, None, "API failed")  # Failed

        # Execute batches in parallel
        batch_results = {}
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as executor:
            future_to_batch = {executor.submit(process_single_batch, b): b[0] for b in all_batches}

            for future in as_completed(future_to_batch):
                batch_num = future_to_batch[future]
                try:
                    result = future.result()
                    batch_results[result[0]] = result  # Store by batch_num
                    status = "OK" if result[2] else "FAILED"
                    self._log(f"     Batch {result[0]}/{total_batches}: [{status}]")
                except Exception as e:
                    self._log(f"     Batch {batch_num} error: {e}", "ERROR")

        # Process and save results sequentially (Excel not thread-safe)
        for batch_num in sorted(batch_results.keys()):
            _, batch, api_scenes, error = batch_results[batch_num]

            if not api_scenes:
                self._log(f"  Batch {batch_num}: skipped ({error})", "WARNING")
                continue

            # Validate
            if len(api_scenes) != len(batch):
                self._log(f"  ⚠️ Batch {batch_num}: API returned {len(api_scenes)}, expected {len(batch)}", "WARN")

            # Check duplicates
            seen_prompts = set()
            duplicate_count = sum(1 for s in api_scenes if (p := s.get("img_prompt", "")[:100]) in seen_prompts or seen_prompts.add(p))
            if duplicate_count > len(api_scenes) * 0.5:
                self._log(f"  Batch {batch_num}: >50% duplicates, skipped!", "ERROR")
                continue

            # Save scenes
            try:
                for scene_data in api_scenes:
                    scene_id = int(scene_data.get("scene_id", 0))
                    original = next((s for s in batch if int(s.get("scene_id", 0)) == scene_id), None)
                    if not original:
                        continue

                    img_prompt = scene_data.get("img_prompt", "")

                    # Post-process: ensure reference annotations
                    char_ids = [cid.strip() for cid in original.get("characters_used", "").split(",") if cid.strip()]
                    loc_id = original.get("location_used", "")

                    for cid in char_ids:
                        img_file = char_image_lookup.get(cid, f"{cid}.png")
                        if img_file and f"({img_file})" not in img_prompt:
                            img_prompt = img_prompt.rstrip(". ") + f" ({img_file})."

                    if loc_id:
                        loc_img = loc_image_lookup.get(loc_id, f"{loc_id}.png")
                        if loc_img and f"({loc_img})" not in img_prompt:
                            img_prompt = img_prompt.rstrip(". ") + f" (reference: {loc_img})."

                    ref_files = [char_image_lookup.get(cid, f"{cid}.png") for cid in char_ids]
                    if loc_id:
                        ref_files.append(loc_image_lookup.get(loc_id, f"{loc_id}.png"))

                    scene = Scene(
                        scene_id=scene_id,
                        srt_start=original.get("srt_start", ""),
                        srt_end=original.get("srt_end", ""),
                        duration=original.get("duration", 0),
                        srt_text=original.get("srt_text", ""),
                        img_prompt=img_prompt,
                        video_prompt=scene_data.get("video_prompt", ""),
                        characters_used=original.get("characters_used", ""),
                        location_used=original.get("location_used", ""),
                        reference_files=json.dumps(ref_files) if ref_files else "",
                        status_img="pending",
                        status_vid="pending"
                    )
                    workbook.add_scene(scene)
                    total_created += 1

                workbook.save()
            except Exception as e:
                self._log(f"  Batch {batch_num} save error: {e}", "ERROR")

        self._log(f"\n  -> Total: Created {total_created} scene prompts")

        if total_created > 0:
            return StepResult("create_scene_prompts", StepStatus.COMPLETED, f"Created {total_created} scenes")
        else:
            return StepResult("create_scene_prompts", StepStatus.FAILED, "No scenes created")

    # =========================================================================
    # MAIN: RUN ALL STEPS
    # =========================================================================

    def run_all_steps(
        self,
        project_dir: Path,
        code: str,
        log_callback: Callable = None
    ) -> bool:
        """
        Chạy tất cả steps theo thứ tự.
        Mỗi step kiểm tra xem đã xong chưa, nếu xong thì skip.

        Returns:
            True nếu thành công (tất cả steps completed)
        """
        self.log_callback = log_callback
        project_dir = Path(project_dir)

        self._log("\n" + "="*70)
        self._log("  PROGRESSIVE PROMPTS GENERATOR")
        self._log("  Mỗi step lưu vào Excel, có thể resume nếu fail")
        self._log("="*70)

        # Paths
        srt_path = project_dir / f"{code}.srt"
        txt_path = project_dir / f"{code}.txt"
        excel_path = project_dir / f"{code}_prompts.xlsx"

        if not srt_path.exists():
            self._log(f"ERROR: SRT not found: {srt_path}", "ERROR")
            return False

        # Parse SRT
        srt_entries = parse_srt_file(srt_path)
        if not srt_entries:
            self._log("ERROR: No SRT entries found!", "ERROR")
            return False

        self._log(f"  SRT: {len(srt_entries)} entries")

        # Read TXT if exists
        txt_content = ""
        if txt_path.exists():
            try:
                txt_content = txt_path.read_text(encoding='utf-8')
                self._log(f"  TXT: {len(txt_content)} chars")
            except:
                pass

        # Load/create workbook
        workbook = PromptWorkbook(excel_path).load_or_create()

        # Run steps
        all_success = True

        # Step 1: Analyze story
        result = self.step_analyze_story(project_dir, code, workbook, srt_entries, txt_content)
        if result.status == StepStatus.FAILED:
            self._log("Step 1 FAILED! Stopping.", "ERROR")
            return False

        # Step 1.5: Analyze story segments (nội dung con)
        result = self.step_analyze_story_segments(project_dir, code, workbook, srt_entries, txt_content)
        if result.status == StepStatus.FAILED:
            self._log("Step 1.5 FAILED! Stopping.", "ERROR")
            return False

        # Step 2: Create characters
        result = self.step_create_characters(project_dir, code, workbook, srt_entries, txt_content)
        if result.status == StepStatus.FAILED:
            self._log("Step 2 FAILED! Stopping.", "ERROR")
            return False

        # Step 3: Create locations
        result = self.step_create_locations(project_dir, code, workbook, srt_entries, txt_content)
        if result.status == StepStatus.FAILED:
            self._log("Step 3 FAILED! Stopping.", "ERROR")
            return False

        # Step 4: Create director plan (sử dụng segments để guide số lượng scenes)
        result = self.step_create_director_plan(project_dir, code, workbook, srt_entries)
        if result.status == StepStatus.FAILED:
            self._log("Step 4 FAILED! Stopping.", "ERROR")
            return False

        # Step 4.5: Lên kế hoạch chi tiết từng scene (artistic planning)
        result = self.step_plan_scenes(project_dir, code, workbook)
        if result.status == StepStatus.FAILED:
            self._log("Step 4.5 FAILED! Stopping.", "ERROR")
            return False

        # Step 5: Create scene prompts (đọc từ scene planning)
        result = self.step_create_scene_prompts(project_dir, code, workbook)
        if result.status == StepStatus.FAILED:
            self._log("Step 5 FAILED!", "ERROR")
            return False

        self._log("\n" + "="*70)
        self._log("  ALL STEPS COMPLETED!")
        self._log("="*70)

        return True
