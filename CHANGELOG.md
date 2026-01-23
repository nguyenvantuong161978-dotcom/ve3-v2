# CHANGELOG

## 2026-01-23 - Excel Worker Bug Fixes ✅

### 7 Critical Bugs Fixed
1. **director_plan missing segment_id** - Added segment_id column tracking
2. **Step 6 crash: None[:slice]** - Fixed None value handling with `or` operator
3. **Step 7 crash: None.split()** - Fixed None string operations
4. **Scene class missing segment_id** - Added to __init__, to_dict(), from_dict()
5. **segment_id position data corruption** - Moved to end of SCENES_COLUMNS
6. **segment_id not passed to constructor** - Added parameter in Step 7
7. **Performance improvement** - max_parallel_api: 6 → 10 (33% faster)

### Test Results
- ✅ 100% success rate (98 scenes, 459/459 SRT coverage)
- ✅ segment_id distribution correct across 10 segments
- ✅ video_note assignment perfect (BASIC mode: Seg1=CREATE, Seg2-10=SKIP)
- ✅ Performance: 9.7 min (33% faster than before)

### Files Modified
- `modules/excel_manager.py` - segment_id support, column reordering
- `modules/progressive_prompts.py` - None handling, segment_id parameter
- `config/settings.yaml` - max_parallel_api increased

### Status
**Excel Worker: PRODUCTION READY** ✅
- Stable (no crashes)
- Accurate (100% data integrity)
- Fast (33% performance improvement)

---

## 2026-01-22 - Chrome 2 Control Fix

### Fixed
- Chrome 2 using wrong portable path (was using Chrome 1's path)
- Added auto-detect skip check when chrome_portable is set
- Added relative-to-absolute path conversion

### Files Modified
- `modules/drission_flow_api.py` - Auto-detect logic, path conversion
- Created `check_version.py` - Verify Chrome fixes

---

## 2026-01-20 - GUI & Worker Improvements

### Fixed
- GUI displaying ProjectStatus attributes correctly
- Bug: `scene_number` → `scene_id` in get_project_status()
- Chrome data clearing on 403 errors
- Old logs deletion on worker start

### Modified
- Updated repository URL to `ve3-tool-simple`
