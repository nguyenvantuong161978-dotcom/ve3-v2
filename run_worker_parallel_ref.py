#!/usr/bin/env python3
"""
Worker Script - Parallel References (2 Chrome)
==============================================
Tạo ảnh tham chiếu (nv/loc) bằng 2 Chrome song song.

Usage:
    python run_worker_parallel_ref.py KA2-0002
"""

import sys
import threading
from pathlib import Path
from modules.utils import load_settings
from modules.browser_flow_generator import BrowserFlowGenerator

def worker_thread(worker_id, project_dir, code, excel_path, settings):
    """
    Worker thread - chạy 1 Chrome instance.

    Args:
        worker_id: 0 hoặc 1
        project_dir: PROJECTS/KA2-0002
        code: KA2-0002
        excel_path: Path to Excel
        settings: Config dict
    """
    print(f"\n[Worker {worker_id}] Starting...")

    # Create generator với worker_id
    generator = BrowserFlowGenerator(
        project_path=str(project_dir),
        profile_name="main",
        headless=False,
        verbose=True,
        config_path="config/settings.yaml",
        worker_id=worker_id,
        total_workers=2,  # 2 Chrome workers
        chrome_portable=None
    )

    # Load project_id từ Excel nếu có
    try:
        from modules.excel_manager import PromptWorkbook
        wb = PromptWorkbook(excel_path)
        wb.load_or_create()
        project_id = wb.workbook['metadata'].cell(2, 2).value if 'metadata' in wb.workbook.sheetnames else None
        if project_id:
            generator.config['flow_project_id'] = project_id
            print(f"[Worker {worker_id}] Using project_id from Excel: {project_id[:8]}...")
    except:
        pass

    # Load reference prompts từ Excel
    from modules.excel_manager import PromptWorkbook
    wb = PromptWorkbook(excel_path)
    wb.load_or_create()

    # Get prompts từ characters sheet (nv*/loc*)
    ref_prompts = []
    ws = wb.workbook['characters']
    for row_idx, row in enumerate(ws.iter_rows(min_row=2), start=2):
        char_id = row[0].value  # Column A
        if not char_id:
            continue

        # Chỉ xử lý references (nv/loc)
        if not (str(char_id).startswith('nv') or str(char_id).startswith('loc')):
            continue

        # Check status - skip if "skip"
        status = row[8].value if len(row) > 8 else None
        if status and str(status).lower() == "skip":
            print(f"[Worker {worker_id}] SKIP {char_id}: status=skip")
            continue

        prompt = row[3].value  # Column D (english_prompt)
        if prompt and str(prompt).upper() != "DO_NOT_GENERATE":
            ref_prompts.append({
                'id': char_id,
                'prompt': prompt,
                'aspect_ratio': "16:9",  # References always 16:9
                'output_path': str(project_dir / "nv" / f"{char_id}.png")
            })

    print(f"[Worker {worker_id}] Found {len(ref_prompts)} reference prompts")

    # Generate với worker_id (parallel mode)
    # Code trong browser_flow_generator sẽ tự động skip scenes không thuộc worker này
    # NHƯNG với all_are_references=True, nó sẽ xử lý TẤT CẢ
    result = generator.generate_from_prompts(
        prompts=ref_prompts,
        excel_path=excel_path
    )

    stats = result.get('stats', {})
    print(f"\n[Worker {worker_id}] DONE!")
    print(f"[Worker {worker_id}] Success: {stats.get('success', 0)}")
    print(f"[Worker {worker_id}] Failed: {stats.get('failed', 0)}")
    print(f"[Worker {worker_id}] Skipped: {stats.get('skipped', 0)}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_worker_parallel_ref.py KA2-0002")
        return 1

    code = sys.argv[1]
    project_dir = Path(f"PROJECTS/{code}")
    excel_path = project_dir / f"{code}_prompts.xlsx"

    if not project_dir.exists():
        print(f"ERROR: Project directory not found: {project_dir}")
        return 1

    if not excel_path.exists():
        print(f"ERROR: Excel not found: {excel_path}")
        return 1

    print("=" * 80)
    print(f"  PARALLEL REFERENCE GENERATOR - 2 Chrome Workers")
    print("=" * 80)
    print(f"  Project: {code}")
    print(f"  Excel: {excel_path}")
    print("=" * 80)

    # Load settings
    settings = load_settings(Path("config/settings.yaml"))

    # Start 2 worker threads
    threads = []
    for worker_id in [0, 1]:
        thread = threading.Thread(
            target=worker_thread,
            args=(worker_id, project_dir, code, excel_path, settings),
            name=f"RefWorker-{worker_id}"
        )
        thread.start()
        threads.append(thread)

    print("\n[MAIN] Waiting for both workers to complete...")

    # Wait for both to finish
    for thread in threads:
        thread.join()

    print("\n" + "=" * 80)
    print("  ✅ ALL WORKERS COMPLETED!")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
