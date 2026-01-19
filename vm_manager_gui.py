#!/usr/bin/env python3
"""
VM Manager GUI - Giao diện đồ họa để quản lý Chrome Workers
============================================================

Giao diện trực quan để:
1. Chọn chế độ: Excel (Basic/Full), Video (Basic/Full)
2. Điều khiển workers (Start/Stop/Restart)
3. Xem tiến độ real-time
4. Xem lỗi và logs
5. Quản lý IPv6

Usage:
    python vm_manager_gui.py
"""

# Fix Windows encoding issues - must be before any other imports
import sys
import os
if sys.platform == "win32":
    # Force UTF-8 for stdout/stderr on Windows
    if sys.stdout:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if sys.stderr:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    # Also set environment variable for subprocesses
    os.environ['PYTHONIOENCODING'] = 'utf-8'

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import time
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

# Import VM Manager
try:
    from vm_manager import VMManager, WorkerStatus, TaskStatus, TaskType, SettingsManager
    VM_MANAGER_AVAILABLE = True
except ImportError:
    VM_MANAGER_AVAILABLE = False

TOOL_DIR = Path(__file__).parent


def startup_cleanup():
    """Clean up logs and cache on startup."""
    import shutil

    print("[STARTUP] Cleaning up...")

    # 1. Clear old log files
    log_dir = TOOL_DIR / ".agent" / "logs"
    if log_dir.exists():
        for log_file in log_dir.glob("*.log"):
            try:
                log_file.unlink()
                print(f"  Deleted: {log_file.name}")
            except:
                pass

    # 2. Clear __pycache__ directories
    cache_count = 0
    for cache_dir in TOOL_DIR.rglob("__pycache__"):
        try:
            shutil.rmtree(cache_dir)
            cache_count += 1
        except:
            pass
    if cache_count:
        print(f"  Cleared {cache_count} __pycache__ directories")

    # 3. Kill any orphan Chrome/Python processes (optional, safer not to do by default)
    # subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True)

    print("[STARTUP] Cleanup complete!")


# Run cleanup on import
startup_cleanup()


class SettingsDialog(tk.Toplevel):
    """Dialog cài đặt chi tiết."""

    def __init__(self, parent, settings_manager):
        super().__init__(parent)
        self.title("Settings")
        self.geometry("500x600")
        self.resizable(False, False)

        self.settings = settings_manager
        self.result = None

        # Make modal
        self.transient(parent)
        self.grab_set()

        self._build_ui()
        self._load_settings()

    def _build_ui(self):
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        # Tab 1: General
        general_frame = ttk.Frame(notebook, padding=10)
        notebook.add(general_frame, text="General")
        self._build_general_tab(general_frame)

        # Tab 2: Excel
        excel_frame = ttk.Frame(notebook, padding=10)
        notebook.add(excel_frame, text="Excel")
        self._build_excel_tab(excel_frame)

        # Tab 3: Video
        video_frame = ttk.Frame(notebook, padding=10)
        notebook.add(video_frame, text="Video")
        self._build_video_tab(video_frame)

        # Tab 4: IPv6
        ipv6_frame = ttk.Frame(notebook, padding=10)
        notebook.add(ipv6_frame, text="IPv6")
        self._build_ipv6_tab(ipv6_frame)

        # Buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=10, pady=10)

        ttk.Button(btn_frame, text="Save", command=self._save).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="Reset Defaults", command=self._reset_defaults).pack(side="left")

    def _build_general_tab(self, parent):
        # Chrome Workers
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text="Chrome Workers:", width=20).pack(side="left")
        self.chrome_count_var = tk.StringVar(value="2")
        ttk.Spinbox(row, from_=1, to=10, textvariable=self.chrome_count_var, width=10).pack(side="left")

        # Excel Mode
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text="Excel Mode:", width=20).pack(side="left")
        self.excel_mode_var = tk.StringVar(value="full")
        ttk.Combobox(row, textvariable=self.excel_mode_var,
                     values=["basic", "full"], width=15, state="readonly").pack(side="left")
        ttk.Label(row, text="(basic: chỉ prompt cơ bản, full: đầy đủ chi tiết)").pack(side="left", padx=10)

        # Video Mode
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text="Video Mode:", width=20).pack(side="left")
        self.video_mode_var = tk.StringVar(value="full")
        ttk.Combobox(row, textvariable=self.video_mode_var,
                     values=["basic", "full"], width=15, state="readonly").pack(side="left")
        ttk.Label(row, text="(basic: 8s đầu, full: toàn bộ)").pack(side="left", padx=10)

        # Auto restart
        self.auto_restart_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(parent, text="Auto restart on error",
                        variable=self.auto_restart_var).pack(anchor="w", pady=5)

        # Max retries
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text="Max Retries:", width=20).pack(side="left")
        self.max_retries_var = tk.StringVar(value="3")
        ttk.Spinbox(row, from_=1, to=10, textvariable=self.max_retries_var, width=10).pack(side="left")

    def _build_excel_tab(self, parent):
        ttk.Label(parent, text="Excel Generation Settings",
                  font=("Arial", 10, "bold")).pack(anchor="w", pady=(0, 10))

        # API Selection
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text="AI API:", width=20).pack(side="left")
        self.ai_api_var = tk.StringVar(value="deepseek")
        ttk.Combobox(row, textvariable=self.ai_api_var,
                     values=["deepseek", "gemini", "groq"], width=15, state="readonly").pack(side="left")

        # Max parallel API
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text="Max Parallel API:", width=20).pack(side="left")
        self.max_api_var = tk.StringVar(value="6")
        ttk.Spinbox(row, from_=1, to=20, textvariable=self.max_api_var, width=10).pack(side="left")

        # Scene duration
        ttk.Label(parent, text="Scene Duration",
                  font=("Arial", 9, "bold")).pack(anchor="w", pady=(15, 5))

        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text="Min (seconds):", width=20).pack(side="left")
        self.min_duration_var = tk.StringVar(value="5")
        ttk.Spinbox(row, from_=3, to=15, textvariable=self.min_duration_var, width=10).pack(side="left")

        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text="Max (seconds):", width=20).pack(side="left")
        self.max_duration_var = tk.StringVar(value="8")
        ttk.Spinbox(row, from_=5, to=20, textvariable=self.max_duration_var, width=10).pack(side="left")

    def _build_video_tab(self, parent):
        ttk.Label(parent, text="Video Generation Settings",
                  font=("Arial", 10, "bold")).pack(anchor="w", pady=(0, 10))

        # Video count
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text="Video Count:", width=20).pack(side="left")
        self.video_count_var = tk.StringVar(value="full")
        ttk.Combobox(row, textvariable=self.video_count_var,
                     values=["full", "10", "20", "30", "50"], width=15).pack(side="left")
        ttk.Label(row, text="(full = tất cả scenes)").pack(side="left", padx=10)

        # Video model
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text="Video Model:", width=20).pack(side="left")
        self.video_model_var = tk.StringVar(value="fast")
        ttk.Combobox(row, textvariable=self.video_model_var,
                     values=["fast", "quality"], width=15, state="readonly").pack(side="left")

        # Generation mode
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text="Generation Mode:", width=20).pack(side="left")
        self.gen_mode_var = tk.StringVar(value="t2v")
        ttk.Combobox(row, textvariable=self.gen_mode_var,
                     values=["t2v", "i2v"], width=15, state="readonly").pack(side="left")
        ttk.Label(row, text="(t2v: text-to-video, i2v: image-to-video)").pack(side="left", padx=10)

        # Aspect ratio
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text="Aspect Ratio:", width=20).pack(side="left")
        self.aspect_var = tk.StringVar(value="landscape")
        ttk.Combobox(row, textvariable=self.aspect_var,
                     values=["landscape", "portrait", "square"], width=15, state="readonly").pack(side="left")

        # Use proxy
        self.use_proxy_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(parent, text="Use Proxy API (bypass captcha)",
                        variable=self.use_proxy_var).pack(anchor="w", pady=10)

    def _build_ipv6_tab(self, parent):
        ttk.Label(parent, text="IPv6 Rotation Settings",
                  font=("Arial", 10, "bold")).pack(anchor="w", pady=(0, 10))

        # Enable
        self.ipv6_enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(parent, text="Enable IPv6 Rotation",
                        variable=self.ipv6_enabled_var).pack(anchor="w", pady=5)

        # Interface
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text="Interface Name:", width=20).pack(side="left")
        self.interface_var = tk.StringVar(value="Ethernet")
        ttk.Entry(row, textvariable=self.interface_var, width=20).pack(side="left")

        # Subnet prefix
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text="Subnet Prefix:", width=20).pack(side="left")
        self.subnet_var = tk.StringVar(value="")
        ttk.Entry(row, textvariable=self.subnet_var, width=30).pack(side="left")

        # Prefix length
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text="Prefix Length:", width=20).pack(side="left")
        self.prefix_len_var = tk.StringVar(value="56")
        ttk.Spinbox(row, from_=48, to=64, textvariable=self.prefix_len_var, width=10).pack(side="left")

        # Max 403 before rotate
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text="Max 403 before rotate:", width=20).pack(side="left")
        self.max_403_var = tk.StringVar(value="5")
        ttk.Spinbox(row, from_=1, to=20, textvariable=self.max_403_var, width=10).pack(side="left")

        # Max errors before clear
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text="Max errors before clear:", width=20).pack(side="left")
        self.max_errors_var = tk.StringVar(value="3")
        ttk.Spinbox(row, from_=1, to=10, textvariable=self.max_errors_var, width=10).pack(side="left")

    def _load_settings(self):
        """Load current settings."""
        if not self.settings:
            return

        config = self.settings.config

        self.chrome_count_var.set(str(self.settings.chrome_count))
        self.excel_mode_var.set(self.settings.excel_mode)

        self.max_api_var.set(str(config.get('max_parallel_api', 6)))
        self.min_duration_var.set(str(config.get('min_scene_duration', 5)))
        self.max_duration_var.set(str(config.get('max_scene_duration', 8)))

        self.video_count_var.set(str(config.get('video_count', 'full')))
        self.video_model_var.set(config.get('video_model', 'fast'))
        self.gen_mode_var.set(config.get('video_generation_mode', 't2v'))
        self.aspect_var.set(config.get('video_aspect_ratio', 'landscape'))
        self.use_proxy_var.set(config.get('use_proxy', True))

        ipv6 = config.get('ipv6_rotation', {})
        self.ipv6_enabled_var.set(ipv6.get('enabled', False))
        self.interface_var.set(ipv6.get('interface_name', 'Ethernet'))
        self.subnet_var.set(ipv6.get('subnet_prefix', ''))
        self.prefix_len_var.set(str(ipv6.get('prefix_length', 56)))
        self.max_403_var.set(str(ipv6.get('max_403_before_rotate', 5)))

    def _save(self):
        """Save settings."""
        if not self.settings:
            self.destroy()
            return

        config = self.settings.config

        # General
        self.settings.chrome_count = int(self.chrome_count_var.get())
        self.settings.excel_mode = self.excel_mode_var.get()

        # Excel
        config['max_parallel_api'] = int(self.max_api_var.get())
        config['min_scene_duration'] = int(self.min_duration_var.get())
        config['max_scene_duration'] = int(self.max_duration_var.get())

        # Video
        config['video_count'] = self.video_count_var.get()
        config['video_model'] = self.video_model_var.get()
        config['video_generation_mode'] = self.gen_mode_var.get()
        config['video_aspect_ratio'] = self.aspect_var.get()
        config['use_proxy'] = self.use_proxy_var.get()

        # IPv6
        if 'ipv6_rotation' not in config:
            config['ipv6_rotation'] = {}
        config['ipv6_rotation']['enabled'] = self.ipv6_enabled_var.get()
        config['ipv6_rotation']['interface_name'] = self.interface_var.get()
        config['ipv6_rotation']['subnet_prefix'] = self.subnet_var.get()
        config['ipv6_rotation']['prefix_length'] = int(self.prefix_len_var.get())
        config['ipv6_rotation']['max_403_before_rotate'] = int(self.max_403_var.get())

        self.settings.save_config()
        self.result = True
        self.destroy()

    def _reset_defaults(self):
        """Reset to default values."""
        self.chrome_count_var.set("2")
        self.excel_mode_var.set("full")
        self.video_mode_var.set("full")
        self.max_api_var.set("6")
        self.min_duration_var.set("5")
        self.max_duration_var.set("8")
        self.video_count_var.set("full")
        self.video_model_var.set("fast")
        self.gen_mode_var.set("t2v")
        self.aspect_var.set("landscape")
        self.use_proxy_var.set(True)
        self.ipv6_enabled_var.set(True)
        self.interface_var.set("Ethernet")
        self.max_403_var.set("5")
        self.max_errors_var.set("3")


class ProjectDetailDialog(tk.Toplevel):
    """Dialog hiển thị chi tiết project với prompts và images."""

    def __init__(self, parent, project_code: str, quality_checker, manager=None):
        super().__init__(parent)
        self.title(f"Project: {project_code}")
        self.geometry("1200x800")

        self.project_code = project_code
        self.quality_checker = quality_checker
        self.manager = manager  # For getting worker status
        self._image_cache = {}  # Cache for loaded images
        self._ref_images = []  # Keep references to prevent GC

        # Make modal
        self.transient(parent)

        self._build_ui()
        self._load_data()

        # Auto-refresh
        self._auto_refresh()

    def _build_ui(self):
        # ===== TOP: Worker Status Bar =====
        status_frame = ttk.LabelFrame(self, text="Worker Status", padding=5)
        status_frame.pack(fill="x", padx=10, pady=(10, 5))

        # Chrome 1 status
        c1_frame = ttk.Frame(status_frame)
        c1_frame.pack(fill="x", pady=2)
        ttk.Label(c1_frame, text="Chrome 1 (odd):", width=15, font=("Arial", 9, "bold")).pack(side="left")
        self.chrome1_status_var = tk.StringVar(value="idle")
        ttk.Label(c1_frame, textvariable=self.chrome1_status_var, width=60).pack(side="left")

        # Chrome 2 status
        c2_frame = ttk.Frame(status_frame)
        c2_frame.pack(fill="x", pady=2)
        ttk.Label(c2_frame, text="Chrome 2 (even):", width=15, font=("Arial", 9, "bold")).pack(side="left")
        self.chrome2_status_var = tk.StringVar(value="idle")
        ttk.Label(c2_frame, textvariable=self.chrome2_status_var, width=60).pack(side="left")

        # ===== EXCEL WORKFLOW STATUS =====
        workflow_frame = ttk.LabelFrame(self, text="Excel Workflow Status", padding=5)
        workflow_frame.pack(fill="x", padx=10, pady=5)

        # Row 1: SRT + Characters
        row1 = ttk.Frame(workflow_frame)
        row1.pack(fill="x", pady=2)

        # SRT Status
        ttk.Label(row1, text="SRT:", width=8).pack(side="left")
        self.srt_status_var = tk.StringVar(value="...")
        self.srt_status_label = ttk.Label(row1, textvariable=self.srt_status_var, width=12)
        self.srt_status_label.pack(side="left")

        ttk.Label(row1, text="  |  ").pack(side="left")

        # Characters Status
        ttk.Label(row1, text="Characters:", width=10).pack(side="left")
        self.chars_status_var = tk.StringVar(value="...")
        self.chars_status_label = ttk.Label(row1, textvariable=self.chars_status_var, width=25)
        self.chars_status_label.pack(side="left")

        ttk.Label(row1, text="  |  ").pack(side="left")

        # NV Images
        ttk.Label(row1, text="NV Images:", width=10).pack(side="left")
        self.nv_count_var = tk.StringVar(value="...")
        ttk.Label(row1, textvariable=self.nv_count_var, width=8).pack(side="left")

        # Row 2: Prompts + Excel Status
        row2 = ttk.Frame(workflow_frame)
        row2.pack(fill="x", pady=2)

        # Prompts Status
        ttk.Label(row2, text="Prompts:", width=8).pack(side="left")
        self.prompts_status_var = tk.StringVar(value="...")
        self.prompts_status_label = ttk.Label(row2, textvariable=self.prompts_status_var, width=25)
        self.prompts_status_label.pack(side="left")

        ttk.Label(row2, text="  |  ").pack(side="left")

        # Excel Overall Status
        ttk.Label(row2, text="Excel Status:", width=12).pack(side="left")
        self.excel_status_var = tk.StringVar(value="...")
        self.excel_status_label = ttk.Label(row2, textvariable=self.excel_status_var, width=15,
                                             font=("Arial", 9, "bold"))
        self.excel_status_label.pack(side="left")

        ttk.Label(row2, text="  |  ").pack(side="left")

        # Current Step
        ttk.Label(row2, text="Step:", width=5).pack(side="left")
        self.current_step_var = tk.StringVar(value="...")
        ttk.Label(row2, textvariable=self.current_step_var, width=10,
                  font=("Arial", 9, "bold")).pack(side="left")

        # Row 3: Video Mode + Segment 1 info
        row3 = ttk.Frame(workflow_frame)
        row3.pack(fill="x", pady=2)

        # Video Mode
        ttk.Label(row3, text="Video Mode:", width=11).pack(side="left")
        self.video_mode_var = tk.StringVar(value="...")
        self.video_mode_label = ttk.Label(row3, textvariable=self.video_mode_var, width=10,
                                           font=("Arial", 9, "bold"))
        self.video_mode_label.pack(side="left")

        ttk.Label(row3, text="  |  ").pack(side="left")

        # Segment 1 info
        ttk.Label(row3, text="Seg.1 Scenes:", width=12).pack(side="left")
        self.seg1_scenes_var = tk.StringVar(value="...")
        ttk.Label(row3, textvariable=self.seg1_scenes_var, width=15).pack(side="left")

        ttk.Label(row3, text="  |  ").pack(side="left")

        # Videos Needed
        ttk.Label(row3, text="Videos Need:", width=12).pack(side="left")
        self.videos_need_var = tk.StringVar(value="...")
        ttk.Label(row3, textvariable=self.videos_need_var, width=15).pack(side="left")

        # ===== MAIN: Notebook with tabs =====
        main_notebook = ttk.Notebook(self)
        main_notebook.pack(fill="both", expand=True, padx=10, pady=5)

        # ----- Tab 1: Scenes Overview -----
        scenes_tab = ttk.Frame(main_notebook, padding=5)
        main_notebook.add(scenes_tab, text="Scenes")

        scenes_paned = ttk.PanedWindow(scenes_tab, orient="horizontal")
        scenes_paned.pack(fill="both", expand=True)

        # Left: Scene list
        left_frame = ttk.Frame(scenes_paned)
        scenes_paned.add(left_frame, weight=1)

        ttk.Label(left_frame, text="All Scenes", font=("Arial", 10, "bold")).pack(anchor="w")

        list_frame = ttk.Frame(left_frame)
        list_frame.pack(fill="both", expand=True, pady=5)

        self.scene_listbox = tk.Listbox(list_frame, font=("Consolas", 9), selectmode="single")
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.scene_listbox.yview)
        self.scene_listbox.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.scene_listbox.pack(side="left", fill="both", expand=True)
        self.scene_listbox.bind("<<ListboxSelect>>", self._on_scene_select)

        # Summary
        self.summary_var = tk.StringVar(value="Loading...")
        ttk.Label(left_frame, textvariable=self.summary_var, font=("Consolas", 9)).pack(anchor="w", pady=5)

        # Right: Detail + Preview
        right_frame = ttk.Frame(scenes_paned)
        scenes_paned.add(right_frame, weight=2)

        # Scene info
        info_frame = ttk.LabelFrame(right_frame, text="Scene Details", padding=5)
        info_frame.pack(fill="x", pady=(0, 5))

        row = ttk.Frame(info_frame)
        row.pack(fill="x")
        ttk.Label(row, text="Scene:", width=10).pack(side="left")
        self.scene_num_var = tk.StringVar(value="-")
        ttk.Label(row, textvariable=self.scene_num_var, font=("Arial", 10, "bold")).pack(side="left")
        ttk.Label(row, text="  Timing:").pack(side="left", padx=(20, 0))
        self.timing_var = tk.StringVar(value="-")
        ttk.Label(row, textvariable=self.timing_var).pack(side="left")

        row = ttk.Frame(info_frame)
        row.pack(fill="x")
        ttk.Label(row, text="Subtitle:", width=10).pack(side="left")
        self.subtitle_var = tk.StringVar(value="-")
        ttk.Label(row, textvariable=self.subtitle_var, wraplength=500).pack(side="left")

        # Prompt text
        prompt_frame = ttk.LabelFrame(right_frame, text="Image Prompt", padding=5)
        prompt_frame.pack(fill="x", pady=5)
        self.img_prompt_text = scrolledtext.ScrolledText(prompt_frame, height=4, font=("Consolas", 8),
                                                          wrap="word", state="disabled")
        self.img_prompt_text.pack(fill="both", expand=True)

        # Preview
        preview_frame = ttk.LabelFrame(right_frame, text="Preview", padding=5)
        preview_frame.pack(fill="both", expand=True)
        self.image_label = ttk.Label(preview_frame, text="Select a scene", anchor="center")
        self.image_label.pack(fill="both", expand=True)
        self.preview_status_var = tk.StringVar(value="")
        ttk.Label(preview_frame, textvariable=self.preview_status_var).pack(anchor="w")

        # ----- Tab 2: References (nv/) -----
        refs_tab = ttk.Frame(main_notebook, padding=5)
        main_notebook.add(refs_tab, text="References (nv/)")

        # Canvas for thumbnails
        refs_canvas_frame = ttk.Frame(refs_tab)
        refs_canvas_frame.pack(fill="both", expand=True)

        self.refs_canvas = tk.Canvas(refs_canvas_frame, bg="white")
        refs_scrollbar = ttk.Scrollbar(refs_canvas_frame, orient="vertical", command=self.refs_canvas.yview)
        self.refs_inner = ttk.Frame(self.refs_canvas)

        self.refs_canvas.configure(yscrollcommand=refs_scrollbar.set)
        refs_scrollbar.pack(side="right", fill="y")
        self.refs_canvas.pack(side="left", fill="both", expand=True)
        self.refs_canvas.create_window((0, 0), window=self.refs_inner, anchor="nw")
        self.refs_inner.bind("<Configure>", lambda e: self.refs_canvas.configure(scrollregion=self.refs_canvas.bbox("all")))

        # ----- Tab 3: Failed/Skipped -----
        failed_tab = ttk.Frame(main_notebook, padding=5)
        main_notebook.add(failed_tab, text="Failed/Skipped")

        self.failed_text = scrolledtext.ScrolledText(failed_tab, font=("Consolas", 9), state="disabled")
        self.failed_text.pack(fill="both", expand=True)

        # Hidden video prompt (keep for compatibility)
        self.vid_prompt_text = scrolledtext.ScrolledText(right_frame, height=1)

        # ===== BOTTOM: Buttons =====
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=10, pady=10)

        ttk.Button(btn_frame, text="Refresh", command=self._load_data).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Open IMG Folder", command=self._open_folder).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Open NV Folder", command=self._open_nv_folder).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Close", command=self.destroy).pack(side="right", padx=5)

    def _load_data(self):
        """Load project data."""
        try:
            from modules.excel_manager import PromptWorkbook

            project_dir = Path(__file__).parent / "PROJECTS" / self.project_code
            img_dir = project_dir / "img"
            excel_path = project_dir / f"{self.project_code}_prompts.xlsx"

            if not excel_path.exists():
                self.summary_var.set("Excel file not found")
                return

            wb = PromptWorkbook(str(excel_path))
            self.scenes = wb.get_scenes()

            # Update listbox
            self.scene_listbox.delete(0, "end")
            for scene in self.scenes:
                scene_id = scene.scene_id
                # Check actual files in img/ folder
                actual_img = img_dir / f"{scene_id}.png"
                img_exists = actual_img.exists()
                vid_icon = "[v]" if scene.video_path and Path(scene.video_path).exists() else "○"
                prompt_icon = "[v]" if scene.img_prompt else "○"
                img_icon = "[v]" if img_exists else "○"

                self.scene_listbox.insert("end",
                    f"Scene {scene_id:03d} │ P:{prompt_icon} I:{img_icon} V:{vid_icon}")

                # Color based on status
                if img_exists:
                    self.scene_listbox.itemconfig("end", fg="green")
                elif not scene.img_prompt:
                    self.scene_listbox.itemconfig("end", fg="red")

            # Summary
            status = self.quality_checker.get_project_status(self.project_code)
            self.summary_var.set(
                f"Total: {status.total_scenes} scenes\n"
                f"Prompts: {status.img_prompts_count}/{status.total_scenes}\n"
                f"Images: {status.images_done}/{status.total_scenes}\n"
                f"Videos: {status.videos_done}/{status.total_scenes}"
            )

            # Update Excel Workflow Status
            self._update_workflow_status(status)

            # Update worker status
            self._update_worker_status()

            # Load failed/skipped
            self._load_failed_skipped()

            # Load references only on first load
            if not self._ref_images:
                self._load_references()

        except Exception as e:
            self.summary_var.set(f"Error: {str(e)[:50]}")

    def _on_scene_select(self, event=None):
        """Handle scene selection."""
        selection = self.scene_listbox.curselection()
        if not selection:
            return

        idx = selection[0]
        if idx >= len(self.scenes):
            return

        scene = self.scenes[idx]

        # Update info
        self.scene_num_var.set(str(scene.scene_id))
        self.timing_var.set(f"{scene.srt_start} → {scene.srt_end}")
        self.subtitle_var.set(scene.srt_text or "-")

        # Update prompts
        self.img_prompt_text.configure(state="normal")
        self.img_prompt_text.delete("1.0", "end")
        self.img_prompt_text.insert("1.0", scene.img_prompt or "(No prompt)")
        self.img_prompt_text.configure(state="disabled")

        self.vid_prompt_text.configure(state="normal")
        self.vid_prompt_text.delete("1.0", "end")
        self.vid_prompt_text.insert("1.0", scene.video_prompt or "(No video prompt)")
        self.vid_prompt_text.configure(state="disabled")

        # Load image preview
        self._load_image_preview(scene)

    def _load_image_preview(self, scene):
        """Load and display image preview."""
        # Check actual img/{scene_id}.png path
        img_dir = Path(__file__).parent / "PROJECTS" / self.project_code / "img"
        img_path = img_dir / f"{scene.scene_id}.png"

        if not img_path.exists():
            self.image_label.configure(image="", text="No image generated")
            self.preview_status_var.set("")
            return

        img_path_str = str(img_path)
        try:
            # Check cache
            if img_path_str in self._image_cache:
                self.image_label.configure(image=self._image_cache[img_path_str], text="")
                self.preview_status_var.set(f"Image: {img_path.name}")
                return

            # Load and resize image
            from PIL import Image, ImageTk

            img = Image.open(img_path)

            # Resize to fit (max 400x300)
            max_size = (400, 300)
            img.thumbnail(max_size, Image.Resampling.LANCZOS)

            photo = ImageTk.PhotoImage(img)

            # Cache and display
            self._image_cache[img_path_str] = photo
            self.image_label.configure(image=photo, text="")
            self.preview_status_var.set(f"Image: {img_path.name}")

        except ImportError:
            self.image_label.configure(image="", text="PIL not installed\n(pip install Pillow)")
            self.preview_status_var.set(str(img_path))
        except Exception as e:
            self.image_label.configure(image="", text=f"Error: {str(e)[:30]}")
            self.preview_status_var.set("")

    def _open_folder(self):
        """Open project folder."""
        import subprocess
        import sys

        project_dir = Path(__file__).parent / "PROJECTS" / self.project_code

        if sys.platform == "win32":
            subprocess.run(["explorer", str(project_dir)])
        elif sys.platform == "darwin":
            subprocess.run(["open", str(project_dir)])
        else:
            subprocess.run(["xdg-open", str(project_dir)])

    def _auto_refresh(self):
        """Auto-refresh data every 5 seconds."""
        if self.winfo_exists():
            self._load_data()
            self.after(5000, self._auto_refresh)

    def _open_nv_folder(self):
        """Open nv/ folder in file explorer."""
        import subprocess
        nv_dir = Path(__file__).parent / "PROJECTS" / self.project_code / "nv"
        if not nv_dir.exists():
            nv_dir.mkdir(parents=True, exist_ok=True)

        if sys.platform == "win32":
            subprocess.run(["explorer", str(nv_dir)])
        else:
            subprocess.run(["xdg-open", str(nv_dir)])

    def _load_references(self):
        """Load reference images from nv/ folder."""
        # Clear existing
        for widget in self.refs_inner.winfo_children():
            widget.destroy()
        self._ref_images.clear()

        nv_dir = Path(__file__).parent / "PROJECTS" / self.project_code / "nv"
        if not nv_dir.exists():
            ttk.Label(self.refs_inner, text="No nv/ folder found").grid(row=0, column=0, pady=20)
            return

        # Find all images
        images = list(nv_dir.glob("*.png")) + list(nv_dir.glob("*.jpg")) + list(nv_dir.glob("*.jpeg"))
        if not images:
            ttk.Label(self.refs_inner, text="No reference images in nv/ folder").grid(row=0, column=0, pady=20)
            return

        try:
            from PIL import Image, ImageTk

            cols = 4
            thumb_size = (150, 150)

            for idx, img_path in enumerate(sorted(images)):
                row = idx // cols
                col = idx % cols

                # Create thumbnail frame
                frame = ttk.Frame(self.refs_inner, padding=5)
                frame.grid(row=row, column=col, padx=5, pady=5)

                try:
                    img = Image.open(img_path)
                    img.thumbnail(thumb_size, Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                    self._ref_images.append(photo)  # Keep reference

                    lbl = ttk.Label(frame, image=photo)
                    lbl.pack()
                    ttk.Label(frame, text=img_path.name, font=("Arial", 8), wraplength=140).pack()
                except Exception as e:
                    ttk.Label(frame, text=f"Error: {img_path.name}").pack()

        except ImportError:
            ttk.Label(self.refs_inner, text="PIL not installed (pip install Pillow)").grid(row=0, column=0, pady=20)

    def _load_failed_skipped(self):
        """Load failed/skipped scenes from log."""
        self.failed_text.configure(state="normal")
        self.failed_text.delete("1.0", "end")

        # Check for scenes without prompts or failed
        failed_info = []

        if hasattr(self, 'scenes') and self.scenes:
            for scene in self.scenes:
                scene_id = scene.scene_id
                img_path = Path(__file__).parent / "PROJECTS" / self.project_code / "img" / f"{scene_id}.png"

                if not scene.img_prompt:
                    failed_info.append(f"Scene {scene_id:03d}: MISSING PROMPT")
                elif not img_path.exists():
                    # Check if it was skipped or failed
                    failed_info.append(f"Scene {scene_id:03d}: Not generated yet")

        if failed_info:
            self.failed_text.insert("1.0", "\n".join(failed_info))
        else:
            self.failed_text.insert("1.0", "No failed or skipped scenes!")

        self.failed_text.configure(state="disabled")

    def _update_worker_status(self):
        """Update Chrome 1/2 status from manager."""
        if not self.manager:
            self.chrome1_status_var.set("(No manager)")
            self.chrome2_status_var.set("(No manager)")
            return

        try:
            # Get status from manager
            chrome1_status = "idle"
            chrome2_status = "idle"

            # Check logs for current work
            log_path = Path(__file__).parent / "chrome_log.txt"
            if log_path.exists():
                try:
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()[-50:]  # Last 50 lines

                    for line in reversed(lines):
                        if "[Chrome1]" in line or "[Worker1]" in line:
                            if "Scene" in line or "scene" in line:
                                # Extract scene info
                                chrome1_status = line.strip()[-80:]
                                break
                        if "[Chrome2]" in line or "[Worker2]" in line:
                            if "Scene" in line or "scene" in line:
                                chrome2_status = line.strip()[-80:]
                                break
                except:
                    pass

            self.chrome1_status_var.set(chrome1_status)
            self.chrome2_status_var.set(chrome2_status)

        except Exception as e:
            self.chrome1_status_var.set(f"Error: {str(e)[:30]}")
            self.chrome2_status_var.set("")

    def _update_workflow_status(self, status):
        """Update the Excel workflow status display."""
        # SRT Status
        if status.srt_exists:
            self.srt_status_var.set(f"OK ({status.srt_scene_count})")
        else:
            self.srt_status_var.set("MISSING")

        # Characters Status
        if status.characters_count == 0:
            self.chars_status_var.set("No characters")
        else:
            refs = status.characters_with_ref
            total = status.characters_count
            if refs == total:
                self.chars_status_var.set(f"OK ({total} chars, all refs)")
            elif refs > 0:
                missing = len(status.characters_missing_ref)
                self.chars_status_var.set(f"{refs}/{total} refs (miss: {missing})")
            else:
                self.chars_status_var.set(f"{total} chars, NO refs!")

        # NV Images count
        self.nv_count_var.set(str(status.nv_images_count))

        # Prompts Status
        prompts = status.img_prompts_count
        total = status.total_scenes
        fallback = status.fallback_prompts
        if prompts == 0:
            self.prompts_status_var.set("No prompts")
        elif prompts == total and fallback == 0:
            self.prompts_status_var.set(f"OK ({prompts}/{total})")
        elif fallback > 0:
            self.prompts_status_var.set(f"{prompts}/{total} ({fallback} FALLBACK)")
        else:
            missing = len(status.missing_img_prompts)
            self.prompts_status_var.set(f"{prompts}/{total} (miss: {missing})")

        # Excel Overall Status
        excel_status_map = {
            "none": "NO FILE",
            "empty": "EMPTY",
            "mismatch": "MISMATCH!",
            "fallback": "HAS FALLBACK",
            "partial": "PARTIAL",
            "complete": "COMPLETE"
        }
        self.excel_status_var.set(excel_status_map.get(status.excel_status, status.excel_status))

        # Current Step
        step_map = {
            "excel": "EXCEL",
            "image": "IMAGE",
            "video": "VIDEO",
            "done": "DONE"
        }
        self.current_step_var.set(step_map.get(status.current_step, status.current_step))

        # Video Mode
        video_mode = status.video_mode.upper() if status.video_mode else "FULL"
        self.video_mode_var.set(video_mode)

        # Segment 1 info
        seg1_count = len(status.segment1_scenes)
        if seg1_count > 0:
            self.seg1_scenes_var.set(f"1-{status.segment1_end_srt} ({seg1_count} scenes)")
        else:
            self.seg1_scenes_var.set("N/A")

        # Videos Needed based on mode
        videos_need = len(status.videos_needed)
        videos_done = status.videos_done
        if status.video_mode == "basic" or "basic" in (status.video_mode or "").lower():
            # BASIC mode: only Segment 1 videos
            total_videos = seg1_count
            self.videos_need_var.set(f"{videos_need}/{total_videos} (Seg.1)")
        else:
            # FULL mode: all videos
            total_videos = status.total_scenes
            self.videos_need_var.set(f"{videos_need}/{total_videos}")


class WorkerCard(ttk.LabelFrame):
    """Card hiển thị thông tin một worker."""

    def __init__(self, parent, worker_id: str, worker_type: str):
        super().__init__(parent, text=worker_id.upper(), padding=10)
        self.worker_id = worker_id
        self.worker_type = worker_type

        # Status
        self.status_var = tk.StringVar(value="stopped")
        self.status_label = ttk.Label(self, textvariable=self.status_var, font=("Arial", 10, "bold"))
        self.status_label.grid(row=0, column=0, columnspan=2, sticky="w")

        # Progress
        self.progress_var = tk.IntVar(value=0)
        self.progress_bar = ttk.Progressbar(self, variable=self.progress_var, maximum=100, length=150)
        self.progress_bar.grid(row=1, column=0, columnspan=2, pady=5, sticky="ew")

        # Current task
        self.task_var = tk.StringVar(value="-")
        ttk.Label(self, text="Task:").grid(row=2, column=0, sticky="w")
        ttk.Label(self, textvariable=self.task_var, width=20).grid(row=2, column=1, sticky="w")

        # Stats
        self.done_var = tk.StringVar(value="0")
        self.fail_var = tk.StringVar(value="0")
        ttk.Label(self, text="Done:").grid(row=3, column=0, sticky="w")
        ttk.Label(self, textvariable=self.done_var).grid(row=3, column=1, sticky="w")
        ttk.Label(self, text="Failed:").grid(row=4, column=0, sticky="w")
        ttk.Label(self, textvariable=self.fail_var).grid(row=4, column=1, sticky="w")

        # Error
        self.error_var = tk.StringVar(value="")
        self.error_label = ttk.Label(self, textvariable=self.error_var, foreground="red", wraplength=150)
        self.error_label.grid(row=5, column=0, columnspan=2, sticky="w")

        # Buttons
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=6, column=0, columnspan=2, pady=5)

        self.restart_btn = ttk.Button(btn_frame, text="Restart", width=8)
        self.restart_btn.pack(side="left", padx=2)

        self.stop_btn = ttk.Button(btn_frame, text="Stop", width=8)
        self.stop_btn.pack(side="left", padx=2)

    def update(self, status: str, progress: int, task: str, done: int, failed: int, error: str = ""):
        self.status_var.set(status)
        self.progress_var.set(progress)
        self.task_var.set(task[:20] if task else "-")
        self.done_var.set(str(done))
        self.fail_var.set(str(failed))
        self.error_var.set(error[:30] if error else "")

        # Color based on status
        colors = {
            "stopped": "gray",
            "idle": "blue",
            "working": "green",
            "error": "red"
        }
        self.status_label.configure(foreground=colors.get(status, "black"))


class ProjectCard(ttk.Frame):
    """Card hiển thị thông tin một project."""

    def __init__(self, parent, project_code: str, on_double_click=None):
        super().__init__(parent)
        self.project_code = project_code
        self.on_double_click = on_double_click

        # Project name (clickable)
        self.name_label = ttk.Label(self, text=project_code, font=("Arial", 9, "bold"),
                                     width=15, cursor="hand2")
        self.name_label.pack(side="left")
        self.name_label.bind("<Double-Button-1>", self._on_click)

        # Excel status
        self.excel_var = tk.StringVar(value="-")
        ttk.Label(self, textvariable=self.excel_var, width=10).pack(side="left")

        # Image progress with progress bar
        img_frame = ttk.Frame(self)
        img_frame.pack(side="left", padx=2)
        self.img_var = tk.StringVar(value="0/0")
        ttk.Label(img_frame, textvariable=self.img_var, width=8).pack(side="left")
        self.img_progress = ttk.Progressbar(img_frame, length=50, maximum=100, mode="determinate")
        self.img_progress.pack(side="left")

        # Video progress with progress bar
        vid_frame = ttk.Frame(self)
        vid_frame.pack(side="left", padx=2)
        self.vid_var = tk.StringVar(value="0/0")
        ttk.Label(vid_frame, textvariable=self.vid_var, width=8).pack(side="left")
        self.vid_progress = ttk.Progressbar(vid_frame, length=50, maximum=100, mode="determinate")
        self.vid_progress.pack(side="left")

        # Status
        self.status_var = tk.StringVar(value="-")
        ttk.Label(self, textvariable=self.status_var, width=10).pack(side="left")

        # Detail button
        ttk.Button(self, text="[LIST]", width=3, command=self._on_click).pack(side="right", padx=2)

        # Make entire row clickable
        self.bind("<Double-Button-1>", self._on_click)

    def _on_click(self, event=None):
        if self.on_double_click:
            self.on_double_click(self.project_code)

    def update(self, excel_status: str, img_done: int, img_total: int,
               vid_done: int, vid_total: int, current_step: str):
        self.excel_var.set(excel_status)
        self.img_var.set(f"{img_done}/{img_total}")
        self.vid_var.set(f"{vid_done}/{vid_total}")
        self.status_var.set(current_step)

        # Update progress bars
        if img_total > 0:
            self.img_progress["value"] = int(img_done / img_total * 100)
        if vid_total > 0:
            self.vid_progress["value"] = int(vid_done / vid_total * 100)


class CurrentActivityPanel(ttk.LabelFrame):
    """Panel hiển thị hoạt động hiện tại - real-time với đầy đủ thông tin."""

    def __init__(self, parent):
        super().__init__(parent, text="[LIVE] Real-time Activity", padding=10)
        self.activity_labels = {}
        self._build_ui()


class ChromeLogWindow(tk.Toplevel):
    """Floating window hiển thị Chrome logs - đặt bên cạnh Chrome windows."""

    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.title("Chrome Logs")

        # Get screen size
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        # Position: below Chrome windows on the right side
        # Chrome windows: 700x550 at x = screen_width - 710
        log_width = 700
        log_height = 300
        x = screen_width - log_width - 10
        # y = below 2 Chrome windows (50 + 550 + 10 + 550 + 10)
        # If that's too low, we'll cap it in the if statement below
        y = 50 + 550 + 10 + 550 + 10  # Below 2 Chrome windows

        # If too low, position it differently
        if y + log_height > screen_height:
            y = screen_height - log_height - 50

        self.geometry(f"{log_width}x{log_height}+{x}+{y}")
        self.resizable(True, True)

        # Keep on top
        self.attributes('-topmost', True)

        self._build_ui()
        self._last_positions = {}
        self._update_logs()

    def _build_ui(self):
        # Notebook for Chrome 1 and Chrome 2 logs
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=5, pady=5)

        # Chrome 1 tab
        self.chrome1_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.chrome1_frame, text="Chrome 1")
        self.chrome1_text = scrolledtext.ScrolledText(
            self.chrome1_frame, height=15, font=("Consolas", 8),
            wrap="word", state="disabled"
        )
        self.chrome1_text.pack(fill="both", expand=True)

        # Chrome 2 tab
        self.chrome2_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.chrome2_frame, text="Chrome 2")
        self.chrome2_text = scrolledtext.ScrolledText(
            self.chrome2_frame, height=15, font=("Consolas", 8),
            wrap="word", state="disabled"
        )
        self.chrome2_text.pack(fill="both", expand=True)

        # Configure tags
        for text_widget in [self.chrome1_text, self.chrome2_text]:
            text_widget.tag_configure("error", foreground="red")
            text_widget.tag_configure("warn", foreground="orange")
            text_widget.tag_configure("ok", foreground="green")

    def _update_logs(self):
        """Update logs from worker log files."""
        if not self.manager:
            self.after(1000, self._update_logs)
            return

        # Update Chrome 1 logs
        self._update_worker_log("chrome_1", self.chrome1_text)
        # Update Chrome 2 logs
        self._update_worker_log("chrome_2", self.chrome2_text)

        # Schedule next update
        self.after(500, self._update_logs)

    def _update_worker_log(self, worker_id: str, text_widget):
        """Update a specific worker's log display."""
        logs = self.manager.get_worker_log_file(worker_id, lines=100)
        if not logs:
            return

        last_pos = self._last_positions.get(worker_id, 0)
        if len(logs) > last_pos:
            new_lines = logs[last_pos:]
            text_widget.configure(state="normal")
            for line in new_lines:
                # Determine tag based on content
                tag = None
                line_lower = line.lower()
                if "error" in line_lower or "fail" in line_lower:
                    tag = "error"
                elif "warn" in line_lower:
                    tag = "warn"
                elif "[ok]" in line_lower or "success" in line_lower:
                    tag = "ok"

                if tag:
                    text_widget.insert("end", line, tag)
                else:
                    text_widget.insert("end", line)
            text_widget.see("end")
            text_widget.configure(state="disabled")
            self._last_positions[worker_id] = len(logs)


# Attach methods to CurrentActivityPanel
def _cap_build_ui(self):
    header = ttk.Frame(self)
    header.pack(fill="x")
    # Note: For Excel worker, "Img/Pmt" shows Prompts, "Vid/Chr" shows Characters with refs
    cols = [("Worker", 10), ("Status", 8), ("Project", 12), ("Pending", 7),
            ("Img/Pmt", 10), ("Vid/Chr", 10), ("Current Task", 28), ("Last Result", 12)]
    for col_name, width in cols:
        ttk.Label(header, text=col_name, width=width, font=("Arial", 9, "bold")).pack(side="left", padx=1)
    ttk.Separator(self, orient="horizontal").pack(fill="x", pady=5)
    self.container = ttk.Frame(self)
    self.container.pack(fill="both", expand=True)


def _cap_update_worker(self, worker_id, status, project, pending_tasks,
                       images_done, images_total, videos_done, videos_total,
                       current_task, last_result, progress):
    if worker_id not in self.activity_labels:
        row = ttk.Frame(self.container)
        row.pack(fill="x", pady=2)
        worker_frame = ttk.Frame(row)
        worker_frame.pack(side="left")
        indicator = tk.Canvas(worker_frame, width=10, height=10, highlightthickness=0)
        indicator.pack(side="left", padx=(0, 3))
        ttk.Label(worker_frame, text=worker_id, width=8, font=("Consolas", 9)).pack(side="left")
        status_label = ttk.Label(row, text="-", width=8, font=("Consolas", 9))
        status_label.pack(side="left", padx=1)
        project_label = ttk.Label(row, text="-", width=12, font=("Consolas", 9, "bold"))
        project_label.pack(side="left", padx=1)
        pending_label = ttk.Label(row, text="-", width=7, font=("Consolas", 9))
        pending_label.pack(side="left", padx=1)
        img_frame = ttk.Frame(row)
        img_frame.pack(side="left", padx=1)
        img_label = ttk.Label(img_frame, text="0/0", width=6, font=("Consolas", 9))
        img_label.pack(side="left")
        img_bar = ttk.Progressbar(img_frame, length=40, maximum=100, mode="determinate")
        img_bar.pack(side="left")
        vid_frame = ttk.Frame(row)
        vid_frame.pack(side="left", padx=1)
        vid_label = ttk.Label(vid_frame, text="0/0", width=6, font=("Consolas", 9))
        vid_label.pack(side="left")
        vid_bar = ttk.Progressbar(vid_frame, length=40, maximum=100, mode="determinate")
        vid_bar.pack(side="left")
        task_label = ttk.Label(row, text="-", width=28, font=("Consolas", 8), anchor="w")
        task_label.pack(side="left", padx=1)
        result_label = ttk.Label(row, text="-", width=12, font=("Consolas", 9))
        result_label.pack(side="left", padx=1)
        self.activity_labels[worker_id] = {
            "indicator": indicator, "status": status_label, "project": project_label,
            "pending": pending_label, "img_label": img_label, "img_bar": img_bar,
            "vid_label": vid_label, "vid_bar": vid_bar, "task": task_label, "result": result_label
        }
    labels = self.activity_labels[worker_id]
    labels["indicator"].delete("all")
    colors = {"working": "#00ff00", "idle": "#ffff00", "error": "#ff0000", "stopped": "#888888"}
    labels["indicator"].create_oval(2, 2, 8, 8, fill=colors.get(status, "#888888"), outline=colors.get(status, "#888888"))
    labels["status"].configure(text=status)
    labels["project"].configure(text=project or "-")
    labels["pending"].configure(text=f"{pending_tasks}" if pending_tasks > 0 else "-")
    labels["img_label"].configure(text=f"{images_done}/{images_total}")
    labels["img_bar"]["value"] = int(images_done / images_total * 100) if images_total > 0 else 0
    labels["vid_label"].configure(text=f"{videos_done}/{videos_total}")
    labels["vid_bar"]["value"] = int(videos_done / videos_total * 100) if videos_total > 0 else 0
    labels["task"].configure(text=(current_task[:26] + "..") if current_task and len(current_task) > 28 else (current_task or "-"))
    labels["result"].configure(text=last_result or "-")
    if last_result:
        if "OK" in last_result or "success" in last_result.lower():
            labels["result"].configure(foreground="green")
        elif "FAIL" in last_result or "error" in last_result.lower():
            labels["result"].configure(foreground="red")
        else:
            labels["result"].configure(foreground="black")


CurrentActivityPanel._build_ui = _cap_build_ui
CurrentActivityPanel.update_worker = _cap_update_worker


class VMManagerGUI:
    """Main GUI Application."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("VM Manager - AI Agent Dashboard")

        # Get screen size and set window size (leave space for Chrome on right)
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()

        # GUI takes left 60% of screen, Chrome windows on right 40%
        gui_width = min(int(screen_width * 0.6), 1200)
        gui_height = min(screen_height - 100, 900)

        self.root.geometry(f"{gui_width}x{gui_height}+0+0")  # Position at top-left
        self.root.minsize(1000, 700)

        # Manager
        self.manager: Optional[VMManager] = None
        self.running = False

        # Get current branch
        self.current_branch = self._get_current_branch()

        # UI Components
        self.worker_cards: Dict[str, WorkerCard] = {}
        self.project_cards: Dict[str, ProjectCard] = {}

        # Build UI
        self._build_ui()

        # Update title with branch info
        self.root.title(f"VM Manager - [{self.current_branch}]")

        # Start update loop - faster for real-time feel
        self._update_loop()

        # Run UPDATE.py asynchronously after GUI is shown
        self.root.after(100, self._run_update_async)

    def _run_update_async(self):
        """Run UPDATE.py in background - disable buttons until done."""
        # Disable buttons during update
        self._set_buttons_state("disabled")
        self._log("Updating... Please wait...")
        self.status_var.set("UPDATING - Please wait...")

        def run():
            update_script = TOOL_DIR / "UPDATE.py"
            success = True
            if update_script.exists():
                try:
                    import subprocess
                    result = subprocess.run(
                        [sys.executable, str(update_script)],
                        capture_output=True, text=True, cwd=str(TOOL_DIR), timeout=60
                    )
                    if result.returncode != 0:
                        success = False
                        err = result.stderr[:100] if result.stderr else 'unknown'
                        self.root.after(0, lambda: self._log(f"Update warning: {err}"))
                except Exception as e:
                    success = False
                    self.root.after(0, lambda: self._log(f"Update error: {e}"))

            # Re-enable buttons and notify completion
            def on_complete():
                self._set_buttons_state("normal")
                if success:
                    self._log("Update completed - Ready!")
                    self.status_var.set("Ready")
                else:
                    self._log("Update had issues - Ready anyway")
                    self.status_var.set("Ready (update had issues)")

            self.root.after(0, on_complete)

        threading.Thread(target=run, daemon=True).start()

    def _set_buttons_state(self, state: str):
        """Enable/disable all action buttons."""
        buttons = [
            self.start_btn, self.stop_btn, self.restart_btn,
            self.ipv6_btn, self.scan_btn, self.hide_chrome_btn,
            self.show_chrome_btn, self.settings_btn
        ]
        for btn in buttons:
            try:
                btn.configure(state=state)
            except:
                pass

    def _get_current_branch(self) -> str:
        """Get current git branch name."""
        try:
            import subprocess
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, cwd=TOOL_DIR, timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass
        return "unknown"


    def _build_ui(self):
        """Xây dựng giao diện."""
        # Main container
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill="both", expand=True)

        # Top: Settings & Controls
        self._build_settings_frame(main_frame)

        # Current Activity Panel - REAL-TIME view
        self.activity_panel = CurrentActivityPanel(main_frame)
        self.activity_panel.pack(fill="x", pady=(0, 10))

        # Middle: Workers & Projects
        middle_frame = ttk.Frame(main_frame)
        middle_frame.pack(fill="both", expand=True, pady=10)

        # Left: Workers
        self._build_workers_frame(middle_frame)

        # Right: Projects & Logs
        right_frame = ttk.Frame(middle_frame)
        right_frame.pack(side="right", fill="both", expand=True, padx=(10, 0))

        self._build_projects_frame(right_frame)
        self._build_logs_frame(right_frame)

        # Bottom: Status bar
        self._build_status_bar(main_frame)

    def _build_settings_frame(self, parent):
        """Frame settings và controls."""
        frame = ttk.LabelFrame(parent, text="Settings & Controls", padding=10)
        frame.pack(fill="x", pady=(0, 10))

        # Row 1: Mode selections
        row1 = ttk.Frame(frame)
        row1.pack(fill="x", pady=5)

        # Excel Mode - default basic
        ttk.Label(row1, text="Excel Mode:").pack(side="left", padx=(0, 5))
        self.excel_mode_var = tk.StringVar(value="basic")
        excel_combo = ttk.Combobox(row1, textvariable=self.excel_mode_var,
                                    values=["basic", "full"], width=10, state="readonly")
        excel_combo.pack(side="left", padx=(0, 20))
        excel_combo.bind("<<ComboboxSelected>>", self._on_excel_mode_change)

        # Video Mode - default basic
        ttk.Label(row1, text="Video Mode:").pack(side="left", padx=(0, 5))
        self.video_mode_var = tk.StringVar(value="basic (8s)")
        video_combo = ttk.Combobox(row1, textvariable=self.video_mode_var,
                                    values=["basic (8s)", "full"], width=12, state="readonly")
        video_combo.pack(side="left", padx=(0, 20))
        video_combo.bind("<<ComboboxSelected>>", self._on_video_mode_change)

        # Chrome Count
        ttk.Label(row1, text="Chrome Workers:").pack(side="left", padx=(0, 5))
        self.chrome_count_var = tk.StringVar(value="2")
        chrome_spin = ttk.Spinbox(row1, from_=1, to=10, textvariable=self.chrome_count_var,
                                   width=5, command=self._on_chrome_count_change)
        chrome_spin.pack(side="left", padx=(0, 20))

        # IPv6 Status
        self.ipv6_status_var = tk.StringVar(value="IPv6: -")
        ttk.Label(row1, textvariable=self.ipv6_status_var).pack(side="left", padx=(0, 10))

        # Row 2: Action buttons
        row2 = ttk.Frame(frame)
        row2.pack(fill="x", pady=5)

        self.start_btn = ttk.Button(row2, text="[>] Start All", command=self._start_all, width=15)
        self.start_btn.pack(side="left", padx=5)

        self.stop_btn = ttk.Button(row2, text="[X] Stop All", command=self._stop_all, width=15)
        self.stop_btn.pack(side="left", padx=5)

        self.restart_btn = ttk.Button(row2, text="[R] Restart All", command=self._restart_all, width=15)
        self.restart_btn.pack(side="left", padx=5)

        ttk.Separator(row2, orient="vertical").pack(side="left", fill="y", padx=10)

        self.ipv6_btn = ttk.Button(row2, text="[IPv6] Rotate", command=self._rotate_ipv6, width=15)
        self.ipv6_btn.pack(side="left", padx=5)

        self.scan_btn = ttk.Button(row2, text="[Scan] Projects", command=self._scan_projects, width=15)
        self.scan_btn.pack(side="left", padx=5)

        self.update_btn = ttk.Button(row2, text="[Update] Code", command=self._update_code, width=14)
        self.update_btn.pack(side="left", padx=5)

        ttk.Separator(row2, orient="vertical").pack(side="left", fill="y", padx=10)

        # Chrome visibility toggle buttons
        self.hide_chrome_btn = ttk.Button(row2, text="[Hide] Chrome", command=self._hide_chrome, width=14)
        self.hide_chrome_btn.pack(side="left", padx=5)

        self.show_chrome_btn = ttk.Button(row2, text="[Show] Chrome", command=self._show_chrome, width=14)
        self.show_chrome_btn.pack(side="left", padx=5)

        self.restart_chrome_btn = ttk.Button(row2, text="[Fix] Chrome", command=self._restart_all_chrome, width=12)
        self.restart_chrome_btn.pack(side="left", padx=5)

        ttk.Separator(row2, orient="vertical").pack(side="left", fill="y", padx=10)

        self.settings_btn = ttk.Button(row2, text="[Settings]", command=self._open_settings, width=12)
        self.settings_btn.pack(side="left", padx=5)

    def _build_workers_frame(self, parent):
        """Frame hiển thị workers."""
        frame = ttk.LabelFrame(parent, text="Workers", padding=10)
        frame.pack(side="left", fill="y", padx=(0, 10))

        self.workers_container = ttk.Frame(frame)
        self.workers_container.pack(fill="both", expand=True)

        # Create default worker cards
        self._create_worker_cards(2)

    def _create_worker_cards(self, chrome_count: int):
        """Tạo worker cards."""
        # Clear existing
        for card in self.worker_cards.values():
            card.destroy()
        self.worker_cards.clear()

        # Excel worker
        excel_card = WorkerCard(self.workers_container, "excel", "excel")
        excel_card.pack(fill="x", pady=5)
        excel_card.restart_btn.configure(command=lambda: self._restart_worker("excel"))
        excel_card.stop_btn.configure(command=lambda: self._stop_worker("excel"))
        self.worker_cards["excel"] = excel_card

        # Chrome workers
        for i in range(1, chrome_count + 1):
            wid = f"chrome_{i}"
            card = WorkerCard(self.workers_container, wid, "chrome")
            card.pack(fill="x", pady=5)
            card.restart_btn.configure(command=lambda w=wid: self._restart_worker(w))
            card.stop_btn.configure(command=lambda w=wid: self._stop_worker(w))
            self.worker_cards[wid] = card

    def _build_projects_frame(self, parent):
        """Frame hiển thị projects."""
        frame = ttk.LabelFrame(parent, text="Projects", padding=10)
        frame.pack(fill="both", expand=True, pady=(0, 10))

        # Header
        header = ttk.Frame(frame)
        header.pack(fill="x")
        ttk.Label(header, text="Project", width=15, font=("Arial", 9, "bold")).pack(side="left")
        ttk.Label(header, text="Excel", width=10, font=("Arial", 9, "bold")).pack(side="left")
        ttk.Label(header, text="Images", width=10, font=("Arial", 9, "bold")).pack(side="left")
        ttk.Label(header, text="Videos", width=10, font=("Arial", 9, "bold")).pack(side="left")
        ttk.Label(header, text="Step", width=10, font=("Arial", 9, "bold")).pack(side="left")

        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=5)

        # Scrollable container
        canvas = tk.Canvas(frame, height=200)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        self.projects_container = ttk.Frame(canvas)

        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.create_window((0, 0), window=self.projects_container, anchor="nw")

        self.projects_container.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

    def _build_logs_frame(self, parent):
        """Frame hiển thị logs và errors."""
        self.logs_notebook = ttk.Notebook(parent)
        self.logs_notebook.pack(fill="both", expand=True)

        # System Logs tab
        logs_frame = ttk.Frame(self.logs_notebook, padding=5)
        self.logs_notebook.add(logs_frame, text="System")

        self.logs_text = scrolledtext.ScrolledText(logs_frame, height=10, state="disabled",
                                                    font=("Consolas", 9))
        self.logs_text.pack(fill="both", expand=True)

        # Worker Logs tab - shows combined worker logs
        worker_logs_frame = ttk.Frame(self.logs_notebook, padding=5)
        self.logs_notebook.add(worker_logs_frame, text="Workers")

        # Worker selector
        selector_frame = ttk.Frame(worker_logs_frame)
        selector_frame.pack(fill="x", pady=(0, 5))

        ttk.Label(selector_frame, text="Worker:").pack(side="left", padx=(0, 5))
        self.log_worker_var = tk.StringVar(value="all")
        self.log_worker_combo = ttk.Combobox(selector_frame, textvariable=self.log_worker_var,
                                              values=["all", "excel", "chrome_1", "chrome_2"],
                                              width=15, state="readonly")
        self.log_worker_combo.pack(side="left", padx=(0, 10))
        self.log_worker_combo.bind("<<ComboboxSelected>>", self._on_log_worker_change)

        ttk.Button(selector_frame, text="Refresh", command=self._refresh_worker_logs, width=10).pack(side="left")
        ttk.Button(selector_frame, text="Clear", command=self._clear_worker_logs, width=10).pack(side="left", padx=5)

        # Auto-scroll checkbox
        self.auto_scroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(selector_frame, text="Auto-scroll", variable=self.auto_scroll_var).pack(side="right")

        self.worker_logs_text = scrolledtext.ScrolledText(worker_logs_frame, height=10, state="disabled",
                                                           font=("Consolas", 9))
        self.worker_logs_text.pack(fill="both", expand=True)

        # Configure tags for different workers
        self.worker_logs_text.tag_configure("excel", foreground="#0066cc")
        self.worker_logs_text.tag_configure("chrome_1", foreground="#006600")
        self.worker_logs_text.tag_configure("chrome_2", foreground="#660066")
        self.worker_logs_text.tag_configure("chrome_3", foreground="#cc6600")
        self.worker_logs_text.tag_configure("chrome_4", foreground="#006666")
        self.worker_logs_text.tag_configure("error", foreground="red")

        # Errors tab
        errors_frame = ttk.Frame(self.logs_notebook, padding=5)
        self.logs_notebook.add(errors_frame, text="Errors")

        self.errors_text = scrolledtext.ScrolledText(errors_frame, height=10, state="disabled",
                                                      font=("Consolas", 9), foreground="red")
        self.errors_text.pack(fill="both", expand=True)

        # Tasks tab
        tasks_frame = ttk.Frame(self.logs_notebook, padding=5)
        self.logs_notebook.add(tasks_frame, text="Tasks")

        # Task stats
        stats_frame = ttk.Frame(tasks_frame)
        stats_frame.pack(fill="x", pady=5)

        self.pending_var = tk.StringVar(value="Pending: 0")
        self.running_var = tk.StringVar(value="Running: 0")
        self.completed_var = tk.StringVar(value="Completed: 0")
        self.failed_var = tk.StringVar(value="Failed: 0")

        ttk.Label(stats_frame, textvariable=self.pending_var).pack(side="left", padx=10)
        ttk.Label(stats_frame, textvariable=self.running_var).pack(side="left", padx=10)
        ttk.Label(stats_frame, textvariable=self.completed_var).pack(side="left", padx=10)
        ttk.Label(stats_frame, textvariable=self.failed_var).pack(side="left", padx=10)

        self.tasks_text = scrolledtext.ScrolledText(tasks_frame, height=8, state="disabled",
                                                     font=("Consolas", 9))
        self.tasks_text.pack(fill="both", expand=True)

        # Scenes tab - show all scenes for selected project
        scenes_frame = ttk.Frame(self.logs_notebook, padding=5)
        self.logs_notebook.add(scenes_frame, text="Scenes")

        # Project selector
        scene_selector_frame = ttk.Frame(scenes_frame)
        scene_selector_frame.pack(fill="x", pady=(0, 5))

        ttk.Label(scene_selector_frame, text="Project:").pack(side="left", padx=(0, 5))
        self.scene_project_var = tk.StringVar(value="")
        self.scene_project_combo = ttk.Combobox(scene_selector_frame, textvariable=self.scene_project_var,
                                                  width=20, state="readonly")
        self.scene_project_combo.pack(side="left", padx=(0, 10))
        self.scene_project_combo.bind("<<ComboboxSelected>>", self._on_scene_project_change)

        ttk.Button(scene_selector_frame, text="Refresh", command=self._refresh_scenes, width=10).pack(side="left")

        # Scene summary
        self.scene_summary_var = tk.StringVar(value="Select a project to view scenes")
        ttk.Label(scene_selector_frame, textvariable=self.scene_summary_var).pack(side="right", padx=10)

        # Scenes treeview
        tree_frame = ttk.Frame(scenes_frame)
        tree_frame.pack(fill="both", expand=True)

        columns = ("scene", "subtitle", "prompt", "image", "video", "status")
        self.scenes_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=8)

        # Column headings
        self.scenes_tree.heading("scene", text="#")
        self.scenes_tree.heading("subtitle", text="Subtitle")
        self.scenes_tree.heading("prompt", text="Prompt")
        self.scenes_tree.heading("image", text="Image")
        self.scenes_tree.heading("video", text="Video")
        self.scenes_tree.heading("status", text="Status")

        # Column widths
        self.scenes_tree.column("scene", width=40, anchor="center")
        self.scenes_tree.column("subtitle", width=200)
        self.scenes_tree.column("prompt", width=60, anchor="center")
        self.scenes_tree.column("image", width=60, anchor="center")
        self.scenes_tree.column("video", width=60, anchor="center")
        self.scenes_tree.column("status", width=100)

        # Scrollbars
        y_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.scenes_tree.yview)
        self.scenes_tree.configure(yscrollcommand=y_scroll.set)

        self.scenes_tree.pack(side="left", fill="both", expand=True)
        y_scroll.pack(side="right", fill="y")

        # Configure tags for row colors
        self.scenes_tree.tag_configure("done", background="#90EE90")  # Light green
        self.scenes_tree.tag_configure("working", background="#FFFF99")  # Light yellow
        self.scenes_tree.tag_configure("pending", background="#FFFFFF")  # White
        self.scenes_tree.tag_configure("no_prompt", background="#FFCCCC")  # Light red

        # References tab - show character/location images from nv/ folder
        refs_frame = ttk.Frame(self.logs_notebook, padding=5)
        self.logs_notebook.add(refs_frame, text="References")

        # Project selector for references
        refs_selector_frame = ttk.Frame(refs_frame)
        refs_selector_frame.pack(fill="x", pady=(0, 5))

        ttk.Label(refs_selector_frame, text="Project:").pack(side="left", padx=(0, 5))
        self.refs_project_var = tk.StringVar(value="")
        self.refs_project_combo = ttk.Combobox(refs_selector_frame, textvariable=self.refs_project_var,
                                                width=20, state="readonly")
        self.refs_project_combo.pack(side="left", padx=(0, 10))
        self.refs_project_combo.bind("<<ComboboxSelected>>", self._on_refs_project_change)

        ttk.Button(refs_selector_frame, text="Refresh", command=self._refresh_refs, width=10).pack(side="left")
        ttk.Button(refs_selector_frame, text="Open NV Folder", command=self._open_nv_folder, width=14).pack(side="left", padx=5)
        ttk.Button(refs_selector_frame, text="Open IMG Folder", command=self._open_img_folder, width=14).pack(side="left", padx=5)

        # Reference summary
        self.refs_summary_var = tk.StringVar(value="Select a project to view references")
        ttk.Label(refs_selector_frame, textvariable=self.refs_summary_var).pack(side="right", padx=10)

        # References canvas for thumbnails
        refs_canvas_frame = ttk.Frame(refs_frame)
        refs_canvas_frame.pack(fill="both", expand=True)

        self.refs_canvas = tk.Canvas(refs_canvas_frame, bg="white")
        refs_scrollbar = ttk.Scrollbar(refs_canvas_frame, orient="vertical", command=self.refs_canvas.yview)
        self.refs_inner_frame = ttk.Frame(self.refs_canvas)

        self.refs_canvas.configure(yscrollcommand=refs_scrollbar.set)
        refs_scrollbar.pack(side="right", fill="y")
        self.refs_canvas.pack(side="left", fill="both", expand=True)
        self.refs_canvas.create_window((0, 0), window=self.refs_inner_frame, anchor="nw")

        self.refs_inner_frame.bind("<Configure>",
            lambda e: self.refs_canvas.configure(scrollregion=self.refs_canvas.bbox("all")))

        # Store image references to prevent garbage collection
        self._ref_images = []

        # Track last log positions for incremental updates
        self._last_log_positions = {}

    def _build_status_bar(self, parent):
        """Status bar with branch info."""
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=(10, 0))

        # Branch info on the left
        branch_label = ttk.Label(frame, text=f"Branch: {self.current_branch}",
                                  font=("Consolas", 9), foreground="blue")
        branch_label.pack(side="left", padx=(0, 20))

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(frame, textvariable=self.status_var).pack(side="left")

        self.time_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.time_var).pack(side="right")

    # ================================================================================
    # Event Handlers
    # ================================================================================

    def _on_excel_mode_change(self, event=None):
        mode = self.excel_mode_var.get()
        self._log(f"Excel mode changed to: {mode}")
        # Save immediately (even without manager)
        try:
            settings = SettingsManager()
            settings.excel_mode = mode
            self._log(f"Excel mode saved: {mode}")
            if self.manager:
                self.manager.settings = settings
        except Exception as e:
            self._log(f"Error saving excel_mode: {e}")

    def _on_video_mode_change(self, event=None):
        mode = self.video_mode_var.get()
        self._log(f"Video mode changed to: {mode}")
        # Save immediately (even without manager)
        try:
            settings = SettingsManager()
            settings.video_mode = mode
            self._log(f"Video mode saved: {mode}")
            if self.manager:
                self.manager.settings = settings
        except Exception as e:
            self._log(f"Error saving video_mode: {e}")

    def _on_chrome_count_change(self):
        try:
            count = int(self.chrome_count_var.get())
            if 1 <= count <= 10:
                self._create_worker_cards(count)
                self._log(f"Chrome count changed to: {count}")
                if self.manager:
                    self.manager.num_chrome_workers = count
                    self.manager._init_workers()
        except ValueError:
            pass

    def _start_all(self):
        """Start all workers and auto-position Chrome on right side."""
        if not self.manager:
            chrome_count = int(self.chrome_count_var.get())
            self.manager = VMManager(num_chrome_workers=chrome_count)
            self._create_worker_cards(chrome_count)
            # Update worker combo values
            worker_list = ["all", "excel"] + [f"chrome_{i}" for i in range(1, chrome_count + 1)]
            self.log_worker_combo.configure(values=worker_list)

        # Sync settings from GUI to manager
        self.manager.settings.excel_mode = self.excel_mode_var.get()
        self.manager.settings.video_mode = self.video_mode_var.get()
        self._log(f"Mode: Excel={self.manager.settings.excel_mode}, Video={self.manager.settings.video_mode}")

        self.running = True
        self._log("Starting all workers...")

        def start_thread():
            # Start workers
            self.manager.start_all(gui_mode=False)
            # Start orchestration in background
            threading.Thread(target=self.manager.orchestrate, daemon=True).start()

        threading.Thread(target=start_thread, daemon=True).start()

        # Auto-position Chrome + CMD windows after 10 seconds (give Chrome time to open)
        def auto_position_chrome():
            import time
            time.sleep(10)  # Wait for Chrome to open
            if self.manager:
                self.manager.show_chrome_with_cmd()  # Position Chrome + CMD side by side

        threading.Thread(target=auto_position_chrome, daemon=True).start()

    def _stop_all(self):
        """Stop all workers."""
        if self.manager:
            self.running = False
            self._log("Stopping all workers...")
            threading.Thread(target=self.manager.stop_all, daemon=True).start()

    def _restart_all(self):
        """Restart all workers."""
        if self.manager:
            self._log("Restarting all workers...")
            def restart_thread():
                for wid in self.manager.workers:
                    self.manager.restart_worker(wid)
            threading.Thread(target=restart_thread, daemon=True).start()

    def _restart_worker(self, worker_id: str):
        """Restart a specific worker."""
        if self.manager and worker_id in self.manager.workers:
            self._log(f"Restarting {worker_id}...")
            threading.Thread(target=lambda: self.manager.restart_worker(worker_id), daemon=True).start()

    def _stop_worker(self, worker_id: str):
        """Stop a specific worker."""
        if self.manager and worker_id in self.manager.workers:
            self._log(f"Stopping {worker_id}...")
            threading.Thread(target=lambda: self.manager.stop_worker(worker_id), daemon=True).start()

    def _restart_all_chrome(self):
        """Restart all Chrome workers (fix connection issues)."""
        if self.manager:
            self._log("[Fix] Restarting all Chrome workers...")
            threading.Thread(target=self.manager.restart_all_chrome, daemon=True).start()
        else:
            messagebox.showwarning("Warning", "Manager not started")

    def _rotate_ipv6(self):
        """Rotate IPv6."""
        if self.manager and self.manager.ipv6_manager:
            self._log("Rotating IPv6...")
            threading.Thread(target=self.manager.perform_ipv6_rotation, daemon=True).start()
        else:
            messagebox.showwarning("Warning", "IPv6 Manager not available")

    def _hide_chrome(self):
        """Hide Chrome windows (move off-screen)."""
        if self.manager:
            self._log("Hiding Chrome + CMD windows...")
            self.manager.hide_chrome_windows()
            self.manager.hide_cmd_windows()
            self._log("Chrome + CMD hidden")
        else:
            messagebox.showwarning("Warning", "Manager not started")

    def _show_chrome(self):
        """Show Chrome windows + CMD windows side by side on right."""
        if self.manager:
            self._log("Showing Chrome + CMD windows (right side)...")
            self.manager.show_chrome_with_cmd()
            self._log("Chrome + CMD shown side by side")
        else:
            messagebox.showwarning("Warning", "Manager not started")

    def _scan_projects(self):
        """Scan for projects."""
        if self.manager:
            projects = self.manager.scan_projects()
            self._log(f"Found {len(projects)} projects")
            self._update_projects()

    def _update_code(self):
        """Update code from git and restart."""
        import subprocess

        # Confirm with user
        if self.running:
            if not messagebox.askyesno("Update", "Workers are running. Stop them and update?"):
                return
            self._stop_all()
            time.sleep(2)

        self._log("Updating code from git...")
        self.update_btn.configure(state="disabled")

        def do_update():
            try:
                # Run UPDATE.py
                update_script = TOOL_DIR / "UPDATE.py"
                if update_script.exists():
                    result = subprocess.run(
                        [sys.executable, str(update_script)],
                        cwd=str(TOOL_DIR),
                        capture_output=True,
                        text=True,
                        timeout=120
                    )
                    if result.returncode == 0:
                        self._log("[OK] Update complete! Please restart the application.")
                        messagebox.showinfo("Update", "Update complete!\n\nPlease close and restart vm_manager_gui.py")
                    else:
                        self._log(f"[ERROR] Update failed: {result.stderr[:200]}")
                else:
                    self._log("[ERROR] UPDATE.py not found")
            except subprocess.TimeoutExpired:
                self._log("[ERROR] Update timed out")
            except Exception as e:
                self._log(f"[ERROR] Update error: {e}")
            finally:
                self.update_btn.configure(state="normal")

        threading.Thread(target=do_update, daemon=True).start()

    def _open_settings(self):
        """Open settings dialog."""
        settings_manager = None
        if self.manager:
            settings_manager = self.manager.settings
        else:
            # Create temporary settings manager to load/save config
            try:
                from vm_manager import SettingsManager
                settings_manager = SettingsManager()
            except:
                pass

        dialog = SettingsDialog(self.root, settings_manager)
        self.root.wait_window(dialog)

        if dialog.result:
            self._log("Settings saved")
            # Reload settings if manager exists
            if self.manager:
                self.manager.settings = SettingsManager()
                # Update UI
                self.chrome_count_var.set(str(self.manager.settings.chrome_count))
                self.excel_mode_var.set(self.manager.settings.excel_mode)
                # Load video_mode - convert to display format
                vm = self.manager.settings.video_mode
                if vm == "basic":
                    self.video_mode_var.set("basic (8s)")
                else:
                    self.video_mode_var.set("full")
                self._create_worker_cards(self.manager.settings.chrome_count)

    # ================================================================================
    # Worker Logs Handling
    # ================================================================================

    def _on_log_worker_change(self, event=None):
        """Handle worker selection change in log viewer."""
        self._refresh_worker_logs()

    def _refresh_worker_logs(self):
        """Refresh the worker logs display."""
        if not self.manager:
            return

        selected = self.log_worker_var.get()

        self.worker_logs_text.configure(state="normal")
        self.worker_logs_text.delete("1.0", "end")

        if selected == "all":
            # Show all workers' logs
            all_logs = self.manager.get_all_worker_logs(lines_per_worker=30)
            for worker_id, logs in all_logs.items():
                if logs:
                    self.worker_logs_text.insert("end", f"\n{'='*20} {worker_id.upper()} {'='*20}\n", worker_id)
                    for line in logs[-30:]:  # Last 30 lines per worker
                        tag = "error" if "error" in line.lower() or "fail" in line.lower() else worker_id
                        self.worker_logs_text.insert("end", line, tag)
        else:
            # Show specific worker logs
            logs = self.manager.get_worker_log_file(selected, lines=100)
            for line in logs:
                tag = "error" if "error" in line.lower() or "fail" in line.lower() else selected
                self.worker_logs_text.insert("end", line, tag)

        if self.auto_scroll_var.get():
            self.worker_logs_text.see("end")

        self.worker_logs_text.configure(state="disabled")

    def _clear_worker_logs(self):
        """Clear the worker logs display."""
        self.worker_logs_text.configure(state="normal")
        self.worker_logs_text.delete("1.0", "end")
        self.worker_logs_text.configure(state="disabled")
        self._last_log_positions.clear()

    def _update_worker_logs_incremental(self):
        """Incrementally update worker logs (called in update loop)."""
        if not self.manager or not self.running:
            return

        selected = self.log_worker_var.get()

        # Only update if Workers tab is active
        try:
            current_tab = self.logs_notebook.index(self.logs_notebook.select())
            if current_tab != 1:  # Workers tab is index 1
                return
        except:
            return

        self.worker_logs_text.configure(state="normal")

        if selected == "all":
            # Update all workers
            for worker_id in self.manager.workers:
                logs = self.manager.get_worker_log_file(worker_id, lines=10)
                last_pos = self._last_log_positions.get(worker_id, 0)

                if logs and len(logs) > last_pos:
                    new_lines = logs[last_pos:]
                    for line in new_lines:
                        tag = "error" if "error" in line.lower() or "fail" in line.lower() else worker_id
                        self.worker_logs_text.insert("end", f"[{worker_id}] {line}", tag)
                    self._last_log_positions[worker_id] = len(logs)
        else:
            # Update specific worker
            logs = self.manager.get_worker_log_file(selected, lines=50)
            last_pos = self._last_log_positions.get(selected, 0)

            if logs and len(logs) > last_pos:
                new_lines = logs[last_pos:]
                for line in new_lines:
                    tag = "error" if "error" in line.lower() or "fail" in line.lower() else selected
                    self.worker_logs_text.insert("end", line, tag)
                self._last_log_positions[selected] = len(logs)

        if self.auto_scroll_var.get():
            self.worker_logs_text.see("end")

        self.worker_logs_text.configure(state="disabled")

    # ================================================================================
    # Scenes Tab Handling
    # ================================================================================

    def _on_scene_project_change(self, event=None):
        """Handle project selection change in scenes tab."""
        self._refresh_scenes()

    def _refresh_scenes(self):
        """Refresh the scenes treeview for selected project."""
        project_code = self.scene_project_var.get()
        if not project_code:
            self.scene_summary_var.set("Select a project to view scenes")
            return

        try:
            from modules.excel_manager import PromptWorkbook
            from pathlib import Path

            project_dir = Path(__file__).parent / "PROJECTS" / project_code
            excel_path = project_dir / f"{project_code}_prompts.xlsx"
            img_dir = project_dir / "img"

            if not excel_path.exists():
                self.scene_summary_var.set(f"Excel not found: {project_code}")
                return

            wb = PromptWorkbook(str(excel_path))
            scenes = wb.get_scenes()

            # Clear existing
            for item in self.scenes_tree.get_children():
                self.scenes_tree.delete(item)

            # Track stats
            prompts_done = 0
            images_done = 0
            videos_done = 0

            # Count prompts for odd/even (Chrome 1 = odd, Chrome 2 = even)
            chrome1_prompts = 0  # Odd scenes
            chrome2_prompts = 0  # Even scenes

            # Get current working scene from worker details
            current_scenes = set()
            if self.manager:
                for wid, w in self.manager.workers.items():
                    details = self.manager.get_worker_details(wid) or {}
                    if details.get("current_project") == project_code:
                        current_scene = details.get("current_scene", "")
                        if current_scene:
                            current_scenes.add(str(current_scene))

            for scene in scenes:
                scene_id = scene.scene_id

                # Check actual files in img/ folder instead of Excel path
                img_file = img_dir / f"{scene_id}.png"
                img_file_jpg = img_dir / f"{scene_id}.jpg"
                video_file = img_dir / f"{scene_id}.mp4"

                img_exists = img_file.exists() or img_file_jpg.exists()
                video_exists = video_file.exists()

                # Status checks
                has_prompt = "[v]" if scene.img_prompt else "-"
                has_image = "[v]" if img_exists else "-"
                has_video = "[v]" if video_exists else "-"

                # Count stats
                if scene.img_prompt:
                    prompts_done += 1
                    # Count by worker (odd = Chrome 1, even = Chrome 2)
                    if scene_id % 2 == 1:
                        chrome1_prompts += 1
                    else:
                        chrome2_prompts += 1

                if img_exists:
                    images_done += 1
                if video_exists:
                    videos_done += 1

                # Determine row status/tag
                scene_num_str = str(scene_id)
                if scene_num_str in current_scenes:
                    status = "WORKING"
                    tag = "working"
                elif has_image == "[v]" and has_video == "[v]":
                    status = "Done"
                    tag = "done"
                elif has_image == "[v]":
                    status = "Image OK"
                    tag = "done"
                elif has_prompt == "[v]":
                    status = "Ready"
                    tag = "pending"
                else:
                    status = "No prompt"
                    tag = "no_prompt"

                # Truncate subtitle
                subtitle = (scene.srt_text or "")[:40]
                if len(scene.srt_text or "") > 40:
                    subtitle += "..."

                self.scenes_tree.insert("", "end", values=(
                    scene_id,
                    subtitle,
                    has_prompt,
                    has_image,
                    has_video,
                    status
                ), tags=(tag,))

            # Update summary with worker split info
            total = len(scenes)
            self.scene_summary_var.set(
                f"Total: {total} | Prompts: {prompts_done} | Images: {images_done} | Videos: {videos_done} | "
                f"C1(odd): {chrome1_prompts} | C2(even): {chrome2_prompts}"
            )

        except Exception as e:
            self.scene_summary_var.set(f"Error: {str(e)[:50]}")

    def _update_scene_project_list(self):
        """Update the project list in scenes combo."""
        if not self.manager:
            return

        try:
            projects = list(self.manager.quality_checker.project_cache.keys())
            if projects:
                current = self.scene_project_var.get()
                self.scene_project_combo["values"] = projects
                if current not in projects and projects:
                    self.scene_project_var.set(projects[0])
        except:
            pass

    def _update_scenes_if_active(self):
        """Auto-refresh scenes tab if it's the active tab."""
        try:
            # Check if Scenes tab is active (index 4)
            current_tab = self.logs_notebook.index(self.logs_notebook.select())
            if current_tab == 4:  # Scenes tab
                project_code = self.scene_project_var.get()
                if project_code:
                    self._refresh_scenes()
        except:
            pass

    # ================================================================================
    # References Tab Handling
    # ================================================================================

    def _on_refs_project_change(self, event=None):
        """Handle project selection change in references tab."""
        self._refresh_refs()

    def _refresh_refs(self):
        """Refresh the references gallery for selected project."""
        project_code = self.refs_project_var.get()
        if not project_code:
            self.refs_summary_var.set("Select a project to view references")
            return

        try:
            from PIL import Image, ImageTk
        except ImportError:
            self.refs_summary_var.set("PIL not installed - cannot show thumbnails")
            return

        project_dir = TOOL_DIR / "PROJECTS" / project_code
        nv_dir = project_dir / "nv"
        img_dir = project_dir / "img"

        # Clear existing thumbnails
        for widget in self.refs_inner_frame.winfo_children():
            widget.destroy()
        self._ref_images.clear()

        # Get reference images from nv/ folder
        ref_files = []
        if nv_dir.exists():
            ref_files = list(nv_dir.glob("*.png")) + list(nv_dir.glob("*.jpg"))

        # Get generated images from img/ folder
        gen_files = []
        if img_dir.exists():
            gen_files = list(img_dir.glob("*.png")) + list(img_dir.glob("*.jpg"))
            gen_files = [f for f in gen_files if not f.stem.endswith('_video')]  # Exclude video frames

        self.refs_summary_var.set(f"References: {len(ref_files)} | Generated: {len(gen_files)}")

        # Create sections
        row = 0

        # NV/References section
        if ref_files:
            ttk.Label(self.refs_inner_frame, text="Reference Images (nv/)",
                      font=("Arial", 10, "bold")).grid(row=row, column=0, columnspan=6, sticky="w", pady=(5, 2))
            row += 1

            col = 0
            for img_path in sorted(ref_files):
                try:
                    img = Image.open(img_path)
                    img.thumbnail((100, 100))
                    photo = ImageTk.PhotoImage(img)
                    self._ref_images.append(photo)

                    frame = ttk.Frame(self.refs_inner_frame)
                    frame.grid(row=row, column=col, padx=5, pady=5)

                    label = ttk.Label(frame, image=photo)
                    label.pack()
                    ttk.Label(frame, text=img_path.stem, font=("Arial", 8)).pack()

                    col += 1
                    if col >= 6:
                        col = 0
                        row += 1
                except Exception:
                    pass
            row += 1

        # Generated Images section
        if gen_files:
            ttk.Label(self.refs_inner_frame, text="Generated Images (img/)",
                      font=("Arial", 10, "bold")).grid(row=row, column=0, columnspan=6, sticky="w", pady=(10, 2))
            row += 1

            col = 0
            for img_path in sorted(gen_files, key=lambda x: int(x.stem) if x.stem.isdigit() else 999):
                try:
                    img = Image.open(img_path)
                    img.thumbnail((100, 100))
                    photo = ImageTk.PhotoImage(img)
                    self._ref_images.append(photo)

                    frame = ttk.Frame(self.refs_inner_frame)
                    frame.grid(row=row, column=col, padx=5, pady=5)

                    label = ttk.Label(frame, image=photo)
                    label.pack()
                    ttk.Label(frame, text=f"Scene {img_path.stem}", font=("Arial", 8)).pack()

                    col += 1
                    if col >= 6:
                        col = 0
                        row += 1
                except Exception:
                    pass

        if not ref_files and not gen_files:
            ttk.Label(self.refs_inner_frame, text="No images found",
                      font=("Arial", 10)).grid(row=0, column=0, pady=20)

    def _open_nv_folder(self):
        """Open the nv/ folder in file explorer."""
        import subprocess
        project_code = self.refs_project_var.get()
        if not project_code:
            messagebox.showwarning("Warning", "Select a project first")
            return

        nv_dir = TOOL_DIR / "PROJECTS" / project_code / "nv"
        if not nv_dir.exists():
            nv_dir.mkdir(parents=True, exist_ok=True)

        if sys.platform == "win32":
            subprocess.run(["explorer", str(nv_dir)])
        else:
            subprocess.run(["xdg-open", str(nv_dir)])

    def _open_img_folder(self):
        """Open the img/ folder in file explorer."""
        import subprocess
        project_code = self.refs_project_var.get()
        if not project_code:
            messagebox.showwarning("Warning", "Select a project first")
            return

        img_dir = TOOL_DIR / "PROJECTS" / project_code / "img"
        if not img_dir.exists():
            img_dir.mkdir(parents=True, exist_ok=True)

        if sys.platform == "win32":
            subprocess.run(["explorer", str(img_dir)])
        else:
            subprocess.run(["xdg-open", str(img_dir)])

    def _update_refs_project_list(self):
        """Update the project list in references combo."""
        if not self.manager:
            return

        try:
            projects = list(self.manager.quality_checker.project_cache.keys())
            if projects:
                current = self.refs_project_var.get()
                self.refs_project_combo["values"] = projects
                if current not in projects and projects:
                    self.refs_project_var.set(projects[0])
        except:
            pass

    # ================================================================================
    # Update Loop
    # ================================================================================

    def _update_loop(self):
        """Main update loop."""
        self._update_time()
        self._update_activity_panel()  # Real-time activity
        self._update_workers()
        self._update_projects()
        self._update_tasks()
        self._update_ipv6_status()
        self._update_worker_logs_incremental()
        self._update_scene_project_list()  # Update scenes project combo
        self._update_refs_project_list()  # Update references project combo
        self._update_scenes_if_active()  # Auto-refresh scenes tab

        # Auto-recovery check every 10 seconds (20 x 500ms)
        if not hasattr(self, '_recovery_counter'):
            self._recovery_counter = 0
        self._recovery_counter += 1
        if self._recovery_counter >= 20 and self.running and self.manager:
            self._recovery_counter = 0
            try:
                if self.manager.check_and_auto_recover():
                    self._log("[AUTO-RECOVERY] Chrome workers restarted due to connection errors")
            except Exception as e:
                pass  # Ignore recovery errors

        # Schedule next update - 500ms for real-time feel
        self.root.after(500, self._update_loop)

    def _update_activity_panel(self):
        """Update the real-time activity panel with full project info."""
        if not self.manager:
            return

        for wid, w in self.manager.workers.items():
            details = self.manager.get_worker_details(wid) or {}
            project_code = details.get("current_project", "")

            # Default values
            pending_tasks = 0
            images_done = 0
            images_total = 0
            videos_done = 0
            videos_total = 0
            current_task = ""
            last_result = ""

            # Get pending task count for this worker
            try:
                for task in self.manager.tasks.values():
                    if task.assigned_to == wid and task.status.value in ("pending", "running"):
                        # Count scenes in this task
                        if task.scenes:
                            pending_tasks += len(task.scenes)
                        else:
                            pending_tasks += 1
            except:
                pass

            if project_code:
                try:
                    # Get project status from quality checker
                    status = self.manager.quality_checker.get_project_status(project_code)

                    # Calculate correct counts based on worker type
                    # Chrome 1 = odd scenes (1,3,5...), Chrome 2 = even scenes (2,4,6...)
                    if wid == "chrome_1":
                        # Count only odd scenes
                        worker_total = (status.total_scenes + 1) // 2  # Odd count
                        worker_images = len([s for s in status.images_missing if s % 2 == 0])  # Missing even = done odd
                        images_total = worker_total
                        images_done = worker_total - len([s for s in status.images_missing if s % 2 == 1])
                        videos_total = worker_total
                        videos_done = worker_total - len([s for s in status.videos_missing if s % 2 == 1])
                    elif wid == "chrome_2":
                        # Count only even scenes
                        worker_total = status.total_scenes // 2  # Even count
                        images_total = worker_total
                        images_done = worker_total - len([s for s in status.images_missing if s % 2 == 0])
                        videos_total = worker_total
                        videos_done = worker_total - len([s for s in status.videos_missing if s % 2 == 0])
                    elif wid == "excel":
                        # Excel worker - show prompts done / total (use Images column for Prompts)
                        images_done = status.img_prompts_count
                        images_total = status.total_scenes
                        # Use Videos column for Characters status
                        videos_done = status.characters_with_ref
                        videos_total = status.characters_count
                        # Show detailed Excel-specific status
                        if status.excel_status == "complete":
                            current_task = "READY - All prompts OK"
                        elif status.excel_status == "fallback":
                            current_task = f"FALLBACK: {status.fallback_prompts} need fix"
                        elif status.excel_status == "partial":
                            missing = len(status.missing_img_prompts)
                            current_task = f"PARTIAL: miss {missing} prompts"
                        elif status.excel_status == "mismatch":
                            current_task = f"MISMATCH: SRT={status.srt_scene_count} Excel={status.excel_scene_count}"
                        elif status.excel_status == "empty":
                            current_task = "EMPTY - No prompts"
                        elif status.excel_status == "none":
                            current_task = "NO FILE - Create Excel"
                        else:
                            current_task = status.excel_status or "Scanning..."
                    else:
                        # Other workers - show total
                        images_done = status.images_done
                        images_total = status.total_scenes
                        videos_done = status.videos_done
                        videos_total = status.total_scenes

                    # Current task from details (override for Chrome)
                    current_scene = details.get("current_scene", 0)
                    if wid.startswith("chrome_") and current_scene > 0:
                        current_task = f"Scene {current_scene}/{status.total_scenes}"
                    elif not current_task:
                        current_task = details.get("current_task", "") or status.current_step
                except:
                    pass

            # Get last result from worker
            if w.completed_tasks > 0 or w.failed_tasks > 0:
                if w.last_error:
                    last_result = "[FAIL]"
                elif w.completed_tasks > 0:
                    last_result = "[OK]"

            self.activity_panel.update_worker(
                worker_id=wid,
                status=w.status.value,
                project=project_code,
                pending_tasks=pending_tasks,
                images_done=images_done,
                images_total=images_total,
                videos_done=videos_done,
                videos_total=videos_total,
                current_task=current_task,
                last_result=last_result,
                progress=details.get("progress", 0)
            )

    def _update_time(self):
        """Update time display."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.time_var.set(now)

    def _update_workers(self):
        """Update worker cards."""
        if not self.manager:
            return

        for wid, card in self.worker_cards.items():
            if wid in self.manager.workers:
                w = self.manager.workers[wid]
                details = self.manager.get_worker_details(wid) or {}

                progress = details.get("progress", 0)
                task = details.get("current_project", "") or w.current_task or ""
                error = details.get("last_error", "") or w.last_error or ""

                card.update(
                    status=w.status.value,
                    progress=progress,
                    task=task,
                    done=w.completed_tasks,
                    failed=w.failed_tasks,
                    error=error
                )

    def _update_projects(self):
        """Update project list."""
        if not self.manager:
            return

        projects = self.manager.scan_projects()

        # Get active projects (being worked on by any worker)
        active_projects = set()
        for wid in self.manager.workers:
            details = self.manager.get_worker_details(wid) or {}
            if details.get("current_project"):
                active_projects.add(details["current_project"])

        # Update or create project cards
        for code in projects[:10]:  # Limit to 10 projects
            if code not in self.project_cards:
                card = ProjectCard(self.projects_container, code,
                                   on_double_click=self._open_project_detail)
                card.pack(fill="x", pady=2)
                self.project_cards[code] = card

            status = self.manager.quality_checker.get_project_status(code)
            self.project_cards[code].update(
                excel_status=status.excel_status,
                img_done=status.images_done,
                img_total=status.total_scenes,
                vid_done=status.videos_done,
                vid_total=status.total_scenes,
                current_step=status.current_step
            )

            # Highlight active projects
            if code in active_projects:
                self.project_cards[code].name_label.configure(foreground="green", font=("Arial", 9, "bold"))
            else:
                self.project_cards[code].name_label.configure(foreground="black", font=("Arial", 9))

    def _open_project_detail(self, project_code: str):
        """Open project detail dialog."""
        if self.manager:
            dialog = ProjectDetailDialog(self.root, project_code, self.manager.quality_checker)
            # Don't wait for dialog - allow non-modal viewing

    def _update_tasks(self):
        """Update task stats."""
        if not self.manager:
            return

        pending = len([t for t in self.manager.tasks.values()
                      if t.status in (TaskStatus.PENDING, TaskStatus.RETRY)])
        running = len([t for t in self.manager.tasks.values()
                      if t.status in (TaskStatus.ASSIGNED, TaskStatus.RUNNING)])
        completed = len([t for t in self.manager.tasks.values()
                        if t.status == TaskStatus.COMPLETED])
        failed = len([t for t in self.manager.tasks.values()
                     if t.status == TaskStatus.FAILED])

        self.pending_var.set(f"Pending: {pending}")
        self.running_var.set(f"Running: {running}")
        self.completed_var.set(f"Completed: {completed}")
        self.failed_var.set(f"Failed: {failed}")

    def _update_ipv6_status(self):
        """Update IPv6 status."""
        if self.manager and self.manager.ipv6_manager:
            status = self.manager.ipv6_manager.get_status()
            if status["enabled"]:
                self.ipv6_status_var.set(f"IPv6: ON (rotations: {status['rotation_count']})")
            else:
                self.ipv6_status_var.set("IPv6: OFF")
        else:
            self.ipv6_status_var.set("IPv6: N/A")

    def _log(self, message: str):
        """Add message to log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")  # Always print to console

        # Also add to GUI log if available
        if not hasattr(self, 'logs_text'):
            return
        self.logs_text.configure(state="normal")
        self.logs_text.insert("end", f"[{timestamp}] {message}\n")
        self.logs_text.see("end")
        self.logs_text.configure(state="disabled")

        self.status_var.set(message)

    def _log_error(self, message: str):
        """Add error to error log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.errors_text.configure(state="normal")
        self.errors_text.insert("end", f"[{timestamp}] {message}\n")
        self.errors_text.see("end")
        self.errors_text.configure(state="disabled")


def main():
    if not VM_MANAGER_AVAILABLE:
        print("Error: vm_manager module not found")
        sys.exit(1)

    root = tk.Tk()

    # Set style
    style = ttk.Style()
    style.theme_use("clam")

    app = VMManagerGUI(root)

    # Handle close - kill all child processes
    def on_closing():
        if app.manager:
            print("[GUI] Stopping all workers...")
            app.manager.stop_all()
            print("[GUI] Killing Chrome processes...")
            app.manager.kill_all_chrome()

        # Also kill any remaining Python processes started by this tool
        import subprocess
        import sys
        if sys.platform == "win32":
            # Kill worker scripts specifically
            try:
                for script in ["_run_chrome1.py", "_run_chrome2.py", "run_excel_api.py"]:
                    subprocess.run(
                        f'wmic process where "commandline like \'%{script}%\'" call terminate',
                        shell=True, capture_output=True, timeout=5
                    )
            except:
                pass

        print("[GUI] Cleanup done, exiting...")
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
