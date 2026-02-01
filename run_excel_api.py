#!/usr/bin/env python3
"""
Run Excel API - Tạo Excel prompts từ SRT bằng API.

=============================================================
  EXCEL API WORKER - Standalone Mode with Agent Protocol
=============================================================

Chạy riêng biệt với Chrome workers, có thể:
1. Quét và tạo Excel cho tất cả projects thiếu
2. Tạo Excel cho 1 project cụ thể
3. Fix/hoàn thiện Excel có [FALLBACK] prompts

Usage:
    python run_excel_api.py                    # Quét và tạo Excel tự động
    python run_excel_api.py KA2-0001           # Tạo Excel cho 1 project
    python run_excel_api.py --fix KA2-0001     # Fix Excel có [FALLBACK]
    python run_excel_api.py --scan             # Chỉ quét, không tạo
    python run_excel_api.py --loop             # Chạy loop liên tục
"""

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
import shutil
import yaml
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Callable

# Add current directory to path
TOOL_DIR = Path(__file__).parent
sys.path.insert(0, str(TOOL_DIR))

# Agent Protocol - giao tiếp với VM Manager
try:
    from modules.agent_protocol import AgentWorker, ErrorType
    AGENT_ENABLED = True
except ImportError:
    AGENT_ENABLED = False
    AgentWorker = None

# Central Logger
try:
    from modules.central_logger import get_logger
    _logger = get_logger("excel")
except ImportError:
    class FakeLogger:
        def info(self, msg): print(f"[excel] {msg}")
        def warn(self, msg): print(f"[excel] WARN: {msg}")
        def error(self, msg): print(f"[excel] ERROR: {msg}")
    _logger = FakeLogger()

# Global agent instance
_agent: Optional['AgentWorker'] = None

# ================================================================================
# CONFIGURATION
# ================================================================================

SCAN_INTERVAL = 60  # Quét mỗi 60 giây

# Auto-detect network paths
# Ưu tiên SMB share (Z:) trước vì ổn định hơn tsclient khi copy file lớn
POSSIBLE_AUTO_PATHS = [
    Path(r"Z:\AUTO"),                              # SMB Share (ưu tiên - ổn định nhất)
    Path(r"Y:\AUTO"),                              # Mapped drive
    Path(r"\\tsclient\D\AUTO"),
    Path(r"\\vmware-host\Shared Folders\D\AUTO"),
    Path(r"\\VBOXSVR\AUTO"),
    Path(r"D:\AUTO"),
]


# ================================================================================
# HELPERS
# ================================================================================

def log(msg: str, level: str = "INFO"):
    """Log với timestamp và gửi đến Agent."""
    global _agent
    timestamp = datetime.now().strftime("%H:%M:%S")
    prefix = {
        "INFO": "   ",
        "WARN": " [WARN]",
        "ERROR": " [FAIL]",
        "SUCCESS": " [OK]",
    }.get(level, "   ")

    # Log to central logger
    full_msg = f"{prefix} {msg}"
    if level == "ERROR":
        _logger.error(full_msg)
    elif level == "WARN":
        _logger.warn(full_msg)
    else:
        _logger.info(full_msg)

    # Gửi đến Agent nếu có
    if _agent and AGENT_ENABLED:
        if level == "ERROR":
            _agent.log_error(msg)
        else:
            _agent.log(msg, level)


def safe_path_exists(path: Path) -> bool:
    """Safely check if path exists (handle network errors)."""
    try:
        return path.exists()
    except (OSError, PermissionError):
        return False


def detect_auto_path() -> Optional[Path]:
    """Detect network AUTO path."""
    for p in POSSIBLE_AUTO_PATHS:
        if safe_path_exists(p):
            log(f"Found AUTO path: {p}")
            return p
    return None


def get_channel_from_folder() -> Optional[str]:
    """Get channel filter from folder name (e.g., KA2-T1 → KA2)."""
    folder = TOOL_DIR.parent.name
    if "-T" in folder:
        return folder.split("-T")[0]
    elif folder.startswith("KA") or folder.startswith("AR"):
        return folder.split("-")[0] if "-" in folder else folder[:3]
    return None


def matches_channel(project_name: str, channel: Optional[str] = None) -> bool:
    """Check if project matches channel filter."""
    if not channel:
        return True
    return project_name.startswith(channel)


def import_from_master(master_dir: Path, name: str, local_projects: Path) -> Optional[Path]:
    """
    Copy project từ master về local để xử lý.

    Args:
        master_dir: Thư mục project trên master
        name: Tên project
        local_projects: Thư mục PROJECTS local

    Returns:
        Path tới project local nếu thành công, None nếu lỗi

    FIX v1.0.46: KHÔNG XÓA local folder nếu đã có Excel hoặc images!
    Bug cũ: Nếu local có Excel nhưng thiếu SRT → xóa hết rồi import lại.
    """
    local_dir = local_projects / name

    # Đã có trong local rồi - kiểm tra CẢ SRT, Excel VÀ images
    if local_dir.exists():
        srt_path = local_dir / f"{name}.srt"
        excel_path = local_dir / f"{name}_prompts.xlsx"
        img_dir = local_dir / "img"

        # Nếu có SRT → OK, dùng local
        if srt_path.exists():
            return local_dir

        # Nếu có Excel → KHÔNG XÓA! Đã có công việc rồi
        if excel_path.exists():
            log(f"[IMPORT] {name}: Local has Excel, keeping existing work")
            return local_dir

        # Nếu có images → KHÔNG XÓA! Đã tạo ảnh rồi
        if img_dir.exists():
            img_files = list(img_dir.glob("*.png")) + list(img_dir.glob("*.jpg"))
            if len(img_files) > 0:
                log(f"[IMPORT] {name}: Local has {len(img_files)} images, keeping existing work")
                return local_dir

    # Copy từ master (chỉ khi local KHÔNG có Excel hoặc images)
    try:
        log(f"[IMPORT] Copying {name} from master to local...")
        local_projects.mkdir(parents=True, exist_ok=True)

        if local_dir.exists():
            # Double-check: KHÔNG XÓA nếu có Excel hoặc images
            excel_path = local_dir / f"{name}_prompts.xlsx"
            img_dir = local_dir / "img"
            if excel_path.exists():
                log(f"[IMPORT] {name}: ABORT - Local has Excel, not deleting!")
                return local_dir
            if img_dir.exists() and len(list(img_dir.glob("*.png"))) > 0:
                log(f"[IMPORT] {name}: ABORT - Local has images, not deleting!")
                return local_dir
            shutil.rmtree(local_dir)

        shutil.copytree(master_dir, local_dir)
        log(f"[IMPORT] Copied: {name}")

        # Delete from master after successful copy (tránh xử lý trùng)
        try:
            shutil.rmtree(master_dir)
            log(f"[IMPORT] Deleted from master: {name}")
        except Exception as e:
            log(f"[IMPORT] Warning - cannot delete from master: {e}", "WARN")

        return local_dir
    except Exception as e:
        log(f"[IMPORT] Error copying {name}: {e}", "ERROR")
        return None


def is_project_complete(project_dir: Path, name: str) -> bool:
    """
    Check if project has completed images (ready to be moved to VISUAL).
    """
    img_dir = project_dir / "img"
    if not img_dir.exists():
        return False

    # Check for scene images
    scene_imgs = list(img_dir.glob("scene_*.png"))
    return len(scene_imgs) > 0


# ================================================================================
# EXCEL API FUNCTIONS
# ================================================================================

def load_config() -> dict:
    """Load config from settings.yaml."""
    cfg = {}
    cfg_file = TOOL_DIR / "config" / "settings.yaml"
    if cfg_file.exists():
        with open(cfg_file, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

    # Collect API keys
    deepseek_key = cfg.get('deepseek_api_key', '')
    if deepseek_key:
        cfg['deepseek_api_keys'] = [deepseek_key]

    return cfg


def has_api_keys(cfg: dict) -> bool:
    """Check if config has any API keys."""
    return bool(
        cfg.get('deepseek_api_keys') or
        cfg.get('groq_api_keys') or
        cfg.get('gemini_api_keys')
    )


def create_excel_with_api(
    project_dir: Path,
    name: str,
    log_callback: Callable = None,
    agent = None
) -> bool:
    """
    Tạo Excel từ SRT bằng Progressive API.

    Args:
        project_dir: Thư mục project
        name: Tên project (e.g., KA2-0001)
        log_callback: Callback để log
        agent: Agent Protocol instance để update status

    Returns:
        True nếu thành công
    """
    if log_callback is None:
        log_callback = lambda msg, level="INFO": log(msg, level)

    excel_path = project_dir / f"{name}_prompts.xlsx"
    srt_path = project_dir / f"{name}.srt"

    # Check SRT exists
    if not srt_path.exists():
        log_callback(f"No SRT file found: {srt_path}", "ERROR")
        return False

    log_callback(f"Creating Excel from SRT (Progressive API)...")

    # Load config
    cfg = load_config()

    if not has_api_keys(cfg):
        log_callback("No API keys configured! Check config/settings.yaml", "ERROR")
        return False

    # Step names for display
    step_names = {
        1: "Story Analysis",
        2: "Story Segments",
        3: "Characters",
        4: "Locations",
        5: "Director Plan",
        6: "Scene Planning",
        7: "Scene Prompts"
    }

    # Wrapper để parse step từ log và update agent
    def log_with_step_tracking(msg, level="INFO"):
        log_callback(msg, level)

        # Parse step number từ message: [STEP X/7]
        if agent and "[STEP" in msg:
            import re
            match = re.search(r'\[STEP\s*(\d+)/7\]', msg)
            if match:
                step_num = int(match.group(1))
                step_name = step_names.get(step_num, f"Step {step_num}")
                agent.update_status(
                    current_step=step_num,
                    step_name=step_name,
                    progress=int(step_num * 100 / 7)
                )

    # === Progressive API ===
    try:
        from modules.progressive_prompts import ProgressivePromptsGenerator

        gen = ProgressivePromptsGenerator(cfg)

        # Run all steps
        api_success = gen.run_all_steps(
            project_dir,
            name,
            log_callback=log_with_step_tracking
        )

        if api_success and excel_path.exists():
            log_callback(f"Excel created successfully!", "SUCCESS")
            return True
        else:
            log_callback("Progressive API incomplete", "WARN")

    except Exception as e:
        log_callback(f"API error: {e}", "ERROR")
        import traceback
        traceback.print_exc()

    # === Fallback ===
    log_callback("Trying fallback method...")

    try:
        cfg['fallback_only'] = True

        from modules.prompts_generator import PromptGenerator
        gen = PromptGenerator(cfg)

        if gen.generate_for_project(project_dir, name, fallback_only=True):
            log_callback("Fallback Excel created", "SUCCESS")
            return True
        else:
            log_callback("Failed to create fallback Excel", "ERROR")
            return False

    except Exception as e:
        log_callback(f"Fallback error: {e}", "ERROR")
        return False


def fix_excel_with_api(
    project_dir: Path,
    name: str,
    log_callback: Callable = None
) -> bool:
    """
    Fix/hoàn thiện Excel có [FALLBACK] prompts.

    Args:
        project_dir: Thư mục project
        name: Tên project
        log_callback: Callback để log

    Returns:
        True nếu thành công
    """
    if log_callback is None:
        log_callback = lambda msg, level="INFO": log(msg, level)

    excel_path = project_dir / f"{name}_prompts.xlsx"

    if not excel_path.exists():
        log_callback(f"No Excel found, creating new...", "WARN")
        return create_excel_with_api(project_dir, name, log_callback)

    log_callback(f"Fixing Excel with API...")

    # Backup first
    backup_path = excel_path.with_suffix('.xlsx.backup')
    shutil.copy2(excel_path, backup_path)
    log_callback(f"Backed up to {backup_path.name}")

    # Load config
    cfg = load_config()

    if not has_api_keys(cfg):
        log_callback("No API keys, keeping existing fallback prompts", "WARN")
        backup_path.unlink()
        return True

    try:
        from modules.progressive_prompts import ProgressivePromptsGenerator

        gen = ProgressivePromptsGenerator(cfg)

        # Run all steps (will skip completed steps)
        api_success = gen.run_all_steps(
            project_dir,
            name,
            log_callback=lambda msg, level="INFO": log_callback(msg, level)
        )

        if api_success:
            log_callback(f"Excel fixed successfully!", "SUCCESS")
            backup_path.unlink()
            return True
        else:
            log_callback("API incomplete, keeping partial results", "WARN")
            return True

    except Exception as e:
        log_callback(f"Fix error: {e}", "ERROR")
        # Restore backup
        shutil.copy2(backup_path, excel_path)
        log_callback("Restored from backup")
        return False


def has_excel_with_prompts(project_dir: Path, name: str) -> bool:
    """Check if project has Excel with prompts."""
    excel_path = project_dir / f"{name}_prompts.xlsx"
    if not excel_path.exists():
        return False

    try:
        from modules.excel_manager import PromptWorkbook
        wb = PromptWorkbook(str(excel_path))
        wb.load_or_create()  # PHẢI load trước khi dùng
        scenes = wb.get_scenes()
        return any(s.img_prompt for s in scenes)
    except:
        return False


def needs_api_completion(project_dir: Path, name: str) -> bool:
    """Check if Excel has [FALLBACK] prompts that need API completion."""
    excel_path = project_dir / f"{name}_prompts.xlsx"
    if not excel_path.exists():
        return False

    try:
        from modules.excel_manager import PromptWorkbook
        wb = PromptWorkbook(str(excel_path))
        wb.load_or_create()  # PHẢI load trước khi dùng
        scenes = wb.get_scenes()
        return any("[FALLBACK]" in (s.img_prompt or "") for s in scenes)
    except:
        return False


def get_excel_progress(project_dir: Path, name: str) -> dict:
    """
    Đọc tiến độ Excel từ processing_status sheet.

    Returns:
        {
            'total_progress': 57.1,
            'current_step': 'step_4',
            'incomplete_steps': ['step_4', 'step_5', ...],
            'incomplete_details': [...],
            'flow_project_url': 'https://...',
            'can_resume': True,
            'is_complete': False
        }
    """
    excel_path = project_dir / f"{name}_prompts.xlsx"
    if not excel_path.exists():
        return {
            'total_progress': 0.0,
            'current_step': None,
            'incomplete_steps': [],
            'incomplete_details': [],
            'flow_project_url': '',
            'can_resume': False,
            'is_complete': False
        }

    try:
        from modules.excel_manager import PromptWorkbook
        wb = PromptWorkbook(str(excel_path))
        wb.load_or_create()
        return wb.get_resume_info()
    except Exception as e:
        log(f"Error getting Excel progress for {name}: {e}", "WARN")
        return {
            'total_progress': 0.0,
            'current_step': None,
            'incomplete_steps': [],
            'incomplete_details': [],
            'flow_project_url': '',
            'can_resume': False,
            'is_complete': False
        }


# ================================================================================
# SCANNER
# ================================================================================

class ExcelAPIWorker:
    """Worker để quét và tạo Excel với Agent Protocol."""

    def __init__(self):
        global _agent

        self.auto_path = detect_auto_path()
        self.channel = get_channel_from_folder()

        if self.auto_path:
            self.master_projects = self.auto_path / "ve3-tool-simple" / "PROJECTS"
        else:
            self.master_projects = None

        self.local_projects = TOOL_DIR / "PROJECTS"

        # Khởi tạo Agent để giao tiếp với VM Manager
        if AGENT_ENABLED:
            _agent = AgentWorker("excel")
            _agent.start_status_updater(interval=5)
            _agent.update_status(state="idle")
            log("Agent Protocol enabled - connected to VM Manager")
        else:
            _agent = None

        # Statistics
        self.completed_count = 0
        self.failed_count = 0

    def scan_projects_needing_excel(self) -> List[tuple]:
        """
        Scan for projects that need Excel creation or completion.

        Returns:
            List of (project_dir, name, status, progress) tuples
            status: "create_new", "resume", or "fix_fallback"
            progress: dict from get_excel_progress()
        """
        results = []

        # Scan local projects
        if self.local_projects.exists():
            for item in self.local_projects.iterdir():
                if not item.is_dir():
                    continue

                name = item.name
                if not matches_channel(name, self.channel):
                    continue

                srt_path = item / f"{name}.srt"
                if not srt_path.exists():
                    continue

                excel_path = item / f"{name}_prompts.xlsx"

                if not excel_path.exists():
                    # Case 1: CHƯA CÓ EXCEL - Tạo mới
                    results.append((item, name, "create_new", None))
                else:
                    # Case 2: ĐÃ CÓ EXCEL - Check progress
                    progress = get_excel_progress(item, name)

                    if progress['is_complete']:
                        # Hoàn thành 100% - Skip
                        pass
                    elif progress['can_resume']:
                        # Đang làm dở - Resume
                        results.append((item, name, "resume", progress))
                    elif needs_api_completion(item, name):
                        # Có [FALLBACK] - Fix
                        results.append((item, name, "fix_fallback", progress))
                    elif not has_excel_with_prompts(item, name):
                        # Excel rỗng hoặc lỗi - Tạo lại
                        results.append((item, name, "create_new", None))

        # Scan master projects (if accessible) - IMPORT to local before processing
        if self.master_projects and safe_path_exists(self.master_projects):
            try:
                for item in self.master_projects.iterdir():
                    if not item.is_dir():
                        continue

                    name = item.name
                    if not matches_channel(name, self.channel):
                        continue

                    # Skip if already in local results
                    if any(r[1] == name for r in results):
                        continue

                    # Skip if already in local folder
                    local_check = self.local_projects / name
                    if local_check.exists():
                        continue

                    srt_path = item / f"{name}.srt"
                    if not safe_path_exists(srt_path):
                        continue

                    # IMPORT: Copy from master to local BEFORE adding to results
                    local_dir = import_from_master(item, name, self.local_projects)
                    if local_dir is None:
                        continue  # Import failed, skip

                    # Add LOCAL path (not master) to results - Check progress
                    excel_path = local_dir / f"{name}_prompts.xlsx"

                    if not excel_path.exists():
                        # Case 1: CHƯA CÓ EXCEL - Tạo mới
                        results.append((local_dir, name, "create_new", None))
                    else:
                        # Case 2: ĐÃ CÓ EXCEL - Check progress
                        progress = get_excel_progress(local_dir, name)

                        if progress['is_complete']:
                            # Hoàn thành 100% - Skip
                            pass
                        elif progress['can_resume']:
                            # Đang làm dở - Resume
                            results.append((local_dir, name, "resume", progress))
                        elif needs_api_completion(local_dir, name):
                            # Có [FALLBACK] - Fix
                            results.append((local_dir, name, "fix_fallback", progress))
                        elif not has_excel_with_prompts(local_dir, name):
                            # Excel rỗng hoặc lỗi - Tạo lại
                            results.append((local_dir, name, "create_new", None))
            except (OSError, PermissionError) as e:
                log(f"Error scanning master: {e}", "WARN")

        return results

    def process_project(self, project_dir: Path, name: str, status: str, progress: dict = None) -> bool:
        """
        Process a single project với Agent Protocol.

        Args:
            project_dir: Thư mục project
            name: Tên project
            status: "create_new", "resume", hoặc "fix_fallback"
            progress: Dict từ get_excel_progress() nếu status là "resume"

        Returns:
            True nếu thành công
        """
        global _agent

        log(f"")
        log(f"{'='*60}")
        if status == "resume" and progress:
            log(f"Processing: {name} (RESUME - {progress['total_progress']}% done)")
        else:
            log(f"Processing: {name} ({status})")
        log(f"{'='*60}")

        # Update agent status
        task_id = f"excel_{name}_{datetime.now().strftime('%H%M%S')}"
        start_time = time.time()

        if _agent:
            initial_progress = progress.get('total_progress', 0) if progress else 0
            _agent.update_status(
                state="working",
                current_project=name,
                current_task=task_id,
                progress=initial_progress
            )

        # Process
        success = False
        error_msg = ""
        try:
            if status == "create_new":
                # Tạo Excel mới từ đầu
                success = create_excel_with_api(project_dir, name, log, agent=_agent)
            elif status == "resume":
                # Resume từ bước chưa hoàn thành
                log(f"Resuming from step: {progress.get('current_step', 'unknown')}")
                log(f"Incomplete steps: {', '.join(progress.get('incomplete_steps', []))}")
                if progress.get('flow_project_url'):
                    log(f"Reusing Flow project: {progress['flow_project_url']}")
                success = create_excel_with_api(project_dir, name, log, agent=_agent)
            elif status == "fix_fallback":
                # Fix Excel có [FALLBACK] prompts
                success = fix_excel_with_api(project_dir, name, log)
        except Exception as e:
            error_msg = str(e)
            log(f"Exception: {e}", "ERROR")

        # Calculate duration
        duration = time.time() - start_time

        # Report result to Agent
        if _agent:
            if success:
                self.completed_count += 1
                _agent.report_success(
                    task_id=task_id,
                    project_code=name,
                    task_type="excel",
                    duration=duration,
                    details={
                        "status": status,
                        "initial_progress": progress.get('total_progress', 0) if progress else 0
                    }
                )
            else:
                self.failed_count += 1
                _agent.report_failure(
                    task_id=task_id,
                    project_code=name,
                    task_type="excel",
                    error=error_msg or f"Failed to process {status}",
                    duration=duration,
                    details={
                        "status": status,
                        "initial_progress": progress.get('total_progress', 0) if progress else 0
                    }
                )

            # Update status back to idle
            _agent.update_status(
                state="idle",
                current_project="",
                current_task="",
                progress=100 if success else 0
            )

        return success

    def run_once(self) -> int:
        """
        Scan và process một lần.

        Returns:
            Số projects đã xử lý
        """
        log(f"Scanning for projects needing Excel...")

        projects = self.scan_projects_needing_excel()

        if not projects:
            log(f"No projects need Excel creation")
            return 0

        log(f"Found {len(projects)} projects:")
        for project_dir, name, status, progress in projects:
            if status == "resume" and progress:
                log(f"  - {name}: {status} ({progress['total_progress']}% done)")
            else:
                log(f"  - {name}: {status}")

        processed = 0
        for project_dir, name, status, progress in projects:
            try:
                if self.process_project(project_dir, name, status, progress):
                    processed += 1
            except KeyboardInterrupt:
                log("Interrupted by user")
                break
            except Exception as e:
                log(f"Error processing {name}: {e}", "ERROR")

        log(f"")
        log(f"Processed {processed}/{len(projects)} projects", "SUCCESS")
        return processed

    def run_loop(self):
        """Run continuous scan loop với Agent Protocol."""
        global _agent

        log(f"")
        log(f"{'='*60}")
        log(f"  EXCEL API WORKER - Continuous Mode")
        log(f"{'='*60}")
        log(f"  Channel: {self.channel or 'ALL'}")
        log(f"  Scan interval: {SCAN_INTERVAL}s")
        log(f"  Local: {self.local_projects}")
        log(f"  Master: {self.master_projects or 'Not connected'}")
        log(f"  Agent: {'Enabled' if _agent else 'Disabled'}")
        log(f"")
        log(f"  Mode: CONTINUOUS - Tự động import từ master")
        log(f"{'='*60}")

        cycle = 0
        try:
            while True:
                cycle += 1
                log(f"")
                log(f"[CYCLE {cycle}] Starting scan...")

                try:
                    self.run_once()
                except Exception as e:
                    log(f"Scan error: {e}", "ERROR")

                log(f"")
                log(f"Waiting {SCAN_INTERVAL}s... (Ctrl+C to stop)")

                try:
                    time.sleep(SCAN_INTERVAL)
                except KeyboardInterrupt:
                    log("Stopped by user")
                    break

        finally:
            # Cleanup agent khi thoát
            if _agent:
                log("Closing agent connection...")
                _agent.close()


# ================================================================================
# MAIN
# ================================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Excel API Worker - Tạo Excel prompts từ SRT"
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=None,
        help="Project code (e.g., KA2-0001)"
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Fix Excel có [FALLBACK] prompts"
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Chỉ quét, không tạo"
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Chạy loop liên tục"
    )

    args = parser.parse_args()

    print(f"""
{'='*60}
  EXCEL API WORKER
{'='*60}
""")

    worker = ExcelAPIWorker()

    # Single project mode
    if args.project:
        # Find project directory
        project_dir = worker.local_projects / args.project

        if not project_dir.exists() and worker.master_projects:
            project_dir = worker.master_projects / args.project

        if not project_dir.exists():
            log(f"Project not found: {args.project}", "ERROR")
            sys.exit(1)

        if args.fix:
            success = fix_excel_with_api(project_dir, args.project, log)
        else:
            success = create_excel_with_api(project_dir, args.project, log)

        sys.exit(0 if success else 1)

    # Scan mode
    if args.scan:
        projects = worker.scan_projects_needing_excel()
        if not projects:
            log("No projects need Excel")
        else:
            log(f"Found {len(projects)} projects:")
            for project_dir, name, status, progress in projects:
                if status == "resume" and progress:
                    log(f"  - {name}: {status} ({progress['total_progress']}% done)")
                else:
                    log(f"  - {name}: {status}")
        sys.exit(0)

    # Loop mode
    if args.loop:
        worker.run_loop()
    else:
        # Run once
        worker.run_once()


if __name__ == "__main__":
    main()
