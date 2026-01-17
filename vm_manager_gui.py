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
    from vm_manager import VMManager, WorkerStatus, TaskStatus, TaskType
    VM_MANAGER_AVAILABLE = True
except ImportError:
    VM_MANAGER_AVAILABLE = False

TOOL_DIR = Path(__file__).parent


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

    def __init__(self, parent, project_code: str):
        super().__init__(parent)
        self.project_code = project_code

        # Project name
        ttk.Label(self, text=project_code, font=("Arial", 9, "bold"), width=15).pack(side="left")

        # Excel status
        self.excel_var = tk.StringVar(value="-")
        ttk.Label(self, textvariable=self.excel_var, width=10).pack(side="left")

        # Image progress
        self.img_var = tk.StringVar(value="0/0")
        ttk.Label(self, textvariable=self.img_var, width=10).pack(side="left")

        # Video progress
        self.vid_var = tk.StringVar(value="0/0")
        ttk.Label(self, textvariable=self.vid_var, width=10).pack(side="left")

        # Status
        self.status_var = tk.StringVar(value="-")
        ttk.Label(self, textvariable=self.status_var, width=10).pack(side="left")

    def update(self, excel_status: str, img_done: int, img_total: int,
               vid_done: int, vid_total: int, current_step: str):
        self.excel_var.set(excel_status)
        self.img_var.set(f"{img_done}/{img_total}")
        self.vid_var.set(f"{vid_done}/{vid_total}")
        self.status_var.set(current_step)


class VMManagerGUI:
    """Main GUI Application."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("VM Manager - AI Agent Dashboard")
        self.root.geometry("1200x800")
        self.root.minsize(1000, 600)

        # Manager
        self.manager: Optional[VMManager] = None
        self.running = False

        # UI Components
        self.worker_cards: Dict[str, WorkerCard] = {}
        self.project_cards: Dict[str, ProjectCard] = {}

        # Build UI
        self._build_ui()

        # Start update loop
        self._update_loop()

    def _build_ui(self):
        """Xây dựng giao diện."""
        # Main container
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill="both", expand=True)

        # Top: Settings & Controls
        self._build_settings_frame(main_frame)

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

        # Excel Mode
        ttk.Label(row1, text="Excel Mode:").pack(side="left", padx=(0, 5))
        self.excel_mode_var = tk.StringVar(value="full")
        excel_combo = ttk.Combobox(row1, textvariable=self.excel_mode_var,
                                    values=["basic", "full"], width=10, state="readonly")
        excel_combo.pack(side="left", padx=(0, 20))
        excel_combo.bind("<<ComboboxSelected>>", self._on_excel_mode_change)

        # Video Mode
        ttk.Label(row1, text="Video Mode:").pack(side="left", padx=(0, 5))
        self.video_mode_var = tk.StringVar(value="full")
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

        self.start_btn = ttk.Button(row2, text="▶ Start All", command=self._start_all, width=15)
        self.start_btn.pack(side="left", padx=5)

        self.stop_btn = ttk.Button(row2, text="⏹ Stop All", command=self._stop_all, width=15)
        self.stop_btn.pack(side="left", padx=5)

        self.restart_btn = ttk.Button(row2, text="🔄 Restart All", command=self._restart_all, width=15)
        self.restart_btn.pack(side="left", padx=5)

        ttk.Separator(row2, orient="vertical").pack(side="left", fill="y", padx=10)

        self.ipv6_btn = ttk.Button(row2, text="🌐 Rotate IPv6", command=self._rotate_ipv6, width=15)
        self.ipv6_btn.pack(side="left", padx=5)

        self.scan_btn = ttk.Button(row2, text="🔍 Scan Projects", command=self._scan_projects, width=15)
        self.scan_btn.pack(side="left", padx=5)

        ttk.Separator(row2, orient="vertical").pack(side="left", fill="y", padx=10)

        self.settings_btn = ttk.Button(row2, text="⚙️ Settings", command=self._open_settings, width=12)
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
        notebook = ttk.Notebook(parent)
        notebook.pack(fill="both", expand=True)

        # Logs tab
        logs_frame = ttk.Frame(notebook, padding=5)
        notebook.add(logs_frame, text="Logs")

        self.logs_text = scrolledtext.ScrolledText(logs_frame, height=10, state="disabled",
                                                    font=("Consolas", 9))
        self.logs_text.pack(fill="both", expand=True)

        # Errors tab
        errors_frame = ttk.Frame(notebook, padding=5)
        notebook.add(errors_frame, text="Errors")

        self.errors_text = scrolledtext.ScrolledText(errors_frame, height=10, state="disabled",
                                                      font=("Consolas", 9), foreground="red")
        self.errors_text.pack(fill="both", expand=True)

        # Tasks tab
        tasks_frame = ttk.Frame(notebook, padding=5)
        notebook.add(tasks_frame, text="Tasks")

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

    def _build_status_bar(self, parent):
        """Status bar."""
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=(10, 0))

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
        if self.manager:
            self.manager.settings.excel_mode = mode

    def _on_video_mode_change(self, event=None):
        mode = self.video_mode_var.get()
        self._log(f"Video mode changed to: {mode}")
        # TODO: Update video mode in settings

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
        """Start all workers."""
        if not self.manager:
            chrome_count = int(self.chrome_count_var.get())
            self.manager = VMManager(num_chrome_workers=chrome_count)
            self._create_worker_cards(chrome_count)

        self.running = True
        self._log("Starting all workers...")

        def start_thread():
            self.manager.start_all()
            # Start orchestration in background
            threading.Thread(target=self.manager.orchestrate, daemon=True).start()

        threading.Thread(target=start_thread, daemon=True).start()

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

    def _rotate_ipv6(self):
        """Rotate IPv6."""
        if self.manager and self.manager.ipv6_manager:
            self._log("Rotating IPv6...")
            threading.Thread(target=self.manager.perform_ipv6_rotation, daemon=True).start()
        else:
            messagebox.showwarning("Warning", "IPv6 Manager not available")

    def _scan_projects(self):
        """Scan for projects."""
        if self.manager:
            projects = self.manager.scan_projects()
            self._log(f"Found {len(projects)} projects")
            self._update_projects()

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
                self._create_worker_cards(self.manager.settings.chrome_count)

    # ================================================================================
    # Update Loop
    # ================================================================================

    def _update_loop(self):
        """Main update loop."""
        self._update_time()
        self._update_workers()
        self._update_projects()
        self._update_tasks()
        self._update_ipv6_status()

        # Schedule next update
        self.root.after(2000, self._update_loop)

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

        # Update or create project cards
        for code in projects[:10]:  # Limit to 10 projects
            if code not in self.project_cards:
                card = ProjectCard(self.projects_container, code)
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

    # Handle close
    def on_closing():
        if app.manager:
            app.manager.stop_all()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
