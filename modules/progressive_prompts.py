"""
VE3 Tool - Progressive Prompts Generator
=========================================
Tạo prompts theo từng step, mỗi step lưu vào Excel ngay.
API có thể đọc context từ Excel để học từ những gì đã làm.

Flow:
    Step 1: Phân tích story → Excel (story_analysis)
    Step 2: Tạo characters → Excel (characters)
    Step 3: Tạo locations → Excel (locations)
    Step 4: Tạo director_plan → Excel (director_plan)
    Step 5-N: Tạo scenes (từng batch) → Excel (scenes)

Lợi ích:
    - Fail recovery: Resume từ step bị fail
    - Debug: Xem Excel biết step nào sai
    - Kiểm soát: Có thể sửa Excel giữa chừng
    - Chất lượng: API đọc context từ Excel
"""

import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Callable
from dataclasses import dataclass
from enum import Enum

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

Return JSON only:
{{
    "characters": [
        {{
            "id": "char_id",
            "name": "Character Name",
            "role": "protagonist/antagonist/supporting/narrator",
            "portrait_prompt": "detailed portrait description for image generation, white background",
            "character_lock": "short description for scene prompts (10-15 words)",
            "vietnamese_description": "Mô tả tiếng Việt"
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
            for char_data in data["characters"]:
                char = Character(
                    id=char_data.get("id", ""),
                    name=char_data.get("name", ""),
                    role=char_data.get("role", "supporting"),
                    english_prompt=char_data.get("portrait_prompt", ""),
                    character_lock=char_data.get("character_lock", ""),
                    vietnamese_prompt=char_data.get("vietnamese_description", ""),
                )
                workbook.add_character(char)

            workbook.save()
            self._log(f"  -> Saved {len(data['characters'])} characters to Excel")
            for c in data["characters"][:3]:
                self._log(f"     - {c.get('name', 'N/A')} ({c.get('role', 'N/A')})")
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

        # Save to Excel
        try:
            for loc_data in data["locations"]:
                loc = Location(
                    id=loc_data.get("id", ""),
                    name=loc_data.get("name", ""),
                    english_prompt=loc_data.get("location_prompt", ""),
                    location_lock=loc_data.get("location_lock", ""),
                    lighting_default=loc_data.get("lighting_default", ""),
                )
                workbook.add_location(loc)

            workbook.save()
            self._log(f"  -> Saved {len(data['locations'])} locations to Excel")
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

        context_lock = story_analysis.get("context_lock", "")

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

        # Format SRT entries
        srt_text = ""
        for i, entry in enumerate(srt_entries):
            srt_text += f"[{i+1}] {entry.start} --> {entry.end}\n{entry.text}\n\n"

        # Build prompt
        prompt = f"""Create a director's shooting plan by dividing the SRT into visual scenes.

VISUAL CONTEXT:
{context_lock}

CHARACTERS (use these exact descriptions in scenes):
{chr(10).join(char_locks) if char_locks else 'No characters defined'}

LOCATIONS (use these exact descriptions in scenes):
{chr(10).join(loc_locks) if loc_locks else 'No locations defined'}

SRT ENTRIES:
{srt_text[:12000]}

Rules:
1. Each scene should be 3-8 seconds
2. Group SRT entries that belong to the same visual moment
3. Assign appropriate characters and locations to each scene
4. Create a visual_moment description (what the viewer sees)

Return JSON only:
{{
    "scenes": [
        {{
            "scene_id": 1,
            "srt_indices": [1, 2],
            "srt_start": "00:00:00,000",
            "srt_end": "00:00:05,000",
            "duration": 5.0,
            "srt_text": "combined text from SRT entries",
            "visual_moment": "what the viewer sees in this scene",
            "characters_used": "char_id1, char_id2",
            "location_used": "loc_id",
            "camera": "shot type and movement",
            "lighting": "lighting description"
        }}
    ]
}}
"""

        # Call API
        response = self._call_api(prompt, temperature=0.5, max_tokens=8192)
        if not response:
            self._log("  ERROR: API call failed!", "ERROR")
            return StepResult("create_director_plan", StepStatus.FAILED, "API call failed")

        # Parse response
        data = self._extract_json(response)
        if not data or "scenes" not in data:
            self._log("  ERROR: Could not parse director plan!", "ERROR")
            return StepResult("create_director_plan", StepStatus.FAILED, "JSON parse failed")

        # Save to Excel
        try:
            workbook.save_director_plan(data["scenes"])
            workbook.save()
            self._log(f"  -> Saved {len(data['scenes'])} scenes to director_plan")
            self._log(f"     Total duration: {sum(s.get('duration', 0) for s in data['scenes']):.1f}s")

            return StepResult("create_director_plan", StepStatus.COMPLETED, "Success", data)
        except Exception as e:
            self._log(f"  ERROR: Could not save to Excel: {e}", "ERROR")
            return StepResult("create_director_plan", StepStatus.FAILED, str(e))

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

        context_lock = story_analysis.get("context_lock", "")

        # Build character/location lookup
        char_lookup = {c.id: c.character_lock for c in characters if c.character_lock}
        loc_lookup = {}
        for loc in locations:
            if hasattr(loc, 'location_lock') and loc.location_lock:
                loc_lookup[loc.id] = loc.location_lock

        # Process in batches
        total_created = 0

        for batch_start in range(0, len(pending_scenes), batch_size):
            batch = pending_scenes[batch_start:batch_start + batch_size]
            batch_num = batch_start // batch_size + 1

            self._log(f"\n  [Batch {batch_num}] Processing {len(batch)} scenes...")

            # Build batch prompt
            scenes_text = ""
            for scene in batch:
                # Get character/location locks
                char_ids = scene.get("characters_used", "").split(", ")
                char_desc = ", ".join([char_lookup.get(cid, cid) for cid in char_ids if cid])

                loc_id = scene.get("location_used", "")
                loc_desc = loc_lookup.get(loc_id, loc_id)

                scenes_text += f"""
Scene {scene.get('scene_id')}:
- Time: {scene.get('srt_start')} --> {scene.get('srt_end')}
- Text: {scene.get('srt_text', '')}
- Visual moment: {scene.get('visual_moment', '')}
- Characters: {char_desc}
- Location: {loc_desc}
- Camera: {scene.get('camera', '')}
- Lighting: {scene.get('lighting', '')}
"""

            prompt = f"""Create detailed image prompts for these scenes.

VISUAL CONTEXT (use as prefix):
{context_lock}

SCENES TO PROCESS:
{scenes_text}

For each scene, create:
1. img_prompt: Detailed image generation prompt (include context_lock, character descriptions, location, camera, lighting)
2. video_prompt: Motion/video prompt if this becomes a video clip

Return JSON only:
{{
    "scenes": [
        {{
            "scene_id": 1,
            "img_prompt": "detailed image prompt...",
            "video_prompt": "camera movement and action description..."
        }}
    ]
}}
"""

            # Call API
            response = self._call_api(prompt, temperature=0.7, max_tokens=8192)
            if not response:
                self._log(f"  ERROR: API call failed for batch {batch_num}!", "ERROR")
                continue

            # Parse response
            data = self._extract_json(response)
            if not data or "scenes" not in data:
                self._log(f"  ERROR: Could not parse batch {batch_num}!", "ERROR")
                continue

            # Save scenes to Excel
            try:
                for scene_data in data["scenes"]:
                    scene_id = scene_data.get("scene_id")

                    # Find original scene from director plan
                    original = next((s for s in batch if s.get("scene_id") == scene_id), None)
                    if not original:
                        continue

                    scene = Scene(
                        scene_id=scene_id,
                        srt_start=original.get("srt_start", ""),
                        srt_end=original.get("srt_end", ""),
                        duration=original.get("duration", 0),
                        srt_text=original.get("srt_text", ""),
                        img_prompt=scene_data.get("img_prompt", ""),
                        video_prompt=scene_data.get("video_prompt", ""),
                        characters_used=original.get("characters_used", ""),
                        location_used=original.get("location_used", ""),
                        status_img="pending",
                        status_vid="pending"
                    )
                    workbook.add_scene(scene)
                    total_created += 1

                workbook.save()
                self._log(f"  -> Saved batch {batch_num} ({len(data['scenes'])} scenes)")

            except Exception as e:
                self._log(f"  ERROR: Could not save batch {batch_num}: {e}", "ERROR")
                continue

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

        # Step 4: Create director plan
        result = self.step_create_director_plan(project_dir, code, workbook, srt_entries)
        if result.status == StepStatus.FAILED:
            self._log("Step 4 FAILED! Stopping.", "ERROR")
            return False

        # Step 5: Create scene prompts
        result = self.step_create_scene_prompts(project_dir, code, workbook)
        if result.status == StepStatus.FAILED:
            self._log("Step 5 FAILED!", "ERROR")
            return False

        self._log("\n" + "="*70)
        self._log("  ALL STEPS COMPLETED!")
        self._log("="*70)

        return True
