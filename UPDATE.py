#!/usr/bin/env python3
"""
VE3 Tool - Auto Updater
Tai phien ban moi tu GitHub (khong can git)
"""

import os
import sys
import json
import shutil
import zipfile
import urllib.request
import ssl
from pathlib import Path

# Disable SSL verification (fix for Windows)
ssl._create_default_https_context = ssl._create_unverified_context

TOOL_DIR = Path(__file__).parent
CONFIG_DIR = TOOL_DIR / "config"
BRANCH_FILE = CONFIG_DIR / "current_branch.txt"

# GitHub repo info
GITHUB_USER = "criggerbrannon-hash"
GITHUB_REPO = "ve3-tool-simple"

def get_current_branch() -> str:
    """Doc branch hien tai tu config"""
    if BRANCH_FILE.exists():
        return BRANCH_FILE.read_text().strip()
    return "main"

def save_current_branch(branch: str):
    """Luu branch hien tai"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    BRANCH_FILE.write_text(branch)

def download_and_extract(branch: str) -> bool:
    """Tai va giai nen code tu GitHub"""
    # URL encode branch name (replace / with %2F)
    branch_encoded = branch.replace("/", "%2F")

    # Try different URL formats
    urls = [
        f"https://github.com/{GITHUB_USER}/{GITHUB_REPO}/archive/refs/heads/{branch_encoded}.zip",
        f"https://github.com/{GITHUB_USER}/{GITHUB_REPO}/archive/{branch_encoded}.zip",
        f"https://codeload.github.com/{GITHUB_USER}/{GITHUB_REPO}/zip/refs/heads/{branch}",
    ]

    zip_path = TOOL_DIR / "update.zip"
    temp_dir = TOOL_DIR / "update_temp"

    # Try each URL
    downloaded = False
    for url in urls:
        try:
            print(f"[*] Trying: {url[:60]}...")
            urllib.request.urlretrieve(url, zip_path)
            if zip_path.exists() and zip_path.stat().st_size > 1000:
                downloaded = True
                print(f"[OK] Downloaded!")
                break
        except Exception as e:
            print(f"[!] Failed: {e}")
            continue

    if not downloaded:
        print(f"[ERROR] Could not download branch: {branch}")
        return False

    # Extract
    try:
        print(f"[*] Extracting...")
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(temp_dir)

        # Find extracted folder
        extracted_folders = list(temp_dir.iterdir())
        if not extracted_folders:
            print(f"[ERROR] Empty archive!")
            return False

        src_dir = extracted_folders[0]

        # Copy files (skip config to preserve local settings)
        print(f"[*] Updating files...")
        for item in src_dir.iterdir():
            dst = TOOL_DIR / item.name
            if item.name == "config":
                continue  # Skip config folder
            if item.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(item, dst)
            else:
                shutil.copy2(item, dst)

        print(f"[OK] Updated successfully!")
        return True

    except Exception as e:
        print(f"[ERROR] Extract failed: {e}")
        return False

    finally:
        # Cleanup
        if zip_path.exists():
            zip_path.unlink()
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

def main():
    print("=" * 40)
    print("  VE3 Tool - Auto Updater")
    print("=" * 40)

    # Clear Python cache to prevent stale bytecode issues
    print("[*] Clearing Python cache...")
    for cache_dir in TOOL_DIR.rglob("__pycache__"):
        try:
            shutil.rmtree(cache_dir)
        except:
            pass
    for pyc_file in TOOL_DIR.rglob("*.pyc"):
        try:
            pyc_file.unlink()
        except:
            pass

    # Check for branch argument
    if len(sys.argv) > 1:
        branch = sys.argv[1]
        save_current_branch(branch)
        print(f"[*] Switching to branch: {branch}")
    else:
        branch = get_current_branch()
        print(f"[*] Current branch: {branch}")

    print()

    if download_and_extract(branch):
        print()
        print("=" * 40)
        print("  UPDATE COMPLETE!")
        print("=" * 40)
        return 0
    else:
        print()
        print("[!] Update failed, using local version")
        return 1

if __name__ == "__main__":
    sys.exit(main())
