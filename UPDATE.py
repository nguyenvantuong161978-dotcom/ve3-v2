"""
VE3 Tool - Auto Updater
=======================
Tu dong tai va cap nhat phien ban moi tu GitHub.
Khong can git - chi can ket noi internet.
"""

import os
import sys
import shutil
import zipfile
import tempfile
import urllib.request
from pathlib import Path

# Doc branch tu file config (de de dang chuyen session)
def get_current_branch():
    branch_file = Path(__file__).parent / "config" / "current_branch.txt"
    if branch_file.exists():
        return branch_file.read_text(encoding='utf-8').strip()
    return "main"  # Fallback to main

REPO = "criggerbrannon-hash/ve3-tool"
BRANCH = get_current_branch()
ZIP_URL = f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip"

# Thu muc hien tai
CURRENT_DIR = Path(__file__).parent

# Cac thu muc/file KHONG duoc ghi de (du lieu nguoi dung)
PROTECTED = [
    "PROJECTS",
    "chrome_profiles",
    "config/accounts.json",
    "config/tokens.json",
]


def download_update():
    """Tai ZIP tu GitHub."""
    print(f"[*] Dang tai update tu: {BRANCH}")
    print(f"    URL: {ZIP_URL}")

    # Tao temp file
    temp_zip = tempfile.mktemp(suffix=".zip")

    try:
        urllib.request.urlretrieve(ZIP_URL, temp_zip)
        print("[OK] Da tai xong!")
        return temp_zip
    except Exception as e:
        print(f"[ERROR] Loi tai: {e}")
        return None


def extract_and_update(zip_path):
    """Giai nen va cap nhat code."""
    print("[*] Dang giai nen...")

    temp_dir = tempfile.mkdtemp()

    try:
        # Giai nen
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(temp_dir)

        # Tim thu muc goc trong ZIP (ve3-tool-branch-name/)
        extracted = list(Path(temp_dir).iterdir())
        if not extracted:
            print("[ERROR] ZIP rong!")
            return False

        source_dir = extracted[0]
        print(f"[*] Source: {source_dir.name}")

        # Copy files, skip protected
        updated = 0
        skipped = 0

        for item in source_dir.rglob("*"):
            if item.is_file():
                rel_path = item.relative_to(source_dir)
                dest_path = CURRENT_DIR / rel_path

                # Check protected
                is_protected = False
                for p in PROTECTED:
                    if str(rel_path).startswith(p):
                        is_protected = True
                        break

                if is_protected and dest_path.exists():
                    skipped += 1
                    continue

                # Copy file
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest_path)
                updated += 1

        print(f"[OK] Da cap nhat {updated} files, bo qua {skipped} files")
        return True

    except Exception as e:
        print(f"[ERROR] Loi giai nen: {e}")
        return False
    finally:
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)
        if os.path.exists(zip_path):
            os.remove(zip_path)


def main():
    print("=" * 50)
    print("  VE3 TOOL - AUTO UPDATER")
    print("=" * 50)
    print()

    # Download
    zip_path = download_update()
    if not zip_path:
        return False

    # Extract and update
    if extract_and_update(zip_path):
        print()
        print("[OK] Cap nhat thanh cong!")
        print("[*] Hay chay lai RUN.bat hoac python ve3_pro.py")
        return True

    return False


if __name__ == "__main__":
    success = main()
    print()
    input("Nhan Enter de dong...")
    sys.exit(0 if success else 1)
