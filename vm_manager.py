#!/usr/bin/env python3
"""
VM Manager - AI Agent Orchestrator với Dashboard
=================================================

Hệ thống AI Agent điều phối công việc với giao diện quản lý:
1. Dashboard hiển thị trạng thái toàn bộ hệ thống
2. Quản lý settings (Chrome count, IPv6, Excel mode...)
3. Giám sát và debug lỗi dễ dàng

Usage:
    python vm_manager.py                  # 2 Chrome workers
    python vm_manager.py --chrome 5       # 5 Chrome workers
"""

import subprocess
import sys
import os

# Fix Windows encoding issues
if sys.platform == "win32":
    if sys.stdout:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if sys.stderr:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    os.environ['PYTHONIOENCODING'] = 'utf-8'
import time
import json
import threading
import shutil
import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List, Set, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
import re

# Import Agent Protocol for worker monitoring
try:
    from modules.agent_protocol import AgentManager as AgentProtocolManager, WorkerStatus as AgentWorkerStatus
    AGENT_PROTOCOL_ENABLED = True
except ImportError:
    AGENT_PROTOCOL_ENABLED = False

# Import IPv6 Manager for rotation
try:
    from modules.ipv6_manager import get_ipv6_manager
    IPV6_MANAGER_ENABLED = True
except ImportError:
    IPV6_MANAGER_ENABLED = False

TOOL_DIR = Path(__file__).parent
AGENT_DIR = TOOL_DIR / ".agent"
TASKS_DIR = AGENT_DIR / "tasks"
RESULTS_DIR = AGENT_DIR / "results"
STATUS_DIR = AGENT_DIR / "status"
LOGS_DIR = AGENT_DIR / "logs"
CONFIG_FILE = TOOL_DIR / "config" / "settings.yaml"

# ================================================================================
# ENUMS & DATA STRUCTURES
# ================================================================================

class TaskType(Enum):
    EXCEL = "excel"
    IMAGE = "image"
    VIDEO = "video"


class TaskStatus(Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"


class WorkerStatus(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    IDLE = "idle"
    WORKING = "working"
    ERROR = "error"


class QualityStatus(Enum):
    PASS = "pass"
    FAIL = "fail"
    PARTIAL = "partial"


@dataclass
class Task:
    task_id: str
    task_type: TaskType
    project_code: str
    scenes: List[int] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    assigned_to: Optional[str] = None
    created_at: str = ""
    assigned_at: str = ""
    completed_at: str = ""
    result: Dict = field(default_factory=dict)
    error: str = ""
    retry_count: int = 0
    max_retries: int = 3

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['task_type'] = self.task_type.value
        d['status'] = self.status.value
        return d


@dataclass
class WorkerInfo:
    worker_id: str
    worker_type: str
    worker_num: int = 0
    process: Optional[subprocess.Popen] = None
    status: WorkerStatus = WorkerStatus.STOPPED
    current_task: Optional[str] = None
    start_time: Optional[datetime] = None
    completed_tasks: int = 0
    failed_tasks: int = 0
    last_error: str = ""
    last_restart_time: Optional[datetime] = None  # Để track restart cooldown
    restart_count: int = 0  # Số lần restart trong session


@dataclass
class ProjectStatus:
    """Trạng thái chi tiết của một project."""
    code: str
    srt_exists: bool = False
    excel_exists: bool = False
    excel_status: str = ""  # "none", "fallback", "partial", "complete"
    total_scenes: int = 0
    prompts_count: int = 0
    fallback_prompts: int = 0

    # Chi tiết Excel validation
    srt_scene_count: int = 0  # Số scene trong SRT
    excel_scene_count: int = 0  # Số scene trong Excel
    scenes_mismatch: bool = False  # SRT != Excel

    # Các loại prompts
    img_prompts_count: int = 0  # Số scene có img_prompt
    video_prompts_count: int = 0  # Số scene có video_prompt
    missing_img_prompts: List[int] = field(default_factory=list)  # Scenes thiếu img_prompt
    missing_video_prompts: List[int] = field(default_factory=list)  # Scenes thiếu video_prompt

    # Chi tiết fallback
    fallback_scenes: List[int] = field(default_factory=list)  # Scenes có [FALLBACK]

    # Characters & References (pre-Excel steps)
    characters_count: int = 0  # Số nhân vật trong Excel
    characters_with_ref: int = 0  # Số nhân vật có ảnh tham chiếu trong nv/
    characters_missing_ref: List[str] = field(default_factory=list)  # IDs nhân vật thiếu ảnh
    nv_images_count: int = 0  # Tổng số ảnh trong nv/ folder

    # Pre-Excel workflow steps
    step_srt: str = "pending"  # pending/done/error
    step_characters: str = "pending"  # pending/partial/done
    step_prompts: str = "pending"  # pending/partial/done

    # Video mode & Segment 1 (for BASIC mode)
    video_mode: str = "full"  # "basic" or "full"
    segment1_scenes: List[int] = field(default_factory=list)  # Scene IDs in Segment 1
    segment1_end_srt: int = 0  # Last SRT entry of Segment 1

    # Images & Videos
    images_done: int = 0
    images_missing: List[int] = field(default_factory=list)
    videos_done: int = 0
    videos_missing: List[int] = field(default_factory=list)
    # Videos needed based on mode (basic = only Segment 1, full = all)
    videos_needed: List[int] = field(default_factory=list)
    current_step: str = ""  # "excel", "image", "video", "done"
    errors: List[str] = field(default_factory=list)


# ================================================================================
# SETTINGS MANAGER
# ================================================================================

class SettingsManager:
    """Quản lý settings của hệ thống."""

    def __init__(self):
        self.config = self._load_config()

    def _load_config(self) -> Dict:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        return {}

    def save_config(self):
        print(f"[DEBUG] Saving config to {CONFIG_FILE}")
        print(f"[DEBUG] video_mode = {self.config.get('video_mode', 'NOT SET')}")
        print(f"[DEBUG] excel_mode = {self.config.get('excel_mode', 'NOT SET')}")
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(self.config, f, default_flow_style=False, allow_unicode=True)
        print(f"[DEBUG] Config saved!")

    # Chrome settings
    @property
    def chrome_count(self) -> int:
        parallel = self.config.get('parallel_chrome', '1/2')
        if '/' in str(parallel):
            return int(str(parallel).split('/')[1])
        return int(parallel) if parallel else 2

    @chrome_count.setter
    def chrome_count(self, value: int):
        current = self.config.get('parallel_chrome', '1/2')
        if '/' in str(current):
            worker_num = str(current).split('/')[0]
            self.config['parallel_chrome'] = f"{worker_num}/{value}"
        else:
            self.config['parallel_chrome'] = value
        self.save_config()

    # Excel mode
    @property
    def excel_mode(self) -> str:
        return self.config.get('excel_mode', 'full')  # "full" or "basic"

    @excel_mode.setter
    def excel_mode(self, value: str):
        self.config['excel_mode'] = value
        self.save_config()

    @property
    def video_mode(self) -> str:
        return self.config.get('video_mode', 'full')  # "full" or "basic"

    @video_mode.setter
    def video_mode(self, value: str):
        # Normalize value (remove "(8s)" suffix if present)
        if "basic" in value.lower():
            value = "basic"
        else:
            value = "full"
        self.config['video_mode'] = value
        self.save_config()

    # IPv6 settings
    @property
    def ipv6_enabled(self) -> bool:
        return bool(self.config.get('ipv6_rotation', {}).get('enabled', False))

    @property
    def ipv6_list(self) -> List[str]:
        return self.config.get('ipv6_rotation', {}).get('ips', [])

    @property
    def ipv6_rotate_on_error(self) -> bool:
        return self.config.get('ipv6_rotation', {}).get('rotate_on_403', True)

    # API keys
    @property
    def has_deepseek_key(self) -> bool:
        return bool(self.config.get('deepseek_api_key'))

    @property
    def has_groq_keys(self) -> bool:
        return bool(self.config.get('groq_api_keys'))

    @property
    def has_gemini_keys(self) -> bool:
        return bool(self.config.get('gemini_api_keys'))

    def get_summary(self) -> Dict:
        return {
            'chrome_count': self.chrome_count,
            'excel_mode': self.excel_mode,
            'ipv6_enabled': self.ipv6_enabled,
            'ipv6_count': len(self.ipv6_list),
            'ipv6_rotate_on_error': self.ipv6_rotate_on_error,
            'api_keys': {
                'deepseek': self.has_deepseek_key,
                'groq': self.has_groq_keys,
                'gemini': self.has_gemini_keys,
            }
        }


# ================================================================================
# QUALITY CHECKER
# ================================================================================

class QualityChecker:
    """Kiểm tra chất lượng kết quả."""

    def __init__(self, projects_dir: Path):
        self.projects_dir = projects_dir

    def get_project_status(self, project_code: str) -> ProjectStatus:
        """Lấy trạng thái chi tiết của project."""
        status = ProjectStatus(code=project_code)
        project_dir = self.projects_dir / project_code

        # Check SRT và đếm số scene từ SRT
        srt_path = project_dir / f"{project_code}.srt"
        status.srt_exists = srt_path.exists()

        if status.srt_exists:
            try:
                # Đếm số scene trong SRT (mỗi subtitle block = 1 scene)
                with open(srt_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Đếm số block (mỗi block bắt đầu bằng số)
                    import re
                    blocks = re.findall(r'^\d+\s*$', content, re.MULTILINE)
                    status.srt_scene_count = len(blocks)
            except:
                pass

        # Check Excel
        excel_path = project_dir / f"{project_code}_prompts.xlsx"
        status.excel_exists = excel_path.exists()

        if not status.excel_exists:
            status.excel_status = "none"
            status.current_step = "excel"
            return status

        try:
            from modules.excel_manager import PromptWorkbook
            wb = PromptWorkbook(str(excel_path))
            scenes = wb.get_scenes()

            status.total_scenes = len(scenes)
            status.excel_scene_count = len(scenes)

            # Kiểm tra số scene khớp với SRT
            if status.srt_scene_count > 0 and status.srt_scene_count != status.excel_scene_count:
                status.scenes_mismatch = True

            # Chi tiết từng loại prompt
            for scene in scenes:
                scene_num = scene.scene_number

                # Check img_prompt
                if scene.img_prompt and scene.img_prompt.strip():
                    status.img_prompts_count += 1
                    # Check fallback
                    if "[FALLBACK]" in scene.img_prompt:
                        status.fallback_prompts += 1
                        status.fallback_scenes.append(scene_num)
                else:
                    status.missing_img_prompts.append(scene_num)

                # Check video_prompt
                if scene.video_prompt and scene.video_prompt.strip():
                    status.video_prompts_count += 1
                else:
                    status.missing_video_prompts.append(scene_num)

            status.prompts_count = status.img_prompts_count

            # Check characters from Excel
            try:
                characters = wb.get_characters()
                status.characters_count = len(characters)

                # Check nv/ folder for reference images
                nv_dir = project_dir / "nv"
                if nv_dir.exists():
                    nv_images = list(nv_dir.glob("*.png")) + list(nv_dir.glob("*.jpg")) + list(nv_dir.glob("*.jpeg"))
                    status.nv_images_count = len(nv_images)
                    nv_image_names = {img.stem.lower() for img in nv_images}

                    # Check which characters have reference images
                    for char in characters:
                        char_id = char.id.lower() if char.id else ""
                        if char_id in nv_image_names:
                            status.characters_with_ref += 1
                        elif char.image_file and (nv_dir / char.image_file).exists():
                            status.characters_with_ref += 1
                        else:
                            if char.id:
                                status.characters_missing_ref.append(char.id)
            except:
                pass

            # Set pre-Excel workflow steps
            status.step_srt = "done" if status.srt_exists else "pending"

            if status.characters_count == 0:
                status.step_characters = "pending"
            elif status.characters_with_ref == status.characters_count:
                status.step_characters = "done"
            elif status.characters_with_ref > 0:
                status.step_characters = "partial"
            else:
                status.step_characters = "pending"

            if status.img_prompts_count == 0:
                status.step_prompts = "pending"
            elif status.img_prompts_count == status.total_scenes and status.fallback_prompts == 0:
                status.step_prompts = "done"
            else:
                status.step_prompts = "partial"

            # Excel status - chi tiết hơn
            if status.prompts_count == 0:
                status.excel_status = "empty"
                status.current_step = "excel"
            elif status.scenes_mismatch:
                status.excel_status = "mismatch"  # SRT và Excel không khớp
                status.current_step = "excel"
            elif status.fallback_prompts > 0:
                status.excel_status = "fallback"
                status.current_step = "excel"  # Need API completion
            elif len(status.missing_img_prompts) > 0:
                status.excel_status = "partial"
                status.current_step = "excel"
            else:
                status.excel_status = "complete"
                status.current_step = "image"

            # Check images - use actual img/{scene_id}.png path
            img_dir = project_dir / "img"
            for scene in scenes:
                actual_img = img_dir / f"{scene.scene_id}.png"
                if actual_img.exists():
                    status.images_done += 1
                else:
                    status.images_missing.append(scene.scene_id)

            if status.excel_status == "complete":
                if status.images_done == status.total_scenes:
                    status.current_step = "video"
                else:
                    status.current_step = "image"

            # Check videos - use actual video/{scene_id}.mp4 path
            video_dir = project_dir / "video"
            for scene in scenes:
                actual_vid = video_dir / f"{scene.scene_id}.mp4"
                if actual_vid.exists():
                    status.videos_done += 1
                else:
                    status.videos_missing.append(scene.scene_id)

            # Get video_mode from SettingsManager
            try:
                settings = SettingsManager()
                status.video_mode = settings.video_mode
            except:
                status.video_mode = "full"

            # Get Segment 1 info for BASIC mode
            try:
                segments = wb.get_story_segments()
                if segments:
                    seg1 = segments[0]  # First segment
                    status.segment1_end_srt = seg1.get('srt_range_end', 0)

                    # Find scenes that belong to Segment 1
                    srt_start = seg1.get('srt_range_start', 1)
                    srt_end = seg1.get('srt_range_end', 0)

                    for scene in scenes:
                        # Scene belongs to Segment 1 if its scene_id is within SRT range
                        if srt_start <= scene.scene_id <= srt_end:
                            status.segment1_scenes.append(scene.scene_id)
            except:
                pass

            # Determine videos_needed based on mode
            if status.video_mode == "basic" or "basic" in status.video_mode.lower():
                # BASIC mode: only videos for Segment 1 scenes that have images
                for scene_id in status.segment1_scenes:
                    if scene_id not in status.images_missing:  # Has image
                        if scene_id in status.videos_missing:  # Needs video
                            status.videos_needed.append(scene_id)
            else:
                # FULL mode: all scenes that have images need videos
                for scene_id in status.videos_missing:
                    if scene_id not in status.images_missing:  # Has image
                        status.videos_needed.append(scene_id)

            # Determine completion based on mode
            if status.video_mode == "basic" or "basic" in status.video_mode.lower():
                # BASIC: done when all Segment 1 videos are complete
                seg1_videos_done = len([s for s in status.segment1_scenes if s not in status.videos_missing])
                seg1_videos_needed = len(status.segment1_scenes)
                videos_complete = (seg1_videos_done >= seg1_videos_needed) if seg1_videos_needed > 0 else True
            else:
                # FULL: done when all videos are complete
                videos_complete = (status.videos_done == status.total_scenes)

            if status.images_done == status.total_scenes:
                if videos_complete:
                    status.current_step = "done"
                else:
                    status.current_step = "video"

        except Exception as e:
            status.errors.append(str(e))

        return status

    def get_excel_validation_report(self, project_code: str) -> Dict:
        """Báo cáo chi tiết về Excel validation."""
        status = self.get_project_status(project_code)

        report = {
            "project": project_code,
            "excel_exists": status.excel_exists,
            "excel_status": status.excel_status,
            "is_complete": status.excel_status == "complete",

            # Scene counts
            "srt_scenes": status.srt_scene_count,
            "excel_scenes": status.excel_scene_count,
            "scenes_match": not status.scenes_mismatch,

            # Prompt stats
            "total_scenes": status.total_scenes,
            "img_prompts": status.img_prompts_count,
            "video_prompts": status.video_prompts_count,
            "fallback_count": status.fallback_prompts,

            # Missing details
            "missing_img_prompts": status.missing_img_prompts[:10],  # First 10
            "missing_video_prompts": status.missing_video_prompts[:10],
            "fallback_scenes": status.fallback_scenes[:10],

            # Progress
            "images_done": status.images_done,
            "videos_done": status.videos_done,
            "current_step": status.current_step,

            # Issues
            "issues": []
        }

        # Add issues
        if status.scenes_mismatch:
            report["issues"].append(f"Scene count mismatch: SRT={status.srt_scene_count}, Excel={status.excel_scene_count}")

        if status.missing_img_prompts:
            report["issues"].append(f"Missing img_prompt in {len(status.missing_img_prompts)} scenes")

        if status.missing_video_prompts:
            report["issues"].append(f"Missing video_prompt in {len(status.missing_video_prompts)} scenes")

        if status.fallback_prompts > 0:
            report["issues"].append(f"{status.fallback_prompts} scenes have [FALLBACK] prompts (need API)")

        return report

    def check_excel(self, project_code: str) -> tuple:
        status = self.get_project_status(project_code)
        if status.excel_status == "complete":
            return QualityStatus.PASS, {"total": status.total_scenes, "prompts": status.prompts_count}
        elif status.excel_status in ("partial", "fallback"):
            return QualityStatus.PARTIAL, {"fallback": status.fallback_prompts}
        return QualityStatus.FAIL, {}

    def check_images(self, project_code: str, scenes: List[int] = None) -> tuple:
        status = self.get_project_status(project_code)
        if scenes:
            missing = [s for s in scenes if s in status.images_missing]
        else:
            missing = status.images_missing

        if not missing:
            return QualityStatus.PASS, {"completed": status.images_done}
        elif status.images_done > 0:
            return QualityStatus.PARTIAL, {"missing": missing}
        return QualityStatus.FAIL, {"missing": missing}

    def check_videos(self, project_code: str, scenes: List[int] = None) -> tuple:
        status = self.get_project_status(project_code)
        if scenes:
            missing = [s for s in scenes if s in status.videos_missing]
        else:
            missing = status.videos_missing

        if not missing:
            return QualityStatus.PASS, {"completed": status.videos_done}
        elif status.videos_done > 0:
            return QualityStatus.PARTIAL, {"missing": missing}
        return QualityStatus.FAIL, {"missing": missing}


# ================================================================================
# DASHBOARD
# ================================================================================

class Dashboard:
    """Giao diện Dashboard để giám sát hệ thống."""

    def __init__(self, manager: 'VMManager'):
        self.manager = manager

    def clear_screen(self):
        os.system('cls' if sys.platform == 'win32' else 'clear')

    def render(self):
        """Render toàn bộ dashboard."""
        lines = []

        # Header
        lines.extend(self._render_header())

        # Settings
        lines.extend(self._render_settings())

        # Workers
        lines.extend(self._render_workers())

        # Projects
        lines.extend(self._render_projects())

        # Tasks
        lines.extend(self._render_tasks())

        # Errors
        lines.extend(self._render_errors())

        # Commands
        lines.extend(self._render_commands())

        return "\n".join(lines)

    def _render_header(self) -> List[str]:
        now = datetime.now().strftime("%H:%M:%S")
        return [
            "",
            "╔═══════════════════════════════════════════════════════════════════════════╗",
            f"║          VM MANAGER - AI Agent Dashboard           [{now}]         ║",
            "╠═══════════════════════════════════════════════════════════════════════════╣",
        ]

    def _render_settings(self) -> List[str]:
        s = self.manager.settings.get_summary()
        api_status = []
        if s['api_keys']['deepseek']:
            api_status.append("DeepSeek[v]")
        if s['api_keys']['groq']:
            api_status.append("Groq[v]")
        if s['api_keys']['gemini']:
            api_status.append("Gemini[v]")

        ipv6_info = f"IPv6: {'ON' if s['ipv6_enabled'] else 'OFF'}"
        if s['ipv6_enabled']:
            ipv6_info += f" ({s['ipv6_count']} IPs)"
            if s['ipv6_rotate_on_error']:
                ipv6_info += " [Auto-rotate on 403]"

        return [
            "║  SETTINGS:                                                                ║",
            f"║    Chrome Workers: {s['chrome_count']:<5} │ Excel Mode: {s['excel_mode']:<8} │ {ipv6_info:<25}║",
            f"║    API Keys: {' | '.join(api_status) if api_status else 'None configured':<60}║",
            "╠═══════════════════════════════════════════════════════════════════════════╣",
        ]

    def _render_workers(self) -> List[str]:
        lines = ["║  WORKERS:                                                                 ║"]

        for wid, w in self.manager.workers.items():
            emoji = {
                "stopped": "[STOP]️ ",
                "idle": "[IDLE]",
                "working": "[RUN]",
                "error": "[FAIL]"
            }.get(w.status.value, "[?]")

            # Get detailed info from Agent Protocol if available
            details = self.manager.get_worker_details(wid)
            task_info = ""
            progress_info = ""

            if details:
                # Progress bar cho working state
                if details.get("current_scene") and details.get("total_scenes"):
                    progress = int(details["current_scene"] / details["total_scenes"] * 100)
                    progress_info = f"[{progress:>3}%]"

                # Task info
                if details.get("current_project"):
                    task_info = f"→ {details['current_project']}"
                    if details.get("current_scene"):
                        task_info += f" scene {details['current_scene']}/{details['total_scenes']}"
            elif w.current_task:
                task_info = f"→ {w.current_task[:25]}"

            uptime = ""
            if details and details.get("uptime_seconds"):
                mins = details["uptime_seconds"] // 60
                uptime = f"({mins}m)"
            elif w.start_time:
                mins = int((datetime.now() - w.start_time).total_seconds() // 60)
                uptime = f"({mins}m)"

            line = f"║    {emoji} {wid:<12} {w.status.value:<8} done:{w.completed_tasks:<3} fail:{w.failed_tasks:<3} {uptime:<6} {progress_info} {task_info}"
            lines.append(f"{line:<76}║")

        lines.append("╠═══════════════════════════════════════════════════════════════════════════╣")
        return lines

    def _render_projects(self) -> List[str]:
        lines = ["║  PROJECTS:                                                                ║"]

        projects = self.manager.scan_projects()
        if not projects:
            lines.append("║    (No projects found)                                                    ║")
        else:
            for code in projects[:5]:  # Show first 5
                status = self.manager.quality_checker.get_project_status(code)

                # Excel status
                excel_emoji = {
                    "none": "[FAIL]",
                    "empty": "[FAIL]",
                    "fallback": "[WARN]",
                    "partial": "[WARN]",
                    "complete": "[OK]"
                }.get(status.excel_status, "[?]")

                # Progress
                img_pct = (status.images_done / status.total_scenes * 100) if status.total_scenes else 0
                vid_pct = (status.videos_done / status.total_scenes * 100) if status.total_scenes else 0

                step_emoji = {"excel": "[LIST]", "image": "[IMG]", "video": "[VIDEO]", "done": "[OK]"}.get(status.current_step, "[?]")

                line = (
                    f"║    {code:<12} │ "
                    f"Excel:{excel_emoji} {status.prompts_count}/{status.total_scenes} │ "
                    f"Img:{status.images_done}/{status.total_scenes} ({img_pct:.0f}%) │ "
                    f"Vid:{status.videos_done}/{status.total_scenes} ({vid_pct:.0f}%) │ "
                    f"{step_emoji}{status.current_step}"
                )
                lines.append(f"{line:<76}║")

            if len(projects) > 5:
                lines.append(f"║    ... và {len(projects) - 5} projects khác                                          ║")

        lines.append("╠═══════════════════════════════════════════════════════════════════════════╣")
        return lines

    def _render_tasks(self) -> List[str]:
        pending = len([t for t in self.manager.tasks.values() if t.status in (TaskStatus.PENDING, TaskStatus.RETRY)])
        running = len([t for t in self.manager.tasks.values() if t.status in (TaskStatus.ASSIGNED, TaskStatus.RUNNING)])
        completed = len([t for t in self.manager.tasks.values() if t.status == TaskStatus.COMPLETED])
        failed = len([t for t in self.manager.tasks.values() if t.status == TaskStatus.FAILED])

        return [
            "║  TASKS:                                                                   ║",
            f"║    [WAIT] Pending: {pending:<5}  [RUN] Running: {running:<5}  [OK] Done: {completed:<5}  [FAIL] Failed: {failed:<5}    ║",
            "╠═══════════════════════════════════════════════════════════════════════════╣",
        ]

    def _render_errors(self) -> List[str]:
        lines = ["║  RECENT ERRORS:                                                           ║"]

        # Get error summary from Agent Protocol
        error_summary = self.manager.get_error_summary()
        if error_summary:
            summary_parts = [f"{k}:{v}" for k, v in error_summary.items()]
            summary_line = f"║    Summary: {' | '.join(summary_parts)}"
            lines.append(f"{summary_line:<76}║")

        errors = []

        # Collect errors from Agent Protocol
        for wid in self.manager.workers:
            details = self.manager.get_worker_details(wid)
            if details and details.get("last_error"):
                error_type = details.get("last_error_type", "")
                error_msg = details["last_error"][:40]
                errors.append((wid, f"[{error_type}] {error_msg}"))

        # Collect errors from tasks
        for t in list(self.manager.tasks.values())[-3:]:
            if t.error:
                errors.append((t.task_id[:12], t.error[:45]))

        if not errors and not error_summary:
            lines.append("║    (No errors)                                                            ║")
        else:
            for source, error in errors[-4:]:
                line = f"║    [{source}] {error}"
                lines.append(f"{line:<76}║")

        lines.append("╠═══════════════════════════════════════════════════════════════════════════╣")
        return lines

    def _render_commands(self) -> List[str]:
        return [
            "║  COMMANDS:                                                                ║",
            "║    status    - Refresh     │ restart      - Restart all                  ║",
            "║    tasks     - Show tasks  │ restart N    - Restart Chrome N             ║",
            "║    scan      - Scan new    │ scale N      - Scale to N Chrome            ║",
            "║    logs N    - Worker logs │ errors       - Show all errors              ║",
            "║    detail N  - Worker info │ ipv6         - IPv6 status/rotate           ║",
            "║    set       - Settings    │ quit         - Exit                         ║",
            "╚═══════════════════════════════════════════════════════════════════════════╝",
        ]


# ================================================================================
# VM MANAGER - AI AGENT ORCHESTRATOR
# ================================================================================

class VMManager:
    """AI Agent Orchestrator với Dashboard."""

    def __init__(self, num_chrome_workers: int = 2, enable_excel: bool = True):
        self.num_chrome_workers = num_chrome_workers
        self.enable_excel = enable_excel

        # Setup
        self._setup_agent_dirs()
        self.settings = SettingsManager()

        # Agent Protocol for worker monitoring
        if AGENT_PROTOCOL_ENABLED:
            self.agent_protocol = AgentProtocolManager()
        else:
            self.agent_protocol = None

        # Workers
        self.workers: Dict[str, WorkerInfo] = {}
        self._init_workers()

        # Tasks
        self.tasks: Dict[str, Task] = {}
        self.project_tasks: Dict[str, List[str]] = {}

        # Quality & Dashboard
        self.quality_checker = QualityChecker(TOOL_DIR / "PROJECTS")
        self.dashboard = Dashboard(self)

        # Control
        self._stop_flag = False
        self._lock = threading.Lock()
        self.gui_mode = False  # Track if workers run in GUI mode (minimized CMD)

        # IPv6 Manager for rotation
        if IPV6_MANAGER_ENABLED:
            self.ipv6_manager = get_ipv6_manager()
        else:
            self.ipv6_manager = None

        # Error tracking for intelligent restart/IPv6 rotation
        self.consecutive_403_count = 0  # Tổng 403 liên tiếp (all workers)
        self.worker_error_counts: Dict[str, int] = {}  # Per-worker consecutive errors
        self.max_403_before_ipv6 = 5  # Đổi IPv6 sau 5 lần 403
        self.max_errors_before_clear = 3  # Xóa data Chrome sau 3 lần lỗi liên tiếp

        # Auto-detect
        self.auto_path = self._detect_auto_path()
        self.channel = self._get_channel_from_folder()

    def _setup_agent_dirs(self):
        for d in [AGENT_DIR, TASKS_DIR, RESULTS_DIR, STATUS_DIR, LOGS_DIR]:
            d.mkdir(parents=True, exist_ok=True)
        for f in TASKS_DIR.glob("*.json"):
            f.unlink()
        for f in RESULTS_DIR.glob("*.json"):
            f.unlink()

    def _init_workers(self):
        if self.enable_excel:
            self.workers["excel"] = WorkerInfo(worker_id="excel", worker_type="excel")

        for i in range(self.num_chrome_workers):
            wid = f"chrome_{i+1}"
            self.workers[wid] = WorkerInfo(worker_id=wid, worker_type="chrome", worker_num=i+1)

    def _detect_auto_path(self) -> Optional[Path]:
        for p in [Path(r"\\tsclient\D\AUTO"), Path(r"\\vmware-host\Shared Folders\D\AUTO"),
                  Path(r"Z:\AUTO"), Path(r"Y:\AUTO"), Path(r"D:\AUTO")]:
            try:
                if p.exists():
                    return p
            except:
                pass
        return None

    def _get_channel_from_folder(self) -> Optional[str]:
        folder = TOOL_DIR.parent.name
        if "-T" in folder:
            return folder.split("-T")[0]
        return None

    # ================================================================================
    # CHROME AUTO-SCALING
    # ================================================================================

    def get_base_chrome_path(self) -> Optional[Path]:
        """Tìm Chrome portable gốc để copy."""
        candidates = [
            TOOL_DIR / "GoogleChromePortable",
            Path.home() / "Documents" / "GoogleChromePortable",
        ]
        for p in candidates:
            exe = p / "GoogleChromePortable.exe"
            if exe.exists():
                return p
        return None

    def get_chrome_path_for_worker(self, worker_num: int) -> Optional[Path]:
        """Lấy đường dẫn Chrome cho worker N."""
        if worker_num == 1:
            return self.get_base_chrome_path()

        # Worker 2+ dùng copy
        base = self.get_base_chrome_path()
        if not base:
            return None

        # Thử các tên khác nhau
        names = [
            f"GoogleChromePortable_{worker_num}",
            f"GoogleChromePortable - Copy{'' if worker_num == 2 else ' ' + str(worker_num - 1)}",
            f"GoogleChromePortable - Copy {worker_num - 1}" if worker_num > 2 else "GoogleChromePortable - Copy",
        ]

        for name in names:
            path = base.parent / name
            if (path / "GoogleChromePortable.exe").exists():
                return path

        return None

    def create_chrome_for_worker(self, worker_num: int) -> Optional[Path]:
        """
        Tạo Chrome portable cho worker N bằng cách copy từ base.
        Không copy Data folder để user cần login lại.

        Returns:
            Path to Chrome folder if created, None if failed
        """
        if worker_num == 1:
            return self.get_base_chrome_path()

        base = self.get_base_chrome_path()
        if not base:
            self.log("Base Chrome not found, cannot create new instances", "CHROME", "ERROR")
            return None

        target_name = f"GoogleChromePortable_{worker_num}"
        target_path = base.parent / target_name

        if target_path.exists():
            self.log(f"Chrome {worker_num} already exists: {target_path}", "CHROME")
            return target_path

        self.log(f"Creating Chrome {worker_num} from base...", "CHROME")

        try:
            # Copy entire folder except Data (so user needs to login)
            def ignore_data(directory, files):
                """Ignore Data folder for fresh login."""
                if directory == str(base):
                    return ['Data', 'User Data']
                return []

            shutil.copytree(base, target_path, ignore=ignore_data)
            self.log(f"Created Chrome {worker_num}: {target_path}", "CHROME", "SUCCESS")
            return target_path
        except Exception as e:
            self.log(f"Failed to create Chrome {worker_num}: {e}", "CHROME", "ERROR")
            return None

    def ensure_chrome_script(self, worker_num: int) -> Optional[Path]:
        """
        Đảm bảo script _run_chromeN.py tồn tại.
        Nếu chưa có, tạo từ template.
        """
        script_path = TOOL_DIR / f"_run_chrome{worker_num}.py"

        if script_path.exists():
            return script_path

        # Template cho Chrome worker script
        self.log(f"Creating script: {script_path.name}", "CHROME")

        # Copy từ _run_chrome1.py và sửa worker number
        base_script = TOOL_DIR / "_run_chrome1.py"
        if not base_script.exists():
            self.log("Base script _run_chrome1.py not found", "CHROME", "ERROR")
            return None

        try:
            with open(base_script, 'r', encoding='utf-8') as f:
                content = f.read()

            # Cập nhật parallel_chrome setting cho worker này
            # Thay "1/2" thành "N/total"
            import re
            # Tìm và thay thế pattern parallel_chrome
            content = re.sub(
                r"parallel_chrome\s*=\s*['\"][^'\"]*['\"]",
                f'parallel_chrome = "{worker_num}/{self.num_chrome_workers}"',
                content
            )

            # Cập nhật WORKER_ID nếu có
            content = re.sub(
                r"WORKER_ID\s*=\s*['\"]chrome_\d+['\"]",
                f'WORKER_ID = "chrome_{worker_num}"',
                content
            )

            # Cập nhật chrome portable path cho worker này
            chrome_path = self.get_chrome_path_for_worker(worker_num)
            if chrome_path:
                # Thêm logic để dùng Chrome portable riêng
                content = re.sub(
                    r"(# Chrome portable path)",
                    f'# Chrome portable path for worker {worker_num}\n'
                    f'CHROME_PORTABLE_{worker_num} = Path(r"{chrome_path}")',
                    content
                )

            with open(script_path, 'w', encoding='utf-8') as f:
                f.write(content)

            self.log(f"Created script: {script_path.name}", "CHROME", "SUCCESS")
            return script_path
        except Exception as e:
            self.log(f"Failed to create script: {e}", "CHROME", "ERROR")
            return None

    def scale_chrome_workers(self, new_count: int) -> bool:
        """
        Scale số lượng Chrome workers.
        Tự động tạo Chrome portable và scripts nếu cần.

        Args:
            new_count: Số Chrome workers mới

        Returns:
            True nếu scale thành công
        """
        if new_count < 1:
            self.log("Chrome count must be >= 1", "CHROME", "ERROR")
            return False

        self.log(f"Scaling Chrome workers: {self.num_chrome_workers} → {new_count}", "CHROME")

        # Tạo Chrome portable và scripts cho workers mới
        for i in range(1, new_count + 1):
            # Kiểm tra/tạo Chrome portable
            chrome_path = self.get_chrome_path_for_worker(i)
            if not chrome_path:
                chrome_path = self.create_chrome_for_worker(i)
                if not chrome_path:
                    self.log(f"Failed to setup Chrome {i}", "CHROME", "ERROR")
                    return False

            # Kiểm tra/tạo script
            script = self.ensure_chrome_script(i)
            if not script:
                self.log(f"Failed to create script for Chrome {i}", "CHROME", "ERROR")
                return False

        # Cập nhật số workers
        old_count = self.num_chrome_workers
        self.num_chrome_workers = new_count
        self._init_workers()

        # Cập nhật settings
        self.settings.chrome_count = new_count

        self.log(f"Scaled to {new_count} Chrome workers", "CHROME", "SUCCESS")

        # Nếu có workers mới, thông báo cần login
        if new_count > old_count:
            new_workers = [f"chrome_{i}" for i in range(old_count + 1, new_count + 1)]
            self.log(f"New workers need Google login: {new_workers}", "CHROME", "WARN")

        return True

    def log(self, msg: str, source: str = "MANAGER", level: str = "INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        emoji = {"INFO": "  ", "WARN": "[WARN]", "ERROR": "[FAIL]", "SUCCESS": "[OK]", "TASK": "[LIST]"}.get(level, "  ")
        print(f"[{timestamp}] [{source}] {emoji} {msg}")

    # ================================================================================
    # AGENT PROTOCOL INTEGRATION
    # ================================================================================

    def sync_worker_status(self):
        """Đồng bộ trạng thái worker từ Agent Protocol."""
        if not self.agent_protocol:
            return

        for worker_id, worker in self.workers.items():
            agent_status = self.agent_protocol.get_worker_status(worker_id)
            if agent_status:
                # Cập nhật status từ agent protocol
                if agent_status.state == "working":
                    worker.status = WorkerStatus.WORKING
                elif agent_status.state == "idle":
                    worker.status = WorkerStatus.IDLE
                elif agent_status.state == "error":
                    worker.status = WorkerStatus.ERROR
                    worker.last_error = agent_status.last_error
                elif agent_status.state == "stopped":
                    worker.status = WorkerStatus.STOPPED

                # Cập nhật task info
                if agent_status.current_task:
                    worker.current_task = agent_status.current_task
                worker.completed_tasks = agent_status.completed_count
                worker.failed_tasks = agent_status.failed_count

    def check_worker_health(self, cooldown_seconds: int = 120) -> List[tuple]:
        """
        Kiểm tra health của workers, trả về danh sách (worker_id, error_type).

        Args:
            cooldown_seconds: Thời gian chờ tối thiểu giữa các lần restart (mặc định 120s)

        Returns:
            List of tuples: [(worker_id, error_type), ...]
        """
        workers_with_errors = []

        if not self.agent_protocol:
            return workers_with_errors

        for worker_id, worker in self.workers.items():
            if worker.status == WorkerStatus.STOPPED:
                continue

            # Check cooldown - không action nếu vừa restart gần đây
            if worker.last_restart_time:
                elapsed = (datetime.now() - worker.last_restart_time).total_seconds()
                if elapsed < cooldown_seconds:
                    continue  # Skip, đang trong cooldown

            # Check if worker is alive (updated status within last 60s)
            if not self.agent_protocol.is_worker_alive(worker_id, timeout_seconds=60):
                self.log(f"{worker_id} không phản hồi (timeout 60s)", worker_id, "WARN")
                workers_with_errors.append((worker_id, "timeout"))
                continue

            # Check for critical errors - chỉ xử lý nếu error mới (sau lần restart cuối)
            agent_status = self.agent_protocol.get_worker_status(worker_id)
            if agent_status and agent_status.last_error_type:
                error_type = agent_status.last_error_type
                if error_type in ("chrome_crash", "chrome_403", "api_error"):
                    # Kiểm tra xem error này có phải sau lần restart cuối không
                    try:
                        error_time = datetime.fromisoformat(agent_status.last_update)
                        if worker.last_restart_time and error_time < worker.last_restart_time:
                            continue  # Error cũ, đã restart rồi
                    except:
                        pass

                    workers_with_errors.append((worker_id, error_type))

        return workers_with_errors

    def get_worker_details(self, worker_id: str) -> Optional[Dict]:
        """Lấy thông tin chi tiết của worker từ Agent Protocol."""
        if not self.agent_protocol:
            return None

        agent_status = self.agent_protocol.get_worker_status(worker_id)
        if not agent_status:
            return None

        return {
            "state": agent_status.state,
            "progress": agent_status.progress,
            "current_project": agent_status.current_project,
            "current_task": agent_status.current_task,
            "current_scene": agent_status.current_scene,
            "total_scenes": agent_status.total_scenes,
            "completed_count": agent_status.completed_count,
            "failed_count": agent_status.failed_count,
            "last_error": agent_status.last_error,
            "last_error_type": agent_status.last_error_type,
            "uptime_seconds": agent_status.uptime_seconds,
        }

    def get_worker_logs(self, worker_id: str, lines: int = 20) -> List[str]:
        """Lấy log gần nhất của worker."""
        if not self.agent_protocol:
            return []
        return self.agent_protocol.get_recent_logs(worker_id, lines)

    def get_worker_log_file(self, worker_id: str, lines: int = 50) -> List[str]:
        """Đọc log từ file log của worker (cho hidden mode)."""
        log_file = AGENT_DIR / "logs" / f"{worker_id}.log"
        if not log_file.exists():
            return []
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                all_lines = f.readlines()
                return all_lines[-lines:] if len(all_lines) > lines else all_lines
        except Exception as e:
            return [f"Error reading log: {e}"]

    def get_all_worker_logs(self, lines_per_worker: int = 20) -> Dict[str, List[str]]:
        """Lấy log của tất cả workers (cho GUI)."""
        logs = {}
        for worker_id in self.workers:
            # Try log file first (hidden mode), then agent protocol
            file_logs = self.get_worker_log_file(worker_id, lines_per_worker)
            if file_logs:
                logs[worker_id] = file_logs
            else:
                logs[worker_id] = self.get_worker_logs(worker_id, lines_per_worker)
        return logs

    def get_error_summary(self) -> Dict[str, int]:
        """Lấy tóm tắt các loại lỗi từ tất cả workers."""
        if not self.agent_protocol:
            return {}
        return self.agent_protocol.get_error_summary()

    # ================================================================================
    # ERROR TRACKING & IPv6 ROTATION
    # ================================================================================

    def track_worker_error(self, worker_id: str, error_type: str) -> str:
        """
        Track lỗi của worker và quyết định hành động.

        Returns:
            "none" - Không cần action
            "restart" - Restart worker đó
            "clear_data" - Xóa data Chrome và login lại
            "rotate_ipv6" - Đổi IPv6 và restart tất cả
        """
        # Track per-worker errors
        if worker_id not in self.worker_error_counts:
            self.worker_error_counts[worker_id] = 0

        if error_type == "chrome_403":
            # Track 403 globally
            self.consecutive_403_count += 1
            self.worker_error_counts[worker_id] += 1

            self.log(f"403 count: {self.consecutive_403_count}/{self.max_403_before_ipv6} (global), "
                     f"{self.worker_error_counts[worker_id]} ({worker_id})", "ERROR", "WARN")

            # Check if need IPv6 rotation
            if self.consecutive_403_count >= self.max_403_before_ipv6:
                return "rotate_ipv6"

            # Check if need Chrome data clear (3 consecutive for same worker)
            if self.worker_error_counts[worker_id] >= self.max_errors_before_clear:
                return "clear_data"

            return "restart"

        elif error_type in ("chrome_crash", "timeout", "unknown"):
            self.worker_error_counts[worker_id] += 1

            if self.worker_error_counts[worker_id] >= self.max_errors_before_clear:
                return "clear_data"

            return "restart"

        return "none"

    def reset_error_tracking(self, worker_id: str = None):
        """Reset error tracking (sau khi action thành công)."""
        if worker_id:
            self.worker_error_counts[worker_id] = 0
        else:
            # Reset all
            self.consecutive_403_count = 0
            self.worker_error_counts.clear()

    def perform_ipv6_rotation(self) -> bool:
        """
        Thực hiện IPv6 rotation:
        1. Tắt tất cả Chrome workers
        2. Đổi IPv6
        3. Khởi động lại tất cả

        Returns:
            True nếu thành công
        """
        if not self.ipv6_manager or not self.ipv6_manager.enabled:
            self.log("IPv6 rotation disabled or not available", "IPv6", "WARN")
            return False

        self.log("Starting IPv6 rotation...", "IPv6", "WARN")

        # 1. Stop all Chrome workers
        for wid, w in self.workers.items():
            if w.worker_type == "chrome":
                self.stop_worker(wid)

        # 2. Kill all Chrome processes
        self.kill_all_chrome()
        time.sleep(2)

        # 3. Rotate IPv6
        result = self.ipv6_manager.rotate_ipv6()

        if result["success"]:
            self.log(f"IPv6 rotated: {result['message']}", "IPv6", "SUCCESS")

            # 4. Reset error tracking
            self.reset_error_tracking()

            # 5. Wait and restart Chrome workers
            time.sleep(3)
            for wid, w in self.workers.items():
                if w.worker_type == "chrome":
                    self.start_worker(wid, gui_mode=self.gui_mode)
                    time.sleep(2)

            return True
        else:
            self.log(f"IPv6 rotation failed: {result['message']}", "IPv6", "ERROR")
            return False

    def clear_chrome_data(self, worker_id: str) -> bool:
        """
        Xóa data Chrome và khởi động lại.
        Worker sẽ cần login lại.
        """
        self.log(f"Clearing Chrome data for {worker_id}...", worker_id, "WARN")

        # Stop worker
        self.stop_worker(worker_id)
        self.kill_all_chrome()

        # Get Chrome profile path
        w = self.workers.get(worker_id)
        if not w:
            return False

        # Xóa profile nếu có
        # TODO: Implement Chrome profile clearing based on settings
        # For now, just restart and reset error count
        self.reset_error_tracking(worker_id)

        time.sleep(3)
        self.start_worker(worker_id)

        self.log(f"Chrome data cleared, {worker_id} restarted", worker_id, "SUCCESS")
        return True

    def handle_worker_error(self, worker_id: str, error_type: str):
        """
        Xử lý lỗi worker theo logic thông minh:
        - Lỗi 1-2 lần → Restart
        - Lỗi 3 lần liên tiếp → Clear data + Restart
        - 403 lỗi 5 lần (any worker) → Đổi IPv6 + Restart all
        """
        action = self.track_worker_error(worker_id, error_type)

        if action == "rotate_ipv6":
            self.log(f"403 threshold reached ({self.consecutive_403_count}), rotating IPv6...", "MANAGER", "ERROR")
            self.perform_ipv6_rotation()

        elif action == "clear_data":
            self.log(f"Error threshold reached for {worker_id}, clearing data...", worker_id, "ERROR")
            self.clear_chrome_data(worker_id)

        elif action == "restart":
            self.restart_worker(worker_id)
            # Reset count cho worker này sau restart
            self.worker_error_counts[worker_id] = max(0, self.worker_error_counts.get(worker_id, 1) - 1)

    # ================================================================================
    # TASK MANAGEMENT
    # ================================================================================

    def create_task(self, task_type: TaskType, project_code: str, scenes: List[int] = None) -> Task:
        task_id = f"{task_type.value}_{project_code}_{datetime.now().strftime('%H%M%S%f')[:10]}"
        task = Task(
            task_id=task_id,
            task_type=task_type,
            project_code=project_code,
            scenes=scenes or [],
            created_at=datetime.now().isoformat(),
        )
        self.tasks[task_id] = task
        if project_code not in self.project_tasks:
            self.project_tasks[project_code] = []
        self.project_tasks[project_code].append(task_id)
        self.log(f"Created: {task_id}", "TASK", "TASK")
        return task

    def assign_task(self, task: Task, worker_id: str) -> bool:
        if worker_id not in self.workers:
            return False
        worker = self.workers[worker_id]
        if worker.current_task:
            return False

        task.status = TaskStatus.ASSIGNED
        task.assigned_to = worker_id
        task.assigned_at = datetime.now().isoformat()
        worker.current_task = task.task_id
        worker.status = WorkerStatus.WORKING

        task_file = TASKS_DIR / f"{worker_id}.json"
        with open(task_file, 'w', encoding='utf-8') as f:
            json.dump(task.to_dict(), f, ensure_ascii=False, indent=2)

        self.log(f"Assigned: {task.task_id} → {worker_id}", "TASK", "TASK")
        return True

    def get_pending_tasks(self, task_type: TaskType = None) -> List[Task]:
        return [t for t in self.tasks.values()
                if t.status in (TaskStatus.PENDING, TaskStatus.RETRY)
                and (task_type is None or t.task_type == task_type)]

    def get_idle_worker(self, worker_type: str) -> Optional[str]:
        for wid, w in self.workers.items():
            if w.worker_type == worker_type and not w.current_task:
                if w.status in (WorkerStatus.IDLE, WorkerStatus.STOPPED):
                    return wid
        return None

    def collect_results(self):
        for f in RESULTS_DIR.glob("*.json"):
            try:
                with open(f, 'r', encoding='utf-8') as rf:
                    result = json.load(rf)
                task_id = result.get('task_id')
                if task_id in self.tasks:
                    task = self.tasks[task_id]
                    task.result = result
                    task.completed_at = datetime.now().isoformat()
                    task.status = TaskStatus.COMPLETED if result.get('success') else TaskStatus.FAILED
                    task.error = result.get('error', '')

                    if task.assigned_to in self.workers:
                        w = self.workers[task.assigned_to]
                        w.current_task = None
                        w.status = WorkerStatus.IDLE
                        if task.status == TaskStatus.COMPLETED:
                            w.completed_tasks += 1
                        else:
                            w.failed_tasks += 1
                            w.last_error = task.error
                f.unlink()
            except Exception as e:
                self.log(f"Result error: {e}", "ERROR", "ERROR")

    def check_and_retry(self, task: Task) -> Optional[Task]:
        if task.retry_count >= task.max_retries:
            return None

        if task.task_type == TaskType.EXCEL:
            status, details = self.quality_checker.check_excel(task.project_code)
        elif task.task_type == TaskType.IMAGE:
            status, details = self.quality_checker.check_images(task.project_code, task.scenes)
        else:
            status, details = self.quality_checker.check_videos(task.project_code, task.scenes)

        if status == QualityStatus.PASS:
            return None

        missing = details.get('missing', task.scenes)
        retry = self.create_task(task.task_type, task.project_code, missing)
        retry.retry_count = task.retry_count + 1
        retry.status = TaskStatus.RETRY
        return retry

    # ================================================================================
    # PROJECT & TASK CREATION
    # ================================================================================

    def scan_projects(self) -> List[str]:
        projects = []
        local = TOOL_DIR / "PROJECTS"
        if not local.exists():
            return projects
        for item in local.iterdir():
            if item.is_dir():
                code = item.name
                if self.channel and not code.startswith(self.channel):
                    continue
                if (item / f"{code}.srt").exists():
                    projects.append(code)
        return sorted(projects)

    def create_tasks_for_project(self, project_code: str):
        status = self.quality_checker.get_project_status(project_code)

        if status.current_step == "excel":
            self.create_task(TaskType.EXCEL, project_code)
        elif status.current_step == "image" and status.images_missing:
            self._distribute_tasks(TaskType.IMAGE, project_code, status.images_missing)
        elif status.current_step == "video" and status.videos_needed:
            # Use videos_needed which is filtered by video_mode (basic = Segment 1 only)
            self._distribute_tasks(TaskType.VIDEO, project_code, status.videos_needed)

    def _distribute_tasks(self, task_type: TaskType, project_code: str, scenes: List[int]):
        n = self.num_chrome_workers
        chunks = [[] for _ in range(n)]
        for i, scene in enumerate(sorted(scenes)):
            chunks[i % n].append(scene)
        for chunk in chunks:
            if chunk:
                self.create_task(task_type, project_code, chunk)

    # ================================================================================
    # WORKER CONTROL
    # ================================================================================

    def kill_all_chrome(self):
        self.log("Killing Chrome...", "SYSTEM")
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True)
            subprocess.run(["taskkill", "/F", "/IM", "GoogleChromePortable.exe"], capture_output=True)
        else:
            subprocess.run(["pkill", "-f", "chrome"], capture_output=True)
        time.sleep(2)

    # ================================================================================
    # CHROME WINDOW MANAGEMENT (Hide/Show by moving off-screen)
    # ================================================================================

    def get_chrome_windows(self) -> List[int]:
        """Lấy danh sách handle của các cửa sổ Chrome."""
        if sys.platform != "win32":
            return []

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            chrome_windows = []

            def enum_windows_callback(hwnd, lParam):
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        title = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, title, length + 1)
                        # Chrome windows usually have " - Google Chrome" in title
                        if "Chrome" in title.value or "chrome" in title.value.lower():
                            chrome_windows.append(hwnd)
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)

            return chrome_windows
        except Exception as e:
            self.log(f"Error getting Chrome windows: {e}", "CHROME", "ERROR")
            return []

    def hide_chrome_windows(self):
        """
        Ẩn các cửa sổ Chrome bằng cách di chuyển ra ngoài màn hình.
        Chrome vẫn chạy và có thể xử lý CAPTCHA.
        """
        if sys.platform != "win32":
            self.log("Window hiding only supported on Windows", "CHROME", "WARN")
            return False

        try:
            import ctypes
            user32 = ctypes.windll.user32

            chrome_windows = self.get_chrome_windows()
            if not chrome_windows:
                self.log("No Chrome windows found", "CHROME", "WARN")
                return False

            # Di chuyển tất cả cửa sổ Chrome ra ngoài màn hình (x = -3000)
            for hwnd in chrome_windows:
                # SWP_NOSIZE = 0x0001, SWP_NOZORDER = 0x0004
                user32.SetWindowPos(hwnd, 0, -3000, 100, 0, 0, 0x0001 | 0x0004)

            self.log(f"Hidden {len(chrome_windows)} Chrome windows (moved off-screen)", "CHROME", "SUCCESS")
            return True
        except Exception as e:
            self.log(f"Error hiding Chrome windows: {e}", "CHROME", "ERROR")
            return False

    def show_chrome_windows(self):
        """
        Hiện các cửa sổ Chrome - đặt bên phải màn hình, size nhỏ.
        """
        if sys.platform != "win32":
            self.log("Window showing only supported on Windows", "CHROME", "WARN")
            return False

        try:
            import ctypes
            user32 = ctypes.windll.user32

            chrome_windows = self.get_chrome_windows()
            if not chrome_windows:
                self.log("No Chrome windows found", "CHROME", "WARN")
                return False

            # Get screen size
            screen_width = user32.GetSystemMetrics(0)  # SM_CXSCREEN
            screen_height = user32.GetSystemMetrics(1)  # SM_CYSCREEN

            # Chrome window size (bigger for better visibility, on right side)
            chrome_width = 700
            chrome_height = 550

            # Position on right side, stacked vertically
            x_start = screen_width - chrome_width - 10  # 10px from right edge
            y_start = 50

            for i, hwnd in enumerate(chrome_windows):
                x = x_start
                y = y_start + (i * (chrome_height + 10))  # Stack vertically with 10px gap

                # Make sure it doesn't go off screen
                if y + chrome_height > screen_height:
                    y = y_start

                # SWP_NOZORDER = 0x0004 (don't change z-order)
                # Move and resize
                user32.SetWindowPos(hwnd, 0, x, y, chrome_width, chrome_height, 0x0004)

            self.log(f"Shown {len(chrome_windows)} Chrome windows (right side)", "CHROME", "SUCCESS")
            return True
        except Exception as e:
            self.log(f"Error showing Chrome windows: {e}", "CHROME", "ERROR")
            return False

    def get_cmd_windows(self) -> List[int]:
        """Lấy danh sách handle của các cửa sổ CMD cho Chrome workers."""
        if sys.platform != "win32":
            return []

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            cmd_windows = []

            def enum_windows_callback(hwnd, lParam):
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        title = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, title, length + 1)
                        # CMD windows have titles like "CHROME 1" or "CHROME 2"
                        if "CHROME" in title.value.upper() and "CHROME" not in title.value.lower().replace("chrome ", ""):
                            cmd_windows.append((hwnd, title.value))
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)

            # Sort by title to ensure consistent ordering (CHROME 1 before CHROME 2)
            cmd_windows.sort(key=lambda x: x[1])
            return [hwnd for hwnd, _ in cmd_windows]
        except Exception as e:
            self.log(f"Error getting CMD windows: {e}", "CHROME", "ERROR")
            return []

    def hide_cmd_windows(self):
        """Ẩn các cửa sổ CMD của Chrome workers."""
        if sys.platform != "win32":
            return False

        try:
            import ctypes
            user32 = ctypes.windll.user32

            cmd_windows = self.get_cmd_windows()
            for hwnd in cmd_windows:
                # Move off-screen
                user32.SetWindowPos(hwnd, 0, -3000, 100, 0, 0, 0x0001 | 0x0004)

            if cmd_windows:
                self.log(f"Hidden {len(cmd_windows)} CMD windows", "CHROME", "SUCCESS")
            return True
        except Exception as e:
            self.log(f"Error hiding CMD windows: {e}", "CHROME", "ERROR")
            return False

    def show_chrome_with_cmd(self):
        """
        Show Chrome và CMD windows cạnh nhau.
        Layout: [CMD 1][Chrome 1]
                [CMD 2][Chrome 2]
        CMD bên trái, Chrome bên phải (cùng hàng)
        """
        if sys.platform != "win32":
            self.log("Window showing only supported on Windows", "CHROME", "WARN")
            return False

        try:
            import ctypes
            user32 = ctypes.windll.user32

            chrome_windows = self.get_chrome_windows()
            cmd_windows = self.get_cmd_windows()

            # Get screen size
            screen_width = user32.GetSystemMetrics(0)
            screen_height = user32.GetSystemMetrics(1)

            # Sizes
            cmd_width = 490
            cmd_height = 450
            chrome_width = 500
            chrome_height = 450

            # Position from right side: [CMD][Chrome]
            x_cmd = screen_width - cmd_width - chrome_width - 20  # CMD bên trái
            x_chrome = screen_width - chrome_width - 10  # Chrome bên phải
            y_start = 50

            # Position CMD windows (bên trái)
            for i, hwnd in enumerate(cmd_windows):
                y = y_start + (i * (cmd_height + 10))
                if y + cmd_height > screen_height:
                    y = y_start
                user32.SetWindowPos(hwnd, 0, x_cmd, y, cmd_width, cmd_height, 0x0004)
                # Restore if minimized
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE

            # Position Chrome windows (bên phải, cùng hàng với CMD)
            for i, hwnd in enumerate(chrome_windows):
                y = y_start + (i * (chrome_height + 10))
                if y + chrome_height > screen_height:
                    y = y_start
                user32.SetWindowPos(hwnd, 0, x_chrome, y, chrome_width, chrome_height, 0x0004)
                # Restore if minimized
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE

            self.log(f"Shown {len(cmd_windows)} CMD + {len(chrome_windows)} Chrome windows (side by side)", "CHROME", "SUCCESS")
            return True
        except Exception as e:
            self.log(f"Error showing Chrome with CMD: {e}", "CHROME", "ERROR")
            return False

    def toggle_chrome_visibility(self) -> bool:
        """
        Toggle hiển thị Chrome windows.
        Returns: True nếu đang hiển thị, False nếu đang ẩn
        """
        if sys.platform != "win32":
            return True

        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32

            chrome_windows = self.get_chrome_windows()
            if not chrome_windows:
                return True

            # Kiểm tra vị trí hiện tại của cửa sổ đầu tiên
            rect = wintypes.RECT()
            user32.GetWindowRect(chrome_windows[0], ctypes.byref(rect))

            # Nếu x < 0 (đang ẩn), thì show
            if rect.left < 0:
                self.show_chrome_windows()
                return True
            else:
                self.hide_chrome_windows()
                return False
        except Exception:
            return True

    def start_worker(self, worker_id: str, gui_mode: bool = False) -> bool:
        """
        Start a worker process.

        Args:
            worker_id: ID of worker to start
            gui_mode: If True, start with minimized CMD window but Chrome visible
        """
        if worker_id not in self.workers:
            return False
        w = self.workers[worker_id]
        if w.process and w.process.poll() is None:
            return True

        self.log(f"Starting {worker_id}...", worker_id)
        try:
            if w.worker_type == "excel":
                script = TOOL_DIR / "run_excel_api.py"
                args = "--loop"  # Excel worker chạy loop liên tục
            else:
                script = TOOL_DIR / f"_run_chrome{w.worker_num}.py"
                args = ""  # Chrome workers chạy bình thường

            if not script.exists():
                # Fallback nếu không có script riêng
                self.log(f"Script not found: {script.name}", worker_id, "ERROR")
                w.status = WorkerStatus.ERROR
                return False

            # Ensure logs directory exists
            log_dir = LOGS_DIR
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"{worker_id}.log"

            if sys.platform == "win32":
                # Windows - start with cmd window
                title = f"{w.worker_type.upper()} {w.worker_num or ''}"
                cmd_args = f"python -X utf8 {script.name}"
                if args:
                    cmd_args += f" {args}"

                # Prepare environment with UTF-8 encoding for subprocess
                worker_env = os.environ.copy()
                worker_env['PYTHONIOENCODING'] = 'utf-8'
                worker_env['PYTHONUTF8'] = '1'

                if gui_mode:
                    # GUI mode - minimize CMD window, redirect output to log file
                    # Chrome will still open and be visible (can be hidden later with hide_chrome_windows)
                    cmd_list = [sys.executable, '-X', 'utf8', str(script)]
                    if args:
                        cmd_list.extend(args.split())

                    # Open log file
                    log_handle = open(log_file, 'a', encoding='utf-8', buffering=1)
                    log_handle.write(f"\n{'='*60}\n")
                    log_handle.write(f"[{datetime.now().isoformat()}] Starting {worker_id}\n")
                    log_handle.write(f"Command: {' '.join(cmd_list)}\n")
                    log_handle.write(f"{'='*60}\n")
                    log_handle.flush()

                    # Minimize CMD window but let Chrome be visible
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = 6  # SW_SHOWMINNOACTIVE

                    w.process = subprocess.Popen(
                        cmd_list,
                        cwd=str(TOOL_DIR),
                        stdout=log_handle,
                        stderr=subprocess.STDOUT,
                        startupinfo=startupinfo,
                        creationflags=subprocess.CREATE_NEW_CONSOLE,
                        env=worker_env
                    )
                    w._log_handle = log_handle
                else:
                    # Normal mode - visible CMD window with UTF-8 code page
                    cmd = f'start "{title}" cmd /k "chcp 65001 >nul && cd /d {TOOL_DIR} && {cmd_args}"'
                    w.process = subprocess.Popen(cmd, shell=True, cwd=str(TOOL_DIR), env=worker_env)
            else:
                # Linux/Mac
                worker_env = os.environ.copy()
                worker_env['PYTHONIOENCODING'] = 'utf-8'
                worker_env['PYTHONUTF8'] = '1'
                cmd_list = [sys.executable, '-X', 'utf8', str(script)]
                if args:
                    cmd_list.extend(args.split())
                w.process = subprocess.Popen(cmd_list, cwd=str(TOOL_DIR), env=worker_env)

            w.status = WorkerStatus.IDLE
            w.start_time = datetime.now()
            self.log(f"{worker_id} started", worker_id, "SUCCESS")
            return True
        except Exception as e:
            self.log(f"Failed: {e}", worker_id, "ERROR")
            import traceback
            self.log(f"Traceback: {traceback.format_exc()}", worker_id, "ERROR")
            w.status = WorkerStatus.ERROR
            w.last_error = str(e)
            return False

    def stop_worker(self, worker_id: str):
        if worker_id not in self.workers:
            return
        w = self.workers[worker_id]
        if w.process:
            try:
                w.process.terminate()
                w.process.wait(timeout=5)
            except:
                w.process.kill()
            w.process = None
        # Close log handle if exists (hidden mode)
        if hasattr(w, '_log_handle') and w._log_handle:
            try:
                w._log_handle.close()
            except:
                pass
            w._log_handle = None
        w.status = WorkerStatus.STOPPED
        w.current_task = None

    def restart_worker(self, worker_id: str):
        self.log(f"Restarting {worker_id}...", worker_id, "WARN")
        self.stop_worker(worker_id)

        w = self.workers[worker_id]
        if w.worker_type == "chrome":
            self.kill_all_chrome()

        time.sleep(3)
        self.start_worker(worker_id, gui_mode=self.gui_mode)

        # Track restart time và count
        w.last_restart_time = datetime.now()
        w.restart_count += 1
        self.log(f"{worker_id} restarted (count: {w.restart_count})", worker_id, "SUCCESS")

    def check_and_auto_recover(self) -> bool:
        """Check for connection errors and auto-recover if needed.

        Returns True if recovery was triggered.
        """
        # Check each Chrome worker's recent logs for connection errors
        error_threshold = 5  # Number of consecutive errors to trigger recovery

        for worker_id in self.workers:
            if not worker_id.startswith("chrome_"):
                continue

            logs = self.get_worker_log_file(worker_id, lines=20)
            if not logs:
                continue

            # Count recent connection errors
            connection_errors = 0
            for line in logs[-10:]:  # Check last 10 lines
                if "connection" in line.lower() and ("disconnected" in line.lower() or "lost" in line.lower()):
                    connection_errors += 1
                elif "RETRY" in line and connection_errors > 0:
                    connection_errors += 1

            if connection_errors >= error_threshold:
                self.log(f"[AUTO-RECOVERY] Detected {connection_errors} connection errors in {worker_id}", "SYSTEM", "WARN")
                self.log("[AUTO-RECOVERY] Killing all Chrome and restarting workers...", "SYSTEM", "WARN")

                # Kill all Chrome
                self.kill_all_chrome()
                time.sleep(2)

                # Restart all Chrome workers
                for wid in list(self.workers.keys()):
                    if wid.startswith("chrome_"):
                        self.stop_worker(wid)

                time.sleep(3)

                for wid in list(self.workers.keys()):
                    if wid.startswith("chrome_"):
                        self.start_worker(wid, gui_mode=self.gui_mode)
                        time.sleep(2)

                self.log("[AUTO-RECOVERY] Chrome workers restarted!", "SYSTEM", "SUCCESS")
                return True

        return False

    def restart_all_chrome(self):
        """Restart all Chrome workers (kill Chrome first)."""
        self.log("Restarting all Chrome workers...", "SYSTEM", "WARN")

        # Kill all Chrome processes
        self.kill_all_chrome()
        time.sleep(2)

        # Stop all Chrome workers
        for wid in list(self.workers.keys()):
            if wid.startswith("chrome_"):
                self.stop_worker(wid)

        time.sleep(3)

        # Start all Chrome workers
        for wid in list(self.workers.keys()):
            if wid.startswith("chrome_"):
                self.start_worker(wid, gui_mode=self.gui_mode)
                time.sleep(2)

        self.log("All Chrome workers restarted!", "SYSTEM", "SUCCESS")

    def start_all(self, gui_mode: bool = False):
        """Start all workers.

        Args:
            gui_mode: If True, minimize CMD windows and log to files (for GUI mode)
        """
        self.gui_mode = gui_mode  # Track mode for restart
        self.kill_all_chrome()
        if self.enable_excel:
            self.start_worker("excel", gui_mode=gui_mode)
            time.sleep(2)
        for i in range(1, self.num_chrome_workers + 1):
            self.start_worker(f"chrome_{i}", gui_mode=gui_mode)
            time.sleep(2)

    def stop_all(self):
        self._stop_flag = True
        for wid in list(self.workers.keys()):
            self.stop_worker(wid)
        self.kill_all_chrome()

    # ================================================================================
    # ORCHESTRATION
    # ================================================================================

    def orchestrate(self):
        self.log("Orchestration started", "MANAGER")
        health_check_counter = 0

        while not self._stop_flag:
            try:
                # 1. Sync worker status từ Agent Protocol
                self.sync_worker_status()

                # 2. Collect results từ workers
                self.collect_results()

                # 3. Health check mỗi 30s (6 vòng x 5s)
                health_check_counter += 1
                if health_check_counter >= 6:
                    health_check_counter = 0
                    workers_with_errors = self.check_worker_health()
                    for wid, error_type in workers_with_errors:
                        # Sử dụng handle_worker_error thay vì restart trực tiếp
                        # Hàm này sẽ quyết định: restart, clear data, hoặc IPv6 rotation
                        self.handle_worker_error(wid, error_type)

                # 4. Check completed tasks và retry nếu cần
                for task in list(self.tasks.values()):
                    if task.status == TaskStatus.COMPLETED:
                        retry = self.check_and_retry(task)
                        if retry:
                            task.status = TaskStatus.FAILED

                # 5. Scan projects mới và tạo tasks
                for project in self.scan_projects():
                    if project not in self.project_tasks:
                        self.create_tasks_for_project(project)

                # 6. Assign pending tasks cho workers
                for task in self.get_pending_tasks(TaskType.EXCEL):
                    wid = self.get_idle_worker("excel")
                    if wid:
                        self.assign_task(task, wid)

                for task in self.get_pending_tasks(TaskType.IMAGE):
                    wid = self.get_idle_worker("chrome")
                    if wid:
                        self.assign_task(task, wid)

                for task in self.get_pending_tasks(TaskType.VIDEO):
                    wid = self.get_idle_worker("chrome")
                    if wid:
                        self.assign_task(task, wid)

                time.sleep(5)
            except Exception as e:
                self.log(f"Error: {e}", "ERROR", "ERROR")
                time.sleep(10)

    # ================================================================================
    # INTERACTIVE
    # ================================================================================

    def run_interactive(self):
        self.dashboard.clear_screen()
        print(self.dashboard.render())

        self.start_all()

        orch_thread = threading.Thread(target=self.orchestrate, daemon=True)
        orch_thread.start()

        try:
            while not self._stop_flag:
                try:
                    cmd = input("\n[VM Manager] > ").strip().lower()

                    if not cmd:
                        continue
                    elif cmd == "status":
                        self.dashboard.clear_screen()
                        print(self.dashboard.render())
                    elif cmd == "tasks":
                        print("\n  TASKS:")
                        for tid, t in self.tasks.items():
                            print(f"    {tid}: {t.status.value} → {t.assigned_to or '-'}")
                    elif cmd == "scan":
                        projects = self.scan_projects()
                        print(f"\n  Found {len(projects)} projects: {projects}")
                    elif cmd == "restart":
                        for wid in self.workers:
                            self.restart_worker(wid)
                    elif cmd.startswith("restart "):
                        try:
                            num = int(cmd.split()[-1])
                            self.restart_worker(f"chrome_{num}")
                        except:
                            pass
                    elif cmd.startswith("scale "):
                        try:
                            num = int(cmd.split()[-1])
                            # Stop existing workers
                            self.stop_all()
                            # Scale with auto-creation of Chrome profiles
                            if self.scale_chrome_workers(num):
                                self.start_all(gui_mode=self.gui_mode)
                                print(f"  Scaled to {num} Chrome workers")
                            else:
                                print(f"  Failed to scale to {num} workers")
                        except Exception as e:
                            print(f"  Error: {e}")
                    elif cmd.startswith("logs "):
                        try:
                            parts = cmd.split()
                            if len(parts) >= 2:
                                target = parts[1]
                                if target.isdigit():
                                    worker_id = f"chrome_{target}"
                                elif target == "excel":
                                    worker_id = "excel"
                                else:
                                    worker_id = target
                                logs = self.get_worker_logs(worker_id, 20)
                                print(f"\n  LOGS [{worker_id}]:")
                                for log in logs:
                                    print(f"    {log.strip()}")
                                if not logs:
                                    print("    (No logs available)")
                        except Exception as e:
                            print(f"  Error: {e}")
                    elif cmd == "logs":
                        print("\n  Usage: logs <worker_id>  (e.g., logs 1, logs excel)")
                    elif cmd == "errors":
                        print("\n  ERROR SUMMARY:")
                        error_summary = self.get_error_summary()
                        if error_summary:
                            for error_type, count in error_summary.items():
                                print(f"    {error_type}: {count}")
                        else:
                            print("    (No errors)")

                        print("\n  WORKER ERRORS:")
                        for wid in self.workers:
                            details = self.get_worker_details(wid)
                            if details and details.get("last_error"):
                                print(f"    [{wid}] {details['last_error_type']}: {details['last_error'][:60]}")
                    elif cmd.startswith("detail "):
                        try:
                            parts = cmd.split()
                            if len(parts) >= 2:
                                target = parts[1]
                                if target.isdigit():
                                    worker_id = f"chrome_{target}"
                                elif target == "excel":
                                    worker_id = "excel"
                                else:
                                    worker_id = target

                                if worker_id in self.workers:
                                    w = self.workers[worker_id]
                                    details = self.get_worker_details(worker_id)

                                    print(f"\n  WORKER DETAIL: {worker_id}")
                                    print(f"  {'='*50}")
                                    print(f"    Type:           {w.worker_type}")
                                    print(f"    Status:         {w.status.value}")
                                    print(f"    Completed:      {w.completed_tasks}")
                                    print(f"    Failed:         {w.failed_tasks}")
                                    print(f"    Restart count:  {w.restart_count}")

                                    if w.last_restart_time:
                                        elapsed = int((datetime.now() - w.last_restart_time).total_seconds())
                                        print(f"    Last restart:   {elapsed}s ago")

                                    if details:
                                        print(f"\n    [From Agent Protocol]")
                                        print(f"    State:          {details.get('state', '-')}")
                                        print(f"    Progress:       {details.get('progress', 0)}%")
                                        print(f"    Project:        {details.get('current_project', '-')}")
                                        print(f"    Scene:          {details.get('current_scene', 0)}/{details.get('total_scenes', 0)}")
                                        print(f"    Uptime:         {details.get('uptime_seconds', 0)}s")
                                        if details.get('last_error'):
                                            print(f"    Last error:     [{details.get('last_error_type')}] {details.get('last_error')[:50]}")
                                else:
                                    print(f"  Worker not found: {worker_id}")
                        except Exception as e:
                            print(f"  Error: {e}")
                    elif cmd == "detail":
                        print("\n  Usage: detail <worker>  (e.g., detail 1, detail excel)")
                    elif cmd == "ipv6":
                        # Hiển thị trạng thái IPv6
                        if self.ipv6_manager:
                            status = self.ipv6_manager.get_status()
                            print(f"\n  IPv6 STATUS:")
                            print(f"    Enabled:        {status['enabled']}")
                            print(f"    Interface:      {status['interface']}")
                            print(f"    Current IPs:    {status['current_ipv6']}")
                            print(f"    Available:      {status['available_count']}")
                            print(f"    Rotations:      {status['rotation_count']}")
                            print(f"    Last rotation:  {status['last_rotation'] or 'Never'}")
                            print(f"\n  ERROR TRACKING:")
                            print(f"    403 count:      {self.consecutive_403_count}/{self.max_403_before_ipv6}")
                            for wid, count in self.worker_error_counts.items():
                                print(f"    {wid}:      {count}/{self.max_errors_before_clear}")
                        else:
                            print("\n  IPv6 Manager not available")
                    elif cmd == "ipv6 rotate":
                        # Manual rotation
                        if self.ipv6_manager and self.ipv6_manager.enabled:
                            print("\n  Rotating IPv6...")
                            self.perform_ipv6_rotation()
                        else:
                            print("\n  IPv6 rotation disabled or not available")
                    elif cmd == "set":
                        print(f"\n  SETTINGS:")
                        for k, v in self.settings.get_summary().items():
                            print(f"    {k}: {v}")
                    elif cmd in ("quit", "exit", "q"):
                        break
                    else:
                        print("  Commands: status, tasks, scan, restart, scale, logs, errors, detail, ipv6, set, quit")

                except (EOFError, KeyboardInterrupt):
                    break

        finally:
            self.stop_all()
            print("\nVM Manager stopped.")


# ================================================================================
# MAIN
# ================================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="VM Manager - AI Agent")
    parser.add_argument("--chrome", "-c", type=int, default=2)
    parser.add_argument("--no-excel", action="store_true")
    args = parser.parse_args()

    manager = VMManager(num_chrome_workers=args.chrome, enable_excel=not args.no_excel)
    manager.run_interactive()


if __name__ == "__main__":
    main()
