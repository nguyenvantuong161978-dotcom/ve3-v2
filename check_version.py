"""
Check if code has latest fixes
"""
import sys
from pathlib import Path

print("=" * 70)
print("CHECKING CODE VERSION")
print("=" * 70)
print()

# Check drission_flow_api.py for the fix
drission_file = Path(__file__).parent / "modules" / "drission_flow_api.py"

if not drission_file.exists():
    print("[ERROR] drission_flow_api.py not found!")
    sys.exit(1)

with open(drission_file, 'r', encoding='utf-8') as f:
    content = f.read()

# Check for the fix
has_fix1 = "if not chrome_exe and not self._chrome_portable and platform.system()" in content
has_fix2 = "if not os.path.isabs(chrome_exe):" in content

print("Checking for Chrome 2 portable path fixes:")
print()
print(f"1. Auto-detect skip check: {'[OK] FOUND' if has_fix1 else '[X] MISSING'}")
print(f"2. Relative path conversion: {'[OK] FOUND' if has_fix2 else '[X] MISSING'}")
print()

if has_fix1 and has_fix2:
    print("[OK] Code has all fixes!")
    print()
    print("If Chrome 2 still uses wrong portable, the issue is elsewhere.")
else:
    print("[ERROR] Code MISSING fixes!")
    print()
    print("YOU NEED TO UPDATE CODE:")
    print("  1. Close tool")
    print("  2. Run UPDATE_MANUAL.bat")
    print("  3. Or click UPDATE button in GUI")
    print("  4. Or: git pull origin main")

print("=" * 70)
