# VE3 Tool Simple - Project Context

## Tổng quan
**Phần mềm tạo video YouTube tự động** sử dụng Veo3 Flow (labs.google/fx).

### Mục đích
- Tool này chạy trên **MÁY ẢO (VM)**
- Các VM tạo: Excel (kịch bản) → Ảnh → Video → Visual
- Sau đó chuyển kết quả về **MÁY CHỦ (Master)**

### Workflow hoàn chỉnh

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         MÁY CHỦ (Master)                                │
│  - Chứa file SRT gốc (phụ đề video)                                     │
│  - Nhận kết quả cuối cùng (ảnh + video)                                 │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ (1) Lấy SRT
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    MÁY ẢO (VM) - Tool này                               │
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │              VM_MANAGER_GUI.PY (Entry Point)                     │   │
│   │                   - GUI chính (Tkinter)                          │   │
│   │                   - Điều phối tất cả workers                     │   │
│   │                   - TẤT CẢ XOAY QUANH NÓ                         │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                │                                         │
│         ┌──────────────────────┼──────────────────────┐                 │
│         ▼                      ▼                      ▼                 │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│   │ Excel Worker │    │Chrome Worker1│    │Chrome Worker2│              │
│   │  (Python)    │    │   (Python)   │    │   (Python)   │              │
│   │              │    │              │    │              │              │
│   │ SRT → Excel  │    │ Excel → Ảnh  │    │ Excel → Ảnh  │              │
│   │ (API AI)     │    │ (Google Flow)│    │ (Google Flow)│              │
│   └──────────────┘    └──────────────┘    └──────────────┘              │
│                                                                         │
│   (2) Bước 1: SRT → Excel (7 steps qua API DeepSeek/Gemini)            │
│       - Phân tích story → Tạo segments → Characters → Locations         │
│       - Director plan → Scene planning → Scene prompts                  │
│                                                                         │
│   (3) Bước 2: Excel → Ảnh + Video (Chrome automation với Google Flow)   │
│       - Chrome 1: Tạo ảnh scenes chẵn (2,4,6...) + reference images     │
│       - Chrome 2: Tạo ảnh scenes lẻ (1,3,5...)                          │
│       - Song song để tối ưu tốc độ                                      │
│                                                                         │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ (4) Trả kết quả
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         MÁY CHỦ (Master)                                │
│  - Nhận ảnh (img/*.png)                                                 │
│  - Nhận video (nếu có)                                                  │
│  - Tiếp tục xử lý (compose video, upload YouTube...)                    │
└─────────────────────────────────────────────────────────────────────────┘
```

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

### 2026-01-23 - Excel API 100% SRT Coverage (v1.0.4)
- **CRITICAL**: Fixed Excel worker losing scenes and SRT coverage
- **4 Major Fixes in `modules/progressive_prompts.py`**:
  1. **VALIDATION 1 (lines 833-1021)**: Split disproportionate segments
     - Ratio > 15: Local split into smaller segments
     - Ratio > 30: Recursive API retry with smaller input
  2. **VALIDATION 2 (lines 1023-1130)**: API call for missing segments
     - Detects gaps in SRT coverage after Step 2
     - Calls API for missing ranges with proper context
     - Recalculates image_count: `seg_entries / 10`
  3. **GAP-FILL (lines 2146-2198)**: Post-processing in Step 5
     - Finds all uncovered SRT indices
     - Creates fill scenes (max 10 SRT per scene)
     - Guarantees 100% SRT coverage
  4. **Duplicate Fallback (line ~2730)**: No more skipped batches
     - Creates unique fallback prompts instead of skipping
     - Prevents losing scenes due to >80% duplicates
- **Test Result (KA2-0238)**: 1183 SRT entries, 100% coverage, 520 scenes

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

### Phiên hiện tại: 2026-01-23 - Excel API 100% SRT Coverage (COMPLETED ✅)

**MISSION**: Fix Excel worker để đảm bảo 100% SRT coverage - không được thiếu scene

**STATUS**: ✅ ALL FIXES APPLIED & TESTED

**4 CRITICAL FIXES IN `modules/progressive_prompts.py`**:

1. **VALIDATION 1 (lines 833-1021)**: Split disproportionate segments
   - Problem: 1 segment có 833 SRT entries nhưng chỉ 4 images → mất 28 phút video
   - Fix: Ratio > 15 → split locally, Ratio > 30 → recursive API retry

2. **VALIDATION 2 (lines 1023-1130)**: API call for missing segments
   - Problem: Step 2 không cover hết SRT range
   - Fix: Detect gaps, call API for missing ranges, recalculate image_count

3. **GAP-FILL (lines 2146-2198)**: Post-processing in Step 5
   - Problem: API scenes không có proper srt_indices
   - Fix: Find uncovered SRT, create fill scenes (max 10 SRT per scene)

4. **Duplicate Fallback (line ~2730)**: No more skipped batches
   - Problem: >80% duplicates → skip batch → lose 10 scenes
   - Fix: Create unique fallback prompts instead of skipping

**TEST RESULT (KA2-0238)**:
- SRT entries: 1183
- Step 2 coverage: 100%
- Step 5 coverage: 100% (with GAP-FILL)
- Total scenes: 520

**KEY INSIGHT**: Khi API trả về không đủ data:
- Chia nhỏ input
- Gọi lại API song song
- Validate và fill gaps sau mỗi step

**STATUS: ✅ PRODUCTION READY** - Excel worker đảm bảo 100% SRT coverage

### Backlog (việc cần làm)

**High Priority:**
- [x] **API Validation Framework**: ✅ DONE (v1.0.4)
  - VALIDATION 1: Check ratio, split if disproportionate
  - VALIDATION 2: Check coverage, call API for missing
  - GAP-FILL: Post-processing to fill remaining gaps
- [ ] **Pipeline Optimization**: Step 6+7 chạy song song (30-40% speedup)
  - Step 7 bắt đầu khi Step 6 hoàn thành batch đầu
  - Excel làm "message queue" giữa 2 steps

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
