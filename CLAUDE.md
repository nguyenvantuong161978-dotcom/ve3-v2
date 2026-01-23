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

### Phiên hiện tại: 2026-01-23 - Excel Worker Bug Hunt

**MISSION**: Chạy THẬT test AR8-0003 để tìm TẤT CẢ bugs trong BASIC/FULL video mode logic

**6 CRITICAL BUGS FOUND & FIXED** (commit 56f840a):

1. **Bug #1: director_plan missing segment_id column**
   - Step 7 không biết scene thuộc segment nào → ALL scenes có video_note=""
   - Fix: Added segment_id to DIRECTOR_PLAN_COLUMNS, updated save/get/update methods

2. **Bug #2: Step 6 crash - None[:slice] TypeError**
   - ALL 18 batches failed với "'NoneType' object is not subscriptable"
   - Root: `scene.get('srt_text', '')[:200]` returns None nếu value là None!
   - Fix: Pattern `(scene.get('key') or default)[:x]` - applied 4 chỗ trong Step 6

3. **Bug #3: Step 7 crash - None.split() AttributeError**
   - 2/27 batches failed với "'NoneType' object has no attribute 'split'"
   - Fix: Pattern `(scene.get('key') or "").split()` - applied 10+ chỗ trong Step 7

4. **Bug #4: Scene class missing segment_id attribute**
   - Added segment_id param to __init__, to_dict(), from_dict()

5. **Bug #5: segment_id position causing DATA CORRUPTION** ⚠️ CRITICAL!
   - Thêm segment_id vào position 2 → shift ALL columns → data swap!
   - location_used chứa reference_files, characters_used chứa location_used
   - Fix: Moved segment_id to END of SCENES_COLUMNS (backward compatible)

6. **Enhancement: max_parallel_api 6 → 10** (25-30% speedup expected)

**CRITICAL PYTHON GOTCHA IDENTIFIED:**
```python
# When dict value is None (not missing):
data = {"key": None}

# ❌ WRONG - .get() with default DOESN'T WORK for None:
data.get("key", "default")  # Returns None, NOT "default"!

# ✅ CORRECT - use `or`:
data.get("key") or "default"  # Returns "default" when value is None
```

**API VALIDATION ISSUES DISCOVERED:**
- Step 2: Segments API failed → fallback (low quality)
- Step 5: Expected 60 scenes, got 52 → auto-fill 8 scenes
- Step 5: 31 SRT entries uncovered (93.2% coverage)

**FILES MODIFIED:**
- modules/excel_manager.py (~100 lines)
- modules/progressive_prompts.py (~30 lines)
- config/settings.yaml (max_parallel_api)
- Created 15+ test/debug scripts

**VERIFIED:**
- ✅ test_segment_id_fix.py: PASSED
- ✅ Excel audit: Raw data CORRECT (không phải lỗi API)
- ✅ Bug từ code đọc Excel, không phải API

**NEXT STEPS:**
1. ⏳ Regenerate AR8-0003 Excel với schema mới (segment_id ở column 19)
2. ⏳ Add API validation framework (check after each step, retry if incomplete)
3. ⏳ Implement pipeline Step 6+7 song song (30-40% speedup)
4. ⏳ Test BASIC mode logic hoàn chỉnh

**DOCUMENTATION:**
- See BUGS_FOUND_2026_01_23.md for detailed analysis
- See FINAL_FIX_SUMMARY.md for complete summary

### Backlog (việc cần làm)

**High Priority:**
- [ ] **API Validation Framework**: Add validation after each Excel worker step
  - Check data completeness (no missing scenes, full coverage)
  - Retry mechanism for incomplete API responses
  - Quality metrics logging
- [ ] **Pipeline Optimization**: Step 6+7 chạy song song (30-40% speedup)
  - Step 7 bắt đầu khi Step 6 hoàn thành batch đầu
  - Excel làm "message queue" giữa 2 steps
- [ ] **Regenerate AR8-0003**: Test với schema mới (segment_id ở column 19)
  - Verify BASIC mode: Seg 1 video_note="", Seg 2+ video_note="SKIP"
  - Verify data integrity: no column shift, correct references

**Medium Priority:**
- [ ] Worker logs không hiển thị trong GUI (trade-off để Chrome automation hoạt động)
- [ ] Kiểm tra và làm sạch IPv6 list
- [ ] Test auto-recovery khi Chrome disconnect

**Low Priority:**
- [ ] Batch size optimization (Step 6: 15→20, Step 7: 10→15)
- [ ] Cache character/location lookups trong parallel processing

### Lịch sử phiên trước

**2026-01-22 - Chrome 2 Portable Path Fix:**
- Fixed Chrome 2 using wrong portable path (2 fixes applied)
- Created check_version.py to verify fixes
- Fixed CMD hiding and Chrome window positioning
- Commit: 43d3158
