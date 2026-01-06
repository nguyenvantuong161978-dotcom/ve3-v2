#!/usr/bin/env python3
"""
Test Webshare Rotating Residential proxy
Theo hướng dẫn: https://help.webshare.io/

Webshare Rotating Residential format:
- Host: p.webshare.io
- Port: 80
- Username: {base_username}-{session_id}
- Password: từ dashboard

Mỗi session_id khác = IP khác
VD: jhvbehdf-residential-1, jhvbehdf-residential-999
"""
import requests

# Config từ Webshare dashboard
BASE_USERNAME = "jhvbehdf-residential"  # Base username (không có số)
PASSWORD = "cf1bi3yvq0t1"
HOST = "p.webshare.io"
PORT = 80

print("=" * 50)
print("WEBSHARE ROTATING RESIDENTIAL TEST")
print("=" * 50)
print(f"Host: {HOST}:{PORT}")
print(f"Base username: {BASE_USERNAME}")
print()

def test_with_session(session_id: int) -> str:
    """Test với một session ID cụ thể."""
    username = f"{BASE_USERNAME}-{session_id}"
    proxy_url = f"http://{username}:{PASSWORD}@{HOST}:{PORT}/"

    print(f"Testing session {session_id}: {username}")

    try:
        response = requests.get(
            "https://ipv4.webshare.io/",
            proxies={"http": proxy_url, "https": proxy_url},
            timeout=15
        )
        if response.status_code == 200:
            ip = response.text.strip()
            print(f"  → IP: {ip}")
            return ip
        elif response.status_code == 407:
            print("  → 407 Proxy Authentication Required")
            return "AUTH_ERROR"
        else:
            print(f"  → HTTP {response.status_code}")
            return f"HTTP_{response.status_code}"
    except Exception as e:
        print(f"  → Error: {e}")
        return str(e)

# Test 2 sessions khác nhau
print("Test 1: Session 1")
ip1 = test_with_session(1)

print("\nTest 2: Session 2")
ip2 = test_with_session(2)

print("\nTest 3: Session 999 (random)")
ip3 = test_with_session(999)

print("\n" + "=" * 50)
if ip1 and ip2 and ip3 and not any(x.startswith(("AUTH", "HTTP", "Error")) for x in [ip1, ip2, ip3]):
    unique_ips = len(set([ip1, ip2, ip3]))
    print(f"✓ Proxy hoạt động!")
    print(f"  {unique_ips}/3 IPs khác nhau")
    if unique_ips > 1:
        print("  → Rotating đang hoạt động!")
    else:
        print("  → Cùng IP (có thể cùng pool region)")
else:
    print("✗ Có lỗi - kiểm tra username/password")
