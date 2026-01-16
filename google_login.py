#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VE3 Tool - Google Login Helper

Đọc thông tin tài khoản từ Google Sheet và đăng nhập vào Chrome.

Sheet: ve3
- Cột A: Mã máy (ví dụ: AR57-T1)
- Cột B: ID (email Google)
- Cột C: Password

Cách detect mã máy:
- Từ đường dẫn: Documents\AR57-T1\ve3-tool-simple\ → mã là AR57-T1
"""

import sys
import os
import json
import time
import re
from pathlib import Path

TOOL_DIR = Path(__file__).parent
sys.path.insert(0, str(TOOL_DIR))

CONFIG_FILE = TOOL_DIR / "config" / "config.json"
SHEET_NAME = "ve3"  # Sheet chứa thông tin tài khoản


def log(msg: str, level: str = "INFO"):
    """Print log with timestamp."""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [{level}] {msg}")


def detect_machine_code() -> str:
    """
    Detect mã máy từ đường dẫn thư mục tool.

    Ví dụ:
    - C:\\Users\\Admin\\Documents\\AR57-T1\\ve3-tool-simple → AR57-T1
    - D:\\VMs\\AR4-T1\\ve3-tool-simple → AR4-T1
    - C:\\Users\\hoangmai\\Documents\\AR4-T1\\ve3-tool-simple → AR4-T1
    """
    tool_path = TOOL_DIR.resolve()

    # Lấy thư mục cha của ve3-tool-simple
    parent = tool_path.parent

    # Mã máy thường có dạng: XX#-T# hoặc XX##-T# hoặc XX##-####
    # Ví dụ: AR4-T1, AR57-T1, AR47-0028
    # Pattern linh hoạt: 2 chữ cái + 1-3 số + dash + alphanumeric
    code_pattern = re.compile(r'^[A-Z]{2}\d{1,3}-[A-Z0-9]+$', re.IGNORECASE)

    # Kiểm tra parent folder
    if code_pattern.match(parent.name):
        return parent.name.upper()

    # Kiểm tra grandparent (Documents\AR57-T1\ve3-tool-simple)
    grandparent = parent.parent
    if code_pattern.match(grandparent.name):
        return grandparent.name.upper()

    # Thử tìm trong path
    for part in tool_path.parts:
        if code_pattern.match(part):
            return part.upper()

    return ""


def load_gsheet_client():
    """Load Google Sheet client."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        log("gspread not installed. Run: pip install gspread google-auth", "ERROR")
        return None, None

    if not CONFIG_FILE.exists():
        log(f"Config file not found: {CONFIG_FILE}", "ERROR")
        return None, None

    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

        sa_path = (
            cfg.get("SERVICE_ACCOUNT_JSON") or
            cfg.get("service_account_json") or
            cfg.get("CREDENTIAL_PATH") or
            cfg.get("credential_path")
        )

        if not sa_path:
            log("Missing SERVICE_ACCOUNT_JSON in config", "ERROR")
            return None, None

        spreadsheet_name = cfg.get("SPREADSHEET_NAME")
        if not spreadsheet_name:
            log("Missing SPREADSHEET_NAME in config", "ERROR")
            return None, None

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]

        sa_file = Path(sa_path)
        if not sa_file.exists():
            sa_file = TOOL_DIR / "config" / sa_path

        if not sa_file.exists():
            log(f"Service account file not found: {sa_path}", "ERROR")
            return None, None

        creds = Credentials.from_service_account_file(str(sa_file), scopes=scopes)
        gc = gspread.authorize(creds)

        return gc, spreadsheet_name

    except Exception as e:
        log(f"Error loading gsheet client: {e}", "ERROR")
        return None, None


def get_account_info(machine_code: str) -> dict:
    """
    Lấy thông tin tài khoản từ Google Sheet.

    Returns:
        {"id": "email@gmail.com", "password": "xxx"} or None
    """
    gc, spreadsheet_name = load_gsheet_client()
    if not gc:
        return None

    try:
        ws = gc.open(spreadsheet_name).worksheet(SHEET_NAME)

        # Đọc tất cả dữ liệu
        all_data = ws.get_all_values()

        if not all_data:
            log(f"Sheet '{SHEET_NAME}' is empty", "ERROR")
            return None

        # Tìm row có mã máy khớp (cột A)
        for row_idx, row in enumerate(all_data, start=1):
            if len(row) >= 3:
                code = str(row[0]).strip().upper()
                if code == machine_code.upper():
                    account_id = str(row[1]).strip()
                    password = str(row[2]).strip()

                    if account_id and password:
                        log(f"Found account for {machine_code}: {account_id}")
                        return {
                            "id": account_id,
                            "password": password,
                            "row": row_idx
                        }
                    else:
                        log(f"Row {row_idx} has empty ID or password", "WARN")

        log(f"Machine code '{machine_code}' not found in sheet", "ERROR")
        return None

    except Exception as e:
        log(f"Error reading sheet: {e}", "ERROR")
        return None


def login_google_chrome(account_info: dict, chrome_portable: str = None, profile_dir: str = None, worker_id: int = 0) -> bool:
    """
    Mở Chrome và đăng nhập Google bằng JavaScript.

    Do Google có nhiều biện pháp chống bot, script này sẽ:
    1. Mở Chrome đến trang đăng nhập
    2. Dùng JavaScript để điền email/password và trigger events
    3. Để user xác thực nếu cần

    Args:
        account_info: Dict với 'id' (email) và 'password'
        chrome_portable: Đường dẫn Chrome Portable cụ thể (nếu có).
                        Quan trọng khi có nhiều Chrome chạy song song.
        profile_dir: Đường dẫn profile Chrome cụ thể (nếu có).
                    Dùng cho Chrome 2 với profile riêng (ví dụ: pic2).
        worker_id: Worker ID để dùng port khác nhau cho mỗi Chrome.
    """
    try:
        from DrissionPage import ChromiumPage, ChromiumOptions
    except ImportError:
        log("DrissionPage not installed. Run: pip install DrissionPage", "ERROR")
        return False

    email = account_info["id"]
    password = account_info["password"]

    log(f"Opening Chrome for login: {email}")

    try:
        # Setup Chrome options
        options = ChromiumOptions()

        # === Port riêng cho mỗi Chrome (tránh conflict) ===
        # Chrome 1 (worker_id=0): port 9222
        # Chrome 2 (worker_id=1): port 9223
        base_port = 9222 + worker_id
        options.set_local_port(base_port)  # Dùng set_local_port như drission_flow_api.py
        log(f"Using port: {base_port} (worker_id={worker_id})")

        # Ưu tiên chrome_portable được truyền vào (cho Chrome 2 song song)
        chrome_exe = None
        if chrome_portable and Path(chrome_portable).exists():
            chrome_exe = chrome_portable
            log(f"Using specified Chrome: {chrome_exe}")
        else:
            # Fallback: Tìm Chrome Portable mặc định
            chrome_paths = [
                TOOL_DIR / "GoogleChromePortable" / "GoogleChromePortable.exe",
                Path.home() / "Documents" / "GoogleChromePortable" / "GoogleChromePortable.exe",
            ]
            for cp in chrome_paths:
                if cp.exists():
                    chrome_exe = str(cp)
                    break

        if chrome_exe:
            options.set_browser_path(chrome_exe)
            log(f"Using Chrome: {chrome_exe}")

            # === Profile: ưu tiên profile_dir được truyền vào ===
            if profile_dir and Path(profile_dir).exists():
                options.set_user_data_path(str(profile_dir))
                log(f"Using profile: {profile_dir}")
            else:
                # Fallback: dùng profile mặc định của Chrome Portable
                chrome_dir = Path(chrome_exe).parent
                for data_path in [chrome_dir / "Data" / "profile", chrome_dir / "User Data"]:
                    if data_path.exists():
                        options.set_user_data_path(str(data_path))
                        log(f"Using default profile: {data_path}")
                        break

        # Mở Chrome mới
        driver = ChromiumPage(options)

        # Đi đến trang đăng nhập Google
        log("Navigating to Google login...")
        driver.get("https://accounts.google.com/signin")
        time.sleep(3)

        # Kiểm tra xem đã đăng nhập chưa
        if "myaccount.google.com" in driver.url or "google.com/search" in driver.url:
            log("Already logged in!", "OK")
            return True

        # === BƯỚC 1: ĐIỀN EMAIL ===
        log("Finding email input...")
        try:
            # Tìm input email
            email_input = driver.ele('#identifierId', timeout=5)
            if not email_input:
                email_input = driver.ele('input[type="email"]', timeout=3)

            if email_input:
                log(f"Found email input, filling: {email}")
                # Click để focus
                email_input.click()
                time.sleep(0.3)

                # Dùng JavaScript để set value và trigger events
                js_set_email = f'''
                    this.value = "{email}";
                    this.dispatchEvent(new Event('input', {{bubbles: true}}));
                    this.dispatchEvent(new Event('change', {{bubbles: true}}));
                '''
                email_input.run_js(js_set_email)
                log(f"Email filled via JS")
                time.sleep(0.5)

                # Nhấn Enter hoặc click Next
                log("Clicking Next button...")
                try:
                    next_btn = driver.ele('button:contains("Next")', timeout=2) or \
                               driver.ele('button:contains("Tiếp theo")', timeout=2) or \
                               driver.ele('button:contains("Tiếp tục")', timeout=2)
                    if next_btn:
                        next_btn.click()
                        log("Clicked Next button")
                    else:
                        # Fallback: nhấn Enter
                        email_input.input('\n')
                        log("Pressed Enter")
                except:
                    email_input.input('\n')
                    log("Pressed Enter (fallback)")

                time.sleep(3)
            else:
                log("Email input not found!", "WARN")
        except Exception as e:
            log(f"Email step error: {e}", "WARN")

        # === BƯỚC 2: ĐIỀN PASSWORD (Ctrl+V) ===
        log("Entering password with Ctrl+V...")
        try:
            # Đợi trang password load
            time.sleep(3)

            # Copy password vào clipboard
            try:
                import pyperclip
                pyperclip.copy(password)
                log("Password copied to clipboard")
            except ImportError:
                # Fallback nếu không có pyperclip - dùng Windows clipboard
                import subprocess
                subprocess.run(['clip'], input=password.encode(), check=True)
                log("Password copied to clipboard (via clip)")

            # Gửi Ctrl+V để paste
            from DrissionPage.common import Actions
            actions = Actions(driver)
            actions.key_down('ctrl').key_down('v').key_up('v').key_up('ctrl')
            log("Sent Ctrl+V")
            time.sleep(0.5)

            # Nhấn Enter để submit
            actions.key_down('enter').key_up('enter')
            log("Pressed Enter")
        except Exception as e:
            log(f"Password step error: {e}", "WARN")

        # === XONG - Đợi login hoàn tất ===
        log("Waiting for login to complete...")
        time.sleep(5)  # Đợi 5s cho login xong
        log("Login completed!", "OK")

        # Đợi thêm để trang load đầy đủ trước khi tắt
        log("Waiting for page to fully load...")
        time.sleep(10)  # Đợi thêm 10s cho trang load xong
        log("Page loaded, closing browser...", "OK")

        # Đóng Chrome (drission_flow_api.py sẽ tự navigate đến project)
        try:
            driver.quit()
            log("Chrome closed")
        except:
            pass

        return True

    except Exception as e:
        log(f"Login error: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 60)
    print("  VE3 TOOL - GOOGLE LOGIN HELPER")
    print("=" * 60)

    # 1. Detect machine code
    machine_code = detect_machine_code()

    if not machine_code:
        log("Cannot detect machine code from path", "ERROR")
        log(f"Current path: {TOOL_DIR}")
        log("Expected pattern: XX#-T# hoặc XX##-T# (ví dụ: AR4-T1, AR57-T1)")

        # Cho user nhập manual
        machine_code = input("\nEnter machine code (e.g., AR57-T1): ").strip().upper()
        if not machine_code:
            log("No machine code provided", "ERROR")
            return 1

    log(f"Machine code: {machine_code}")

    # 2. Get account info from sheet
    log(f"Reading account info from sheet '{SHEET_NAME}'...")
    account_info = get_account_info(machine_code)

    if not account_info:
        log("Cannot get account info", "ERROR")
        return 1

    # 3. Login to Google
    log("Starting Google login...")
    success = login_google_chrome(account_info)

    if success:
        log("=" * 60)
        log("  LOGIN COMPLETED!")
        log("=" * 60)
        return 0
    else:
        log("Login failed", "ERROR")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
