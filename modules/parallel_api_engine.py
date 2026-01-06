"""
VE3 Tool - Parallel API Engine
==============================
Chạy nhiều voice song song với API mode.
Mỗi voice có Chrome profile riêng, chạy headless.

Features:
- Mỗi voice = 1 worker thread độc lập
- Mỗi worker có Chrome profile riêng (headless)
- Token được quản lý riêng cho từng worker
- Không can thiệp vào cửa sổ khác
"""

import os
import sys
import time
import json
import shutil
import threading
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field


@dataclass
class VoiceTask:
    """Một task xử lý voice."""
    voice_path: Path
    project_dir: Path
    worker_id: int
    profile_path: Path
    status: str = "pending"  # pending, running, completed, failed
    progress: float = 0.0
    message: str = ""
    result: Dict = field(default_factory=dict)
    start_time: float = 0.0
    end_time: float = 0.0


@dataclass
class WorkerState:
    """Trạng thái của một worker."""
    worker_id: int
    profile_path: Path
    token: str = ""
    project_id: str = ""
    token_time: float = 0.0
    browser: Any = None
    is_busy: bool = False
    current_task: Optional[VoiceTask] = None


class ParallelAPIEngine:
    """
    Engine chạy nhiều voice song song với API mode.

    Mỗi worker:
    - Có Chrome profile riêng (copy từ template hoặc tạo mới)
    - Chạy Chrome headless để lấy token
    - Sử dụng API để tạo ảnh (không cần browser UI)
    """

    TOKEN_EXPIRY_SECONDS = 50 * 60  # Token hết hạn sau 50 phút

    def __init__(
        self,
        num_workers: int = 3,
        chrome_path: str = None,
        base_profile_path: str = None,
        config_path: str = None,
        headless: bool = True,
        verbose: bool = True
    ):
        """
        Khởi tạo ParallelAPIEngine.

        Args:
            num_workers: Số worker chạy song song (1-5)
            chrome_path: Đường dẫn Chrome executable
            base_profile_path: Profile template để copy (hoặc None để tạo mới)
            config_path: Đường dẫn config file
            headless: Chạy Chrome ẩn
            verbose: In log chi tiết
        """
        self.num_workers = max(1, min(num_workers, 5))
        self.headless = headless
        self.verbose = verbose

        # Paths
        self.root_dir = Path(__file__).parent.parent
        self.config_dir = Path(os.environ.get('VE3_CONFIG_DIR', self.root_dir / "config"))
        self.profiles_dir = self.root_dir / "chrome_profiles" / "parallel"
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

        # Chrome path
        self.chrome_path = chrome_path or self._detect_chrome_path()

        # Base profile (template để copy)
        self.base_profile_path = base_profile_path

        # Load config
        self.config = self._load_config(config_path)

        # Workers
        self.workers: List[WorkerState] = []
        self._init_workers()

        # Threading
        self._lock = threading.Lock()
        self._stop_flag = False

        # Callbacks
        self.on_progress: Optional[Callable[[VoiceTask], None]] = None
        self.on_complete: Optional[Callable[[VoiceTask], None]] = None
        self.on_log: Optional[Callable[[str, str], None]] = None

    def _detect_chrome_path(self) -> str:
        """Tự động tìm Chrome."""
        paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        ]
        for p in paths:
            if os.path.exists(p):
                return p
        return paths[0]  # Default Windows path

    def _load_config(self, config_path: str = None) -> Dict:
        """Load config từ file."""
        if config_path:
            path = Path(config_path)
        else:
            path = self.config_dir / "accounts.json"

        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}

    def _init_workers(self):
        """Khởi tạo workers với profiles riêng."""
        self.workers = []

        # Lấy danh sách profile từ config hoặc tạo mới
        chrome_profiles = self.config.get('chrome_profiles', [])

        for i in range(self.num_workers):
            # Tạo profile path cho worker này
            if i < len(chrome_profiles):
                # Dùng profile từ config
                profile_path = Path(chrome_profiles[i])
                if not profile_path.exists():
                    profile_path = self._create_worker_profile(i)
            else:
                # Tạo profile mới
                profile_path = self._create_worker_profile(i)

            worker = WorkerState(
                worker_id=i,
                profile_path=profile_path
            )
            self.workers.append(worker)

        self.log(f"Initialized {len(self.workers)} workers")

    def _create_worker_profile(self, worker_id: int) -> Path:
        """Tạo Chrome profile riêng cho worker."""
        profile_dir = self.profiles_dir / f"worker_{worker_id}"

        if self.base_profile_path and Path(self.base_profile_path).exists():
            # Copy từ base profile
            if not profile_dir.exists():
                self.log(f"Copying profile for worker {worker_id}...")
                shutil.copytree(self.base_profile_path, profile_dir, dirs_exist_ok=True)
        else:
            # Tạo profile rỗng
            profile_dir.mkdir(parents=True, exist_ok=True)

        return profile_dir

    def log(self, message: str, level: str = "INFO"):
        """Log message."""
        if self.verbose:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] [{level}] {message}")

        if self.on_log:
            self.on_log(message, level)

    def _get_token_for_worker(self, worker: WorkerState) -> bool:
        """
        Lấy token cho worker bằng Chrome headless.

        Sử dụng ChromeTokenExtractor với profile riêng.
        """
        from modules.chrome_token_extractor import ChromeTokenExtractor

        self.log(f"[Worker {worker.worker_id}] Getting token...")

        try:
            extractor = ChromeTokenExtractor(
                chrome_path=self.chrome_path,
                profile_path=str(worker.profile_path),
                headless=self.headless,
                timeout=60
            )

            token, project_id, error = extractor.extract_token()

            if token:
                worker.token = token
                worker.project_id = project_id or ""
                worker.token_time = time.time()
                self.log(f"[Worker {worker.worker_id}] Token OK!", "OK")
                return True
            else:
                self.log(f"[Worker {worker.worker_id}] Token failed: {error}", "ERROR")
                return False

        except Exception as e:
            self.log(f"[Worker {worker.worker_id}] Token error: {e}", "ERROR")
            return False

    def _is_token_valid(self, worker: WorkerState) -> bool:
        """Check token còn valid không."""
        if not worker.token:
            return False

        if worker.token_time:
            age = time.time() - worker.token_time
            if age > self.TOKEN_EXPIRY_SECONDS:
                self.log(f"[Worker {worker.worker_id}] Token expired ({int(age/60)} min)")
                worker.token = ""
                return False

        return True

    def _process_voice(self, task: VoiceTask, worker: WorkerState) -> Dict:
        """
        Xử lý một voice với worker được gán.

        Flow:
        1. Check/refresh token
        2. Voice to SRT (nếu cần)
        3. SRT to Prompts (nếu cần)
        4. Prompts to Images (API mode)
        """
        task.status = "running"
        task.start_time = time.time()
        task.message = "Starting..."

        if self.on_progress:
            self.on_progress(task)

        try:
            # 1. Ensure valid token
            if not self._is_token_valid(worker):
                task.message = "Getting token..."
                if self.on_progress:
                    self.on_progress(task)

                if not self._get_token_for_worker(worker):
                    raise Exception("Failed to get token")

            # 2. Import SmartEngine cho xử lý
            from modules.smart_engine import SmartEngine

            # Tạo engine với profile của worker
            engine = SmartEngine(
                config_path=str(self.config_dir / "accounts.json"),
                assigned_profile=str(worker.profile_path)
            )

            # Override token từ worker
            if engine.profiles:
                engine.profiles[0].token = worker.token
                engine.profiles[0].project_id = worker.project_id
                engine.profiles[0].token_time = worker.token_time

            # Progress callback
            def progress_cb(msg):
                task.message = msg
                if self.on_progress:
                    self.on_progress(task)

            # 3. Run engine
            result = engine.run(str(task.voice_path), callback=progress_cb)

            # 4. Update worker token (có thể đã refresh)
            if engine.profiles:
                worker.token = engine.profiles[0].token
                worker.project_id = engine.profiles[0].project_id
                worker.token_time = engine.profiles[0].token_time

            task.result = result
            task.status = "completed"
            task.progress = 100.0
            task.message = "Done!"

        except Exception as e:
            import traceback
            traceback.print_exc()
            task.status = "failed"
            task.result = {"error": str(e)}
            task.message = f"Error: {e}"

        finally:
            task.end_time = time.time()
            worker.is_busy = False
            worker.current_task = None

            if self.on_complete:
                self.on_complete(task)

        return task.result

    def process_voices(
        self,
        voice_paths: List[Path],
        output_dir: Path = None
    ) -> Dict[str, Any]:
        """
        Xử lý nhiều voice song song.

        Args:
            voice_paths: Danh sách file voice
            output_dir: Thư mục output (PROJECTS/)

        Returns:
            Dict với kết quả tổng hợp
        """
        if not voice_paths:
            return {"error": "No voice files"}

        self._stop_flag = False

        # Default output dir
        if output_dir is None:
            output_dir = Path(os.environ.get('VE3_PROJECTS_DIR', self.root_dir / "PROJECTS"))

        # Tạo tasks
        tasks = []
        for i, voice_path in enumerate(voice_paths):
            # Gán worker theo round-robin
            worker_id = i % self.num_workers
            worker = self.workers[worker_id]

            # Project dir cho voice này
            project_name = voice_path.stem
            project_dir = output_dir / project_name

            task = VoiceTask(
                voice_path=voice_path,
                project_dir=project_dir,
                worker_id=worker_id,
                profile_path=worker.profile_path
            )
            tasks.append(task)

        self.log(f"Processing {len(tasks)} voices with {self.num_workers} workers...")

        # Chạy song song
        results = {"success": 0, "failed": 0, "tasks": []}

        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            futures = {}

            for task in tasks:
                if self._stop_flag:
                    break

                worker = self.workers[task.worker_id]
                future = executor.submit(self._process_voice, task, worker)
                futures[future] = task

            # Wait for completion
            for future in as_completed(futures):
                if self._stop_flag:
                    break

                task = futures[future]
                try:
                    result = future.result()
                    if "error" in result:
                        results["failed"] += 1
                    else:
                        results["success"] += result.get("success", 0)
                        results["failed"] += result.get("failed", 0)
                except Exception as e:
                    self.log(f"Task error: {e}", "ERROR")
                    results["failed"] += 1

                results["tasks"].append({
                    "voice": task.voice_path.name,
                    "status": task.status,
                    "result": task.result
                })

        self.log(f"Completed: {results['success']} success, {results['failed']} failed")
        return results

    def stop(self):
        """Dừng tất cả workers."""
        self._stop_flag = True
        self.log("Stopping all workers...")

    def cleanup(self):
        """Dọn dẹp resources."""
        for worker in self.workers:
            if worker.browser:
                try:
                    worker.browser.quit()
                except:
                    pass
                worker.browser = None


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="VE3 Parallel API Engine")
    parser.add_argument("voices", nargs="+", help="Voice files or folder")
    parser.add_argument("--workers", "-w", type=int, default=3, help="Number of workers (1-5)")
    parser.add_argument("--headless", action="store_true", help="Run Chrome headless")
    parser.add_argument("--visible", action="store_true", help="Show Chrome windows")

    args = parser.parse_args()

    # Collect voice files
    voice_paths = []
    for path in args.voices:
        p = Path(path)
        if p.is_dir():
            voice_paths.extend(p.glob("*.mp3"))
            voice_paths.extend(p.glob("*.wav"))
        elif p.exists():
            voice_paths.append(p)

    if not voice_paths:
        print("No voice files found!")
        sys.exit(1)

    print(f"Found {len(voice_paths)} voice files")

    # Create engine
    engine = ParallelAPIEngine(
        num_workers=args.workers,
        headless=not args.visible
    )

    # Progress callback
    def on_progress(task):
        print(f"[Worker {task.worker_id}] {task.voice_path.name}: {task.message}")

    engine.on_progress = on_progress

    # Run
    try:
        results = engine.process_voices(voice_paths)
        print(f"\n=== RESULTS ===")
        print(f"Success: {results['success']}")
        print(f"Failed: {results['failed']}")
    except KeyboardInterrupt:
        engine.stop()
    finally:
        engine.cleanup()
