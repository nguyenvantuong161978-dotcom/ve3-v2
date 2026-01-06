"""
PARALLEL VIDEO PROCESSOR
========================

Hệ thống xử lý nhiều video song song với Chrome Pool.

Kiến trúc:
=========

                    ┌─────────────────────────────────┐
                    │     VIDEO FOLDER (N videos)     │
                    └────────────────┬────────────────┘
                                     │
                    ┌────────────────▼────────────────┐
                    │    ParallelVideoProcessor       │
                    │    (Orchestrator - Main Thread) │
                    └────────────────┬────────────────┘
                                     │
         ┌───────────────────────────┼───────────────────────────┐
         │                           │                           │
    ┌────▼────┐                 ┌────▼────┐                 ┌────▼────┐
    │ Video 1 │                 │ Video 2 │                 │ Video N │
    │ Thread  │                 │ Thread  │                 │ Thread  │
    └────┬────┘                 └────┬────┘                 └────┬────┘
         │                           │                           │
         └───────────────────────────┼───────────────────────────┘
                                     │
                    ┌────────────────▼────────────────┐
                    │         CHROME POOL             │
                    │   (5 Chrome Instances - Shared) │
                    │                                 │
                    │  ┌─────┐ ┌─────┐ ┌─────┐       │
                    │  │ C1  │ │ C2  │ │ C3  │ ...   │
                    │  └─────┘ └─────┘ └─────┘       │
                    │                                 │
                    │  checkout() ─► token_queue     │
                    │  checkin()  ◄─ return          │
                    └─────────────────────────────────┘

Flow:
====
1. Video thread cần Chrome → gọi pool.checkout()
2. Nếu Chrome available → trả về ngay
3. Nếu hết Chrome → đợi (queue)
4. Xong việc → pool.checkin(chrome)

Token Extraction:
================
- Chỉ 1 Chrome extract token tại 1 thời điểm
- Dùng Lock để serialize token extraction
- Cache token để tái sử dụng

Author: VE3 Tool
"""

import threading
import queue
import time
import logging
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime, timedelta


@dataclass
class ChromeInstance:
    """Đại diện 1 Chrome instance trong pool"""
    id: int
    profile_path: str
    token: Optional[str] = None
    project_id: Optional[str] = None
    token_expires: Optional[datetime] = None
    is_busy: bool = False
    driver: Any = None  # WebDriver instance
    last_used: Optional[datetime] = None
    error_count: int = 0

    def is_token_valid(self) -> bool:
        """Kiểm tra token còn hạn không (55 phút)"""
        if not self.token or not self.token_expires:
            return False
        return datetime.now() < self.token_expires

    def set_token(self, token: str, project_id: str):
        """Set token mới với expiry 55 phút"""
        self.token = token
        self.project_id = project_id
        self.token_expires = datetime.now() + timedelta(minutes=55)
        self.error_count = 0


class ChromePool:
    """
    Thread-safe Chrome Pool Manager

    Quản lý N Chrome instances, cho phép checkout/checkin như connection pool.
    """

    def __init__(
        self,
        chrome_profiles: List[str],
        chrome_path: str,
        token_extractor_class: Any,
        logger: Optional[logging.Logger] = None,
        headless: bool = False
    ):
        """
        Args:
            chrome_profiles: List đường dẫn profile Chrome
            chrome_path: Path tới chrome.exe
            token_extractor_class: Class để extract token (ChromeAutoToken hoặc ChromeTokenExtractor)
            logger: Logger instance
            headless: Chạy Chrome ẩn (cũng áp dụng cho lấy token)
        """
        self.logger = logger or logging.getLogger(__name__)
        self.chrome_path = chrome_path
        self.token_extractor_class = token_extractor_class
        self.headless = headless  # Áp dụng cho cả token extraction

        # Tạo Chrome instances
        self.instances: List[ChromeInstance] = []
        for i, profile in enumerate(chrome_profiles):
            self.instances.append(ChromeInstance(
                id=i + 1,
                profile_path=profile
            ))

        # Thread-safe mechanisms
        self._lock = threading.Lock()  # Protect instance access
        self._token_lock = threading.Lock()  # Serialize token extraction
        self._available = threading.Semaphore(len(self.instances))  # Track available
        self._wait_queue = queue.Queue()  # Threads waiting for Chrome

        # Stats
        self.stats = {
            "total_checkouts": 0,
            "total_token_refreshes": 0,
            "total_errors": 0,
            "wait_time_total": 0.0
        }

        self.logger.info(f"[ChromePool] Initialized with {len(self.instances)} Chrome instances")

    def checkout(self, timeout: float = 300) -> Optional[ChromeInstance]:
        """
        Lấy 1 Chrome instance từ pool.

        - Nếu có available → trả ngay
        - Nếu hết → đợi (max timeout giây)

        Returns:
            ChromeInstance hoặc None nếu timeout
        """
        start_time = time.time()

        # Đợi có Chrome available
        if not self._available.acquire(timeout=timeout):
            self.logger.warning(f"[ChromePool] Timeout waiting for Chrome ({timeout}s)")
            return None

        wait_time = time.time() - start_time

        with self._lock:
            # Tìm Chrome không busy
            for instance in self.instances:
                if not instance.is_busy:
                    instance.is_busy = True
                    instance.last_used = datetime.now()
                    self.stats["total_checkouts"] += 1
                    self.stats["wait_time_total"] += wait_time

                    if wait_time > 1:
                        self.logger.info(f"[ChromePool] Checkout Chrome #{instance.id} (waited {wait_time:.1f}s)")
                    else:
                        self.logger.debug(f"[ChromePool] Checkout Chrome #{instance.id}")

                    return instance

        # Không tìm thấy (lỗi logic)
        self._available.release()
        self.logger.error("[ChromePool] No available Chrome found despite semaphore!")
        return None

    def checkin(self, instance: ChromeInstance):
        """
        Trả Chrome về pool.
        """
        with self._lock:
            instance.is_busy = False
            self.logger.debug(f"[ChromePool] Checkin Chrome #{instance.id}")

        self._available.release()

    def ensure_token(self, instance: ChromeInstance) -> bool:
        """
        Đảm bảo Chrome có token hợp lệ.

        - Nếu token còn hạn → return True
        - Nếu hết hạn → extract mới (serialized)

        Returns:
            True nếu có token, False nếu lỗi
        """
        # Kiểm tra token hiện tại
        if instance.is_token_valid():
            self.logger.debug(f"[ChromePool] Chrome #{instance.id} token still valid")
            return True

        # Cần extract token mới
        # Serialize token extraction với lock
        with self._token_lock:
            # Double-check sau khi có lock (thread khác có thể đã refresh)
            if instance.is_token_valid():
                return True

            headless_mode = "ẩn" if self.headless else "hiện"
            self.logger.info(f"[ChromePool] 🔑 Extracting token for Chrome #{instance.id} (mode: {headless_mode})...")

            try:
                # Extract token (sử dụng headless setting từ config)
                extractor = self.token_extractor_class(
                    chrome_path=self.chrome_path,
                    profile_path=instance.profile_path,
                    headless=self.headless  # Áp dụng headless setting
                )

                token, project_id, error = extractor.extract_token(
                    project_id=instance.project_id
                )

                if token:
                    instance.set_token(token, project_id)
                    self.stats["total_token_refreshes"] += 1
                    self.logger.info(f"[ChromePool] ✅ Token extracted for Chrome #{instance.id}")
                    return True
                else:
                    instance.error_count += 1
                    self.stats["total_errors"] += 1
                    self.logger.error(f"[ChromePool] ❌ Token extraction failed: {error}")
                    return False

            except Exception as e:
                instance.error_count += 1
                self.stats["total_errors"] += 1
                self.logger.error(f"[ChromePool] Exception extracting token: {e}")
                return False

    def get_stats(self) -> Dict:
        """Trả về thống kê pool"""
        with self._lock:
            busy_count = sum(1 for i in self.instances if i.is_busy)
            valid_tokens = sum(1 for i in self.instances if i.is_token_valid())

            return {
                **self.stats,
                "total_instances": len(self.instances),
                "busy_instances": busy_count,
                "available_instances": len(self.instances) - busy_count,
                "valid_tokens": valid_tokens,
                "avg_wait_time": self.stats["wait_time_total"] / max(1, self.stats["total_checkouts"])
            }

    def shutdown(self):
        """Cleanup tất cả Chrome instances"""
        self.logger.info("[ChromePool] Shutting down...")
        with self._lock:
            for instance in self.instances:
                if instance.driver:
                    try:
                        instance.driver.quit()
                    except:
                        pass
                    instance.driver = None
        self.logger.info("[ChromePool] Shutdown complete")


@dataclass
class VideoTask:
    """Đại diện 1 video cần xử lý"""
    id: int
    video_path: Path
    status: str = "pending"  # pending, processing, completed, failed
    chrome_id: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error: Optional[str] = None
    result: Optional[Dict] = None

    def duration(self) -> float:
        """Thời gian xử lý (giây)"""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0


class ParallelVideoProcessor:
    """
    Xử lý nhiều video song song với Chrome Pool.

    Usage:
        processor = ParallelVideoProcessor(
            video_folder="/path/to/videos",
            chrome_profiles=["profile1", "profile2", ...],
            chrome_path="C:/Chrome/chrome.exe",
            process_func=my_process_function
        )
        results = processor.run()
    """

    def __init__(
        self,
        video_folder: str,
        chrome_profiles: List[str],
        chrome_path: str,
        process_func: Callable[[Path, ChromeInstance], Dict],
        token_extractor_class: Any,
        max_workers: Optional[int] = None,
        logger: Optional[logging.Logger] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        headless: bool = False
    ):
        """
        Args:
            video_folder: Thư mục chứa video
            chrome_profiles: List Chrome profiles
            chrome_path: Path chrome.exe
            process_func: Function xử lý 1 video: func(video_path, chrome) -> result
            token_extractor_class: Class extract token
            max_workers: Số thread tối đa (mặc định = số Chrome)
            logger: Logger
            progress_callback: Callback báo tiến độ: func(completed, total, current_file)
            headless: Chạy Chrome ẩn (áp dụng cả token extraction)
        """
        self.logger = logger or logging.getLogger(__name__)
        self.video_folder = Path(video_folder)
        self.process_func = process_func
        self.max_workers = max_workers or len(chrome_profiles)
        self.progress_callback = progress_callback
        self.headless = headless

        # Tạo Chrome Pool (với headless setting)
        self.chrome_pool = ChromePool(
            chrome_profiles=chrome_profiles,
            chrome_path=chrome_path,
            token_extractor_class=token_extractor_class,
            logger=self.logger,
            headless=headless  # Pass headless setting
        )

        # Video tasks
        self.tasks: List[VideoTask] = []
        self._results_lock = threading.Lock()

        # Control
        self._stop_event = threading.Event()
        self._running = False

    def discover_videos(self, extensions: List[str] = None) -> List[Path]:
        """
        Tìm tất cả video trong folder.

        Args:
            extensions: Danh sách extension (mặc định: mp4, mkv, avi, mov)
        """
        if extensions is None:
            extensions = [".mp4", ".mkv", ".avi", ".mov", ".mp3", ".wav"]

        videos = []
        for ext in extensions:
            videos.extend(self.video_folder.glob(f"*{ext}"))
            videos.extend(self.video_folder.glob(f"*{ext.upper()}"))

        # Sort by name
        videos = sorted(set(videos), key=lambda p: p.name.lower())

        self.logger.info(f"[ParallelProcessor] Found {len(videos)} video files")
        return videos

    def _process_video_worker(self, task: VideoTask) -> VideoTask:
        """
        Worker thread xử lý 1 video.

        1. Checkout Chrome từ pool
        2. Ensure token valid
        3. Gọi process_func
        4. Checkin Chrome
        """
        task.status = "processing"
        task.start_time = datetime.now()

        # Checkout Chrome
        chrome = self.chrome_pool.checkout(timeout=600)  # Max 10 phút đợi
        if not chrome:
            task.status = "failed"
            task.error = "Timeout waiting for Chrome"
            task.end_time = datetime.now()
            return task

        task.chrome_id = chrome.id
        self.logger.info(f"[Worker] Video {task.id}: {task.video_path.name} → Chrome #{chrome.id}")

        try:
            # Ensure token
            if not self.chrome_pool.ensure_token(chrome):
                task.status = "failed"
                task.error = "Failed to get token"
                task.end_time = datetime.now()
                return task

            # Process video
            result = self.process_func(task.video_path, chrome)

            task.status = "completed"
            task.result = result

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            self.logger.error(f"[Worker] Video {task.id} error: {e}")

        finally:
            # Checkin Chrome
            self.chrome_pool.checkin(chrome)
            task.end_time = datetime.now()

        return task

    def run(
        self,
        video_extensions: List[str] = None,
        skip_existing: bool = True
    ) -> Dict[str, Any]:
        """
        Chạy xử lý song song tất cả video.

        Args:
            video_extensions: Extensions tìm kiếm
            skip_existing: Bỏ qua video đã xử lý

        Returns:
            {
                "total": int,
                "completed": int,
                "failed": int,
                "results": [VideoTask],
                "chrome_stats": {...}
            }
        """
        self._running = True
        self._stop_event.clear()

        # Discover videos
        videos = self.discover_videos(video_extensions)
        if not videos:
            self.logger.warning("[ParallelProcessor] No videos found!")
            return {"total": 0, "completed": 0, "failed": 0, "results": []}

        # Create tasks
        self.tasks = [
            VideoTask(id=i+1, video_path=v)
            for i, v in enumerate(videos)
        ]

        total = len(self.tasks)
        completed = 0

        self.logger.info(f"[ParallelProcessor] Starting {total} videos with {self.max_workers} workers")

        # Process với ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._process_video_worker, task): task
                for task in self.tasks
            }

            for future in as_completed(futures):
                if self._stop_event.is_set():
                    self.logger.warning("[ParallelProcessor] Stop requested, cancelling...")
                    break

                task = futures[future]
                try:
                    result_task = future.result()
                    completed += 1

                    duration = result_task.duration()
                    status_emoji = "✅" if result_task.status == "completed" else "❌"

                    self.logger.info(
                        f"[ParallelProcessor] {status_emoji} [{completed}/{total}] "
                        f"{result_task.video_path.name} ({duration:.1f}s)"
                    )

                    # Progress callback
                    if self.progress_callback:
                        self.progress_callback(completed, total, result_task.video_path.name)

                except Exception as e:
                    self.logger.error(f"[ParallelProcessor] Future error: {e}")

        self._running = False

        # Summary
        completed_count = sum(1 for t in self.tasks if t.status == "completed")
        failed_count = sum(1 for t in self.tasks if t.status == "failed")

        self.logger.info("=" * 50)
        self.logger.info(f"[ParallelProcessor] HOÀN THÀNH!")
        self.logger.info(f"  ✅ Thành công: {completed_count}/{total}")
        self.logger.info(f"  ❌ Thất bại: {failed_count}/{total}")
        self.logger.info("=" * 50)

        return {
            "total": total,
            "completed": completed_count,
            "failed": failed_count,
            "results": self.tasks,
            "chrome_stats": self.chrome_pool.get_stats()
        }

    def stop(self):
        """Dừng xử lý"""
        self._stop_event.set()
        self.logger.info("[ParallelProcessor] Stop requested")

    def shutdown(self):
        """Cleanup resources"""
        self.stop()
        self.chrome_pool.shutdown()


class TokenQueue:
    """
    Thread-safe Token Queue cho token extraction.

    Đảm bảo chỉ 1 token extraction tại 1 thời điểm.
    """

    def __init__(self, logger: Optional[logging.Logger] = None, headless: bool = False):
        self.logger = logger or logging.getLogger(__name__)
        self.headless = headless  # Áp dụng headless cho token extraction
        self._lock = threading.Lock()
        self._queue = queue.Queue()
        self._extracting = False
        self._condition = threading.Condition(self._lock)

    def request_token(
        self,
        chrome_instance: ChromeInstance,
        extractor_class: Any,
        chrome_path: str,
        timeout: float = 120,
        headless: bool = None  # Override headless setting nếu cần
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Request token extraction.

        Xếp hàng và đợi đến lượt.

        Args:
            headless: Override headless setting (None = dùng default từ __init__)

        Returns:
            (token, project_id, error)
        """
        # Quyết định headless mode
        use_headless = headless if headless is not None else self.headless

        start_time = time.time()

        with self._condition:
            # Đợi đến lượt
            while self._extracting:
                remaining = timeout - (time.time() - start_time)
                if remaining <= 0:
                    return None, None, "Timeout waiting in queue"
                self._condition.wait(timeout=remaining)

            # Đến lượt
            self._extracting = True

        wait_time = time.time() - start_time
        if wait_time > 1:
            self.logger.info(f"[TokenQueue] Chrome #{chrome_instance.id} waited {wait_time:.1f}s in queue")

        try:
            # Extract token
            mode_text = "ẩn" if use_headless else "hiện"
            self.logger.info(f"[TokenQueue] 🔑 Extracting token for Chrome #{chrome_instance.id} (mode: {mode_text})...")

            extractor = extractor_class(
                chrome_path=chrome_path,
                profile_path=chrome_instance.profile_path,
                headless=use_headless  # Áp dụng headless setting
            )

            token, project_id, error = extractor.extract_token(
                project_id=chrome_instance.project_id
            )

            if token:
                chrome_instance.set_token(token, project_id)
                self.logger.info(f"[TokenQueue] ✅ Token extracted for Chrome #{chrome_instance.id}")
            else:
                self.logger.error(f"[TokenQueue] ❌ Failed: {error}")

            return token, project_id, error

        except Exception as e:
            self.logger.error(f"[TokenQueue] Exception: {e}")
            return None, None, str(e)

        finally:
            with self._condition:
                self._extracting = False
                self._condition.notify_all()


# ============== HELPER FUNCTIONS ==============

def process_video_folder(
    folder_path: str,
    chrome_profiles: List[str],
    chrome_path: str,
    process_func: Callable,
    token_extractor_class: Any,
    max_workers: int = None,
    logger: logging.Logger = None,
    progress_callback: Callable = None,
    headless: bool = False
) -> Dict:
    """
    Helper function để xử lý folder video.

    Usage:
        from modules.parallel_video_processor import process_video_folder
        from modules.chrome_auto_token import ChromeAutoToken

        def my_processor(video_path, chrome):
            # Xử lý video với chrome.token và chrome.project_id
            return {"success": True}

        results = process_video_folder(
            folder_path="/videos",
            chrome_profiles=["/profile1", "/profile2"],
            chrome_path="chrome.exe",
            process_func=my_processor,
            token_extractor_class=ChromeAutoToken,
            headless=True  # Chạy ẩn Chrome (cả khi lấy token)
        )
    """
    processor = ParallelVideoProcessor(
        video_folder=folder_path,
        chrome_profiles=chrome_profiles,
        chrome_path=chrome_path,
        process_func=process_func,
        token_extractor_class=token_extractor_class,
        max_workers=max_workers,
        logger=logger,
        progress_callback=progress_callback,
        headless=headless  # Pass headless setting
    )

    try:
        results = processor.run()
        return results
    finally:
        processor.shutdown()


# ============== EXAMPLE USAGE ==============

if __name__ == "__main__":
    import sys

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logger = logging.getLogger(__name__)

    # Example: Mock processor
    def mock_process(video_path: Path, chrome: ChromeInstance) -> Dict:
        """Mock processor - simulates work"""
        logger.info(f"Processing {video_path.name} with Chrome #{chrome.id}, token={chrome.token[:20]}...")
        time.sleep(2)  # Simulate work
        return {"video": str(video_path), "chrome_id": chrome.id}

    # Example: Mock token extractor
    class MockTokenExtractor:
        def __init__(self, chrome_path, profile_path, headless=False):
            self.profile = profile_path

        def extract_token(self, project_id=None):
            time.sleep(1)  # Simulate extraction
            return f"token_{self.profile}", "project_123", None

    # Run
    if len(sys.argv) > 1:
        folder = sys.argv[1]
    else:
        folder = "."

    processor = ParallelVideoProcessor(
        video_folder=folder,
        chrome_profiles=["profile1", "profile2", "profile3"],
        chrome_path="chrome.exe",
        process_func=mock_process,
        token_extractor_class=MockTokenExtractor,
        logger=logger
    )

    results = processor.run()
    print(f"\nResults: {results}")
