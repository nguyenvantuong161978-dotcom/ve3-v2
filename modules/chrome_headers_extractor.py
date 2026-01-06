#!/usr/bin/env python3
"""
VE3 Tool - Chrome Headers Extractor
====================================
Mở Chrome, intercept network requests để lấy headers real-time.
Sau đó dùng headers để gọi API.

Flow:
1. Mở Chrome với Selenium + CDP (Chrome DevTools Protocol)
2. Navigate tới labs.google/flow
3. Intercept network requests
4. Capture headers (x-browser-validation, authorization, etc.)
5. Return headers để gọi API
"""

import json
import time
import threading
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass


@dataclass
class CapturedHeaders:
    """Headers captured từ Chrome."""
    authorization: str = ""
    x_browser_validation: str = ""
    x_browser_channel: str = ""
    x_browser_copyright: str = ""
    x_browser_year: str = ""
    x_client_data: str = ""
    cookies: str = ""
    user_agent: str = ""
    timestamp: float = 0

    def is_valid(self) -> bool:
        """Check if headers are valid."""
        return bool(self.authorization and self.x_browser_validation)

    def age_seconds(self) -> float:
        """Tuổi của headers (giây)."""
        return time.time() - self.timestamp if self.timestamp else 999999

    def to_dict(self) -> Dict[str, str]:
        """Convert to dict for requests - dùng đúng case như Chrome."""
        headers = {
            "Authorization": self.authorization,
            "Content-Type": "text/plain;charset=UTF-8",
            "Accept": "*/*",
            "Origin": "https://labs.google",
            "Referer": "https://labs.google/",
            "x-browser-channel": self.x_browser_channel or "stable",
            "x-browser-copyright": self.x_browser_copyright or "Copyright 2025 Google LLC. All Rights reserved.",
            "x-browser-validation": self.x_browser_validation,
            "x-browser-year": self.x_browser_year or "2025",
            "User-Agent": self.user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        # Chỉ thêm x-client-data nếu có
        if self.x_client_data:
            headers["x-client-data"] = self.x_client_data
        return headers


class ChromeHeadersExtractor:
    """
    Extract headers từ Chrome real-time bằng CDP.
    """

    FLOW_URL = "https://labs.google/fx/vi/tools/flow"
    API_PATTERN = "aisandbox-pa.googleapis.com"

    def __init__(
        self,
        chrome_profile_path: str = None,
        headless: bool = False,
        verbose: bool = True
    ):
        self.chrome_profile_path = chrome_profile_path
        self.headless = headless
        self.verbose = verbose

        self.driver = None
        self.captured_headers = CapturedHeaders()
        self._capture_lock = threading.Lock()

    def _log(self, msg: str):
        if self.verbose:
            print(f"[HeadersExtractor] {msg}")

    def start_browser(self) -> bool:
        """
        Khởi động Chrome với CDP enabled.
        Copy từ browser_flow_generator._create_driver() để đảm bảo tương thích.
        """
        import os
        import random
        import shutil

        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options

            options = Options()

            # Tim Chrome binary (giong browser_flow_generator)
            chrome_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                "/usr/bin/google-chrome",
                "/usr/bin/chromium-browser",
            ]
            for chrome_path in chrome_paths:
                if os.path.exists(chrome_path):
                    options.binary_location = chrome_path
                    self._log(f"Chrome binary: {chrome_path}")
                    break

            # Tao working profile (giong browser_flow_generator)
            if self.chrome_profile_path:
                profile_dir = Path(self.chrome_profile_path)
                profile_name = profile_dir.name

                # Working profile rieng cho headers extractor
                working_profile_base = Path.home() / ".ve3_chrome_profiles"
                working_profile_base.mkdir(parents=True, exist_ok=True)
                working_profile = working_profile_base / f"{profile_name}_headers"

                self._log(f"Profile goc: {profile_dir}")
                self._log(f"Working profile: {working_profile}")

                # Copy profile neu chua co
                if not working_profile.exists():
                    working_profile.mkdir(parents=True, exist_ok=True)
                    if profile_dir.exists() and any(profile_dir.iterdir()):
                        for item in profile_dir.iterdir():
                            try:
                                dest = working_profile / item.name
                                if item.is_dir():
                                    shutil.copytree(item, dest, dirs_exist_ok=True)
                                else:
                                    shutil.copy2(item, dest)
                            except Exception:
                                pass  # Skip locked files
                        self._log("Da copy profile data")
                else:
                    self._log("Su dung working profile da co")

                options.add_argument(f"--user-data-dir={working_profile}")

            # Random debug port (tranh xung dot)
            debug_port = random.randint(9222, 9999)
            options.add_argument(f"--remote-debugging-port={debug_port}")
            self._log(f"Debug port: {debug_port}")

            if self.headless:
                options.add_argument("--headless=new")
                options.add_argument("--disable-gpu")

            # Cac options giong browser_flow_generator
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-infobars")
            options.add_argument("--window-size=1920,1080")

            # Enable CDP logging
            options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

            options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
            options.add_experimental_option("useAutomationExtension", False)

            self._log(f"Dang khoi dong Chrome...")
            self.driver = webdriver.Chrome(options=options)

            # Hide webdriver
            self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            })

            self._log("Browser started!")
            return True

        except Exception as e:
            self._log(f"Error starting browser: {e}")
            import traceback
            traceback.print_exc()
            return False

    def navigate_to_flow(self) -> bool:
        """Navigate tới Flow page."""
        if not self.driver:
            return False

        try:
            self._log(f"Navigating to {self.FLOW_URL}...")
            self.driver.get(self.FLOW_URL)
            time.sleep(3)
            return True
        except Exception as e:
            self._log(f"Error navigating: {e}")
            return False

    def capture_headers_from_network(self, timeout: int = 30) -> CapturedHeaders:
        """
        Capture headers từ network logs.
        Trigger 1 request để capture headers.
        """
        if not self.driver:
            return CapturedHeaders()

        self._log("Capturing headers from network...")

        # Enable network tracking
        self.driver.execute_cdp_cmd("Network.enable", {})

        # Trigger a request bằng cách click vào page hoặc scroll
        try:
            self.driver.execute_script("""
                // Trigger any API call
                if (typeof window.__VE3_TRIGGER__ === 'undefined') {
                    window.__VE3_TRIGGER__ = true;
                    // Scroll to trigger lazy load
                    window.scrollTo(0, 100);
                    window.scrollTo(0, 0);
                }
            """)
        except:
            pass

        # Wait và check logs
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                logs = self.driver.get_log("performance")

                for log in logs:
                    try:
                        message = json.loads(log["message"])
                        method = message.get("message", {}).get("method", "")

                        # Check both requestWillBeSent và requestWillBeSentExtraInfo
                        # ExtraInfo chứa headers thực tế Chrome gửi (bao gồm x-browser-validation)
                        if method in ["Network.requestWillBeSent", "Network.requestWillBeSentExtraInfo"]:
                            params = message.get("message", {}).get("params", {})

                            # requestWillBeSent có request.url, ExtraInfo có headers trực tiếp
                            if method == "Network.requestWillBeSent":
                                request = params.get("request", {})
                                url = request.get("url", "")
                                headers = request.get("headers", {})
                            else:  # ExtraInfo - headers thực tế được gửi
                                url = "aisandbox-pa.googleapis.com"  # ExtraInfo không có URL, dùng pattern
                                headers = params.get("headers", {})

                            if self.API_PATTERN in url:

                                self._log(f"Found API request: {url[:60]}...")

                                # Case-insensitive header lookup
                                def get_header(name):
                                    for k, v in headers.items():
                                        if k.lower() == name.lower():
                                            return v
                                    return ""

                                auth = get_header("Authorization")
                                x_browser = get_header("x-browser-validation")

                                # Debug: show what we found
                                if auth:
                                    self._log(f"   Authorization: {auth[:40]}...")
                                if x_browser:
                                    self._log(f"   x-browser-validation: {x_browser[:40]}...")

                                with self._capture_lock:
                                    # Only update if we found something new
                                    if auth and not self.captured_headers.authorization:
                                        self.captured_headers.authorization = auth
                                    if x_browser and not self.captured_headers.x_browser_validation:
                                        self.captured_headers.x_browser_validation = x_browser

                                    # Also capture other headers
                                    if not self.captured_headers.x_browser_channel:
                                        self.captured_headers.x_browser_channel = get_header("x-browser-channel")
                                    if not self.captured_headers.x_browser_copyright:
                                        self.captured_headers.x_browser_copyright = get_header("x-browser-copyright")
                                    if not self.captured_headers.x_browser_year:
                                        self.captured_headers.x_browser_year = get_header("x-browser-year")
                                    if not self.captured_headers.x_client_data:
                                        self.captured_headers.x_client_data = get_header("x-client-data")
                                    if not self.captured_headers.user_agent:
                                        self.captured_headers.user_agent = get_header("User-Agent")
                                    self.captured_headers.timestamp = time.time()

                                    if self.captured_headers.is_valid():
                                        self._log("✅ Captured valid headers!")
                                        return self.captured_headers
                    except:
                        continue

                time.sleep(0.5)

            except Exception as e:
                self._log(f"Error reading logs: {e}")
                time.sleep(1)

        self._log("Timeout waiting for headers")
        return self.captured_headers

    def trigger_api_and_capture(self) -> CapturedHeaders:
        """
        Trigger 1 API call và capture headers.
        Dùng VE3 script giống Chrome mode - inject script và gọi VE3.run()
        """
        if not self.driver:
            return CapturedHeaders()

        self._log("Setting up Fetch intercept for x-browser-validation...")

        try:
            # Enable Fetch domain để intercept requests
            self.driver.execute_cdp_cmd("Fetch.enable", {
                "patterns": [{"urlPattern": "*aisandbox-pa.googleapis.com*"}]
            })
        except Exception as e:
            self._log(f"Fetch.enable error: {e}")

        # === STEP 1: Inject VE3 script (giống Chrome mode) ===
        self._log("Step 1: Inject VE3 automation script...")
        try:
            from pathlib import Path
            script_path = Path(__file__).parent.parent / "scripts" / "ve3_browser_automation.js"
            if script_path.exists():
                with open(script_path, "r", encoding="utf-8") as f:
                    js_code = f.read()
                self.driver.execute_script(js_code)
                self._log("  VE3 script injected!")
            else:
                self._log(f"  Script not found: {script_path}", "error")
                return CapturedHeaders()
        except Exception as e:
            self._log(f"  Inject error: {e}")
            return CapturedHeaders()

        time.sleep(2)

        # === STEP 2: Setup VE3 (tạo project mới) ===
        self._log("Step 2: VE3.setup()...")
        result = self.driver.execute_script("""
            return (async function() {
                if (typeof VE3 === 'undefined') return 'VE3_not_found';
                try {
                    await VE3.setup('header_capture_test');
                    return 'setup_done: ' + (VE3.getProjectUrl() || 'no_url');
                } catch(e) {
                    return 'setup_error: ' + e.message;
                }
            })();
        """)
        self._log(f"  Result: {result}")
        time.sleep(3)

        # === STEP 3: Gọi VE3.run() để trigger API request ===
        self._log("Step 3: VE3.run() to trigger API...")
        self.driver.execute_script("""
            (async function() {
                if (typeof VE3 !== 'undefined') {
                    try {
                        await VE3.run([{
                            sceneId: 'test_capture',
                            prompt: 'a simple red apple on white background'
                        }]);
                    } catch(e) {
                        console.log('VE3.run error:', e);
                    }
                }
            })();
        """)
        self._log("  VE3.run() called, waiting for API request...")

        # Đợi ảnh được tạo - TỐI THIỂU 20 giây để đảm bảo API request được gửi
        self._log("Waiting for image generation (min 20s)...")

        # Poll nhiều lần để capture headers (10 attempts x 3s = 30s max)
        for attempt in range(10):
            time.sleep(3)
            self._log(f"Checking for headers... attempt {attempt + 1}/10")

            try:
                # Get CDP events - look for Fetch.requestPaused
                logs = self.driver.get_log("performance")
                for log in logs:
                    try:
                        msg = json.loads(log["message"])
                        method = msg.get("message", {}).get("method", "")
                        if method == "Fetch.requestPaused":
                            params = msg.get("message", {}).get("params", {})
                            request = params.get("request", {})
                            headers = request.get("headers", {})
                            url = request.get("url", "")

                            self._log(f"[Fetch] Intercepted: {url[:50]}...")
                            self._log(f"[Fetch] Headers count: {len(headers)}")

                            # Show all headers
                            for k, v in headers.items():
                                if 'browser' in k.lower() or 'auth' in k.lower():
                                    self._log(f"   {k}: {str(v)[:40]}...")

                            # Continue the request
                            request_id = params.get("requestId")
                            if request_id:
                                try:
                                    self.driver.execute_cdp_cmd("Fetch.continueRequest", {"requestId": request_id})
                                except:
                                    pass

                            # Extract headers
                            def get_h(name):
                                for k, v in headers.items():
                                    if k.lower() == name.lower():
                                        return v
                                return ""

                            auth = get_h("Authorization")
                            x_browser = get_h("x-browser-validation")

                            if auth or x_browser:
                                self.captured_headers.authorization = auth
                                self.captured_headers.x_browser_validation = x_browser
                                self.captured_headers.timestamp = time.time()

                                if self.captured_headers.is_valid():
                                    self._log("✅ Captured from Fetch intercept!")
                                    return self.captured_headers
                    except:
                        continue
            except Exception as e:
                self._log(f"Fetch capture error: {e}")

            # Check if we already have valid headers from network logs
            if self.captured_headers.is_valid():
                self._log("✅ Headers already captured!")
                return self.captured_headers

        # Fallback to network logs with longer timeout
        self._log("Fallback: trying network logs capture...")
        return self.capture_headers_from_network(timeout=30)

    def get_headers(self) -> CapturedHeaders:
        """Get current captured headers."""
        with self._capture_lock:
            return self.captured_headers

    def stop_browser(self):
        """Đóng browser."""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None


def extract_headers_for_api(chrome_profile: str = None) -> Dict[str, str]:
    """
    Helper function: Mở Chrome, capture headers, trả về dict.

    Usage:
        headers = extract_headers_for_api("path/to/chrome/profile")
        response = requests.post(url, headers=headers, json=payload)
    """
    extractor = ChromeHeadersExtractor(
        chrome_profile_path=chrome_profile,
        headless=False,
        verbose=True
    )

    try:
        if not extractor.start_browser():
            return {}

        if not extractor.navigate_to_flow():
            return {}

        # Wait for page load
        time.sleep(3)

        # Capture headers
        headers = extractor.capture_headers_from_network(timeout=30)

        if headers.is_valid():
            return headers.to_dict()

        # Try trigger API
        headers = extractor.trigger_api_and_capture()

        if headers.is_valid():
            return headers.to_dict()

        return {}

    finally:
        extractor.stop_browser()


if __name__ == "__main__":
    print("=" * 60)
    print("CHROME HEADERS EXTRACTOR - TEST")
    print("=" * 60)

    headers = extract_headers_for_api()

    if headers:
        print("\n✅ Captured headers:")
        for k, v in headers.items():
            print(f"   {k}: {v[:50]}..." if len(str(v)) > 50 else f"   {k}: {v}")
    else:
        print("\n❌ Failed to capture headers")
