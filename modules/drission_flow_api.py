#!/usr/bin/env python3
"""
VE3 Tool - DrissionPage Flow API
================================
Gọi Google Flow API trực tiếp bằng DrissionPage.

Flow:
1. Sử dụng Webshare proxy pool (tự động xoay khi bị block)
2. Mở Chrome với proxy → Vào Google Flow → Đợi user chọn project
3. Inject JS Interceptor để capture tokens + CANCEL request
4. Gọi API trực tiếp với captured URL + payload
"""

import json
import time
import random
import base64
import requests
import threading
import os
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any, Callable
from dataclasses import dataclass
from datetime import datetime

# Optional DrissionPage import
DRISSION_AVAILABLE = False
try:
    from DrissionPage import ChromiumPage, ChromiumOptions
    DRISSION_AVAILABLE = True
except ImportError:
    ChromiumPage = None
    ChromiumOptions = None

# Webshare Proxy imports (IPv6 proxy đã bị bỏ)
WEBSHARE_AVAILABLE = False
try:
    from webshare_proxy import WebshareProxy, get_proxy_manager, init_proxy_manager
    WEBSHARE_AVAILABLE = True
except ImportError:
    WebshareProxy = None
    get_proxy_manager = None
    init_proxy_manager = None


# ============================================================================
# SESSION STATE PERSISTENCE
# ============================================================================
SESSION_STATE_FILE = Path(__file__).parent.parent / "config" / "session_state.yaml"

def _load_session_state() -> Dict[str, Any]:
    """Load session state from file."""
    try:
        if SESSION_STATE_FILE.exists():
            import yaml
            with open(SESSION_STATE_FILE, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
    except Exception:
        pass
    return {}

def _save_session_state(state: Dict[str, Any]) -> None:
    """Save session state to file."""
    try:
        import yaml
        SESSION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SESSION_STATE_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(state, f, allow_unicode=True)
    except Exception:
        pass

def _get_last_session_id(machine_id: int, worker_id: int) -> Optional[int]:
    """Get last session ID for a machine/worker from persistent storage."""
    state = _load_session_state()
    key = f"machine_{machine_id}_worker_{worker_id}"
    return state.get(key)

def _save_last_session_id(machine_id: int, worker_id: int, session_id: int) -> None:
    """Save last session ID for a machine/worker to persistent storage."""
    state = _load_session_state()
    key = f"machine_{machine_id}_worker_{worker_id}"
    state[key] = session_id
    state['last_updated'] = datetime.now().isoformat()
    _save_session_state(state)


@dataclass
class GeneratedImage:
    """Kết quả ảnh được tạo."""
    url: str = ""
    base64_data: Optional[str] = None
    seed: Optional[int] = None
    media_name: Optional[str] = None
    local_path: Optional[Path] = None


# JS Interceptor - INJECT CUSTOM PAYLOAD với reCAPTCHA token fresh
# Flow: Python chuẩn bị payload (có media_id) → Chrome trigger reCAPTCHA → Inject token → Gửi ngay
JS_INTERCEPTOR = '''
window._tk=null;window._pj=null;window._xbv=null;window._rct=null;window._payload=null;window._sid=null;window._url=null;
window._response=null;window._responseError=null;window._requestPending=false;
window._customPayload=null; // Payload đầy đủ từ Python (có media_id)
window._videoResponse=null;window._videoError=null;window._videoPending=false;

(function(){
    if(window.__interceptReady) return 'ALREADY_READY';
    window.__interceptReady = true;

    var orig = window.fetch;
    window.fetch = async function(url, opts) {
        var urlStr = typeof url === 'string' ? url : url.url;

        // ============================================
        // IMAGE GENERATION REQUESTS
        // ============================================
        if (urlStr.includes('aisandbox') && (urlStr.includes('batchGenerate') || urlStr.includes('flowMedia'))) {
            console.log('[IMG] Request intercepted:', urlStr);
            window._requestPending = true;
            window._response = null;
            window._responseError = null;
            window._url = urlStr;

            // Capture headers
            if (opts && opts.headers) {
                var h = opts.headers;
                if (h['Authorization']) {
                    window._tk = h['Authorization'].replace('Bearer ', '');
                }
                if (h['x-browser-validation']) {
                    window._xbv = h['x-browser-validation'];
                }
            }

            // Parse Chrome's original body để lấy reCAPTCHA token FRESH
            var chromeBody = null;
            var freshRecaptcha = null;
            if (opts && opts.body) {
                try {
                    chromeBody = JSON.parse(opts.body);
                    // Lấy reCAPTCHA token từ Chrome (FRESH!)
                    if (chromeBody.recaptchaToken) {
                        freshRecaptcha = chromeBody.recaptchaToken;
                    } else if (chromeBody.clientContext && chromeBody.clientContext.recaptchaToken) {
                        freshRecaptcha = chromeBody.clientContext.recaptchaToken;
                    }
                    window._rct = freshRecaptcha;
                    window._pj = chromeBody.clientContext ? chromeBody.clientContext.projectId : null;
                    window._sid = chromeBody.clientContext ? chromeBody.clientContext.sessionId : null;
                } catch(e) {
                    console.log('[ERROR] Parse Chrome body failed:', e);
                }
            }

            // ============================================
            // CUSTOM PAYLOAD MODE: Thay thế body bằng payload của Python
            // ============================================
            if (window._customPayload && freshRecaptcha) {
                try {
                    var customBody = window._customPayload;

                    // INJECT fresh reCAPTCHA token vào payload của chúng ta
                    if (customBody.clientContext) {
                        customBody.clientContext.recaptchaToken = freshRecaptcha;
                        // Cũng copy sessionId và projectId
                        if (chromeBody && chromeBody.clientContext) {
                            customBody.clientContext.sessionId = chromeBody.clientContext.sessionId;
                            customBody.clientContext.projectId = chromeBody.clientContext.projectId;
                        }
                    }

                    // Thay thế body
                    opts.body = JSON.stringify(customBody);
                    console.log('[INJECT] Custom payload với fresh reCAPTCHA, gửi NGAY!');
                    console.log('[INJECT] imageInputs:', customBody.requests[0].imageInputs ? customBody.requests[0].imageInputs.length : 0);

                    // Clear để không dùng lại
                    window._customPayload = null;
                } catch(e) {
                    console.log('[ERROR] Inject custom payload failed:', e);
                }
            }
            // ============================================
            // SIMPLE MODIFY MODE: Chỉ sửa imageCount/imageInputs
            // ============================================
            else if (window._modifyConfig && chromeBody) {
                try {
                    var cfg = window._modifyConfig;

                    if (cfg.imageCount && chromeBody.requests) {
                        chromeBody.requests = chromeBody.requests.slice(0, cfg.imageCount);
                    }

                    if (cfg.imageInputs && chromeBody.requests) {
                        chromeBody.requests.forEach(function(req) {
                            req.imageInputs = cfg.imageInputs;
                        });
                        console.log('[MODIFY] Added ' + cfg.imageInputs.length + ' reference images');
                    }

                    opts.body = JSON.stringify(chromeBody);
                    window._modifyConfig = null;
                } catch(e) {
                    console.log('[ERROR] Modify failed:', e);
                }
            }

            // FORWARD NGAY LẬP TỨC (trong 0.05s)
            try {
                console.log('[FORWARD] Sending with fresh reCAPTCHA...');
                var response = await orig.apply(this, [url, opts]);
                var cloned = response.clone();

                try {
                    var data = await cloned.json();
                    window._response = data;
                    console.log('[RESPONSE] Status:', response.status);
                    if (data.media) {
                        console.log('[RESPONSE] Got ' + data.media.length + ' images');
                    }
                } catch(e) {
                    window._response = {status: response.status, error: 'parse_failed'};
                }

                window._requestPending = false;
                return response;
            } catch(e) {
                console.log('[ERROR] Request failed:', e);
                window._responseError = e.toString();
                window._requestPending = false;
                throw e;
            }
        }

        // ============================================
        // VIDEO GENERATION REQUESTS (I2V)
        // ============================================
        if (urlStr.includes('aisandbox') && urlStr.includes('video:')) {
            console.log('[VIDEO] Request to:', urlStr);
            window._videoPending = true;
            window._videoResponse = null;
            window._videoError = null;

            if (opts && opts.headers) {
                var h = opts.headers;
                if (h['Authorization']) window._tk = h['Authorization'].replace('Bearer ', '');
                if (h['x-browser-validation']) window._xbv = h['x-browser-validation'];
            }

            if (opts && opts.body) {
                try {
                    var body = JSON.parse(opts.body);
                    if (body.clientContext) {
                        window._sid = body.clientContext.sessionId;
                        window._pj = body.clientContext.projectId;
                        window._rct = body.clientContext.recaptchaToken;
                    }
                } catch(e) {}
            }

            try {
                var response = await orig.apply(this, [url, opts]);
                var cloned = response.clone();
                try {
                    window._videoResponse = await cloned.json();
                } catch(e) {
                    window._videoResponse = {status: response.status, error: 'parse_failed'};
                }
                window._videoPending = false;
                return response;
            } catch(e) {
                window._videoError = e.toString();
                window._videoPending = false;
                throw e;
            }
        }

        return orig.apply(this, arguments);
    };
    console.log('[INTERCEPTOR] Ready - CUSTOM PAYLOAD INJECTION mode');
    return 'READY';
})();
'''

# JS để click "Dự án mới"
JS_CLICK_NEW_PROJECT = '''
(function() {
    var btns = document.querySelectorAll('button');
    for (var b of btns) {
        var text = b.textContent || '';
        if (text.includes('Dự án mới') || text.includes('New project')) {
            b.click();
            console.log('[AUTO] Clicked: Du an moi');
            return 'CLICKED';
        }
    }
    return 'NOT_FOUND';
})();
'''

# JS để chọn "Tạo hình ảnh" từ dropdown
JS_SELECT_IMAGE_MODE = '''
(async function() {
    // 1. Click dropdown
    var dropdown = document.querySelector('button[role="combobox"]');
    if (!dropdown) {
        console.log('[AUTO] Dropdown not found');
        return 'NO_DROPDOWN';
    }
    dropdown.click();
    console.log('[AUTO] Clicked dropdown');

    // 2. Đợi dropdown mở
    await new Promise(r => setTimeout(r, 500));

    // 3. Tìm và click "Tạo hình ảnh"
    var allElements = document.querySelectorAll('*');
    for (var el of allElements) {
        var text = el.textContent || '';
        if (text === 'Tạo hình ảnh' || text.includes('Tạo hình ảnh từ văn bản') ||
            text === 'Generate image' || text.includes('Generate image from text')) {
            var rect = el.getBoundingClientRect();
            if (rect.height > 10 && rect.height < 80 && rect.width > 50) {
                el.click();
                console.log('[AUTO] Clicked: Tao hinh anh');
                return 'CLICKED';
            }
        }
    }
    return 'NOT_FOUND';
})();
'''


class DrissionFlowAPI:
    """
    Google Flow API client sử dụng DrissionPage.

    Sử dụng:
    ```python
    api = DrissionFlowAPI(
        profile_dir="./chrome_profiles/main",
        proxy_port=1080  # SOCKS5 proxy
    )

    # Setup Chrome và đợi user chọn project
    if api.setup():
        # Generate ảnh
        success, images, error = api.generate_image("a cat playing piano")
    ```
    """

    BASE_URL = "https://aisandbox-pa.googleapis.com"
    FLOW_URL = "https://labs.google/fx/vi/tools/flow"

    def __init__(
        self,
        profile_dir: str = "./chrome_profile",
        chrome_port: int = 0,  # 0 = auto-generate unique port (parallel-safe)
        verbose: bool = True,
        log_callback: Optional[Callable] = None,
        # Webshare proxy - dùng global proxy manager
        webshare_enabled: bool = True,  # BẬT Webshare proxy by default
        worker_id: int = 0,  # Worker ID cho proxy rotation (mỗi Chrome có proxy riêng)
        headless: bool = True,  # Chạy Chrome ẩn (default: ON)
        machine_id: int = 1,  # Máy số mấy (1-99) - tránh trùng session giữa các máy
        # Legacy params (ignored)
        proxy_port: int = 1080,
        use_proxy: bool = False,
    ):
        """
        Khởi tạo DrissionFlowAPI.

        Args:
            profile_dir: Thư mục Chrome profile
            chrome_port: Port cho Chrome debugging (0 = auto-generate unique port)
            verbose: In log chi tiết
            log_callback: Callback để log (msg, level)
            webshare_enabled: Dùng Webshare proxy pool (default True)
            worker_id: Worker ID cho proxy rotation (mỗi Chrome có proxy riêng)
            headless: Chạy Chrome ẩn không hiện cửa sổ (default True)
            machine_id: Máy số mấy (1-99), mỗi máy cách nhau 30000 session để tránh trùng
        """
        self.profile_dir = Path(profile_dir)
        self.worker_id = worker_id  # Lưu worker_id để dùng cho proxy rotation
        self._headless = headless  # Lưu setting headless
        self._machine_id = machine_id  # Máy số mấy (1-99)
        # Unique port cho mỗi worker (không random để tránh conflict)
        # Worker 0 → 9222, Worker 1 → 9223, ...
        if chrome_port == 0:
            self.chrome_port = 9222 + worker_id
        else:
            self.chrome_port = chrome_port
        self.verbose = verbose
        self.log_callback = log_callback

        # Chrome/DrissionPage
        self.driver: Optional[ChromiumPage] = None

        # Webshare Proxy - dùng global manager
        self._webshare_proxy = None
        self._use_webshare = webshare_enabled
        self._proxy_bridge = None  # Local proxy bridge

        # === TÍNH SESSION ID DỰA TRÊN WORKER VÀ SỐ LUỒNG ===
        # Đọc số luồng từ settings để chia dải proxy đều
        num_workers = 2  # Default
        try:
            import yaml
            settings_path = Path(__file__).parent.parent / "config" / "settings.yaml"
            if settings_path.exists():
                with open(settings_path, 'r', encoding='utf-8') as f:
                    cfg = yaml.safe_load(f) or {}
                num_workers = max(1, cfg.get('parallel_voices', 2))
        except:
            pass

        # Mỗi worker có dải proxy riêng:
        # - 2 workers: Worker 0 = 1-15000, Worker 1 = 15001-30000
        # - 3 workers: Worker 0 = 1-10000, Worker 1 = 10001-20000, Worker 2 = 20001-30000
        sessions_per_worker = 30000 // num_workers
        base_offset = (self._machine_id - 1) * 30000  # Offset theo máy
        worker_offset = self.worker_id * sessions_per_worker  # Offset theo worker
        range_start = base_offset + worker_offset + 1
        range_end = base_offset + worker_offset + sessions_per_worker
        self._sessions_per_worker = sessions_per_worker  # Lưu để tăng đúng trong dải
        self._session_range_start = range_start
        self._session_range_end = range_end

        # === LOAD LAST SESSION ID FROM FILE ===
        # Tiếp tục từ session cuối để không lặp lại các session đã dùng
        last_session = _get_last_session_id(self._machine_id, self.worker_id)
        if last_session and range_start <= last_session < range_end:
            # Tiếp tục từ session cuối + 1
            self._rotating_session_id = last_session + 1
            # Nếu đã hết dải, quay lại đầu
            if self._rotating_session_id > range_end:
                self._rotating_session_id = range_start
                self.log(f"[Session] ♻️ Đã hết dải, quay lại từ đầu: {range_start}")
            else:
                self.log(f"[Session] ⏩ Tiếp tục từ session {self._rotating_session_id} (last={last_session})")
        else:
            # Bắt đầu từ đầu dải
            self._rotating_session_id = range_start
            self.log(f"[Session] 🆕 Bắt đầu từ session {range_start}")

        self.log(f"[Session] Machine {self._machine_id}, Worker {self.worker_id}: session range {range_start}-{range_end}")

        self._bridge_port = None   # Bridge port for API calls
        self._is_rotating_mode = False  # True = Rotating Endpoint (auto IP change)
        if webshare_enabled and WEBSHARE_AVAILABLE:
            try:
                from webshare_proxy import get_proxy_manager, WebshareProxy
                manager = get_proxy_manager()

                # Check rotating endpoint mode first
                if manager.is_rotating_mode():
                    self._webshare_proxy = WebshareProxy()
                    self._is_rotating_mode = True
                    rotating = manager.rotating_endpoint
                    self.log(f"✓ Webshare: ROTATING ENDPOINT mode")
                    self.log(f"  → {rotating.host}:{rotating.port}")
                elif manager.proxies:
                    self._webshare_proxy = WebshareProxy()  # Wrapper cho manager
                    # Lấy proxy cho worker này (không dùng current_proxy global)
                    worker_proxy = manager.get_proxy_for_worker(self.worker_id)
                    if worker_proxy:
                        self.log(f"✓ Webshare: {len(manager.proxies)} proxies, worker {self.worker_id}: {worker_proxy.endpoint}")
                    else:
                        self.log(f"✓ Webshare: {len(manager.proxies)} proxies loaded")
                else:
                    self._use_webshare = False
                    self.log("⚠️ Webshare: No proxies loaded", "WARN")
            except Exception as e:
                self._use_webshare = False
                self.log(f"⚠️ Webshare init error: {e}", "WARN")

        # Captured tokens
        self.bearer_token: Optional[str] = None
        self.project_id: Optional[str] = None
        self.session_id: Optional[str] = None
        self.recaptcha_token: Optional[str] = None
        self.x_browser_validation: Optional[str] = None
        self.captured_url: Optional[str] = None
        self.captured_payload: Optional[str] = None

        # State
        self._ready = False

    def log(self, msg: str, level: str = "INFO"):
        """Log message - chỉ dùng 1 trong 2: callback hoặc print."""
        if self.log_callback:
            # Nếu có callback, để parent xử lý log (tránh duplicate)
            self.log_callback(msg, level)
        elif self.verbose:
            # Fallback: print trực tiếp nếu không có callback
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] [{level}] {msg}")

    def _auto_setup_project(self, timeout: int = 60) -> bool:
        """
        Tự động setup project:
        1. Click "Dự án mới" (New project)
        2. Chọn "Tạo hình ảnh" (Generate image)
        3. Đợi vào project

        Args:
            timeout: Timeout tổng (giây)

        Returns:
            True nếu thành công
        """
        self.log("→ Đang tự động tạo dự án mới...")

        # 1. Đợi trang load và tìm button "Dự án mới"
        for i in range(15):
            result = self.driver.run_js(JS_CLICK_NEW_PROJECT)
            if result == 'CLICKED':
                self.log("✓ Clicked 'Dự án mới'")
                time.sleep(2)
                break
            time.sleep(1)
            if i == 5:
                self.log("  ... đợi button 'Dự án mới' xuất hiện...")
        else:
            self.log("✗ Không tìm thấy button 'Dự án mới'", "ERROR")
            self.log("→ Hãy click thủ công vào dự án", "WARN")
            # Fallback: đợi user click thủ công
            return self._wait_for_project_manual(timeout)

        # 2. Chọn "Tạo hình ảnh" từ dropdown
        time.sleep(1)
        for i in range(10):
            result = self.driver.run_js(JS_SELECT_IMAGE_MODE)
            if result == 'CLICKED':
                self.log("✓ Chọn 'Tạo hình ảnh'")
                time.sleep(2)
                break
            time.sleep(0.5)
        else:
            self.log("⚠️ Không tìm thấy dropdown - có thể đã ở mode đúng", "WARN")

        # 3. Đợi vào project
        self.log("→ Đợi vào project...")
        for i in range(timeout):
            current_url = self.driver.url
            if "/project/" in current_url:
                self.log(f"✓ Đã vào dự án!")
                return True
            time.sleep(1)
            if i % 10 == 9:
                self.log(f"  ... đợi {i+1}s")

        self.log("✗ Timeout - chưa vào được dự án", "ERROR")
        return False

    def _wait_for_project_manual(self, timeout: int = 60) -> bool:
        """
        Fallback: đợi user chọn project thủ công.
        Nếu quá lâu (30s) → tự động F5 refresh.
        Nếu vẫn không được (60s) → restart Chrome với IP mới.
        """
        self.log("Đợi chọn dự án thủ công...")
        self.log("→ Click vào dự án có sẵn hoặc tạo dự án mới")

        REFRESH_TIMEOUT = 30  # Sau 30s không click được → F5
        refreshed = False

        for i in range(timeout):
            current_url = self.driver.url
            if "/project/" in current_url:
                self.log(f"✓ Đã vào dự án!")

                # Quan trọng: Chọn "Tạo hình ảnh" từ dropdown
                time.sleep(1)
                for j in range(10):
                    result = self.driver.run_js(JS_SELECT_IMAGE_MODE)
                    if result == 'CLICKED':
                        self.log("✓ Chọn 'Tạo hình ảnh'")
                        time.sleep(1)
                        break
                    time.sleep(0.5)
                else:
                    self.log("⚠️ Không tìm thấy dropdown 'Tạo hình ảnh'", "WARN")

                return True
            time.sleep(1)

            # Sau 30s → tự động F5 refresh
            if i == REFRESH_TIMEOUT and not refreshed:
                self.log(f"⚠️ Đợi quá lâu ({REFRESH_TIMEOUT}s) - Tự động F5 refresh...")
                try:
                    self.driver.refresh()
                    refreshed = True
                    time.sleep(3)  # Đợi page load
                except Exception as e:
                    self.log(f"  → F5 error: {e}", "WARN")

            if i % 15 == 14:
                self.log(f"... đợi {i+1}s - hãy click chọn dự án")

        self.log("✗ Timeout - chưa chọn dự án", "ERROR")

        # Timeout → gợi ý restart với IP mới
        self.log("→ Sẽ restart Chrome với IP mới...", "WARN")
        return False  # Trả về False để trigger restart ở layer trên

    def _warm_up_session(self, dummy_prompt: str = "a simple test image") -> bool:
        """
        Warm up session bằng cách tạo 1 ảnh thật trong Chrome.
        Điều này "activate" session và làm cho tokens hợp lệ.

        Args:
            dummy_prompt: Prompt đơn giản để warm up

        Returns:
            True nếu thành công
        """
        self.log("=" * 50)
        self.log("  WARM UP SESSION")
        self.log("=" * 50)
        self.log("→ Tạo 1 ảnh trong Chrome để activate session...")
        self.log(f"  Prompt: {dummy_prompt[:50]}...")

        # Tìm textarea và gửi prompt
        textarea = self._find_textarea()
        if not textarea:
            self.log("✗ Không tìm thấy textarea", "ERROR")
            return False

        textarea.clear()
        time.sleep(0.2)
        textarea.input(dummy_prompt)
        time.sleep(0.3)
        textarea.input('\n')
        self.log("✓ Đã gửi prompt, đợi Chrome tạo ảnh...")

        # Đợi ảnh được tạo - kiểm tra bằng cách tìm img elements mới
        # hoặc đợi loading indicator biến mất
        self.log("→ Đợi ảnh được tạo (có thể mất 10-30s)...")

        for i in range(60):  # Đợi tối đa 60s
            time.sleep(2)

            # Kiểm tra có ảnh được tạo không
            # Tìm elements chứa ảnh generated
            check_result = self.driver.run_js("""
                // Tìm các img elements có src chứa base64 hoặc googleusercontent
                var imgs = document.querySelectorAll('img');
                var found = 0;
                for (var img of imgs) {
                    var src = img.src || '';
                    if (src.includes('data:image') || src.includes('googleusercontent') || src.includes('ggpht')) {
                        // Kiểm tra kích thước - ảnh generated thường lớn
                        if (img.naturalWidth > 200 || img.width > 200) {
                            found++;
                        }
                    }
                }
                return {found: found, loading: !!document.querySelector('[data-loading="true"]')};
            """)

            if check_result and check_result.get('found', 0) > 0:
                self.log(f"✓ Phát hiện {check_result['found']} ảnh!")
                time.sleep(2)  # Đợi thêm để ổn định
                self.log("✓ Session đã được warm up!")
                return True

            if i % 5 == 4:
                self.log(f"  ... đợi {(i+1)*2}s")

        self.log("⚠️ Không phát hiện được ảnh, tiếp tục...", "WARN")
        return True  # Vẫn return True để tiếp tục

    def _kill_chrome(self):
        """
        Close Chrome của tool này (không kill tất cả Chrome).
        Chỉ đóng driver và proxy bridge.
        """
        try:
            # Chỉ close driver của tool này
            if self.driver:
                try:
                    self.driver.quit()
                except:
                    pass
                self.driver = None

            # Stop proxy bridge
            if hasattr(self, '_proxy_bridge') and self._proxy_bridge:
                try:
                    from proxy_bridge import stop_proxy_bridge
                    stop_proxy_bridge(self._proxy_bridge)
                except:
                    pass
                self._proxy_bridge = None

            self.log("✓ Closed Chrome và proxy bridge của tool")
            time.sleep(1)
        except Exception as e:
            pass

    def setup(
        self,
        wait_for_project: bool = True,
        timeout: int = 120,
        warm_up: bool = False,
        project_url: str = None
    ) -> bool:
        """
        Setup Chrome và inject interceptor.
        Giống batch_generator.py - không cần warm_up.

        Args:
            wait_for_project: Đợi user chọn project
            timeout: Timeout đợi project (giây)
            warm_up: Tạo 1 ảnh trong Chrome trước (default False - không cần)
            project_url: URL project cố định (nếu có, sẽ vào thẳng project này)

        Returns:
            True nếu thành công
        """
        if not DRISSION_AVAILABLE:
            self.log("DrissionPage không được cài đặt! pip install DrissionPage", "ERROR")
            return False

        self.log("=" * 50)
        self.log("  DRISSION FLOW API - Setup")
        self.log("=" * 50)

        # 1. Tạo thư mục profile
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.log(f"Profile: {self.profile_dir}")
        self.log(f"Chrome port: {self.chrome_port}")

        # 2. Khởi tạo Chrome với proxy
        self.log("Khởi động Chrome...")
        try:
            options = ChromiumOptions()
            options.set_user_data_path(str(self.profile_dir))
            options.set_local_port(self.chrome_port)

            # Tìm và set đường dẫn Chrome
            import platform
            if platform.system() == 'Windows':
                chrome_paths = [
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                ]
                for chrome_path in chrome_paths:
                    if os.path.exists(chrome_path):
                        options.set_browser_path(chrome_path)
                        self.log(f"  Chrome path: {chrome_path}")
                        break

            # Thêm arguments cần thiết
            options.set_argument('--no-sandbox')  # Cần cho cả Windows và Linux
            options.set_argument('--disable-dev-shm-usage')
            options.set_argument('--disable-gpu')
            options.set_argument('--disable-software-rasterizer')
            options.set_argument('--disable-extensions')
            options.set_argument('--no-first-run')
            options.set_argument('--no-default-browser-check')

            # Headless mode - chạy Chrome ẩn
            if self._headless:
                options.headless()  # Dùng method built-in của DrissionPage
                options.set_argument('--window-size=1920,1080')
                options.set_argument('--disable-popup-blocking')
                options.set_argument('--ignore-certificate-errors')
                self.log("🔇 Headless mode: ON (Chrome chạy ẩn)")
            else:
                self.log("👁️ Headless mode: OFF (Chrome hiển thị)")

            if self._use_webshare and self._webshare_proxy:
                from webshare_proxy import get_proxy_manager
                manager = get_proxy_manager()

                # === CHECK ROTATING ENDPOINT MODE ===
                if manager.is_rotating_mode():
                    # ROTATING RESIDENTIAL: 2 modes
                    # 1. Random IP: username ends with -rotate → mỗi request = IP ngẫu nhiên
                    # 2. Sticky Session: username không -rotate → session ID tự động thêm
                    rotating = manager.rotating_endpoint
                    self._is_rotating_mode = True
                    self._is_random_ip_mode = rotating.base_username.endswith('-rotate')

                    # Session ID từ counter (chỉ dùng cho Sticky Session mode)
                    session_id = self._rotating_session_id
                    session_username = rotating.get_username_for_session(session_id)

                    try:
                        from proxy_bridge import start_proxy_bridge
                        bridge_port = 8800 + self.worker_id
                        self._proxy_bridge = start_proxy_bridge(
                            local_port=bridge_port,
                            remote_host=rotating.host,
                            remote_port=rotating.port,
                            username=session_username,
                            password=rotating.password
                        )
                        self._bridge_port = bridge_port
                        time.sleep(0.5)

                        options.set_argument(f'--proxy-server=http://127.0.0.1:{bridge_port}')
                        options.set_argument('--proxy-bypass-list=<-loopback>')
                        options.set_argument('--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1')

                        if self._is_random_ip_mode:
                            self.log(f"🎲 RANDOM IP MODE [Worker {self.worker_id}]")
                            self.log(f"  → {rotating.host}:{rotating.port}")
                            self.log(f"  → Username: {session_username} (mỗi request = IP mới)")
                        else:
                            self.log(f"🔄 STICKY SESSION [Worker {self.worker_id}]")
                            self.log(f"  → {rotating.host}:{rotating.port}")
                            self.log(f"  → Session: {session_username}")
                        self.log(f"  Local: http://127.0.0.1:{bridge_port}")

                    except Exception as e:
                        self.log(f"Bridge error: {e}", "ERROR")
                        return False
                else:
                    # === DIRECT PROXY LIST MODE ===
                    self._is_rotating_mode = False
                    username, password = self._webshare_proxy.get_chrome_auth(self.worker_id)
                    remote_proxy_url = self._webshare_proxy.get_chrome_proxy_arg(self.worker_id)

                    if username and password:
                        # Có auth → dùng local proxy bridge
                        # QUAN TRỌNG: Lấy proxy cho worker này, không dùng current_proxy global
                        proxy = manager.get_proxy_for_worker(self.worker_id)
                        if not proxy:
                            # Không có proxy khả dụng - chạy không proxy (fallback)
                            self.log(f"⚠️ No proxy available - running WITHOUT proxy", "WARN")
                            self._use_webshare = False
                            # Không set proxy args - Chrome sẽ chạy direct
                        else:
                            try:
                                from proxy_bridge import start_proxy_bridge
                                # Unique bridge port based on worker_id (parallel-safe)
                                bridge_port = 8800 + self.worker_id
                                self._proxy_bridge = start_proxy_bridge(
                                    local_port=bridge_port,
                                    remote_host=proxy.host,
                                    remote_port=proxy.port,
                                    username=proxy.username,
                                    password=proxy.password
                                )
                                self._bridge_port = bridge_port  # LƯU ĐỂ DÙNG TRONG call_api()
                                time.sleep(0.5)  # Đợi bridge start

                                # Chrome kết nối đến local bridge (không cần auth)
                                options.set_argument(f'--proxy-server=http://127.0.0.1:{bridge_port}')
                                options.set_argument('--proxy-bypass-list=<-loopback>')
                                options.set_argument('--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1')

                                self.log(f"Proxy [Worker {self.worker_id}]: Bridge → {proxy.endpoint}")
                                self.log(f"  Local: http://127.0.0.1:{bridge_port}")
                                self.log(f"  Auth: {username}:****")

                            except Exception as e:
                                self.log(f"Bridge error: {e}, using direct proxy", "WARN")
                                options.set_argument(f'--proxy-server={remote_proxy_url}')
                                options.set_argument('--proxy-bypass-list=<-loopback>')
                                self._proxy_auth = (username, password)
                    else:
                        # IP Authorization mode
                        options.set_argument(f'--proxy-server={remote_proxy_url}')
                        options.set_argument('--proxy-bypass-list=<-loopback>')
                        options.set_argument('--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1')
                        self.log(f"Proxy: Webshare ({remote_proxy_url})")
                        self.log(f"  Mode: IP Authorization")
            else:
                self._is_rotating_mode = False
                self.log("⚠️ Webshare proxy không sẵn sàng - chạy không có proxy", "WARN")

            # Tắt Chrome đang dùng profile này trước (tránh conflict)
            self._kill_chrome_using_profile()

            # Clean up profile lock trước khi start (tránh conflict)
            try:
                lock_file = self.profile_dir / "SingletonLock"
                if lock_file.exists():
                    lock_file.unlink()
                    self.log("  Đã xóa SingletonLock cũ")
            except:
                pass

            # Thử khởi tạo Chrome với retry
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self.driver = ChromiumPage(addr_or_opts=options)
                    self.log("✓ Chrome started")
                    break
                except Exception as chrome_err:
                    self.log(f"Chrome attempt {attempt+1}/{max_retries} failed: {chrome_err}", "WARN")
                    if attempt < max_retries - 1:
                        # Thử port khác
                        self.chrome_port = random.randint(9222, 9999)
                        options.set_local_port(self.chrome_port)
                        self.log(f"  → Retry với port {self.chrome_port}...")
                        time.sleep(3)  # Đợi lâu hơn để Chrome cũ tắt hẳn
                    else:
                        raise chrome_err

            # Setup proxy auth nếu cần (CDP-based)
            if self._use_webshare and hasattr(self, '_proxy_auth') and self._proxy_auth:
                self._setup_proxy_auth()

        except Exception as e:
            self.log(f"✗ Chrome error: {e}", "ERROR")
            return False

        # 3. Vào Google Flow (hoặc project cố định nếu có) - VỚI RETRY
        target_url = project_url if project_url else self.FLOW_URL
        self.log(f"Vào: {target_url[:60]}...")

        max_nav_retries = 3
        nav_success = False

        for nav_attempt in range(max_nav_retries):
            try:
                self.driver.get(target_url)
                time.sleep(3)

                # Kiểm tra xem trang có load được không
                current_url = self.driver.url
                if not current_url or current_url == "about:blank" or "error" in current_url.lower():
                    raise Exception(f"Page không load được: {current_url}")

                self.log(f"✓ URL: {current_url}")

                # Lưu project_url để dùng khi retry
                if "/project/" in current_url:
                    self._current_project_url = current_url
                    self.log(f"  → Saved project URL for retry")

                nav_success = True
                break

            except Exception as e:
                error_msg = str(e)
                self.log(f"✗ Navigation error (attempt {nav_attempt+1}/{max_nav_retries}): {error_msg}", "WARN")

                # Kiểm tra lỗi proxy/connection
                is_proxy_error = any(x in error_msg.lower() for x in [
                    "timeout", "connection", "proxy", "10060", "err_proxy", "err_connection"
                ])

                if is_proxy_error and nav_attempt < max_nav_retries - 1:
                    self.log(f"  → Proxy/Connection error, restart Chrome...", "WARN")

                    # Restart Chrome
                    self._kill_chrome()
                    self.close()
                    time.sleep(3)

                    # Restart với cùng config
                    try:
                        if not self._start_chrome():
                            self.log("  → Không restart được Chrome", "ERROR")
                            continue
                        self.log("  → Chrome restarted, thử lại...")
                    except Exception as restart_err:
                        self.log(f"  → Restart Chrome lỗi: {restart_err}", "ERROR")
                        continue
                elif nav_attempt >= max_nav_retries - 1:
                    self.log(f"✗ Navigation failed sau {max_nav_retries} lần thử", "ERROR")
                    return False

        if not nav_success:
            # === FALLBACK: Thử đổi proxy mode ===
            fallback_tried = False

            if hasattr(self, '_is_rotating_mode') and self._is_rotating_mode:
                try:
                    from webshare_proxy import get_proxy_manager
                    manager = get_proxy_manager()

                    if manager.is_rotating_mode() and manager.rotating_endpoint:
                        rotating = manager.rotating_endpoint
                        old_username = rotating.base_username

                        # Xác định mode hiện tại và đổi sang mode khác
                        if hasattr(self, '_is_random_ip_mode') and self._is_random_ip_mode:
                            # Đang Random IP → thử Sticky Session
                            self.log("⚠️ Random IP mode failed, thử STICKY SESSION mode...", "WARN")
                            new_username = old_username.replace('-rotate', '')
                            fallback_mode = "Sticky Session"
                        else:
                            # Đang Sticky Session → thử Random IP
                            self.log("⚠️ Sticky Session mode failed, thử RANDOM IP mode...", "WARN")
                            if not old_username.endswith('-rotate'):
                                new_username = old_username + '-rotate'
                            else:
                                new_username = old_username
                            fallback_mode = "Random IP"

                        if new_username != old_username:
                            # Kill everything
                            self._kill_chrome()
                            self.close()
                            time.sleep(2)

                            # Switch mode
                            rotating.base_username = new_username
                            self._is_random_ip_mode = new_username.endswith('-rotate')
                            self.log(f"  → Đổi từ '{old_username}' sang '{new_username}'")

                            if not self._is_random_ip_mode:
                                self.log(f"  → Sticky Session ID: {self._rotating_session_id}")

                            # Restart với mode mới
                            if self._start_chrome():
                                # Retry navigation
                                try:
                                    self.driver.get(target_url)
                                    time.sleep(3)
                                    if self.driver.url and self.driver.url != "about:blank":
                                        self.log(f"✓ {fallback_mode} OK! URL: {self.driver.url}")
                                        nav_success = True
                                        fallback_tried = True
                                except Exception as e:
                                    self.log(f"  → {fallback_mode} cũng fail: {e}", "ERROR")
                                    fallback_tried = True

                except Exception as fallback_err:
                    self.log(f"  → Fallback error: {fallback_err}", "ERROR")

            if not nav_success:
                if fallback_tried:
                    self.log("✗ Cả hai proxy modes đều fail!", "ERROR")
                else:
                    self.log("✗ Không thể vào trang Google Flow", "ERROR")
                return False

        # 4. Auto setup project (click "Dự án mới" + chọn "Tạo hình ảnh")
        if wait_for_project:
            # Kiểm tra đã ở trong project chưa
            if "/project/" not in self.driver.url:
                # Nếu có project_url nhưng bị redirect về trang chủ → retry vào project cũ
                if project_url and "/project/" in project_url:
                    self.log(f"⚠️ Bị redirect, retry vào project cũ...")
                    # Retry vào project URL (max 3 lần)
                    for retry in range(3):
                        time.sleep(2)
                        self.driver.get(project_url)
                        time.sleep(3)
                        if "/project/" in self.driver.url:
                            self._current_project_url = self.driver.url
                            self.log(f"✓ Vào lại project thành công!")
                            break
                        self.log(f"  → Retry {retry+1}/3...")
                    else:
                        self.log("✗ Không vào được project cũ, session có thể hết hạn", "ERROR")
                        return False
                else:
                    # Không có project URL → tạo mới
                    self.log("Auto setup project...")
                    if not self._auto_setup_project(timeout):
                        return False
                    # Lưu project URL sau khi tạo mới
                    if "/project/" in self.driver.url:
                        self._current_project_url = self.driver.url
                        self.log(f"  → New project URL saved")
            else:
                self.log("✓ Đã ở trong project!")
                # Chọn "Tạo hình ảnh" từ dropdown
                time.sleep(1)
                for j in range(10):
                    result = self.driver.run_js(JS_SELECT_IMAGE_MODE)
                    if result == 'CLICKED':
                        self.log("✓ Chọn 'Tạo hình ảnh'")
                        time.sleep(1)
                        break
                    time.sleep(0.5)

        # 5. Đợi textarea sẵn sàng
        self.log("Đợi project load...")
        for i in range(30):
            if self._find_textarea():
                self.log("✓ Project đã sẵn sàng!")
                break
            time.sleep(1)
        else:
            self.log("✗ Timeout - không tìm thấy textarea", "ERROR")
            return False

        # 6. Warm up session (tạo 1 ảnh trong Chrome để activate)
        if warm_up:
            if not self._warm_up_session():
                self.log("⚠️ Warm up không thành công, tiếp tục...", "WARN")

        # 7. Inject interceptor (SAU khi warm up)
        self.log("Inject interceptor...")
        self._reset_tokens()
        result = self.driver.run_js(JS_INTERCEPTOR)
        self.log(f"✓ Interceptor: {result}")

        self._ready = True
        return True

    def _find_textarea(self):
        """Tìm textarea input (không click)."""
        for sel in ["tag:textarea", "css:textarea"]:
            try:
                el = self.driver.ele(sel, timeout=2)
                if el:
                    return el
            except:
                pass
        return None

    def _click_textarea(self):
        """
        Click vào textarea để focus - QUAN TRỌNG để nhập prompt.
        Dùng JavaScript với MouseEvent để đảm bảo click chính xác.
        """
        try:
            result = self.driver.run_js("""
                (function() {
                    var textarea = document.querySelector('textarea');
                    if (!textarea) return 'not_found';

                    // Scroll vào view
                    textarea.scrollIntoView({block: 'center', behavior: 'instant'});

                    // Lấy vị trí giữa textarea
                    var rect = textarea.getBoundingClientRect();
                    var centerX = rect.left + rect.width / 2;
                    var centerY = rect.top + rect.height / 2;

                    // Tạo và dispatch mousedown event
                    var mousedown = new MouseEvent('mousedown', {
                        bubbles: true, cancelable: true, view: window,
                        clientX: centerX, clientY: centerY
                    });
                    textarea.dispatchEvent(mousedown);

                    // Tạo và dispatch mouseup event
                    var mouseup = new MouseEvent('mouseup', {
                        bubbles: true, cancelable: true, view: window,
                        clientX: centerX, clientY: centerY
                    });
                    textarea.dispatchEvent(mouseup);

                    // Tạo và dispatch click event
                    var click = new MouseEvent('click', {
                        bubbles: true, cancelable: true, view: window,
                        clientX: centerX, clientY: centerY
                    });
                    textarea.dispatchEvent(click);

                    // Focus
                    textarea.focus();

                    return 'clicked';
                })();
            """)

            if result == 'clicked':
                self.log("✓ Clicked textarea (JS)")
                time.sleep(0.3)
                return True
            elif result == 'not_found':
                self.log("✗ Textarea not found", "ERROR")
            return False
        except Exception as e:
            self.log(f"⚠️ Click textarea error: {e}", "WARN")
            return False

    def _reset_tokens(self):
        """Reset captured tokens trong browser."""
        self.driver.run_js("""
            window.__interceptReady = false;
            window._tk = null;
            window._pj = null;
            window._xbv = null;
            window._rct = null;
            window._payload = null;
            window._sid = null;
            window._url = null;
            window._response = null;
            window._responseError = null;
            window._requestPending = false;
            window._customPayload = null;
            window._videoResponse = null;
            window._videoError = null;
            window._videoPending = false;
        """)

    def _capture_tokens(self, prompt: str, timeout: int = 10) -> bool:
        """
        Gửi prompt để capture tất cả tokens cần thiết.
        Giống batch_generator.py get_tokens().

        Args:
            prompt: Prompt để gửi
            timeout: Timeout đợi tokens (giây)

        Returns:
            True nếu capture thành công
        """
        self.log(f"    Prompt: {prompt[:50]}...")

        # QUAN TRỌNG: Reset tokens trước khi capture để đợi giá trị MỚI
        # Nếu không reset, sẽ lấy tokens cũ từ lần capture trước!
        self.driver.run_js("""
            window._rct = null;
            window._payload = null;
            window._url = null;
        """)

        # Tìm và gửi prompt
        textarea = self._find_textarea()
        if not textarea:
            self.log("✗ Không tìm thấy textarea", "ERROR")
            return False

        textarea.clear()
        time.sleep(0.2)
        textarea.input(prompt)
        time.sleep(0.3)
        textarea.input('\n')  # Enter để gửi
        self.log("    ✓ Đã gửi, đợi capture...")

        # Đợi 3 giây theo hướng dẫn (giống batch_generator.py)
        time.sleep(3)

        # Đọc tokens từ window variables
        for i in range(timeout):
            tokens = self.driver.run_js("""
                return {
                    tk: window._tk,
                    pj: window._pj,
                    xbv: window._xbv,
                    rct: window._rct,
                    sid: window._sid,
                    url: window._url
                };
            """)

            # Debug output (giống batch_generator.py)
            if i == 0 or i == 5:
                self.log(f"    [DEBUG] Bearer: {'YES' if tokens.get('tk') else 'NO'}")
                self.log(f"    [DEBUG] recaptcha: {'YES' if tokens.get('rct') else 'NO'}")
                self.log(f"    [DEBUG] projectId: {'YES' if tokens.get('pj') else 'NO'}")
                self.log(f"    [DEBUG] URL: {'YES' if tokens.get('url') else 'NO'}")

            if tokens.get("tk") and tokens.get("rct"):
                self.bearer_token = f"Bearer {tokens['tk']}"
                self.project_id = tokens.get("pj")
                self.session_id = tokens.get("sid")
                self.recaptcha_token = tokens.get("rct")
                self.x_browser_validation = tokens.get("xbv")
                self.captured_url = tokens.get("url")

                self.log("    ✓ Got Bearer token!")
                self.log("    ✓ Got recaptchaToken!")
                if self.captured_url:
                    self.log(f"    ✓ Captured URL: {self.captured_url[:60]}...")
                return True

            time.sleep(1)

        self.log("    ✗ Không lấy được đủ tokens", "ERROR")
        return False

    def refresh_recaptcha(self, prompt: str) -> bool:
        """
        Gửi prompt mới để lấy fresh recaptchaToken.
        Giống batch_generator.py refresh_recaptcha().

        Args:
            prompt: Prompt để trigger recaptcha

        Returns:
            True nếu thành công
        """
        # Reset captured data (chỉ rct - giống batch_generator.py)
        self.driver.run_js("window._rct = null;")

        textarea = self._find_textarea()
        if not textarea:
            return False

        textarea.clear()
        time.sleep(0.2)
        textarea.input(prompt)
        time.sleep(0.3)
        textarea.input('\n')

        # Đợi 3 giây
        time.sleep(3)

        # Wait for new token
        for i in range(10):
            rct = self.driver.run_js("return window._rct;")
            if rct:
                self.recaptcha_token = rct
                self.log("    ✓ Got new recaptchaToken!")
                return True
            time.sleep(1)

        self.log("    ✗ Không lấy được recaptchaToken mới", "ERROR")
        return False

    def call_api(self, prompt: str = None, num_images: int = 1, image_inputs: Optional[List[Dict]] = None) -> Tuple[List[GeneratedImage], Optional[str]]:
        """
        Gọi API với captured tokens.
        Giống batch_generator.py - lấy payload từ browser mỗi lần.

        Args:
            prompt: Prompt (nếu None, dùng payload đã capture)
            num_images: Số ảnh cần tạo (mặc định 1)
            image_inputs: List of reference images [{name, inputType}]

        Returns:
            Tuple[list of GeneratedImage, error message]
        """
        if not self.captured_url:
            return [], "No URL captured"

        url = self.captured_url
        self.log(f"→ URL: {url[:80]}...")

        # Lấy payload gốc từ Chrome (giống batch_generator.py)
        original_payload = self.driver.run_js("return window._payload;")
        if not original_payload:
            return [], "No payload captured"

        # Sửa số ảnh trong payload - FORCE đúng số lượng
        # API dùng số lượng items trong array "requests", mỗi request = 1 ảnh
        try:
            payload_data = json.loads(original_payload)

            if "requests" in payload_data and payload_data["requests"]:
                old_count = len(payload_data["requests"])
                if old_count > num_images:
                    # Chỉ giữ lại num_images requests đầu tiên
                    payload_data["requests"] = payload_data["requests"][:num_images]
                    self.log(f"   → requests: {old_count} → {num_images}")
                elif old_count < num_images:
                    self.log(f"   → requests: {old_count} (giữ nguyên, không đủ để tăng)")
                else:
                    self.log(f"   → requests: {old_count} (đã đúng)")

                # === INJECT imageInputs cho reference images ===
                if image_inputs:
                    for req in payload_data["requests"]:
                        req["imageInputs"] = image_inputs
                    self.log(f"   → Injected {len(image_inputs)} reference image(s) into payload")

            original_payload = json.dumps(payload_data)
        except Exception as e:
            self.log(f"⚠️ Không sửa được payload: {e}", "WARN")

        # Headers
        headers = {
            "Authorization": self.bearer_token,
            "Content-Type": "text/plain;charset=UTF-8",
            "Origin": "https://labs.google",
            "Referer": "https://labs.google/",
        }
        if self.x_browser_validation:
            headers["x-browser-validation"] = self.x_browser_validation

        self.log(f"→ Calling API with captured payload ({len(original_payload)} chars)...")

        try:
            # API call qua proxy bridge (127.0.0.1:port) để IP match với Chrome
            # QUAN TRỌNG: Dùng bridge URL, KHÔNG dùng proxy trực tiếp (sẽ bị 407)
            proxies = None
            if self._use_webshare and hasattr(self, '_bridge_port') and self._bridge_port:
                bridge_url = f"http://127.0.0.1:{self._bridge_port}"
                proxies = {"http": bridge_url, "https": bridge_url}
                self.log(f"→ Using proxy bridge: {bridge_url}")

            resp = requests.post(
                url,
                headers=headers,
                data=original_payload,
                timeout=120,
                proxies=proxies
            )

            if resp.status_code == 200:
                return self._parse_response(resp.json()), None
            else:
                error = f"{resp.status_code}: {resp.text[:200]}"
                self.log(f"✗ API Error: {error}", "ERROR")
                return [], error

        except Exception as e:
            self.log(f"✗ Request error: {e}", "ERROR")
            return [], str(e)

    def _parse_response(self, data: Dict) -> List[GeneratedImage]:
        """Parse API response để lấy images."""
        images = []

        for media_item in data.get("media", data.get("images", [])):
            if isinstance(media_item, dict):
                gen_image = media_item.get("image", {}).get("generatedImage", media_item)
                img = GeneratedImage()

                # Base64 encoded image
                if gen_image.get("encodedImage"):
                    img.base64_data = gen_image["encodedImage"]

                # URL
                if gen_image.get("fifeUrl"):
                    img.url = gen_image["fifeUrl"]

                # Media name (for video generation) - check multiple locations
                img.media_name = (
                    media_item.get("name") or
                    media_item.get("mediaName") or
                    gen_image.get("name") or
                    gen_image.get("mediaName") or
                    ""
                )

                # Seed
                if gen_image.get("seed"):
                    img.seed = gen_image["seed"]

                if img.base64_data or img.url:
                    images.append(img)

        self.log(f"✓ Parsed {len(images)} images")
        return images

    def generate_image_forward(
        self,
        prompt: str,
        num_images: int = 1,
        image_inputs: Optional[List[Dict]] = None,
        timeout: int = 120
    ) -> Tuple[List[GeneratedImage], Optional[str]]:
        """
        Generate image bằng MODIFY MODE - giữ nguyên Chrome's payload.

        Flow:
        1. Type FULL prompt vào Chrome textarea
        2. Chrome tạo payload với model mới nhất + prompt enhancement + reCAPTCHA
        3. Interceptor chỉ THÊM imageInputs (nếu có) vào payload
        4. Forward request với tất cả settings gốc của Chrome
        5. Capture response

        Ưu điểm so với Custom Payload:
        - Dùng model mới nhất của Google (không hardcode GEM_PIX)
        - Giữ prompt enhancement của Chrome
        - Giữ tất cả settings/parameters của Chrome
        - Chất lượng ảnh tốt hơn

        Args:
            prompt: Prompt mô tả ảnh
            num_images: Số ảnh cần tạo
            image_inputs: Reference images [{name, inputType}] với name = media_id
            timeout: Timeout đợi response (giây)

        Returns:
            Tuple[list of GeneratedImage, error message]
        """
        if not self._ready:
            return [], "API chưa setup! Gọi setup() trước."

        # 1. Reset state
        self.driver.run_js("""
            window._response = null;
            window._responseError = null;
            window._requestPending = false;
            window._modifyConfig = null;
        """)

        # 2. MODIFY MODE: Luôn set imageCount=1, thêm imageInputs nếu có
        # Chrome sẽ dùng model mới nhất, prompt enhancement, tất cả settings
        modify_config = {
            "imageCount": num_images if num_images else 1  # Luôn giới hạn số ảnh
        }

        if image_inputs and len(image_inputs) > 0:
            modify_config["imageInputs"] = image_inputs
            self.driver.run_js(f"window._modifyConfig = {json.dumps(modify_config)};")
            self.log(f"→ MODIFY MODE: {len(image_inputs)} reference image(s), {modify_config['imageCount']} image(s)")
        else:
            self.driver.run_js(f"window._modifyConfig = {json.dumps(modify_config)};")
            self.log(f"→ MODIFY MODE: {modify_config['imageCount']} image(s), no reference")

        # 3. Tìm textarea và nhập prompt (giống phiên bản hoạt động)
        self.log(f"→ Prompt: {prompt[:50]}...")
        textarea = self._find_textarea()
        if not textarea:
            return [], "Không tìm thấy textarea"

        # Click vào textarea trước (dùng DrissionPage click)
        try:
            textarea.click()
            time.sleep(0.3)
        except:
            pass

        textarea.clear()
        time.sleep(0.2)
        textarea.input(prompt)  # Type FULL prompt

        # Đợi 2 giây để reCAPTCHA chuẩn bị token
        time.sleep(2)

        # Nhấn Enter để gửi
        textarea.input('\n')
        self.log("→ Pressed Enter to send")
        self.log("→ Chrome đang gửi request...")

        # 4. Đợi response từ browser (không gọi API riêng!)
        start_time = time.time()
        while time.time() - start_time < timeout:
            result = self.driver.run_js("""
                return {
                    pending: window._requestPending,
                    response: window._response,
                    error: window._responseError
                };
            """)

            if result.get('error'):
                error_msg = result['error']
                self.log(f"✗ Browser request error: {error_msg}", "ERROR")
                return [], error_msg

            if result.get('response'):
                response_data = result['response']

                # Check for API errors in response
                if isinstance(response_data, dict):
                    if response_data.get('error'):
                        error_info = response_data['error']
                        error_msg = f"{error_info.get('code', 'unknown')}: {error_info.get('message', str(error_info))}"
                        self.log(f"✗ API Error: {error_msg}", "ERROR")
                        return [], error_msg

                    # Parse successful response
                    images = self._parse_response(response_data)
                    self.log(f"✓ Got {len(images)} images from browser!")

                    # Clear modifyConfig for next request
                    self.driver.run_js("window._modifyConfig = null;")

                    # Đợi 3 giây để reCAPTCHA có thời gian regenerate token mới
                    # Nếu không đợi, request tiếp theo sẽ bị 403
                    time.sleep(3)

                    return images, None

            # Still pending or no response yet
            time.sleep(0.5)

        self.log("✗ Timeout đợi response từ browser", "ERROR")
        return [], "Timeout waiting for browser response"

    def generate_image(
        self,
        prompt: str,
        save_dir: Optional[Path] = None,
        filename: str = None,
        max_retries: int = 3,
        image_inputs: Optional[List[Dict]] = None
    ) -> Tuple[bool, List[GeneratedImage], Optional[str]]:
        """
        Generate image - full flow với retry khi gặp 403.

        Args:
            prompt: Prompt mô tả ảnh
            save_dir: Thư mục lưu ảnh (optional)
            filename: Tên file (không có extension)
            max_retries: Số lần retry khi gặp 403 (mặc định 3)
            image_inputs: List of reference images [{name, inputType}]

        Returns:
            Tuple[success, list of images, error]
        """
        if not self._ready:
            return False, [], "API chưa setup! Gọi setup() trước."

        last_error = None

        # Log reference images if provided
        if image_inputs:
            self.log(f"→ Using {len(image_inputs)} reference image(s)")

        for attempt in range(max_retries):
            # SỬ DỤNG FORWARD MODE - không cancel request
            # reCAPTCHA token được dùng ngay (0.05s không bị expired)
            images, error = self.generate_image_forward(
                prompt=prompt,
                num_images=1,
                image_inputs=image_inputs,
                timeout=90
            )

            if error:
                last_error = error

                # === ERROR 253/429: Quota exceeded ===
                # Close Chrome, đổi session/proxy, mở lại
                if "253" in error or "429" in error or "quota" in error.lower() or "exceeds" in error.lower():
                    self.log(f"⚠️ QUOTA EXCEEDED - Đổi session và restart...", "WARN")

                    # Close Chrome của tool (không kill tất cả Chrome)
                    self._kill_chrome()
                    self.close()

                    # Rotating mode: Restart Chrome với IP mới
                    if hasattr(self, '_is_rotating_mode') and self._is_rotating_mode:
                        if hasattr(self, '_is_random_ip_mode') and self._is_random_ip_mode:
                            # Random IP mode: Chỉ cần restart Chrome, Webshare tự đổi IP
                            self.log(f"  → 🎲 Random IP: Restart Chrome để lấy IP mới...")
                        else:
                            # Sticky Session mode: Tăng session ID
                            self._rotating_session_id += 1
                            # Wrap around nếu hết dải
                            if self._rotating_session_id > self._session_range_end:
                                self._rotating_session_id = self._session_range_start
                                self.log(f"  → ♻️ Hết dải, quay lại session {self._rotating_session_id}")
                            else:
                                self.log(f"  → Sticky: Đổi sang session {self._rotating_session_id}")
                            # Lưu session ID để tiếp tục lần sau
                            _save_last_session_id(self._machine_id, self.worker_id, self._rotating_session_id)

                        if attempt < max_retries - 1:
                            time.sleep(3)
                            if self.setup(project_url=getattr(self, '_current_project_url', None)):
                                continue
                        return False, [], f"Quota exceeded sau {max_retries} lần thử"

                    # Direct mode: Rotate proxy
                    if self._use_webshare and self._webshare_proxy:
                        success, msg = self._webshare_proxy.rotate_ip(self.worker_id, "253 Quota")
                        self.log(f"  → Webshare rotate [Worker {self.worker_id}]: {msg}", "WARN")

                        if success and attempt < max_retries - 1:
                            # Mở Chrome mới với proxy mới
                            self.log("  → Mở Chrome mới với proxy mới...")
                            time.sleep(3)  # Đợi proxy ổn định
                            if self.setup(project_url=getattr(self, '_current_project_url', None)):
                                continue
                            else:
                                return False, [], "Không setup được Chrome mới sau khi đổi proxy"

                    # Không có proxy hoặc rotate thất bại
                    if attempt < max_retries - 1:
                        self.log(f"  → Đợi 30s rồi thử lại với Chrome mới...", "WARN")
                        time.sleep(30)
                        if self.setup(project_url=getattr(self, '_current_project_url', None)):
                            continue

                    return False, [], f"Quota exceeded sau {max_retries} lần thử. Hãy đổi proxy hoặc tài khoản."

                # Nếu lỗi 500 (Internal Error), retry với delay
                if "500" in error:
                    self.log(f"⚠️ 500 Internal Error (attempt {attempt+1}/{max_retries})", "WARN")
                    if attempt < max_retries - 1:
                        self.log(f"  → Đợi 3s rồi retry...")
                        time.sleep(3)
                        continue
                    else:
                        return False, [], error

                # Nếu lỗi 403, xoay IP và retry
                if "403" in error:
                    self.log(f"⚠️ 403 error (attempt {attempt+1}/{max_retries})", "WARN")

                    # === ROTATING ENDPOINT MODE ===
                    # Restart Chrome để đổi IP
                    if hasattr(self, '_is_rotating_mode') and self._is_rotating_mode:
                        if hasattr(self, '_is_random_ip_mode') and self._is_random_ip_mode:
                            # Random IP mode: Chỉ cần restart Chrome, Webshare tự đổi IP
                            self.log(f"  → 🎲 Random IP: Restart Chrome để lấy IP mới...")
                        else:
                            # Sticky Session mode: Tăng session ID
                            self._rotating_session_id += 1
                            # Wrap around nếu hết dải
                            if self._rotating_session_id > self._session_range_end:
                                self._rotating_session_id = self._session_range_start
                                self.log(f"  → ♻️ Hết dải, quay lại session {self._rotating_session_id}")
                            else:
                                self.log(f"  → Sticky: Đổi sang session {self._rotating_session_id}")
                            # Lưu session ID để tiếp tục lần sau
                            _save_last_session_id(self._machine_id, self.worker_id, self._rotating_session_id)

                        if attempt < max_retries - 1:
                            # Restart Chrome với IP mới
                            self._kill_chrome()
                            self.close()
                            time.sleep(2)
                            self.log(f"  → Restart Chrome...")
                            if self.setup(project_url=getattr(self, '_current_project_url', None)):
                                continue
                            else:
                                return False, [], "Không restart được Chrome"
                        else:
                            return False, [], error

                    # === DIRECT PROXY LIST MODE ===
                    # Cần xoay proxy và restart Chrome
                    if self._use_webshare and self._webshare_proxy:
                        # Gọi Webshare API để xoay IP cho worker (lưu proxy cũ vào blocked 48h)
                        success, msg = self._webshare_proxy.rotate_ip(self.worker_id, "403 reCAPTCHA")
                        self.log(f"  → Webshare rotate [Worker {self.worker_id}]: {msg}", "WARN")

                        if success and attempt < max_retries - 1:
                            # Restart Chrome để nhận IP mới
                            self.log("  → Restart Chrome với IP mới...")
                            if self.restart_chrome():
                                time.sleep(3)  # Đợi Chrome ổn định
                                continue
                            else:
                                return False, [], "Không restart được Chrome sau khi xoay IP"

                    if attempt < max_retries - 1:
                        self.log(f"  → Đợi 5s rồi retry...", "WARN")
                        time.sleep(5)
                        continue
                    else:
                        return False, [], error

                # === TIMEOUT ERROR: Tương tự 403, cần reset Chrome và đổi proxy ===
                if "timeout" in error.lower():
                    self.log(f"⚠️ Timeout error (attempt {attempt+1}/{max_retries}) - Reset Chrome...", "WARN")

                    # Kill Chrome và đổi proxy
                    self._kill_chrome()
                    self.close()

                    # === ROTATING ENDPOINT MODE ===
                    if hasattr(self, '_is_rotating_mode') and self._is_rotating_mode:
                        if hasattr(self, '_is_random_ip_mode') and self._is_random_ip_mode:
                            self.log(f"  → 🎲 Random IP: Restart Chrome để lấy IP mới...")
                        else:
                            # Sticky Session mode: Tăng session ID
                            self._rotating_session_id += 1
                            if self._rotating_session_id > self._session_range_end:
                                self._rotating_session_id = self._session_range_start
                                self.log(f"  → ♻️ Hết dải, quay lại session {self._rotating_session_id}")
                            else:
                                self.log(f"  → Sticky: Đổi sang session {self._rotating_session_id}")
                            _save_last_session_id(self._machine_id, self.worker_id, self._rotating_session_id)

                        if attempt < max_retries - 1:
                            time.sleep(3)
                            if self.setup(project_url=getattr(self, '_current_project_url', None)):
                                continue
                            else:
                                return False, [], "Không restart được Chrome sau timeout"
                        else:
                            return False, [], error

                    # === DIRECT PROXY LIST MODE ===
                    if self._use_webshare and self._webshare_proxy:
                        success, msg = self._webshare_proxy.rotate_ip(self.worker_id, "Timeout")
                        self.log(f"  → Webshare rotate [Worker {self.worker_id}]: {msg}", "WARN")

                        if success and attempt < max_retries - 1:
                            self.log("  → Restart Chrome với IP mới...")
                            time.sleep(3)
                            if self.setup(project_url=getattr(self, '_current_project_url', None)):
                                continue
                            else:
                                return False, [], "Không restart được Chrome sau khi đổi proxy"

                    if attempt < max_retries - 1:
                        self.log(f"  → Đợi 5s rồi retry...", "WARN")
                        time.sleep(5)
                        if self.setup(project_url=getattr(self, '_current_project_url', None)):
                            continue
                    return False, [], error

                # Lỗi khác, không retry
                return False, [], error

            if not images:
                return False, [], "Không có ảnh trong response"

            # Thành công!
            break
        else:
            return False, [], last_error or "Max retries exceeded"

        # 3. Download và save nếu cần
        if save_dir:
            save_dir = Path(save_dir)
            save_dir.mkdir(parents=True, exist_ok=True)

            for i, img in enumerate(images):
                fname = filename or f"image_{int(time.time())}"
                if len(images) > 1:
                    fname = f"{fname}_{i+1}"

                if img.base64_data:
                    img_path = save_dir / f"{fname}.png"
                    img_path.write_bytes(base64.b64decode(img.base64_data))
                    img.local_path = img_path
                    self.log(f"✓ Saved: {img_path.name}")
                elif img.url:
                    # Download from URL
                    try:
                        proxies = None
                        if self._use_webshare and self._webshare_proxy:
                            proxies = self._webshare_proxy.get_proxies()
                        resp = requests.get(img.url, timeout=60, proxies=proxies)
                        if resp.status_code == 200:
                            img_path = save_dir / f"{fname}.png"
                            img_path.write_bytes(resp.content)
                            img.local_path = img_path
                            img.base64_data = base64.b64encode(resp.content).decode()
                            self.log(f"✓ Downloaded: {img_path.name}")
                    except Exception as e:
                        self.log(f"✗ Download error: {e}", "WARN")

        return True, images, None

    def generate_batch(
        self,
        prompts: List[str],
        save_dir: Path,
        on_progress: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        Generate batch nhiều ảnh.

        Args:
            prompts: Danh sách prompts
            save_dir: Thư mục lưu ảnh
            on_progress: Callback(index, total, success, error)

        Returns:
            Dict với thống kê
        """
        results = {
            "total": len(prompts),
            "success": 0,
            "failed": 0,
            "images": []
        }

        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

        for i, prompt in enumerate(prompts):
            self.log(f"\n[{i+1}/{len(prompts)}] {prompt[:50]}...")

            # FORWARD MODE: Không cancel request, reCAPTCHA token còn fresh
            images, error = self.generate_image_forward(
                prompt=prompt,
                num_images=1,
                timeout=90
            )

            if error:
                results["failed"] += 1
                if on_progress:
                    on_progress(i+1, len(prompts), False, error)

                # Token hết hạn → dừng
                if "401" in error:
                    self.log("Bearer token hết hạn!", "ERROR")
                    break
                continue

            if images:
                # Save images
                for j, img in enumerate(images):
                    fname = f"batch_{i+1:03d}_{j+1}"
                    if img.base64_data:
                        img_path = save_dir / f"{fname}.png"
                        img_path.write_bytes(base64.b64decode(img.base64_data))
                        img.local_path = img_path

                results["success"] += 1
                results["images"].extend(images)
                if on_progress:
                    on_progress(i+1, len(prompts), True, None)
            else:
                results["failed"] += 1
                if on_progress:
                    on_progress(i+1, len(prompts), False, "No images")

            time.sleep(1)  # Rate limit

        self.log(f"\n{'='*50}")
        self.log(f"DONE: {results['success']}/{results['total']}")
        return results

    def generate_video(
        self,
        media_id: str,
        prompt: str = "Subtle motion, cinematic, slow movement",
        aspect_ratio: str = "VIDEO_ASPECT_RATIO_LANDSCAPE",
        video_model: str = "veo_3_0_r2v_fast_ultra",
        max_wait: int = 300,
        max_retries: int = 3
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Tạo video từ ảnh (I2V) - CÓ RETRY VỚI 403/QUOTA HANDLING như generate_image.

        Args:
            media_id: Media ID của ảnh (từ generate_image)
            prompt: Prompt mô tả chuyển động
            aspect_ratio: Tỷ lệ video
            video_model: Model video (fast hoặc quality)
            max_wait: Thời gian chờ tối đa (giây)
            max_retries: Số lần retry khi gặp 403/quota (mặc định 3)

        Returns:
            Tuple[success, video_url, error]
        """
        if not self._ready:
            return False, None, "API chưa setup! Gọi setup() trước."

        if not media_id:
            return False, None, "Media ID không được để trống"

        self.log(f"[I2V] Creating video from media: {media_id[:50]}...")

        last_error = None

        for attempt in range(max_retries):
            # === QUAN TRỌNG: Capture/Refresh tokens mỗi lần retry ===
            if hasattr(self, 'driver') and self.driver:
                if not self.bearer_token or not self.project_id:
                    self.log("[I2V] Capturing full tokens (bearer, project_id, recaptcha)...")
                    capture_prompt = prompt[:30] if len(prompt) > 30 else prompt
                    if self._capture_tokens(capture_prompt):
                        self.log("[I2V] ✓ Got all tokens!")
                    else:
                        self.log("[I2V] ⚠️ Không capture được tokens", "WARN")
                        return False, None, "Không capture được tokens từ Chrome"
                else:
                    self.log("[I2V] Refreshing recaptcha token...")
                    if self.refresh_recaptcha(prompt[:30] if len(prompt) > 30 else prompt):
                        self.log("[I2V] ✓ Got fresh recaptcha token")
                    else:
                        self.log("[I2V] ⚠️ Không refresh được recaptcha", "WARN")
            else:
                self.log("[I2V] Token mode - dùng cached recaptcha")

            # Build request payload
            import uuid
            session_id = f";{int(time.time() * 1000)}"
            scene_id = str(uuid.uuid4())
            recaptcha = getattr(self, 'recaptcha_token', '') or ''

            request_data = {
                "aspectRatio": aspect_ratio,
                "metadata": {"sceneId": scene_id},
                "referenceImages": [{
                    "imageUsageType": "IMAGE_USAGE_TYPE_ASSET",
                    "mediaId": media_id
                }],
                "seed": int(time.time()) % 100000,
                "textInput": {"prompt": prompt},
                "videoModelKey": video_model
            }

            payload = {
                "clientContext": {
                    "projectId": self.project_id,
                    "recaptchaToken": recaptcha,
                    "sessionId": session_id,
                    "tool": "PINHOLE",
                    "userPaygateTier": "PAYGATE_TIER_TWO"
                },
                "requests": [request_data]
            }

            self.log(f"[I2V] recaptchaToken: {'có' if recaptcha else 'KHÔNG CÓ!'}")

            # Video API - project_id trong payload, KHÔNG trong URL
            url = "https://aisandbox-pa.googleapis.com/v1/video:batchAsyncGenerateVideoReferenceImages"

            headers = {
                "Authorization": self.bearer_token,
                "Content-Type": "application/json",
                "Origin": "https://labs.google",
                "Referer": "https://labs.google/",
            }
            if self.x_browser_validation:
                headers["x-browser-validation"] = self.x_browser_validation

            self.log(f"[I2V] Calling video API (attempt {attempt+1}/{max_retries})...")

            try:
                proxies = None
                if self._use_webshare and hasattr(self, '_bridge_port') and self._bridge_port:
                    bridge_url = f"http://127.0.0.1:{self._bridge_port}"
                    proxies = {"http": bridge_url, "https": bridge_url}

                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=60,
                    proxies=proxies
                )

                if resp.status_code != 200:
                    error = f"{resp.status_code}: {resp.text[:200]}"
                    last_error = error
                    self.log(f"[I2V] API Error: {error}", "ERROR")

                    # Project URL cho retry - dùng project_id hiện tại
                    retry_project_url = f"https://labs.google/fx/vi/tools/flow/project/{self.project_id}"

                    # === ERROR 253/403: Quota exceeded ===
                    if "253" in error or "quota" in error.lower() or "exceeds" in error.lower():
                        self.log(f"[I2V] ⚠️ QUOTA EXCEEDED - Đổi proxy...", "WARN")

                        self.close()  # Chỉ close driver, không kill hết Chrome

                        if self._use_webshare and self._webshare_proxy:
                            success, msg = self._webshare_proxy.rotate_ip(self.worker_id, "I2V 253 Quota")
                            self.log(f"[I2V] → Webshare rotate: {msg}", "WARN")

                            if success and attempt < max_retries - 1:
                                self.log("[I2V] → Mở Chrome mới với proxy mới...")
                                time.sleep(3)
                                if self.setup(project_url=retry_project_url):
                                    continue
                                else:
                                    return False, None, "Không setup được Chrome mới sau khi đổi proxy"

                        if attempt < max_retries - 1:
                            self.log("[I2V] → Đợi 30s rồi thử lại...", "WARN")
                            time.sleep(30)
                            if self.setup(project_url=retry_project_url):
                                continue
                        return False, None, f"Quota exceeded sau {max_retries} lần thử"

                    # === 403 error ===
                    if "403" in error:
                        self.log(f"[I2V] ⚠️ 403 error (attempt {attempt+1}/{max_retries})", "WARN")

                        # === ROTATING ENDPOINT MODE ===
                        # Restart Chrome để đổi IP (giống như xử lý ảnh)
                        if hasattr(self, '_is_rotating_mode') and self._is_rotating_mode:
                            if hasattr(self, '_is_random_ip_mode') and self._is_random_ip_mode:
                                # Random IP mode: Chỉ cần restart Chrome, Webshare tự đổi IP
                                self.log(f"[I2V] → 🎲 Random IP: Restart Chrome để lấy IP mới...")
                            else:
                                # Sticky Session mode: Tăng session ID
                                self._rotating_session_id += 1
                                # Wrap around nếu hết dải
                                if self._rotating_session_id > self._session_range_end:
                                    self._rotating_session_id = self._session_range_start
                                    self.log(f"[I2V] → ♻️ Hết dải, quay lại session {self._rotating_session_id}")
                                else:
                                    self.log(f"[I2V] → Sticky: Đổi sang session {self._rotating_session_id}")
                                # Lưu session ID để tiếp tục lần sau
                                _save_last_session_id(self._machine_id, self.worker_id, self._rotating_session_id)

                            if attempt < max_retries - 1:
                                # Restart Chrome với IP mới
                                self._kill_chrome()
                                self.close()
                                time.sleep(2)
                                self.log(f"[I2V] → Restart Chrome...")
                                if self.setup(project_url=retry_project_url):
                                    continue
                                else:
                                    return False, None, "Không restart được Chrome"
                            else:
                                return False, None, error

                        # === DIRECT PROXY LIST MODE ===
                        # Cần xoay proxy và restart Chrome
                        if self._use_webshare and self._webshare_proxy:
                            success, msg = self._webshare_proxy.rotate_ip(self.worker_id, "I2V 403")
                            self.log(f"[I2V] → Webshare rotate: {msg}", "WARN")

                            if success and attempt < max_retries - 1:
                                # Restart Chrome với IP mới
                                self.log("[I2V] → Restart Chrome với IP mới...")
                                if self.restart_chrome():
                                    time.sleep(3)
                                    continue
                                else:
                                    return False, None, "Không restart được Chrome sau khi xoay IP"

                        if attempt < max_retries - 1:
                            self.log("[I2V] → Đợi 5s rồi retry...", "WARN")
                            time.sleep(5)
                            continue

                    # Other errors - simple retry
                    if attempt < max_retries - 1:
                        self.log(f"[I2V] → Retry in 5s...", "WARN")
                        time.sleep(5)
                        continue
                    return False, None, error

                result = resp.json()

                # Log full response để debug
                self.log(f"[I2V] Full response keys: {list(result.keys())}")
                self.log(f"[I2V] Response: {json.dumps(result)[:500]}")

                # Giống image gen - check nếu có video trực tiếp trong response
                # (không cần poll như image gen)
                if "media" in result or "generatedVideos" in result:
                    videos = result.get("generatedVideos", result.get("media", []))
                    if videos:
                        video_url = videos[0].get("video", {}).get("fifeUrl") or videos[0].get("fifeUrl")
                        if video_url:
                            self.log(f"[I2V] ✓ Video ready (no poll): {video_url[:60]}...")
                            return True, video_url, None

                operations = result.get("operations", [])

                if not operations:
                    if attempt < max_retries - 1:
                        time.sleep(5)
                        continue
                    return False, None, "No operations/videos in response"

                self.log(f"[I2V] Got {len(operations)} operations, polling for result...")

                op = operations[0]
                self.log(f"[I2V] Operation status: {op.get('status', 'unknown')}")

                # Truyền full operation data cho poll (không chỉ operation_id)
                video_url = self._poll_video_operation(op, headers, proxies, max_wait)

                if video_url:
                    self.log(f"[I2V] Video ready: {video_url[:60]}...")
                    return True, video_url, None
                else:
                    last_error = "Timeout waiting for video"
                    if attempt < max_retries - 1:
                        self.log("[I2V] → Timeout, will retry...", "WARN")
                        continue
                    return False, None, last_error

            except Exception as e:
                last_error = str(e)
                self.log(f"[I2V] Error: {e}", "ERROR")

                # Project URL cho retry
                retry_project_url = f"https://labs.google/fx/vi/tools/flow/project/{self.project_id}"

                # Check if exception contains 403/quota error
                if "253" in last_error or "quota" in last_error.lower() or "403" in last_error:
                    self.log("[I2V] ⚠️ Exception with 403/quota - Đổi proxy...", "WARN")
                    self.close()  # Chỉ close driver

                    if self._use_webshare and self._webshare_proxy:
                        success, msg = self._webshare_proxy.rotate_ip(self.worker_id, "I2V Exception")
                        self.log(f"[I2V] → Webshare rotate: {msg}", "WARN")

                        if success and attempt < max_retries - 1:
                            time.sleep(3)
                            if self.setup(project_url=retry_project_url):
                                continue

                if attempt < max_retries - 1:
                    time.sleep(5)
                    continue
                return False, None, last_error

        return False, None, last_error or "Failed after all retries"

    def _poll_video_operation(
        self,
        operation_data: Dict,
        headers: Dict,
        proxies: Optional[Dict],
        max_wait: int
    ) -> Optional[str]:
        """
        Poll cho video operation hoàn thành.
        Dùng POST với body chứa operation info (không phải GET).
        """
        url = "https://aisandbox-pa.googleapis.com/v1/video:batchCheckAsyncVideoGenerationStatus"

        # Payload gửi đi - chứa operation info từ response đầu
        poll_payload = {"operations": [operation_data]}

        start_time = time.time()
        poll_interval = 5  # Poll mỗi 5 giây

        poll_count = 0
        while time.time() - start_time < max_wait:
            try:
                poll_count += 1
                elapsed = int(time.time() - start_time)

                resp = requests.post(
                    url,
                    headers=headers,
                    json=poll_payload,
                    timeout=30,
                    proxies=proxies
                )

                if resp.status_code == 200:
                    data = resp.json()
                    operations = data.get("operations", [])

                    if operations:
                        op = operations[0]
                        status = op.get("status", "")

                        # Log progress
                        if poll_count == 1 or elapsed % 30 < poll_interval:
                            self.log(f"[I2V] Poll #{poll_count}: {status}, {elapsed}s")

                        # Check status
                        if "COMPLETE" in status or "SUCCESS" in status or "DONE" in status:
                            # Video xong - tìm URL (path: operation.metadata.video.fifeUrl)
                            video_url = op.get("operation", {}).get("metadata", {}).get("video", {}).get("fifeUrl")
                            if video_url:
                                return video_url

                            # Log full response để debug
                            self.log(f"[I2V] Complete but no URL: {json.dumps(op)[:500]}")
                            return None

                        elif "FAILED" in status or "ERROR" in status:
                            error_msg = op.get("error", {}).get("message", status)
                            self.log(f"[I2V] Video failed: {error_msg}", "ERROR")
                            return None

                        # Còn đang xử lý - update payload với status mới
                        poll_payload = {"operations": [op]}

                else:
                    self.log(f"[I2V] Poll error: HTTP {resp.status_code} - {resp.text[:200]}", "WARN")

                time.sleep(poll_interval)

            except Exception as e:
                self.log(f"[I2V] Poll error: {e}", "WARN")
                time.sleep(poll_interval)

        self.log(f"[I2V] Timeout after {max_wait}s", "ERROR")
        return None

    def close(self):
        """Đóng Chrome và proxy bridge."""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None

        # Dừng proxy bridge nếu có
        if self._proxy_bridge:
            try:
                self._proxy_bridge.stop()
                self.log("Proxy bridge stopped")
            except:
                pass
            self._proxy_bridge = None
            self._bridge_port = None

        self._ready = False

    def _kill_chrome_using_profile(self):
        """Tắt Chrome đang dùng profile này để tránh conflict."""
        import subprocess
        import platform

        profile_path = str(self.profile_dir.absolute())

        try:
            if platform.system() == 'Windows':
                # Windows: tìm và kill Chrome process dùng profile này
                result = subprocess.run(
                    ['wmic', 'process', 'where', "name='chrome.exe'", 'get', 'commandline,processid'],
                    capture_output=True, text=True, timeout=10
                )

                if result.returncode == 0:
                    lines = result.stdout.strip().split('\n')
                    for line in lines:
                        if profile_path.replace('/', '\\') in line or profile_path in line:
                            # Tìm PID ở cuối dòng
                            parts = line.strip().split()
                            if parts:
                                pid = parts[-1]
                                if pid.isdigit():
                                    subprocess.run(['taskkill', '/F', '/PID', pid],
                                                 capture_output=True, timeout=5)
                                    self.log(f"  Đã tắt Chrome cũ (PID: {pid})")
            else:
                # Linux/Mac: dùng pkill
                result = subprocess.run(
                    ['pgrep', '-f', profile_path],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    pids = result.stdout.strip().split('\n')
                    for pid in pids:
                        if pid.isdigit():
                            subprocess.run(['kill', '-9', pid], capture_output=True, timeout=5)
                            self.log(f"  Đã tắt Chrome cũ (PID: {pid})")

            # Đợi Chrome tắt hẳn
            time.sleep(1)

        except Exception as e:
            pass  # Không quan trọng nếu không kill được

    def _setup_proxy_auth(self):
        """
        Setup CDP để tự động xử lý proxy authentication.
        Dùng Network.setExtraHTTPHeaders với Proxy-Authorization.
        """
        if not hasattr(self, '_proxy_auth') or not self._proxy_auth:
            return

        username, password = self._proxy_auth
        if not username or not password:
            return

        try:
            import base64
            # Tạo Basic Auth header
            auth_string = f"{username}:{password}"
            auth_bytes = base64.b64encode(auth_string.encode()).decode()

            self.log(f"Setting up proxy auth for: {username}")

            # Thử dùng CDP Fetch API để handle auth challenges
            try:
                self.driver.run_cdp('Fetch.enable', handleAuthRequests=True)
                self.log("✓ CDP Fetch.enable OK")
            except Exception as e:
                self.log(f"CDP Fetch not supported: {e}", "WARN")

            self.log("✓ Proxy auth ready")
            self.log("  [!] Nếu vẫn lỗi, whitelist IP trên Webshare Dashboard")

        except Exception as e:
            self.log(f"[!] Proxy auth error: {e}", "WARN")
            self.log("    → Whitelist IP: 14.224.157.134 trên Webshare")

    def restart_chrome(self) -> bool:
        """
        Restart Chrome với proxy mới sau khi rotate.
        Proxy đã được rotate trước khi gọi hàm này.
        setup() sẽ lấy proxy mới từ manager.get_proxy_for_worker(worker_id).

        Returns:
            True nếu restart thành công
        """
        if self._use_webshare:
            # Lấy proxy mới để log
            from webshare_proxy import get_proxy_manager
            manager = get_proxy_manager()
            new_proxy = manager.get_proxy_for_worker(self.worker_id)
            if new_proxy:
                self.log(f"🔄 Restart Chrome [Worker {self.worker_id}] với proxy mới: {new_proxy.endpoint}")
            else:
                self.log(f"🔄 Restart Chrome [Worker {self.worker_id}]...")
        else:
            self.log("🔄 Restart Chrome với proxy mới...")

        # Close Chrome và proxy bridge hiện tại
        self.close()

        time.sleep(2)

        # Restart Chrome với proxy mới - setup() sẽ lấy proxy từ manager
        # Lấy saved project URL để vào lại đúng project
        saved_project_url = getattr(self, '_current_project_url', None)
        if saved_project_url:
            self.log(f"  → Reusing project: {saved_project_url[:50]}...")

        if self.setup(project_url=saved_project_url):
            self.log("✓ Chrome restarted thành công!")
            return True
        else:
            self.log("✗ Không restart được Chrome", "ERROR")
            return False

    @property
    def is_ready(self) -> bool:
        """Kiểm tra API đã sẵn sàng chưa."""
        return self._ready and self.driver is not None


# Factory function
def create_drission_api(
    profile_dir: str = "./chrome_profile",
    log_callback: Optional[Callable] = None,
    webshare_enabled: bool = True,  # BẬT Webshare by default
    worker_id: int = 0,  # Worker ID cho proxy rotation
    machine_id: int = 1,  # Máy số mấy (1-99) - tránh trùng session
) -> DrissionFlowAPI:
    """
    Tạo DrissionFlowAPI instance.

    Args:
        profile_dir: Thư mục Chrome profile
        log_callback: Callback để log
        webshare_enabled: Dùng Webshare proxy pool (default True)
        worker_id: Worker ID cho proxy rotation (mỗi Chrome có proxy riêng)
        machine_id: Máy số mấy (1-99), mỗi máy cách nhau 30000 session

    Returns:
        DrissionFlowAPI instance
    """
    return DrissionFlowAPI(
        profile_dir=profile_dir,
        log_callback=log_callback,
        webshare_enabled=webshare_enabled,
        worker_id=worker_id,
        machine_id=machine_id,
    )
