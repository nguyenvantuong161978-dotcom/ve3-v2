"""
VE3 Tool - Flows Lab Automation Module
======================================
Web automation để tạo ảnh và video trên Flows Lab sử dụng Selenium.

LƯU Ý: Các selector trong module này là TEMPLATE và cần được chỉnh sửa
cho phù hợp với UI thực tế của Flows Lab.

Module này yêu cầu selenium. Nếu không cài đặt, các class sẽ không hoạt động
nhưng không gây lỗi import.
"""

import time
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

# Optional selenium imports
SELENIUM_AVAILABLE = False
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        TimeoutException,
        NoSuchElementException,
        WebDriverException
    )
    SELENIUM_AVAILABLE = True
except ImportError:
    # Create dummy classes for when selenium is not installed
    webdriver = None
    By = None
    Keys = None
    WebDriverWait = None
    EC = None
    TimeoutException = Exception
    NoSuchElementException = Exception
    WebDriverException = Exception

from modules.utils import get_logger, sanitize_filename
from modules.excel_manager import Scene


# ============================================================================
# ACCOUNT MANAGER
# ============================================================================

class Account:
    """Đại diện cho một tài khoản Flows Lab."""
    
    def __init__(
        self,
        account_name: str,
        email: str,
        password: str,
        profile_dir: Optional[str] = None,
        cookies_file: Optional[str] = None,
        active: bool = True
    ):
        self.account_name = account_name
        self.email = email
        self.password = password
        self.profile_dir = profile_dir
        self.cookies_file = cookies_file
        self.active = active
        self.scenes_processed = 0
    
    def __repr__(self):
        return f"Account({self.account_name}, active={self.active})"


class AccountManager:
    """
    Quản lý danh sách tài khoản từ file CSV.
    """
    
    def __init__(self, csv_path: Path):
        """
        Khởi tạo AccountManager.
        
        Args:
            csv_path: Path đến file accounts.csv
        """
        self.csv_path = Path(csv_path)
        self.accounts: List[Account] = []
        self.current_index = 0
        self.logger = get_logger("account_manager")
        
        self._load_accounts()
    
    def _load_accounts(self) -> None:
        """Load danh sách tài khoản từ CSV."""
        if not self.csv_path.exists():
            self.logger.warning(f"Accounts file not found: {self.csv_path}")
            return
        
        import csv
        
        with open(self.csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                # Skip dòng trống
                if not row or not row.get("account_name"):
                    continue
                
                # Xử lý giá trị active an toàn
                active_value = row.get("active", "true")
                if active_value is None:
                    active_value = "true"
                active = active_value.lower().strip() == "true"
                
                account = Account(
                    account_name=row.get("account_name", ""),
                    email=row.get("email", ""),
                    password=row.get("password", ""),
                    profile_dir=row.get("profile_dir") or None,
                    cookies_file=row.get("cookies_file") or None,
                    active=active
                )
                
                self.accounts.append(account)
        
        self.logger.info(f"Loaded {len(self.accounts)} accounts, {self.get_active_count()} active")
    
    def get_active_accounts(self) -> List[Account]:
        """Lấy danh sách tài khoản đang active."""
        return [a for a in self.accounts if a.active]
    
    def get_active_count(self) -> int:
        """Đếm số tài khoản active."""
        return len(self.get_active_accounts())
    
    def get_next_active_account(self) -> Optional[Account]:
        """
        Lấy tài khoản tiếp theo để sử dụng.
        
        Returns:
            Account tiếp theo hoặc None nếu không còn
        """
        active_accounts = self.get_active_accounts()
        
        if not active_accounts:
            return None
        
        if self.current_index >= len(active_accounts):
            self.current_index = 0  # Reset về đầu
        
        account = active_accounts[self.current_index]
        self.current_index += 1
        
        return account
    
    def reset_scene_counts(self) -> None:
        """Reset số scenes đã xử lý của tất cả accounts."""
        for account in self.accounts:
            account.scenes_processed = 0


# ============================================================================
# SELENIUM DRIVER FACTORY
# ============================================================================

class DriverFactory:
    """
    Factory để tạo Selenium WebDriver.
    Yêu cầu selenium được cài đặt.
    """
    
    @staticmethod
    def create_driver(
        browser: str = "chrome",
        profile_dir: Optional[str] = None,
        headless: bool = False
    ) -> Any:
        """
        Tạo WebDriver instance.
        
        Args:
            browser: Loại browser ("chrome" hoặc "edge")
            profile_dir: Path đến Chrome profile (nếu có)
            headless: Chạy ẩn không hiện UI
            
        Returns:
            WebDriver instance
            
        Raises:
            ImportError: Nếu selenium không được cài đặt
        """
        if not SELENIUM_AVAILABLE:
            raise ImportError(
                "Selenium không được cài đặt. "
                "Chạy: pip install selenium webdriver-manager"
            )
        
        if browser.lower() == "chrome":
            return DriverFactory._create_chrome_driver(profile_dir, headless)
        elif browser.lower() == "edge":
            return DriverFactory._create_edge_driver(profile_dir, headless)
        else:
            raise ValueError(f"Unsupported browser: {browser}")
    
    @staticmethod
    def _create_chrome_driver(
        profile_dir: Optional[str] = None,
        headless: bool = False
    ) -> Any:
        """Tạo Chrome WebDriver."""
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        
        options = Options()
        
        if profile_dir:
            options.add_argument(f"--user-data-dir={profile_dir}")
        
        if headless:
            options.add_argument("--headless=new")
        
        # Các options phổ biến
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        
        # Disable download prompt
        prefs = {
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True
        }
        options.add_experimental_option("prefs", prefs)
        
        try:
            driver = webdriver.Chrome(options=options)
            driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            return driver
        except WebDriverException as e:
            raise RuntimeError(f"Failed to create Chrome driver: {e}")
    
    @staticmethod
    def _create_edge_driver(
        profile_dir: Optional[str] = None,
        headless: bool = False
    ) -> Any:
        """Tạo Edge WebDriver."""
        from selenium.webdriver.edge.options import Options
        
        options = Options()
        
        if profile_dir:
            options.add_argument(f"--user-data-dir={profile_dir}")
        
        if headless:
            options.add_argument("--headless=new")
        
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        
        try:
            return webdriver.Edge(options=options)
        except WebDriverException as e:
            raise RuntimeError(f"Failed to create Edge driver: {e}")


# ============================================================================
# FLOWS LAB CLIENT
# ============================================================================

class FlowsLabClient:
    """
    Client để tự động hóa Flows Lab.
    
    LƯU Ý: Các selector trong class này là TEMPLATE.
    Bạn cần chỉnh lại cho phù hợp với UI thực tế của Flows Lab.
    
    TODO markers chỉ ra những chỗ cần chỉnh sửa.
    """
    
    def __init__(
        self,
        account: Account,
        settings: Dict[str, Any],
        download_dir: Optional[Path] = None
    ):
        """
        Khởi tạo FlowsLabClient.
        
        Args:
            account: Account object
            settings: Dictionary cấu hình
            download_dir: Thư mục để lưu file download
        """
        self.account = account
        self.settings = settings
        self.download_dir = download_dir or Path.home() / "Downloads"
        self.logger = get_logger("flowslab_client")
        
        self.base_url = settings.get("flowslab_base_url", "https://app.flowslab.io")
        self.wait_timeout = settings.get("wait_timeout", 30)
        self.retry_count = settings.get("retry_count", 3)
        
        self.driver: Optional[Any] = None
        self._is_logged_in = False
    
    def start(self) -> None:
        """Khởi động browser và driver."""
        self.logger.info(f"Starting browser for account: {self.account.account_name}")
        
        self.driver = DriverFactory.create_driver(
            browser=self.settings.get("browser", "chrome"),
            profile_dir=self.account.profile_dir,
            headless=False  # Nên để False khi develop/debug
        )
        
        # Set download directory
        # TODO: Cấu hình download directory tùy browser
    
    def stop(self) -> None:
        """Đóng browser."""
        if self.driver:
            self.logger.info("Closing browser")
            self.driver.quit()
            self.driver = None
            self._is_logged_in = False
    
    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
    
    # ========================================================================
    # LOGIN METHODS
    # ========================================================================
    
    def login_if_needed(self) -> bool:
        """
        Login vào Flows Lab nếu chưa login.
        
        Returns:
            True nếu đã login thành công
        """
        if self._is_logged_in:
            return True
        
        if self.driver is None:
            self.start()
        
        self.logger.info(f"Navigating to {self.base_url}")
        self.driver.get(self.base_url)
        
        time.sleep(3)  # Chờ page load
        
        # Kiểm tra đã login chưa (dựa vào element nào đó)
        if self._check_if_logged_in():
            self.logger.info("Already logged in")
            self._is_logged_in = True
            return True
        
        # Thực hiện login
        self.logger.info(f"Logging in as {self.account.email}")
        
        try:
            self._perform_login()
            self._is_logged_in = True
            return True
        except Exception as e:
            self.logger.error(f"Login failed: {e}")
            return False
    
    def _check_if_logged_in(self) -> bool:
        """
        Kiểm tra xem đã login chưa.
        
        TODO: Chỉnh selector để detect trạng thái login
        """
        try:
            # TODO: Chỉnh selector này - tìm element chỉ hiện khi đã login
            # Ví dụ: avatar, dashboard link, user menu, etc.
            self.driver.find_element(
                By.CSS_SELECTOR,
                "div.user-avatar, button.user-menu, [data-testid='user-profile']"
            )
            return True
        except NoSuchElementException:
            return False
    
    def _perform_login(self) -> None:
        """
        Thực hiện login.
        
        TODO: Chỉnh toàn bộ logic và selector cho phù hợp với Flows Lab
        """
        wait = WebDriverWait(self.driver, self.wait_timeout)
        
        # TODO: Tìm và click nút Login nếu cần
        # login_btn = wait.until(EC.element_to_be_clickable(
        #     (By.CSS_SELECTOR, "a[href*='login'], button.login-btn")
        # ))
        # login_btn.click()
        
        # TODO: Chỉnh selector cho email input
        email_input = wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "input[type='email'], input[name='email'], #email")
        ))
        email_input.clear()
        email_input.send_keys(self.account.email)
        
        # TODO: Chỉnh selector cho password input
        password_input = self.driver.find_element(
            By.CSS_SELECTOR, "input[type='password'], input[name='password'], #password"
        )
        password_input.clear()
        password_input.send_keys(self.account.password)
        
        # TODO: Chỉnh selector cho submit button
        submit_btn = self.driver.find_element(
            By.CSS_SELECTOR, "button[type='submit'], button.login-submit, input[type='submit']"
        )
        submit_btn.click()
        
        # Chờ login hoàn tất
        time.sleep(5)
        
        # Verify login thành công
        if not self._check_if_logged_in():
            raise RuntimeError("Login verification failed")
        
        self.logger.info("Login successful")
    
    # ========================================================================
    # PROJECT METHODS
    # ========================================================================
    
    def open_project_or_create(self, project_name: str) -> bool:
        """
        Mở project có sẵn hoặc tạo mới.
        
        TODO: Implement logic tạo/mở project trên Flows Lab
        
        Args:
            project_name: Tên project
            
        Returns:
            True nếu thành công
        """
        self.logger.info(f"Opening/creating project: {project_name}")
        
        # TODO: Implement project navigation
        # Ví dụ:
        # 1. Navigate đến trang projects
        # 2. Tìm project theo tên
        # 3. Nếu có thì click vào, nếu không thì tạo mới
        
        return True
    
    # ========================================================================
    # IMAGE GENERATION METHODS
    # ========================================================================
    
    def create_image_from_prompt(
        self,
        prompt: str,
        reference_image: Optional[Path] = None,
        out_dir: Path = None
    ) -> Optional[Path]:
        """
        Tạo ảnh từ prompt trên Flows Lab.
        
        TODO: Chỉnh toàn bộ logic và selector cho phù hợp với UI của Flows Lab
        
        Args:
            prompt: Prompt mô tả ảnh
            reference_image: Ảnh tham chiếu (nếu có)
            out_dir: Thư mục lưu ảnh output
            
        Returns:
            Path đến ảnh đã tạo, hoặc None nếu thất bại
        """
        if not self.login_if_needed():
            return None
        
        self.logger.info("Creating image from prompt...")
        
        wait = WebDriverWait(self.driver, self.wait_timeout)
        
        try:
            # TODO: Navigate đến trang tạo ảnh
            # self.driver.get(f"{self.base_url}/generate/image")
            # time.sleep(2)
            
            # TODO: Upload reference image nếu có
            if reference_image and reference_image.exists():
                # TODO: Tìm input file upload và upload ảnh
                # file_input = self.driver.find_element(
                #     By.CSS_SELECTOR, "input[type='file'].reference-upload"
                # )
                # file_input.send_keys(str(reference_image))
                # time.sleep(2)
                pass
            
            # TODO: Nhập prompt
            # Chỉnh selector cho textarea prompt
            prompt_input = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "textarea.prompt-input, textarea[name='prompt'], #prompt-textarea")
            ))
            prompt_input.clear()
            prompt_input.send_keys(prompt)
            
            # TODO: Click nút Generate
            generate_btn = self.driver.find_element(
                By.CSS_SELECTOR, "button.generate-btn, button[type='submit'].generate"
            )
            generate_btn.click()
            
            # TODO: Chờ ảnh được tạo
            # Có thể cần chờ loading indicator biến mất
            # Hoặc chờ ảnh kết quả xuất hiện
            self.logger.info("Waiting for image generation...")
            time.sleep(30)  # TODO: Thay bằng wait condition phù hợp
            
            # TODO: Download ảnh
            # Tìm nút download và click
            # download_btn = wait.until(EC.element_to_be_clickable(
            #     (By.CSS_SELECTOR, "button.download, a.download-link")
            # ))
            # download_btn.click()
            
            # TODO: Chờ file download và move đến out_dir
            # downloaded_file = self._wait_for_download()
            # if downloaded_file and out_dir:
            #     final_path = out_dir / f"img_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            #     shutil.move(downloaded_file, final_path)
            #     return final_path
            
            # Placeholder return
            self.logger.warning("Image generation not fully implemented - returning placeholder")
            return None
            
        except TimeoutException as e:
            self.logger.error(f"Timeout while creating image: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error creating image: {e}")
            return None
    
    def generate_image_for_scene(
        self,
        scene: Scene,
        nv_dir: Path,
        out_dir: Path
    ) -> Optional[Path]:
        """
        Tạo ảnh cho một scene.
        
        Args:
            scene: Scene object
            nv_dir: Thư mục chứa ảnh nhân vật tham chiếu
            out_dir: Thư mục lưu output
            
        Returns:
            Path đến ảnh đã tạo
        """
        # Tìm reference image của nhân vật chính
        nvc_image = nv_dir / "nvc.png"
        reference = nvc_image if nvc_image.exists() else None
        
        for attempt in range(self.retry_count):
            self.logger.info(f"Generating image for scene {scene.scene_id}, attempt {attempt + 1}")
            
            result = self.create_image_from_prompt(
                prompt=scene.img_prompt,
                reference_image=reference,
                out_dir=out_dir
            )
            
            if result:
                return result
            
            if attempt < self.retry_count - 1:
                self.logger.warning(f"Retrying in 10 seconds...")
                time.sleep(10)
        
        return None
    
    # ========================================================================
    # VIDEO GENERATION METHODS
    # ========================================================================
    
    def create_video_from_prompt(
        self,
        prompt: str,
        source_image: Path,
        out_dir: Path
    ) -> Optional[Path]:
        """
        Tạo video từ ảnh và prompt.
        
        TODO: Chỉnh toàn bộ logic và selector cho phù hợp với UI của Flows Lab
        
        Args:
            prompt: Prompt mô tả chuyển động video
            source_image: Ảnh nguồn
            out_dir: Thư mục lưu video output
            
        Returns:
            Path đến video đã tạo, hoặc None nếu thất bại
        """
        if not self.login_if_needed():
            return None
        
        if not source_image.exists():
            self.logger.error(f"Source image not found: {source_image}")
            return None
        
        self.logger.info("Creating video from image and prompt...")
        
        wait = WebDriverWait(self.driver, self.wait_timeout)
        
        try:
            # TODO: Navigate đến trang tạo video
            # self.driver.get(f"{self.base_url}/generate/video")
            # time.sleep(2)
            
            # TODO: Upload source image
            # file_input = self.driver.find_element(
            #     By.CSS_SELECTOR, "input[type='file'].source-image-upload"
            # )
            # file_input.send_keys(str(source_image))
            # time.sleep(2)
            
            # TODO: Nhập video prompt
            prompt_input = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "textarea.video-prompt, textarea[name='video_prompt']")
            ))
            prompt_input.clear()
            prompt_input.send_keys(prompt)
            
            # TODO: Click Generate Video
            generate_btn = self.driver.find_element(
                By.CSS_SELECTOR, "button.generate-video-btn"
            )
            generate_btn.click()
            
            # TODO: Chờ video được tạo (thường lâu hơn ảnh)
            self.logger.info("Waiting for video generation...")
            time.sleep(60)  # TODO: Thay bằng wait condition phù hợp
            
            # TODO: Download video
            # download_btn = wait.until(EC.element_to_be_clickable(
            #     (By.CSS_SELECTOR, "button.download-video, a.video-download-link")
            # ))
            # download_btn.click()
            
            # TODO: Move file đến out_dir
            
            # Placeholder return
            self.logger.warning("Video generation not fully implemented - returning placeholder")
            return None
            
        except TimeoutException as e:
            self.logger.error(f"Timeout while creating video: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error creating video: {e}")
            return None
    
    def generate_video_for_scene(
        self,
        scene: Scene,
        img_dir: Path,
        out_dir: Path
    ) -> Optional[Path]:
        """
        Tạo video cho một scene.
        
        Args:
            scene: Scene object (phải có img_path)
            img_dir: Thư mục chứa ảnh
            out_dir: Thư mục lưu video output
            
        Returns:
            Path đến video đã tạo
        """
        if not scene.img_path:
            self.logger.error(f"Scene {scene.scene_id} has no image path")
            return None
        
        source_image = img_dir / scene.img_path
        if not source_image.exists():
            # Thử với path tuyệt đối
            source_image = Path(scene.img_path)
        
        if not source_image.exists():
            self.logger.error(f"Source image not found: {scene.img_path}")
            return None
        
        for attempt in range(self.retry_count):
            self.logger.info(f"Generating video for scene {scene.scene_id}, attempt {attempt + 1}")
            
            result = self.create_video_from_prompt(
                prompt=scene.video_prompt,
                source_image=source_image,
                out_dir=out_dir
            )
            
            if result:
                return result
            
            if attempt < self.retry_count - 1:
                self.logger.warning(f"Retrying in 10 seconds...")
                time.sleep(10)
        
        return None
    
    # ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    def _wait_for_download(
        self,
        timeout: int = 60,
        poll_interval: float = 1.0
    ) -> Optional[Path]:
        """
        Chờ file download hoàn tất.
        
        Args:
            timeout: Thời gian chờ tối đa (giây)
            poll_interval: Khoảng cách giữa các lần check (giây)
            
        Returns:
            Path đến file đã download
        """
        download_dir = Path(self.download_dir)
        
        # Lấy danh sách file trước khi download
        existing_files = set(download_dir.glob("*"))
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            current_files = set(download_dir.glob("*"))
            new_files = current_files - existing_files
            
            # Bỏ qua file .crdownload (Chrome download in progress)
            completed_files = [
                f for f in new_files
                if not f.suffix == ".crdownload" and not f.suffix == ".tmp"
            ]
            
            if completed_files:
                # Trả về file mới nhất
                return max(completed_files, key=lambda f: f.stat().st_mtime)
            
            time.sleep(poll_interval)
        
        self.logger.warning(f"Download timeout after {timeout}s")
        return None
