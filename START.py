#!/usr/bin/env python3
"""
VE3 Tool - Khoi dong
====================
Chay file nay de:
1. Tu dong cai thu vien can thiet
2. Mo GUI

Usage:
    python START.py
"""

import subprocess
import sys
import os

# Thu muc chua tool
TOOL_DIR = os.path.dirname(os.path.abspath(__file__))

def install_requirements():
    """Cai thu vien tu requirements.txt"""
    req_file = os.path.join(TOOL_DIR, "requirements.txt")

    if not os.path.exists(req_file):
        print("[ERROR] Khong tim thay requirements.txt!")
        return False

    print("=" * 50)
    print("DANG CAI THU VIEN...")
    print("=" * 50)

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", req_file],
            cwd=TOOL_DIR
        )

        if result.returncode == 0:
            print("\n[OK] Cai thu vien thanh cong!")
            return True
        else:
            print("\n[ERROR] Loi khi cai thu vien!")
            return False

    except Exception as e:
        print(f"\n[ERROR] {e}")
        return False

def check_requirements():
    """Kiem tra xem da cai du thu vien chua"""
    required = ['yaml', 'openpyxl', 'PIL', 'requests']
    missing = []

    for mod in required:
        try:
            if mod == 'yaml':
                import yaml
            elif mod == 'openpyxl':
                import openpyxl
            elif mod == 'PIL':
                from PIL import Image
            elif mod == 'requests':
                import requests
        except ImportError:
            missing.append(mod)

    return len(missing) == 0

def run_gui():
    """Chay GUI"""
    gui_file = os.path.join(TOOL_DIR, "vm_manager_gui.py")

    if not os.path.exists(gui_file):
        print("[ERROR] Khong tim thay vm_manager_gui.py!")
        return

    print("\n" + "=" * 50)
    print("DANG MO GUI...")
    print("=" * 50)

    # Chay GUI
    subprocess.run([sys.executable, gui_file], cwd=TOOL_DIR)

def main():
    print("""
    ╔═══════════════════════════════════════╗
    ║         VE3 TOOL - KHOI DONG          ║
    ╚═══════════════════════════════════════╝
    """)

    # Kiem tra thu vien
    if not check_requirements():
        print("[INFO] Chua cai du thu vien, dang cai...")
        if not install_requirements():
            print("\n[ERROR] Khong the cai thu vien!")
            print("Thu chay thu cong: pip install -r requirements.txt")
            input("\nNhan Enter de thoat...")
            return
    else:
        print("[OK] Da cai du thu vien")

    # Chay GUI
    run_gui()

if __name__ == "__main__":
    main()
