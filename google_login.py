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


def login_google_chrome(account_info: dict) -> bool:
    """
    Mở Chrome và đăng nhập Google bằng JavaScript.

    Do Google có nhiều biện pháp chống bot, script này sẽ:
    1. Mở Chrome đến trang đăng nhập
    2. Dùng JavaScript để điền email/password và trigger events
    3. Để user xác thực nếu cần
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

        # Tìm Chrome Portable
        chrome_paths = [
            TOOL_DIR / "GoogleChromePortable" / "GoogleChromePortable.exe",
            Path.home() / "Documents" / "GoogleChromePortable" / "GoogleChromePortable.exe",
        ]

        chrome_exe = None
        for cp in chrome_paths:
            if cp.exists():
                chrome_exe = str(cp)
                break

        if chrome_exe:
            options.set_browser_path(chrome_exe)
            log(f"Using Chrome: {chrome_exe}")

            # User data
            chrome_dir = Path(chrome_exe).parent
            for data_path in [chrome_dir / "Data" / "profile", chrome_dir / "User Data"]:
                if data_path.exists():
                    options.set_user_data_path(str(data_path))
                    break

        # Mở Chrome
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
            time.sleep(3)
        except Exception as e:
            log(f"Password step error: {e}", "WARN")

        # === BƯỚC 3: CHỌN CHẾ ĐỘ LOGIN (Tab Tab Enter) ===
        log("Waiting for login mode selection screen...")
        try:
            time.sleep(6)  # Đợi trang load lâu hơn
            log("Selecting login mode (Tab Tab Enter)...")
            from DrissionPage.common import Actions
            actions = Actions(driver)

            # Tab 2 lần
            actions.key_down('tab').key_up('tab')
            time.sleep(0.2)
            actions.key_down('tab').key_up('tab')
            time.sleep(0.2)

            # Enter để chọn
            actions.key_down('enter').key_up('enter')
            log("Sent Tab Tab Enter")
        except Exception as e:
            log(f"Tab Tab Enter error: {e}", "WARN")

        # === BƯỚC 4: VÀO FLOW VÀ CLICK "Create with Flow" ===
        log("Navigating to Flow...")
        try:
            time.sleep(3)
            driver.get("https://labs.google/fx/vi/tools/flow")
            time.sleep(5)  # Đợi trang load

            log("Looking for 'Create with Flow' button...")
            from DrissionPage.common import Actions
            actions = Actions(driver)

            # Thử click button "Create with Flow"
            try:
                create_btn = driver.ele('button:contains("Create with Flow")', timeout=3)
                if create_btn:
                    create_btn.click()
                    log("Clicked 'Create with Flow' button")
                else:
                    # Fallback: Tab 3 lần rồi Enter
                    log("Button not found, trying Tab Tab Tab Enter...")
                    for _ in range(3):
                        actions.key_down('tab').key_up('tab')
                        time.sleep(0.2)
                    actions.key_down('enter').key_up('enter')
                    log("Sent Tab Tab Tab Enter")
            except:
                # Fallback: Tab 3 lần rồi Enter
                log("Fallback: Tab Tab Tab Enter...")
                for _ in range(3):
                    actions.key_down('tab').key_up('tab')
                    time.sleep(0.2)
                actions.key_down('enter').key_up('enter')
                log("Sent Tab Tab Tab Enter")

            time.sleep(3)
        except Exception as e:
            log(f"Create Flow error: {e}", "WARN")

        # === BƯỚC 5: CLICK "Tiếp theo" (Chính sách) ===
        log("Looking for 'Tiếp theo' button (Policy)...")
        try:
            time.sleep(2)
            next_btn = driver.ele('button:contains("Tiếp theo")', timeout=5)
            if next_btn:
                next_btn.click()
                log("Clicked 'Tiếp theo' button")
            else:
                log("'Tiếp theo' button not found", "WARN")
            time.sleep(2)
        except Exception as e:
            log(f"Policy button error: {e}", "WARN")

        # === BƯỚC 6: TAB + END để cuộn xuống cuối ===
        log("Scrolling down with Tab + End...")
        try:
            time.sleep(2)
            from DrissionPage.common import Actions
            actions = Actions(driver)

            # Tab để focus vào content
            actions.key_down('tab').key_up('tab')
            time.sleep(0.3)

            # End để cuộn xuống cuối
            actions.key_down('end').key_up('end')
            log("Sent Tab + End")
            time.sleep(1)
        except Exception as e:
            log(f"Scroll error: {e}", "WARN")

        # === BƯỚC 7: CLICK "Tiếp tục" ===
        log("Looking for 'Tiếp tục' button...")
        try:
            time.sleep(1)
            continue_btn = driver.ele('button:contains("Tiếp tục")', timeout=5)
            if continue_btn:
                continue_btn.click()
                log("Clicked 'Tiếp tục' button")
            else:
                log("'Tiếp tục' button not found", "WARN")
            time.sleep(2)
        except Exception as e:
            log(f"Continue button error: {e}", "WARN")

        # Kiểm tra kết quả
        time.sleep(3)
        log("Setup completed!", "OK")

        # Đóng Chrome (không đợi user nhấn Enter khi chạy tự động)
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
