# BUGS FOUND AND FIXED - 2026-01-23

## Session Goal
Run REAL test on AR8-0003 project to find all bugs in video mode logic (BASIC vs FULL).

## Critical Bugs Found and Fixed

### BUG #1: director_plan Missing segment_id Column
**Symptom:** Step 7 couldn't determine which segment each scene belongs to, resulting in ALL scenes having video_note="" instead of BASIC mode behavior where Segment 2+ should have video_note="SKIP".

**Root Cause:**
- `director_plan` sheet didn't have `segment_id` column
- When Step 7 read director_plan, it got no segment_id, defaulted to 1
- ALL scenes treated as Segment 1

**Fix:**
1. Added "segment_id" to DIRECTOR_PLAN_COLUMNS (excel_manager.py line 58)
2. Updated save_director_plan() to write segment_id to column 2
3. Updated get_director_plan() to read segment_id from column 2
4. Updated update_director_plan_status() to write status to column 11 (was 6)

**Files Modified:**
- modules/excel_manager.py

**Status:** ✅ FIXED and TESTED

---

### BUG #2: Step 6 - NoneType object is not subscriptable
**Symptom:** Step 6 (scene planning) failed with "'NoneType' object is not subscriptable" in ALL 18 batches.

**Root Cause:**
- director_plan entries had keys with None values (srt_text=None, img_prompt=None)
- Code used `scene.get('srt_text', '')[:200]`
- When value is None, `.get()` returns None instead of default ''
- `None[:200]` raised "'NoneType' object is not subscriptable"

**Examples:**
```python
# BROKEN:
scene.get('srt_text', '')[:200]  # Returns None if srt_text=None

# FIXED:
(scene.get('srt_text') or '')[:200]  # Returns '' if srt_text=None
```

**Fix:**
- progressive_prompts.py lines 2006-2009: Added `or ''` to handle None values
- progressive_prompts.py lines 2078-2079: Added `or "default"` for fallback prompts

**Files Modified:**
- modules/progressive_prompts.py (Step 6)

**Status:** ✅ FIXED

---

### BUG #3: Step 7 - NoneType object has no attribute 'split'
**Symptom:** Step 7 (scene prompts) had 2/27 batches fail with "'NoneType' object has no attribute 'split'".

**Root Cause:**
- Similar to Bug #2, but for `.split()` operations
- Code used `scene.get("characters_used", "").split(",")`
- When value is None, `.get()` returns None
- `None.split(",")` raised "'NoneType' object has no attribute 'split'"

**Examples:**
```python
# BROKEN:
scene.get("characters_used", "").split(",")  # Fails if characters_used=None

# FIXED:
(scene.get("characters_used") or "").split(",")  # Works even if None
```

**Fix:**
- progressive_prompts.py line 2243: Fixed characters_used with `or ""`
- progressive_prompts.py line 2253: Fixed location_used with `or ""`
- progressive_prompts.py lines 2265-2271: Fixed all plan.get() calls with `or ''`
- progressive_prompts.py lines 2276-2282: Fixed all scene.get() calls with `or ''`
- progressive_prompts.py lines 2372-2375: Fixed fallback prompt variables with `or ""`

**Files Modified:**
- modules/progressive_prompts.py (Step 7)

**Status:** ✅ FIXED

---

## Pattern Identified

**CRITICAL PYTHON GOTCHA:**
```python
# When dict value is None (not missing):
data = {"key": None}

# .get() with default DOESN'T WORK:
data.get("key", "default")  # Returns None, NOT "default"!

# CORRECT approach:
data.get("key") or "default"  # Returns "default" when value is None
```

This pattern appears throughout the codebase when Excel cells are empty/NULL - openpyxl returns None, not missing keys.

**Solution:** Always use `dict.get("key") or default_value` when None is possible.

---

## Tests Created

1. `test_segment_id_fix.py` - Verifies segment_id save/load in director_plan ✅ PASSED
2. `run_ar8_0003_full.py` - Full Excel worker test (all 7 steps)
3. `debug_director_plan.py` - Debug tool to inspect director_plan structure

---

## Current Test Status

Running full test on AR8-0003 (background task b9571c8)...

**Expected Results:**
- All 7 steps complete without errors
- director_plan has segment_id for all entries
- BASIC mode behavior:
  - Segment 1 scenes: video_note="" (CREATE video)
  - Segment 2+ scenes: video_note="SKIP" (skip video)
- 265/265 scenes created (no batch errors)

---

## Next Steps

1. ✅ Wait for full test to complete
2. ⏳ Verify segment_id is correctly saved in director_plan
3. ⏳ Verify video_note is correctly assigned based on segment_id and mode
4. ⏳ Check for any remaining errors or edge cases
5. ⏳ Update CLAUDE.md with session notes
6. ⏳ Commit all fixes to git

---

## Summary for User (thutruc)

Đã tìm ra và fix 3 lỗi chính:

1. **Director plan thiếu segment_id** → Fixed Excel schema
2. **Step 6 crash do None[:slice]** → Fixed với `or ''`
3. **Step 7 crash do None.split()** → Fixed với `or ""`

Đang chạy test THẬT để verify tất cả fixes hoạt động đúng.
