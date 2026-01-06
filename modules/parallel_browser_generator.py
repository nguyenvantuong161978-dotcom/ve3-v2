"""
VE3 Tool - Parallel Browser Image Generator
============================================
Tao anh bang nhieu trinh duyet chay song song.

Features:
- Headless mode: Chay an khong hien UI
- Parallel processing: Nhieu browser cung luc
- Session isolation: Moi project/voice 1 browser rieng
- Auto retry: Tu dong thu lai khi loi
"""

import os
import time
import json
import threading
import tempfile
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Callable
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from queue import Queue
import uuid

# Browser driver imports - prefer undetected-chromedriver
DRIVER_TYPE = None  # "undetected", "selenium", or None

try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        TimeoutException,
        WebDriverException,
        JavascriptException
    )
    DRIVER_TYPE = "undetected"
except ImportError:
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import (
            TimeoutException,
            WebDriverException,
            JavascriptException
        )
        DRIVER_TYPE = "selenium"
    except ImportError:
        pass

SELENIUM_AVAILABLE = DRIVER_TYPE is not None


@dataclass
class BrowserSession:
    """Dai dien cho mot browser session."""
    session_id: str
    project_name: str
    driver: Any = None
    profile_dir: str = ""
    is_ready: bool = False
    is_logged_in: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    images_generated: int = 0
    errors: List[str] = field(default_factory=list)


@dataclass
class GenerationTask:
    """Task tao anh."""
    task_id: str
    project_name: str
    prompts: List[str]
    output_dir: Path
    prefix: str = "ve3"
    priority: int = 0


@dataclass
class GenerationResult:
    """Ket qua tao anh."""
    task_id: str
    project_name: str
    success_count: int = 0
    failed_count: int = 0
    images: List[Dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class ParallelBrowserGenerator:
    """
    Quan ly nhieu browser de tao anh song song.

    Usage:
        generator = ParallelBrowserGenerator(max_browsers=3, headless=True)
        generator.start()

        # Add tasks
        generator.add_task(project="voice1", prompts=["prompt1", "prompt2"])
        generator.add_task(project="voice2", prompts=["prompt3", "prompt4"])

        # Wait for completion
        results = generator.wait_all()

        generator.stop()
    """

    FLOW_URL = "https://labs.google/fx/vi/tools/flow"

    def __init__(
        self,
        max_browsers: int = 2,
        headless: bool = False,
        base_profile_dir: Optional[str] = None,
        download_base_dir: Optional[Path] = None,
        verbose: bool = True,
        login_timeout: int = 120,
        generation_timeout: int = 90
    ):
        """
        Khoi tao ParallelBrowserGenerator.

        Args:
            max_browsers: So luong browser toi da chay song song
            headless: Chay an (True) hoac hien UI (False)
            base_profile_dir: Thu muc goc chua Chrome profiles
            download_base_dir: Thu muc goc luu anh download
            verbose: In log chi tiet
            login_timeout: Thoi gian cho login (giay)
            generation_timeout: Thoi gian cho tao anh (giay)
        """
        if not SELENIUM_AVAILABLE:
            raise ImportError(
                "Selenium chua duoc cai dat. Chay: pip install selenium"
            )

        self.max_browsers = max_browsers
        self.headless = headless
        self.verbose = verbose
        self.login_timeout = login_timeout
        self.generation_timeout = generation_timeout

        # Directories
        self.base_profile_dir = Path(base_profile_dir) if base_profile_dir else \
            Path(tempfile.gettempdir()) / "ve3_chrome_profiles"
        self.download_base_dir = download_base_dir or \
            Path.home() / "Downloads" / "ve3_parallel"

        self.base_profile_dir.mkdir(parents=True, exist_ok=True)
        self.download_base_dir.mkdir(parents=True, exist_ok=True)

        # State
        self.sessions: Dict[str, BrowserSession] = {}
        self.task_queue: Queue = Queue()
        self.results: Dict[str, GenerationResult] = {}
        self.is_running = False
        self._lock = threading.Lock()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._worker_threads: List[threading.Thread] = []

        # Callbacks
        self.on_task_complete: Optional[Callable[[GenerationResult], None]] = None
        self.on_image_generated: Optional[Callable[[str, str, str], None]] = None

    def _log(self, message: str, session_id: str = None) -> None:
        """Print log message."""
        if self.verbose:
            timestamp = datetime.now().strftime("%H:%M:%S")
            prefix = f"[{session_id}]" if session_id else "[Main]"
            print(f"[{timestamp}] {prefix} {message}")

    def _get_js_script(self) -> str:
        """Doc file JavaScript automation."""
        script_path = Path(__file__).parent.parent / "scripts" / "ve3_browser_automation.js"

        if script_path.exists():
            with open(script_path, "r", encoding="utf-8") as f:
                return f.read()

        raise FileNotFoundError(f"JS script not found: {script_path}")

    def _create_driver(self, session: BrowserSession) -> Any:
        """
        Tao Chrome WebDriver cho session.

        Uu tien su dung undetected-chromedriver de tranh bi Google detect.
        Fallback sang selenium neu khong co undetected-chromedriver.
        """
        # Profile directory rieng cho moi session
        session.profile_dir = str(self.base_profile_dir / session.session_id)
        Path(session.profile_dir).mkdir(parents=True, exist_ok=True)

        # Download directory
        download_dir = self.download_base_dir / session.project_name
        download_dir.mkdir(parents=True, exist_ok=True)

        if DRIVER_TYPE == "undetected":
            # Su dung undetected-chromedriver (tot nhat cho automation)
            self._log(f"Using undetected-chromedriver", session.session_id)

            options = uc.ChromeOptions()
            options.add_argument(f"--user-data-dir={session.profile_dir}")

            if self.headless:
                options.add_argument("--headless=new")
                self._log(f"Headless mode enabled", session.session_id)

            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1920,1080")

            if self.headless:
                options.add_argument("--disable-gpu")

            # Download prefs
            prefs = {
                "download.default_directory": str(download_dir),
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
            }
            options.add_experimental_option("prefs", prefs)

            # Tao driver voi undetected-chromedriver
            driver = uc.Chrome(
                options=options,
                use_subprocess=True,
                version_main=None  # Auto-detect Chrome version
            )

            return driver

        else:
            # Fallback: Su dung selenium thuong
            self._log(f"Using standard selenium (consider installing undetected-chromedriver)", session.session_id)

            from selenium.webdriver.chrome.options import Options

            options = Options()
            options.add_argument(f"--user-data-dir={session.profile_dir}")

            if self.headless:
                options.add_argument("--headless=new")
                self._log(f"Headless mode enabled", session.session_id)

            # Chong phat hien automation (khong hoan hao nhu undetected)
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)
            options.add_argument("--window-size=1920,1080")

            if self.headless:
                options.add_argument("--disable-gpu")
                options.add_argument("--disable-software-rasterizer")

            prefs = {
                "download.default_directory": str(download_dir),
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
            }
            options.add_experimental_option("prefs", prefs)

            driver = webdriver.Chrome(options=options)

            # An navigator.webdriver
            driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            return driver

    def _init_session(self, project_name: str) -> BrowserSession:
        """Khoi tao mot browser session moi."""
        session_id = f"{project_name}_{uuid.uuid4().hex[:8]}"
        session = BrowserSession(
            session_id=session_id,
            project_name=project_name
        )

        self._log(f"Initializing session for project: {project_name}", session_id)

        try:
            # Tao driver
            session.driver = self._create_driver(session)

            # Navigate to Flow
            self._log(f"Navigate to: {self.FLOW_URL}", session_id)
            session.driver.get(self.FLOW_URL)

            time.sleep(3)

            # Inject JS
            js_script = self._get_js_script()
            session.driver.execute_script(js_script)
            self._log("JS script injected", session_id)

            session.is_ready = True

            with self._lock:
                self.sessions[session_id] = session

            return session

        except Exception as e:
            self._log(f"Failed to init session: {e}", session_id)
            if session.driver:
                try:
                    session.driver.quit()
                except:
                    pass
            raise

    def _wait_for_login(self, session: BrowserSession) -> bool:
        """Doi nguoi dung login."""
        if session.is_logged_in:
            return True

        self._log(f"Waiting for login (timeout: {self.login_timeout}s)...", session.session_id)

        if not self.headless:
            self._log("Please login to Google account in the browser", session.session_id)

        start = time.time()

        while time.time() - start < self.login_timeout:
            try:
                # Check for textarea (chi co khi da login)
                session.driver.find_element(By.CSS_SELECTOR, "textarea")
                session.is_logged_in = True
                self._log("Login detected!", session.session_id)
                return True
            except:
                pass

            time.sleep(2)

        self._log("Login timeout", session.session_id)
        return False

    def _escape_js_string(self, s: str) -> str:
        """Escape chuoi cho JavaScript."""
        return (s
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("'", "\\'")
            .replace("\n", "\\n")
            .replace("\r", "\\r"))

    def _generate_images(self, session: BrowserSession, task: GenerationTask) -> GenerationResult:
        """Tao anh cho mot task."""
        result = GenerationResult(
            task_id=task.task_id,
            project_name=task.project_name
        )

        start_time = time.time()

        # Ensure login
        if not self._wait_for_login(session):
            result.errors.append("Login failed")
            return result

        self._log(f"Generating {len(task.prompts)} images...", session.session_id)

        for i, prompt in enumerate(task.prompts):
            try:
                self._log(f"[{i+1}/{len(task.prompts)}] {prompt[:50]}...", session.session_id)

                # Goi JS generateOne
                escaped_prompt = self._escape_js_string(prompt)

                js_result = session.driver.execute_async_script(f"""
                    const callback = arguments[arguments.length - 1];
                    const timeout = setTimeout(() => {{
                        callback({{ success: false, error: 'Timeout' }});
                    }}, {self.generation_timeout * 1000});

                    VE3.generateOne("{escaped_prompt}", {{
                        download: true,
                        outputName: "{task.prefix}_{i+1}_{int(time.time())}.png"
                    }}).then(r => {{
                        clearTimeout(timeout);
                        callback(r);
                    }}).catch(e => {{
                        clearTimeout(timeout);
                        callback({{ success: false, error: e.message }});
                    }});
                """)

                if js_result and js_result.get("success"):
                    result.success_count += 1
                    session.images_generated += 1

                    for img in js_result.get("images", []):
                        result.images.append({
                            "prompt": prompt,
                            "url": img.get("url"),
                            "seed": img.get("seed")
                        })

                    if self.on_image_generated:
                        self.on_image_generated(
                            task.project_name,
                            prompt,
                            js_result.get("images", [{}])[0].get("url", "")
                        )
                else:
                    result.failed_count += 1
                    error = js_result.get("error", "Unknown error") if js_result else "No response"
                    result.errors.append(f"Prompt {i+1}: {error}")
                    session.errors.append(error)

                # Delay giua cac anh
                if i < len(task.prompts) - 1:
                    time.sleep(2)

            except Exception as e:
                result.failed_count += 1
                result.errors.append(f"Prompt {i+1}: {str(e)}")
                self._log(f"Error: {e}", session.session_id)

        result.duration_seconds = time.time() - start_time

        self._log(
            f"Completed: {result.success_count} success, {result.failed_count} failed "
            f"in {result.duration_seconds:.1f}s",
            session.session_id
        )

        return result

    def _worker(self) -> None:
        """Worker thread xu ly tasks."""
        session: Optional[BrowserSession] = None

        while self.is_running:
            try:
                # Lay task tu queue
                task = self.task_queue.get(timeout=1)

                if task is None:  # Shutdown signal
                    break

                # Init session neu chua co
                if session is None or session.project_name != task.project_name:
                    if session:
                        self._close_session(session)
                    session = self._init_session(task.project_name)

                # Generate images
                result = self._generate_images(session, task)

                # Luu ket qua
                with self._lock:
                    self.results[task.task_id] = result

                # Callback
                if self.on_task_complete:
                    self.on_task_complete(result)

                self.task_queue.task_done()

            except Exception as e:
                if "Empty" not in str(type(e).__name__):
                    self._log(f"Worker error: {e}")

        # Cleanup
        if session:
            self._close_session(session)

    def _close_session(self, session: BrowserSession) -> None:
        """Dong mot session."""
        self._log(f"Closing session", session.session_id)

        try:
            if session.driver:
                session.driver.quit()
        except:
            pass

        with self._lock:
            if session.session_id in self.sessions:
                del self.sessions[session.session_id]

    def start(self) -> None:
        """Khoi dong parallel generator."""
        if self.is_running:
            return

        self._log(f"Starting with {self.max_browsers} browser(s), headless={self.headless}")

        self.is_running = True

        # Khoi dong worker threads
        for i in range(self.max_browsers):
            thread = threading.Thread(target=self._worker, daemon=True, name=f"Worker-{i}")
            thread.start()
            self._worker_threads.append(thread)

        self._log(f"Started {len(self._worker_threads)} worker threads")

    def stop(self) -> None:
        """Dung tat ca."""
        self._log("Stopping...")

        self.is_running = False

        # Gui shutdown signal
        for _ in self._worker_threads:
            self.task_queue.put(None)

        # Cho threads ket thuc
        for thread in self._worker_threads:
            thread.join(timeout=10)

        self._worker_threads.clear()

        # Dong tat ca sessions
        with self._lock:
            for session in list(self.sessions.values()):
                self._close_session(session)

        self._log("Stopped")

    def add_task(
        self,
        project: str,
        prompts: List[str],
        output_dir: Optional[Path] = None,
        prefix: str = "ve3",
        priority: int = 0
    ) -> str:
        """
        Them task vao queue.

        Args:
            project: Ten project (vd: voice1, video2)
            prompts: Danh sach prompts
            output_dir: Thu muc output (mac dinh: download_base_dir/project)
            prefix: Prefix ten file
            priority: Do uu tien (chua implement)

        Returns:
            task_id
        """
        task_id = f"{project}_{uuid.uuid4().hex[:8]}"

        task = GenerationTask(
            task_id=task_id,
            project_name=project,
            prompts=prompts,
            output_dir=output_dir or (self.download_base_dir / project),
            prefix=prefix,
            priority=priority
        )

        self.task_queue.put(task)
        self._log(f"Added task {task_id}: {len(prompts)} prompts for {project}")

        return task_id

    def wait_all(self, timeout: Optional[float] = None) -> Dict[str, GenerationResult]:
        """
        Doi tat ca tasks hoan thanh.

        Args:
            timeout: Thoi gian cho toi da (None = vo han)

        Returns:
            Dict[task_id, result]
        """
        self._log("Waiting for all tasks to complete...")
        self.task_queue.join()
        return dict(self.results)

    def get_status(self) -> Dict[str, Any]:
        """Lay trang thai hien tai."""
        with self._lock:
            return {
                "is_running": self.is_running,
                "active_sessions": len(self.sessions),
                "pending_tasks": self.task_queue.qsize(),
                "completed_tasks": len(self.results),
                "sessions": [
                    {
                        "id": s.session_id,
                        "project": s.project_name,
                        "is_ready": s.is_ready,
                        "is_logged_in": s.is_logged_in,
                        "images_generated": s.images_generated
                    }
                    for s in self.sessions.values()
                ]
            }

    def cleanup_profiles(self) -> None:
        """Xoa tat ca Chrome profiles tam."""
        if self.base_profile_dir.exists():
            shutil.rmtree(self.base_profile_dir, ignore_errors=True)
            self._log(f"Cleaned up profiles: {self.base_profile_dir}")


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def generate_parallel(
    projects: Dict[str, List[str]],
    max_browsers: int = 2,
    headless: bool = False,
    verbose: bool = True
) -> Dict[str, GenerationResult]:
    """
    Tao anh song song cho nhieu projects.

    Args:
        projects: Dict[project_name, list_of_prompts]
        max_browsers: So browser toi da
        headless: Chay an
        verbose: In log

    Returns:
        Dict[project_name, result]

    Example:
        results = generate_parallel({
            "voice1": ["prompt1", "prompt2"],
            "voice2": ["prompt3", "prompt4", "prompt5"]
        }, max_browsers=2)
    """
    generator = ParallelBrowserGenerator(
        max_browsers=max_browsers,
        headless=headless,
        verbose=verbose
    )

    try:
        generator.start()

        # Add all tasks
        task_to_project = {}
        for project, prompts in projects.items():
            task_id = generator.add_task(project=project, prompts=prompts)
            task_to_project[task_id] = project

        # Wait for completion
        results = generator.wait_all()

        # Map results back to project names
        project_results = {}
        for task_id, result in results.items():
            project_results[result.project_name] = result

        return project_results

    finally:
        generator.stop()


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import sys

    print("""
+================================================================+
|     PARALLEL BROWSER IMAGE GENERATOR - VE3 TOOL                |
+================================================================+
|  Tao anh song song voi nhieu trinh duyet                       |
|                                                                |
|  Usage:                                                        |
|    python parallel_browser_generator.py [options] prompts.json |
|                                                                |
|  Options:                                                      |
|    --browsers N    So luong browser (default: 2)               |
|    --headless      Chay an khong hien UI                       |
|                                                                |
|  prompts.json format:                                          |
|    {                                                           |
|      "voice1": ["prompt1", "prompt2"],                         |
|      "voice2": ["prompt3", "prompt4"]                          |
|    }                                                           |
+================================================================+
""")

    if not SELENIUM_AVAILABLE:
        print("Error: Selenium chua duoc cai dat")
        print("Chay: pip install selenium")
        sys.exit(1)

    # Parse args
    headless = "--headless" in sys.argv
    max_browsers = 2

    for i, arg in enumerate(sys.argv):
        if arg == "--browsers" and i + 1 < len(sys.argv):
            max_browsers = int(sys.argv[i + 1])

    # Find prompts file
    prompts_file = None
    for arg in sys.argv[1:]:
        if arg.endswith(".json") and not arg.startswith("-"):
            prompts_file = Path(arg)
            break

    if not prompts_file or not prompts_file.exists():
        print("Vui long cung cap file prompts.json")
        print("\nVi du noi dung file:")
        print(json.dumps({
            "voice1": ["a cute cat", "a happy dog"],
            "voice2": ["beautiful sunset", "mountain landscape"]
        }, indent=2))
        sys.exit(1)

    # Load prompts
    with open(prompts_file, "r", encoding="utf-8") as f:
        projects = json.load(f)

    print(f"\nLoaded {len(projects)} projects:")
    for name, prompts in projects.items():
        print(f"  - {name}: {len(prompts)} prompts")

    print(f"\nStarting with {max_browsers} browsers, headless={headless}")
    print("NOTE: If not headless, please login in each browser window\n")

    # Run
    results = generate_parallel(
        projects=projects,
        max_browsers=max_browsers,
        headless=headless
    )

    # Print results
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    total_success = 0
    total_failed = 0

    for project, result in results.items():
        print(f"\n{project}:")
        print(f"  Success: {result.success_count}")
        print(f"  Failed:  {result.failed_count}")
        print(f"  Time:    {result.duration_seconds:.1f}s")

        total_success += result.success_count
        total_failed += result.failed_count

        if result.errors:
            print(f"  Errors:")
            for e in result.errors[:3]:
                print(f"    - {e}")

    print("\n" + "-" * 60)
    print(f"TOTAL: {total_success} success, {total_failed} failed")
