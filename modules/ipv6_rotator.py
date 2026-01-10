#!/usr/bin/env python3
"""
IPv6 Rotator - Tự động đổi IPv6 khi bị 403
==========================================

Sử dụng danh sách IPv6 từ file config/ipv6_list.txt
Khi Chrome bị 403, tự động đổi sang IPv6 khác trong danh sách.

Usage:
    from modules.ipv6_rotator import IPv6Rotator, get_ipv6_rotator

    # Cách 1: Dùng singleton
    rotator = get_ipv6_rotator(settings)
    if rotator and rotator.enabled:
        new_ip = rotator.rotate()

    # Cách 2: Tạo instance riêng
    rotator = IPv6Rotator(settings)
    rotator.rotate()
"""

import subprocess
import random
import re
import time
import sys
import os
from pathlib import Path
from typing import Optional, Dict, Any, List


def _is_admin() -> bool:
    """Check if running with admin privileges (Windows)."""
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False


def _run_netsh_admin(commands: List[str], log_func=print) -> bool:
    """
    Run netsh commands with admin privileges using PowerShell.

    Args:
        commands: List of netsh commands to run
        log_func: Function to log messages

    Returns:
        True if successful
    """
    try:
        # Create a batch script with all commands
        script_path = Path(__file__).parent.parent / "config" / "ipv6_change.bat"

        with open(script_path, 'w', encoding='utf-8') as f:
            f.write("@echo off\n")
            for cmd in commands:
                f.write(f"{cmd}\n")
            f.write("exit /b 0\n")

        # Run batch file with admin privileges using PowerShell
        ps_cmd = f'Start-Process -FilePath "{script_path}" -Verb RunAs -Wait -WindowStyle Hidden'

        result = subprocess.run(
            ['powershell', '-Command', ps_cmd],
            capture_output=True,
            text=True,
            timeout=30
        )

        # Clean up
        try:
            script_path.unlink()
        except:
            pass

        return True

    except subprocess.TimeoutExpired:
        log_func("[IPv6] Admin command timeout")
        return False
    except Exception as e:
        log_func(f"[IPv6] Admin command error: {e}")
        return False


class IPv6Rotator:
    """Quản lý việc đổi IPv6 khi bị block."""

    def __init__(self, settings: Dict[str, Any] = None):
        """
        Khởi tạo IPv6 Rotator.

        Args:
            settings: Dict cấu hình từ settings.yaml (optional)
        """
        settings = settings or {}
        ipv6_cfg = settings.get('ipv6_rotation', {})

        self.enabled = ipv6_cfg.get('enabled', False)
        self.interface_name = ipv6_cfg.get('interface_name', 'Ethernet')
        self.max_403 = ipv6_cfg.get('max_403_before_rotate', 3)
        self.gateway = ipv6_cfg.get('gateway', '')
        self.disable_ipv4 = ipv6_cfg.get('disable_ipv4', True)  # Tắt IPv4 để ép dùng IPv6

        # Load IPv6 list from file
        self.ipv6_list: List[str] = []
        self.current_index = 0
        self._load_ipv6_list()

        # State
        self.consecutive_403 = 0
        self.current_ipv6 = None
        self.last_rotated = None
        self._ipv4_disabled = False  # Track trạng thái IPv4

        # Log function (có thể override)
        self.log = print

    def _load_ipv6_list(self):
        """Load danh sách IPv6 từ file config/ipv6_list.txt"""
        try:
            # Tìm file ipv6_list.txt
            base_dir = Path(__file__).parent.parent
            ipv6_file = base_dir / "config" / "ipv6_list.txt"

            if ipv6_file.exists():
                with open(ipv6_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()

                self.ipv6_list = [
                    line.strip() for line in lines
                    if line.strip() and not line.startswith('#')
                ]

                if self.ipv6_list:
                    self.enabled = True  # Auto-enable nếu có danh sách
                    print(f"[IPv6] Loaded {len(self.ipv6_list)} IPv6 addresses from {ipv6_file.name}")
                else:
                    print(f"[IPv6] No IPv6 addresses in {ipv6_file.name}")
            else:
                print(f"[IPv6] File not found: {ipv6_file}")

        except Exception as e:
            print(f"[IPv6] Error loading IPv6 list: {e}")

    def set_logger(self, log_func):
        """Set custom log function."""
        self.log = log_func

    def increment_403(self) -> bool:
        """
        Tăng counter 403 và kiểm tra có cần rotate không.

        Returns:
            True nếu đã đạt max và cần rotate
        """
        self.consecutive_403 += 1
        self.log(f"[IPv6] 403 count: {self.consecutive_403}/{self.max_403}")

        if self.consecutive_403 >= self.max_403:
            return True
        return False

    def reset_403(self):
        """Reset counter 403 khi thành công."""
        if self.consecutive_403 > 0:
            self.log(f"[IPv6] Reset 403 counter (was {self.consecutive_403})")
        self.consecutive_403 = 0

    def get_current_ipv6(self) -> Optional[str]:
        """
        Lấy IPv6 hiện tại của interface (Windows).

        Returns:
            IPv6 address hoặc None
        """
        try:
            # netsh interface ipv6 show addresses "Ethernet"
            cmd = f'netsh interface ipv6 show addresses "{self.interface_name}"'
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=10
            )

            if result.returncode == 0:
                # Parse output để tìm global IPv6 (không phải fe80:: link-local)
                lines = result.stdout.split('\n')
                for line in lines:
                    # Tìm dòng chứa "Address" và IPv6
                    if 'Address' in line:
                        # Match IPv6 pattern
                        match = re.search(r'(2[0-9a-fA-F]{3}:[0-9a-fA-F:]+)', line)
                        if match:
                            return match.group(1)
            return None
        except Exception as e:
            self.log(f"[IPv6] Error getting current IP: {e}")
            return None

    def get_next_ipv6(self) -> Optional[str]:
        """
        Lấy IPv6 tiếp theo trong danh sách.

        Returns:
            IPv6 address hoặc None nếu hết danh sách
        """
        if not self.ipv6_list:
            return None

        # Lấy IPv6 hiện tại để tránh trùng
        current = self.get_current_ipv6()

        # Thử tìm IPv6 khác trong danh sách
        for _ in range(len(self.ipv6_list)):
            self.current_index = (self.current_index + 1) % len(self.ipv6_list)
            next_ip = self.ipv6_list[self.current_index]

            # Kiểm tra không trùng với IP hiện tại
            if current and next_ip.lower() == current.lower():
                continue

            return next_ip

        # Nếu tất cả đều trùng (không nên xảy ra), random 1 cái
        return random.choice(self.ipv6_list)

    def set_ipv6(self, new_ipv6: str) -> bool:
        """
        Đặt IPv6 mới cho interface (Windows).

        Steps:
        1. Tắt IPv4 để ép dùng IPv6 (nếu bật disable_ipv4)
        2. Xóa tất cả IPv6 cũ (trong danh sách) khỏi interface
        3. Thêm IPv6 mới
        4. Đợi network adapter cập nhật

        Tự động yêu cầu quyền Admin nếu cần.

        Args:
            new_ipv6: IPv6 address mới

        Returns:
            True nếu thành công
        """
        try:
            self.log(f"[IPv6] 🔄 Changing to: {new_ipv6}")

            # Collect all netsh commands
            commands = []

            # Bước 0: Tắt IPv4 để Chrome phải dùng IPv6
            if self.disable_ipv4 and not self._ipv4_disabled:
                self.log("[IPv6] 🔌 Disabling IPv4 to force IPv6...")
                commands.append(f'netsh interface ipv4 set interface "{self.interface_name}" admin=disabled')

            # Bước 1: Xóa tất cả IPv6 cũ trong danh sách khỏi interface
            for old_ip in self.ipv6_list:
                if old_ip.lower() != new_ipv6.lower():
                    commands.append(f'netsh interface ipv6 delete address "{self.interface_name}" {old_ip}')

            # Bước 2: Thêm IPv6 mới
            commands.append(f'netsh interface ipv6 add address "{self.interface_name}" {new_ipv6}')

            # Bước 3: Set gateway nếu có
            if self.gateway:
                commands.append(f'netsh interface ipv6 add route ::/0 "{self.interface_name}" {self.gateway}')

            # Check admin và chạy commands
            if _is_admin():
                # Đã có quyền admin - chạy trực tiếp
                self.log("[IPv6] Running with admin privileges...")
                for cmd in commands:
                    subprocess.run(cmd, shell=True, capture_output=True, timeout=5)
            else:
                # Cần yêu cầu quyền admin
                self.log("[IPv6] Requesting admin privileges...")
                if not _run_netsh_admin(commands, self.log):
                    self.log("[IPv6] ✗ Failed to get admin privileges")
                    return False

            # Đợi adapter cập nhật
            time.sleep(3)

            # Track IPv4 disabled status
            if self.disable_ipv4:
                self._ipv4_disabled = True

            # Verify
            current = self.get_current_ipv6()
            if current:
                self.log(f"[IPv6] ✓ Now using: {current}")
                if self.disable_ipv4:
                    self.log("[IPv6] ✓ IPv4 disabled - Chrome sẽ dùng IPv6")
                self.current_ipv6 = current
                return True
            else:
                self.log("[IPv6] ✗ Failed to verify new IP")
                return False

        except Exception as e:
            self.log(f"[IPv6] Error setting IP: {e}")
            return False

    def enable_ipv4(self) -> bool:
        """Bật lại IPv4 (khi không cần ép IPv6 nữa)."""
        if not self._ipv4_disabled:
            return True

        try:
            self.log("[IPv6] 🔌 Re-enabling IPv4...")
            cmd = f'netsh interface ipv4 set interface "{self.interface_name}" admin=enabled'

            if _is_admin():
                subprocess.run(cmd, shell=True, capture_output=True, timeout=5)
            else:
                _run_netsh_admin([cmd], self.log)

            self._ipv4_disabled = False
            self.log("[IPv6] ✓ IPv4 re-enabled")
            return True
        except Exception as e:
            self.log(f"[IPv6] Error enabling IPv4: {e}")
            return False

    def rotate(self) -> Optional[str]:
        """
        Thực hiện rotate IPv6.

        1. Lấy IPv6 tiếp theo từ danh sách
        2. Set IPv6 mới
        3. Reset 403 counter

        Returns:
            IPv6 mới nếu thành công, None nếu thất bại
        """
        if not self.enabled:
            self.log("[IPv6] Rotation is disabled")
            return None

        if not self.ipv6_list:
            self.log("[IPv6] No IPv6 list available!")
            return None

        try:
            current = self.get_current_ipv6()
            new_ipv6 = self.get_next_ipv6()

            if not new_ipv6:
                self.log("[IPv6] No IPv6 available")
                return None

            self.log(f"[IPv6] Rotating: {current} → {new_ipv6}")

            if self.set_ipv6(new_ipv6):
                self.reset_403()
                self.last_rotated = time.time()
                return new_ipv6
            else:
                return None

        except Exception as e:
            self.log(f"[IPv6] Rotation error: {e}")
            return None

    def should_rotate(self) -> bool:
        """
        Kiểm tra có nên rotate không.

        Returns:
            True nếu cần rotate (403 >= max)
        """
        return self.enabled and self.consecutive_403 >= self.max_403


# Singleton instance
_rotator_instance: Optional[IPv6Rotator] = None


def get_ipv6_rotator(settings: Dict[str, Any] = None) -> Optional[IPv6Rotator]:
    """
    Lấy IPv6Rotator instance (singleton).

    Args:
        settings: Dict cấu hình (chỉ cần lần đầu)

    Returns:
        IPv6Rotator instance hoặc None nếu disabled
    """
    global _rotator_instance

    if _rotator_instance is None:
        _rotator_instance = IPv6Rotator(settings)

    return _rotator_instance


def init_ipv6_rotator(settings: Dict[str, Any] = None) -> IPv6Rotator:
    """
    Khởi tạo IPv6Rotator singleton.

    Args:
        settings: Dict cấu hình

    Returns:
        IPv6Rotator instance
    """
    global _rotator_instance
    _rotator_instance = IPv6Rotator(settings)
    return _rotator_instance
