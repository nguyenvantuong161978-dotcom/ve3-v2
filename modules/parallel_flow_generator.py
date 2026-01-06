"""
VE3 Tool - Parallel Flow Generator (2-Step Workflow)
=====================================================
Tạo ảnh song song với workflow 2 bước:
1. Bước 1: Tạo ảnh tham chiếu (nvc, nv*, loc*) song song
2. Bước 2: Tạo ảnh phân cảnh song song (upload ref từ nv/)

Features:
- Multiple browsers chạy song song
- 2-step workflow đảm bảo có ảnh ref trước khi tạo scenes
- Auto upload reference từ thư mục nv/
- Chia đều prompts cho các browsers
"""

import os
import time
import json
import base64
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED
from dataclasses import dataclass, field

# Import từ modules hiện có
from modules.browser_flow_generator import BrowserFlowGenerator
from modules.excel_manager import PromptWorkbook
from modules.utils import get_logger, load_settings


@dataclass
class ParallelStats:
    """Thống kê parallel generation."""
    total_prompts: int = 0
    ref_prompts: int = 0
    scene_prompts: int = 0
    success: int = 0
    failed: int = 0
    browsers_used: int = 0
    step1_time: float = 0.0
    step2_time: float = 0.0
    total_time: float = 0.0


class ParallelFlowGenerator:
    """
    Tạo ảnh song song với nhiều browser, workflow 2 bước.

    Workflow:
    ```
    BƯỚC 1: Tạo ảnh tham chiếu (song song)
    ├── Browser 1 → nvc, nv1, nv2
    ├── Browser 2 → nv3, nv4, loc1
    └── Browser 3 → loc2, loc3
         ↓
    [Đợi tất cả xong, lưu vào nv/]
         ↓
    BƯỚC 2: Tạo ảnh phân cảnh (song song)
    ├── Browser 1 → Scene 1, 4, 7... (upload ref từ nv/)
    ├── Browser 2 → Scene 2, 5, 8...
    └── Browser 3 → Scene 3, 6, 9...
    ```
    """

    def __init__(
        self,
        project_path: str,
        num_browsers: int = 3,
        headless: bool = True,
        verbose: bool = True,
        config_path: str = "config/settings.yaml"
    ):
        """
        Khởi tạo ParallelFlowGenerator.

        Args:
            project_path: Đường dẫn project (PROJECTS/KA1-0001)
            num_browsers: Số lượng browser chạy song song
            headless: Chạy ẩn browser
            verbose: In log chi tiết
            config_path: Đường dẫn config
        """
        self.project_path = Path(project_path)
        self.num_browsers = max(1, min(num_browsers, 5))  # 1-5 browsers
        self.headless = headless
        self.verbose = verbose
        self.config_path = config_path

        # Load config
        self.config = {}
        config_file = Path(config_path)
        if config_file.exists():
            self.config = load_settings(config_file)

        # Paths
        self.nv_path = self.project_path / "nv"
        self.img_path = self.project_path / "img"
        self.prompts_path = self.project_path / "prompts"

        # Tạo thư mục
        self.nv_path.mkdir(parents=True, exist_ok=True)
        self.img_path.mkdir(parents=True, exist_ok=True)

        # Logger
        self.logger = get_logger("parallel_flow")

        # Stats
        self.stats = ParallelStats()

        # Chrome profiles - load từ chrome_profiles/ (đã đăng nhập từ GUI)
        root_dir = Path(__file__).parent.parent
        self.profiles_dir = root_dir / "chrome_profiles"

        # Load danh sách profile đã có
        self.available_profiles = []
        if self.profiles_dir.exists():
            for item in sorted(self.profiles_dir.iterdir()):
                if item.is_dir() and not item.name.startswith('.'):
                    self.available_profiles.append(item.name)

        if not self.available_profiles:
            # Tạo profile mặc định nếu chưa có
            default_profile = self.profiles_dir / "main"
            default_profile.mkdir(parents=True, exist_ok=True)
            self.available_profiles = ["main"]

        # Lock cho thread-safe
        self._lock = threading.Lock()
        self._results: Dict[str, Any] = {}

        # QUAN TRỌNG: Lock cho download - chỉ 1 browser download tại 1 thời điểm
        # Tránh nhầm lẫn ảnh khi nhiều browser cùng download
        self._download_lock = threading.Lock()
        self._download_queue_enabled = True  # Bật xếp hàng download

    def _log(self, message: str, level: str = "info") -> None:
        """Print log message."""
        if self.verbose:
            timestamp = datetime.now().strftime("%H:%M:%S")
            icons = {
                "info": "[INFO]",
                "success": "[OK]",
                "error": "[ERROR]",
                "warn": "[WARN]",
            }
            print(f"[{timestamp}] {icons.get(level, '')} {message}")

    def _find_excel_file(self) -> Optional[Path]:
        """Tìm file Excel prompts."""
        for pattern in ["*_prompts.xlsx", "*.xlsx"]:
            files = list(self.prompts_path.glob(pattern))
            if files:
                return files[0]
            files = list(self.project_path.glob(pattern))
            if files:
                return files[0]
        return None

    def _split_prompts(self, prompts: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """
        Chia prompts thành 2 nhóm: ref (nvc, nv*, loc*) và scenes.

        Args:
            prompts: List prompts [{'id': '...', 'prompt': '...'}]

        Returns:
            Tuple[ref_prompts, scene_prompts]
        """
        ref_prompts = []
        scene_prompts = []

        for p in prompts:
            pid = str(p.get('id', ''))
            if pid.startswith('nv') or pid.startswith('loc'):
                ref_prompts.append(p)
            else:
                scene_prompts.append(p)

        return ref_prompts, scene_prompts

    def _chunk_prompts(self, prompts: List[Dict], n_chunks: int) -> List[List[Dict]]:
        """
        Chia đều prompts cho n browsers.

        Args:
            prompts: List prompts
            n_chunks: Số phần cần chia

        Returns:
            List các chunks
        """
        if not prompts:
            return [[] for _ in range(n_chunks)]

        chunks = [[] for _ in range(n_chunks)]
        for i, p in enumerate(prompts):
            chunks[i % n_chunks].append(p)

        return chunks

    def _get_profile_name(self, browser_idx: int) -> str:
        """
        Lấy tên profile cho browser từ danh sách đã đăng nhập.

        QUAN TRỌNG:
        - Dùng profile từ chrome_profiles/ (đã đăng nhập từ GUI)
        - Round-robin nếu có nhiều browser hơn profile
        - BrowserFlowGenerator sẽ tạo working copy để tránh conflict

        Returns:
            Tên profile từ chrome_profiles/ (e.g., "Default", "account1")
        """
        # Round-robin qua danh sách profile đã có
        profile_idx = browser_idx % len(self.available_profiles)
        profile_name = self.available_profiles[profile_idx]
        self._log(f"Browser-{browser_idx} dùng profile: {profile_name}")
        return profile_name

    def _worker_generate(
        self,
        browser_idx: int,
        prompts: List[Dict],
        phase: str,  # "ref" hoặc "scene"
        excel_path: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        Worker function cho mỗi browser thread.

        Args:
            browser_idx: Index của browser (0, 1, 2...)
            prompts: Prompts cần xử lý
            phase: "ref" (bước 1) hoặc "scene" (bước 2)
            excel_path: Đường dẫn Excel

        Returns:
            Dict với kết quả
        """
        thread_name = f"Browser-{browser_idx}"
        self._log(f"[{thread_name}] Bắt đầu {phase}: {len(prompts)} prompts")

        if not prompts:
            return {"success": 0, "failed": 0, "browser": browser_idx}

        profile_name = self._get_profile_name(browser_idx)

        try:
            # Tạo generator cho browser này
            generator = BrowserFlowGenerator(
                project_path=str(self.project_path),
                profile_name=profile_name,
                headless=self.headless,
                verbose=self.verbose,
                config_path=self.config_path
            )

            # Start browser
            if not generator.start_browser():
                self._log(f"[{thread_name}] Không khởi động được browser", "error")
                return {"success": 0, "failed": len(prompts), "browser": browser_idx, "error": "Browser start failed"}

            # Wait for login
            if not generator.wait_for_login(timeout=120):
                generator.stop_browser()
                self._log(f"[{thread_name}] Chưa đăng nhập", "error")
                return {"success": 0, "failed": len(prompts), "browser": browser_idx, "error": "Login timeout"}

            # Inject JS
            if not generator._inject_js():
                generator.stop_browser()
                return {"success": 0, "failed": len(prompts), "browser": browser_idx, "error": "JS inject failed"}

            # Load media cache (cho bước 2 - scene)
            if phase == "scene":
                cached = generator._load_media_cache()
                if cached:
                    generator._load_media_names_to_js(cached)
                    self._log(f"[{thread_name}] Loaded {len(cached)} media references")

            # Generate từng prompt
            success = 0
            failed = 0

            for i, p in enumerate(prompts):
                pid = str(p.get('id', ''))
                prompt_text = p.get('prompt', '')
                ref_files = p.get('reference_files', [])

                self._log(f"[{thread_name}] [{i+1}/{len(prompts)}] {pid}")

                if not prompt_text:
                    failed += 1
                    continue

                try:
                    # Upload reference nếu có (cho scenes)
                    if phase == "scene" and ref_files:
                        if isinstance(ref_files, str):
                            try:
                                ref_files = json.loads(ref_files)
                            except:
                                ref_files = [f.strip() for f in ref_files.split(',') if f.strip()]
                        generator._upload_reference_images(ref_files)

                    # =========================================================
                    # XẾP HÀNG DOWNLOAD: Acquire lock trước khi generate
                    # Đảm bảo chỉ 1 browser download tại 1 thời điểm
                    # =========================================================
                    with self._download_lock:
                        self._log(f"[{thread_name}] 🔒 Bắt đầu generate + download: {pid}")

                        # Gọi VE3.run()
                        ref_json = json.dumps(ref_files if ref_files else [])
                        result = generator.driver.execute_async_script(f"""
                            const callback = arguments[arguments.length - 1];
                            const timeout = setTimeout(() => {{
                                callback({{ success: false, error: 'Timeout 120s' }});
                            }}, 120000);

                            VE3.run([{{
                                sceneId: "{pid}",
                                prompt: `{generator._escape_js_string(prompt_text)}`,
                                referenceFiles: {ref_json}
                            }}]).then(r => {{
                                clearTimeout(timeout);
                                callback({{ success: true, result: r }});
                            }}).catch(e => {{
                                clearTimeout(timeout);
                                callback({{ success: false, error: e.message }});
                            }});
                        """)

                        if result and result.get("success"):
                            # Di chuyển file (trong lock để không nhầm)
                            img_file, score, _ = generator._move_downloaded_images(pid)
                            if img_file:
                                success += 1
                                self._log(f"[{thread_name}] ✅ OK: {pid} -> {img_file.name}", "success")

                                # Save media name (cho ref)
                                if phase == "ref":
                                    js_result = result.get("result", {})
                                    js_images = js_result.get("images", []) if isinstance(js_result, dict) else []
                                    if js_images and js_images[0].get("mediaName"):
                                        generator.driver.execute_script(
                                            f"VE3.setMediaName('{pid}', '{js_images[0]['mediaName']}', {js_images[0].get('seed', 'null')});"
                                        )
                            else:
                                failed += 1
                                self._log(f"[{thread_name}] ❌ Không tìm thấy file: {pid}", "error")
                        else:
                            failed += 1
                            self._log(f"[{thread_name}] ❌ FAIL: {pid}", "error")

                        self._log(f"[{thread_name}] 🔓 Xong download: {pid}")

                    # Delay
                    time.sleep(2)

                except Exception as e:
                    failed += 1
                    self._log(f"[{thread_name}] Error {pid}: {e}", "error")

            # Lưu media cache (sau bước ref)
            if phase == "ref":
                media_names = generator._get_media_names_from_js()
                if media_names:
                    generator._save_media_cache(media_names)
                    self._log(f"[{thread_name}] Saved {len(media_names)} media names")

            # Đóng browser
            generator.stop_browser()

            return {
                "success": success,
                "failed": failed,
                "browser": browser_idx
            }

        except Exception as e:
            self._log(f"[{thread_name}] Exception: {e}", "error")
            import traceback
            traceback.print_exc()
            return {
                "success": 0,
                "failed": len(prompts),
                "browser": browser_idx,
                "error": str(e)
            }

    def generate_parallel(
        self,
        excel_path: Optional[Path] = None,
        overwrite: bool = False
    ) -> Dict[str, Any]:
        """
        Tạo ảnh song song với workflow 2 bước.

        Bước 1: Tạo ảnh tham chiếu (nvc, nv*, loc*) song song
        Bước 2: Tạo ảnh phân cảnh song song (có upload ref)

        Args:
            excel_path: Đường dẫn Excel
            overwrite: Ghi đè ảnh đã có

        Returns:
            Dict với kết quả
        """
        total_start = time.time()

        self._log("=" * 60)
        self._log(f"PARALLEL FLOW GENERATOR - {self.num_browsers} BROWSERS")
        self._log("=" * 60)

        # Tìm Excel
        if excel_path is None:
            excel_path = self._find_excel_file()

        if not excel_path or not excel_path.exists():
            return {"success": False, "error": "Không tìm thấy file Excel"}

        self._log(f"Excel: {excel_path}")
        self._log(f"Project: {self.project_path.name}")
        self._log(f"Browsers: {self.num_browsers}")

        # Load Excel
        workbook = PromptWorkbook(excel_path)
        workbook.load_or_create()

        # Lấy tất cả prompts
        all_prompts = []

        # Characters
        for char in workbook.get_characters():
            if char.english_prompt:
                if char.status == "done" and not overwrite:
                    continue
                all_prompts.append({
                    'id': char.id,
                    'prompt': char.english_prompt,
                    'reference_files': []
                })

        # Scenes
        for scene in workbook.get_scenes():
            if scene.img_prompt:
                if scene.status_img == "done" and not overwrite:
                    continue
                ref_str = getattr(scene, 'reference_files', '') or ''
                all_prompts.append({
                    'id': str(scene.scene_id),
                    'prompt': scene.img_prompt,
                    'reference_files': ref_str
                })

        if not all_prompts:
            self._log("Không có prompt nào cần xử lý", "warn")
            return {"success": True, "stats": self.stats}

        # Chia prompts
        ref_prompts, scene_prompts = self._split_prompts(all_prompts)

        self._log(f"\nTổng: {len(all_prompts)} prompts")
        self._log(f"  - Tham chiếu (nv/loc): {len(ref_prompts)}")
        self._log(f"  - Phân cảnh: {len(scene_prompts)}")

        self.stats.total_prompts = len(all_prompts)
        self.stats.ref_prompts = len(ref_prompts)
        self.stats.scene_prompts = len(scene_prompts)
        self.stats.browsers_used = self.num_browsers

        # =====================================================================
        # BƯỚC 1: Tạo ảnh tham chiếu song song
        # =====================================================================
        if ref_prompts:
            step1_start = time.time()
            self._log("\n" + "=" * 60)
            self._log("BƯỚC 1: TẠO ẢNH THAM CHIẾU (SONG SONG)")
            self._log("=" * 60)

            # Chia prompts cho các browsers
            ref_chunks = self._chunk_prompts(ref_prompts, self.num_browsers)

            for i, chunk in enumerate(ref_chunks):
                if chunk:
                    self._log(f"  Browser {i}: {len(chunk)} prompts ({[p['id'] for p in chunk]})")

            # Chạy song song
            with ThreadPoolExecutor(max_workers=self.num_browsers) as executor:
                futures = []
                for i, chunk in enumerate(ref_chunks):
                    if chunk:
                        future = executor.submit(
                            self._worker_generate,
                            i, chunk, "ref", excel_path
                        )
                        futures.append(future)

                # Đợi tất cả xong
                done, _ = wait(futures, return_when=ALL_COMPLETED)

                # Thu thập kết quả
                for future in done:
                    try:
                        result = future.result()
                        self.stats.success += result.get("success", 0)
                        self.stats.failed += result.get("failed", 0)
                    except Exception as e:
                        self._log(f"Worker error: {e}", "error")

            self.stats.step1_time = time.time() - step1_start
            self._log(f"\nBước 1 hoàn thành: {self.stats.step1_time:.1f}s")

        # =====================================================================
        # BƯỚC 2: Tạo ảnh phân cảnh song song
        # =====================================================================
        if scene_prompts:
            step2_start = time.time()
            self._log("\n" + "=" * 60)
            self._log("BƯỚC 2: TẠO ẢNH PHÂN CẢNH (SONG SONG)")
            self._log("=" * 60)

            # Chia prompts
            scene_chunks = self._chunk_prompts(scene_prompts, self.num_browsers)

            for i, chunk in enumerate(scene_chunks):
                if chunk:
                    self._log(f"  Browser {i}: {len(chunk)} scenes")

            # Chạy song song
            with ThreadPoolExecutor(max_workers=self.num_browsers) as executor:
                futures = []
                for i, chunk in enumerate(scene_chunks):
                    if chunk:
                        future = executor.submit(
                            self._worker_generate,
                            i, chunk, "scene", excel_path
                        )
                        futures.append(future)

                done, _ = wait(futures, return_when=ALL_COMPLETED)

                for future in done:
                    try:
                        result = future.result()
                        self.stats.success += result.get("success", 0)
                        self.stats.failed += result.get("failed", 0)
                    except Exception as e:
                        self._log(f"Worker error: {e}", "error")

            self.stats.step2_time = time.time() - step2_start
            self._log(f"\nBước 2 hoàn thành: {self.stats.step2_time:.1f}s")

        # Summary
        self.stats.total_time = time.time() - total_start

        self._log("\n" + "=" * 60)
        self._log("HOÀN THÀNH")
        self._log("=" * 60)
        self._log(f"Tổng thời gian: {self.stats.total_time:.1f}s")
        self._log(f"  - Bước 1 (ref): {self.stats.step1_time:.1f}s")
        self._log(f"  - Bước 2 (scene): {self.stats.step2_time:.1f}s")
        self._log(f"Kết quả: {self.stats.success} thành công, {self.stats.failed} thất bại")

        # So sánh với chạy tuần tự
        estimated_sequential = len(all_prompts) * 15  # ~15s per image
        speedup = estimated_sequential / self.stats.total_time if self.stats.total_time > 0 else 1
        self._log(f"Tốc độ: ~{speedup:.1f}x nhanh hơn chạy tuần tự")

        return {
            "success": True,
            "stats": {
                "total": self.stats.total_prompts,
                "success": self.stats.success,
                "failed": self.stats.failed,
                "time": self.stats.total_time,
                "step1_time": self.stats.step1_time,
                "step2_time": self.stats.step2_time,
                "browsers": self.stats.browsers_used,
                "speedup": speedup
            }
        }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def generate_images_parallel(
    project_path: str,
    num_browsers: int = 3,
    headless: bool = True,
    overwrite: bool = False
) -> Dict[str, Any]:
    """
    Hàm tiện ích để tạo ảnh song song.

    Args:
        project_path: Đường dẫn project
        num_browsers: Số browsers
        headless: Chạy ẩn
        overwrite: Ghi đè

    Returns:
        Dict kết quả
    """
    generator = ParallelFlowGenerator(
        project_path=project_path,
        num_browsers=num_browsers,
        headless=headless
    )
    return generator.generate_parallel(overwrite=overwrite)


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import sys

    print("""
+================================================================+
|     PARALLEL FLOW GENERATOR - VE3 TOOL                         |
+================================================================+
|  Tạo ảnh song song với workflow 2 bước:                        |
|  1. Tạo ảnh tham chiếu (nvc, nv*, loc*)                        |
|  2. Tạo ảnh phân cảnh (có upload reference)                    |
|                                                                |
|  Usage:                                                        |
|    python parallel_flow_generator.py <project_path>            |
|                                                                |
|  Options:                                                      |
|    --browsers N    Số browser (default: 3, max: 5)             |
|    --headless      Chạy ẩn                                     |
|    --overwrite     Ghi đè ảnh đã có                            |
+================================================================+
""")

    if len(sys.argv) < 2:
        print("Vui lòng cung cấp đường dẫn project")
        print("Ví dụ: python parallel_flow_generator.py ./PROJECTS/KA1-0001")
        sys.exit(1)

    project_path = sys.argv[1]
    num_browsers = 3
    headless = "--headless" in sys.argv
    overwrite = "--overwrite" in sys.argv

    for i, arg in enumerate(sys.argv):
        if arg == "--browsers" and i + 1 < len(sys.argv):
            num_browsers = int(sys.argv[i + 1])

    result = generate_images_parallel(
        project_path=project_path,
        num_browsers=num_browsers,
        headless=headless,
        overwrite=overwrite
    )

    if result.get("success"):
        stats = result.get("stats", {})
        print(f"\n✅ Hoàn thành: {stats.get('success', 0)} ảnh")
        print(f"   Thời gian: {stats.get('time', 0):.1f}s")
        print(f"   Speedup: {stats.get('speedup', 1):.1f}x")
    else:
        print(f"\n❌ Lỗi: {result.get('error')}")
        sys.exit(1)
