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

TOOL_DIR = Path(__file__).parent
AGENT_DIR = TOOL_DIR / ".agent"
TASKS_DIR = AGENT_DIR / "tasks"
RESULTS_DIR = AGENT_DIR / "results"
STATUS_DIR = AGENT_DIR / "status"
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
    images_done: int = 0
    images_missing: List[int] = field(default_factory=list)
    videos_done: int = 0
    videos_missing: List[int] = field(default_factory=list)
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
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(self.config, f, default_flow_style=False, allow_unicode=True)

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

        # Check SRT
        srt_path = project_dir / f"{project_code}.srt"
        status.srt_exists = srt_path.exists()

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
            status.prompts_count = sum(1 for s in scenes if s.img_prompt)
            status.fallback_prompts = sum(1 for s in scenes if "[FALLBACK]" in (s.img_prompt or ""))

            # Excel status
            if status.prompts_count == 0:
                status.excel_status = "empty"
                status.current_step = "excel"
            elif status.fallback_prompts > 0:
                status.excel_status = "fallback"
                status.current_step = "excel"  # Need API completion
            elif status.prompts_count < status.total_scenes:
                status.excel_status = "partial"
                status.current_step = "excel"
            else:
                status.excel_status = "complete"
                status.current_step = "image"

            # Check images
            for scene in scenes:
                img_path = scene.img_local_path
                if img_path and Path(img_path).exists():
                    status.images_done += 1
                else:
                    status.images_missing.append(scene.scene_number)

            if status.excel_status == "complete":
                if status.images_done == status.total_scenes:
                    status.current_step = "video"
                else:
                    status.current_step = "image"

            # Check videos
            for scene in scenes:
                video_path = scene.video_local_path
                if video_path and Path(video_path).exists():
                    status.videos_done += 1
                else:
                    status.videos_missing.append(scene.scene_number)

            if status.images_done == status.total_scenes:
                if status.videos_done == status.total_scenes:
                    status.current_step = "done"
                else:
                    status.current_step = "video"

        except Exception as e:
            status.errors.append(str(e))

        return status

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
            api_status.append("DeepSeek✓")
        if s['api_keys']['groq']:
            api_status.append("Groq✓")
        if s['api_keys']['gemini']:
            api_status.append("Gemini✓")

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
                "stopped": "⏹️ ",
                "idle": "😴",
                "working": "⚡",
                "error": "❌"
            }.get(w.status.value, "❓")

            task = ""
            if w.current_task:
                task = f" → {w.current_task[:30]}"

            uptime = ""
            if w.start_time:
                mins = int((datetime.now() - w.start_time).total_seconds() // 60)
                uptime = f" ({mins}m)"

            line = f"║    {emoji} {wid:<12} {w.status.value:<10} done:{w.completed_tasks:<3} fail:{w.failed_tasks:<3}{uptime}{task}"
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
                    "none": "❌",
                    "empty": "❌",
                    "fallback": "⚠️",
                    "partial": "⚠️",
                    "complete": "✅"
                }.get(status.excel_status, "❓")

                # Progress
                img_pct = (status.images_done / status.total_scenes * 100) if status.total_scenes else 0
                vid_pct = (status.videos_done / status.total_scenes * 100) if status.total_scenes else 0

                step_emoji = {"excel": "📋", "image": "🖼️", "video": "🎬", "done": "✅"}.get(status.current_step, "❓")

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
            f"║    ⏳ Pending: {pending:<5}  ⚡ Running: {running:<5}  ✅ Done: {completed:<5}  ❌ Failed: {failed:<5}    ║",
            "╠═══════════════════════════════════════════════════════════════════════════╣",
        ]

    def _render_errors(self) -> List[str]:
        lines = ["║  RECENT ERRORS:                                                           ║"]

        errors = []
        for w in self.manager.workers.values():
            if w.last_error:
                errors.append((w.worker_id, w.last_error[:50]))

        for t in list(self.manager.tasks.values())[-3:]:
            if t.error:
                errors.append((t.task_id[:15], t.error[:50]))

        if not errors:
            lines.append("║    (No errors)                                                            ║")
        else:
            for source, error in errors[-3:]:
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

        # Auto-detect
        self.auto_path = self._detect_auto_path()
        self.channel = self._get_channel_from_folder()

    def _setup_agent_dirs(self):
        for d in [AGENT_DIR, TASKS_DIR, RESULTS_DIR, STATUS_DIR]:
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

    def log(self, msg: str, source: str = "MANAGER", level: str = "INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        emoji = {"INFO": "  ", "WARN": "⚠️", "ERROR": "❌", "SUCCESS": "✅", "TASK": "📋"}.get(level, "  ")
        print(f"[{timestamp}] [{source}] {emoji} {msg}")

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
        elif status.current_step == "video" and status.videos_missing:
            self._distribute_tasks(TaskType.VIDEO, project_code, status.videos_missing)

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

    def start_worker(self, worker_id: str) -> bool:
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

            if sys.platform == "win32":
                title = f"{w.worker_type.upper()} {w.worker_num or ''}"
                cmd_args = f"python {script.name}"
                if args:
                    cmd_args += f" {args}"
                cmd = f'start "{title}" cmd /k "cd /d {TOOL_DIR} && {cmd_args}"'
                w.process = subprocess.Popen(cmd, shell=True, cwd=str(TOOL_DIR))
            else:
                cmd_list = [sys.executable, str(script)]
                if args:
                    cmd_list.extend(args.split())
                w.process = subprocess.Popen(cmd_list, cwd=str(TOOL_DIR))

            w.status = WorkerStatus.IDLE
            w.start_time = datetime.now()
            self.log(f"{worker_id} started", worker_id, "SUCCESS")
            return True
        except Exception as e:
            self.log(f"Failed: {e}", worker_id, "ERROR")
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
        w.status = WorkerStatus.STOPPED
        w.current_task = None

    def restart_worker(self, worker_id: str):
        self.log(f"Restarting {worker_id}...", worker_id, "WARN")
        self.stop_worker(worker_id)
        if self.workers[worker_id].worker_type == "chrome":
            self.kill_all_chrome()
        time.sleep(3)
        self.start_worker(worker_id)

    def start_all(self):
        self.kill_all_chrome()
        if self.enable_excel:
            self.start_worker("excel")
            time.sleep(2)
        for i in range(1, self.num_chrome_workers + 1):
            self.start_worker(f"chrome_{i}")
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
        while not self._stop_flag:
            try:
                self.collect_results()

                for task in list(self.tasks.values()):
                    if task.status == TaskStatus.COMPLETED:
                        retry = self.check_and_retry(task)
                        if retry:
                            task.status = TaskStatus.FAILED

                for project in self.scan_projects():
                    if project not in self.project_tasks:
                        self.create_tasks_for_project(project)

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
                            self.num_chrome_workers = num
                            self._init_workers()
                            self.settings.chrome_count = num
                            self.start_all()
                            print(f"  Scaled to {num} Chrome workers")
                        except:
                            pass
                    elif cmd == "set":
                        print(f"\n  SETTINGS:")
                        for k, v in self.settings.get_summary().items():
                            print(f"    {k}: {v}")
                    elif cmd in ("quit", "exit", "q"):
                        break
                    else:
                        print("  Commands: status, tasks, scan, restart, scale, set, quit")

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
