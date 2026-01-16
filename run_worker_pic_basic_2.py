#!/usr/bin/env python3
"""
VE3 Tool - Worker PIC BASIC 2 Chrome Mode
==========================================
Chay 2 Chrome SONG SONG de tao anh nhanh hon:
- Chrome 1: Characters + 50% scenes
- Chrome 2: Locations + 50% scenes

FLOW:
1. Phase 1 (song song): Chrome1 tao characters, Chrome2 tao locations
2. Phase 2 (song song): Ca 2 Chrome chia nhau tao scenes (50/50)

Usage:
    python run_worker_pic_basic_2.py                     (quet va xu ly tu dong)
    python run_worker_pic_basic_2.py AR47-0028           (chay 1 project cu the)
"""

import sys
import os
import time
import threading
from pathlib import Path
from typing import List, Dict, Callable

# Add current directory to path
TOOL_DIR = Path(__file__).parent
sys.path.insert(0, str(TOOL_DIR))

# Import tu run_worker (dung chung logic)
from run_worker import (
    detect_auto_path,
    POSSIBLE_AUTO_PATHS,
    get_channel_from_folder,
    matches_channel,
    is_project_complete_on_master,
    has_excel_with_prompts,
    copy_from_master,
    SCAN_INTERVAL,
)

# Import tu run_worker_pic_basic
from run_worker_pic_basic import (
    create_excel_with_api_basic,
    is_local_pic_complete,
)

# Detect paths
AUTO_PATH = detect_auto_path()
if AUTO_PATH:
    MASTER_PROJECTS = AUTO_PATH / "ve3-tool-simple" / "PROJECTS"
    MASTER_VISUAL = AUTO_PATH / "VISUAL"
else:
    MASTER_PROJECTS = Path(r"\\tsclient\D\AUTO\ve3-tool-simple\PROJECTS")
    MASTER_VISUAL = Path(r"\\tsclient\D\AUTO\VISUAL")

LOCAL_PROJECTS = TOOL_DIR / "PROJECTS"
WORKER_CHANNEL = get_channel_from_folder()


def load_chrome_paths() -> tuple:
    """
    Load 2 Chrome portable paths from settings.yaml.

    Returns:
        (chrome_path_1, chrome_path_2) or (None, None) if not configured
    """
    import yaml

    settings_path = TOOL_DIR / "config" / "settings.yaml"
    if not settings_path.exists():
        return None, None

    with open(settings_path, 'r', encoding='utf-8') as f:
        settings = yaml.safe_load(f) or {}

    chrome1 = settings.get('chrome_portable', '')
    chrome2 = settings.get('chrome_portable_2', '')

    # Auto-detect if not configured
    if not chrome1:
        # Try to find GoogleChromePortable in tool directory
        default_chrome = TOOL_DIR / "GoogleChromePortable" / "GoogleChromePortable.exe"
        if default_chrome.exists():
            chrome1 = str(default_chrome)

    if not chrome2:
        # Try to find "GoogleChromePortable - Copy" in tool directory
        copy_chrome = TOOL_DIR / "GoogleChromePortable - Copy" / "GoogleChromePortable.exe"
        if copy_chrome.exists():
            chrome2 = str(copy_chrome)

    return chrome1, chrome2


class DualChromeImageGenerator:
    """
    Tao anh bang 2 Chrome PORTABLE song song.

    Phase 1: Chrome1 tao characters, Chrome2 tao locations (SONG SONG)
    Phase 2: Ca 2 chia nhau tao scenes (SONG SONG)

    QUAN TRONG:
    - Dung 2 thu muc Chrome Portable RIENG BIET
    - Moi Chrome co Data folder rieng, khong conflict
    - VD: GoogleChromePortable va GoogleChromePortable - Copy
    """

    def __init__(self, callback: Callable = None):
        self.callback = callback
        self.stop_flag = False
        self._lock = threading.Lock()

        # 2 Chrome paths
        self.chrome_path_1, self.chrome_path_2 = load_chrome_paths()

        # 2 separate engines (each with own Chrome)
        self._engine1 = None
        self._engine2 = None

        # Results
        self.results = {
            "chrome1": {"success": 0, "failed": 0},
            "chrome2": {"success": 0, "failed": 0},
        }

    def log(self, msg: str, level: str = "INFO"):
        """Log message."""
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        full_msg = f"[{ts}] {msg}"

        if self.callback:
            self.callback(full_msg, level)
        else:
            print(full_msg)

    def _create_engine(self, chrome_id: int) -> 'SmartEngine':
        """
        Create SmartEngine instance with specific Chrome path.

        Args:
            chrome_id: 0 = Chrome 1, 1 = Chrome 2
        """
        from modules.smart_engine import SmartEngine

        engine = SmartEngine(
            worker_id=chrome_id,
            total_workers=2
        )

        # Override chrome_portable path
        if chrome_id == 0 and self.chrome_path_1:
            engine.chrome_portable = self.chrome_path_1
            self.log(f"Chrome1 path: {self.chrome_path_1}")
        elif chrome_id == 1 and self.chrome_path_2:
            engine.chrome_portable = self.chrome_path_2
            self.log(f"Chrome2 path: {self.chrome_path_2}")

        return engine

    def _get_engines(self) -> tuple:
        """Get or create 2 separate SmartEngine instances."""
        if self._engine1 is None:
            self._engine1 = self._create_engine(0)
        if self._engine2 is None:
            self._engine2 = self._create_engine(1)
        return self._engine1, self._engine2

    def _split_prompts(self, all_prompts: List[Dict]) -> tuple:
        """
        Split prompts into reference images and scenes.

        Returns:
            (references, scenes_chrome1, scenes_chrome2)
            - references: Characters (nv*) + Locations (loc*) - tạo trước
            - scenes_chrome1: Odd scenes (s001, s003, ...) - Chrome 1
            - scenes_chrome2: Even scenes (s002, s004, ...) - Chrome 2
        """
        characters = []
        locations = []
        scenes = []

        for p in all_prompts:
            pid = p.get('id', '')
            if pid.startswith('nv'):
                characters.append(p)
            elif pid.startswith('loc'):
                locations.append(p)
            else:
                scenes.append(p)

        # Sort scenes by ID for consistent splitting
        scenes.sort(key=lambda x: x.get('id', ''))

        # Split scenes: odd to Chrome1, even to Chrome2
        scenes_chrome1 = scenes[::2]   # 0, 2, 4, ... (s001, s003, ...)
        scenes_chrome2 = scenes[1::2]  # 1, 3, 5, ... (s002, s004, ...)

        # References = characters + locations (tạo trước)
        references = characters + locations

        self.log(f"References: {len(references)} (nv:{len(characters)}, loc:{len(locations)})")
        self.log(f"Scenes Chrome1: {len(scenes_chrome1)} (odd)")
        self.log(f"Scenes Chrome2: {len(scenes_chrome2)} (even)")

        return references, scenes_chrome1, scenes_chrome2

    def _worker_thread(self, chrome_id: int, prompts: List[Dict], proj_dir: Path, engine: 'SmartEngine'):
        """
        Worker thread for 1 Chrome instance.
        Creates images sequentially within this thread.

        Args:
            chrome_id: 0 or 1
            prompts: List of prompts for this thread
            proj_dir: Project directory
            engine: SmartEngine instance with its own Chrome path
        """
        thread_name = f"Chrome{chrome_id + 1}"

        try:
            self.log(f"[{thread_name}] Starting with {len(prompts)} images...")

            # Get token for this Chrome
            self.log(f"[{thread_name}] Getting token...")
            token_count = engine.get_all_tokens()

            if token_count == 0:
                self.log(f"[{thread_name}] No token available!", "ERROR")
                with self._lock:
                    self.results[f"chrome{chrome_id + 1}"] = {"success": 0, "failed": len(prompts)}
                return

            # Get active profile for this engine
            all_accounts = engine.headless_accounts + engine.profiles
            active_profile = None
            for p in all_accounts:
                if p.token and p.status != 'exhausted':
                    active_profile = p
                    break

            if not active_profile:
                self.log(f"[{thread_name}] No active profile!", "ERROR")
                with self._lock:
                    self.results[f"chrome{chrome_id + 1}"] = {"success": 0, "failed": len(prompts)}
                return

            self.log(f"[{thread_name}] Using profile: {Path(active_profile.value).name}")

            # Process prompts sequentially
            success = 0
            failed = 0

            for i, prompt_data in enumerate(prompts):
                if self.stop_flag:
                    break

                pid = prompt_data.get('id', '')
                output_path = prompt_data.get('output_path', '')

                # Skip if exists
                if Path(output_path).exists():
                    self.log(f"[{thread_name}] [{pid}] Already exists, skip")
                    success += 1
                    continue

                self.log(f"[{thread_name}] [{i+1}/{len(prompts)}] Creating {pid}...")

                # Check token valid - if expired, try to refresh
                if not active_profile.token:
                    self.log(f"[{thread_name}] Token expired, refreshing...")
                    engine.get_all_tokens()

                    # Find new active profile
                    active_profile = None
                    for p in all_accounts:
                        if p.token and p.status != 'exhausted':
                            active_profile = p
                            break

                    if not active_profile or not active_profile.token:
                        self.log(f"[{thread_name}] Cannot refresh token!", "ERROR")
                        failed += len(prompts) - i
                        break

                # Generate image
                ok, token_expired = engine.generate_single_image(prompt_data, active_profile)

                if token_expired:
                    active_profile.token = ""
                    self.log(f"[{thread_name}] Token expired during {pid}", "WARN")

                if ok:
                    success += 1
                    self.log(f"[{thread_name}] [{pid}] OK!", "OK")
                else:
                    failed += 1
                    self.log(f"[{thread_name}] [{pid}] FAILED", "ERROR")

                # Small delay
                time.sleep(0.3)

            # Update results
            with self._lock:
                self.results[f"chrome{chrome_id + 1}"] = {
                    "success": success,
                    "failed": failed,
                }

            self.log(f"[{thread_name}] Done: {success} OK, {failed} FAILED")

        except Exception as e:
            self.log(f"[{thread_name}] Exception: {e}", "ERROR")
            import traceback
            traceback.print_exc()

    def generate_parallel(self, all_prompts: List[Dict], proj_dir: Path) -> Dict:
        """
        Generate images using 2 Chrome instances in parallel.

        FLOW:
        1. Phase 1: Chrome1 tạo reference images (nv + loc) - PHẢI XONG TRƯỚC
        2. Phase 2: Cả 2 Chrome tạo scenes song song (cần media_id từ Phase 1)

        Args:
            all_prompts: List of prompt dicts with id, prompt, output_path, etc.
            proj_dir: Project directory

        Returns:
            Dict with success/failed counts
        """
        self.log(f"\n{'='*60}")
        self.log(f"  2-CHROME PARALLEL IMAGE GENERATION")
        self.log(f"  Total images: {len(all_prompts)}")
        self.log(f"{'='*60}")

        # Check Chrome paths
        if not self.chrome_path_1:
            self.log("Chrome 1 path not configured!", "ERROR")
            return {"success": 0, "failed": len(all_prompts)}

        if not self.chrome_path_2:
            self.log("Chrome 2 path not configured! Set chrome_portable_2 in settings.yaml", "WARN")
            self.log("Falling back to single Chrome mode...", "WARN")
            # Fall back to single Chrome
            self.chrome_path_2 = self.chrome_path_1

        self.log(f"Chrome1: {self.chrome_path_1}")
        self.log(f"Chrome2: {self.chrome_path_2}")

        if not all_prompts:
            return {"success": 0, "failed": 0}

        # Create 2 separate engines with different Chrome paths
        engine1, engine2 = self._get_engines()

        # Split prompts: references first, then scenes for 2 Chrome
        references, scenes_chrome1, scenes_chrome2 = self._split_prompts(all_prompts)

        # ============================================================
        # PHASE 1: Tạo reference images (characters + locations) TRƯỚC
        # Dùng Chrome1 để tạo, Chrome2 chờ
        # QUAN TRỌNG: Scenes cần media_id từ references
        # ============================================================
        if references:
            self.log(f"\n{'='*60}")
            self.log(f"  PHASE 1: Creating {len(references)} reference images...")
            self.log(f"  (Characters + Locations - PHẢI XONG TRƯỚC)")
            self.log(f"{'='*60}")

            # Reset results for phase 1
            self.results["chrome1"] = {"success": 0, "failed": 0}

            # Chrome1 creates all references
            thread_ref = threading.Thread(
                target=self._worker_thread,
                args=(0, references, proj_dir, engine1),
                name="Chrome1-Refs"
            )
            thread_ref.start()
            thread_ref.join()  # WAIT until done

            self.log(f"Phase 1 done: {self.results['chrome1']['success']} OK, {self.results['chrome1']['failed']} FAILED")

        # ============================================================
        # PHASE 2: Cả 2 Chrome tạo scenes SONG SONG
        # Lúc này references đã có media_id
        # ============================================================
        if scenes_chrome1 or scenes_chrome2:
            self.log(f"\n{'='*60}")
            self.log(f"  PHASE 2: Creating scenes in PARALLEL")
            self.log(f"  Chrome1: {len(scenes_chrome1)} scenes (odd)")
            self.log(f"  Chrome2: {len(scenes_chrome2)} scenes (even)")
            self.log(f"{'='*60}")

            # Reset results for phase 2
            phase1_results = self.results["chrome1"].copy()
            self.results["chrome1"] = {"success": 0, "failed": 0}
            self.results["chrome2"] = {"success": 0, "failed": 0}

            # Create threads for both Chrome
            threads = []

            if scenes_chrome1:
                t1 = threading.Thread(
                    target=self._worker_thread,
                    args=(0, scenes_chrome1, proj_dir, engine1),
                    name="Chrome1-Scenes"
                )
                threads.append(t1)

            if scenes_chrome2:
                t2 = threading.Thread(
                    target=self._worker_thread,
                    args=(1, scenes_chrome2, proj_dir, engine2),
                    name="Chrome2-Scenes"
                )
                threads.append(t2)

            # Start all threads
            for i, t in enumerate(threads):
                t.start()
                if i < len(threads) - 1:
                    time.sleep(2)  # Delay between Chrome startups

            # Wait for all to finish
            for t in threads:
                t.join()

            # Add phase 1 results back
            self.results["chrome1"]["success"] += phase1_results["success"]
            self.results["chrome1"]["failed"] += phase1_results["failed"]

        # Combine results
        total_success = self.results["chrome1"]["success"] + self.results["chrome2"]["success"]
        total_failed = self.results["chrome1"]["failed"] + self.results["chrome2"]["failed"]

        self.log(f"\n{'='*60}")
        self.log(f"  FINAL RESULTS:")
        self.log(f"  Chrome1: {self.results['chrome1']['success']} OK, {self.results['chrome1']['failed']} FAILED")
        self.log(f"  Chrome2: {self.results['chrome2']['success']} OK, {self.results['chrome2']['failed']} FAILED")
        self.log(f"  TOTAL:   {total_success} OK, {total_failed} FAILED")
        self.log(f"{'='*60}")

        return {
            "success": total_success,
            "failed": total_failed,
            "chrome1": self.results["chrome1"],
            "chrome2": self.results["chrome2"],
        }


def get_prompts_from_excel(excel_path: Path, proj_dir: Path) -> List[Dict]:
    """
    Read prompts from Excel and prepare prompt list for image generation.
    """
    from modules.excel_manager import PromptWorkbook

    prompts = []
    img_dir = proj_dir / "img"
    img_dir.mkdir(exist_ok=True)
    nv_dir = proj_dir / "nv"
    nv_dir.mkdir(exist_ok=True)

    wb = PromptWorkbook(str(excel_path))

    # Get characters
    characters = wb.get_characters()
    for char in characters:
        if char.img_prompt:
            char_id = char.id or f"nv{len(prompts) + 1}"
            prompts.append({
                "id": char_id,
                "prompt": char.img_prompt,
                "output_path": str(nv_dir / f"{char_id}.png"),
                "type": "character",
            })

    # Get locations
    locations = wb.get_locations()
    for loc in locations:
        if loc.img_prompt:
            loc_id = loc.id or f"loc{len(prompts) + 1}"
            prompts.append({
                "id": loc_id,
                "prompt": loc.img_prompt,
                "output_path": str(nv_dir / f"{loc_id}.png"),
                "type": "location",
            })

    # Get scenes
    scenes = wb.get_scenes()
    for scene in scenes:
        if scene.img_prompt:
            scene_id = scene.id or f"s{len(prompts) + 1:03d}"

            # Prepare reference files
            reference_files = scene.reference_files or ""
            nv_path = str(nv_dir) if (nv_dir / "nvc.png").exists() or any(nv_dir.glob("nv*.png")) else ""

            prompts.append({
                "id": scene_id,
                "prompt": scene.img_prompt,
                "output_path": str(img_dir / f"{scene_id}.png"),
                "video_prompt": scene.video_prompt or "",
                "reference_files": reference_files,
                "nv_path": nv_path,
                "type": "scene",
            })

    return prompts


def process_project_pic_basic_2(code: str, callback=None) -> bool:
    """Process a single project using 2 Chrome instances in parallel."""

    def log(msg, level="INFO"):
        if callback:
            callback(msg, level)
        else:
            print(msg)

    log(f"\n{'='*60}")
    log(f"[PIC BASIC 2-CHROME] Processing: {code}")
    log(f"{'='*60}")

    # Step 1: Check if already done on master
    if is_project_complete_on_master(code):
        log(f"  Already in VISUAL folder, skip!")
        return True

    # Step 2: Copy from master
    local_dir = copy_from_master(code)
    if not local_dir:
        return False

    # Step 3: Check/Create Excel (BASIC mode)
    excel_path = local_dir / f"{code}_prompts.xlsx"
    srt_path = local_dir / f"{code}.srt"

    if not excel_path.exists():
        if srt_path.exists():
            log(f"  No Excel found, creating (BASIC mode)...")
            if not create_excel_with_api_basic(local_dir, code, callback):
                log(f"  Failed to create Excel, skip!", "ERROR")
                return False
        else:
            log(f"  No Excel and no SRT, skip!")
            return False
    elif not has_excel_with_prompts(local_dir, code):
        log(f"  Excel empty/corrupt, recreating (BASIC mode)...")
        excel_path.unlink()
        if not create_excel_with_api_basic(local_dir, code, callback):
            log(f"  Failed to recreate Excel, skip!", "ERROR")
            return False

    # Step 4: Get prompts from Excel
    log(f"  Reading prompts from Excel...")
    all_prompts = get_prompts_from_excel(excel_path, local_dir)

    if not all_prompts:
        log(f"  No prompts found in Excel!", "ERROR")
        return False

    log(f"  Found {len(all_prompts)} prompts")

    # Step 5: Generate images using 2 Chrome in parallel
    generator = DualChromeImageGenerator(callback=callback)
    result = generator.generate_parallel(all_prompts, local_dir)

    if result.get('failed', 0) > 0:
        log(f"  Some images failed: {result['failed']}", "WARN")

    # Step 6: Check completion
    if is_local_pic_complete(local_dir, code):
        log(f"  Images complete!")
        return True
    else:
        log(f"  Images incomplete", "WARN")
        return False


def scan_incomplete_local_projects() -> list:
    """Scan local PROJECTS for incomplete projects."""
    incomplete = []

    if not LOCAL_PROJECTS.exists():
        return incomplete

    for item in LOCAL_PROJECTS.iterdir():
        if not item.is_dir():
            continue

        code = item.name

        if not matches_channel(code):
            continue

        if is_project_complete_on_master(code):
            continue

        if is_local_pic_complete(item, code):
            continue

        srt_path = item / f"{code}.srt"
        if has_excel_with_prompts(item, code):
            print(f"    - {code}: incomplete (has Excel, no images)")
            incomplete.append(code)
        elif srt_path.exists():
            print(f"    - {code}: has SRT, no Excel")
            incomplete.append(code)

    return sorted(incomplete)


def scan_master_projects() -> list:
    """Scan master PROJECTS folder for pending projects."""
    pending = []

    if not MASTER_PROJECTS.exists():
        return pending

    for item in MASTER_PROJECTS.iterdir():
        if not item.is_dir():
            continue

        code = item.name

        if not matches_channel(code):
            continue

        if is_project_complete_on_master(code):
            continue

        srt_path = item / f"{code}.srt"

        if has_excel_with_prompts(item, code):
            print(f"    - {code}: ready (has prompts)")
            pending.append(code)
        elif srt_path.exists():
            print(f"    - {code}: has SRT")
            pending.append(code)

    return sorted(pending)


def run_scan_loop():
    """Run continuous scan loop for IMAGE generation (2-Chrome mode)."""
    print(f"\n{'='*60}")
    print(f"  VE3 TOOL - WORKER PIC BASIC 2-CHROME")
    print(f"{'='*60}")
    print(f"  Worker folder:   {TOOL_DIR.parent.name}")
    print(f"  Channel filter:  {WORKER_CHANNEL or 'ALL'}")
    print(f"  Mode:            2-CHROME PARALLEL")
    print(f"  Chrome1:         Characters + 50% scenes")
    print(f"  Chrome2:         Locations + 50% scenes")
    print(f"{'='*60}")

    cycle = 0

    while True:
        cycle += 1
        print(f"\n[2-CHROME CYCLE {cycle}] Scanning...")

        incomplete_local = scan_incomplete_local_projects()
        pending_master = scan_master_projects()
        pending = list(dict.fromkeys(incomplete_local + pending_master))

        if not pending:
            print(f"  No pending projects")
            print(f"\n  Waiting {SCAN_INTERVAL}s... (Ctrl+C to stop)")
            try:
                time.sleep(SCAN_INTERVAL)
            except KeyboardInterrupt:
                print("\n\nStopped by user.")
                break
        else:
            print(f"  Found: {len(pending)} pending projects")

            for code in pending:
                try:
                    success = process_project_pic_basic_2(code)
                    if not success:
                        print(f"  Skipping {code}, moving to next...")
                        continue
                except KeyboardInterrupt:
                    print("\n\nStopped by user.")
                    return
                except Exception as e:
                    print(f"  Error processing {code}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue

            print(f"\n  Processed all pending projects!")
            print(f"  Waiting {SCAN_INTERVAL}s... (Ctrl+C to stop)")
            try:
                time.sleep(SCAN_INTERVAL)
            except KeyboardInterrupt:
                print("\n\nStopped by user.")
                break


def main():
    import argparse
    parser = argparse.ArgumentParser(description='VE3 Worker PIC BASIC 2-Chrome - Parallel Image Generation')
    parser.add_argument('project', nargs='?', default=None, help='Project code')
    args = parser.parse_args()

    if args.project:
        process_project_pic_basic_2(args.project)
    else:
        run_scan_loop()


if __name__ == "__main__":
    main()
