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

import sys
import os

# Fix Windows encoding issues
if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except:
            pass
    if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
        try:
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        except:
            pass


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
        """Extract JSON từ response text - với repair cho truncated JSON."""
        import re

        if not text:
            return None

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
                # Thử repair
                repaired = self._repair_truncated_json(match.group(1))
                if repaired:
                    try:
                        return json.loads(repaired)
                    except:
                        pass

        # Tìm JSON object
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            json_str = match.group(0)
            try:
                return json.loads(json_str)
            except:
                # Thử repair truncated JSON
                repaired = self._repair_truncated_json(json_str)
                if repaired:
                    try:
                        return json.loads(repaired)
                    except:
                        pass

        # Tìm JSON bắt đầu bằng { nhưng có thể bị cắt cuối
        start_idx = text.find('{')
        if start_idx != -1:
            json_str = text[start_idx:]
            repaired = self._repair_truncated_json(json_str)
            if repaired:
                try:
                    return json.loads(repaired)
                except:
                    pass

        return None

    def _repair_truncated_json(self, json_str: str) -> Optional[str]:
        """Repair JSON bị truncated (thiếu closing brackets)."""
        if not json_str:
            return None

        # Đếm brackets
        open_braces = json_str.count('{')
        close_braces = json_str.count('}')
        open_brackets = json_str.count('[')
        close_brackets = json_str.count(']')

        # Nếu balanced thì return nguyên
        if open_braces == close_braces and open_brackets == close_brackets:
            return json_str

        # Nếu có nhiều close hơn open -> JSON không valid
        if close_braces > open_braces or close_brackets > open_brackets:
            return None

        # Cắt bỏ phần dở dang cuối và thêm closing brackets
        # Tìm vị trí cuối cùng có thể là kết thúc hợp lệ
        for i in range(len(json_str) - 1, max(0, len(json_str) - 200), -1):
            char = json_str[i]
            if char in '}]"':
                test_str = json_str[:i+1]
                # Đếm lại
                ob = test_str.count('{')
                cb = test_str.count('}')
                oB = test_str.count('[')
                cB = test_str.count(']')
                # Thêm closing cần thiết
                suffix = ']' * max(0, oB - cB) + '}' * max(0, ob - cb)
                repaired = test_str + suffix
                try:
                    json.loads(repaired)
                    return repaired
                except:
                    continue

        # Fallback: Thêm closing brackets đơn giản
        suffix = ']' * max(0, open_brackets - close_brackets)
        suffix += '}' * max(0, open_braces - close_braces)
        return json_str + suffix

    def _sample_text(self, text: str, total_chars: int = 8000) -> str:
        """
        Lấy mẫu text thông minh: đầu + giữa + cuối.
        Thay vì gửi 15-20k chars, chỉ gửi ~8k nhưng bao phủ toàn bộ nội dung.

        Args:
            text: Full text
            total_chars: Tổng số ký tự muốn lấy (default 8000)

        Returns:
            Sampled text với markers [BEGINNING], [MIDDLE], [END]
        """
        if len(text) <= total_chars:
            return text

        # Chia tỷ lệ: 40% đầu, 30% giữa, 30% cuối
        begin_chars = int(total_chars * 0.4)
        middle_chars = int(total_chars * 0.3)
        end_chars = int(total_chars * 0.3)

        # Lấy phần đầu
        begin_text = text[:begin_chars]

        # Lấy phần giữa (từ khoảng 40% đến 60% của text)
        middle_start = len(text) // 2 - middle_chars // 2
        middle_text = text[middle_start:middle_start + middle_chars]

        # Lấy phần cuối
        end_text = text[-end_chars:]

        sampled = f"""[BEGINNING - First {begin_chars} chars]
{begin_text}

[MIDDLE - Around center of story]
{middle_text}

[END - Last {end_chars} chars]
{end_text}"""

        return sampled

    def _get_srt_for_range(self, srt_entries: list, start_idx: int, end_idx: int) -> str:
        """
        Lấy SRT text cho một range cụ thể.

        Args:
            srt_entries: List of SRT entries
            start_idx: 1-based start index
            end_idx: 1-based end index

        Returns:
            Formatted SRT text
        """
        srt_text = ""
        for i, entry in enumerate(srt_entries, 1):
            if start_idx <= i <= end_idx:
                srt_text += f"[{i}] {entry.start_time} --> {entry.end_time}\n{entry.text}\n\n"
        return srt_text

    def _normalize_character_ids(self, characters_used: str, valid_char_ids: set) -> str:
        """
        Normalize character IDs từ API response về format chuẩn (nv_xxx).

        Vấn đề: API có thể trả về "john, mary" thay vì "nv_john, nv_mary"
        Giải pháp: Map về IDs đã biết trong valid_char_ids

        Args:
            characters_used: String từ API như "john, mary" hoặc "nv_john"
            valid_char_ids: Set of valid IDs như {"nv_john", "nv_mary", "loc_office"}

        Returns:
            Normalized string như "nv_john, nv_mary"
        """
        if not characters_used or not valid_char_ids:
            return characters_used

        raw_ids = [x.strip() for x in characters_used.split(",") if x.strip()]
        normalized = []

        # Build lookup (lowercase -> original)
        id_lookup = {cid.lower(): cid for cid in valid_char_ids}
        # Also add versions without prefix
        for cid in list(valid_char_ids):
            if cid.startswith("nv_"):
                id_lookup[cid[3:].lower()] = cid  # "john" -> "nv_john"
            if cid.startswith("loc_"):
                id_lookup[cid[4:].lower()] = cid  # "office" -> "loc_office"

        for raw_id in raw_ids:
            raw_lower = raw_id.lower()

            # Tìm trong lookup
            if raw_lower in id_lookup:
                normalized.append(id_lookup[raw_lower])
            elif raw_id in valid_char_ids:
                normalized.append(raw_id)
            elif f"nv_{raw_id}" in valid_char_ids:
                normalized.append(f"nv_{raw_id}")
            else:
                # Không tìm thấy - giữ nguyên nhưng thêm nv_ prefix nếu chưa có
                if not raw_id.startswith("nv_") and not raw_id.startswith("loc_"):
                    normalized.append(f"nv_{raw_id}")
                else:
                    normalized.append(raw_id)

        return ", ".join(normalized)

    def _normalize_location_id(self, location_used: str, valid_loc_ids: set) -> str:
        """
        Normalize location ID từ API response về format chuẩn (loc_xxx).

        Args:
            location_used: String từ API như "office" hoặc "loc_office"
            valid_loc_ids: Set of valid location IDs

        Returns:
            Normalized ID như "loc_office"
        """
        if not location_used or not valid_loc_ids:
            return location_used

        raw_id = location_used.strip()
        raw_lower = raw_id.lower()

        # Build lookup
        id_lookup = {lid.lower(): lid for lid in valid_loc_ids}
        for lid in list(valid_loc_ids):
            if lid.startswith("loc_"):
                id_lookup[lid[4:].lower()] = lid  # "office" -> "loc_office"

        # Tìm trong lookup
        if raw_lower in id_lookup:
            return id_lookup[raw_lower]
        elif raw_id in valid_loc_ids:
            return raw_id
        elif f"loc_{raw_id}" in valid_loc_ids:
            return f"loc_{raw_id}"
        else:
            # Không tìm thấy - thêm loc_ prefix nếu chưa có
            if not raw_id.startswith("loc_"):
                return f"loc_{raw_id}"
            return raw_id

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
        import time
        step_start = time.time()

        self._log("\n" + "="*60)
        self._log("[STEP 1/7] Phân tích story...")
        self._log("="*60)

        # Check if already done
        try:
            existing = workbook.get_story_analysis()
            if existing and existing.get("setting"):
                self._log("  -> Đã có story_analysis, skip!")
                workbook.update_step_status("step_1", "COMPLETED", 1, 1, "Already done")
                return StepResult("analyze_story", StepStatus.COMPLETED, "Already done")
        except:
            pass

        # Prepare story text - OPTIMIZED: Use sampled text instead of full 15k
        if txt_content:
            story_text = txt_content
        else:
            story_text = " ".join([e.text for e in srt_entries])

        # Sample text: 8k chars thay vì 15k - tiết kiệm ~50% tokens
        sampled_text = self._sample_text(story_text, total_chars=8000)
        self._log(f"  Text: {len(story_text)} chars → sampled {len(sampled_text)} chars")

        # Build prompt
        prompt = f"""Analyze this story and extract key information for visual production.

NOTE: The story is provided in sampled format (beginning + middle + end) to capture the full narrative arc.

STORY (SAMPLED):
{sampled_text}

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

            # TRACKING: Cập nhật trạng thái với thời gian
            elapsed = int(time.time() - step_start)
            workbook.update_step_status("step_1", "COMPLETED", 1, 1,
                f"{elapsed}s - {data.get('context_lock', '')[:40]}...")

            return StepResult("analyze_story", StepStatus.COMPLETED, "Success", data)
        except Exception as e:
            self._log(f"  ERROR: Could not save to Excel: {e}", "ERROR")
            elapsed = int(time.time() - step_start)
            workbook.update_step_status("step_1", "ERROR", 0, 0, f"{elapsed}s - {str(e)[:80]}")
            return StepResult("analyze_story", StepStatus.FAILED, str(e))

    # =========================================================================
    # STEP 2: PHÂN TÍCH NỘI DUNG CON (STORY SEGMENTS)
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
        import time
        step_start = time.time()

        self._log("\n" + "="*60)
        self._log("[STEP 2/7] Phân tích nội dung con (story segments)...")
        self._log("="*60)

        # Check if already done
        try:
            existing = workbook.get_story_segments()
            if existing and len(existing) > 0:
                self._log(f"  -> Đã có {len(existing)} segments, skip!")
                workbook.update_step_status("step_2", "COMPLETED", len(existing), len(existing), "Already done")
                return StepResult("analyze_story_segments", StepStatus.COMPLETED, "Already done")
        except:
            pass

        # TRACKING: Khởi tạo SRT coverage để đối chiếu
        self._log(f"  Khởi tạo SRT coverage tracking...")
        workbook.init_srt_coverage(srt_entries)

        # Read context from previous step
        story_analysis = {}
        try:
            story_analysis = workbook.get_story_analysis() or {}
        except:
            pass

        context_lock = story_analysis.get("context_lock", "")
        themes = story_analysis.get("themes", [])

        # Prepare story text - OPTIMIZED: Use sampled text
        if txt_content:
            story_text = txt_content
        else:
            story_text = " ".join([e.text for e in srt_entries])

        # Sample text: 10k chars để có đủ context cho segment analysis
        sampled_text = self._sample_text(story_text, total_chars=10000)
        self._log(f"  Text: {len(story_text)} chars → sampled {len(sampled_text)} chars")

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

        # Build prompt - OPTIMIZED: Produce richer segment insights for later steps
        prompt = f"""Analyze this story and divide it into content segments for video creation.

IMPORTANT: Your segment analysis will be used by later steps to create visuals WITHOUT re-reading the full story.
So make your "message" and "key_elements" DETAILED enough to guide visual creation.

STORY CONTEXT:
{context_lock}

THEMES: {', '.join(themes) if themes else 'Not specified'}

TOTAL DURATION: {total_duration:.1f} seconds
TOTAL SRT ENTRIES: {len(srt_entries)}

STORY CONTENT (SAMPLED - beginning + middle + end):
{sampled_text}

TASK: Divide the story into logical segments. Each segment is a distinct part of the narrative.

CRITICAL REQUIREMENT:
- Your segments MUST cover ALL {len(srt_entries)} SRT entries
- First segment starts at srt_range_start: 1
- Last segment MUST end at srt_range_end: {len(srt_entries)}
- NO gaps between segments (segment N ends where segment N+1 starts)

For each segment, provide DETAILED information (this will guide image creation):
1. message: The narrative purpose - what story is being told? What happens?
2. key_elements: List of VISUAL elements (characters, locations, objects, actions, emotions)
3. visual_summary: A 2-3 sentence description of what images should show for this segment
4. mood: The emotional tone (tense, warm, sad, hopeful, dramatic, etc.)
5. characters_involved: Which characters appear in this segment

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
            "message": "DETAILED narrative: what happens, who is involved, what's the conflict/emotion",
            "key_elements": ["character doing action", "specific location", "emotional state", "important object"],
            "visual_summary": "2-3 sentences describing what the images should show. E.g., 'Show the protagonist alone in his room, looking worried. Then show him making a decision, getting up with determination.'",
            "mood": "melancholic/hopeful/tense/etc",
            "characters_involved": ["main character", "supporting character"],
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
            self._log("  ERROR: Could not parse segments from API!", "ERROR")
            self._log(f"  API Response (first 500 chars): {response[:500] if response else 'None'}", "DEBUG")

            # === FALLBACK: Tạo segments đơn giản dựa trên SRT ===
            self._log("  -> Creating FALLBACK segments based on SRT duration...")
            total_srt = len(srt_entries)
            # Parse end_time from last SRT entry
            try:
                last_entry = srt_entries[-1]
                parts = last_entry.end_time.replace(',', ':').split(':')
                total_duration = int(parts[0])*3600 + int(parts[1])*60 + int(parts[2]) + int(parts[3])/1000
            except:
                total_duration = len(srt_entries) * 3  # Fallback: 3s per entry

            # Tính số segments (~60s mỗi segment, ~12 ảnh)
            num_segments = max(1, int(total_duration / 60))
            entries_per_seg = max(1, total_srt // num_segments)
            images_per_seg = max(1, int(60 / 5))  # ~12 ảnh per 60s

            segments = []
            for i in range(num_segments):
                seg_start = i * entries_per_seg + 1
                seg_end = min((i + 1) * entries_per_seg, total_srt)
                if i == num_segments - 1:
                    seg_end = total_srt  # Last segment gets all remaining

                segments.append({
                    "segment_id": i + 1,
                    "segment_name": f"Part {i + 1}",
                    "message": f"Story segment {i + 1}",
                    "key_elements": [],
                    "image_count": images_per_seg,
                    "srt_range_start": seg_start,
                    "srt_range_end": seg_end
                })

            self._log(f"  -> Created {len(segments)} fallback segments")
            data = {"segments": segments}

        segments = data["segments"]
        total_srt = len(srt_entries)

        # VALIDATION: Check if segments cover all SRT entries
        if segments:
            last_seg = segments[-1]
            last_srt_end = last_seg.get("srt_range_end", 0)

            if last_srt_end < total_srt:
                # FIX: Extend coverage to include all SRT entries
                missing_entries = total_srt - last_srt_end
                self._log(f"  [WARN] Segments only cover SRT 1-{last_srt_end}, missing {missing_entries} entries")
                self._log(f"  -> Auto-fixing: extending coverage to SRT {total_srt}")

                # Calculate how many additional images needed (~5s per image)
                missing_duration = missing_entries * (total_duration / total_srt)
                additional_images = max(1, int(missing_duration / 5))

                # Either extend last segment or add new segment
                if missing_entries <= 50:  # Small gap - extend last segment
                    segments[-1]["srt_range_end"] = total_srt
                    segments[-1]["image_count"] = segments[-1].get("image_count", 1) + additional_images
                    self._log(f"     -> Extended last segment to SRT {total_srt} (+{additional_images} images)")
                else:
                    # Larger gap - add new segment(s)
                    remaining = missing_entries
                    current_start = last_srt_end + 1
                    seg_id = len(segments) + 1

                    while remaining > 0:
                        chunk = min(remaining, 100)  # Max 100 entries per segment
                        chunk_images = max(1, int(chunk * (total_duration / total_srt) / 5))
                        new_seg = {
                            "segment_id": seg_id,
                            "segment_name": f"Continuation Part {seg_id - len(data['segments'])}",
                            "message": "Continuing the narrative",
                            "key_elements": [],
                            "image_count": chunk_images,
                            "estimated_duration": chunk * (total_duration / total_srt),
                            "srt_range_start": current_start,
                            "srt_range_end": current_start + chunk - 1,
                            "importance": "medium"
                        }
                        segments.append(new_seg)
                        self._log(f"     -> Added segment {seg_id}: SRT {current_start}-{current_start + chunk - 1} ({chunk_images} images)")

                        current_start += chunk
                        remaining -= chunk
                        seg_id += 1

                data["segments"] = segments

        # Save to Excel
        try:
            workbook.save_story_segments(data["segments"], data.get("total_images", 0), data.get("summary", ""))
            workbook.save()

            total_images = sum(s.get("image_count", 0) for s in data["segments"])
            self._log(f"  -> Saved {len(data['segments'])} segments ({total_images} total images)")
            for seg in data["segments"][:5]:
                self._log(f"     - {seg.get('segment_name')}: {seg.get('image_count')} images")

            # TRACKING: Cập nhật và kiểm tra coverage
            coverage = workbook.update_srt_coverage_segments(data["segments"])
            self._log(f"\n  [STATS] SRT COVERAGE (sau Step 1.5):")
            self._log(f"     Total SRT: {coverage['total_srt']}")
            self._log(f"     Covered by segments: {coverage['covered_by_segment']} ({coverage['coverage_percent']}%)")

            # Determine status based on coverage
            elapsed = int(time.time() - step_start)
            if coverage['uncovered'] > 0:
                self._log(f"     [WARN] UNCOVERED: {coverage['uncovered']} entries", "WARN")
                status = "PARTIAL" if coverage['coverage_percent'] >= 50 else "ERROR"
                workbook.update_step_status("step_2", status,
                    coverage['total_srt'], coverage['covered_by_segment'],
                    f"{elapsed}s - {len(data['segments'])} segs, {coverage['uncovered']} uncovered")
            else:
                workbook.update_step_status("step_2", "COMPLETED",
                    coverage['total_srt'], coverage['covered_by_segment'],
                    f"{elapsed}s - {len(data['segments'])} segs, {total_images} imgs")

            return StepResult("analyze_story_segments", StepStatus.COMPLETED, "Success", data)
        except Exception as e:
            self._log(f"  ERROR: Could not save to Excel: {e}", "ERROR")
            elapsed = int(time.time() - step_start)
            workbook.update_step_status("step_2", "ERROR", 0, 0, f"{elapsed}s - {str(e)[:80]}")
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
        import time
        step_start = time.time()

        self._log("\n" + "="*60)
        self._log("[STEP 3/7] Tạo characters...")
        self._log("="*60)

        # Check if already done
        existing_chars = workbook.get_characters()
        if existing_chars and len(existing_chars) > 0:
            self._log(f"  -> Đã có {len(existing_chars)} characters, skip!")
            workbook.update_step_status("step_3", "COMPLETED", len(existing_chars), len(existing_chars), "Already done")
            return StepResult("create_characters", StepStatus.COMPLETED, "Already done")

        # Read story_analysis from Excel
        story_analysis = {}
        try:
            story_analysis = workbook.get_story_analysis() or {}
        except:
            pass

        context_lock = story_analysis.get("context_lock", "")
        setting = story_analysis.get("setting", {})

        # OPTIMIZED: Tận dụng insights từ Step 1.5 (segments)
        story_segments = workbook.get_story_segments() or []

        # Build rich context từ segments thay vì đọc lại full text
        segment_insights = ""
        all_characters_mentioned = set()
        all_key_elements = []

        for seg in story_segments:
            seg_name = seg.get("segment_name", "")
            message = seg.get("message", "")
            visual_summary = seg.get("visual_summary", "")
            key_elements = seg.get("key_elements", [])
            chars_involved = seg.get("characters_involved", [])
            mood = seg.get("mood", "")

            segment_insights += f"""
SEGMENT "{seg_name}":
- Story: {message}
- Visuals: {visual_summary}
- Mood: {mood}
- Characters: {', '.join(chars_involved) if isinstance(chars_involved, list) else chars_involved}
- Key elements: {', '.join(key_elements) if isinstance(key_elements, list) else key_elements}
"""
            if isinstance(chars_involved, list):
                all_characters_mentioned.update(chars_involved)
            if isinstance(key_elements, list):
                all_key_elements.extend(key_elements)

        # Chỉ dùng TARGETED text từ SRT cho các segment chính (đầu + giữa + cuối)
        # thay vì gửi full text
        targeted_srt_text = ""
        if story_segments and srt_entries:
            # Lấy 3 segments: đầu, giữa, cuối
            target_segments = [story_segments[0]]
            if len(story_segments) > 2:
                target_segments.append(story_segments[len(story_segments)//2])
                target_segments.append(story_segments[-1])
            elif len(story_segments) > 1:
                target_segments.append(story_segments[-1])

            for seg in target_segments:
                srt_start = seg.get("srt_range_start", 1)
                srt_end = seg.get("srt_range_end", min(srt_start + 20, len(srt_entries)))
                # Chỉ lấy 10 entries đầu của mỗi segment
                entries_to_take = min(10, srt_end - srt_start + 1)
                targeted_srt_text += f"\n[From segment '{seg.get('segment_name')}']\n"
                targeted_srt_text += self._get_srt_for_range(srt_entries, srt_start, srt_start + entries_to_take - 1)

        self._log(f"  Using {len(story_segments)} segment insights + targeted SRT (~{len(targeted_srt_text)} chars)")

        # Build prompt - dùng SEGMENT INSIGHTS thay vì full text
        prompt = f"""Based on the story analysis below, identify all characters and create visual descriptions.

STORY CONTEXT (from Step 1):
- Era: {setting.get('era', 'Not specified')}
- Location: {setting.get('location', 'Not specified')}
- Visual style: {context_lock}

CHARACTERS TO LOOK FOR (from Step 1.5 segments):
{', '.join(all_characters_mentioned) if all_characters_mentioned else 'Analyze from story segments below'}

STORY SEGMENTS ANALYSIS (from Step 1.5 - this tells you WHAT happens and WHO is involved):
{segment_insights}

SAMPLE SRT CONTENT (for character dialogue/description details):
{targeted_srt_text[:8000] if targeted_srt_text else 'Use segment analysis above'}

For each character, provide:
1. portrait_prompt: Portrait on pure white background, 85mm lens, front-facing, Caucasian, photorealistic 8K, NO TEXT
2. character_lock: Short 10-15 word description for scene prompts
3. is_minor: true if under 18 (child, teenager, baby, etc.)

Return JSON:
{{
    "characters": [
        {{
            "id": "char_id",
            "name": "Name",
            "role": "protagonist/supporting/narrator",
            "portrait_prompt": "Portrait on pure white background, 85mm lens, [age]-year-old Caucasian [man/woman], [hair], [eyes], [clothing], front-facing neutral expression, photorealistic 8K, no text, no watermark",
            "character_lock": "[age] Caucasian [man/woman], [hair], [eyes], [clothing]",
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
            char_counter = 0  # Đếm để tạo ID đơn giản: nv1, nv2, nv3...

            for char_data in data["characters"]:
                role = char_data.get("role", "supporting").lower()

                # Tạo ID đơn giản và nhất quán
                if role == "narrator" or "narrator" in char_data.get("name", "").lower():
                    char_id = "nvc"  # Narrator luôn là nvc
                else:
                    char_counter += 1
                    char_id = f"nv{char_counter}"  # nv1, nv2, nv3...

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
                self._log(f"  -> [WARN] {minor_count} characters là trẻ em (sẽ KHÔNG tạo ảnh)")
            for c in data["characters"][:3]:
                minor_tag = " [MINOR]" if c.get("is_minor") else ""
                self._log(f"     - {c.get('name', 'N/A')} ({c.get('role', 'N/A')}){minor_tag}")
            if len(data["characters"]) > 3:
                self._log(f"     ... và {len(data['characters']) - 3} characters khác")

            # Update step status with duration
            elapsed = int(time.time() - step_start)
            workbook.update_step_status("step_3", "COMPLETED", len(data['characters']), len(data['characters']),
                f"{elapsed}s - {len(data['characters'])} chars")

            return StepResult("create_characters", StepStatus.COMPLETED, "Success", data)
        except Exception as e:
            self._log(f"  ERROR: Could not save to Excel: {e}", "ERROR")
            elapsed = int(time.time() - step_start)
            workbook.update_step_status("step_3", "ERROR", 0, 0, f"{elapsed}s - {str(e)[:80]}")
            return StepResult("create_characters", StepStatus.FAILED, str(e))

    # =========================================================================
    # STEP 4: TẠO LOCATIONS
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
        import time
        step_start = time.time()

        self._log("\n" + "="*60)
        self._log("[STEP 4/7] Tạo locations...")
        self._log("="*60)

        # Check if already done
        existing_locs = workbook.get_locations()
        if existing_locs and len(existing_locs) > 0:
            self._log(f"  -> Đã có {len(existing_locs)} locations, skip!")
            workbook.update_step_status("step_4", "COMPLETED", len(existing_locs), len(existing_locs), "Already done")
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

        # OPTIMIZED: Tận dụng insights từ Step 1.5 (segments)
        story_segments = workbook.get_story_segments() or []

        # Build rich context từ segments thay vì đọc lại full text
        segment_insights = ""
        all_locations_hints = set()

        for seg in story_segments:
            seg_name = seg.get("segment_name", "")
            message = seg.get("message", "")
            visual_summary = seg.get("visual_summary", "")
            key_elements = seg.get("key_elements", [])
            mood = seg.get("mood", "")

            segment_insights += f"""
SEGMENT "{seg_name}":
- Story: {message}
- Visuals: {visual_summary}
- Mood: {mood}
- Key elements: {', '.join(key_elements) if isinstance(key_elements, list) else key_elements}
"""
            # Extract location hints từ key_elements
            if isinstance(key_elements, list):
                for elem in key_elements:
                    elem_lower = elem.lower()
                    if any(word in elem_lower for word in ["room", "house", "office", "street", "park", "school", "hospital", "forest", "beach", "city", "village", "building", "kitchen", "bedroom", "garden", "car", "restaurant", "cafe", "church"]):
                        all_locations_hints.add(elem)

        # Chỉ lấy targeted SRT từ vài segment để có thêm context
        targeted_srt_text = ""
        if story_segments and srt_entries:
            target_segments = [story_segments[0]]
            if len(story_segments) > 2:
                target_segments.append(story_segments[len(story_segments)//2])
                target_segments.append(story_segments[-1])
            elif len(story_segments) > 1:
                target_segments.append(story_segments[-1])

            for seg in target_segments:
                srt_start = seg.get("srt_range_start", 1)
                entries_to_take = min(8, len(srt_entries) - srt_start + 1)
                targeted_srt_text += f"\n[From segment '{seg.get('segment_name')}']\n"
                targeted_srt_text += self._get_srt_for_range(srt_entries, srt_start, srt_start + entries_to_take - 1)

        self._log(f"  Using {len(story_segments)} segment insights + targeted SRT (~{len(targeted_srt_text)} chars)")

        # Build prompt - dùng SEGMENT INSIGHTS thay vì full text
        prompt = f"""Based on the story analysis below, identify all locations and create visual descriptions.

STORY CONTEXT (from Step 1):
- Era: {setting.get('era', 'Not specified')}
- Location type: {setting.get('location', 'Not specified')}
- Visual style: {context_lock}
- Characters: {', '.join(char_names[:5])}

LOCATION HINTS (from Step 1.5 key_elements):
{', '.join(all_locations_hints) if all_locations_hints else 'Analyze from story segments below'}

STORY SEGMENTS ANALYSIS (from Step 1.5 - shows WHERE scenes take place):
{segment_insights}

SAMPLE SRT CONTENT (for location description details):
{targeted_srt_text[:6000] if targeted_srt_text else 'Use segment analysis above'}

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
            loc_counter = 0  # Đếm để tạo ID đơn giản: loc1, loc2, loc3...

            for loc_data in data["locations"]:
                loc_counter += 1
                loc_id = f"loc{loc_counter}"  # Đơn giản: loc1, loc2, loc3...

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

            # Update step status with duration
            elapsed = int(time.time() - step_start)
            workbook.update_step_status("step_4", "COMPLETED", len(data['locations']), len(data['locations']),
                f"{elapsed}s - {len(data['locations'])} locs")

            return StepResult("create_locations", StepStatus.COMPLETED, "Success", data)
        except Exception as e:
            self._log(f"  ERROR: Could not save to Excel: {e}", "ERROR")
            elapsed = int(time.time() - step_start)
            workbook.update_step_status("step_4", "ERROR", 0, 0, f"{elapsed}s - {str(e)[:80]}")
            return StepResult("create_locations", StepStatus.FAILED, str(e))

    # =========================================================================
    # STEP 5: TẠO DIRECTOR'S PLAN (OPTIMIZED - SEGMENT-FIRST)
    # =========================================================================

    def step_create_director_plan(
        self,
        project_dir: Path,
        code: str,
        workbook: PromptWorkbook,
        srt_entries: list
    ) -> StepResult:
        """
        Step 4: Tạo director's plan - OPTIMIZED với segment-first approach.

        THAY ĐỔI SO VỚI PHIÊN BẢN CŨ:
        - CŨ: Chia SRT theo character count (~6000 chars) → batch processing
        - MỚI: Xử lý BY SEGMENT từ Step 1.5, tận dụng segment insights

        Mỗi segment đã có:
        - message: Nội dung chính của segment
        - visual_summary: Mô tả visual cần show
        - key_elements: Các yếu tố quan trọng
        - mood: Tone cảm xúc
        - characters_involved: Nhân vật xuất hiện
        - image_count: Số scenes cần tạo

        → API chỉ cần quyết định HOW to visualize, không cần re-read toàn bộ story
        """
        # Redirect to basic version which is complete
        return self.step_create_director_plan_basic(project_dir, code, workbook, srt_entries)

    def _process_segment_sub_batch(self, seg_name, message, visual_summary, key_elements,
                                    mood, chars_involved, image_count, srt_start, srt_end,
                                    srt_entries, context_lock, char_locks, loc_locks):
        """Helper: Xử lý sub-batch nhỏ của segment (dùng khi segment quá lớn hoặc retry fail)."""
        import time

        # Lấy SRT text cho sub-batch
        seg_srt_text = self._get_srt_for_range(srt_entries, srt_start, srt_end)

        # Tính duration
        seg_duration = (srt_end - srt_start + 1) * 3  # ~3s per entry

        # Build character/location info
        relevant_chars = []
        if isinstance(chars_involved, list):
            for char_name in chars_involved:
                for cid, clock in char_locks.items():
                    if char_name.lower() in clock.lower() or char_name.lower() in cid.lower():
                        relevant_chars.append(f"- {cid}: {clock}")
                        break
        if not relevant_chars:
            relevant_chars = [f"- {cid}: {clock}" for cid, clock in list(char_locks.items())[:5]]

        relevant_locs = [f"- {lid}: {llock}" for lid, llock in list(loc_locks.items())[:3]]

        # Build prompt
        prompt = f"""Create {image_count} cinematic shots for this story segment.

SEGMENT: "{seg_name}"
Story: {message}
Visuals: {visual_summary}
Mood: {mood}
Key elements: {', '.join(key_elements) if isinstance(key_elements, list) else key_elements}

VISUAL STYLE: {context_lock}

CHARACTERS:
{chr(10).join(relevant_chars) if relevant_chars else 'Use generic descriptions'}

LOCATIONS:
{chr(10).join(relevant_locs) if relevant_locs else 'Use generic descriptions'}

SRT ({srt_end - srt_start + 1} entries):
{seg_srt_text[:3000]}

TASK: Create EXACTLY {image_count} scenes (~{seg_duration/image_count:.1f}s each)

Return JSON only:
{{
    "scenes": [
        {{
            "scene_id": 1,
            "srt_indices": [list of SRT indices],
            "srt_start": "00:00:00,000",
            "srt_end": "00:00:05,000",
            "duration": {seg_duration/image_count:.1f},
            "srt_text": "narration",
            "visual_moment": "specific visual",
            "characters_used": "nv_xxx",
            "location_used": "loc_xxx",
            "camera": "shot type",
            "lighting": "lighting"
        }}
    ]
}}
"""

        # Call API with retry (simpler - 3 retries)
        MAX_RETRIES = 3
        for retry in range(MAX_RETRIES):
            response = self._call_api(prompt, temperature=0.5, max_tokens=4096)
            if response:
                data = self._extract_json(response)
                if data and "scenes" in data:
                    self._log(f"     -> Sub-batch got {len(data['scenes'])} scenes")
                    return data["scenes"]
            time.sleep(2 ** retry)

        # Nếu fail, trả về empty list (không tạo fallback cho sub-batch)
        self._log(f"     -> Sub-batch failed after {MAX_RETRIES} retries", "WARNING")
        return []

        # Execute segments in parallel
        segment_results = {}
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as executor:
            futures = {executor.submit(process_segment, (i, seg)): i for i, seg in enumerate(story_segments)}
            for future in as_completed(futures):
                seg_idx = futures[future]
                try:
                    result_idx, scenes = future.result()
                    segment_results[result_idx] = scenes
                except Exception as e:
                    self._log(f"     -> Segment {seg_idx+1} failed: {e}", "ERROR")
                    segment_results[seg_idx] = []

        # Merge results in order and assign scene_ids
        scene_id_counter = 1
        for seg_idx in range(len(story_segments)):
            seg_scenes = segment_results.get(seg_idx, [])
            for scene in seg_scenes:
                scene["scene_id"] = scene_id_counter
                all_scenes.append(scene)
                scene_id_counter += 1

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

            # TRACKING: Cập nhật và kiểm tra coverage
            coverage = workbook.update_srt_coverage_scenes(all_scenes)
            self._log(f"\n  [STATS] SRT COVERAGE (sau Step 4):")
            self._log(f"     Total SRT: {coverage['total_srt']}")
            self._log(f"     Covered by scenes: {coverage['covered_by_scene']} ({coverage['coverage_percent']}%)")

            total_duration = sum(s.get('duration', 0) for s in all_scenes)

            # Determine status based on coverage
            elapsed = int(time.time() - step_start)
            if coverage['uncovered'] > 0:
                self._log(f"     [WARN] UNCOVERED: {coverage['uncovered']} entries", "WARN")
                uncovered_list = workbook.get_uncovered_srt_entries()
                if uncovered_list:
                    self._log(f"     Missing SRT: {[u['srt_index'] for u in uncovered_list[:10]]}...")
                status = "PARTIAL" if coverage['coverage_percent'] >= 80 else "ERROR"
                workbook.update_step_status("step_5", status,
                    coverage['total_srt'], coverage['covered_by_scene'],
                    f"{elapsed}s - {len(all_scenes)} scenes, {coverage['uncovered']} uncovered")
            else:
                workbook.update_step_status("step_5", "COMPLETED",
                    coverage['total_srt'], coverage['covered_by_scene'],
                    f"{elapsed}s - {len(all_scenes)} scenes, {total_duration:.0f}s")

            return StepResult("create_director_plan", StepStatus.COMPLETED, "Success", {"scenes": all_scenes})
        except Exception as e:
            self._log(f"  ERROR: Could not save to Excel: {e}", "ERROR")
            elapsed = int(time.time() - step_start)
            workbook.update_step_status("step_5", "ERROR", 0, 0, f"{elapsed}s - {str(e)[:80]}")
            return StepResult("create_director_plan", StepStatus.FAILED, str(e))

    def _step_create_director_plan_legacy(
        self,
        project_dir: Path,
        code: str,
        workbook: PromptWorkbook,
        srt_entries: list
    ) -> StepResult:
        """
        Legacy fallback: Xử lý SRT theo character-batch khi không có segments.
        Chỉ dùng khi Step 1.5 chưa chạy.
        """
        self._log("  Using legacy character-batch mode...")

        story_analysis = workbook.get_story_analysis() or {}
        characters = workbook.get_characters()
        locations = workbook.get_locations()
        context_lock = story_analysis.get("context_lock", "")

        char_locks = [f"- {c.id}: {c.character_lock}" for c in characters if c.character_lock]
        loc_locks = [f"- {loc.id}: {loc.location_lock}" for loc in locations if hasattr(loc, 'location_lock') and loc.location_lock]

        # Build valid ID sets for normalization
        valid_char_ids = {c.id for c in characters}
        valid_loc_ids = {loc.id for loc in locations}

        # Chia SRT entries thành batches ~6000 chars
        MAX_BATCH_CHARS = 6000
        batches = []
        current_batch = []
        current_chars = 0

        for i, entry in enumerate(srt_entries):
            entry_text = f"[{i+1}] {entry.start_time} --> {entry.end_time}\n{entry.text}\n\n"
            entry_len = len(entry_text)

            if current_chars + entry_len > MAX_BATCH_CHARS and current_batch:
                batches.append(current_batch)
                current_batch = []
                current_chars = 0

            current_batch.append((i, entry))
            current_chars += entry_len

        if current_batch:
            batches.append(current_batch)

        all_scenes = []
        scene_id_counter = 1

        for batch_idx, batch_entries in enumerate(batches):
            batch_start = batch_entries[0][0]
            batch_end = batch_entries[-1][0]

            srt_text = ""
            for idx, entry in batch_entries:
                srt_text += f"[{idx+1}] {entry.start_time} --> {entry.end_time}\n{entry.text}\n\n"

            prompt = f"""Create cinematic shots for this content.

CONTEXT: {context_lock}

CHARACTERS:
{chr(10).join(char_locks[:5]) if char_locks else 'Generic'}

LOCATIONS:
{chr(10).join(loc_locks[:3]) if loc_locks else 'Generic'}

SRT (entries {batch_start+1}-{batch_end+1}):
{srt_text}

Create scenes (~8s each). Return JSON:
{{"scenes": [{{"scene_id": {scene_id_counter}, "srt_indices": [], "srt_start": "", "srt_end": "", "duration": 8, "srt_text": "", "visual_moment": "", "characters_used": "", "location_used": "", "camera": "", "lighting": ""}}]}}
"""

            response = self._call_api(prompt, temperature=0.5, max_tokens=4096)
            data = self._extract_json(response) if response else None

            if data and "scenes" in data:
                for scene in data["scenes"]:
                    scene["scene_id"] = scene_id_counter

                    # Normalize IDs từ API response
                    raw_chars = scene.get("characters_used", "")
                    raw_loc = scene.get("location_used", "")
                    scene["characters_used"] = self._normalize_character_ids(raw_chars, valid_char_ids)
                    scene["location_used"] = self._normalize_location_id(raw_loc, valid_loc_ids)

                    all_scenes.append(scene)
                    scene_id_counter += 1

        if not all_scenes:
            return StepResult("create_director_plan", StepStatus.FAILED, "No scenes created")

        workbook.save_director_plan(all_scenes)
        workbook.save()
        return StepResult("create_director_plan", StepStatus.COMPLETED, "Success (legacy)", {"scenes": all_scenes})

    # =========================================================================
    # STEP 5 BASIC: TẠO DIRECTOR'S PLAN (SEGMENT-BASED, NO 8s LIMIT)
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
        self._log("[STEP 5/7] Creating director's plan (segment-based)...")
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

        # Build character/location info + valid ID sets for normalization
        char_locks = []
        valid_char_ids = set()  # Để normalize IDs từ API response
        for c in characters:
            valid_char_ids.add(c.id)
            if c.character_lock:
                char_locks.append(f"- {c.id}: {c.character_lock}")

        loc_locks = []
        valid_loc_ids = set()  # Để normalize IDs từ API response
        for loc in locations:
            valid_loc_ids.add(loc.id)
            if hasattr(loc, 'location_lock') and loc.location_lock:
                loc_locks.append(f"- {loc.id}: {loc.location_lock}")

        self._log(f"  Valid char IDs: {valid_char_ids}")
        self._log(f"  Valid loc IDs: {valid_loc_ids}")

        # Process segments in PARALLEL
        all_scenes = []
        total_entries = len(srt_entries)
        MAX_PARALLEL = self.config.get("max_parallel_api", 6)

        self._log(f"  Processing {len(story_segments)} segments in parallel (max {MAX_PARALLEL} concurrent)...")

        # HELPER: Process single segment - returns (seg_idx, scenes_list, actual_image_count)
        def process_segment_basic(seg_idx_seg):
            seg_idx, seg = seg_idx_seg
            local_scenes = []

            seg_id = seg.get("segment_id", seg_idx + 1)
            seg_name = seg.get("segment_name", "")
            image_count = seg.get("image_count", 1)
            srt_start = seg.get("srt_range_start", 1)
            srt_end = seg.get("srt_range_end", total_entries)
            message = seg.get("message", "")

            self._log(f"  Segment {seg_id}/{len(story_segments)}: {seg_name} ({image_count} images, SRT {srt_start}-{srt_end})")

            # Get SRT entries for this segment
            seg_entries = [e for i, e in enumerate(srt_entries, 1) if srt_start <= i <= srt_end]

            if not seg_entries:
                self._log(f"     -> No SRT entries for this segment, skip")
                return (seg_idx, [], 0)

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

            # SEGMENT 1 SPECIAL: Tuân thủ 8s limit
            if seg_id == 1:
                original_image_count = image_count
                image_count = max(1, int(seg_duration / 8) + 1)
                self._log(f"     -> Segment 1 special: {original_image_count} planned -> {image_count} scenes (8s limit)")

            # Calculate duration per scene
            scene_duration = seg_duration / image_count if image_count > 0 else seg_duration
            entries_per_scene = len(seg_entries) / image_count if image_count > 0 else len(seg_entries)

            # Build SRT text for API prompt
            srt_text = ""
            for i, entry in enumerate(seg_entries):
                idx = srt_start + i
                srt_text += f"[{idx}] {entry.start_time} --> {entry.end_time}\n{entry.text}\n\n"

            # Call API to create scenes (scene_id will be assigned after merge)
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
6. scene_id: just use 1, 2, 3... (will be renumbered later)

Return JSON only:
{{
    "scenes": [
        {{
            "scene_id": 1,
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
                if response:
                    data = self._extract_json(response)
                    if data and "scenes" in data:
                        break
                time.sleep(2 ** retry)

            # If all retries failed, create fallback scenes
            if not data or "scenes" not in data:
                self._log(f"     -> All retries failed, creating {image_count} fallback scenes", "WARNING")
                for i in range(image_count):
                    start_idx = int(i * entries_per_scene)
                    end_idx = min(int((i + 1) * entries_per_scene), len(seg_entries))
                    scene_ents = seg_entries[start_idx:end_idx] if seg_entries else []

                    fallback_scene = {
                        "scene_id": 0,  # Will be assigned after merge
                        "srt_indices": list(range(srt_start + start_idx, srt_start + end_idx)),
                        "srt_start": scene_ents[0].start_time if scene_ents else "",
                        "srt_end": scene_ents[-1].end_time if scene_ents else "",
                        "duration": scene_duration,
                        "srt_text": " ".join([e.text for e in scene_ents]) if scene_ents else "",
                        "visual_moment": f"[Auto] Scene {i+1}/{image_count} from: {seg_name}",
                        "characters_used": "",
                        "location_used": "",
                        "camera": "Medium shot",
                        "lighting": "Natural lighting"
                    }
                    local_scenes.append(fallback_scene)
                return (seg_idx, local_scenes, image_count)

            # Process API response
            api_scenes = data["scenes"]
            self._log(f"     -> Got {len(api_scenes)} scenes from API")

            # Ensure correct scene count - add missing if needed
            if len(api_scenes) < image_count:
                self._log(f"     -> Warning: Expected {image_count}, got {len(api_scenes)} - ADDING MISSING")
                existing_srt_indices = set()
                for s in api_scenes:
                    indices = s.get("srt_indices", [])
                    if isinstance(indices, list):
                        existing_srt_indices.update(indices)

                all_seg_indices = list(range(srt_start, srt_end + 1))
                missing_indices = [i for i in all_seg_indices if i not in existing_srt_indices]

                scenes_needed = image_count - len(api_scenes)
                if missing_indices and scenes_needed > 0:
                    indices_per_scene_fill = max(1, len(missing_indices) // scenes_needed)
                    for i in range(scenes_needed):
                        start_i = i * indices_per_scene_fill
                        end_i = min((i + 1) * indices_per_scene_fill, len(missing_indices))
                        scene_indices = missing_indices[start_i:end_i]
                        if not scene_indices:
                            continue
                        scene_ents = [e for idx, e in enumerate(srt_entries, 1) if idx in scene_indices]
                        fill_scene = {
                            "scene_id": 0,
                            "srt_indices": scene_indices,
                            "srt_start": scene_ents[0].start_time if scene_ents else "",
                            "srt_end": scene_ents[-1].end_time if scene_ents else "",
                            "duration": scene_duration,
                            "srt_text": " ".join([e.text for e in scene_ents]) if scene_ents else "",
                            "visual_moment": f"[Auto-fill] Scene covering SRT {scene_indices[0]}-{scene_indices[-1]}",
                            "characters_used": "",
                            "location_used": "",
                            "camera": "Medium shot",
                            "lighting": "Natural lighting"
                        }
                        api_scenes.append(fill_scene)
                    self._log(f"     -> Added {scenes_needed} auto-fill scenes, total: {len(api_scenes)}")

            local_scenes.extend(api_scenes)
            return (seg_idx, local_scenes, image_count)

        # Execute segments in parallel
        segment_results = {}
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as executor:
            futures = {executor.submit(process_segment_basic, (i, seg)): i for i, seg in enumerate(story_segments)}
            for future in as_completed(futures):
                seg_idx = futures[future]
                try:
                    result_idx, scenes, _ = future.result()
                    segment_results[result_idx] = scenes
                except Exception as e:
                    self._log(f"     -> Segment {seg_idx+1} failed: {e}", "ERROR")
                    segment_results[seg_idx] = []

        # Merge results in order and assign scene_ids
        scene_id_counter = 1
        for seg_idx in range(len(story_segments)):
            seg_scenes = segment_results.get(seg_idx, [])
            for scene in seg_scenes:
                scene["scene_id"] = scene_id_counter
                # Normalize IDs
                raw_chars = scene.get("characters_used", "")
                raw_loc = scene.get("location_used", "")
                scene["characters_used"] = self._normalize_character_ids(raw_chars, valid_char_ids)
                scene["location_used"] = self._normalize_location_id(raw_loc, valid_loc_ids)
                all_scenes.append(scene)
                scene_id_counter += 1

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

            # TRACKING: Cập nhật và kiểm tra coverage
            coverage = workbook.update_srt_coverage_scenes(all_scenes)
            self._log(f"\n  [STATS] SRT COVERAGE (sau Step 4 BASIC):")
            self._log(f"     Total SRT: {coverage['total_srt']}")
            self._log(f"     Covered by scenes: {coverage['covered_by_scene']} ({coverage['coverage_percent']}%)")
            if coverage['uncovered'] > 0:
                self._log(f"     [WARN] UNCOVERED: {coverage['uncovered']} entries", "WARN")
                uncovered_list = workbook.get_uncovered_srt_entries()
                if uncovered_list:
                    self._log(f"     Missing SRT: {[u['srt_index'] for u in uncovered_list[:10]]}...")

            return StepResult("create_director_plan_basic", StepStatus.COMPLETED, "Success", {"scenes": all_scenes})
        except Exception as e:
            self._log(f"  ERROR: Could not save to Excel: {e}", "ERROR")
            return StepResult("create_director_plan_basic", StepStatus.FAILED, str(e))

    # =========================================================================
    # STEP 6: LÊN KẾ HOẠCH CHI TIẾT TỪNG SCENE
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
        import time
        step_start = time.time()

        self._log("\n" + "="*60)
        self._log("[STEP 6/7] Lên kế hoạch chi tiết từng scene...")
        self._log("="*60)

        # Check if already done
        try:
            existing = workbook.get_scene_planning()
            if existing and len(existing) > 0:
                self._log(f"  -> Đã có {len(existing)} scene plans, skip!")
                workbook.update_step_status("step_6", "COMPLETED", len(existing), len(existing), "Already done")
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

            # Update step status with duration
            elapsed = int(time.time() - step_start)
            workbook.update_step_status("step_6", "COMPLETED", len(all_plans), len(all_plans),
                f"{elapsed}s - {len(all_plans)} plans")

            return StepResult("plan_scenes", StepStatus.COMPLETED, "Success", {"plans": all_plans})
        except Exception as e:
            self._log(f"  ERROR: Could not save: {e}", "ERROR")
            elapsed = int(time.time() - step_start)
            workbook.update_step_status("step_6", "ERROR", 0, 0, f"{elapsed}s - {str(e)[:80]}")
            return StepResult("plan_scenes", StepStatus.FAILED, str(e))

    # =========================================================================
    # STEP 7: TẠO SCENE PROMPTS (BATCH)
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
        import time
        step_start = time.time()

        self._log("\n" + "="*60)
        self._log("[STEP 7/7] Tạo scene prompts...")
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
            workbook.update_step_status("step_7", "COMPLETED", len(existing_scenes), len(existing_scenes), "Already done")
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

            # Validate và tạo fallback cho scenes thiếu
            if len(api_scenes) < len(batch):
                self._log(f"  [WARN] Batch {batch_num}: API returned {len(api_scenes)}, expected {len(batch)} - ADDING MISSING")

                # Tìm scene_ids đã có từ API
                api_scene_ids = {int(s.get("scene_id", 0)) for s in api_scenes}

                # Tạo fallback cho scenes thiếu
                for original in batch:
                    orig_id = int(original.get("scene_id", 0))
                    if orig_id not in api_scene_ids:
                        # Tạo fallback prompt
                        srt_text = original.get("srt_text", "")
                        visual_moment = original.get("visual_moment", "")
                        chars_used = original.get("characters_used") or ""
                        loc_used = original.get("location_used") or ""

                        fallback_prompt = f"Cinematic scene: {visual_moment or srt_text[:200]}. "
                        fallback_prompt += "4K photorealistic, dramatic lighting, film quality."

                        # Thêm character/location annotations
                        if chars_used:
                            for cid in chars_used.split(","):
                                cid = cid.strip()
                                if cid:
                                    img = char_image_lookup.get(cid, f"{cid}.png")
                                    fallback_prompt += f" ({img})"
                        if loc_used:
                            img = loc_image_lookup.get(loc_used, f"{loc_used}.png")
                            fallback_prompt += f" (reference: {img})"

                        fallback_scene = {
                            "scene_id": orig_id,
                            "img_prompt": fallback_prompt,
                            "video_prompt": f"Smooth camera movement: {visual_moment or srt_text[:100]}"
                        }
                        api_scenes.append(fallback_scene)
                        self._log(f"     -> Created fallback for scene {orig_id}")

            # Check duplicates - chỉ skip nếu >80% trùng lặp
            seen_prompts = set()
            duplicate_count = 0
            for s in api_scenes:
                prompt_key = s.get("img_prompt", "")[:100]
                if prompt_key in seen_prompts:
                    duplicate_count += 1
                else:
                    seen_prompts.add(prompt_key)

            if len(api_scenes) > 0 and duplicate_count > len(api_scenes) * 0.8:
                self._log(f"  Batch {batch_num}: >80% duplicates ({duplicate_count}/{len(api_scenes)}), skipped!", "ERROR")
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
                    char_ids = [cid.strip() for cid in (original.get("characters_used") or "").split(",") if cid.strip()]
                    loc_id = original.get("location_used") or ""

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

        elapsed = int(time.time() - step_start)
        if total_created > 0:
            # Update step status with duration
            workbook.update_step_status("step_7", "COMPLETED", total_created, total_created,
                f"{elapsed}s - {total_created} prompts")
            return StepResult("create_scene_prompts", StepStatus.COMPLETED, f"Created {total_created} scenes")
        else:
            workbook.update_step_status("step_7", "ERROR", 0, 0, f"{elapsed}s - No scenes created")
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
