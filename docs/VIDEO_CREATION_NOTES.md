# Video Creation Notes (T2V → I2V Conversion)

## Tổng quan

Tool tạo video từ ảnh sử dụng flow T2V → I2V conversion:
- Chrome ở mode **"Từ văn bản sang video"** (Text-to-Video)
- Interceptor convert request T2V thành I2V (Image-to-Video)

## Flow hoạt động

```
1. Chrome ở mode T2V ("Từ văn bản sang video")
2. User gửi prompt → Chrome tạo T2V request
3. Interceptor bắt request và convert:
   - URL: batchAsyncGenerateVideoText → batchAsyncGenerateVideoReferenceImages
   - Thêm referenceImages với mediaId của ảnh đã upload
   - Convert model: veo_3_1_t2v_* → veo_3_1_r2v_*_landscape_*
   - Giữ TẤT CẢ requests (batch support)
4. Gửi I2V request → API trả về video
```

## Model Conversion

```
T2V Model: veo_3_1_t2v_fast_ultra_relaxed
    ↓
I2V Model: veo_3_1_r2v_fast_landscape_ultra_relaxed
```

Các bước convert:
1. `_t2v_` → `_r2v_`
2. Thêm `_landscape` trước `_ultra`
3. Giữ nguyên `veo_3_1` và `_relaxed`

## Payload I2V thành công (mẫu)

```json
{
  "clientContext": {
    "recaptchaToken": "...",
    "sessionId": ";timestamp",
    "projectId": "uuid",
    "tool": "PINHOLE",
    "userPaygateTier": "PAYGATE_TIER_TWO"
  },
  "requests": [
    {
      "aspectRatio": "VIDEO_ASPECT_RATIO_LANDSCAPE",
      "seed": 12345,
      "textInput": {"prompt": "..."},
      "videoModelKey": "veo_3_1_r2v_fast_landscape_ultra_relaxed",
      "metadata": {"sceneId": "uuid"},
      "referenceImages": [{
        "imageUsageType": "IMAGE_USAGE_TYPE_ASSET",
        "mediaId": "CAMSJDhl..."
      }]
    },
    {
      "aspectRatio": "VIDEO_ASPECT_RATIO_LANDSCAPE",
      "seed": 67890,
      "textInput": {"prompt": "..."},
      "videoModelKey": "veo_3_1_r2v_fast_landscape_ultra_relaxed",
      "metadata": {"sceneId": "uuid"},
      "referenceImages": [{
        "imageUsageType": "IMAGE_USAGE_TYPE_ASSET",
        "mediaId": "CAMSJDhl..."
      }]
    }
  ]
}
```

## Lưu ý quan trọng

1. **PHẢI giữ TẤT CẢ requests** - API I2V hỗ trợ batch (2 requests)
2. **PHẢI thêm `_landscape`** vào model I2V
3. **KHÔNG đổi `veo_3_1` → `veo_3_0`** - I2V veo 3.1 hoạt động!
4. **KHÔNG strip `_relaxed`** - I2V accept suffix này
5. **Giữ seed** - I2V cần seed

## Files liên quan

- `run_worker_video.py` - Worker tạo video
- `modules/drission_flow_api.py` - Interceptor JS code (JS_INTERCEPTOR)
- Function: `generate_video_t2v_mode()`, `switch_to_t2v_mode()`

## Xử lý lỗi 403

Khi gặp 403:
1. Reset Chrome
2. Xóa Chrome data (cookies, cache)
3. Đăng nhập lại Google
4. Rotate IPv6 nếu cần

---
Last updated: 2026-01-15
