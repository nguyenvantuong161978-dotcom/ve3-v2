#!/usr/bin/env python3
"""
VE3 Tool - Setup Browser Profile
================================
Script de setup va quan ly Chrome profiles cho browser automation.

HUONG DAN:
1. Chay script nay lan dau de dang nhap Google account
2. Sau khi dang nhap, profile se duoc luu lai
3. Cac lan sau co the chay headless (an) vi da co session

Usage:
    python setup_browser_profile.py [profile_name]
    python setup_browser_profile.py --list
    python setup_browser_profile.py --test profile_name
"""

import sys
import os
import time
import yaml
from pathlib import Path

# Add modules to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Prefer undetected-chromedriver
DRIVER_TYPE = None
try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    DRIVER_TYPE = "undetected"
except ImportError:
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.chrome.options import Options
        DRIVER_TYPE = "selenium"
    except ImportError:
        print("Loi: Selenium chua duoc cai dat")
        print("Chay: pip install selenium undetected-chromedriver")
        sys.exit(1)


FLOW_URL = "https://labs.google/fx/vi/tools/flow"


def load_config():
    """Load config tu settings.yaml."""
    config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


def get_profiles_dir():
    """Lay thu muc profiles."""
    config = load_config()
    profiles_dir = config.get("browser_profiles_dir", "./chrome_profiles")

    # Resolve relative path
    if not os.path.isabs(profiles_dir):
        profiles_dir = Path(__file__).parent.parent / profiles_dir

    Path(profiles_dir).mkdir(parents=True, exist_ok=True)
    return Path(profiles_dir)


def list_profiles():
    """Liet ke cac profiles hien co."""
    profiles_dir = get_profiles_dir()

    print(f"\nThu muc profiles: {profiles_dir}")
    print("-" * 50)

    profiles = [d for d in profiles_dir.iterdir() if d.is_dir()]

    if not profiles:
        print("Chua co profile nao.")
        print("Chay: python setup_browser_profile.py <ten_profile>")
    else:
        print(f"Co {len(profiles)} profile(s):\n")
        for p in profiles:
            # Check size
            size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            size_mb = size / (1024 * 1024)
            print(f"  - {p.name} ({size_mb:.1f} MB)")

    print()


def create_driver(profile_dir: str, headless: bool = False):
    """Tao Chrome driver voi profile."""
    if DRIVER_TYPE == "undetected":
        # Undetected-chromedriver (tot nhat)
        print(f"  [INFO] Using undetected-chromedriver")

        options = uc.ChromeOptions()
        options.add_argument(f"--user-data-dir={profile_dir}")

        if headless:
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")

        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")

        driver = uc.Chrome(
            options=options,
            use_subprocess=True,
            version_main=None
        )

        return driver

    else:
        # Fallback: Selenium thuong
        print(f"  [INFO] Using standard selenium")

        options = Options()
        options.add_argument(f"--user-data-dir={profile_dir}")

        if headless:
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")

        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("--window-size=1920,1080")

        driver = webdriver.Chrome(options=options)

        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        return driver


def setup_profile(profile_name: str):
    """Setup profile moi va dang nhap."""
    profiles_dir = get_profiles_dir()
    profile_path = profiles_dir / profile_name

    print(f"\n{'='*60}")
    print(f"  SETUP PROFILE: {profile_name}")
    print(f"{'='*60}")
    print(f"\nProfile path: {profile_path}")

    # Tao driver
    print("\nKhoi dong Chrome...")
    driver = create_driver(str(profile_path), headless=False)

    try:
        # Navigate to Flow
        print(f"Mo trang: {FLOW_URL}")
        driver.get(FLOW_URL)

        print("\n" + "="*60)
        print("  VUI LONG DANG NHAP GOOGLE ACCOUNT TREN TRINH DUYET")
        print("="*60)
        print("\nSau khi dang nhap xong, quay lai day va nhan Enter...")

        # Cho nguoi dung dang nhap
        config = load_config()
        timeout = config.get("browser_login_timeout", 120)

        start = time.time()
        logged_in = False

        while time.time() - start < timeout:
            try:
                driver.find_element(By.CSS_SELECTOR, "textarea")
                logged_in = True
                break
            except:
                pass

            # Check neu user nhan Enter
            # (Khong hoat dong trong script, chi la placeholder)
            time.sleep(2)

        if logged_in:
            print("\n[OK] Da phat hien dang nhap thanh cong!")
            print(f"Profile da duoc luu tai: {profile_path}")
            print("\nBay gio ban co the:")
            print(f"  1. Chay headless: browser_headless: true trong settings.yaml")
            print(f"  2. Su dung profile nay cho cac voice/project khac nhau")
        else:
            print("\n[WARN] Chua phat hien dang nhap.")
            print("Profile van duoc luu, hay thu lai sau.")

        print("\nNhan Enter de dong trinh duyet...")
        input()

    finally:
        driver.quit()

    print("Done!")


def test_profile(profile_name: str, headless: bool = True):
    """Test profile bang cach tao 1 anh."""
    profiles_dir = get_profiles_dir()
    profile_path = profiles_dir / profile_name

    if not profile_path.exists():
        print(f"Loi: Profile '{profile_name}' khong ton tai")
        print(f"Chay: python setup_browser_profile.py {profile_name}")
        return

    print(f"\n{'='*60}")
    print(f"  TEST PROFILE: {profile_name}")
    print(f"{'='*60}")
    print(f"\nHeadless: {headless}")

    # Tao driver
    print("\nKhoi dong Chrome...")
    driver = create_driver(str(profile_path), headless=headless)

    try:
        # Navigate
        print(f"Mo trang: {FLOW_URL}")
        driver.get(FLOW_URL)

        time.sleep(3)

        # Check login
        print("\nKiem tra dang nhap...")
        try:
            driver.find_element(By.CSS_SELECTOR, "textarea")
            print("[OK] Da dang nhap!")

            # Inject JS
            print("\nInject JS script...")
            js_path = Path(__file__).parent / "ve3_browser_automation.js"
            if js_path.exists():
                with open(js_path, "r", encoding="utf-8") as f:
                    js_code = f.read()
                driver.execute_script(js_code)
                print("[OK] Da inject JS")

                # Test generate
                print("\nTest tao 1 anh...")
                print("Prompt: 'a cute orange cat, studio photo'")

                result = driver.execute_async_script("""
                    const callback = arguments[arguments.length - 1];
                    const timeout = setTimeout(() => {
                        callback({ success: false, error: 'Timeout after 60s' });
                    }, 60000);

                    VE3.generateOne("a cute orange cat, studio photo", {
                        download: false
                    }).then(r => {
                        clearTimeout(timeout);
                        callback(r);
                    }).catch(e => {
                        clearTimeout(timeout);
                        callback({ success: false, error: e.message });
                    });
                """)

                if result and result.get("success"):
                    print("\n[SUCCESS] Tao anh thanh cong!")
                    images = result.get("images", [])
                    for img in images:
                        print(f"  URL: {img.get('url', '')[:80]}...")
                else:
                    error = result.get("error", "Unknown") if result else "No response"
                    print(f"\n[FAILED] Loi: {error}")

            else:
                print(f"[WARN] JS file khong tim thay: {js_path}")

        except Exception as e:
            print(f"[FAILED] Chua dang nhap hoac loi: {e}")
            print("\nHay chay setup lai:")
            print(f"  python setup_browser_profile.py {profile_name}")

    finally:
        print("\nDong trinh duyet...")
        driver.quit()

    print("\nDone!")


def main():
    print("""
+============================================================+
|       VE3 BROWSER PROFILE MANAGER                          |
+============================================================+
""")

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python setup_browser_profile.py <profile_name>  - Setup profile moi")
        print("  python setup_browser_profile.py --list          - Liet ke profiles")
        print("  python setup_browser_profile.py --test <name>   - Test profile")
        print()
        list_profiles()
        return

    arg = sys.argv[1]

    if arg == "--list":
        list_profiles()

    elif arg == "--test":
        if len(sys.argv) < 3:
            print("Vui long cung cap ten profile")
            print("  python setup_browser_profile.py --test <profile_name>")
            return
        headless = "--headless" in sys.argv
        test_profile(sys.argv[2], headless=headless)

    else:
        # Setup profile
        profile_name = arg
        setup_profile(profile_name)


if __name__ == "__main__":
    main()
