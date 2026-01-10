#!/usr/bin/env python3
"""
IPv6 Rotator - Tự động đổi IPv6 khi bị 403
==========================================

Sử dụng trên Windows với /56 subnet (256 IPv6 addresses).
Khi Chrome bị 403 nhiều lần, tự động đổi sang IPv6 khác trong subnet.

Usage:
    from modules.ipv6_rotator import IPv6Rotator

    rotator = IPv6Rotator(settings)
    if rotator.enabled:
        new_ip = rotator.rotate()
"""

import subprocess
import random
import re
import time
from pathlib import Path
from typing import Optional, Dict, Any


class IPv6Rotator:
    """Quản lý việc đổi IPv6 khi bị block."""

    def __init__(self, settings: Dict[str, Any]):
        """
        Khởi tạo IPv6 Rotator.

        Args:
            settings: Dict cấu hình từ settings.yaml
        """
        ipv6_cfg = settings.get('ipv6_rotation', {})

        self.enabled = ipv6_cfg.get('enabled', False)
        self.interface_name = ipv6_cfg.get('interface_name', 'Ethernet')
        self.subnet_prefix = ipv6_cfg.get('subnet_prefix', '')
        self.prefix_length = ipv6_cfg.get('prefix_length', 56)
        self.max_403 = ipv6_cfg.get('max_403_before_rotate', 3)
        self.gateway = ipv6_cfg.get('gateway', '')

        # State
        self.consecutive_403 = 0
        self.current_ipv6 = None
        self.last_rotated = None

        # Log function (có thể override)
        self.log = print

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
        Lấy IPv6 hiện tại của interface.

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
                        match = re.search(r'([0-9a-fA-F:]+::[0-9a-fA-F:]+)', line)
                        if match:
                            ipv6 = match.group(1)
                            # Bỏ qua link-local
                            if not ipv6.startswith('fe80'):
                                return ipv6
            return None
        except Exception as e:
            self.log(f"[IPv6] Error getting current IP: {e}")
            return None

    def generate_random_ipv6(self) -> str:
        """
        Tạo IPv6 ngẫu nhiên trong subnet.

        Với /56 subnet: prefix:XX:: (XX = 00-FF)

        Returns:
            IPv6 address string
        """
        if not self.subnet_prefix:
            raise ValueError("subnet_prefix chưa được cấu hình")

        # Parse prefix
        prefix = self.subnet_prefix.rstrip(':')

        if self.prefix_length == 56:
            # /56 = có 8 bit để random (256 subnets)
            # Format: prefix:XX::1
            random_part = random.randint(0, 255)
            new_ipv6 = f"{prefix}:{random_part:02x}::1"
        elif self.prefix_length == 64:
            # /64 = có 64 bit host để random
            random_host = random.randint(1, 0xFFFFFFFF)
            new_ipv6 = f"{prefix}::{random_host:x}"
        else:
            # Generic: random the remaining bits
            random_suffix = random.randint(1, 0xFFFF)
            new_ipv6 = f"{prefix}::{random_suffix:x}"

        return new_ipv6

    def set_ipv6(self, new_ipv6: str) -> bool:
        """
        Đặt IPv6 mới cho interface (Windows).

        Steps:
        1. Xóa IPv6 cũ (nếu có)
        2. Thêm IPv6 mới
        3. Đợi network adapter cập nhật

        Args:
            new_ipv6: IPv6 address mới

        Returns:
            True nếu thành công
        """
        try:
            # Bước 1: Lấy IPv6 cũ
            old_ipv6 = self.get_current_ipv6()

            # Bước 2: Xóa IPv6 cũ (nếu có và khác IPv6 mới)
            if old_ipv6 and old_ipv6 != new_ipv6:
                self.log(f"[IPv6] Removing old: {old_ipv6}")
                delete_cmd = f'netsh interface ipv6 delete address "{self.interface_name}" {old_ipv6}'
                subprocess.run(delete_cmd, shell=True, capture_output=True, timeout=10)
                time.sleep(1)

            # Bước 3: Thêm IPv6 mới
            self.log(f"[IPv6] Adding new: {new_ipv6}")
            add_cmd = f'netsh interface ipv6 add address "{self.interface_name}" {new_ipv6}'
            result = subprocess.run(add_cmd, shell=True, capture_output=True, text=True, timeout=10)

            if result.returncode != 0:
                # Có thể cần chạy với admin
                self.log(f"[IPv6] Warning: {result.stderr}")

            # Bước 4: Set gateway nếu có
            if self.gateway:
                self.log(f"[IPv6] Setting gateway: {self.gateway}")
                gw_cmd = f'netsh interface ipv6 add route ::/0 "{self.interface_name}" {self.gateway}'
                subprocess.run(gw_cmd, shell=True, capture_output=True, timeout=10)

            # Đợi adapter cập nhật
            time.sleep(2)

            # Verify
            current = self.get_current_ipv6()
            if current:
                self.log(f"[IPv6] ✓ Current IP: {current}")
                self.current_ipv6 = current
                return True
            else:
                self.log("[IPv6] ✗ Failed to verify new IP")
                return False

        except Exception as e:
            self.log(f"[IPv6] Error setting IP: {e}")
            return False

    def rotate(self) -> Optional[str]:
        """
        Thực hiện rotate IPv6.

        1. Generate IPv6 mới
        2. Set IPv6 mới
        3. Reset 403 counter

        Returns:
            IPv6 mới nếu thành công, None nếu thất bại
        """
        if not self.enabled:
            self.log("[IPv6] Rotation is disabled")
            return None

        if not self.subnet_prefix:
            self.log("[IPv6] subnet_prefix chưa được cấu hình!")
            return None

        try:
            # Generate IP mới (khác IP hiện tại)
            current = self.get_current_ipv6()
            new_ipv6 = self.generate_random_ipv6()

            # Đảm bảo IP mới khác IP cũ
            attempts = 0
            while new_ipv6 == current and attempts < 10:
                new_ipv6 = self.generate_random_ipv6()
                attempts += 1

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
        return self.consecutive_403 >= self.max_403


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

    if _rotator_instance is None and settings:
        _rotator_instance = IPv6Rotator(settings)

    return _rotator_instance


def init_ipv6_rotator(settings: Dict[str, Any]) -> IPv6Rotator:
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
