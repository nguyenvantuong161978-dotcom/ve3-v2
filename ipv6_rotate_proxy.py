#!/usr/bin/env python3
"""
IPv6 Rotating Proxy Server
==========================
Tạo SOCKS5 proxy server xoay qua danh sách IPv6 của bạn.
Chrome kết nối qua proxy này sẽ dùng IPv6 khác nhau mỗi request.
"""

import socket
import threading
import struct
import select
import time
from typing import List

# Danh sách 100 IPv6
IPV6_LIST = [
    "2001:ee0:b004:1f00::2",
    "2001:ee0:b004:1f01::2",
    "2001:ee0:b004:1f02::3",
    "2001:ee0:b004:1f03::4",
    "2001:ee0:b004:1f04::5",
    "2001:ee0:b004:1f05::6",
    "2001:ee0:b004:1f06::7",
    "2001:ee0:b004:1f07::8",
    "2001:ee0:b004:1f08::9",
    "2001:ee0:b004:1f09::10",
    "2001:ee0:b004:1f0A::11",
    "2001:ee0:b004:1f0B::12",
    "2001:ee0:b004:1f0C::13",
    "2001:ee0:b004:1f0D::14",
    "2001:ee0:b004:1f0E::15",
    "2001:ee0:b004:1f10::16",
    "2001:ee0:b004:1f11::17",
    "2001:ee0:b004:1f12::18",
    "2001:ee0:b004:1f13::19",
    "2001:ee0:b004:1f14::20",
    "2001:ee0:b004:1f15::21",
    "2001:ee0:b004:1f16::22",
    "2001:ee0:b004:1f17::23",
    "2001:ee0:b004:1f18::24",
    "2001:ee0:b004:1f19::25",
    "2001:ee0:b004:1f1A::26",
    "2001:ee0:b004:1f1B::27",
    "2001:ee0:b004:1f1C::28",
    "2001:ee0:b004:1f1D::29",
    "2001:ee0:b004:1f1E::30",
    "2001:ee0:b004:1f1F::31",
    "2001:ee0:b004:1f20::32",
    "2001:ee0:b004:1f21::33",
    "2001:ee0:b004:1f22::34",
    "2001:ee0:b004:1f23::35",
    "2001:ee0:b004:1f24::36",
    "2001:ee0:b004:1f25::37",
    "2001:ee0:b004:1f26::38",
    "2001:ee0:b004:1f27::39",
    "2001:ee0:b004:1f28::40",
    "2001:ee0:b004:1f29::41",
    "2001:ee0:b004:1f2A::42",
    "2001:ee0:b004:1f2B::43",
    "2001:ee0:b004:1f2C::44",
    "2001:ee0:b004:1f2D::45",
    "2001:ee0:b004:1f2E::46",
    "2001:ee0:b004:1f2F::47",
    "2001:ee0:b004:1f30::48",
    "2001:ee0:b004:1f31::49",
    "2001:ee0:b004:1f32::50",
    "2001:ee0:b004:1f33::51",
    "2001:ee0:b004:1f34::52",
    "2001:ee0:b004:1f35::53",
    "2001:ee0:b004:1f36::54",
    "2001:ee0:b004:1f37::55",
    "2001:ee0:b004:1f38::56",
    "2001:ee0:b004:1f39::57",
    "2001:ee0:b004:1f3A::58",
    "2001:ee0:b004:1f3B::59",
    "2001:ee0:b004:1f3C::60",
    "2001:ee0:b004:1f3D::61",
    "2001:ee0:b004:1f3E::62",
    "2001:ee0:b004:1f3F::63",
    "2001:ee0:b004:1f40::64",
    "2001:ee0:b004:1f41::65",
    "2001:ee0:b004:1f42::66",
    "2001:ee0:b004:1f43::67",
    "2001:ee0:b004:1f44::68",
    "2001:ee0:b004:1f45::69",
    "2001:ee0:b004:1f46::70",
    "2001:ee0:b004:1f47::71",
    "2001:ee0:b004:1f48::72",
    "2001:ee0:b004:1f49::73",
    "2001:ee0:b004:1f4A::74",
    "2001:ee0:b004:1f4B::75",
    "2001:ee0:b004:1f4C::76",
    "2001:ee0:b004:1f4D::77",
    "2001:ee0:b004:1f4E::78",
    "2001:ee0:b004:1f4F::79",
    "2001:ee0:b004:1f50::80",
    "2001:ee0:b004:1f51::81",
    "2001:ee0:b004:1f52::82",
    "2001:ee0:b004:1f53::83",
    "2001:ee0:b004:1f54::84",
    "2001:ee0:b004:1f55::85",
    "2001:ee0:b004:1f56::86",
    "2001:ee0:b004:1f57::87",
    "2001:ee0:b004:1f58::88",
    "2001:ee0:b004:1f59::89",
    "2001:ee0:b004:1f5A::90",
    "2001:ee0:b004:1f5B::91",
    "2001:ee0:b004:1f5C::92",
    "2001:ee0:b004:1f5D::93",
    "2001:ee0:b004:1f5E::94",
    "2001:ee0:b004:1f5F::95",
    "2001:ee0:b004:1f60::96",
    "2001:ee0:b004:1f61::97",
    "2001:ee0:b004:1f62::98",
    "2001:ee0:b004:1f63::99",
    "2001:ee0:b004:1f64::100",
]

PROXY_HOST = "127.0.0.1"
PROXY_PORT = 1080


def test_ipv6_bindable(ipv6_addr: str) -> bool:
    """Test if we can bind to this IPv6 address"""
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sock.bind((ipv6_addr, 0))
        sock.close()
        return True
    except:
        return False


# DNS cache để tránh query lặp lại
_dns_cache = {}
_dns_cache_time = {}
DNS_CACHE_TTL = 300  # 5 phút


def resolve_ipv6_direct(domain: str) -> str:
    """
    Query AAAA record trực tiếp từ Google DNS (8.8.8.8).
    Bypass system DNS để lấy IPv6 address.
    """
    import random

    # Check cache
    now = time.time()
    if domain in _dns_cache and now - _dns_cache_time.get(domain, 0) < DNS_CACHE_TTL:
        return _dns_cache[domain]

    # Build DNS query for AAAA record
    # Transaction ID
    tx_id = struct.pack('>H', random.randint(0, 65535))

    # Flags: standard query, recursion desired
    flags = struct.pack('>H', 0x0100)

    # Questions: 1, Answers: 0, Authority: 0, Additional: 0
    counts = struct.pack('>HHHH', 1, 0, 0, 0)

    # QNAME: domain name in DNS format
    qname = b''
    for part in domain.split('.'):
        qname += bytes([len(part)]) + part.encode('ascii')
    qname += b'\x00'

    # QTYPE: AAAA (28), QCLASS: IN (1)
    qtype_class = struct.pack('>HH', 28, 1)

    query = tx_id + flags + counts + qname + qtype_class

    # Try Google DNS (8.8.8.8) and Cloudflare (1.1.1.1)
    dns_servers = ['8.8.8.8', '1.1.1.1']

    for dns_server in dns_servers:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(3)
            sock.sendto(query, (dns_server, 53))
            response, _ = sock.recvfrom(512)
            sock.close()

            # Parse response
            # Skip header (12 bytes) + question section
            offset = 12

            # Skip QNAME
            while response[offset] != 0:
                offset += response[offset] + 1
            offset += 1  # null terminator
            offset += 4  # QTYPE + QCLASS

            # Parse answers
            answer_count = struct.unpack('>H', response[6:8])[0]

            for _ in range(answer_count):
                # Skip name (might be pointer)
                if response[offset] & 0xC0 == 0xC0:
                    offset += 2  # pointer
                else:
                    while response[offset] != 0:
                        offset += response[offset] + 1
                    offset += 1

                # TYPE, CLASS, TTL, RDLENGTH
                rtype = struct.unpack('>H', response[offset:offset+2])[0]
                offset += 2
                offset += 2  # class
                offset += 4  # ttl
                rdlength = struct.unpack('>H', response[offset:offset+2])[0]
                offset += 2

                # AAAA record (type 28)
                if rtype == 28 and rdlength == 16:
                    ipv6_bytes = response[offset:offset+16]
                    # Convert to IPv6 string
                    ipv6 = ':'.join(f'{ipv6_bytes[i]:02x}{ipv6_bytes[i+1]:02x}'
                                   for i in range(0, 16, 2))
                    # Normalize (remove leading zeros)
                    parts = ipv6.split(':')
                    parts = [p.lstrip('0') or '0' for p in parts]
                    ipv6 = ':'.join(parts)

                    # Cache và return
                    _dns_cache[domain] = ipv6
                    _dns_cache_time[domain] = now
                    return ipv6

                offset += rdlength

        except Exception as e:
            continue

    return None


# Chế độ IPv6-only: từ chối kết nối với domain không có IPv6
IPV6_ONLY_MODE = True


class IPv6Rotator:
    # Thời gian block IPv6 khi bị rate limit (giây)
    BLOCK_DURATION = 300  # 5 phút

    def __init__(self, ipv6_list: List[str]):
        # Filter only bindable IPs
        print("[INFO] Testing IPv6 addresses...")
        self.ipv6_list = []
        for ip in ipv6_list:
            if test_ipv6_bindable(ip):
                self.ipv6_list.append(ip)
                print(f"  ✓ {ip}")
            else:
                print(f"  ✗ {ip} (not bindable)")

        if not self.ipv6_list:
            raise Exception("No bindable IPv6 addresses found!")

        print(f"\n[OK] {len(self.ipv6_list)} IPv6 addresses available\n")

        self.index = 0
        self.lock = threading.Lock()
        self.usage_count = {ip: 0 for ip in self.ipv6_list}
        self.blocked_until = {}  # ip -> timestamp khi hết block
        self.last_used = None  # IPv6 vừa dùng

    def get_next(self) -> str:
        with self.lock:
            now = time.time()

            # Tìm IPv6 không bị block
            attempts = 0
            while attempts < len(self.ipv6_list):
                ip = self.ipv6_list[self.index]
                self.index = (self.index + 1) % len(self.ipv6_list)

                # Kiểm tra có bị block không
                if ip in self.blocked_until:
                    if now < self.blocked_until[ip]:
                        attempts += 1
                        continue
                    else:
                        # Hết thời gian block
                        del self.blocked_until[ip]
                        print(f"[PROXY] ✓ Unblocked: {ip}")

                self.usage_count[ip] += 1
                self.last_used = ip
                return ip

            # Nếu tất cả đều bị block, dùng cái ít bị block nhất
            ip = self.ipv6_list[self.index]
            self.index = (self.index + 1) % len(self.ipv6_list)
            self.usage_count[ip] += 1
            self.last_used = ip
            print(f"[PROXY] ⚠️ All IPs blocked, using: {ip}")
            return ip

    def mark_blocked(self, ip: str = None):
        """Đánh dấu IPv6 bị block (rate limited)."""
        with self.lock:
            if ip is None:
                ip = self.last_used
            if ip:
                self.blocked_until[ip] = time.time() + self.BLOCK_DURATION
                print(f"[PROXY] ✗ Blocked for {self.BLOCK_DURATION}s: {ip}")

    def get_blocked_count(self) -> int:
        """Số IPv6 đang bị block."""
        now = time.time()
        return sum(1 for t in self.blocked_until.values() if now < t)

    def clear_blocked(self):
        """Xóa tất cả blocked IPs - dùng khi restart Chrome session."""
        with self.lock:
            count = len(self.blocked_until)
            self.blocked_until.clear()
            if count > 0:
                print(f"[PROXY] ✓ Cleared {count} blocked IPs")

    def stats(self):
        return dict(self.usage_count)


class SOCKS5Handler(threading.Thread):
    """Handle SOCKS5 connection with IPv6 source binding"""

    def __init__(self, client_socket, client_addr, rotator: IPv6Rotator):
        super().__init__()
        self.client = client_socket
        self.client_addr = client_addr
        self.rotator = rotator
        self.daemon = True

    def run(self):
        try:
            self.handle_socks5()
        except Exception as e:
            pass
        finally:
            try:
                self.client.close()
            except:
                pass

    def handle_socks5(self):
        # SOCKS5 greeting
        self.client.settimeout(30)
        data = self.client.recv(262)
        if len(data) < 2 or data[0] != 0x05:
            return

        # No auth required
        self.client.send(b'\x05\x00')

        # SOCKS5 request
        data = self.client.recv(4)
        if len(data) < 4:
            return

        ver, cmd, _, atyp = data[0], data[1], data[2], data[3]

        if ver != 0x05 or cmd != 0x01:  # Only CONNECT supported
            self.client.send(b'\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00')
            return

        # Parse destination address
        if atyp == 0x01:  # IPv4
            addr_data = self.client.recv(4)
            dest_addr = socket.inet_ntoa(addr_data)
            is_ipv4 = True
        elif atyp == 0x03:  # Domain name
            length = self.client.recv(1)[0]
            dest_addr = self.client.recv(length).decode('utf-8')
            is_ipv4 = None  # Will resolve later
        elif atyp == 0x04:  # IPv6
            addr_data = self.client.recv(16)
            dest_addr = socket.inet_ntop(socket.AF_INET6, addr_data)
            is_ipv4 = False
        else:
            self.client.send(b'\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00')
            return

        # Port
        port_data = self.client.recv(2)
        dest_port = struct.unpack('!H', port_data)[0]

        # Get rotating IPv6
        source_ipv6 = self.rotator.get_next()

        # Connect to destination
        try:
            remote = None

            # For domain names, try to get IPv6 address first
            if is_ipv4 is None:
                original_domain = dest_addr

                # 1. Thử query IPv6 trực tiếp từ Google DNS (bypass system DNS)
                ipv6_addr = resolve_ipv6_direct(dest_addr)
                if ipv6_addr:
                    dest_addr = ipv6_addr
                    is_ipv4 = False
                    print(f"[DNS] {original_domain} → {ipv6_addr} (IPv6)")
                else:
                    # 2. Fallback: thử system getaddrinfo
                    try:
                        infos = socket.getaddrinfo(dest_addr, dest_port, socket.AF_INET6, socket.SOCK_STREAM)
                        if infos:
                            dest_addr = infos[0][4][0]
                            is_ipv4 = False
                            print(f"[DNS] {original_domain} → {dest_addr} (IPv6 system)")
                    except:
                        pass

                    # 3. Nếu vẫn không có IPv6
                    if is_ipv4 is None:
                        if IPV6_ONLY_MODE:
                            # Chế độ IPv6-only: từ chối kết nối
                            print(f"[BLOCKED] {original_domain} - No IPv6 (IPv6-only mode)")
                            self.client.send(b'\x05\x04\x00\x01\x00\x00\x00\x00\x00\x00')
                            return
                        else:
                            # Fallback to IPv4
                            try:
                                dest_addr = socket.gethostbyname(original_domain)
                                is_ipv4 = True
                                print(f"[DNS] {original_domain} → {dest_addr} (IPv4 fallback)")
                            except:
                                self.client.send(b'\x05\x04\x00\x01\x00\x00\x00\x00\x00\x00')
                                return

            if is_ipv4:
                if IPV6_ONLY_MODE:
                    # Chế độ IPv6-only: từ chối kết nối IPv4 direct
                    print(f"[BLOCKED] {dest_addr}:{dest_port} - IPv4 direct blocked")
                    self.client.send(b'\x05\x02\x00\x01\x00\x00\x00\x00\x00\x00')
                    return
                else:
                    # For IPv4 destinations, connect directly (can't use IPv6 source)
                    remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    remote.settimeout(30)
                    remote.connect((dest_addr, dest_port))
                    print(f"[PROXY] direct → {dest_addr}:{dest_port}")
            else:
                # For IPv6 destinations, use our rotating IPv6
                remote = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
                remote.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                remote.bind((source_ipv6, 0))
                remote.settimeout(30)
                remote.connect((dest_addr, dest_port))
                print(f"[PROXY] {source_ipv6} → {dest_addr}:{dest_port}")

            # Success response
            self.client.send(b'\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00')

            # Relay data
            self.relay(self.client, remote)

        except Exception as e:
            print(f"[ERROR] Connect failed to {dest_addr}:{dest_port} - {e}")
            self.client.send(b'\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00')
        finally:
            if remote:
                try:
                    remote.close()
                except:
                    pass

    def relay(self, client, remote):
        """Relay data between client and remote using select"""
        sockets = [client, remote]

        while True:
            try:
                readable, _, exceptional = select.select(sockets, [], sockets, 60)

                if exceptional:
                    break

                if not readable:
                    break  # Timeout

                for sock in readable:
                    other = remote if sock is client else client
                    try:
                        data = sock.recv(65536)
                        if data:
                            other.sendall(data)
                        else:
                            return  # Connection closed
                    except:
                        return

            except:
                break


class ProxyServer(threading.Thread):
    """Proxy server that can run as background thread"""

    def __init__(self, rotator: IPv6Rotator):
        super().__init__()
        self.rotator = rotator
        self.daemon = True
        self.server = None

    def run(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((PROXY_HOST, PROXY_PORT))
        self.server.listen(100)
        print(f"[PROXY] Running on {PROXY_HOST}:{PROXY_PORT}")

        while True:
            try:
                client, addr = self.server.accept()
                handler = SOCKS5Handler(client, addr, self.rotator)
                handler.start()
            except:
                break

    def stop(self):
        if self.server:
            self.server.close()


def main():
    print("=" * 60)
    print("  IPv6 ROTATING PROXY SERVER")
    print("=" * 60)
    print()

    try:
        rotator = IPv6Rotator(IPV6_LIST)
    except Exception as e:
        print(f"[ERROR] {e}")
        print("\n[TIP] Run PowerShell as Admin:")
        print("  powershell -ExecutionPolicy Bypass -File add_ipv6_windows.ps1")
        return

    print(f"[INFO] Starting SOCKS5 proxy on {PROXY_HOST}:{PROXY_PORT}")
    print(f"[MODE] IPv6-only mode: {'ON (sẽ block IPv4 fallback)' if IPV6_ONLY_MODE else 'OFF'}")
    print(f"\n[USAGE] Start Chrome with proxy:")
    print(f'  chrome.exe --proxy-server="socks5://127.0.0.1:1080" --remote-debugging-port=9222')
    print("\n" + "=" * 60)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((PROXY_HOST, PROXY_PORT))
    server.listen(100)

    print(f"\n[OK] Proxy server running... (Ctrl+C to stop)\n")

    try:
        while True:
            client, addr = server.accept()
            handler = SOCKS5Handler(client, addr, rotator)
            handler.start()
    except KeyboardInterrupt:
        print("\n\n[INFO] Stopping...")
        print("\n[STATS] IPv6 usage:")
        for ip, count in rotator.stats().items():
            if count > 0:
                print(f"  {ip}: {count} requests")
    finally:
        server.close()


if __name__ == "__main__":
    main()
