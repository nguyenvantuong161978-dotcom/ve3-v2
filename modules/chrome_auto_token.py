"""
VE3 Tool - Chrome Auto Token Extractor v2
==========================================
Tu dong 100% lay Bearer Token tu Google Flow.
Ho tro chay an (headless) khi da co Project ID.
"""

import json
import os
import shutil
import tempfile
import time
import threading
from pathlib import Path
from typing import Optional, Tuple, Callable
from datetime import datetime


class ChromeAutoToken:
    """
    Tu dong lay Bearer Token tu Google Flow.
    
    Features:
    - Copy Chrome profile de tranh xung dot
    - Tu dong tao project hoac dung project co san
    - Tu dong click chuyen sang mode tao anh
    - Capture token tu network requests
    - Ho tro headless mode
    """
    
    FLOW_URL = "https://labs.google/fx/vi/tools/flow"
    
    def __init__(
        self,
        chrome_path: str = None,
        profile_path: str = None,
        headless: bool = False,
        timeout: int = 60
    ):
        self.chrome_path = chrome_path or r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        self.profile_path = profile_path
        self.headless = headless
        self.timeout = timeout
        
        self.driver = None
        self.temp_profile_dir = None
        self.bearer_token = None
        self.project_id = None
    
    def _copy_profile(self) -> str:
        """Copy Chrome profile sang thu muc tam."""
        if not self.profile_path or not Path(self.profile_path).exists():
            return None
        
        # Tao thu muc tam
        self.temp_profile_dir = tempfile.mkdtemp(prefix="ve3_chrome_")
        
        # Copy cac file quan trong
        src = Path(self.profile_path)
        dst = Path(self.temp_profile_dir) / "Profile"
        dst.mkdir(parents=True, exist_ok=True)
        
        important_files = [
            "Cookies", "Login Data", "Web Data", 
            "Preferences", "Secure Preferences",
            "Local State"
        ]
        
        for item in important_files:
            src_path = src / item
            if src_path.exists():
                try:
                    if src_path.is_file():
                        shutil.copy2(src_path, dst / item)
                    else:
                        shutil.copytree(src_path, dst / item, dirs_exist_ok=True)
                except Exception as e:
                    print(f"Warning: Could not copy {item}: {e}")
        
        # Copy Network folder (chua cookies moi)
        network_src = src / "Network"
        if network_src.exists():
            try:
                shutil.copytree(network_src, dst / "Network", dirs_exist_ok=True)
            except:
                pass
        
        return self.temp_profile_dir
    
    def _create_driver(self, use_temp_profile: bool = True):
        """Tao Chrome WebDriver voi anti-detection."""

        # Prioritize undetected-chromedriver (best anti-detection)
        try:
            import undetected_chromedriver as uc
            self._create_driver_undetected(uc, use_temp_profile)
            return
        except ImportError:
            pass

        # Fallback to selenium with stealth
        self._create_driver_selenium(use_temp_profile)

    def _create_driver_undetected(self, uc, use_temp_profile: bool = True):
        """Tao driver voi undetected-chromedriver."""
        options = uc.ChromeOptions()

        # Profile
        if use_temp_profile and self.profile_path:
            temp_dir = self._copy_profile()
            if temp_dir:
                options.add_argument(f"--user-data-dir={temp_dir}")
                options.add_argument("--profile-directory=Profile")

        # Chrome binary
        if self.chrome_path and Path(self.chrome_path).exists():
            options.binary_location = self.chrome_path

        # Headless
        if self.headless:
            options.add_argument("--headless=new")

        # NOTE: Removed goog:loggingPrefs - it's a strong fingerprint!
        # Will use JavaScript injection to capture tokens instead

        # Anti-detection flags
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1400,900")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-popup-blocking")

        # QUAN TRỌNG: Đảm bảo Chrome chạy riêng biệt, không reuse process
        options.add_argument("--no-first-run")
        options.add_argument("--new-window")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-features=ChromeWhatsNewUI")

        # Disable images in headless for speed
        if self.headless:
            prefs = {"profile.managed_default_content_settings.images": 2}
            options.add_experimental_option("prefs", prefs)

        self.driver = uc.Chrome(
            options=options,
            use_subprocess=True,
            version_main=None
        )

        # Setup CDP for network interception (more stealthy)
        self._setup_cdp_network_capture()

        # Inject stealth scripts
        self._inject_stealth_scripts()

    def _create_driver_selenium(self, use_temp_profile: bool = True):
        """Fallback: Tao driver voi Selenium + stealth."""
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options

        options = Options()

        # Profile
        if use_temp_profile and self.profile_path:
            temp_dir = self._copy_profile()
            if temp_dir:
                options.add_argument(f"--user-data-dir={temp_dir}")
                options.add_argument("--profile-directory=Profile")

        # Chrome binary
        if self.chrome_path and Path(self.chrome_path).exists():
            options.binary_location = self.chrome_path

        # Headless
        if self.headless:
            options.add_argument("--headless=new")

        # NOTE: Removed goog:loggingPrefs - it's a strong fingerprint!

        # === ANTI-DETECTION FLAGS ===
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1400,900")

        # Key anti-detection flags
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--allow-running-insecure-content")

        # Hide automation indicators
        options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        options.add_experimental_option("useAutomationExtension", False)

        # QUAN TRỌNG: Đảm bảo Chrome chạy riêng biệt, không reuse process
        options.add_argument("--no-first-run")
        options.add_argument("--new-window")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-features=ChromeWhatsNewUI")

        # Disable images in headless for speed
        if self.headless:
            prefs = {"profile.managed_default_content_settings.images": 2}
            options.add_experimental_option("prefs", prefs)

        # Get chromedriver
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
        except:
            service = Service()

        self.driver = webdriver.Chrome(service=service, options=options)

        # Setup CDP for network interception (more stealthy)
        self._setup_cdp_network_capture()

        # Inject stealth scripts
        self._inject_stealth_scripts()

    def _setup_cdp_network_capture(self):
        """Setup CDP network capture without using loggingPrefs."""
        # Enable Network domain
        self.driver.execute_cdp_cmd("Network.enable", {})

        # Inject JavaScript to intercept fetch/XHR and capture Authorization headers
        intercept_js = """
        window.__ve3_captured_tokens__ = [];

        // Intercept fetch
        const originalFetch = window.fetch;
        window.fetch = function(...args) {
            const [url, options] = args;
            if (url && url.includes('aisandbox-pa.googleapis.com') && url.includes('flowMedia')) {
                const headers = options?.headers || {};
                const auth = headers['Authorization'] || headers['authorization'];
                if (auth && auth.startsWith('Bearer ')) {
                    window.__ve3_captured_tokens__.push({
                        token: auth.substring(7),
                        url: url,
                        timestamp: Date.now()
                    });
                }
            }
            return originalFetch.apply(this, args);
        };

        // Intercept XMLHttpRequest
        const originalXHROpen = XMLHttpRequest.prototype.open;
        const originalXHRSetHeader = XMLHttpRequest.prototype.setRequestHeader;

        XMLHttpRequest.prototype.open = function(method, url) {
            this.__ve3_url__ = url;
            return originalXHROpen.apply(this, arguments);
        };

        XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
            if (this.__ve3_url__ &&
                this.__ve3_url__.includes('aisandbox-pa.googleapis.com') &&
                this.__ve3_url__.includes('flowMedia') &&
                (name.toLowerCase() === 'authorization') &&
                value.startsWith('Bearer ')) {
                window.__ve3_captured_tokens__.push({
                    token: value.substring(7),
                    url: this.__ve3_url__,
                    timestamp: Date.now()
                });
            }
            return originalXHRSetHeader.apply(this, arguments);
        };
        """
        try:
            self.driver.execute_script(intercept_js)
        except Exception:
            pass

    def _inject_stealth_scripts(self):
        """Inject JavaScript to hide automation fingerprints."""
        stealth_js = """
        // Override navigator.webdriver
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });

        // Override navigator.plugins (non-empty)
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });

        // Override navigator.languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en', 'vi']
        });

        // Override permissions query
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );

        // Override Chrome automation detection
        window.chrome = {
            runtime: {}
        };

        // Remove automation-related properties
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
        """
        try:
            self.driver.execute_script(stealth_js)
        except Exception:
            pass
    
    def _wait_for_element(self, by, value, timeout=10, clickable=False):
        """Doi element xuat hien."""
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        
        condition = EC.element_to_be_clickable if clickable else EC.presence_of_element_located
        return WebDriverWait(self.driver, timeout).until(condition((by, value)))
    
    def _extract_token_from_logs(self) -> Tuple[Optional[str], Optional[str]]:
        """Extract Bearer Token tu JavaScript captured tokens."""
        try:
            # Get tokens captured by JavaScript injection
            tokens = self.driver.execute_script("return window.__ve3_captured_tokens__ || [];")

            if tokens and len(tokens) > 0:
                # Get the latest token
                latest = tokens[-1]
                self.bearer_token = latest.get("token")
                url = latest.get("url", "")

                # Extract project ID from URL
                if "/projects/" in url:
                    parts = url.split("/projects/")[1]
                    self.project_id = parts.split("/")[0]

                if self.bearer_token:
                    return self.bearer_token, self.project_id

        except Exception:
            pass

        return None, None
    
    def _navigate_to_flow(self, project_id: str = None):
        """Navigate den Flow."""
        if project_id:
            url = f"https://labs.google/fx/vi/tools/flow/project/{project_id}"
        else:
            url = self.FLOW_URL

        self.driver.get(url)
        time.sleep(3)

        # Re-inject token capture script after navigation (script is lost on page load)
        self._setup_cdp_network_capture()
        self._inject_stealth_scripts()
    
    def _click_new_project(self) -> bool:
        """Click nut Du an moi."""
        from selenium.webdriver.common.by import By
        
        try:
            # Tim nut Du an moi
            selectors = [
                "//span[contains(text(), 'Dự án mới')]/..",
                "//button[contains(., 'Dự án mới')]",
                "//div[contains(text(), 'Dự án mới')]/..",
                "//*[contains(text(), '+ Dự án mới')]",
            ]
            
            for sel in selectors:
                try:
                    btn = self._wait_for_element(By.XPATH, sel, timeout=5, clickable=True)
                    btn.click()
                    time.sleep(2)
                    return True
                except:
                    continue
            
            return False
        except:
            return False
    
    def _switch_to_image_mode(self) -> bool:
        """Chuyen sang che do Tao hinh anh."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        
        try:
            # Click dropdown "Tu van ban sang video"
            dropdown_selectors = [
                "//button[contains(., 'Từ văn bản sang video')]",
                "//span[contains(text(), 'Từ văn bản sang video')]/..",
                "//button[@role='combobox']",
            ]
            
            for sel in dropdown_selectors:
                try:
                    dropdown = self._wait_for_element(By.XPATH, sel, timeout=5, clickable=True)
                    dropdown.click()
                    time.sleep(1)
                    break
                except:
                    continue
            
            # Click "Tao hinh anh"
            image_selectors = [
                "//div[contains(text(), 'Tạo hình ảnh')]",
                "//span[contains(text(), 'Tạo hình ảnh')]",
                "//*[contains(text(), 'Tạo hình ảnh')]",
            ]
            
            for sel in image_selectors:
                try:
                    btn = self._wait_for_element(By.XPATH, sel, timeout=3, clickable=True)
                    btn.click()
                    time.sleep(2)
                    return True
                except:
                    continue
            
            return False
        except:
            return False
    
    def _send_test_prompt(self) -> bool:
        """Gui prompt test de capture token."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        
        try:
            # Tim textarea
            textarea = self._wait_for_element(
                By.ID, "PINHOLE_TEXT_AREA_ELEMENT_ID", timeout=10
            )
            
            # Clear va gui prompt
            textarea.clear()
            textarea.send_keys("test image generation")
            time.sleep(0.5)
            textarea.send_keys(Keys.RETURN)
            
            return True
        except Exception as e:
            print(f"Send prompt error: {e}")
            
            # Fallback: tim textarea khac
            try:
                textarea = self._wait_for_element(By.TAG_NAME, "textarea", timeout=5)
                textarea.clear()
                textarea.send_keys("test")
                textarea.send_keys(Keys.RETURN)
                return True
            except:
                return False
    
    def _check_login(self) -> bool:
        """Kiem tra da dang nhap chua."""
        current_url = self.driver.current_url
        return "accounts.google.com" not in current_url
    
    def _wait_for_login(self, callback: Callable = None, timeout: int = 120):
        """Doi user dang nhap."""
        if callback:
            callback("Vui long dang nhap Google trong cua so Chrome...")
        
        start = time.time()
        while time.time() - start < timeout:
            if self._check_login():
                return True
            time.sleep(2)
        
        return False
    
    def extract_token(
        self,
        project_id: str = None,
        callback: Callable = None
    ) -> Tuple[Optional[str], Optional[str], str]:
        """
        Lay Bearer Token.
        
        Args:
            project_id: Project ID co san (neu co se dung, neu khong se tao moi)
            callback: Function(message) de cap nhat progress
            
        Returns:
            Tuple[bearer_token, project_id, error_message]
        """
        error = ""
        
        try:
            if callback:
                callback("Dang khoi dong Chrome...")
            
            self._create_driver(use_temp_profile=True)
            
            if callback:
                callback("Dang mo Google Flow...")
            
            # Navigate
            self._navigate_to_flow(project_id)
            
            # Check login
            if not self._check_login():
                if self.headless:
                    return None, None, "Can dang nhap! Hay tat che do an hoac dang nhap truoc."
                
                if callback:
                    callback("Can dang nhap Google...")
                
                if not self._wait_for_login(callback):
                    return None, None, "Timeout cho dang nhap"
                
                # Re-navigate after login
                time.sleep(2)
                self._navigate_to_flow(project_id)
            
            time.sleep(3)
            
            # Neu khong co project_id, tao moi
            if not project_id:
                if callback:
                    callback("Dang tao project moi...")
                
                self._click_new_project()
                time.sleep(2)
                
                # Lay project_id tu URL
                current_url = self.driver.current_url
                if "/project/" in current_url:
                    project_id = current_url.split("/project/")[1].split("/")[0].split("?")[0]
                    self.project_id = project_id
            
            # Chuyen sang mode tao anh
            if callback:
                callback("Dang chuyen sang che do tao anh...")
            
            self._switch_to_image_mode()
            time.sleep(2)
            
            # Gui prompt de capture token
            if callback:
                callback("Dang capture token...")
            
            self._send_test_prompt()
            
            # Cho va capture token
            start_time = time.time()
            while time.time() - start_time < self.timeout:
                token, pid = self._extract_token_from_logs()
                if token:
                    if callback:
                        callback("Da lay duoc token!")
                    return token, pid or project_id, ""
                time.sleep(1)
            
            error = "Khong capture duoc token. Vui long thu lai."
            
        except ImportError as e:
            error = f"Thieu thu vien: {e}\nChay: pip install selenium webdriver-manager"
        except Exception as e:
            error = f"Loi: {str(e)}"
        finally:
            self._cleanup()
        
        return None, None, error
    
    def _cleanup(self):
        """Don dep - ĐÓNG TRÌNH DUYỆT và xóa temp profile."""
        print("[ChromeAutoToken] Đang đóng trình duyệt...")

        if self.driver:
            try:
                # Đóng tất cả tabs trước
                try:
                    self.driver.close()
                except:
                    pass

                # Quit để đóng hoàn toàn
                self.driver.quit()
                print("[ChromeAutoToken] ✓ Đã đóng trình duyệt")
            except Exception as e:
                print(f"[ChromeAutoToken] Lỗi khi đóng: {e}")
            finally:
                self.driver = None

        # Chờ một chút để Chrome process thoát hoàn toàn
        import time
        time.sleep(1)

        if self.temp_profile_dir and Path(self.temp_profile_dir).exists():
            try:
                shutil.rmtree(self.temp_profile_dir, ignore_errors=True)
                print(f"[ChromeAutoToken] ✓ Đã xóa temp profile: {self.temp_profile_dir}")
            except:
                pass
            self.temp_profile_dir = None
    
    def extract_token_async(
        self,
        project_id: str = None,
        callback: Callable = None,
        on_complete: Callable = None
    ):
        """
        Lay token trong background thread.
        
        Args:
            project_id: Project ID (optional)
            callback: Function(message) cap nhat progress
            on_complete: Function(token, project_id, error) khi xong
        """
        def worker():
            token, pid, error = self.extract_token(project_id, callback)
            if on_complete:
                on_complete(token, pid, error)
        
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return thread


class TokenManager:
    """
    Quan ly nhieu tokens va project IDs.
    """
    
    def __init__(self):
        self.tokens = []  # List of (token, project_id, timestamp)
        self.current_index = 0
    
    def add_token(self, token: str, project_id: str = None):
        """Them token moi."""
        self.tokens.append({
            "token": token,
            "project_id": project_id,
            "timestamp": datetime.now(),
            "used_count": 0
        })
    
    def get_next_token(self) -> Tuple[Optional[str], Optional[str]]:
        """Lay token tiep theo (round-robin)."""
        if not self.tokens:
            return None, None
        
        token_info = self.tokens[self.current_index]
        token_info["used_count"] += 1
        
        # Move to next
        self.current_index = (self.current_index + 1) % len(self.tokens)
        
        return token_info["token"], token_info["project_id"]
    
    def get_valid_token(self) -> Tuple[Optional[str], Optional[str]]:
        """Lay token con hieu luc (duoi 50 phut)."""
        now = datetime.now()
        
        for token_info in self.tokens:
            age = (now - token_info["timestamp"]).total_seconds()
            if age < 3000:  # 50 phut
                return token_info["token"], token_info["project_id"]
        
        return None, None
    
    def remove_expired(self):
        """Xoa cac token het han."""
        now = datetime.now()
        self.tokens = [
            t for t in self.tokens
            if (now - t["timestamp"]).total_seconds() < 3600
        ]
        
        if self.current_index >= len(self.tokens):
            self.current_index = 0
    
    def count(self) -> int:
        return len(self.tokens)


if __name__ == "__main__":
    import sys
    
    print("Chrome Auto Token Test")
    print("=" * 50)
    
    def progress(msg):
        print(f"[Progress] {msg}")
    
    extractor = ChromeAutoToken(
        headless=False  # Hien thi de debug
    )
    
    # Test voi project ID cu the (neu co)
    project_id = sys.argv[1] if len(sys.argv) > 1 else None
    
    token, pid, error = extractor.extract_token(project_id=project_id, callback=progress)
    
    if token:
        print(f"\n✅ Success!")
        print(f"Token: {token[:50]}...")
        print(f"Project ID: {pid}")
    else:
        print(f"\n❌ Failed: {error}")
