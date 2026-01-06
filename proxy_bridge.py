#!/usr/bin/env python3
"""
Local Proxy Bridge for Webshare
===============================
Chạy local proxy server (không cần auth) → forward đến Webshare (có auth).
Chrome kết nối đến local proxy, không cần xử lý auth.

Usage:
    python proxy_bridge.py [local_port]

Ví dụ:
    python proxy_bridge.py 8888
    → Chrome dùng: http://127.0.0.1:8888
"""

import socket
import threading
import select
import base64
from typing import Tuple, Optional

# Default config
LOCAL_PORT = 8888


class ProxyBridge:
    """
    Local proxy bridge - nhận request từ Chrome,
    forward đến remote proxy với authentication.
    """

    def __init__(
        self,
        local_port: int = 8888,
        remote_host: str = "",
        remote_port: int = 0,
        username: str = "",
        password: str = ""
    ):
        self.local_port = local_port
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.username = username
        self.password = password
        self.running = False
        self.server_socket = None
        self._lock = threading.Lock()  # Thread-safe upstream updates

    def update_upstream(self, remote_host: str, remote_port: int,
                        username: str = None, password: str = None):
        """
        Đổi proxy upstream mà không cần restart Chrome.
        Thread-safe - có thể gọi trong khi đang xử lý requests.
        """
        with self._lock:
            self.remote_host = remote_host
            self.remote_port = remote_port
            if username is not None:
                self.username = username
            if password is not None:
                self.password = password
        print(f"[+] Switched upstream to {remote_host}:{remote_port}")

    def get_proxy_auth_header(self) -> str:
        """Tạo Proxy-Authorization header."""
        if self.username and self.password:
            auth = f"{self.username}:{self.password}"
            auth_b64 = base64.b64encode(auth.encode()).decode()
            return f"Proxy-Authorization: Basic {auth_b64}\r\n"
        return ""

    def handle_client(self, client_socket: socket.socket, client_addr: Tuple):
        """Xử lý một client connection."""
        try:
            # Nhận request từ client
            request = client_socket.recv(8192)
            if not request:
                client_socket.close()
                return

            # Parse request để lấy target host
            request_str = request.decode('utf-8', errors='ignore')
            first_line = request_str.split('\r\n')[0]
            method = first_line.split()[0]

            # Kết nối đến remote proxy (thread-safe read) với RETRY
            with self._lock:
                remote_host = self.remote_host
                remote_port = self.remote_port

            max_retries = 3
            remote_socket = None
            last_error = None

            for attempt in range(max_retries):
                try:
                    remote_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    remote_socket.settimeout(30)
                    remote_socket.connect((remote_host, remote_port))
                    break  # Thành công
                except Exception as e:
                    last_error = e
                    if remote_socket:
                        try:
                            remote_socket.close()
                        except:
                            pass
                    if attempt < max_retries - 1:
                        print(f"[!] Proxy connect failed (attempt {attempt+1}/{max_retries}): {e}")
                        import time
                        time.sleep(2)  # Wait before retry
                    else:
                        print(f"[!] Cannot connect to remote proxy after {max_retries} attempts: {e}")

            if remote_socket is None or last_error:
                client_socket.close()
                return

            if method == 'CONNECT':
                # HTTPS tunnel - gửi CONNECT với auth đến remote proxy
                target = first_line.split()[1]  # host:port

                connect_request = f"CONNECT {target} HTTP/1.1\r\n"
                connect_request += f"Host: {target}\r\n"
                connect_request += self.get_proxy_auth_header()
                connect_request += "\r\n"

                remote_socket.send(connect_request.encode())

                # Đọc response từ remote proxy
                response = remote_socket.recv(4096)
                response_str = response.decode('utf-8', errors='ignore')

                if '200' in response_str.split('\r\n')[0]:
                    # Tunnel established - báo client OK
                    client_socket.send(b"HTTP/1.1 200 Connection Established\r\n\r\n")

                    # Relay data giữa client và remote
                    self._relay(client_socket, remote_socket)
                else:
                    print(f"[!] Proxy auth failed: {response_str[:100]}")
                    client_socket.send(response)
            else:
                # HTTP request - thêm Proxy-Authorization header
                auth_header = self.get_proxy_auth_header()
                if auth_header:
                    # Insert auth header after first line
                    lines = request_str.split('\r\n')
                    lines.insert(1, auth_header.strip())
                    request = '\r\n'.join(lines).encode()

                remote_socket.send(request)

                # Relay response
                while True:
                    data = remote_socket.recv(8192)
                    if not data:
                        break
                    client_socket.send(data)

            remote_socket.close()
            client_socket.close()

        except Exception as e:
            print(f"[!] Error handling client: {e}")
            try:
                client_socket.close()
            except:
                pass

    def _relay(self, client: socket.socket, remote: socket.socket):
        """Relay data giữa 2 sockets."""
        sockets = [client, remote]
        try:
            while True:
                readable, _, _ = select.select(sockets, [], [], 60)
                if not readable:
                    break
                for sock in readable:
                    data = sock.recv(8192)
                    if not data:
                        return
                    if sock is client:
                        remote.send(data)
                    else:
                        client.send(data)
        except:
            pass

    def start(self):
        """Start proxy bridge server."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(('127.0.0.1', self.local_port))
        self.server_socket.listen(50)
        self.running = True

        print(f"[+] Proxy Bridge started on 127.0.0.1:{self.local_port}")
        print(f"[+] Forwarding to {self.remote_host}:{self.remote_port}")
        print(f"[+] Auth: {self.username}:****")
        print(f"[+] Chrome proxy: http://127.0.0.1:{self.local_port}")

        while self.running:
            try:
                client_socket, client_addr = self.server_socket.accept()
                thread = threading.Thread(
                    target=self.handle_client,
                    args=(client_socket, client_addr)
                )
                thread.daemon = True
                thread.start()
            except Exception as e:
                if self.running:
                    print(f"[!] Accept error: {e}")

    def stop(self):
        """Stop proxy bridge."""
        self.running = False
        if self.server_socket:
            self.server_socket.close()


def start_proxy_bridge(
    local_port: int,
    remote_host: str,
    remote_port: int,
    username: str,
    password: str
) -> ProxyBridge:
    """Start proxy bridge in background thread."""
    bridge = ProxyBridge(
        local_port=local_port,
        remote_host=remote_host,
        remote_port=remote_port,
        username=username,
        password=password
    )
    thread = threading.Thread(target=bridge.start)
    thread.daemon = True
    thread.start()
    return bridge


if __name__ == "__main__":
    import sys

    # Load proxy from config
    try:
        from webshare_proxy import init_proxy_manager
        from pathlib import Path

        proxy_file = Path("config/proxies.txt")
        if proxy_file.exists():
            manager = init_proxy_manager(proxy_file=str(proxy_file))
            if manager.proxies:
                proxy = manager.current_proxy
                print(f"[+] Loaded proxy: {proxy.endpoint}")

                local_port = int(sys.argv[1]) if len(sys.argv) > 1 else 8888

                bridge = ProxyBridge(
                    local_port=local_port,
                    remote_host=proxy.host,
                    remote_port=proxy.port,
                    username=proxy.username,
                    password=proxy.password
                )
                bridge.start()
            else:
                print("[!] No proxies loaded")
        else:
            print("[!] config/proxies.txt not found")

    except KeyboardInterrupt:
        print("\n[+] Stopped")
    except Exception as e:
        print(f"[!] Error: {e}")
