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

---

## 3 FILE PYTHON CHÍNH

### 1. `run_excel_api.py` - Excel Worker (PY Đạo Diễn)

**Mục đích**: Chuyển đổi file SRT (phụ đề) thành Excel kịch bản hoàn chỉnh qua 7 bước API.

**Input**: `PROJECTS/{code}/{code}.srt`
**Output**: `PROJECTS/{code}/{code}_prompts.xlsx`

**7 Bước xử lý**:
```
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 1: Story Analysis                                                  │
│   - Đọc toàn bộ SRT                                                     │
│   - API phân tích: thể loại, mood, style, tổng quan câu chuyện          │
│   - Output: story_analysis sheet trong Excel                            │
├─────────────────────────────────────────────────────────────────────────┤
│ STEP 2: Segments (Phân đoạn)                                            │
│   - Chia SRT thành các đoạn logic (mỗi đoạn ~5-15 SRT entries)          │
│   - VALIDATION 1: Check ratio SRT/images, split nếu quá lớn             │
│   - VALIDATION 2: Check coverage, call API bổ sung nếu thiếu            │
│   - Output: segments sheet (segment_id, name, srt_range, image_count)   │
├─────────────────────────────────────────────────────────────────────────┤
│ STEP 3: Characters (Nhân vật)                                           │
│   - API phân tích các nhân vật xuất hiện trong story                    │
│   - Output: characters sheet (id, name, description, appearance)        │
├─────────────────────────────────────────────────────────────────────────┤
│ STEP 4: Locations (Địa điểm)                                            │
│   - API phân tích các địa điểm/bối cảnh                                 │
│   - Output: locations sheet (id, name, description, atmosphere)         │
├─────────────────────────────────────────────────────────────────────────┤
│ STEP 5: Director Plan (Kế hoạch đạo diễn)                               │
│   - Tạo danh sách scenes cho từng segment                               │
│   - Mỗi scene: visual_moment, srt_start, srt_end, duration              │
│   - GAP-FILL: Đảm bảo 100% SRT coverage                                 │
│   - Output: director_plan sheet                                         │
├─────────────────────────────────────────────────────────────────────────┤
│ STEP 6: Scene Planning (Chi tiết hóa)                                   │
│   - API chi tiết từng scene: camera_angle, lighting, composition        │
│   - Parallel processing: 15 scenes/batch, max 10 concurrent             │
│   - Output: Update director_plan với chi tiết                           │
├─────────────────────────────────────────────────────────────────────────┤
│ STEP 7: Scene Prompts (Tạo prompts)                                     │
│   - Tạo img_prompt cho từng scene (dùng để tạo ảnh)                     │
│   - Parallel processing: 10 scenes/batch, max 10 concurrent             │
│   - Duplicate detection + fallback                                      │
│   - Output: scenes sheet (img_prompt, ref_files, characters_used, etc.) │
└─────────────────────────────────────────────────────────────────────────┘
```

**Key modules sử dụng**:
- `modules/progressive_prompts.py` - Logic 7 steps
- `modules/ai_providers.py` - API calls (DeepSeek/Gemini)
- `modules/excel_manager.py` - Excel I/O (PromptWorkbook class)

---

### 2. `_run_chrome1.py` - Chrome Worker 1

**Mục đích**: Tạo ảnh cho scenes CHẴN (2, 4, 6, 8...) + Reference images

**Chrome Portable**: `GoogleChromePortable/`

**Nhiệm vụ**:
```
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. TẠO REFERENCE IMAGES (ưu tiên cao)                                   │
│    - Characters: nv/{char_id}.png (ảnh nhân vật)                        │
│    - Locations: loc/{loc_id}.png (ảnh địa điểm)                         │
│    - Dùng làm style reference cho scenes                                │
├─────────────────────────────────────────────────────────────────────────┤
│ 2. TẠO SCENE IMAGES (scenes chẵn)                                       │
│    - Scene 2, 4, 6, 8, 10...                                            │
│    - Output: img/scene_002.png, img/scene_004.png...                    │
│    - Upload reference images kèm theo                                   │
├─────────────────────────────────────────────────────────────────────────┤
│ 3. TẠO VIDEO (nếu cần - video_mode)                                     │
│    - Dùng ảnh scene để tạo video clips                                  │
│    - Output: video/scene_XXX.mp4                                        │
└─────────────────────────────────────────────────────────────────────────┘
```

**Key modules sử dụng**:
- `modules/drission_flow_api.py` - DrissionPage browser control
- `modules/smart_engine.py` - Main image/video generation engine
- `modules/chrome_manager.py` - Chrome process management

---

### 3. `_run_chrome2.py` - Chrome Worker 2

**Mục đích**: Tạo ảnh cho scenes LẺ (1, 3, 5, 7...)

**Chrome Portable**: `GoogleChromePortable - Copy/` (riêng biệt để chạy song song)

**Nhiệm vụ**:
```
┌─────────────────────────────────────────────────────────────────────────┐
│ TẠO SCENE IMAGES (scenes lẻ)                                            │
│    - Scene 1, 3, 5, 7, 9...                                             │
│    - Output: img/scene_001.png, img/scene_003.png...                    │
│    - KHÔNG tạo reference (Chrome 1 đã làm)                              │
│    - skip_references=True để tránh trùng lặp                            │
└─────────────────────────────────────────────────────────────────────────┘
```

**Lý do tách 2 Chrome Workers**:
- Google Flow rate limit → chạy song song để tăng tốc 2x
- Chrome 1 tạo references trước, Chrome 2 chỉ tạo scenes
- Mỗi Chrome dùng folder Data riêng để tránh xung đột

**Key modules sử dụng** (giống Chrome 1):
- `modules/drission_flow_api.py`
- `modules/smart_engine.py`
- `modules/chrome_manager.py`

---

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
