"""
VE3 Tool - Browser Image Generator Module
=========================================
Tao anh bang cach dieu khien trinh duyet voi Selenium va JavaScript injection.

Module nay khong su dung API truc tiep ma thao tac tren giao dien web cua Google Flow.
"""

import os
import time
import json
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime

# Browser driver imports - prefer undetected-chromedriver
DRIVER_TYPE = None  # "undetected", "selenium", or None

try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        TimeoutException,
        WebDriverException,
        JavascriptException
    )
    DRIVER_TYPE = "undetected"
except ImportError:
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import (
            TimeoutException,
            WebDriverException,
            JavascriptException
        )
        DRIVER_TYPE = "selenium"
    except ImportError:
        webdriver = None
        By = None
        WebDriverWait = None
        EC = None
        TimeoutException = Exception
        WebDriverException = Exception
        JavascriptException = Exception

SELENIUM_AVAILABLE = DRIVER_TYPE is not None


class BrowserImageGenerator:
    """
    Tao anh bang cach dieu khien trinh duyet.

    Workflow:
    1. Mo trinh duyet va navigate den Google Flow
    2. Inject JavaScript automation script
    3. Goi cac ham JS de tao anh
    4. Lay ket qua va download anh
    """

    FLOW_URL = "https://labs.google/fx/vi/tools/flow"

    def __init__(
        self,
        profile_dir: Optional[str] = None,
        headless: bool = False,
        download_dir: Optional[Path] = None,
        verbose: bool = True
    ):
        """
        Khoi tao BrowserImageGenerator.

        Args:
            profile_dir: Duong dan den Chrome profile (de duy tri session login)
            headless: Chay an (khong hien UI)
            download_dir: Thu muc luu anh download
            verbose: In log chi tiet
        """
        if not SELENIUM_AVAILABLE:
            raise ImportError(
                "Selenium khong duoc cai dat. "
                "Chay: pip install selenium"
            )

        self.profile_dir = profile_dir
        self.headless = headless
        self.download_dir = download_dir or Path.home() / "Downloads" / "ve3_images"
        self.verbose = verbose

        self.driver: Optional[Any] = None
        self._js_injected = False

        # Dam bao thu muc download ton tai
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def _log(self, message: str) -> None:
        """Print log message."""
        if self.verbose:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] [Browser] {message}")

    def _get_js_script(self) -> str:
        """Doc noi dung file JavaScript automation."""
        script_path = Path(__file__).parent.parent / "scripts" / "ve3_browser_automation.js"

        if script_path.exists():
            with open(script_path, "r", encoding="utf-8") as f:
                return f.read()

        # Fallback: Inline minimal script
        self._log("Warning: JS script file not found, using minimal inline version")
        return self._get_minimal_js_script()

    def _get_minimal_js_script(self) -> str:
        """Minimal JS script neu khong tim thay file chinh."""
        return """
        (function() {
            window.VE3_MINIMAL = true;

            window.VE3 = {
                setPrompt: function(prompt) {
                    const textarea = document.querySelector('textarea');
                    if (!textarea) return false;

                    const setter = Object.getOwnPropertyDescriptor(
                        HTMLTextAreaElement.prototype, 'value'
                    ).set;
                    setter.call(textarea, prompt);
                    textarea.dispatchEvent(new Event('input', {bubbles: true}));
                    return true;
                },

                clickGenerate: function() {
                    const buttons = document.querySelectorAll('button');
                    for (const btn of buttons) {
                        if (btn.textContent.includes('Tao') || btn.textContent.includes('Create')) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }
            };

            console.log('VE3 Minimal Script loaded');
        })();
        """

    def start(self) -> bool:
        """
        Khoi dong trinh duyet va inject script.

        Returns:
            True neu thanh cong
        """
        self._log("Khoi dong trinh duyet...")

        try:
            self.driver = self._create_driver()
            self._log("Da khoi dong Chrome")

            # Navigate den Google Flow
            self._log(f"Navigate den: {self.FLOW_URL}")
            self.driver.get(self.FLOW_URL)

            # Cho page load
            time.sleep(5)

            # Inject JS script
            self._inject_js()

            return True

        except Exception as e:
            self._log(f"Loi khoi dong: {e}")
            return False

    def _create_driver(self) -> Any:
        """
        Tao Chrome WebDriver.

        Uu tien su dung undetected-chromedriver de tranh bi Google detect.
        """
        # Download prefs
        prefs = {
            "download.default_directory": str(self.download_dir),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
        }

        if DRIVER_TYPE == "undetected":
            # Undetected-chromedriver (tot nhat)
            self._log("Using undetected-chromedriver")

            options = uc.ChromeOptions()

            if self.profile_dir:
                options.add_argument(f"--user-data-dir={self.profile_dir}")

            if self.headless:
                options.add_argument("--headless=new")
                options.add_argument("--disable-gpu")

            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1920,1080")
            options.add_experimental_option("prefs", prefs)

            driver = uc.Chrome(
                options=options,
                use_subprocess=True,
                version_main=None
            )

            return driver

        else:
            # Fallback: Selenium thuong
            self._log("Using standard selenium")
            from selenium.webdriver.chrome.options import Options

            options = Options()

            if self.profile_dir:
                options.add_argument(f"--user-data-dir={self.profile_dir}")

            if self.headless:
                options.add_argument("--headless=new")

            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)
            options.add_argument("--window-size=1920,1080")
            options.add_experimental_option("prefs", prefs)

            driver = webdriver.Chrome(options=options)

            driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            return driver

    def _inject_js(self) -> None:
        """Inject JavaScript automation script."""
        if self._js_injected:
            return

        self._log("Inject JavaScript script...")
        js_code = self._get_js_script()
        self.driver.execute_script(js_code)
        self._js_injected = True
        self._log("Da inject JS script")

    def stop(self) -> None:
        """Dong trinh duyet."""
        if self.driver:
            self._log("Dong trinh duyet...")
            self.driver.quit()
            self.driver = None
            self._js_injected = False

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()

    def wait_for_login(self, timeout: int = 300) -> bool:
        """
        Cho nguoi dung dang nhap thu cong.

        Args:
            timeout: Thoi gian cho toi da (giay)

        Returns:
            True neu da dang nhap
        """
        self._log(f"Cho dang nhap (timeout: {timeout}s)...")
        self._log("Vui long dang nhap Google account tren trinh duyet")

        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                # Kiem tra co textarea (chi co khi da dang nhap)
                textarea = self.driver.find_element(By.CSS_SELECTOR, "textarea")
                if textarea:
                    self._log("Da phat hien dang nhap thanh cong!")
                    return True
            except:
                pass

            time.sleep(2)

        self._log("Timeout - chua dang nhap")
        return False

    def generate_image(
        self,
        prompt: str,
        wait_timeout: int = 90,
        download: bool = True
    ) -> Tuple[bool, List[str], str]:
        """
        Tao anh tu prompt.

        Args:
            prompt: Prompt mo ta anh
            wait_timeout: Thoi gian cho (giay)
            download: Tu dong download anh

        Returns:
            Tuple[success, list_of_urls, error_message]
        """
        if not self.driver:
            return False, [], "Trinh duyet chua khoi dong"

        # Dam bao JS da inject
        self._inject_js()

        self._log(f"Tao anh: {prompt[:50]}...")

        try:
            # Goi ham JS generateOne
            download_str = "true" if download else "false"
            result = self.driver.execute_async_script(f"""
                const callback = arguments[arguments.length - 1];

                VE3.generateOne("{self._escape_js_string(prompt)}", {{
                    download: {download_str}
                }}).then(result => {{
                    callback(result);
                }}).catch(error => {{
                    callback({{ success: false, error: error.message }});
                }});
            """)

            if result.get("success"):
                images = result.get("images", [])
                urls = [img.get("url") for img in images if img.get("url")]
                self._log(f"Thanh cong: {len(urls)} anh")
                return True, urls, ""
            else:
                error = result.get("error", "Unknown error")
                self._log(f"That bai: {error}")
                return False, [], error

        except JavascriptException as e:
            self._log(f"JS Error: {e}")
            return False, [], str(e)
        except TimeoutException:
            self._log("Timeout")
            return False, [], "Timeout"
        except Exception as e:
            self._log(f"Error: {e}")
            return False, [], str(e)

    def generate_batch(
        self,
        prompts: List[str],
        prefix: str = "ve3",
        download: bool = True,
        continue_on_error: bool = True
    ) -> Dict[str, Any]:
        """
        Tao nhieu anh tu danh sach prompts.

        Args:
            prompts: Danh sach prompts
            prefix: Prefix cho ten file
            download: Tu dong download
            continue_on_error: Tiep tuc khi gap loi

        Returns:
            Dict voi ket qua
        """
        if not self.driver:
            return {"success": False, "error": "Trinh duyet chua khoi dong"}

        self._inject_js()

        self._log(f"Bat dau tao {len(prompts)} anh...")

        try:
            # Chuyen prompts sang JSON
            prompts_json = json.dumps(prompts)

            result = self.driver.execute_async_script(f"""
                const callback = arguments[arguments.length - 1];

                VE3.generateBatch({prompts_json}, {{
                    prefix: "{prefix}",
                    download: {str(download).lower()},
                    continueOnError: {str(continue_on_error).lower()}
                }}).then(result => {{
                    callback(result);
                }}).catch(error => {{
                    callback({{ success: false, error: error.message }});
                }});
            """)

            self._log(f"Hoan thanh: {result.get('successCount', 0)} thanh cong, "
                     f"{result.get('failedCount', 0)} that bai")

            return result

        except Exception as e:
            self._log(f"Batch error: {e}")
            return {"success": False, "error": str(e)}

    def _escape_js_string(self, s: str) -> str:
        """Escape chuoi de dung trong JavaScript."""
        return (s
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("'", "\\'")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t"))


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def create_browser_generator(
    profile_dir: Optional[str] = None,
    verbose: bool = True
) -> BrowserImageGenerator:
    """
    Factory function de tao BrowserImageGenerator.

    Args:
        profile_dir: Chrome profile directory
        verbose: Enable verbose logging

    Returns:
        BrowserImageGenerator instance
    """
    return BrowserImageGenerator(
        profile_dir=profile_dir,
        verbose=verbose
    )


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import sys

    print("""
+============================================================+
|       BROWSER IMAGE GENERATOR - VE3 TOOL                   |
+============================================================+
|  Tao anh bang cach dieu khien trinh duyet                  |
|                                                            |
|  Usage:                                                    |
|    python browser_image_generator.py "prompt"              |
|    python browser_image_generator.py --batch prompts.txt   |
+============================================================+
""")

    if not SELENIUM_AVAILABLE:
        print("Error: Selenium chua duoc cai dat")
        print("Chay: pip install selenium")
        sys.exit(1)

    if len(sys.argv) < 2:
        print("Vui long cung cap prompt hoac file prompts")
        sys.exit(1)

    # Single prompt
    if sys.argv[1] != "--batch":
        prompt = sys.argv[1]

        with BrowserImageGenerator(verbose=True) as generator:
            print("\nVui long dang nhap Google account tren trinh duyet...")
            if generator.wait_for_login(timeout=120):
                success, urls, error = generator.generate_image(prompt)
                if success:
                    print(f"\nThanh cong! URLs:")
                    for url in urls:
                        print(f"  {url}")
                else:
                    print(f"\nThat bai: {error}")

    # Batch mode
    else:
        if len(sys.argv) < 3:
            print("Vui long cung cap file prompts")
            sys.exit(1)

        prompts_file = Path(sys.argv[2])
        if not prompts_file.exists():
            print(f"File khong ton tai: {prompts_file}")
            sys.exit(1)

        with open(prompts_file, "r", encoding="utf-8") as f:
            prompts = [line.strip() for line in f if line.strip()]

        print(f"Da doc {len(prompts)} prompts")

        with BrowserImageGenerator(verbose=True) as generator:
            print("\nVui long dang nhap Google account tren trinh duyet...")
            if generator.wait_for_login(timeout=120):
                result = generator.generate_batch(prompts)
                print(f"\nKet qua:")
                print(f"  Thanh cong: {result.get('successCount', 0)}")
                print(f"  That bai: {result.get('failedCount', 0)}")
