# VE3 Tool Simple - Project Context

## Tổng quan
**Phần mềm tạo video YouTube tự động** sử dụng Veo3 Flow (labs.google/fx).

### Mục đích
- Tool này chạy trên **MÁY ẢO (VM)**
- Các VM tạo: Excel (kịch bản) → Ảnh → Video → Visual
- Sau đó chuyển kết quả về **MÁY CHỦ (Master)**

### 2 Chức năng chính
1. **PY Đạo Diễn (Excel Worker)**: Tạo Excel kịch bản từ SRT - phân tích story, tạo segments, characters, locations, director plan, scene prompts
2. **Flow Image/Video (Chrome Workers)**: Tạo ảnh và video từ prompts bằng Google Veo3 Flow

- **Owner**: nguyenvantuong161978-dotcom
- **Repo chính thức**: https://github.com/nguyenvantuong161978-dotcom/ve3-tool-simple

## Kiến trúc chính

### Entry Points
- `vm_manager_gui.py` - GUI chính (Tkinter), quản lý workers
- `vm_manager.py` - Logic điều phối workers (VMManager class)
- `START.py` / `START.bat` - Khởi động tool

### Workers (chạy song song)
- **Excel Worker** (`run_excel_api.py`): Tạo Excel từ SRT (7 bước: story → segments → characters → locations → director_plan → scene_planning → prompts)
- **Chrome Worker 1** (`_run_chrome1.py`): Tạo ảnh scenes chẵn (2,4,6...) + reference images (nv/loc)
- **Chrome Worker 2** (`_run_chrome2.py`): Tạo ảnh scenes lẻ (1,3,5...)

### Modules quan trọng
- `modules/smart_engine.py` - Engine chính tạo ảnh/video
- `modules/drission_flow_api.py` - DrissionPage API cho Google Flow
- `modules/browser_flow_generator.py` - Browser automation
- `modules/excel_manager.py` - Quản lý Excel (PromptWorkbook)
- `modules/ipv6_manager.py` - Quản lý IPv6 rotation
- `modules/chrome_manager.py` - Quản lý Chrome instances

### Cấu trúc dữ liệu
```
PROJECTS/
└── {project_code}/
    ├── {code}.srt           # File phụ đề
    ├── {code}_prompts.xlsx  # Excel chứa prompts
    ├── nv/                  # Reference images (characters/locations)
    └── img/                 # Scene images (scene_001.png, ...)
```

## Config
- `config/settings.yaml` - Cấu hình chính (API keys, Chrome paths, IPv6...)
- `config/ipv6_list.txt` - Danh sách IPv6 addresses

## Quy tắc xử lý lỗi

### 403 Errors (Google Flow bị block)
- 3 lỗi liên tiếp → Xóa Chrome data + Restart worker
- 5 lỗi (bất kỳ worker) → Rotate IPv6 + Restart tất cả

### Chrome Data Clearing
- Xóa tất cả trong `Data/` folder
- GIỮ LẠI `Data/profile/First Run` để tránh first-run prompts

## Commands thường dùng

```bash
# Chạy GUI
python vm_manager_gui.py

# Chạy worker riêng
python run_excel_api.py --loop
python _run_chrome1.py
python _run_chrome2.py

# Git
git push official main  # Push lên repo chính thức
```

## Lưu ý quan trọng

1. **Chrome Portable**: Sử dụng 2 Chrome Portable riêng biệt
   - Chrome 1: `GoogleChromePortable/`
   - Chrome 2: `GoogleChromePortable - Copy/`

2. **Google Login**: Chrome phải đăng nhập Google trước khi chạy

3. **IPv6**: Cần có IPv6 list trong `config/ipv6_list.txt` để bypass rate limit

4. **Agent Protocol**: Workers giao tiếp qua `.agent/status/*.json`

## Recent Fixes

### 2026-01-22 - Chrome 2 Control Fix
- **CRITICAL**: Fixed Chrome 2 using wrong portable path
  - Added `not self._chrome_portable` check to prevent auto-detect override
  - Added relative-to-absolute path conversion in drission_flow_api.py
- Created check_version.py to verify fixes are applied
- Created FIX_CHROME2_INSTRUCTIONS.txt for user update guide
- Fixed CMD hiding (START.bat uses pythonw)
- Fixed Chrome window positioning (even split, no overlap)
- Added show_cmd_windows() function

### 2026-01-20
- Fix GUI hiển thị đúng ProjectStatus attributes
- Fix bug `scene_number` → `scene_id` trong `get_project_status()`
- Thêm Chrome data clearing khi 403 errors
- Xóa log cũ khi start worker mới
- Đổi UPDATE URL sang repo mới `ve3-tool-simple`

---

## GHI CHÚ CÔNG VIỆC (Session Notes)

> **QUAN TRỌNG**: Claude Code phải cập nhật section này sau mỗi phiên làm việc để phiên sau sử dụng hiệu quả.

### Phiên hiện tại: 2026-01-22 (Session 2 - Exception Handling & Auto Recovery)

**ISSUE: Chrome exception errors with no details**
- User reported: "[ERROR] [x] Exception:" with no message
- Root cause: Exception logging didn't show type/traceback
- Impact: Cannot debug why image generation fails

**FIXES APPLIED:**

**1. Enhanced Exception Logging (browser_flow_generator.py)**
- Line 4131-4134: Added exception type and full traceback
- Line 4265-4268: Same for retry phase exceptions
- Now shows: `{type(e).__name__}: {str(e)}` + traceback

**2. GUI Timezone Fix (vm_manager_gui.py)**
- Line 2006-2028: Changed `_get_git_version()` to use Vietnam timezone (GMT+7)
- Display format: `v{hash} | YYYY-MM-DD HH:MM (VN)`
- Commit: 52aee60

**3. Chrome Auto-Restart Logic (browser_flow_generator.py)**
- Line 3685-3687: Added `consecutive_exceptions` counter (max: 10)
- Line 3871: Reset counter on successful image generation
- Line 4131-4168: Main exception handler:
  - Track consecutive exceptions
  - If >= 10: Kill ALL Chrome processes + raise exception (worker restarts)
  - If Chrome/API error: Auto restart Chrome once
  - Reset counter after successful restart
- Line 4265-4296: Retry phase exception handler:
  - Detect Chrome/API errors
  - Restart Chrome and retry immediately
  - Continue if retry succeeds

**4. Kill All Chrome Logic**
- If 10+ consecutive exceptions: `taskkill /F /IM chrome.exe`
- Raise exception to trigger worker restart
- Prevents infinite loop when Chrome is stuck

**Completed this session:**
- [x] Fixed exception logging to show full details
- [x] Added Vietnam timezone to GUI version display
- [x] Added Chrome auto-restart when API/connection errors
- [x] Added kill-all-Chrome logic when too many exceptions
- [x] Tested and committed (3da0a85, 15f3a3f, cf77a30)
- [x] Pushed to GitHub with force update

**How it works now:**
1. Exception → Log type + traceback (debug)
2. If Chrome/API error → Auto restart Chrome
3. If 10+ consecutive exceptions → Kill all Chrome + worker restart
4. Reset counter on success or successful restart

**User feedback:**
- "NÓ CŨNG LÀ LỖI KHÔNG MỞ CHROME ĐÓ" ✅ Fixed with auto-restart
- "NẾU CỨNG THÌ RESET ALL CÁC CMD ĐÓ" ✅ Fixed with kill-all logic

### Backlog (việc cần làm)
- [ ] Worker logs không hiển thị trong GUI (trade-off để Chrome automation hoạt động)
- [ ] Kiểm tra và làm sạch IPv6 list
- [ ] Test auto-recovery khi Chrome disconnect

### Lịch sử phiên trước
_(Thêm tóm tắt phiên cũ vào đây)_
