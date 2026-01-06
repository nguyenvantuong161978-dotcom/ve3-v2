#!/usr/bin/env python3
"""
VE3 Tool - Debug Test
=====================
Test API với debug chi tiết để tìm nguyên nhân lỗi.
"""

import json
import requests
from pathlib import Path
from datetime import datetime

print("=" * 60)
print("  VE3 DEBUG TEST")
print("=" * 60)
print(f"  Time: {datetime.now()}")
print("=" * 60)

# Step 1: Bearer token
print("\n[1] BEARER TOKEN")
print("    Copy từ Network tab → Headers → authorization")
bearer = input("    Paste: ").strip()
if bearer.lower().startswith("bearer "):
    bearer = bearer[7:]
print(f"    ✓ Length: {len(bearer)} chars")
print(f"    ✓ Preview: {bearer[:20]}...{bearer[-10:]}")

# Step 2: x-browser-validation
print("\n[2] X-BROWSER-VALIDATION")
print("    Copy từ Network tab → Headers → x-browser-validation")
x_browser = input("    Paste: ").strip()
if x_browser:
    print(f"    ✓ Value: {x_browser}")
else:
    print("    ⚠ Bỏ qua (có thể gây lỗi)")

# Step 3: Payload file
print("\n[3] PAYLOAD FILE")
print("    Kéo file payload.json vào đây hoặc nhấn Enter để dùng Downloads")
file_input = input("    Path: ").strip().strip('"').strip("'")

# Tìm file
locations = []
if file_input:
    locations.append(Path(file_input))
locations.extend([
    Path.home() / "Downloads" / "payload.json",
    Path("payload.json"),
    Path("C:/Users/admin/Downloads/payload.json"),
])

payload = None
payload_path = None
for loc in locations:
    try:
        if loc.exists():
            payload = json.loads(loc.read_text(encoding='utf-8'))
            payload_path = loc
            break
    except:
        continue

if not payload:
    print("    ❌ Không tìm thấy payload.json!")
    print(f"    Đã thử: {[str(l) for l in locations]}")
    exit(1)

print(f"    ✓ Loaded: {payload_path}")
print(f"    ✓ File size: {payload_path.stat().st_size} bytes")

# Parse payload
requests_list = payload.get("requests", [])
if not requests_list:
    print("    ❌ Payload không có 'requests'!")
    exit(1)

first_req = requests_list[0]
client_ctx = first_req.get("clientContext", {})
project_id = client_ctx.get("projectId", "")
recaptcha = client_ctx.get("recaptchaToken", "")
prompt = first_req.get("prompt", "")

print(f"\n[4] PAYLOAD INFO")
print(f"    Project ID: {project_id}")
print(f"    Prompt: {prompt[:50]}...")
print(f"    recaptchaToken length: {len(recaptcha)}")
print(f"    recaptchaToken preview: {recaptcha[:30]}...{recaptcha[-10:] if len(recaptcha) > 40 else ''}")

# Build request
url = f"https://aisandbox-pa.googleapis.com/v1/projects/{project_id}/flowMedia:batchGenerateImages"

headers = {
    "Authorization": f"Bearer {bearer}",
    "Content-Type": "text/plain;charset=UTF-8",
    "Accept": "*/*",
    "Origin": "https://labs.google",
    "Referer": "https://labs.google/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}

if x_browser:
    headers["x-browser-validation"] = x_browser
    headers["x-browser-channel"] = "stable"
    headers["x-browser-year"] = "2025"

print(f"\n[5] REQUEST")
print(f"    URL: {url[:70]}...")
print(f"    Headers count: {len(headers)}")

print("\n" + "=" * 60)
print("  CALLING API...")
print("=" * 60)

try:
    resp = requests.post(
        url,
        headers=headers,
        data=json.dumps(payload),
        timeout=120
    )

    print(f"\n[RESPONSE]")
    print(f"    Status: {resp.status_code}")
    print(f"    Headers: {dict(resp.headers)}")

    if resp.status_code == 200:
        result = resp.json()

        if "media" in result and result["media"]:
            print(f"\n✅ SUCCESS! Got {len(result['media'])} images")

            output_dir = Path("./test_output")
            output_dir.mkdir(exist_ok=True)

            for i, media in enumerate(result["media"]):
                img_url = media.get("image", {}).get("generatedImage", {}).get("fifeUrl")
                seed = media.get("seed", "unknown")

                if img_url:
                    print(f"\n    Image {i+1}:")
                    print(f"      Seed: {seed}")
                    print(f"      URL: {img_url[:50]}...")

                    try:
                        img_resp = requests.get(img_url, timeout=60)
                        if img_resp.status_code == 200:
                            filename = f"debug_{datetime.now().strftime('%H%M%S')}_{i+1}.png"
                            (output_dir / filename).write_bytes(img_resp.content)
                            print(f"      ✓ Saved: {output_dir / filename}")
                    except Exception as e:
                        print(f"      ❌ Download error: {e}")
        else:
            print(f"\n⚠ Response has no images:")
            print(json.dumps(result, indent=2)[:500])

    elif resp.status_code == 401:
        print("\n❌ 401 UNAUTHORIZED")
        print("   → Bearer token hết hạn!")
        print("   → Cần lấy Bearer MỚI từ Network tab")
        print(f"\n   Response: {resp.text[:300]}")

    elif resp.status_code == 403:
        print("\n❌ 403 FORBIDDEN")
        resp_text = resp.text.lower()

        if "recaptcha" in resp_text:
            print("   → recaptchaToken đã hết hạn hoặc đã dùng!")
            print("   → Cần tạo ảnh MỚI trong Chrome để có payload MỚI")
        elif "permission" in resp_text:
            print("   → Không có quyền truy cập project này")
        else:
            print("   → Có thể thiếu x-browser-validation")

        print(f"\n   Response: {resp.text[:500]}")

    else:
        print(f"\n❌ ERROR {resp.status_code}")
        print(f"   Response: {resp.text[:500]}")

except requests.exceptions.Timeout:
    print("\n❌ TIMEOUT (>120s)")
except Exception as e:
    print(f"\n❌ EXCEPTION: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
