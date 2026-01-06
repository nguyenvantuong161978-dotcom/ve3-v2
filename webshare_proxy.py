#!/usr/bin/env python3
"""
Webshare.io Proxy Manager with Smart Rotation
==============================================
Quản lý pool 100 proxy từ Webshare với auto-rotation.

Features:
- Load proxy list từ file hoặc API Webshare
- Mỗi worker (Chrome) có proxy riêng
- Tự động xoay sang proxy khác khi bị block (sau 3 lần thử)
- Đánh dấu proxy bị block để tránh dùng lại trong 5 phút
- Thread-safe cho parallel mode

Usage:
    from webshare_proxy import init_proxy_manager, get_proxy_manager

    # Khởi tạo với API key
    manager = init_proxy_manager(api_key="your_api_key")

    # Hoặc load từ file
    manager = init_proxy_manager(proxy_file="config/proxies.txt")

    # Lấy proxy cho worker
    proxy = manager.get_proxy_for_worker(worker_id=0)

    # Xoay proxy khi bị block
    manager.rotate_worker_proxy(worker_id=0)
"""

import os
import requests
import time
import random
import threading
from typing import Optional, Dict, Tuple, List
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RotatingEndpointConfig:
    """
    Config cho Rotating Residential Endpoint mode.

    Webshare Rotating Residential format:
    - Username: {base_username}-{session_id}
    - VD: jhvbehdf-residential-1, jhvbehdf-residential-999
    - Mỗi session_id khác = IP khác
    - Để đổi IP mỗi request: dùng session_id ngẫu nhiên
    """
    host: str = "p.webshare.io"
    port: int = 80
    base_username: str = ""  # VD: jhvbehdf-residential
    password: str = ""
    _request_count: int = field(default=0, repr=False)

    @property
    def endpoint(self) -> str:
        return f"{self.host}:{self.port}"

    def get_username_for_session(self, session_id: int = None) -> str:
        """
        Tạo username với session ID.
        Mỗi session_id khác = IP khác.

        Nếu base_username kết thúc bằng '-rotate', trả về nguyên username
        (random IP mode - không cần quản lý session).
        """
        # Mode 2: Random IP (username ends with -rotate)
        if self.base_username.endswith('-rotate'):
            return self.base_username

        # Mode 1: Sticky session (append session ID)
        if session_id is None:
            # Auto increment để đổi IP mỗi request
            self._request_count += 1
            session_id = self._request_count
        return f"{self.base_username}-{session_id}"

    @property
    def username(self) -> str:
        """Username hiện tại (auto-rotate)."""
        return self.get_username_for_session()

    def get_proxy_url(self, session_id: int = None) -> str:
        """
        URL cho requests library.
        Mỗi lần gọi với session_id khác = IP khác.
        """
        username = self.get_username_for_session(session_id)
        if username and self.password:
            return f"http://{username}:{self.password}@{self.host}:{self.port}"
        return f"http://{self.host}:{self.port}"

    @property
    def proxy_url(self) -> str:
        """URL với auto-rotate session (mỗi lần gọi = IP mới)."""
        return self.get_proxy_url()


@dataclass
class ProxyInfo:
    """Thông tin một proxy."""
    host: str
    port: int
    username: str = ""
    password: str = ""
    blocked: bool = False
    last_used: float = 0
    fail_count: int = 0
    worker_id: int = -1  # Worker đang sử dụng proxy này (-1 = chưa ai dùng)

    @property
    def endpoint(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def proxy_url(self) -> str:
        """URL cho requests library."""
        if self.username and self.password:
            return f"http://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"http://{self.host}:{self.port}"

    @property
    def chrome_url(self) -> str:
        """URL cho Chrome --proxy-server (không có auth)."""
        return f"http://{self.host}:{self.port}"

    def reset(self):
        """Reset trạng thái proxy."""
        self.blocked = False
        self.fail_count = 0
        self.worker_id = -1

    @classmethod
    def from_string(cls, line: str) -> Optional['ProxyInfo']:
        """
        Parse proxy từ string.
        Formats:
        - IP:PORT:USER:PASS
        - IP:PORT (IP Authorization)
        - USER:PASS@IP:PORT
        """
        line = line.strip()
        if not line or line.startswith('#'):
            return None

        try:
            # Format: IP:PORT:USER:PASS
            if line.count(':') == 3:
                parts = line.split(':')
                return cls(
                    host=parts[0],
                    port=int(parts[1]),
                    username=parts[2],
                    password=parts[3]
                )
            # Format: USER:PASS@IP:PORT
            elif '@' in line:
                auth, endpoint = line.rsplit('@', 1)
                user, pwd = auth.split(':', 1)
                host, port = endpoint.split(':')
                return cls(host=host, port=int(port), username=user, password=pwd)
            # Format: IP:PORT (IP Authorization)
            elif line.count(':') == 1:
                host, port = line.split(':')
                return cls(host=host, port=int(port))
        except:
            pass
        return None


class WebshareProxyManager:
    """
    Quản lý pool proxy với auto-rotation cho mỗi worker.

    Mỗi Chrome (worker) có proxy riêng.
    Khi bị block (403) sau 3 lần thử → xoay sang proxy khác.
    Proxy bị block được lưu vào file và không dùng lại trong 48h.
    """

    API_BASE = "https://proxy.webshare.io/api/v2"
    MAX_FAIL_COUNT = 3  # Số lần fail trước khi xoay proxy
    BLOCK_TIMEOUT = 300  # 5 phút timeout trong memory
    BLOCK_DURATION = 120 * 60  # 120 phút - thời gian không dùng lại proxy bị block
    BLOCKED_FILE = "config/blocked_proxies.json"  # File lưu danh sách blocked

    def __init__(
        self,
        api_key: str = "",
        default_username: str = "",
        default_password: str = ""
    ):
        self.api_key = api_key
        self.default_username = default_username
        self.default_password = default_password

        self.proxies: List[ProxyInfo] = []
        self.rotate_count = 0
        self._lock = threading.Lock()

        # Mapping: worker_id -> proxy_index
        self._worker_proxy_map: Dict[int, int] = {}

        # Load blocked list từ file (persistent across sessions/machines)
        self._blocked_proxies: Dict[str, dict] = self._load_blocked_list()

        # === ROTATING ENDPOINT MODE ===
        # Nếu enabled, mỗi request tự động đổi IP (không cần quản lý pool)
        self.rotating_endpoint: Optional[RotatingEndpointConfig] = None
        self._use_rotating_endpoint: bool = False

    def _load_blocked_list(self) -> Dict[str, dict]:
        """Load danh sách proxy bị block từ file."""
        try:
            blocked_file = Path(self.BLOCKED_FILE)
            if blocked_file.exists():
                import json
                data = json.loads(blocked_file.read_text())
                # Cleanup: xóa proxies đã hết 48h
                now = time.time()
                cleaned = {}
                for endpoint, info in data.items():
                    blocked_at = info.get('blocked_at', 0)
                    if now - blocked_at < self.BLOCK_DURATION:
                        cleaned[endpoint] = info
                # Save cleaned list
                if len(cleaned) != len(data):
                    self._save_blocked_list(cleaned)
                    print(f"[Webshare] Cleaned {len(data) - len(cleaned)} expired blocked proxies")
                return cleaned
        except Exception as e:
            print(f"[Webshare] Error loading blocked list: {e}")
        return {}

    def _save_blocked_list(self, blocked_list: Dict[str, dict] = None):
        """Lưu danh sách proxy bị block vào file."""
        try:
            import json
            blocked_file = Path(self.BLOCKED_FILE)
            blocked_file.parent.mkdir(parents=True, exist_ok=True)
            data = blocked_list if blocked_list is not None else self._blocked_proxies
            blocked_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            print(f"[Webshare] Error saving blocked list: {e}")

    def _is_proxy_blocked(self, endpoint: str) -> bool:
        """Kiểm tra proxy có bị block trong 48h không."""
        if endpoint not in self._blocked_proxies:
            return False
        info = self._blocked_proxies[endpoint]
        blocked_at = info.get('blocked_at', 0)
        if time.time() - blocked_at >= self.BLOCK_DURATION:
            # Đã hết 48h, xóa khỏi danh sách
            del self._blocked_proxies[endpoint]
            self._save_blocked_list()
            return False
        return True

    def _add_to_blocked(self, endpoint: str, reason: str = "403"):
        """Thêm proxy vào danh sách bị block (lưu 48h)."""
        self._blocked_proxies[endpoint] = {
            'blocked_at': time.time(),
            'reason': reason,
            'blocked_time': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        self._save_blocked_list()
        remaining = self.BLOCK_DURATION / 3600
        print(f"[Webshare] Blocked {endpoint} for {remaining:.0f}h (reason: {reason})")

    # === ROTATING ENDPOINT METHODS ===

    def setup_rotating_endpoint(self, host: str = "p.webshare.io", port: int = 80,
                                 username: str = "", password: str = "",
                                 base_username: str = "") -> bool:
        """
        Setup Rotating Residential Endpoint mode.
        Mỗi request qua endpoint này tự động đổi IP.

        Args:
            host: Rotating endpoint host (default: p.webshare.io)
            port: Port (default: 80)
            username: Full username (legacy) - sẽ tách base_username nếu có dạng xxx-N
            password: Proxy password
            base_username: Base username (VD: jhvbehdf-residential)

        Returns:
            True nếu setup thành công
        """
        # Tách base_username từ username nếu có dạng xxx-N
        if not base_username and username:
            # VD: jhvbehdf-residential-1 → jhvbehdf-residential
            parts = username.rsplit('-', 1)
            if len(parts) == 2 and parts[1].isdigit():
                base_username = parts[0]
            else:
                base_username = username

        self.rotating_endpoint = RotatingEndpointConfig(
            host=host,
            port=port,
            base_username=base_username or self.default_username,
            password=password or self.default_password
        )
        self._use_rotating_endpoint = True
        print(f"[Webshare] Rotating Residential enabled: {host}:{port}")
        print(f"[Webshare] Base username: {self.rotating_endpoint.base_username}")
        print(f"[Webshare] Each request = NEW session = NEW IP!")
        return True

    def disable_rotating_endpoint(self):
        """Tắt Rotating Endpoint mode, quay lại Direct proxy list."""
        self._use_rotating_endpoint = False
        print(f"[Webshare] Rotating Endpoint disabled, using Direct proxy list")

    def is_rotating_mode(self) -> bool:
        """Check if using rotating endpoint mode."""
        return self._use_rotating_endpoint and self.rotating_endpoint is not None

    def get_rotating_proxy(self) -> Optional[RotatingEndpointConfig]:
        """Lấy rotating endpoint config."""
        if self.is_rotating_mode():
            return self.rotating_endpoint
        return None

    def get_rotating_proxy_url(self) -> str:
        """Lấy proxy URL cho rotating endpoint."""
        if self.rotating_endpoint:
            return self.rotating_endpoint.proxy_url
        return ""

    def test_rotating_endpoint(self) -> Tuple[bool, str]:
        """Test rotating endpoint - gọi 2 lần với session khác để verify IP khác nhau."""
        if not self.rotating_endpoint:
            return False, "Rotating endpoint chưa được setup"

        ips = []
        usernames = []
        try:
            for i in range(2):
                # Mỗi lần dùng session ID khác = IP khác
                session_id = 1000 + i  # VD: 1000, 1001
                proxy_url = self.rotating_endpoint.get_proxy_url(session_id)
                username = self.rotating_endpoint.get_username_for_session(session_id)
                usernames.append(username)

                proxies = {"http": proxy_url, "https": proxy_url}

                print(f"[Webshare] Test #{i+1}: {username}")
                resp = requests.get(
                    "https://ipv4.webshare.io/",
                    proxies=proxies,
                    timeout=15
                )
                if resp.status_code == 200:
                    ip = resp.text.strip()
                    ips.append(ip)
                    print(f"[Webshare] → IP = {ip}")
                elif resp.status_code == 407:
                    return False, f"407 Proxy Authentication Required - kiểm tra username/password"
                else:
                    return False, f"HTTP {resp.status_code}"
                time.sleep(0.5)

            if len(ips) == 2:
                if ips[0] != ips[1]:
                    return True, f"Rotating OK!\nSession 1: {ips[0]}\nSession 2: {ips[1]}"
                else:
                    return True, f"Connected!\nIP: {ips[0]}\n(2 sessions = same IP, có thể cùng pool)"

        except requests.exceptions.ProxyError as e:
            if "407" in str(e):
                return False, f"407 Proxy Authentication Required\nKiểm tra: base_username, password"
            return False, f"Proxy Error: {e}"
        except Exception as e:
            return False, f"Error: {e}"

        return False, "Unknown error"

    def load_from_list(self, proxy_lines: List[str]) -> int:
        """Load proxies từ danh sách strings."""
        count = 0
        for line in proxy_lines:
            proxy = ProxyInfo.from_string(line)
            if proxy:
                if not proxy.username and self.default_username:
                    proxy.username = self.default_username
                if not proxy.password and self.default_password:
                    proxy.password = self.default_password
                self.proxies.append(proxy)
                count += 1
        return count

    def load_from_file(self, filepath: str) -> int:
        """Load proxies từ file."""
        path = Path(filepath)
        if not path.exists():
            return 0
        lines = path.read_text().strip().split('\n')
        return self.load_from_list(lines)

    def load_from_api(self) -> int:
        """
        Load proxies từ Webshare API.
        Cần API key.
        """
        if not self.api_key:
            print("[Webshare] No API key provided")
            return 0

        try:
            print(f"[Webshare] Fetching proxies from API...")
            headers = {"Authorization": f"Token {self.api_key}"}
            resp = requests.get(
                f"{self.API_BASE}/proxy/list/?mode=direct&page_size=100",
                headers=headers,
                timeout=30
            )

            if resp.status_code != 200:
                print(f"[Webshare] API error: {resp.status_code} - {resp.text[:100]}")
                return 0

            data = resp.json()
            results = data.get('results', [])

            for item in results:
                proxy = ProxyInfo(
                    host=item.get('proxy_address', ''),
                    port=int(item.get('port', 0)),
                    username=item.get('username', self.default_username),
                    password=item.get('password', self.default_password)
                )
                if proxy.host and proxy.port:
                    self.proxies.append(proxy)

            print(f"[Webshare] Loaded {len(results)} proxies from API")
            return len(results)

        except Exception as e:
            print(f"[Webshare] API error: {e}")
            return 0

    def get_proxy_for_worker(self, worker_id: int) -> Optional[ProxyInfo]:
        """
        Lấy proxy cho worker (Chrome).
        Mỗi worker có proxy riêng, không trùng nhau.
        Skip các proxy đã bị block trong 48h (lưu trong file).
        SỬ DỤNG RANDOM SELECTION để tránh nhiều máy chọn cùng proxy.

        Args:
            worker_id: ID của worker (0, 1, 2, ...)

        Returns:
            ProxyInfo cho worker đó
        """
        with self._lock:
            if not self.proxies:
                return None

            # Nếu worker đã có proxy và proxy chưa bị block 48h, trả về proxy đó
            if worker_id in self._worker_proxy_map:
                idx = self._worker_proxy_map[worker_id]
                if idx < len(self.proxies):
                    proxy = self.proxies[idx]
                    # Kiểm tra proxy có bị block 48h không
                    if not self._is_proxy_blocked(proxy.endpoint):
                        return proxy
                    # Proxy đã bị block, cần tìm proxy mới
                    print(f"[Webshare] Worker {worker_id}'s proxy {proxy.endpoint} is blocked, finding new one...")

            # === RANDOM SELECTION ===
            # Tìm tất cả proxy khả dụng (chưa ai dùng, chưa bị block)
            now = time.time()
            available_indices = []

            for i, proxy in enumerate(self.proxies):
                # Skip proxy đã bị block trong 48h
                if self._is_proxy_blocked(proxy.endpoint):
                    continue

                # Proxy chưa ai dùng và không bị block trong memory
                if proxy.worker_id == -1:
                    if not proxy.blocked or (now - proxy.last_used > self.BLOCK_TIMEOUT):
                        available_indices.append(i)

            # Random chọn từ danh sách khả dụng
            if available_indices:
                chosen_idx = random.choice(available_indices)
                proxy = self.proxies[chosen_idx]
                proxy.worker_id = worker_id
                proxy.blocked = False
                self._worker_proxy_map[worker_id] = chosen_idx
                print(f"[Webshare] Worker {worker_id}: Random selected {proxy.endpoint} (from {len(available_indices)} available)")
                return proxy

            # Nếu không còn proxy trống, random từ proxy không bị block 48h
            fallback_indices = [
                i for i, proxy in enumerate(self.proxies)
                if not self._is_proxy_blocked(proxy.endpoint)
            ]
            if fallback_indices:
                chosen_idx = random.choice(fallback_indices)
                self._worker_proxy_map[worker_id] = chosen_idx
                self.proxies[chosen_idx].worker_id = worker_id
                print(f"[Webshare] Worker {worker_id}: Fallback to {self.proxies[chosen_idx].endpoint}")
                return self.proxies[chosen_idx]

            # Tất cả proxy đều bị block 48h
            print(f"[Webshare] WARNING: All {len(self.proxies)} proxies are blocked!")
            print(f"[Webshare] Blocked list: {len(self._blocked_proxies)} proxies")
            return None

    def mark_worker_fail(self, worker_id: int) -> Tuple[bool, str]:
        """
        Đánh dấu worker gặp lỗi.
        Nếu fail >= 3 lần → tự động xoay proxy.

        Returns:
            (should_rotate, message)
        """
        with self._lock:
            if worker_id not in self._worker_proxy_map:
                return False, "Worker không có proxy"

            idx = self._worker_proxy_map[worker_id]
            proxy = self.proxies[idx]
            proxy.fail_count += 1
            proxy.last_used = time.time()

            if proxy.fail_count >= self.MAX_FAIL_COUNT:
                return True, f"Proxy {proxy.endpoint} fail {proxy.fail_count} lần, cần xoay"
            else:
                return False, f"Proxy {proxy.endpoint} fail {proxy.fail_count}/{self.MAX_FAIL_COUNT}"

    def rotate_worker_proxy(self, worker_id: int, reason: str = "403") -> Tuple[bool, str]:
        """
        Xoay proxy cho worker khi bị block.
        Proxy bị block sẽ được lưu vào file và không dùng lại trong 48h.

        Args:
            worker_id: ID của worker
            reason: Lý do block (vd: "403 reCAPTCHA")

        Returns:
            (success, message)
        """
        with self._lock:
            if not self.proxies:
                return False, "Không có proxy nào"

            # Đánh dấu proxy cũ là blocked + LƯU VÀO FILE (48h)
            if worker_id in self._worker_proxy_map:
                old_idx = self._worker_proxy_map[worker_id]
                old_proxy = self.proxies[old_idx]
                old_proxy.blocked = True
                old_proxy.last_used = time.time()
                old_proxy.worker_id = -1  # Giải phóng

                # LƯU VÀO FILE ĐỂ KHÔNG DÙNG LẠI TRONG 48H
                self._add_to_blocked(old_proxy.endpoint, reason)

            # Tìm proxy mới không bị block (cả memory và file 48h)
            now = time.time()
            for i, proxy in enumerate(self.proxies):
                # Bỏ qua proxy đang được dùng bởi worker khác
                if proxy.worker_id != -1 and proxy.worker_id != worker_id:
                    continue

                # Bỏ qua proxy bị block trong memory (chưa hết 5 phút)
                if proxy.blocked and (now - proxy.last_used < self.BLOCK_TIMEOUT):
                    continue

                # Bỏ qua proxy bị block trong file (chưa hết 48h)
                if self._is_proxy_blocked(proxy.endpoint):
                    continue

                # Tìm được proxy mới
                proxy.blocked = False
                proxy.fail_count = 0
                proxy.worker_id = worker_id
                self._worker_proxy_map[worker_id] = i
                self.rotate_count += 1

                return True, f"Rotated to {proxy.endpoint} (total rotations: {self.rotate_count})"

            # Không tìm được proxy mới - reset memory block nhưng KHÔNG reset file block
            available = len(self.proxies) - len(self._blocked_proxies)
            print(f"[Webshare] Không còn proxy khả dụng! Available: {available}/{len(self.proxies)}")

            # Chỉ reset memory block (5 phút), KHÔNG động đến file block (48h)
            for p in self.proxies:
                if p.worker_id == -1 and not self._is_proxy_blocked(p.endpoint):
                    p.blocked = False
                    p.fail_count = 0

            # Thử lại - vẫn skip các proxy bị block 48h
            for i, proxy in enumerate(self.proxies):
                if proxy.worker_id == -1 and not self._is_proxy_blocked(proxy.endpoint):
                    proxy.worker_id = worker_id
                    self._worker_proxy_map[worker_id] = i
                    self.rotate_count += 1
                    return True, f"Reset & rotated to {proxy.endpoint}"

            return False, f"Không tìm được proxy khả dụng (blocked 48h: {len(self._blocked_proxies)})"

    def release_worker_proxy(self, worker_id: int, rotate_next: bool = True):
        """
        Giải phóng proxy khi worker kết thúc.

        Args:
            worker_id: ID của worker
            rotate_next: True = lần gọi get_proxy_for_worker tiếp theo sẽ lấy proxy MỚI
        """
        with self._lock:
            if worker_id in self._worker_proxy_map:
                idx = self._worker_proxy_map[worker_id]
                old_proxy = self.proxies[idx]
                old_proxy.worker_id = -1
                old_proxy.fail_count = 0
                old_proxy.last_used = time.time()

                if rotate_next:
                    # Đánh dấu để lần sau lấy proxy khác
                    old_proxy.blocked = True  # Block tạm 5 phút (memory only)
                    print(f"[Webshare] Worker {worker_id} released {old_proxy.endpoint} (will rotate next)")

                del self._worker_proxy_map[worker_id]

    def test_and_get_proxy(self, worker_id: int, max_retries: int = 3) -> Tuple[Optional[ProxyInfo], str]:
        """
        Lấy proxy và test xem có hoạt động không.
        Nếu fail, tự động rotate sang proxy khác.

        Args:
            worker_id: ID của worker
            max_retries: Số lần thử tối đa

        Returns:
            (ProxyInfo, ip_address) hoặc (None, error_message)
        """
        for attempt in range(max_retries):
            proxy = self.get_proxy_for_worker(worker_id)
            if not proxy:
                return None, "Không có proxy khả dụng"

            # Test proxy
            try:
                resp = requests.get(
                    "https://ipv4.webshare.io/",
                    proxies={"http": proxy.proxy_url, "https": proxy.proxy_url},
                    timeout=10
                )
                if resp.status_code == 200:
                    ip = resp.text.strip()
                    print(f"[Webshare] Worker {worker_id}: {proxy.endpoint} → IP: {ip}")
                    return proxy, ip
                else:
                    print(f"[Webshare] Worker {worker_id}: {proxy.endpoint} → HTTP {resp.status_code}")
            except Exception as e:
                print(f"[Webshare] Worker {worker_id}: {proxy.endpoint} → Error: {e}")

            # Rotate sang proxy khác
            if attempt < max_retries - 1:
                self.rotate_worker_proxy(worker_id, f"test_failed_attempt_{attempt+1}")

        return None, f"Không tìm được proxy hoạt động sau {max_retries} lần thử"

    def get_current_ip(self, worker_id: int) -> Optional[str]:
        """Lấy IP hiện tại của worker."""
        proxy = self.get_proxy_for_worker(worker_id)
        if not proxy:
            return None
        try:
            resp = requests.get(
                "https://ipv4.webshare.io/",
                proxies={"http": proxy.proxy_url, "https": proxy.proxy_url},
                timeout=10
            )
            if resp.status_code == 200:
                return resp.text.strip()
        except:
            pass
        return None

    def get_proxies_dict(self, worker_id: int = None) -> Dict[str, str]:
        """Dict proxies cho requests library."""
        proxy = self.get_proxy_for_worker(worker_id) if worker_id is not None else None
        if not proxy and self.proxies:
            proxy = self.proxies[0]
        if not proxy:
            return {}
        return {
            "http": proxy.proxy_url,
            "https": proxy.proxy_url
        }

    def get_chrome_proxy_arg(self, worker_id: int = None) -> str:
        """Proxy URL cho Chrome --proxy-server."""
        proxy = self.get_proxy_for_worker(worker_id) if worker_id is not None else None
        if not proxy and self.proxies:
            proxy = self.proxies[0]
        if not proxy:
            return ""
        return proxy.chrome_url

    def get_chrome_auth(self, worker_id: int = None) -> Tuple[str, str]:
        """Username, password cho Chrome auth."""
        proxy = self.get_proxy_for_worker(worker_id) if worker_id is not None else None
        if not proxy and self.proxies:
            proxy = self.proxies[0]
        if not proxy:
            return "", ""
        return proxy.username, proxy.password

    def test_proxy(self, worker_id: int = None) -> Tuple[bool, str]:
        """Test proxy của worker với nhiều URL fallback."""
        proxy = self.get_proxy_for_worker(worker_id) if worker_id is not None else None
        if not proxy and self.proxies:
            proxy = self.proxies[0]
        if not proxy:
            return False, "Không có proxy"

        # Try multiple test URLs in case one is blocked
        test_urls = [
            ("http://ip-api.com/json", lambda r: r.json().get('query', r.text)),
            ("https://api.ipify.org", lambda r: r.text.strip()),
            ("https://httpbin.org/ip", lambda r: r.json().get('origin', r.text)),
        ]

        last_error = ""
        for url, extract_ip in test_urls:
            try:
                start = time.time()
                resp = requests.get(
                    url,
                    proxies={"http": proxy.proxy_url, "https": proxy.proxy_url},
                    timeout=10
                )
                elapsed = time.time() - start

                if resp.status_code == 200:
                    try:
                        ip = extract_ip(resp)
                    except:
                        ip = resp.text[:50]
                    return True, f"OK! IP: {ip} ({elapsed:.1f}s) via {proxy.endpoint}"
                last_error = f"HTTP {resp.status_code} from {url}"

            except requests.exceptions.ProxyError as e:
                last_error = f"Proxy error: {str(e)[:100]}"
            except requests.exceptions.Timeout:
                last_error = f"Timeout connecting to {url}"
            except Exception as e:
                last_error = f"Error: {str(e)[:100]}"

        return False, last_error

    def get_stats(self) -> Dict:
        """Thống kê."""
        with self._lock:
            blocked_memory = sum(1 for p in self.proxies if p.blocked)
            blocked_48h = len(self._blocked_proxies)
            in_use = sum(1 for p in self.proxies if p.worker_id != -1)
            # Available = không bị block memory VÀ không bị block 48h
            available = sum(
                1 for p in self.proxies
                if not p.blocked and not self._is_proxy_blocked(p.endpoint) and p.worker_id == -1
            )
            return {
                "total": len(self.proxies),
                "in_use": in_use,
                "blocked_memory": blocked_memory,
                "blocked_48h": blocked_48h,
                "available": available,
                "rotate_count": self.rotate_count,
                "workers": list(self._worker_proxy_map.keys())
            }

    def get_blocked_list(self) -> Dict[str, dict]:
        """Lấy danh sách proxy bị block 48h."""
        return self._blocked_proxies.copy()

    def clear_blocked_list(self):
        """Xóa tất cả proxy khỏi blocked list (cho testing)."""
        self._blocked_proxies = {}
        self._save_blocked_list()
        print(f"[Webshare] Cleared all blocked proxies")

    # ============= Legacy compatibility =============
    @property
    def current_proxy(self) -> Optional[ProxyInfo]:
        """Legacy: Proxy đầu tiên."""
        return self.proxies[0] if self.proxies else None

    @property
    def available_count(self) -> int:
        """Legacy: Số proxy khả dụng (không bị block memory VÀ file)."""
        now = time.time()
        return sum(
            1 for p in self.proxies
            if (not p.blocked or (now - p.last_used > self.BLOCK_TIMEOUT))
            and not self._is_proxy_blocked(p.endpoint)
        )

    def rotate(self, reason: str = "403") -> Tuple[bool, str]:
        """Legacy: Xoay proxy (cho worker 0)."""
        return self.rotate_worker_proxy(0, reason)

    def mark_current_blocked(self, reason: str = "manual"):
        """Legacy: Đánh dấu proxy hiện tại bị block (lưu 48h)."""
        if self.proxies:
            self.proxies[0].blocked = True
            self.proxies[0].last_used = time.time()
            self._add_to_blocked(self.proxies[0].endpoint, reason)


# ============= Singleton instance (Thread-Safe) =============
_manager: Optional[WebshareProxyManager] = None
_manager_lock = threading.Lock()


def get_proxy_manager() -> WebshareProxyManager:
    """Get global proxy manager instance (thread-safe)."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = WebshareProxyManager()
    return _manager


def init_proxy_manager(
    api_key: str = "",
    username: str = "",
    password: str = "",
    proxy_list: List[str] = None,
    proxy_file: str = None,
    force_reinit: bool = False,
    # === ROTATING ENDPOINT CONFIG ===
    rotating_endpoint: bool = False,
    rotating_host: str = "p.webshare.io",
    rotating_port: int = 80
) -> WebshareProxyManager:
    """
    Khởi tạo proxy manager (thread-safe).

    Args:
        api_key: Webshare API key (để auto-fetch proxy list)
        username: Default username cho tất cả proxy
        password: Default password
        proxy_list: List các proxy strings
        proxy_file: Path đến file chứa proxy list
        force_reinit: Force re-init (default False)

        # Rotating Endpoint (mỗi request tự đổi IP)
        rotating_endpoint: True = sử dụng Rotating Endpoint mode
        rotating_host: Host của rotating endpoint (default: p.webshare.io)
        rotating_port: Port của rotating endpoint (từ Webshare dashboard)

    Returns:
        WebshareProxyManager instance
    """
    global _manager

    with _manager_lock:
        if _manager is not None and not force_reinit:
            # Đã có manager, check xem có đủ config không
            if rotating_endpoint and not _manager.is_rotating_mode():
                # Cần chuyển sang rotating mode
                _manager.setup_rotating_endpoint(
                    host=rotating_host,
                    port=rotating_port,
                    username=username,
                    password=password
                )
            elif _manager.proxies or _manager.is_rotating_mode():
                return _manager

        _manager = WebshareProxyManager(
            api_key=api_key,
            default_username=username,
            default_password=password
        )

        # === ROTATING ENDPOINT MODE ===
        if rotating_endpoint is False:
            # Explicitly disable rotating mode (Direct Proxy List mode)
            _manager.disable_rotating_endpoint()

        if rotating_endpoint:
            _manager.setup_rotating_endpoint(
                host=rotating_host,
                port=rotating_port,
                username=username,
                password=password
            )
            return _manager

        # === DIRECT PROXY LIST MODE ===
        # Load từ các nguồn (ưu tiên API)
        if api_key:
            count = _manager.load_from_api()
            if count > 0:
                random.shuffle(_manager.proxies)
                return _manager

        if proxy_list:
            count = _manager.load_from_list(proxy_list)
            print(f"[Webshare] Loaded {count} proxies from list")

        if proxy_file:
            count = _manager.load_from_file(proxy_file)
            print(f"[Webshare] Loaded {count} proxies from file")

        if _manager.proxies:
            random.shuffle(_manager.proxies)

    return _manager


# ============= Legacy compatibility =============
class WebshareProxy:
    """Legacy wrapper cho WebshareProxyManager."""

    def __init__(self, config=None):
        self._manager = get_proxy_manager()

    def get_proxies(self, worker_id: int = None) -> Dict[str, str]:
        return self._manager.get_proxies_dict(worker_id)

    def get_chrome_proxy_arg(self, worker_id: int = None) -> str:
        return self._manager.get_chrome_proxy_arg(worker_id)

    def get_chrome_auth(self, worker_id: int = None) -> Tuple[str, str]:
        return self._manager.get_chrome_auth(worker_id)

    def rotate_ip(self, worker_id: int = 0, reason: str = "403") -> Tuple[bool, str]:
        return self._manager.rotate_worker_proxy(worker_id, reason)

    def mark_fail(self, worker_id: int = 0) -> Tuple[bool, str]:
        return self._manager.mark_worker_fail(worker_id)

    def test_connection(self, worker_id: int = None) -> Tuple[bool, str]:
        return self._manager.test_proxy(worker_id)

    def get_stats(self) -> Dict:
        return self._manager.get_stats()

    @property
    def config(self):
        """Fake config cho legacy code."""
        class FakeConfig:
            endpoint = ""
            is_ip_auth_mode = False
        cfg = FakeConfig()
        proxy = self._manager.current_proxy
        if proxy:
            cfg.endpoint = proxy.endpoint
            cfg.is_ip_auth_mode = not proxy.username
        return cfg


def create_webshare_proxy(
    api_key: str = None,
    username: str = None,
    password: str = None,
    endpoint: str = None
) -> WebshareProxy:
    """Factory function cho legacy compatibility."""
    manager = get_proxy_manager()

    if not manager.proxies:
        if endpoint:
            proxy = ProxyInfo.from_string(
                f"{endpoint}:{username or ''}:{password or ''}"
                if username else endpoint
            )
            if proxy:
                if not proxy.username and username:
                    proxy.username = username
                if not proxy.password and password:
                    proxy.password = password
                manager.proxies.append(proxy)

        if api_key:
            manager.api_key = api_key
            manager.load_from_api()

    return WebshareProxy()


# ============= Test =============
if __name__ == "__main__":
    print("=" * 60)
    print("  WEBSHARE PROXY MANAGER TEST")
    print("=" * 60)

    # Test với API key
    API_KEY = os.environ.get("WEBSHARE_API_KEY", "")

    if API_KEY:
        print(f"\n[1] Testing with API key...")
        manager = init_proxy_manager(api_key=API_KEY, force_reinit=True)
    else:
        print(f"\n[1] Testing with sample proxies...")
        test_proxies = """
166.88.64.59:6442:jhvbehdf:cf1bi3yvq0t1
82.24.221.235:6086:jhvbehdf:cf1bi3yvq0t1
92.112.200.224:6807:jhvbehdf:cf1bi3yvq0t1
        """.strip().split('\n')
        manager = init_proxy_manager(proxy_list=test_proxies, force_reinit=True)

    print(f"\nLoaded {len(manager.proxies)} proxies")

    # Test lấy proxy cho workers
    print("\n[2] Testing worker proxies...")
    for worker_id in range(3):
        proxy = manager.get_proxy_for_worker(worker_id)
        if proxy:
            print(f"    Worker {worker_id}: {proxy.endpoint}")

    # Test rotation
    print("\n[3] Testing rotation for worker 0...")
    for i in range(3):
        success, msg = manager.rotate_worker_proxy(0)
        print(f"    {msg}")

    # Stats
    print("\n[4] Stats:")
    for k, v in manager.get_stats().items():
        print(f"    {k}: {v}")

    # Test connection
    print("\n[5] Testing connection...")
    success, msg = manager.test_proxy(0)
    print(f"    {'✓' if success else '✗'} {msg}")
