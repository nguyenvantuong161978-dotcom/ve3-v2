#!/usr/bin/env python3
"""
Simple Dashboard - Giao dien don gian
=====================================
- Bam Start de chay
- Xem tien do tuc thi
- Click vao project de xem chi tiet
- Nut HIEN/AN CMD de toggle CMD windows

Usage:
    pythonw vm_manager_gui.py   (an console)
    python vm_manager_gui.py    (co console)
"""

import sys
import os

# AN CONSOLE WINDOW KHI CHAY GUI
if sys.platform == "win32":
    try:
        import ctypes
        # Ẩn console window
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except:
        pass

    if sys.stdout:
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except:
            pass
    os.environ['PYTHONIOENCODING'] = 'utf-8'

import tkinter as tk
from tkinter import ttk
import threading
import time
from pathlib import Path
from typing import Dict, Optional

# PIL for thumbnails
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except:
    PIL_AVAILABLE = False

TOOL_DIR = Path(__file__).parent

# Import VM Manager
try:
    from vm_manager import VMManager
    VM_AVAILABLE = True
except:
    VM_AVAILABLE = False

# Import Central Logger
try:
    from modules.central_logger import get_recent_logs, tail_log, LOG_FILE, add_callback, remove_callback
    LOGGER_AVAILABLE = True
except:
    LOGGER_AVAILABLE = False

# Import Excel Status for detailed status checking
try:
    from modules.excel_status import check_project_status as check_excel_status, EXCEL_STEPS
    EXCEL_STATUS_AVAILABLE = True
except:
    EXCEL_STATUS_AVAILABLE = False


# ================================================================================
# PROJECT DETAIL - Hiển thị chi tiết từng scene
# ================================================================================

def find_scene_image(img_folder: Path, scene_id: int) -> Path | None:
    """
    Tìm ảnh scene với nhiều format khác nhau:
    - scene_001.png (format chuẩn)
    - 1.png (format đơn giản)
    - scene_1.png (không padding)
    """
    if not img_folder or not img_folder.exists():
        return None

    # Các format có thể có
    candidates = [
        img_folder / f"scene_{scene_id:03d}.png",  # scene_001.png
        img_folder / f"{scene_id}.png",             # 1.png
        img_folder / f"scene_{scene_id}.png",       # scene_1.png
        img_folder / f"scene_{scene_id:03d}.jpg",  # scene_001.jpg
        img_folder / f"{scene_id}.jpg",             # 1.jpg
    ]

    for path in candidates:
        if path.exists():
            return path
    return None


def find_scene_video(vid_folder: Path, scene_id: int) -> Path | None:
    """
    Tìm video scene với nhiều format khác nhau.
    """
    if not vid_folder or not vid_folder.exists():
        return None

    candidates = [
        vid_folder / f"scene_{scene_id:03d}.mp4",
        vid_folder / f"{scene_id}.mp4",
        vid_folder / f"scene_{scene_id}.mp4",
    ]

    for path in candidates:
        if path.exists():
            return path
    return None


class ProjectDetail(tk.Toplevel):
    """Xem chi tiết project - Excel steps + từng scene."""

    def __init__(self, parent, code: str):
        super().__init__(parent)
        self.code = code
        self.title(f"{code} - Chi tiết")
        self.geometry("900x700")
        self.configure(bg='#1a1a2e')
        self._auto_refresh = True

        self._build()
        self._load()
        self._start_auto_refresh()

    def _start_auto_refresh(self):
        """Auto refresh mỗi 3 giây."""
        if self._auto_refresh and self.winfo_exists():
            self._load()
            self.after(3000, self._start_auto_refresh)

    def destroy(self):
        """Stop auto refresh khi đóng."""
        self._auto_refresh = False
        super().destroy()

    def _build(self):
        # Header
        tk.Label(
            self, text=f"PROJECT: {self.code}",
            font=("Arial", 16, "bold"),
            bg='#0f3460', fg='white',
            pady=15
        ).pack(fill="x")

        # Buttons
        btn_row = tk.Frame(self, bg='#1a1a2e')
        btn_row.pack(fill="x", padx=10, pady=5)

        tk.Button(btn_row, text="Mở thư mục", command=self._open_folder,
                  bg='#e94560', fg='white', font=("Arial", 10), relief="flat", padx=15).pack(side="left", padx=5)
        tk.Button(btn_row, text="Làm mới", command=self._load,
                  bg='#0f3460', fg='white', font=("Arial", 10), relief="flat", padx=15).pack(side="left", padx=5)

        # === EXCEL STEPS SECTION ===
        excel_frame = tk.LabelFrame(self, text=" EXCEL - 7 BƯỚC ", bg='#16213e', fg='white',
                                    font=("Arial", 10, "bold"), padx=10, pady=5)
        excel_frame.pack(fill="x", padx=10, pady=5)

        # Steps header
        steps_header = tk.Frame(excel_frame, bg='#0f3460')
        steps_header.pack(fill="x")
        for txt, w in [("Bước", 20), ("Trạng thái", 12), ("Thời gian", 15), ("Ghi chú", 30)]:
            tk.Label(steps_header, text=txt, width=w, bg='#0f3460', fg='white',
                     font=("Arial", 9, "bold")).pack(side="left", padx=2, pady=3)

        # Steps container
        self.steps_frame = tk.Frame(excel_frame, bg='#16213e')
        self.steps_frame.pack(fill="x")

        # === SCENES SECTION ===
        # Summary
        self.summary_var = tk.StringVar(value="Đang tải...")
        tk.Label(self, textvariable=self.summary_var, bg='#1a1a2e', fg='#00d9ff',
                 font=("Consolas", 12, "bold")).pack(pady=5)

        # Scenes list
        list_frame = tk.LabelFrame(self, text=" SCENES - ẢNH & VIDEO ", bg='#16213e', fg='white',
                                   font=("Arial", 10, "bold"), padx=5, pady=5)
        list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Header
        header = tk.Frame(list_frame, bg='#0f3460')
        header.pack(fill="x")
        for txt, w in [("Scene", 6), ("Prompt", 35), ("Ảnh", 6), ("Video", 6), ("Status", 10)]:
            tk.Label(header, text=txt, width=w, bg='#0f3460', fg='white',
                     font=("Arial", 9, "bold")).pack(side="left", padx=2, pady=5)

        # Scrollable
        canvas = tk.Canvas(list_frame, bg='#16213e', highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        self.scenes_frame = tk.Frame(canvas, bg='#16213e')

        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.create_window((0, 0), window=self.scenes_frame, anchor="nw")
        self.scenes_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        # Mouse wheel
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

    def _load(self):
        """Load Excel steps và scenes."""
        # Clear
        for w in self.steps_frame.winfo_children():
            w.destroy()
        for w in self.scenes_frame.winfo_children():
            w.destroy()

        project_dir = self._find_dir()
        if not project_dir:
            self.summary_var.set("Không tìm thấy project!")
            return

        excel_path = project_dir / f"{self.code}_prompts.xlsx"
        if not excel_path.exists():
            self.summary_var.set("Chưa có Excel!")
            self._show_no_excel_steps()
            return

        try:
            from modules.excel_manager import PromptWorkbook
            wb = PromptWorkbook(str(excel_path))
            wb.load_or_create()  # PHẢI gọi load trước khi dùng

            # Load Excel steps status
            self._load_excel_steps(wb)

            scenes = wb.get_scenes()

            if not scenes:
                self.summary_var.set("Excel chưa có scenes!")
                return

            img_folder = project_dir / "img"
            vid_folder = project_dir / "vid"

            img_ok = vid_ok = vid_need = 0

            for i, scene in enumerate(scenes):
                # Handle both Scene objects and dicts
                if hasattr(scene, 'scene_id'):
                    sid = scene.scene_id
                    prompt = (scene.img_prompt or "")[:35]
                    vid_enabled = scene.video_enabled if hasattr(scene, 'video_enabled') else False
                else:
                    sid = scene.get('scene_id', i + 1)
                    prompt = (scene.get('img_prompt') or "")[:35]
                    vid_enabled = scene.get('video_enabled', False)

                img_path = find_scene_image(img_folder, sid)
                vid_path = find_scene_video(vid_folder, sid)
                has_img = img_path is not None
                has_vid = vid_path is not None

                if has_img:
                    img_ok += 1
                if vid_enabled:
                    vid_need += 1
                    if has_vid:
                        vid_ok += 1

                # Row
                bg = '#1a1a2e' if i % 2 == 0 else '#16213e'
                row = tk.Frame(self.scenes_frame, bg=bg)
                row.pack(fill="x", pady=1)

                tk.Label(row, text=str(sid), width=4, bg=bg, fg='white', font=("Consolas", 9)).pack(side="left", padx=2)

                # Thumbnail (40x40)
                thumb_label = tk.Label(row, width=5, height=2, bg='#333', cursor="hand2")
                thumb_label.pack(side="left", padx=2)

                if has_img and img_path and PIL_AVAILABLE:
                    try:
                        img = Image.open(str(img_path))
                        img.thumbnail((40, 40))
                        photo = ImageTk.PhotoImage(img)
                        thumb_label.configure(image=photo, width=40, height=40)
                        thumb_label.image = photo  # Keep reference
                        thumb_label.bind("<Button-1>", lambda e, s=sid: self._open_img(s))
                    except:
                        thumb_label.configure(text="IMG", fg='#00ff88')
                        thumb_label.bind("<Button-1>", lambda e, s=sid: self._open_img(s))
                elif has_img:
                    thumb_label.configure(text="IMG", fg='#00ff88')
                    thumb_label.bind("<Button-1>", lambda e, s=sid: self._open_img(s))
                else:
                    thumb_label.configure(text="--", fg='#666')

                tk.Label(row, text=prompt, width=30, bg=bg, fg='#aaa', font=("Consolas", 8), anchor="w").pack(side="left", padx=2)

                # Video status
                if not vid_enabled:
                    vid_txt, vid_clr = "-", '#444'
                elif has_vid:
                    vid_txt, vid_clr = "VID", '#00ff88'
                else:
                    vid_txt, vid_clr = "...", '#666'

                vid_lbl = tk.Label(row, text=vid_txt, width=5, bg=bg, fg=vid_clr, font=("Arial", 9, "bold"), cursor="hand2")
                vid_lbl.pack(side="left", padx=2)
                if has_vid:
                    vid_lbl.bind("<Button-1>", lambda e, s=sid: self._open_vid(s))

                # Status
                if has_img and (has_vid or not vid_enabled):
                    status_txt, status_clr = "OK", '#00ff88'
                elif has_img:
                    status_txt, status_clr = "...", '#ffaa00'
                else:
                    status_txt, status_clr = "--", '#666'

                tk.Label(row, text=status_txt, width=4, bg=bg, fg=status_clr, font=("Arial", 9)).pack(side="left", padx=2)

            self.summary_var.set(f"Anh: {img_ok}/{len(scenes)} | Video: {vid_ok}/{vid_need}")

        except Exception as e:
            self.summary_var.set(f"Loi: {e}")

    def _load_excel_steps(self, wb):
        """Load và hiển thị trạng thái các bước Excel."""
        step_names = [
            ("step_1", "1. Story Analysis"),
            ("step_2", "2. Story Segments"),
            ("step_3", "3. Characters"),
            ("step_4", "4. Locations"),
            ("step_5", "5. Director Plan"),
            ("step_6", "6. Scene Planning"),
            ("step_7", "7. Scene Prompts")
        ]

        try:
            all_status = wb.get_all_step_status() if hasattr(wb, 'get_all_step_status') else []

            # Convert to dict
            status_dict = {}
            for s in all_status:
                if isinstance(s, dict):
                    status_dict[s.get('step_id', '')] = s

            for i, (step_id, step_name) in enumerate(step_names):
                bg = '#1a1a2e' if i % 2 == 0 else '#16213e'
                row = tk.Frame(self.steps_frame, bg=bg)
                row.pack(fill="x")

                step_status = status_dict.get(step_id, {})
                status = step_status.get('status', 'PENDING')
                last_updated = step_status.get('last_updated', '')
                notes_raw = step_status.get('notes', '') or ''

                # Extract duration from notes (format: "Xs - description")
                duration_txt = "--"
                notes_display = notes_raw[:30]
                if notes_raw and 's - ' in notes_raw:
                    parts = notes_raw.split('s - ', 1)
                    if parts[0].isdigit():
                        secs = int(parts[0])
                        if secs >= 60:
                            duration_txt = f"{secs//60}m{secs%60:02d}s"
                        else:
                            duration_txt = f"{secs}s"
                        notes_display = parts[1][:25] if len(parts) > 1 else ""

                # Status color and icon
                if status == 'COMPLETED':
                    status_txt = "OK"
                    status_clr = '#00ff88'
                elif status == 'IN_PROGRESS':
                    status_txt = "Dang chay"
                    status_clr = '#00d9ff'
                elif status == 'ERROR':
                    status_txt = "Loi"
                    status_clr = '#e94560'
                elif status == 'PARTIAL':
                    status_txt = "Mot phan"
                    status_clr = '#ffaa00'
                else:
                    status_txt = "Cho"
                    status_clr = '#666'

                tk.Label(row, text=step_name, width=20, bg=bg, fg='white',
                         font=("Consolas", 9), anchor="w").pack(side="left", padx=2)
                tk.Label(row, text=status_txt, width=10, bg=bg, fg=status_clr,
                         font=("Arial", 9, "bold")).pack(side="left", padx=2)
                tk.Label(row, text=duration_txt, width=8, bg=bg, fg='#ffcc00',
                         font=("Consolas", 9, "bold")).pack(side="left", padx=2)
                tk.Label(row, text=notes_display, width=28, bg=bg, fg='#888',
                         font=("Consolas", 8), anchor="w").pack(side="left", padx=2)

        except Exception as e:
            self._show_no_excel_steps()

    def _show_no_excel_steps(self):
        """Hiển thị steps khi chưa có Excel."""
        step_names = [
            "1. Story Analysis",
            "2. Story Segments",
            "3. Characters",
            "4. Locations",
            "5. Director Plan",
            "6. Scene Planning",
            "7. Scene Prompts"
        ]

        for i, name in enumerate(step_names):
            bg = '#1a1a2e' if i % 2 == 0 else '#16213e'
            row = tk.Frame(self.steps_frame, bg=bg)
            row.pack(fill="x")

            tk.Label(row, text=name, width=20, bg=bg, fg='#666',
                     font=("Consolas", 9), anchor="w").pack(side="left", padx=2)
            tk.Label(row, text="Cho", width=12, bg=bg, fg='#444',
                     font=("Arial", 9)).pack(side="left", padx=2)
            tk.Label(row, text="--", width=15, bg=bg, fg='#444',
                     font=("Consolas", 9)).pack(side="left", padx=2)
            tk.Label(row, text="", width=30, bg=bg, fg='#444',
                     font=("Consolas", 8)).pack(side="left", padx=2)

    def _find_dir(self):
        local = TOOL_DIR / "PROJECTS" / self.code
        if local.exists():
            return local
        for drive in ["Z:", "Y:", "X:"]:
            master = Path(f"{drive}/AUTO/ve3-tool-simple/PROJECTS/{self.code}")
            if master.exists():
                return master
        return None

    def _open_folder(self):
        d = self._find_dir()
        if d:
            os.startfile(str(d))

    def _open_img(self, sid):
        d = self._find_dir()
        if d:
            p = d / "img" / f"scene_{sid:03d}.png"
            if p.exists():
                os.startfile(str(p))

    def _open_vid(self, sid):
        d = self._find_dir()
        if d:
            p = d / "vid" / f"scene_{sid:03d}.mp4"
            if p.exists():
                os.startfile(str(p))


# ================================================================================
# PROJECT DETAIL - Xem chi tiết project + ảnh tham chiếu
# ================================================================================

class ProjectDetail(tk.Toplevel):
    """Popup hiển thị chi tiết project và ảnh tham chiếu."""

    def __init__(self, parent, code: str):
        super().__init__(parent)
        self.code = code
        self.title(f"Chi tiet: {code}")
        self.geometry("800x600")
        self.configure(bg='#1a1a2e')

        self._build()

    def _find_project_dir(self) -> Optional[Path]:
        """Tìm thư mục project."""
        local = TOOL_DIR / "PROJECTS" / self.code
        if local.exists():
            return local
        return None

    def _build(self):
        # Header
        header = tk.Frame(self, bg='#0f3460', height=40)
        header.pack(fill="x")
        tk.Label(header, text=f"Project: {self.code}", bg='#0f3460', fg='#00ff88',
                 font=("Arial", 14, "bold")).pack(side="left", padx=20, pady=8)

        # Main content - 2 panels
        main = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg='#1a1a2e', sashwidth=4)
        main.pack(fill="both", expand=True, padx=5, pady=5)

        # Left - Info
        left = tk.Frame(main, bg='#16213e')
        main.add(left, width=300)

        info_frame = tk.LabelFrame(left, text=" THONG TIN ", bg='#16213e', fg='white',
                                   font=("Arial", 10, "bold"), padx=10, pady=10)
        info_frame.pack(fill="x", padx=5, pady=5)

        project_dir = self._find_project_dir()
        if project_dir:
            # Count images
            img_dir = project_dir / "img"
            img_count = len(list(img_dir.glob("*.png"))) + len(list(img_dir.glob("*.jpg"))) if img_dir.exists() else 0

            # Count videos
            vid_dir = project_dir / "vid"
            vid_count = len(list(vid_dir.glob("*.mp4"))) if vid_dir.exists() else 0

            # Count reference files
            ref_dir = project_dir / "NV"
            ref_count = len(list(ref_dir.glob("*.*"))) if ref_dir.exists() else 0

            info_text = f"""
Thu muc: {project_dir}

So anh: {img_count}
So video: {vid_count}
So anh tham chieu: {ref_count}
"""
            tk.Label(info_frame, text=info_text, bg='#16213e', fg='#c8d6e5',
                     font=("Consolas", 10), justify="left", anchor="w").pack(anchor="w")
        else:
            tk.Label(info_frame, text="Khong tim thay project", bg='#16213e', fg='#ff6b6b',
                     font=("Consolas", 10)).pack()

        # Right - Reference images
        right = tk.Frame(main, bg='#16213e')
        main.add(right, width=480)

        ref_frame = tk.LabelFrame(right, text=" ANH THAM CHIEU (NV/) ", bg='#16213e', fg='white',
                                  font=("Arial", 10, "bold"), padx=5, pady=5)
        ref_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # Canvas with scrollbar for images
        canvas = tk.Canvas(ref_frame, bg='#1a1a2e', highlightthickness=0)
        scrollbar = ttk.Scrollbar(ref_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='#1a1a2e')

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Load reference images
        if project_dir:
            nv_dir = project_dir / "NV"
            if nv_dir.exists():
                self._load_reference_images(scrollable_frame, nv_dir)
            else:
                tk.Label(scrollable_frame, text="Khong co thu muc NV/", bg='#1a1a2e', fg='#666',
                         font=("Consolas", 10)).pack(pady=20)

    def _load_reference_images(self, parent, nv_dir: Path):
        """Load và hiển thị ảnh tham chiếu từ thư mục NV."""
        if not PIL_AVAILABLE:
            tk.Label(parent, text="Can cai PIL de xem anh\npip install Pillow", bg='#1a1a2e', fg='#ffd93d',
                     font=("Consolas", 10)).pack(pady=20)
            return

        # Get all image files
        image_files = []
        for ext in ['*.png', '*.jpg', '*.jpeg', '*.webp']:
            image_files.extend(nv_dir.glob(ext))
        image_files.sort()

        if not image_files:
            tk.Label(parent, text="Khong co anh trong NV/", bg='#1a1a2e', fg='#666',
                     font=("Consolas", 10)).pack(pady=20)
            return

        # Display images in grid (3 columns)
        cols = 3
        row_frame = None
        self.photo_refs = []  # Keep references to prevent garbage collection

        for i, img_path in enumerate(image_files[:30]):  # Limit to 30 images
            if i % cols == 0:
                row_frame = tk.Frame(parent, bg='#1a1a2e')
                row_frame.pack(fill="x", pady=2)

            try:
                img = Image.open(img_path)
                img.thumbnail((140, 100))  # Thumbnail size
                photo = ImageTk.PhotoImage(img)
                self.photo_refs.append(photo)  # Keep reference

                # Frame for each image
                img_frame = tk.Frame(row_frame, bg='#0f3460', padx=2, pady=2)
                img_frame.pack(side="left", padx=3, pady=3)

                # Image label
                lbl = tk.Label(img_frame, image=photo, bg='#0f3460')
                lbl.pack()

                # Filename
                name = img_path.stem[:15] + "..." if len(img_path.stem) > 15 else img_path.stem
                tk.Label(img_frame, text=name, bg='#0f3460', fg='#aaa',
                         font=("Consolas", 7)).pack()

                # Click to open full size
                lbl.bind("<Button-1>", lambda e, p=img_path: os.startfile(str(p)))
                lbl.config(cursor="hand2")

            except Exception as e:
                pass

        # Info label
        tk.Label(parent, text=f"Tong: {len(image_files)} anh (click de mo)", bg='#1a1a2e', fg='#666',
                 font=("Consolas", 9)).pack(pady=10)


# ================================================================================
# MAIN GUI - Dashboard với LOG
# ================================================================================

class SimpleGUI(tk.Tk):
    """Dashboard don gian - click project de xem chi tiet."""

    def __init__(self):
        super().__init__()
        self.title("VE3 Dashboard")
        self.geometry("1400x850")
        self.configure(bg='#1a1a2e')

        # Khoi tao manager ngay de hien projects
        self.manager = VMManager(num_chrome_workers=2)
        self.running = False
        self.selected_project = None  # Project dang xem chi tiet
        self.scene_photo_refs = []  # Keep references for thumbnails
        self.windows_visible = False  # Track CMD/Chrome visibility

        self._build()
        self._load_projects_on_startup()  # Load projects ngay khi mo
        self._update_loop()

    def _build(self):
        # === TOP: Controls ===
        top = tk.Frame(self, bg='#0f3460', height=60)
        top.pack(fill="x")
        top.pack_propagate(False)

        # Start/Stop
        self.start_btn = tk.Button(
            top, text="BAT DAU", command=self._start,
            bg='#00ff88', fg='#1a1a2e', font=("Arial", 12, "bold"),
            relief="flat", padx=20, pady=5
        )
        self.start_btn.pack(side="left", padx=20, pady=12)

        self.stop_btn = tk.Button(
            top, text="DUNG", command=self._stop,
            bg='#e94560', fg='white', font=("Arial", 12, "bold"),
            relief="flat", padx=20, pady=5
        )
        self.stop_btn.pack(side="left", padx=5, pady=12)

        # Mode
        mode_frame = tk.Frame(top, bg='#0f3460')
        mode_frame.pack(side="left", padx=30)
        tk.Label(mode_frame, text="Mode:", bg='#0f3460', fg='white', font=("Arial", 10)).pack(side="left")
        self.mode_var = tk.StringVar(value="basic")
        tk.Radiobutton(mode_frame, text="Basic", variable=self.mode_var, value="basic",
                       bg='#0f3460', fg='white', selectcolor='#1a1a2e', font=("Arial", 10)).pack(side="left")
        tk.Radiobutton(mode_frame, text="Full", variable=self.mode_var, value="full",
                       bg='#0f3460', fg='white', selectcolor='#1a1a2e', font=("Arial", 10)).pack(side="left")

        # Show/Hide CMD+Chrome button
        self.windows_visible = False  # Start hidden
        self.toggle_btn = tk.Button(top, text="HIEN CMD", command=self._toggle_windows,
                  bg='#6c5ce7', fg='white', font=("Arial", 9, "bold"), relief="flat", padx=10)
        self.toggle_btn.pack(side="left", padx=10)

        # IPv6 toggle
        self.ipv6_var = tk.BooleanVar(value=self._get_ipv6_setting())
        self.ipv6_check = tk.Checkbutton(top, text="IPv6", variable=self.ipv6_var,
                  command=self._toggle_ipv6, bg='#0f3460', fg='#00ff88',
                  selectcolor='#1a1a2e', font=("Arial", 10, "bold"),
                  activebackground='#0f3460', activeforeground='#00ff88')
        self.ipv6_check.pack(side="left", padx=15)

        # Setup button - cai thu vien
        self.setup_btn = tk.Button(top, text="SETUP", command=self._run_setup,
                  bg='#ff9f43', fg='white', font=("Arial", 9, "bold"), relief="flat", padx=10)
        self.setup_btn.pack(side="left", padx=5)

        # Status
        self.status_var = tk.StringVar(value="San sang")
        tk.Label(top, textvariable=self.status_var, bg='#0f3460', fg='#00d9ff',
                 font=("Consolas", 11, "bold")).pack(side="right", padx=20)

        # === MAIN CONTENT: Left (Workers + Projects) | Right (LOG) ===
        main = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg='#1a1a2e', sashwidth=5)
        main.pack(fill="both", expand=True, padx=5, pady=5)

        # Left panel
        left = tk.Frame(main, bg='#1a1a2e')
        main.add(left, width=450)

        # === WORKERS - Compact inline ===
        workers = tk.Frame(left, bg='#16213e', padx=5, pady=5)
        workers.pack(fill="x", padx=5, pady=5)

        self.worker_vars = {}
        self.worker_labels = {}
        self.worker_rows = {}  # Store row frames

        # Tao 3 workers tren 1 dong
        for wid, name in [("excel", "EXCEL"), ("chrome_1", "CHR1"), ("chrome_2", "CHR2")]:
            frame = tk.Frame(workers, bg='#0f3460', padx=8, pady=4)
            frame.pack(side="left", padx=3, pady=2)

            self.worker_vars[f"{wid}_project"] = tk.StringVar(value="")
            self.worker_vars[f"{wid}_status"] = tk.StringVar(value="")

            # Name label
            name_lbl = tk.Label(frame, text=name, bg='#0f3460', fg='#888',
                     font=("Consolas", 9, "bold"))
            name_lbl.pack(side="left")

            # Project label - chi hien khi co project
            proj_lbl = tk.Label(frame, textvariable=self.worker_vars[f"{wid}_project"], bg='#0f3460', fg='#00d9ff',
                     font=("Consolas", 10, "bold"))
            proj_lbl.pack(side="left", padx=3)

            # Status label - chi hien khi dang chay
            status_lbl = tk.Label(frame, textvariable=self.worker_vars[f"{wid}_status"], bg='#0f3460', fg='#ffd93d',
                     font=("Consolas", 9))
            status_lbl.pack(side="left", padx=2)

            self.worker_labels[wid] = {'name': name_lbl, 'project': proj_lbl, 'status': status_lbl}
            self.worker_rows[wid] = frame

        # === PROJECTS ===
        projects = tk.LabelFrame(left, text=" PROJECTS (click de xem) ", bg='#16213e', fg='white',
                                 font=("Arial", 10, "bold"), padx=5, pady=5)
        projects.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        # Header
        header = tk.Frame(projects, bg='#0f3460')
        header.pack(fill="x")
        for txt, w in [("Code", 10), ("Excel", 7), ("Anh", 8), ("Video", 8), ("Status", 10)]:
            tk.Label(header, text=txt, width=w, bg='#0f3460', fg='white',
                     font=("Arial", 9, "bold")).pack(side="left", padx=2, pady=5)

        # List
        canvas = tk.Canvas(projects, bg='#16213e', highlightthickness=0)
        scrollbar = ttk.Scrollbar(projects, orient="vertical", command=canvas.yview)
        self.projects_frame = tk.Frame(canvas, bg='#16213e')

        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.create_window((0, 0), window=self.projects_frame, anchor="nw")
        self.projects_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        self.project_rows: Dict[str, dict] = {}

        # Right panel - CHI TIET PROJECT (hien khi click project)
        right = tk.Frame(main, bg='#1a1a2e')
        main.add(right, width=550)

        # Header - ten project dang xem
        self.detail_header = tk.Frame(right, bg='#0f3460', height=40)
        self.detail_header.pack(fill="x")
        self.detail_header.pack_propagate(False)

        self.detail_title_var = tk.StringVar(value="Click vao project de xem chi tiet")
        tk.Label(self.detail_header, textvariable=self.detail_title_var, bg='#0f3460', fg='#00ff88',
                 font=("Arial", 12, "bold")).pack(side="left", padx=15, pady=8)

        # === EXCEL STEPS ===
        self.excel_frame = tk.LabelFrame(right, text=" EXCEL (7 STEPS) ", bg='#16213e', fg='#00ff88',
                                    font=("Arial", 10, "bold"), padx=10, pady=5)
        self.excel_frame.pack(fill="x", padx=5, pady=5)

        self.excel_step_labels = []
        step_names = ["1.Story", "2.Segments", "3.Characters", "4.Locations", "5.Director", "6.Plans", "7.Prompts"]
        for name in step_names:
            lbl = tk.Label(self.excel_frame, text=name, bg='#16213e', fg='#666',
                          font=("Consolas", 9), padx=8)
            lbl.pack(side="left")
            self.excel_step_labels.append(lbl)

        # === REFERENCE IMAGES (NV) - dang danh sach ===
        ref_frame = tk.LabelFrame(right, text=" ANH THAM CHIEU (NV/) ", bg='#16213e', fg='#ff6b6b',
                                  font=("Arial", 9, "bold"), padx=5, pady=3)
        ref_frame.pack(fill="x", padx=5, pady=3, ipady=2)

        # Header
        ref_header = tk.Frame(ref_frame, bg='#0f3460')
        ref_header.pack(fill="x")
        tk.Label(ref_header, text="#", width=3, bg='#0f3460', fg='white', font=("Consolas", 9, "bold")).pack(side="left", padx=2)
        tk.Label(ref_header, text="Thumb", width=6, bg='#0f3460', fg='white', font=("Consolas", 9, "bold")).pack(side="left", padx=2)
        tk.Label(ref_header, text="Ten file", width=25, bg='#0f3460', fg='white', font=("Consolas", 9, "bold")).pack(side="left", padx=2)

        # Scrollable list
        self.ref_canvas = tk.Canvas(ref_frame, bg='#1a1a2e', highlightthickness=0, height=90)
        ref_scrollbar = ttk.Scrollbar(ref_frame, orient="vertical", command=self.ref_canvas.yview)
        self.ref_images_frame = tk.Frame(self.ref_canvas, bg='#1a1a2e')

        self.ref_images_frame.bind("<Configure>",
            lambda e: self.ref_canvas.configure(scrollregion=self.ref_canvas.bbox("all")))
        self.ref_canvas.create_window((0, 0), window=self.ref_images_frame, anchor="nw")
        self.ref_canvas.configure(yscrollcommand=ref_scrollbar.set)

        ref_scrollbar.pack(side="right", fill="y")
        self.ref_canvas.pack(fill="both", expand=True)

        self.ref_photo_refs = []

        # === SCENES LIST ===
        scenes_frame = tk.LabelFrame(right, text=" SCENES ", bg='#16213e', fg='#ffd93d',
                                     font=("Arial", 10, "bold"), padx=5, pady=5)
        scenes_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # Header row - font to hon
        header_row = tk.Frame(scenes_frame, bg='#0f3460')
        header_row.pack(fill="x")
        tk.Label(header_row, text="ID", width=4, bg='#0f3460', fg='white', font=("Consolas", 10, "bold")).pack(side="left", padx=2)
        tk.Label(header_row, text="Thumb", width=6, bg='#0f3460', fg='white', font=("Consolas", 10, "bold")).pack(side="left", padx=2)
        tk.Label(header_row, text="SRT Time", width=18, bg='#0f3460', fg='white', font=("Consolas", 10, "bold")).pack(side="left", padx=2)
        tk.Label(header_row, text="Prompt", width=25, bg='#0f3460', fg='white', font=("Consolas", 10, "bold")).pack(side="left", padx=2)
        tk.Label(header_row, text="Img", width=5, bg='#0f3460', fg='white', font=("Consolas", 10, "bold")).pack(side="left", padx=2)
        tk.Label(header_row, text="Vid", width=5, bg='#0f3460', fg='white', font=("Consolas", 10, "bold")).pack(side="left", padx=2)

        # Scrollable scene list
        self.scene_canvas = tk.Canvas(scenes_frame, bg='#1a1a2e', highlightthickness=0)
        scene_scrollbar = ttk.Scrollbar(scenes_frame, orient="vertical", command=self.scene_canvas.yview)
        self.scenes_list_frame = tk.Frame(self.scene_canvas, bg='#1a1a2e')

        self.scenes_list_frame.bind("<Configure>",
            lambda e: self.scene_canvas.configure(scrollregion=self.scene_canvas.bbox("all")))
        self.scene_canvas.create_window((0, 0), window=self.scenes_list_frame, anchor="nw")
        self.scene_canvas.configure(yscrollcommand=scene_scrollbar.set)

        scene_scrollbar.pack(side="right", fill="y")
        self.scene_canvas.pack(fill="both", expand=True)

        # Enable mouse wheel scrolling
        def _on_mousewheel(event):
            self.scene_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        self.scene_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # === STATUS BAR - Hien thi dang lam gi ===
        status_bar = tk.Frame(self, bg='#0f3460', height=35)
        status_bar.pack(fill="x", side="bottom")
        status_bar.pack_propagate(False)

        tk.Label(status_bar, text="DANG LAM:", bg='#0f3460', fg='#888',
                 font=("Consolas", 10)).pack(side="left", padx=10)

        self.current_action_var = tk.StringVar(value="Cho bat dau...")
        tk.Label(status_bar, textvariable=self.current_action_var, bg='#0f3460', fg='#ffd93d',
                 font=("Consolas", 11, "bold")).pack(side="left", padx=5)

    def _select_project(self, code: str):
        """Chon project de hien chi tiet."""
        self.selected_project = code
        self.detail_title_var.set(f"Project: {code}")
        self._load_project_detail(code)

    def _load_project_detail(self, code: str):
        """Load chi tiet project vao panel phai."""
        project_dir = TOOL_DIR / "PROJECTS" / code
        if not project_dir.exists():
            return

        # Load reference images
        self._load_reference_images(code)

        # Load scenes from Excel
        self._load_scenes_list(code)

    def _load_reference_images(self, project_code: str):
        """Load anh tham chieu tu thu muc NV - dang danh sach."""
        for widget in self.ref_images_frame.winfo_children():
            widget.destroy()
        self.ref_photo_refs = []

        nv_dir = TOOL_DIR / "PROJECTS" / project_code / "nv"
        if not nv_dir.exists() or not PIL_AVAILABLE:
            tk.Label(self.ref_images_frame, text="Khong co NV/", bg='#1a1a2e', fg='#666',
                     font=("Consolas", 10)).pack(pady=5)
            return

        image_files = []
        for ext in ['*.png', '*.jpg', '*.jpeg', '*.webp']:
            image_files.extend(nv_dir.glob(ext))
        image_files.sort()

        if not image_files:
            tk.Label(self.ref_images_frame, text="Chua co anh", bg='#1a1a2e', fg='#666',
                     font=("Consolas", 10)).pack(pady=5)
            return

        for i, img_path in enumerate(image_files[:20]):  # Max 20 anh
            try:
                bg = '#1a1a2e' if i % 2 == 0 else '#16213e'
                row = tk.Frame(self.ref_images_frame, bg=bg, height=40)
                row.pack(fill="x", pady=1)
                row.pack_propagate(False)

                # So thu tu
                tk.Label(row, text=str(i+1), width=3, bg=bg, fg='#00d9ff',
                         font=("Consolas", 10, "bold")).pack(side="left", padx=3)

                # Thumbnail (35x35)
                img = Image.open(img_path)
                img.thumbnail((35, 35))
                photo = ImageTk.PhotoImage(img)
                self.ref_photo_refs.append(photo)

                thumb_lbl = tk.Label(row, image=photo, bg=bg, cursor="hand2")
                thumb_lbl.pack(side="left", padx=3)
                thumb_lbl.bind("<Button-1>", lambda e, p=img_path: os.startfile(str(p)))

                # Ten file
                name = img_path.name[:25] + "..." if len(img_path.name) > 25 else img_path.name
                tk.Label(row, text=name, bg=bg, fg='#c8d6e5',
                         font=("Consolas", 9), anchor="w").pack(side="left", padx=5)

            except:
                pass

    def _load_scenes_list(self, project_code: str):
        """Load danh sach scenes tu Excel - voi thumbnail va SRT time."""
        for widget in self.scenes_list_frame.winfo_children():
            widget.destroy()
        self.scene_photo_refs = []

        project_dir = TOOL_DIR / "PROJECTS" / project_code
        excel_path = project_dir / f"{project_code}_prompts.xlsx"

        if not excel_path.exists():
            tk.Label(self.scenes_list_frame, text="Chua co Excel", bg='#1a1a2e', fg='#666',
                     font=("Consolas", 12)).pack(pady=20)
            return

        try:
            from modules.excel_manager import PromptWorkbook
            wb = PromptWorkbook(str(excel_path))
            wb.load_or_create()
            scenes = wb.get_scenes()

            img_dir = project_dir / "img"
            vid_dir = project_dir / "vid"

            for i, scene in enumerate(scenes[:150]):  # Max 150 scenes
                bg = '#1a1a2e' if i % 2 == 0 else '#16213e'
                row = tk.Frame(self.scenes_list_frame, bg=bg, height=50)
                row.pack(fill="x", pady=1)
                row.pack_propagate(False)  # Fixed height

                # Scene ID - font to hon
                tk.Label(row, text=str(scene.scene_id), width=4, bg=bg, fg='#00d9ff',
                         font=("Consolas", 11, "bold")).pack(side="left", padx=3)

                # Thumbnail (45x45)
                img_path = find_scene_image(img_dir, scene.scene_id)
                thumb_frame = tk.Frame(row, bg=bg, width=50, height=45)
                thumb_frame.pack(side="left", padx=3)
                thumb_frame.pack_propagate(False)

                if img_path and PIL_AVAILABLE:
                    try:
                        img = Image.open(str(img_path))
                        img.thumbnail((45, 45))
                        photo = ImageTk.PhotoImage(img)
                        self.scene_photo_refs.append(photo)

                        thumb_lbl = tk.Label(thumb_frame, image=photo, bg=bg, cursor="hand2")
                        thumb_lbl.pack(expand=True)
                        thumb_lbl.bind("<Button-1>", lambda e, p=img_path: os.startfile(str(p)))
                    except:
                        tk.Label(thumb_frame, text="IMG", bg=bg, fg='#1dd1a1',
                                 font=("Consolas", 9)).pack(expand=True)
                else:
                    tk.Label(thumb_frame, text="--", bg=bg, fg='#444',
                             font=("Consolas", 9)).pack(expand=True)

                # SRT time - lay tu srt_start va srt_end
                srt_start = getattr(scene, 'srt_start', '') or ''
                srt_end = getattr(scene, 'srt_end', '') or ''

                if srt_start and srt_end:
                    # Format: "00:01:23" thay vi "00:01:23,456"
                    start_short = srt_start.split(',')[0] if ',' in srt_start else srt_start
                    end_short = srt_end.split(',')[0] if ',' in srt_end else srt_end
                    srt_text = f"{start_short} - {end_short}"
                else:
                    srt_text = "--"

                tk.Label(row, text=srt_text, width=18, bg=bg, fg='#ffd93d',
                         font=("Consolas", 9)).pack(side="left", padx=3)

                # Prompt (truncated) - font to hon
                prompt_text = scene.img_prompt or ""
                prompt = prompt_text[:28] + "..." if len(prompt_text) > 28 else prompt_text or "--"
                tk.Label(row, text=prompt, width=25, bg=bg, fg='#c8d6e5',
                         font=("Consolas", 9), anchor="w").pack(side="left", padx=3)

                # Image status
                if img_path:
                    img_status = tk.Label(row, text="OK", width=5, bg=bg, fg='#1dd1a1',
                             font=("Consolas", 10, "bold"), cursor="hand2")
                    img_status.pack(side="left", padx=2)
                    img_status.bind("<Button-1>", lambda e, p=img_path: os.startfile(str(p)))
                else:
                    tk.Label(row, text="--", width=5, bg=bg, fg='#666',
                             font=("Consolas", 10)).pack(side="left", padx=2)

                # Video status
                vid_path = find_scene_video(vid_dir, scene.scene_id)
                if vid_path:
                    vid_status = tk.Label(row, text="OK", width=5, bg=bg, fg='#1dd1a1',
                             font=("Consolas", 10, "bold"), cursor="hand2")
                    vid_status.pack(side="left", padx=2)
                    # Copy vid_path to avoid closure issue
                    vid_status.bind("<Button-1>", lambda e, p=str(vid_path): os.startfile(p))
                else:
                    tk.Label(row, text="--", width=5, bg=bg, fg='#666',
                             font=("Consolas", 10)).pack(side="left", padx=2)

        except Exception as e:
            tk.Label(self.scenes_list_frame, text=f"Loi: {e}", bg='#1a1a2e', fg='#ff6b6b',
                     font=("Consolas", 10)).pack(pady=20)

    def _update_detail_panel(self):
        """Update detail panel neu co project duoc chon."""
        if self.selected_project:
            # Update Excel steps status
            self._update_excel_steps(self.selected_project)

    def _update_excel_steps(self, project_code: str):
        """Update mau cua Excel step labels dua tren trang thai."""
        project_dir = TOOL_DIR / "PROJECTS" / project_code
        excel_path = project_dir / f"{project_code}_prompts.xlsx"

        if not excel_path.exists():
            # Reset all to gray
            for lbl in self.excel_step_labels:
                lbl.config(fg='#666')
            return

        try:
            from modules.excel_manager import PromptWorkbook
            wb = PromptWorkbook(str(excel_path))
            wb.load_or_create()

            # Get step status
            step_ids = ["step_1", "step_2", "step_3", "step_4", "step_5", "step_6", "step_7"]

            if hasattr(wb, 'get_all_step_status'):
                all_status = wb.get_all_step_status()
                status_dict = {}
                for s in all_status:
                    if isinstance(s, dict):
                        status_dict[s.get('step_id', '')] = s.get('status', 'PENDING')

                for i, step_id in enumerate(step_ids):
                    status = status_dict.get(step_id, 'PENDING')
                    if status == 'COMPLETED':
                        self.excel_step_labels[i].config(fg='#00ff88')  # Green
                    elif status == 'IN_PROGRESS':
                        self.excel_step_labels[i].config(fg='#ffd93d')  # Yellow
                    elif status == 'ERROR':
                        self.excel_step_labels[i].config(fg='#ff6b6b')  # Red
                    else:
                        self.excel_step_labels[i].config(fg='#666')  # Gray
            else:
                # Fallback - check if sheets exist
                for i, lbl in enumerate(self.excel_step_labels):
                    lbl.config(fg='#666')

        except Exception:
            for lbl in self.excel_step_labels:
                lbl.config(fg='#666')

    def _load_projects_on_startup(self):
        """Load projects ngay khi mo GUI (truoc khi bat dau chay)."""
        if not self.manager:
            return

        try:
            projects = self.manager.scan_projects()[:12]

            for i, code in enumerate(projects):
                if code not in self.project_rows:
                    self._create_row(code, i)

                # Load basic info
                status = self.manager.quality_checker.get_project_status(code)
                if status:
                    labels = self.project_rows[code]['labels']

                    # Excel status
                    excel_complete = getattr(status, 'excel_complete', False)
                    if excel_complete:
                        labels['excel'].config(text="OK", fg='#00ff88')
                    else:
                        labels['excel'].config(text="--", fg='#666')

                    # Images
                    img_done = getattr(status, 'images_done', 0)
                    img_total = getattr(status, 'total_scenes', 0)
                    if img_total > 0:
                        pct = int(img_done * 100 / img_total)
                        labels['images'].config(text=f"{img_done}/{img_total}", fg='#00d9ff' if pct > 0 else '#666')
                    else:
                        labels['images'].config(text="--", fg='#666')

                    # Videos
                    vid_done = getattr(status, 'videos_done', 0)
                    vid_total = getattr(status, 'total_scenes', 0)
                    if vid_total > 0:
                        labels['videos'].config(text=f"{vid_done}/{vid_total}", fg='#00d9ff' if vid_done > 0 else '#666')
                    else:
                        labels['videos'].config(text="--", fg='#666')

                    labels['status'].config(text="Ready", fg='#aaa')

            # Auto-select first project
            if projects and not self.selected_project:
                self._select_project(projects[0])

        except Exception as e:
            print(f"Error loading projects: {e}")

    def _start(self):
        if not self.manager:
            self.manager = VMManager(num_chrome_workers=2)

        self.manager.settings.excel_mode = self.mode_var.get()
        self.manager.settings.video_mode = self.mode_var.get()

        self.running = True
        self.status_var.set(f"Dang chay ({self.mode_var.get().upper()})")
        self.start_btn.config(bg='#666', state="disabled")

        # Log start
        if LOGGER_AVAILABLE:
            from modules.central_logger import log
            log("main", f"=== STARTED === Mode: {self.mode_var.get()}", "INFO")

        def run():
            self.manager.start_all(gui_mode=True)  # True = ẩn CMD windows
            threading.Thread(target=self.manager.orchestrate, daemon=True).start()

        threading.Thread(target=run, daemon=True).start()

    def _stop(self):
        if self.manager:
            self.running = False
            self.status_var.set("Dang dung...")

            # Log stop
            if LOGGER_AVAILABLE:
                from modules.central_logger import log
                log("main", "=== STOPPING ===", "INFO")

            # Kill all CMD and Chrome processes
            def stop_and_kill():
                self.manager.stop_all()
                self.manager.kill_all_chrome()
            threading.Thread(target=stop_and_kill, daemon=True).start()
            self.start_btn.config(bg='#00ff88', state="normal")

    def _toggle_windows(self):
        """Toggle CMD+Chrome windows visibility."""
        if not self.manager:
            return

        if self.windows_visible:
            # Hide - move off screen
            self.manager.hide_cmd_windows()
            self.manager.hide_chrome_windows()
            self.toggle_btn.config(text="HIEN CMD", bg='#6c5ce7')
            self.windows_visible = False
        else:
            # Show - arrange on screen
            self.manager.show_chrome_with_cmd()
            self.toggle_btn.config(text="AN CMD", bg='#00b894')
            self.windows_visible = True

    def _get_ipv6_setting(self) -> bool:
        """Doc IPv6 enabled tu settings.yaml. Mac dinh la True."""
        try:
            import yaml
            config_path = TOOL_DIR / "config" / "settings.yaml"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}
                ipv6_cfg = config.get('ipv6_rotation', {})
                # Mac dinh la True neu khong co setting
                return ipv6_cfg.get('enabled', True)
        except:
            pass
        return True  # Mac dinh enabled

    def _run_setup(self):
        """Chay pip install de cai thu vien."""
        import subprocess

        def do_setup():
            self.setup_btn.config(state="disabled", text="DANG CAI...", bg='#666')
            self.status_var.set("Dang cai thu vien...")

            try:
                # Chay pip install
                req_file = TOOL_DIR / "requirements.txt"
                if req_file.exists():
                    result = subprocess.run(
                        [sys.executable, "-m", "pip", "install", "-r", str(req_file)],
                        capture_output=True,
                        text=True,
                        timeout=300  # 5 phut
                    )

                    if result.returncode == 0:
                        self.status_var.set("Cai xong! Khoi dong lai de ap dung.")
                        self.setup_btn.config(text="XONG", bg='#00ff88')
                    else:
                        self.status_var.set("Loi khi cai!")
                        self.setup_btn.config(text="LOI", bg='#e94560')
                        print(f"Setup error: {result.stderr}")
                else:
                    self.status_var.set("Khong tim thay requirements.txt!")
                    self.setup_btn.config(text="LOI", bg='#e94560')
            except Exception as e:
                self.status_var.set(f"Loi: {e}")
                self.setup_btn.config(text="LOI", bg='#e94560')
            finally:
                self.after(3000, lambda: self.setup_btn.config(state="normal", text="SETUP", bg='#ff9f43'))

        threading.Thread(target=do_setup, daemon=True).start()

    def _toggle_ipv6(self):
        """Bat/tat IPv6 va luu vao settings.yaml."""
        try:
            import yaml
            config_path = TOOL_DIR / "config" / "settings.yaml"

            # Doc config hien tai
            config = {}
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}

            # Update IPv6 setting
            if 'ipv6_rotation' not in config:
                config['ipv6_rotation'] = {}
            config['ipv6_rotation']['enabled'] = self.ipv6_var.get()

            # Luu lai
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(config, f, default_flow_style=False, allow_unicode=True)

            # Update manager settings neu dang chay
            if self.manager and hasattr(self.manager, 'settings'):
                if hasattr(self.manager.settings, 'ipv6_rotation'):
                    self.manager.settings.ipv6_rotation['enabled'] = self.ipv6_var.get()

            status = "BAT" if self.ipv6_var.get() else "TAT"
            print(f"[GUI] IPv6: {status}")

        except Exception as e:
            print(f"[GUI] Error toggling IPv6: {e}")

    def _update_loop(self):
        self._update_workers()
        self._update_projects()
        self._update_detail_panel()
        self.after(1000, self._update_loop)

    def _update_workers(self):
        if not self.manager:
            return

        actions = []  # Thu thap cac hanh dong dang lam

        for wid in ["excel", "chrome_1", "chrome_2"]:
            try:
                status = self.manager.get_worker_status(wid)
                if status:
                    proj = status.get('current_project', '') or ''
                    state = status.get('state', 'idle')
                    step = status.get('current_step', 0)
                    step_name = status.get('step_name', '')
                    task = status.get('current_task', '')

                    # Chi hien project khi dang lam viec
                    if proj and state.lower() in ['working', 'busy']:
                        self.worker_vars[f"{wid}_project"].set(proj)
                        self.worker_labels[wid]['project'].config(fg='#00d9ff')
                        self.worker_labels[wid]['name'].config(fg='#00ff88')  # Green khi active

                        # Status text
                        if wid == "excel" and step > 0:
                            self.worker_vars[f"{wid}_status"].set(f"S{step}/7")
                            actions.append(f"EXCEL {proj}: Step {step}/7 - {step_name}")
                        else:
                            self.worker_vars[f"{wid}_status"].set("")
                            # Chrome worker
                            if 'image' in task.lower():
                                actions.append(f"{wid.upper()}: {proj} tao anh")
                            elif 'video' in task.lower():
                                actions.append(f"{wid.upper()}: {proj} tao video")
                            else:
                                actions.append(f"{wid.upper()}: {proj}")
                    else:
                        # Idle - chi hien ten, bo project va status
                        self.worker_vars[f"{wid}_project"].set("")
                        self.worker_vars[f"{wid}_status"].set("")
                        self.worker_labels[wid]['name'].config(fg='#666')  # Gray khi idle
            except:
                pass

        # Update status bar
        if actions:
            self.current_action_var.set(" | ".join(actions[:3]))  # Max 3 actions
        else:
            if self.running:
                self.current_action_var.set("Dang tim project...")
            else:
                self.current_action_var.set("Cho bat dau...")

    def _update_projects(self):
        if not self.manager:
            return

        try:
            projects = self.manager.scan_projects()[:12]

            for i, code in enumerate(projects):
                if code not in self.project_rows:
                    self._create_row(code, i)

                status = self.manager.quality_checker.get_project_status(code)
                if status:
                    labels = self.project_rows[code]['labels']

                    # Excel
                    excel_complete = getattr(status, 'excel_complete', False)
                    excel_step = getattr(status, 'excel_current_step', 0)

                    if excel_complete:
                        labels['excel'].config(text="OK", fg='#00ff88')
                    elif excel_step > 0:
                        labels['excel'].config(text=f"{excel_step}/7", fg='#00d9ff')
                    else:
                        labels['excel'].config(text="--", fg='#666')

                    # Images
                    img_done = getattr(status, 'images_done', 0)
                    img_total = getattr(status, 'total_scenes', 0)
                    if img_total > 0:
                        if img_done >= img_total:
                            labels['images'].config(text=f"{img_done}/{img_total}", fg='#00ff88')
                        else:
                            labels['images'].config(text=f"{img_done}/{img_total}", fg='#00d9ff')
                    else:
                        labels['images'].config(text="--", fg='#666')

                    # Videos
                    vid_done = getattr(status, 'videos_done', 0)
                    videos_needed = getattr(status, 'videos_needed', [])
                    vid_total = len(videos_needed) if videos_needed else 0
                    if vid_total > 0:
                        if vid_done >= vid_total:
                            labels['videos'].config(text=f"{vid_done}/{vid_total}", fg='#00ff88')
                        else:
                            labels['videos'].config(text=f"{vid_done}/{vid_total}", fg='#00d9ff')
                    else:
                        labels['videos'].config(text="--", fg='#666')

                    # Status
                    next_action = getattr(status, 'next_action', '')
                    if next_action == 'create_excel':
                        labels['status'].config(text="Tao Excel")
                    elif next_action == 'create_images':
                        labels['status'].config(text="Tao anh")
                    elif next_action == 'create_videos':
                        labels['status'].config(text="Tao video")
                    elif next_action == 'copy_to_visual':
                        labels['status'].config(text="XONG")
                    else:
                        labels['status'].config(text="--")
        except Exception as e:
            pass

    def _create_row(self, code: str, i: int):
        bg = '#1a1a2e' if i % 2 == 0 else '#16213e'

        row = tk.Frame(self.projects_frame, bg=bg, cursor="hand2")
        row.pack(fill="x", pady=1)
        row.bind("<Button-1>", lambda e, c=code: self._select_project(c))

        labels = {}

        labels['code'] = tk.Label(row, text=code, width=10, bg=bg, fg='white', font=("Consolas", 10, "bold"), anchor="w")
        labels['code'].pack(side="left", padx=2)
        labels['code'].bind("<Button-1>", lambda e, c=code: self._select_project(c))

        labels['excel'] = tk.Label(row, text="--", width=7, bg=bg, fg='#666', font=("Consolas", 10))
        labels['excel'].pack(side="left", padx=2)

        labels['images'] = tk.Label(row, text="--", width=8, bg=bg, fg='#666', font=("Consolas", 10))
        labels['images'].pack(side="left", padx=2)

        labels['videos'] = tk.Label(row, text="--", width=8, bg=bg, fg='#666', font=("Consolas", 10))
        labels['videos'].pack(side="left", padx=2)

        labels['status'] = tk.Label(row, text="--", width=10, bg=bg, fg='#aaa', font=("Consolas", 10))
        labels['status'].pack(side="left", padx=2)

        self.project_rows[code] = {'row': row, 'labels': labels, 'bg': bg}

    def _show_detail_popup(self, code: str):
        """Double click - mo popup chi tiet."""
        ProjectDetail(self, code)

    def destroy(self):
        # Kill all processes khi dong GUI
        if self.manager:
            try:
                self.manager.stop_all()
                self.manager.kill_all_chrome()
            except:
                pass

        # Remove callback when closing
        if LOGGER_AVAILABLE:
            try:
                remove_callback(self._on_new_log)
            except:
                pass
        super().destroy()


# ================================================================================
# MAIN
# ================================================================================

if __name__ == "__main__":
    if not VM_AVAILABLE:
        print("Loi: Khong tim thay vm_manager.py!")
        input("Nhan Enter de thoat...")
        sys.exit(1)

    app = SimpleGUI()
    app.mainloop()
