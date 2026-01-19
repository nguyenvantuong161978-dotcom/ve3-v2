#!/usr/bin/env python3
"""
IPv6 Local Proxy - SOCKS5 proxy để Chrome dùng IPv6
===================================================

Tạo local SOCKS5 proxy tại localhost:1088
Proxy sẽ route traffic qua IPv6 address được chỉ định.

Chrome kết nối: localhost:1088 (IPv4)
Proxy kết nối ra ngoài: IPv6 address

Như vậy RDP vẫn dùng IPv4, Chrome dùng IPv6.
"""

import sys
import os

# Fix Windows encoding issues
if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except:
            pass
    if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
        try:
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        except:
            pass


import socket
import threading
import select
import struct
import time
from typing import Optional, Tuple, Callable


class IPv6SocksProxy:
    """Simple SOCKS5 proxy that routes traffic through IPv6."""

    SOCKS_VERSION = 5

    def __init__(
        self,
        listen_port: int = 1088,
        ipv6_address: str = None,
        log_func: Callable = print
    ):
        """
        Initialize IPv6 SOCKS5 proxy.

        Args:
            listen_port: Port to listen on (localhost)
            ipv6_address: IPv6 address to bind outgoing connections
            log_func: Logging function
        """
        self.listen_port = listen_port
        self.ipv6_address = ipv6_address
        self.log = log_func
        self._server_socket = None
        self._running = False
        self._thread = None

    def start(self) -> bool:
        """Start the proxy server in background thread."""
        if self._running:
            return True

        try:
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.bind(('127.0.0.1', self.listen_port))
            self._server_socket.listen(100)
            self._server_socket.settimeout(1.0)

            self._running = True
            self._thread = threading.Thread(target=self._accept_loop, daemon=True)
            self._thread.start()

            self.log(f"[IPv6-Proxy] [v] Started on localhost:{self.listen_port}")
            if self.ipv6_address:
                self.log(f"[IPv6-Proxy] → Routing via: {self.ipv6_address}")
            return True

        except Exception as e:
            self.log(f"[IPv6-Proxy] [x] Failed to start: {e}")
            return False

    def stop(self):
        """Stop the proxy server."""
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except:
                pass
        self.log("[IPv6-Proxy] Stopped")

    def set_ipv6(self, ipv6_address: str):
        """Update IPv6 address for outgoing connections."""
        self.ipv6_address = ipv6_address
        self.log(f"[IPv6-Proxy] → Now using: {ipv6_address}")

    def _accept_loop(self):
        """Accept incoming connections."""
        while self._running:
            try:
                client_socket, addr = self._server_socket.accept()
                # Handle each connection in a new thread
                handler = threading.Thread(
                    target=self._handle_client,
                    args=(client_socket,),
                    daemon=True
                )
                handler.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    self.log(f"[IPv6-Proxy] Accept error: {e}")

    def _handle_client(self, client_socket: socket.socket):
        """Handle SOCKS5 client connection."""
        try:
            # SOCKS5 handshake
            if not self._socks5_handshake(client_socket):
                client_socket.close()
                return

            # Get target address
            target = self._socks5_get_target(client_socket)
            if not target:
                client_socket.close()
                return

            host, port = target

            # Connect to target via IPv6
            remote_socket = self._connect_via_ipv6(host, port)
            if not remote_socket:
                # Send failure response
                client_socket.send(b'\x05\x04\x00\x01\x00\x00\x00\x00\x00\x00')
                client_socket.close()
                return

            # Send success response
            client_socket.send(b'\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00')

            # Relay data
            self._relay(client_socket, remote_socket)

        except Exception as e:
            pass
        finally:
            try:
                client_socket.close()
            except:
                pass

    def _socks5_handshake(self, sock: socket.socket) -> bool:
        """Perform SOCKS5 handshake."""
        try:
            # Receive greeting
            data = sock.recv(256)
            if len(data) < 2 or data[0] != self.SOCKS_VERSION:
                return False

            # Send response (no auth required)
            sock.send(b'\x05\x00')
            return True
        except:
            return False

    def _socks5_get_target(self, sock: socket.socket) -> Optional[Tuple[str, int]]:
        """Get target address from SOCKS5 request."""
        try:
            # Receive request
            data = sock.recv(4)
            if len(data) < 4:
                return None

            version, cmd, _, atyp = data

            if version != self.SOCKS_VERSION or cmd != 1:  # Only CONNECT
                return None

            # Get address
            if atyp == 1:  # IPv4
                addr_data = sock.recv(4)
                host = socket.inet_ntoa(addr_data)
            elif atyp == 3:  # Domain
                length = sock.recv(1)[0]
                host = sock.recv(length).decode('utf-8')
            elif atyp == 4:  # IPv6
                addr_data = sock.recv(16)
                host = socket.inet_ntop(socket.AF_INET6, addr_data)
            else:
                return None

            # Get port
            port_data = sock.recv(2)
            port = struct.unpack('!H', port_data)[0]

            return (host, port)
        except:
            return None

    def _connect_via_ipv6(self, host: str, port: int) -> Optional[socket.socket]:
        """Connect to target - CHỈ dùng IPv6 và BIND vào source IPv6 cụ thể."""
        try:
            # CHỈ dùng IPv6 - ÉP BUỘC
            addrinfo = socket.getaddrinfo(host, port, socket.AF_INET6, socket.SOCK_STREAM)

            if not addrinfo:
                self.log(f"[IPv6-Proxy] No IPv6 address for {host}")
                return None

            family, socktype, proto, canonname, sockaddr = addrinfo[0]
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(30)

            # === QUAN TRỌNG: BIND vào IPv6 cụ thể để ép dùng đúng source IP ===
            if self.ipv6_address:
                try:
                    # Bind socket vào IPv6 address đã chọn (port 0 = OS chọn port tự do)
                    sock.bind((self.ipv6_address, 0, 0, 0))  # (host, port, flowinfo, scope_id)
                except Exception as bind_err:
                    self.log(f"[IPv6-Proxy] Bind warning: {bind_err}")
                    # Vẫn thử connect dù bind fail

            sock.connect(sockaddr)
            return sock

        except Exception as e:
            self.log(f"[IPv6-Proxy] IPv6 connect failed: {e}")
            return None

    def _relay(self, client: socket.socket, remote: socket.socket):
        """Relay data between client and remote."""
        try:
            client.setblocking(False)
            remote.setblocking(False)

            while True:
                ready, _, _ = select.select([client, remote], [], [], 60)

                if not ready:
                    break

                for sock in ready:
                    try:
                        data = sock.recv(8192)
                        if not data:
                            return

                        if sock is client:
                            remote.send(data)
                        else:
                            client.send(data)
                    except:
                        return
        except:
            pass
        finally:
            try:
                remote.close()
            except:
                pass


# Global proxy instance
_proxy_instance: Optional[IPv6SocksProxy] = None


def get_ipv6_proxy(port: int = 1088, log_func: Callable = print) -> IPv6SocksProxy:
    """Get or create global IPv6 proxy instance."""
    global _proxy_instance

    if _proxy_instance is None:
        _proxy_instance = IPv6SocksProxy(listen_port=port, log_func=log_func)

    return _proxy_instance


def start_ipv6_proxy(ipv6_address: str, port: int = 1088, log_func: Callable = print) -> Optional[IPv6SocksProxy]:
    """Start IPv6 proxy with specified address."""
    proxy = get_ipv6_proxy(port, log_func)
    proxy.set_ipv6(ipv6_address)

    if not proxy._running:
        if proxy.start():
            return proxy
        return None

    return proxy
