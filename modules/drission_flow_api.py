#!/usr/bin/env python3
"""
VE3 Tool - DrissionPage Flow API
================================
Gọi Google Flow API trực tiếp bằng DrissionPage.

Flow:
1. Sử dụng Webshare proxy pool (tự động xoay khi bị block)
2. Mở Chrome với proxy → Vào Google Flow → Đợi user chọn project
3. Inject JS Interceptor để capture tokens + CANCEL request
4. Gọi API trực tiếp với captured URL + payload
"""

import sys
import os

# Fix Windows encoding issues - must be at module level
if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except:
            pass
    if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
        try:
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        except:
            pass

import json
import time
import random
import base64
import requests
import threading
import os
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any, Callable
from dataclasses import dataclass
from datetime import datetime

# Optional DrissionPage import
DRISSION_AVAILABLE = False
ContextLostError = None
try:
    from DrissionPage import ChromiumPage, ChromiumOptions
    from DrissionPage.errors import ContextLostError
    DRISSION_AVAILABLE = True
except ImportError:
    ChromiumPage = None
    ChromiumOptions = None

# Webshare Proxy imports (IPv6 proxy đã bị bỏ)
WEBSHARE_AVAILABLE = False
try:
    from webshare_proxy import WebshareProxy, get_proxy_manager, init_proxy_manager
    WEBSHARE_AVAILABLE = True
except ImportError:
    WebshareProxy = None
    get_proxy_manager = None
    init_proxy_manager = None


# ============================================================================
# SESSION STATE PERSISTENCE
# ============================================================================
SESSION_STATE_FILE = Path(__file__).parent.parent / "config" / "session_state.yaml"

def _load_session_state() -> Dict[str, Any]:
    """Load session state from file."""
    try:
        if SESSION_STATE_FILE.exists():
            import yaml
            with open(SESSION_STATE_FILE, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
    except Exception:
        pass
    return {}

def _save_session_state(state: Dict[str, Any]) -> None:
    """Save session state to file."""
    try:
        import yaml
        SESSION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SESSION_STATE_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(state, f, allow_unicode=True)
    except Exception:
        pass

def _get_last_session_id(machine_id: int, worker_id: int) -> Optional[int]:
    """Get last session ID for a machine/worker from persistent storage."""
    state = _load_session_state()
    key = f"machine_{machine_id}_worker_{worker_id}"
    return state.get(key)

def _save_last_session_id(machine_id: int, worker_id: int, session_id: int) -> None:
    """Save last session ID for a machine/worker to persistent storage."""
    state = _load_session_state()
    key = f"machine_{machine_id}_worker_{worker_id}"
    state[key] = session_id
    state['last_updated'] = datetime.now().isoformat()
    _save_session_state(state)


@dataclass
class GeneratedImage:
    """Kết quả ảnh được tạo."""
    url: str = ""
    base64_data: Optional[str] = None
    seed: Optional[int] = None
    media_name: Optional[str] = None
    local_path: Optional[Path] = None


# JS Interceptor - INJECT CUSTOM PAYLOAD với reCAPTCHA token fresh
# Flow: Python chuẩn bị payload (có media_id) → Chrome trigger reCAPTCHA → Inject token → Gửi ngay
JS_INTERCEPTOR = '''
window._tk=null;window._pj=null;window._xbv=null;window._rct=null;window._payload=null;window._sid=null;window._url=null;
window._response=null;window._responseError=null;window._requestPending=false;
window._customPayload=null; // Payload đầy đủ từ Python (có media_id) cho IMAGE
window._videoResponse=null;window._videoError=null;window._videoPending=false;
window._customVideoPayload=null; // Payload đầy đủ từ Python cho VIDEO (có referenceImages.mediaId)
window._t2vToI2vConfig=null; // Config để convert T2V request thành I2V (thêm referenceImages, đổi model)

(function(){
    if(window.__interceptReady) return 'ALREADY_READY';
    window.__interceptReady = true;

    var orig = window.fetch;
    window.fetch = async function(url, opts) {
        var urlStr = typeof url === 'string' ? url : url.url;

        // ============================================
        // IMAGE GENERATION REQUESTS
        // ============================================
        if (urlStr.includes('aisandbox') && (urlStr.includes('batchGenerate') || urlStr.includes('flowMedia'))) {
            console.log('[IMG] Request intercepted:', urlStr);

            // ============================================
            // FORCE VIDEO MODE: Thay đổi URL và payload thành VIDEO request
            // Ý tưởng: Gửi prompt như tạo ảnh, nhưng Interceptor đổi thành video
            // ============================================
            if (window._forceVideoPayload && urlStr.includes('batchGenerateImages')) {
                console.log('[FORCE-VIDEO] Intercepting image request -> Converting to VIDEO request');

                // Parse Chrome body để lấy fresh reCAPTCHA
                var chromeBodyForVideo = null;
                var freshRecaptchaForVideo = null;
                if (opts && opts.body) {
                    try {
                        chromeBodyForVideo = JSON.parse(opts.body);
                        if (chromeBodyForVideo.clientContext) {
                            freshRecaptchaForVideo = chromeBodyForVideo.clientContext.recaptchaToken;
                        }
                    } catch(e) {}
                }

                if (freshRecaptchaForVideo && window._forceVideoPayload) {
                    try {
                        var videoPayload = window._forceVideoPayload;

                        // Inject fresh reCAPTCHA từ Chrome
                        if (videoPayload.clientContext) {
                            videoPayload.clientContext.recaptchaToken = freshRecaptchaForVideo;
                            if (chromeBodyForVideo && chromeBodyForVideo.clientContext) {
                                videoPayload.clientContext.sessionId = chromeBodyForVideo.clientContext.sessionId;
                                videoPayload.clientContext.projectId = chromeBodyForVideo.clientContext.projectId;
                            }
                        }

                        // ĐỔI URL: /projects/xxx/flowMedia:batchGenerateImages -> /video:batchAsyncGenerateVideoReferenceImages
                        // I2V endpoint = "Tạo video từ các thành phần" - cần referenceImages với mediaId
                        // Video endpoint KHÔNG có /projects/xxx/ prefix
                        var projectsIdx = urlStr.indexOf('/projects/');
                        var newUrl;
                        if (projectsIdx !== -1) {
                            // Lấy base URL trước /projects/
                            var baseUrl = urlStr.substring(0, projectsIdx);
                            newUrl = baseUrl + '/video:batchAsyncGenerateVideoReferenceImages';
                        } else {
                            // Fallback: simple replace
                            newUrl = urlStr.replace('flowMedia:batchGenerateImages', 'video:batchAsyncGenerateVideoReferenceImages');
                        }
                        console.log('[FORCE-VIDEO] Original URL:', urlStr);
                        console.log('[FORCE-VIDEO] New URL:', newUrl);
                        console.log('[FORCE-VIDEO] mediaId:', videoPayload.requests[0].referenceImages[0].mediaId.substring(0, 50) + '...');

                        // Gửi VIDEO request thay vì IMAGE request
                        opts.body = JSON.stringify(videoPayload);
                        window._forceVideoPayload = null;

                        // Set video response handlers
                        window._videoPending = true;
                        window._videoResponse = null;
                        window._videoError = null;

                        try {
                            console.log('[FORCE-VIDEO] Sending video request with fresh reCAPTCHA...');
                            var videoResponse = await orig.apply(this, [newUrl, opts]);
                            var videoCloned = videoResponse.clone();
                            try {
                                window._videoResponse = await videoCloned.json();
                                console.log('[FORCE-VIDEO] Response status:', videoResponse.status);
                                if (window._videoResponse.operations) {
                                    console.log('[FORCE-VIDEO] Got operations:', window._videoResponse.operations.length);
                                }
                            } catch(e) {
                                window._videoResponse = {status: videoResponse.status, error: 'parse_failed'};
                            }
                            window._videoPending = false;
                            return videoResponse;
                        } catch(e) {
                            console.log('[FORCE-VIDEO] Request failed:', e);
                            window._videoError = e.toString();
                            window._videoPending = false;
                            throw e;
                        }
                    } catch(e) {
                        console.log('[FORCE-VIDEO] Failed to convert:', e);
                        window._forceVideoPayload = null;
                    }
                }
            }

            // Normal image flow continues below...
            // CHỈ reset nếu chưa có response (tránh override response đã có)
            if (!window._response) {
                window._requestPending = true;
                window._response = null;
                window._responseError = null;
                window._url = urlStr;
                console.log('[IMG] New request, reset state');
            } else {
                console.log('[IMG] Skip reset - already have response');
                return orig.apply(this, [url, opts]);  // Forward mà không intercept
            }

            // Capture headers
            if (opts && opts.headers) {
                var h = opts.headers;
                if (h['Authorization']) {
                    window._tk = h['Authorization'].replace('Bearer ', '');
                }
                if (h['x-browser-validation']) {
                    window._xbv = h['x-browser-validation'];
                }
            }

            // Parse Chrome's original body để lấy reCAPTCHA token FRESH
            var chromeBody = null;
            var freshRecaptcha = null;
            if (opts && opts.body) {
                try {
                    chromeBody = JSON.parse(opts.body);
                    // Lấy reCAPTCHA token từ Chrome (FRESH!)
                    if (chromeBody.recaptchaToken) {
                        freshRecaptcha = chromeBody.recaptchaToken;
                    } else if (chromeBody.clientContext && chromeBody.clientContext.recaptchaToken) {
                        freshRecaptcha = chromeBody.clientContext.recaptchaToken;
                    }
                    window._rct = freshRecaptcha;
                    window._pj = chromeBody.clientContext ? chromeBody.clientContext.projectId : null;
                    window._sid = chromeBody.clientContext ? chromeBody.clientContext.sessionId : null;
                } catch(e) {
                    console.log('[ERROR] Parse Chrome body failed:', e);
                }
            }

            // ============================================
            // CUSTOM PAYLOAD MODE: Thay thế body bằng payload của Python
            // ============================================
            if (window._customPayload && freshRecaptcha) {
                try {
                    var customBody = window._customPayload;

                    // INJECT fresh reCAPTCHA token vào payload của chúng ta
                    if (customBody.clientContext) {
                        customBody.clientContext.recaptchaToken = freshRecaptcha;
                        // Cũng copy sessionId và projectId
                        if (chromeBody && chromeBody.clientContext) {
                            customBody.clientContext.sessionId = chromeBody.clientContext.sessionId;
                            customBody.clientContext.projectId = chromeBody.clientContext.projectId;
                        }
                    }

                    // Thay thế body
                    opts.body = JSON.stringify(customBody);
                    console.log('[INJECT] Custom payload với fresh reCAPTCHA, gửi NGAY!');
                    console.log('[INJECT] imageInputs:', customBody.requests[0].imageInputs ? customBody.requests[0].imageInputs.length : 0);

                    // Clear để không dùng lại
                    window._customPayload = null;
                } catch(e) {
                    console.log('[ERROR] Inject custom payload failed:', e);
                }
            }
            // ============================================
            // SIMPLE MODIFY MODE: Chỉ sửa imageCount/imageInputs
            // ============================================
            else if (window._modifyConfig && chromeBody) {
                try {
                    var cfg = window._modifyConfig;

                    // LOG: Xem Chrome đang dùng model gì (kiểm tra TẤT CẢ fields liên quan)
                    var currentModel = 'UNKNOWN';
                    if (chromeBody.requests && chromeBody.requests[0]) {
                        var req = chromeBody.requests[0];
                        console.log('=== CHROME IMAGE REQUEST DEBUG ===');
                        console.log('[CHROME] generationModelId:', req.generationModelId || 'NOT_SET');
                        console.log('[CHROME] imageModelName:', req.imageModelName || 'NOT_SET');
                        console.log('[CHROME] imageGenerationModel:', req.imageGenerationModel || 'NOT_SET');
                        console.log('[CHROME] model:', req.model || 'NOT_SET');
                        console.log('[CHROME] aspectRatio:', req.aspectRatio || 'NOT_SET');
                        console.log('[CHROME] imageAspectRatio:', req.imageAspectRatio || 'NOT_SET');
                        console.log('[CHROME] outputOptions:', JSON.stringify(req.outputOptions || {}));
                        console.log('[CHROME] prompt (first 50 chars):', (req.prompt || '').substring(0, 50));
                        // Log toàn bộ keys để debug
                        console.log('[CHROME] ALL REQUEST KEYS:', Object.keys(req).join(', '));
                        console.log('=== END DEBUG ===');

                        // Detect current model
                        currentModel = req.imageModelName || req.generationModelId || req.imageGenerationModel || req.model || 'NOT_SET';
                    }

                    // Lưu model đang dùng để Python có thể đọc
                    window._chromeModel = currentModel;

                    if (cfg.imageCount && chromeBody.requests) {
                        chromeBody.requests = chromeBody.requests.slice(0, cfg.imageCount);
                    }

                    if (cfg.imageInputs && chromeBody.requests) {
                        chromeBody.requests.forEach(function(req) {
                            req.imageInputs = cfg.imageInputs;
                        });
                        console.log('[MODIFY] Added ' + cfg.imageInputs.length + ' reference images');
                    }

                    // FORCE MODEL: Đảm bảo dùng model chất lượng cao (Nano Banana Pro = GEM_PIX_2)
                    if (cfg.forceModel && chromeBody.requests) {
                        var goodModels = ['GEM_PIX_2', 'GEM_PIX', 'IMAGEN_4', 'IMAGEN_3_5'];
                        var needForce = !goodModels.includes(currentModel);

                        if (needForce || cfg.forceModel === 'always') {
                            chromeBody.requests.forEach(function(req) {
                                // Thử set cả 2 fields để đảm bảo hoạt động
                                req.imageModelName = cfg.forceModel === 'always' ? cfg.forceModelName : 'GEM_PIX_2';
                                if (req.generationModelId) {
                                    req.generationModelId = req.imageModelName;
                                }
                            });
                            console.log('[FORCE MODEL] Changed to:', cfg.forceModelName || 'GEM_PIX_2', '(was:', currentModel, ')');
                        } else {
                            console.log('[MODEL OK] Using Chrome model:', currentModel);
                        }
                    }

                    opts.body = JSON.stringify(chromeBody);
                    window._modifyConfig = null;
                } catch(e) {
                    console.log('[ERROR] Modify failed:', e);
                }
            }

            // FORWARD NGAY LẬP TỨC (trong 0.05s)
            try {
                console.log('[FORWARD] Sending with fresh reCAPTCHA...');
                var response = await orig.apply(this, [url, opts]);
                var cloned = response.clone();

                try {
                    var data = await cloned.json();
                    console.log('[RESPONSE] Status:', response.status);

                    // === 403 ERROR: Detect ngay và báo lỗi ===
                    if (response.status === 403 || (data.error && data.error.code === 403)) {
                        console.log('[RESPONSE] [x] 403 FORBIDDEN - IP blocked!');
                        var errorMsg = data.error ? data.error.message : 'Permission denied';
                        window._response = {error: {code: 403, message: errorMsg}};
                        window._responseError = 'Error 403: ' + errorMsg;
                        window._requestPending = false;
                        return response;
                    }

                    // === 400 ERROR: Policy violation (prompt bị cấm) ===
                    if (response.status === 400 || (data.error && data.error.code === 400)) {
                        console.log('[RESPONSE] [x] 400 POLICY VIOLATION - Prompt rejected!');
                        var errorMsg = data.error ? data.error.message : 'Policy violation';
                        window._response = {error: {code: 400, message: errorMsg}};
                        window._responseError = 'Error 400: ' + errorMsg;
                        window._requestPending = false;
                        return response;
                    }

                    // Check nếu có media MỚI với fifeUrl → trigger ngay
                    if (data.media && data.media.length > 0) {
                        var readyMedia = data.media.filter(function(m) {
                            return m.image && m.image.generatedImage && m.image.generatedImage.fifeUrl;
                        });

                        if (readyMedia.length > 0) {
                            console.log('[RESPONSE] [v] Got ' + readyMedia.length + ' images with fifeUrl!');
                            window._response = data;
                            window._requestPending = false;
                        } else {
                            console.log('[RESPONSE] Media exists but no fifeUrl yet, waiting...');
                        }
                    } else {
                        console.log('[RESPONSE] No media yet, waiting for poll...');
                    }
                } catch(e) {
                    window._response = {status: response.status, error: 'parse_failed'};
                    window._requestPending = false;
                }

                return response;
            } catch(e) {
                console.log('[ERROR] Request failed:', e);
                window._responseError = e.toString();
                window._requestPending = false;
                throw e;
            }
        }

        // ============================================
        // VIDEO GENERATION REQUESTS (I2V) - CUSTOM PAYLOAD INJECTION
        // ============================================
        if (urlStr.includes('aisandbox') && urlStr.includes('video:')) {
            console.log('[VIDEO] Request to:', urlStr);
            window._videoPending = true;
            window._videoResponse = null;
            window._videoError = null;

            // Capture headers
            if (opts && opts.headers) {
                var h = opts.headers;
                if (h['Authorization']) window._tk = h['Authorization'].replace('Bearer ', '');
                if (h['x-browser-validation']) window._xbv = h['x-browser-validation'];
            }

            // Parse Chrome's original body để lấy reCAPTCHA token FRESH
            var chromeVideoBody = null;
            var freshVideoRecaptcha = null;
            if (opts && opts.body) {
                try {
                    chromeVideoBody = JSON.parse(opts.body);
                    if (chromeVideoBody.clientContext) {
                        window._sid = chromeVideoBody.clientContext.sessionId;
                        window._pj = chromeVideoBody.clientContext.projectId;
                        freshVideoRecaptcha = chromeVideoBody.clientContext.recaptchaToken;
                        window._rct = freshVideoRecaptcha;
                    }
                } catch(e) {
                    console.log('[VIDEO] Parse Chrome body failed:', e);
                }
            }

            // ============================================
            // T2V → I2V CONVERSION MODE: Convert Text-to-Video thành Image-to-Video
            // Chrome gửi T2V request (batchAsyncGenerateVideoText) với model veo_3_1_t2v_fast_landscape_ultra_relaxed
            // Interceptor chỉ đổi: _t2v_ → _r2v_, GIỮ NGUYÊN phần còn lại
            // Result: veo_3_1_r2v_fast_landscape_ultra_relaxed (I2V endpoint)
            // ============================================
            if (window._t2vToI2vConfig && chromeVideoBody && urlStr.includes('batchAsyncGenerateVideoText')) {
                try {
                    var t2vConfig = window._t2vToI2vConfig;
                    console.log('[T2V→I2V] Converting Text-to-Video request to Image-to-Video...');
                    console.log('[T2V→I2V] Original URL:', urlStr);
                    console.log('[T2V→I2V] Chrome original payload:', JSON.stringify(chromeVideoBody, null, 2));

                    // 1. Đổi URL: T2V endpoint → I2V endpoint
                    var newUrl = urlStr.replace('batchAsyncGenerateVideoText', 'batchAsyncGenerateVideoReferenceImages');
                    console.log('[T2V→I2V] New URL:', newUrl);

                    // 2. GIỮ TẤT CẢ REQUESTS - Thêm referenceImages và fix model cho mỗi request
                    console.log('[T2V→I2V] Processing ' + (chromeVideoBody.requests ? chromeVideoBody.requests.length : 0) + ' requests');

                    if (chromeVideoBody.requests && chromeVideoBody.requests.length > 0) {
                        for (var i = 0; i < chromeVideoBody.requests.length; i++) {
                            var req = chromeVideoBody.requests[i];

                            // Thêm reference image với mediaId từ ảnh đã upload
                            req.referenceImages = [{
                                "imageUsageType": "IMAGE_USAGE_TYPE_ASSET",
                                "mediaId": t2vConfig.mediaId
                            }];

                            // GIỮ seed - I2V CẦN seed

                            // Đổi model từ T2V sang I2V
                            var currentModel = req.videoModelKey || 'veo_3_1_t2v_fast';

                            // STEP 1: Đổi _t2v_ → _r2v_
                            var newModel = currentModel.replace('_t2v_', '_r2v_');

                            // STEP 2: Thêm _landscape trước _ultra (I2V model format)
                            if (newModel.includes('_ultra') && !newModel.includes('_landscape')) {
                                newModel = newModel.replace('_ultra', '_landscape_ultra');
                            }

                            // Override nếu config có chỉ định model cụ thể
                            if (t2vConfig.videoModelKey) {
                                newModel = t2vConfig.videoModelKey;
                            }

                            req.videoModelKey = newModel;

                            if (i === 0) {
                                console.log('[T2V→I2V] Model converted:', currentModel, '→', newModel);
                                console.log('[T2V→I2V] MediaId:', t2vConfig.mediaId.substring(0, 50) + '...');
                            }
                        }
                        console.log('[T2V→I2V] All ' + chromeVideoBody.requests.length + ' requests processed');
                    }

                    // Update body với payload đã convert
                    opts.body = JSON.stringify(chromeVideoBody);
                    console.log('[T2V→I2V] Conversion complete, sending I2V request...');
                    console.log('[T2V→I2V] Final payload:', JSON.stringify(chromeVideoBody, null, 2));

                    // Clear config
                    window._t2vToI2vConfig = null;

                    // Gửi request tới URL mới
                    try {
                        var response = await orig.apply(this, [newUrl, opts]);
                        var cloned = response.clone();
                        try {
                            window._videoResponse = await cloned.json();
                            console.log('[T2V→I2V] Response status:', response.status);
                            if (window._videoResponse.operations) {
                                console.log('[T2V→I2V] Got operations:', window._videoResponse.operations.length);
                            }
                        } catch(e) {
                            window._videoResponse = {status: response.status, error: 'parse_failed'};
                        }
                        window._videoPending = false;
                        return response;
                    } catch(e) {
                        console.log('[T2V→I2V] Request failed:', e);
                        window._videoError = e.toString();
                        window._videoPending = false;
                        throw e;
                    }
                } catch(e) {
                    console.log('[T2V→I2V] Conversion failed:', e);
                    window._t2vToI2vConfig = null;
                }
            }

            // ============================================
            // MODIFY VIDEO MODE: Giữ payload Chrome, chỉ thêm referenceImages
            // (GIỐNG NHƯ TẠO ẢNH - dùng model/settings của Chrome)
            // ============================================
            if (window._modifyVideoConfig && chromeVideoBody && !window._customVideoPayload) {
                try {
                    var videoConfig = window._modifyVideoConfig;
                    console.log('[VIDEO-MODIFY] Modifying Chrome payload...');

                    // THÊM referenceImages (media_id) vào payload Chrome
                    if (videoConfig.referenceImages && videoConfig.referenceImages.length > 0) {
                        if (chromeVideoBody.requests) {
                            for (var i = 0; i < chromeVideoBody.requests.length; i++) {
                                chromeVideoBody.requests[i].referenceImages = videoConfig.referenceImages;
                            }
                            console.log('[VIDEO-MODIFY] Added referenceImages:', videoConfig.referenceImages[0].mediaId.substring(0, 50) + '...');
                        }
                    }

                    // Cập nhật body với payload đã modify
                    opts.body = JSON.stringify(chromeVideoBody);
                    console.log('[VIDEO-MODIFY] Payload modified, keeping Chrome model/settings');

                    // Clear để không dùng lại
                    window._modifyVideoConfig = null;
                } catch(e) {
                    console.log('[VIDEO-MODIFY] Failed:', e);
                }
            }
            // ============================================
            // CUSTOM VIDEO PAYLOAD MODE: Thay thế hoàn toàn body (backup)
            // ============================================
            else if (window._customVideoPayload && freshVideoRecaptcha) {
                try {
                    var customVideoBody = window._customVideoPayload;

                    // INJECT fresh reCAPTCHA token vào payload của chúng ta
                    if (customVideoBody.clientContext) {
                        customVideoBody.clientContext.recaptchaToken = freshVideoRecaptcha;
                        // Copy sessionId và projectId từ Chrome
                        if (chromeVideoBody && chromeVideoBody.clientContext) {
                            customVideoBody.clientContext.sessionId = chromeVideoBody.clientContext.sessionId;
                            customVideoBody.clientContext.projectId = chromeVideoBody.clientContext.projectId;
                        }
                    }

                    // Thay thế body
                    opts.body = JSON.stringify(customVideoBody);
                    console.log('[VIDEO-INJECT] Custom payload với fresh reCAPTCHA!');
                    if (customVideoBody.requests && customVideoBody.requests[0]) {
                        var refImages = customVideoBody.requests[0].referenceImages;
                        if (refImages && refImages.length > 0) {
                            console.log('[VIDEO-INJECT] referenceImages.mediaId:', refImages[0].mediaId ? refImages[0].mediaId.substring(0, 50) + '...' : 'NONE');
                        }
                    }

                    // Clear để không dùng lại
                    window._customVideoPayload = null;
                } catch(e) {
                    console.log('[VIDEO] Inject custom payload failed:', e);
                }
            }

            // FORWARD request
            try {
                console.log('[VIDEO] Sending request...');
                var response = await orig.apply(this, [url, opts]);
                var cloned = response.clone();
                try {
                    window._videoResponse = await cloned.json();
                    console.log('[VIDEO] Response status:', response.status);
                    if (window._videoResponse.operations) {
                        console.log('[VIDEO] Got operations:', window._videoResponse.operations.length);
                    }
                } catch(e) {
                    window._videoResponse = {status: response.status, error: 'parse_failed'};
                }
                window._videoPending = false;
                return response;
            } catch(e) {
                console.log('[VIDEO] Request failed:', e);
                window._videoError = e.toString();
                window._videoPending = false;
                throw e;
            }
        }

        // ============================================
        // CATCH getProject RESPONSE (có media sau khi generation xong)
        // Google API flow: batchGenerateImages → workflow ID → getProject poll → media ready
        // ============================================
        if (urlStr.includes('aisandbox') && urlStr.includes('getProject')) {
            try {
                var response = await orig.apply(this, [url, opts]);
                var cloned = response.clone();

                try {
                    var data = await cloned.json();
                    // Nếu đang đợi response VÀ có media
                    if (data.media && window._requestPending) {
                        var currentMediaCount = data.media.length;

                        // Đếm số media có fifeUrl (ảnh đã ready)
                        var readyCount = data.media.filter(function(m) {
                            return m.image && m.image.generatedImage && m.image.generatedImage.fifeUrl;
                        }).length;

                        // Lần poll đầu tiên: set baseline
                        if (window._lastMediaCount === null) {
                            window._lastMediaCount = readyCount;
                            console.log('[PROJECT] Baseline set:', readyCount, 'ready images');
                        } else {
                            console.log('[PROJECT] Media:', currentMediaCount, 'Ready:', readyCount, 'Baseline:', window._lastMediaCount);

                            // Chỉ accept khi số ảnh ready TĂNG LÊN so với baseline
                            if (readyCount > window._lastMediaCount) {
                                console.log('[PROJECT] [v] New image ready! (' + window._lastMediaCount + ' → ' + readyCount + ')');
                                window._response = data;
                                window._requestPending = false;
                            }
                        }
                    }
                } catch(e) {
                    // Ignore parse errors for getProject
                }

                return response;
            } catch(e) {
                throw e;
            }
        }

        return orig.apply(this, arguments);
    };
    console.log('[INTERCEPTOR] Ready - CUSTOM PAYLOAD INJECTION mode');
    return 'READY';
})();
'''

# JS để click dự án (ưu tiên dự án có sẵn, sau đó mới tạo mới)
JS_CLICK_NEW_PROJECT = '''
(function() {
    // 1. Ưu tiên: Click vào dự án có sẵn (thường là div với thumbnail)
    var projectCards = document.querySelectorAll('[role="listitem"], [data-project-id], .project-card');
    for (var card of projectCards) {
        if (card.offsetWidth > 50 && card.offsetHeight > 50) {
            card.click();
            console.log('[AUTO] Clicked existing project card');
            return 'CLICKED';
        }
    }

    // 2. Tìm div/button có chứa thumbnail ảnh (dự án có sẵn)
    var thumbs = document.querySelectorAll('img[src*="thumbnail"], img[src*="project"]');
    for (var img of thumbs) {
        var parent = img.closest('button') || img.closest('[role="button"]') || img.parentElement;
        if (parent) {
            parent.click();
            console.log('[AUTO] Clicked project thumbnail');
            return 'CLICKED';
        }
    }

    // 3. Fallback: Tìm button "Dự án mới" / "New project"
    var btns = document.querySelectorAll('button');
    for (var b of btns) {
        var text = b.textContent || '';
        if (text.includes('Dự án mới') || text.includes('New project')) {
            b.click();
            console.log('[AUTO] Clicked: Du an moi');
            return 'CLICKED';
        }
    }

    // 4. Tìm bất kỳ clickable element nào có text project
    var allElements = document.querySelectorAll('*');
    for (var el of allElements) {
        var text = (el.textContent || '').trim();
        if (el.offsetWidth > 100 && el.offsetHeight > 50) {
            // Có thể là project card
            var style = window.getComputedStyle(el);
            if (style.cursor === 'pointer' && text.length < 50) {
                el.click();
                console.log('[AUTO] Clicked clickable element:', text.substring(0, 30));
                return 'CLICKED';
            }
        }
    }

    return 'NOT_FOUND';
})();
'''

# JS để chọn "Tạo hình ảnh" từ dropdown
# Dùng cách giống T2V: click dropdown 2 lần với setTimeout
# Vietnamese: "Tạo hình ảnh" = 12 ký tự
JS_SELECT_IMAGE_MODE = '''
// Tìm bằng "hình ảnh" + length 12
var btn = document.querySelector('button[role="combobox"]');
btn.click();
setTimeout(() => {
    btn.click();
    setTimeout(() => {
        var spans = document.querySelectorAll('span');
        for (var el of spans) {
            var text = el.textContent.trim();
            // Vietnamese: "Tạo hình ảnh" = 12 chars
            // English: "Generate image" = 14 chars
            if ((text.includes('hình ảnh') && text.length === 12) ||
                (text.includes('image') && text.length === 14)) {
                console.log('[IMAGE] FOUND:', text);
                el.click();
                window._imageResult = 'CLICKED';
                return;
            }
        }
        console.log('[IMAGE] NOT FOUND');
        window._imageResult = 'NOT_FOUND';
    }, 300);
}, 100);
'''

# JS để chọn "Tạo video từ các thành phần" từ dropdown (cho I2V)
# Bước 1: Click dropdown 2 lần để mở menu đúng
JS_SELECT_VIDEO_MODE_STEP1 = '''
(function() {
    var dropdown = document.querySelector('button[role="combobox"]');
    if (!dropdown) {
        return 'NO_DROPDOWN';
    }
    dropdown.click();
    return 'CLICKED_FIRST';
})();
'''

# Bước 2: Click lần 2 để mở lại
JS_SELECT_VIDEO_MODE_STEP2 = '''
(function() {
    var dropdown = document.querySelector('button[role="combobox"]');
    if (!dropdown) {
        return 'NO_DROPDOWN';
    }
    dropdown.click();
    return 'CLICKED_SECOND';
})();
'''

# Bước 3: Tìm và click option (hỗ trợ cả tiếng Việt và Anh)
JS_SELECT_VIDEO_MODE_STEP3 = '''
(function() {
    var allSpans = document.querySelectorAll('span');
    for (var el of allSpans) {
        var text = (el.textContent || '').trim().toLowerCase();
        // Vietnamese: "Tạo video từ các thành phần"
        // English: "Create video from assets" / "Generate video from assets"
        if (text.includes('video') && (text.includes('thành phần') || text.includes('assets') || text.includes('elements'))) {
            el.click();
            console.log('[VIDEO] Clicked: ' + text);
            return 'CLICKED';
        }
    }
    return 'NOT_FOUND';
})();
'''

# Alias cho backward compatibility
JS_SELECT_VIDEO_MODE = JS_SELECT_VIDEO_MODE_STEP1

# ============================================================================
# JS để chọn "Từ văn bản sang video" (Text-to-Video = T2V mode)
# Flow mới: Chrome gửi T2V request → Interceptor convert sang I2V
# ============================================================================

# T2V Mode - JS ALL-IN-ONE với setTimeout (đợi dropdown mở)
# Vietnamese: "Từ văn bản sang video" = 22 ký tự
JS_SELECT_T2V_MODE_ALL = '''
// Tìm bằng video + length 22
var btn = document.querySelector('button[role="combobox"]');
btn.click();
setTimeout(() => {
    btn.click();
    setTimeout(() => {
        var spans = document.querySelectorAll('span');
        for (var el of spans) {
            var text = el.textContent.trim();
            if (text.includes('video') && text.length === 22) {
                console.log('FOUND:', text);
                el.click();
                window._t2vResult = 'CLICKED';
                return;
            }
        }
        console.log('NOT FOUND');
        window._t2vResult = 'NOT_FOUND';
    }, 300);
}, 100);
'''

# Legacy: Các bước riêng lẻ (backup)
JS_SELECT_T2V_MODE_STEP1 = '''
(function() {
    var dropdown = document.querySelector('button[role="combobox"]');
    if (!dropdown) { return 'NO_DROPDOWN'; }
    dropdown.click();
    return 'CLICKED_FIRST';
})();
'''

JS_SELECT_T2V_MODE_STEP2 = '''
(function() {
    var dropdown = document.querySelector('button[role="combobox"]');
    if (!dropdown) { return 'NO_DROPDOWN'; }
    dropdown.click();
    return 'CLICKED_SECOND';
})();
'''

JS_SELECT_T2V_MODE_STEP3 = '''
(function() {
    var spans = document.querySelectorAll('span');
    for (var el of spans) {
        var text = (el.textContent || '').trim();
        if (text.includes('video') && (text.length === 22 || text.length === 13)) {
            el.click();
            console.log('[T2V] Clicked: ' + text);
            return 'CLICKED';
        }
    }
    return 'NOT_FOUND';
})();
'''

# JS để chuyển model sang "Lower Priority" (tránh rate limit)
# Flow: Click Cài đặt → Click Mô hình dropdown → Select Lower Priority
JS_SWITCH_TO_LOWER_PRIORITY = '''
(function() {
    window._modelSwitchResult = 'PENDING';

    // Step 1: Click "Cài đặt"
    var buttons = document.querySelectorAll('button');
    for (var btn of buttons) {
        if (btn.textContent.includes('Cài đặt')) {
            btn.click();
            console.log('[MODEL] [1] [v] Clicked Cài đặt');

            setTimeout(function() {
                // Step 2: Click dropdown "Mô hình"
                var combos = document.querySelectorAll('button[role="combobox"]');
                for (var combo of combos) {
                    if (combo.textContent.includes('Mô hình')) {
                        combo.click();
                        console.log('[MODEL] [2] [v] Clicked Mô hình dropdown');

                        setTimeout(function() {
                            // Step 3: Select "Lower Priority"
                            var spans = document.querySelectorAll('span');
                            for (var span of spans) {
                                if (span.textContent.includes('Lower Priority')) {
                                    span.click();
                                    console.log('[MODEL] [3] [v] Selected Lower Priority');
                                    window._modelSwitchResult = 'SUCCESS';
                                    return;
                                }
                            }
                            console.log('[MODEL] [3] [FAIL] Lower Priority not found');
                            window._modelSwitchResult = 'NOT_FOUND_OPTION';
                        }, 300);
                        return;
                    }
                }
                console.log('[MODEL] [2] [FAIL] Mô hình dropdown not found');
                window._modelSwitchResult = 'NOT_FOUND_DROPDOWN';
            }, 500);
            return;
        }
    }
    console.log('[MODEL] [1] [FAIL] Cài đặt button not found');
    window._modelSwitchResult = 'NOT_FOUND_SETTINGS';
})();
'''


class DrissionFlowAPI:
    """
    Google Flow API client sử dụng DrissionPage.

    Sử dụng:
    ```python
    api = DrissionFlowAPI(
        profile_dir="./chrome_profiles/main",
        proxy_port=1080  # SOCKS5 proxy
    )

    # Setup Chrome và đợi user chọn project
    if api.setup():
        # Generate ảnh
        success, images, error = api.generate_image("a cat playing piano")
    ```
    """

    BASE_URL = "https://aisandbox-pa.googleapis.com"
    FLOW_URL = "https://labs.google/fx/vi/tools/flow"

    def __init__(
        self,
        profile_dir: str = "./chrome_profile",
        chrome_port: int = 0,  # 0 = auto-generate unique port (parallel-safe)
        verbose: bool = True,
        log_callback: Optional[Callable] = None,
        # Webshare proxy - dùng global proxy manager
        webshare_enabled: bool = True,  # BẬT Webshare proxy by default
        worker_id: int = 0,  # Worker ID cho proxy rotation (mỗi Chrome có proxy riêng)
        total_workers: int = 1,  # Tổng số workers (để chia màn hình)
        headless: bool = True,  # Chạy Chrome ẩn (default: ON)
        machine_id: int = 1,  # Máy số mấy (1-99) - tránh trùng session giữa các máy
        # Chrome portable - dùng Chrome đã đăng nhập sẵn
        chrome_portable: str = "",  # Đường dẫn Chrome portable (VD: C:\ve3\chrome.exe)
        skip_portable_detection: bool = False,  # Bỏ qua auto-detect Chrome Portable (dùng profile_dir)
        # Legacy params (ignored)
        proxy_port: int = 1080,
        use_proxy: bool = False,
    ):
        """
        Khởi tạo DrissionFlowAPI.

        Args:
            profile_dir: Thư mục Chrome profile (chỉ dùng khi không có chrome_portable)
            chrome_port: Port cho Chrome debugging (0 = auto-generate unique port)
            verbose: In log chi tiết
            log_callback: Callback để log (msg, level)
            webshare_enabled: Dùng Webshare proxy pool (default True)
            worker_id: Worker ID cho proxy rotation (mỗi Chrome có proxy riêng)
            total_workers: Tổng số workers (để chia màn hình: 1=full, 2=chia đôi, ...)
            headless: Chạy Chrome ẩn không hiện cửa sổ (default True)
            machine_id: Máy số mấy (1-99), mỗi máy cách nhau 30000 session để tránh trùng
            chrome_portable: Đường dẫn Chrome portable đã đăng nhập sẵn (ưu tiên cao nhất)
        """
        self.profile_dir = Path(profile_dir)
        self.worker_id = worker_id  # Lưu worker_id để dùng cho proxy rotation
        self._total_workers = total_workers  # Tổng số workers để chia màn hình
        self._headless = headless  # Lưu setting headless
        self._machine_id = machine_id  # Máy số mấy (1-99)
        self._chrome_portable = chrome_portable  # Chrome portable path
        self._skip_portable_detection = skip_portable_detection  # Bỏ qua auto-detect Chrome Portable
        # Unique port cho mỗi worker (không random để tránh conflict)
        # Worker 0 → 9222, Worker 1 → 9223, ...
        # CHROME_PORT_OFFSET từ environment (cho parallel mode - tránh conflict)
        port_offset = int(os.environ.get('CHROME_PORT_OFFSET', '0'))
        if chrome_port == 0:
            self.chrome_port = 9222 + worker_id + port_offset
        else:
            self.chrome_port = chrome_port + port_offset
        self.verbose = verbose
        self.log_callback = log_callback

        # Chrome/DrissionPage
        self.driver: Optional[ChromiumPage] = None

        # Webshare Proxy - dùng global manager
        self._webshare_proxy = None
        self._use_webshare = webshare_enabled
        self._proxy_bridge = None  # Local proxy bridge

        # === TÍNH SESSION ID DỰA TRÊN WORKER VÀ SỐ LUỒNG ===
        # Đọc số luồng từ settings để chia dải proxy đều
        num_workers = 2  # Default
        try:
            import yaml
            settings_path = Path(__file__).parent.parent / "config" / "settings.yaml"
            if settings_path.exists():
                with open(settings_path, 'r', encoding='utf-8') as f:
                    cfg = yaml.safe_load(f) or {}
                num_workers = max(1, cfg.get('parallel_voices', 2))
        except:
            pass

        # Mỗi worker có dải proxy riêng:
        # - 2 workers: Worker 0 = 1-15000, Worker 1 = 15001-30000
        # - 3 workers: Worker 0 = 1-10000, Worker 1 = 10001-20000, Worker 2 = 20001-30000
        sessions_per_worker = 30000 // num_workers
        base_offset = (self._machine_id - 1) * 30000  # Offset theo máy
        worker_offset = self.worker_id * sessions_per_worker  # Offset theo worker
        range_start = base_offset + worker_offset + 1
        range_end = base_offset + worker_offset + sessions_per_worker
        self._sessions_per_worker = sessions_per_worker  # Lưu để tăng đúng trong dải
        self._session_range_start = range_start
        self._session_range_end = range_end

        # === LOAD LAST SESSION ID FROM FILE ===
        # Tiếp tục từ session cuối để không lặp lại các session đã dùng
        last_session = _get_last_session_id(self._machine_id, self.worker_id)
        if last_session and range_start <= last_session < range_end:
            # Tiếp tục từ session cuối + 1
            self._rotating_session_id = last_session + 1
            # Nếu đã hết dải, quay lại đầu
            if self._rotating_session_id > range_end:
                self._rotating_session_id = range_start
                self.log(f"[Session] [RECYCLE] Đã hết dải, quay lại từ đầu: {range_start}")
            else:
                self.log(f"[Session] [>>] Tiếp tục từ session {self._rotating_session_id} (last={last_session})")
        else:
            # Bắt đầu từ đầu dải
            self._rotating_session_id = range_start
            self.log(f"[Session] [NEW] Bắt đầu từ session {range_start}")

        self.log(f"[Session] Machine {self._machine_id}, Worker {self.worker_id}: session range {range_start}-{range_end}")

        self._bridge_port = None   # Bridge port for API calls
        self._is_rotating_mode = False  # True = Rotating Endpoint (auto IP change)
        if webshare_enabled and WEBSHARE_AVAILABLE:
            try:
                from webshare_proxy import get_proxy_manager, WebshareProxy
                manager = get_proxy_manager()

                # Check rotating endpoint mode first
                if manager.is_rotating_mode():
                    self._webshare_proxy = WebshareProxy()
                    self._is_rotating_mode = True
                    rotating = manager.rotating_endpoint
                    self.log(f"[v] Webshare: ROTATING ENDPOINT mode")
                    self.log(f"  → {rotating.host}:{rotating.port}")
                elif manager.proxies:
                    self._webshare_proxy = WebshareProxy()  # Wrapper cho manager
                    # Lấy proxy cho worker này (không dùng current_proxy global)
                    worker_proxy = manager.get_proxy_for_worker(self.worker_id)
                    if worker_proxy:
                        self.log(f"[v] Webshare: {len(manager.proxies)} proxies, worker {self.worker_id}: {worker_proxy.endpoint}")
                    else:
                        self.log(f"[v] Webshare: {len(manager.proxies)} proxies loaded")
                else:
                    self._use_webshare = False
                    self.log("[WARN] Webshare: No proxies loaded", "WARN")
            except Exception as e:
                self._use_webshare = False
                self.log(f"[WARN] Webshare init error: {e}", "WARN")

        # Captured tokens
        self.bearer_token: Optional[str] = None
        self.project_id: Optional[str] = None
        self.session_id: Optional[str] = None
        self.recaptcha_token: Optional[str] = None
        self.x_browser_validation: Optional[str] = None
        self.captured_url: Optional[str] = None
        self.captured_payload: Optional[str] = None

        # State
        self._ready = False

        # Model fallback: khi quota exceeded (429), chuyển từ GEM_PIX_2 (Pro) sang GEM_PIX
        self._use_fallback_model = False  # True = dùng nano banana (GEM_PIX) thay vì pro (GEM_PIX_2)

        # IPv6 rotation: Đọc từ settings.yaml
        self._consecutive_403 = 0
        self._ipv6_activated = False  # True = đã bật IPv6 proxy
        self._ipv6_rotator = None  # IPv6Rotator instance

        # Đọc max_403_before_rotate từ settings
        try:
            import yaml
            settings_path = Path(__file__).parent.parent / "config" / "settings.yaml"
            if settings_path.exists():
                with open(settings_path, 'r', encoding='utf-8') as f:
                    cfg = yaml.safe_load(f) or {}
                ipv6_cfg = cfg.get('ipv6_rotation', {})
                self._max_403_before_ipv6 = ipv6_cfg.get('max_403_before_rotate', 3)
            else:
                self._max_403_before_ipv6 = 3
        except:
            self._max_403_before_ipv6 = 3

        # Mode tracking: chỉ chọn mode/model lần đầu khi mới mở Chrome
        # Sau F5 refresh thì trang vẫn giữ mode/model đã chọn, không cần chọn lại
        self._t2v_mode_selected = False  # True = đã chọn T2V mode + Lower Priority model
        self._image_mode_selected = False  # True = đã chọn Image mode

    def log(self, msg: str, level: str = "INFO"):
        """Log message - chỉ dùng 1 trong 2: callback hoặc print."""
        if self.log_callback:
            # Nếu có callback, để parent xử lý log (tránh duplicate)
            self.log_callback(msg, level)
        elif self.verbose:
            # Fallback: print trực tiếp nếu không có callback
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] [{level}] {msg}")

    def reset_to_pro_model(self):
        """Reset về model pro (GEM_PIX_2) - gọi khi bắt đầu project mới."""
        if self._use_fallback_model:
            self._use_fallback_model = False
            self.log("[MODEL] ↩️ Reset về Nano Banana Pro (GEM_PIX_2)")

    def switch_to_fallback_model(self):
        """Chuyển sang model fallback (GEM_PIX) khi quota exceeded."""
        if not self._use_fallback_model:
            self._use_fallback_model = True
            self.log("[MODEL] [SYNC] Chuyển sang Nano Banana (GEM_PIX) do quota exceeded")

    def get_current_model(self) -> str:
        """Trả về model đang dùng."""
        return "GEM_PIX" if self._use_fallback_model else "GEM_PIX_2"

    def _activate_ipv6(self) -> bool:
        """
        Bật IPv6 mode khi bị 403 đủ lần.
        Restart Chrome với IPv6 proxy.

        Returns:
            True nếu activate thành công
        """
        if self._ipv6_activated:
            self.log("[IPv6] Đã activated trước đó, rotate IP...")
            try:
                from modules.ipv6_rotator import get_ipv6_rotator
                rotator = get_ipv6_rotator()
                if rotator:
                    new_ip = rotator.rotate()
                    if new_ip:
                        self.log(f"[IPv6] [v] Rotated to: {new_ip}")
                        return True
            except Exception as e:
                self.log(f"[IPv6] Rotate error: {e}", "WARN")
            return False

        self.log("[NET] [IPv6] ACTIVATING IPv6 MODE...")

        try:
            from modules.ipv6_rotator import get_ipv6_rotator
            rotator = get_ipv6_rotator()

            if not rotator or not rotator.ipv6_list:
                self.log("[IPv6] [x] Không có IPv6 list!", "ERROR")
                return False

            # Tìm IPv6 hoạt động
            working_ipv6 = rotator.init_with_working_ipv6()
            if not working_ipv6:
                self.log("[IPv6] [x] Không tìm được IPv6 hoạt động!", "ERROR")
                return False

            # Set flag activated
            self._ipv6_activated = True
            self.log(f"[IPv6] [v] Activated với IP: {working_ipv6}")
            self.log("[IPv6] → Restart Chrome với IPv6 proxy...")

            return True

        except Exception as e:
            self.log(f"[IPv6] Activate error: {e}", "ERROR")
            return False

    def _auto_setup_project(self, timeout: int = 60) -> bool:
        """
        Tự động setup project:
        1. Click "Dự án mới" (New project)
        2. Chọn "Tạo hình ảnh" (Generate image)
        3. Đợi vào project

        Args:
            timeout: Timeout tổng (giây)

        Returns:
            True nếu thành công
        """
        self.log("→ Đang tự động tạo dự án mới...")

        # 0. Đợi page load xong trước (tránh ContextLostError)
        self.log("   Đợi page load...")
        if not self._wait_for_page_ready(timeout=30):
            self.log("[WARN] Page chưa sẵn sàng", "WARN")

        # 1. Đợi trang load và tìm button "Dự án mới"
        # Nếu không tìm thấy → F5 refresh và thử lại (mỗi 10s)
        MAX_REFRESH = 6  # Tối đa 6 lần refresh (60s)
        clicked_success = False
        for refresh_count in range(MAX_REFRESH):
            # Thử tìm button trong 10s
            for i in range(10):
                # Check URL trước - có thể đã vào project rồi
                try:
                    current_url = self.driver.url
                    if "/project/" in current_url:
                        self.log("[v] Đã vào project (URL check)")
                        return True
                except:
                    pass

                try:
                    result = self.driver.run_js(JS_CLICK_NEW_PROJECT)
                    if result == 'CLICKED':
                        self.log("[v] Clicked 'Dự án mới'")
                        clicked_success = True
                        time.sleep(2)
                        # Check URL ngay sau click
                        try:
                            if "/project/" in self.driver.url:
                                self.log("[v] Đã vào project!")
                                return True
                        except:
                            pass
                        break
                except Exception as e:
                    if "ContextLost" in str(type(e).__name__) or "refresh" in str(e).lower():
                        self.log(f"   Page đang refresh, đợi...")
                        time.sleep(2)
                        # Page refresh có thể là do đang navigate vào project
                        try:
                            if "/project/" in self.driver.url:
                                self.log("[v] Đã vào project (sau refresh)!")
                                return True
                        except:
                            pass
                        continue
                    raise
                time.sleep(1)
                if i == 4:
                    self.log("  ... đợi button 'Dự án mới' xuất hiện...")
            else:
                # Không tìm thấy button → check URL trước khi F5
                try:
                    if "/project/" in self.driver.url:
                        self.log("[v] Đã vào project!")
                        return True
                except:
                    pass
                # F5 refresh
                self.log(f"[WARN] Không tìm thấy button - F5 refresh (lần {refresh_count + 1}/{MAX_REFRESH})...")
                try:
                    self.driver.refresh()
                    time.sleep(3)  # Đợi page load sau refresh
                    if not self._wait_for_page_ready(timeout=15):
                        self.log("[WARN] Page chưa sẵn sàng sau refresh", "WARN")
                except Exception as e:
                    self.log(f"  → F5 error: {e}", "WARN")
                continue

            # Đã click thành công, check URL một lần nữa
            if clicked_success:
                break
        else:
            # Check URL lần cuối
            try:
                if "/project/" in self.driver.url:
                    self.log("[v] Đã vào project!")
                    return True
            except:
                pass
            self.log(f"[x] Không tìm thấy button 'Dự án mới' sau {MAX_REFRESH} lần refresh", "ERROR")
            return False

        # 2. Chọn "Tạo hình ảnh" từ dropdown
        time.sleep(1)
        for i in range(10):
            result = self.driver.run_js(JS_SELECT_IMAGE_MODE)
            if result == 'CLICKED':
                self.log("[v] Chọn 'Tạo hình ảnh'")
                self._image_mode_selected = True  # Đánh dấu đã chọn mode
                time.sleep(2)
                break
            time.sleep(0.5)
        else:
            self.log("[WARN] Không tìm thấy dropdown - có thể đã ở mode đúng", "WARN")

        # 3. Đợi vào project
        self.log("→ Đợi vào project...")
        for i in range(timeout):
            current_url = self.driver.url
            if "/project/" in current_url:
                self.log(f"[v] Đã vào dự án!")
                return True
            time.sleep(1)
            if i % 10 == 9:
                self.log(f"  ... đợi {i+1}s")

        self.log("[x] Timeout - chưa vào được dự án", "ERROR")
        return False

    def _warm_up_session(self, dummy_prompt: str = "a simple test image") -> bool:
        """
        Warm up session bằng cách tạo 1 ảnh thật trong Chrome.
        Điều này "activate" session và làm cho tokens hợp lệ.

        Args:
            dummy_prompt: Prompt đơn giản để warm up

        Returns:
            True nếu thành công
        """
        self.log("=" * 50)
        self.log("  WARM UP SESSION")
        self.log("=" * 50)
        self.log("→ Tạo 1 ảnh trong Chrome để activate session...")
        self.log(f"  Prompt: {dummy_prompt[:50]}...")

        # Tìm textarea và gửi prompt
        textarea = self._find_textarea()
        if not textarea:
            self.log("[x] Không tìm thấy textarea", "ERROR")
            return False

        textarea.clear()
        time.sleep(0.2)
        textarea.input(dummy_prompt)
        time.sleep(0.3)
        textarea.input('\n')
        self.log("[v] Đã gửi prompt, đợi Chrome tạo ảnh...")

        # Đợi ảnh được tạo - kiểm tra bằng cách tìm img elements mới
        # hoặc đợi loading indicator biến mất
        self.log("→ Đợi ảnh được tạo (có thể mất 10-30s)...")

        for i in range(60):  # Đợi tối đa 60s
            time.sleep(2)

            # Kiểm tra có ảnh được tạo không
            # Tìm elements chứa ảnh generated
            check_result = self.driver.run_js("""
                // Tìm các img elements có src chứa base64 hoặc googleusercontent
                var imgs = document.querySelectorAll('img');
                var found = 0;
                for (var img of imgs) {
                    var src = img.src || '';
                    if (src.includes('data:image') || src.includes('googleusercontent') || src.includes('ggpht')) {
                        // Kiểm tra kích thước - ảnh generated thường lớn
                        if (img.naturalWidth > 200 || img.width > 200) {
                            found++;
                        }
                    }
                }
                return {found: found, loading: !!document.querySelector('[data-loading="true"]')};
            """)

            if check_result and check_result.get('found', 0) > 0:
                self.log(f"[v] Phát hiện {check_result['found']} ảnh!")
                time.sleep(2)  # Đợi thêm để ổn định
                self.log("[v] Session đã được warm up!")
                return True

            if i % 5 == 4:
                self.log(f"  ... đợi {(i+1)*2}s")

        self.log("[WARN] Không phát hiện được ảnh, tiếp tục...", "WARN")
        return True  # Vẫn return True để tiếp tục

    def _is_logged_out(self) -> bool:
        """
        Kiểm tra xem Chrome có bị logout khỏi Google không.
        Chỉ check URL redirect về trang login Google.
        """
        try:
            if not self.driver:
                return False

            current_url = self.driver.url or ""

            # Check URL redirect về trang login Google
            logout_url_indicators = [
                "accounts.google.com/signin",
                "accounts.google.com/v3/signin",
                "accounts.google.com/ServiceLogin",
                "accounts.google.com/AccountChooser",
            ]
            for indicator in logout_url_indicators:
                if indicator in current_url:
                    self.log(f"[LOGOUT] Detected via URL: {indicator}")
                    return True

        except Exception as e:
            pass
        return False

    def _auto_login_google(self, max_retries: int = 3) -> bool:
        """
        Tự động đăng nhập Google khi bị logout.
        Gọi hàm login từ google_login.py. Tự động retry khi fail.

        Args:
            max_retries: Số lần retry tối đa (default 3)

        Returns:
            True nếu login thành công
        """
        self.log("=" * 50)
        self.log("[WARN] PHÁT HIỆN BỊ LOGOUT - TỰ ĐỘNG ĐĂNG NHẬP LẠI")
        self.log("=" * 50)

        try:
            # Import hàm login từ google_login.py
            import sys
            tool_dir = Path(__file__).parent.parent
            if str(tool_dir) not in sys.path:
                sys.path.insert(0, str(tool_dir))

            from google_login import detect_machine_code, get_account_info, login_google_chrome

            # 1. Detect mã máy
            machine_code = detect_machine_code()
            if not machine_code:
                self.log("[x] Không detect được mã máy", "ERROR")
                return False

            self.log(f"Mã máy: {machine_code}")

            # 2. Lấy thông tin tài khoản từ Google Sheet (đã có retry bên trong)
            self.log("Đọc thông tin tài khoản từ Google Sheet...")
            account_info = get_account_info(machine_code)
            if not account_info:
                self.log("[x] Không lấy được thông tin tài khoản", "ERROR")
                return False

            self.log(f"Tài khoản: {account_info['id']}")

            # 3. Đóng Chrome hiện tại
            self.log("Đóng Chrome để login lại...")
            self._kill_chrome()
            self.close()
            time.sleep(2)

            # 4. Chạy login với retry
            # QUAN TRỌNG: Truyền chrome_portable, profile_dir và worker_id
            # Khi có 2 Chrome song song (Chrome 1 tạo ảnh, Chrome 2 tạo video),
            # cần login đúng Chrome bị logout, không phải Chrome kia
            for attempt in range(max_retries):
                if attempt > 0:
                    self.log(f"[SYNC] Retry login ({attempt + 1}/{max_retries})...")
                    time.sleep(3)

                self.log("Bắt đầu đăng nhập Google...")
                self.log(f"  Chrome: {self._chrome_portable or 'default'}")
                self.log(f"  Profile: {self.profile_dir}")
                self.log(f"  Worker ID: {self.worker_id}")

                try:
                    success = login_google_chrome(
                        account_info,
                        chrome_portable=self._chrome_portable,
                        profile_dir=str(self.profile_dir) if self.profile_dir else None,
                        worker_id=self.worker_id
                    )

                    if success:
                        self.log("[v] Đăng nhập thành công!")
                        # Đóng Chrome login để setup lại từ đầu
                        time.sleep(2)
                        return True
                    else:
                        self.log(f"[x] Đăng nhập thất bại (attempt {attempt + 1}/{max_retries})", "WARN")
                        # Kill Chrome trước khi retry
                        self._kill_chrome()
                        time.sleep(2)

                except Exception as login_err:
                    self.log(f"[x] Login error (attempt {attempt + 1}): {login_err}", "WARN")
                    self._kill_chrome()
                    time.sleep(2)

            self.log("[x] Đăng nhập thất bại sau nhiều lần thử", "ERROR")
            return False

        except ImportError as e:
            self.log(f"[x] Không import được google_login: {e}", "ERROR")
            return False
        except Exception as e:
            self.log(f"[x] Lỗi auto-login: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            return False

    def _kill_chrome(self):
        """
        Close Chrome của tool này (không kill tất cả Chrome).
        Chỉ đóng driver và proxy bridge.
        """
        try:
            # Chỉ close driver của tool này
            if self.driver:
                try:
                    self.driver.quit()
                except:
                    pass
                self.driver = None

            # Stop proxy bridge
            if hasattr(self, '_proxy_bridge') and self._proxy_bridge:
                try:
                    from proxy_bridge import stop_proxy_bridge
                    stop_proxy_bridge(self._proxy_bridge)
                except:
                    pass
                self._proxy_bridge = None

            self.log("[v] Closed Chrome và proxy bridge của tool")
            time.sleep(1)
        except Exception as e:
            pass

    def clear_cookies_only(self) -> bool:
        """
        Chỉ xóa cookies và cache, GIỮA LẠI Login Data.
        Dùng khi restart sau mỗi ảnh để reset reCAPTCHA mà không mất login.

        Returns:
            True nếu xóa thành công
        """
        import shutil

        try:
            self.log("[DEL] Clearing cookies & cache (giữ login)...")

            # Đóng Chrome trước
            self._kill_chrome()
            time.sleep(1)

            profile_path = self.profile_dir
            if not profile_path or not profile_path.exists():
                self.log("[WARN] Profile directory not found", "WARN")
                return False

            # Chỉ xóa cookies, cache - KHÔNG xóa Login Data
            items_to_clear = [
                "Cookies", "Cookies-journal",
                "Cache", "Code Cache", "GPUCache",
                "Session Storage", "Local Storage",
                "IndexedDB", "Service Worker",
                # Default/ subfolder
                "Default/Cookies", "Default/Cookies-journal",
                "Default/Cache", "Default/Code Cache", "Default/GPUCache",
                "Default/Session Storage", "Default/Local Storage",
                "Default/IndexedDB", "Default/Service Worker",
            ]

            cleared = 0
            for item in items_to_clear:
                target = profile_path / item
                if target.exists():
                    try:
                        if target.is_dir():
                            shutil.rmtree(target)
                        else:
                            target.unlink()
                        cleared += 1
                    except:
                        pass

            self.log(f"[v] Cleared {cleared} items (Login Data kept)")
            return True

        except Exception as e:
            self.log(f"[WARN] Clear cookies error: {e}", "WARN")
            return False

    def clear_chrome_data(self) -> bool:
        """
        Xóa dữ liệu Chrome bằng UI (giống Ctrl+H → Delete browsing data).
        Gọi khi gặp 403 liên tiếp nhiều lần.

        Returns:
            True nếu xóa thành công
        """
        try:
            self.log("[DEL] Clearing Chrome data via UI...")

            if not self.driver:
                self.log("[WARN] Chrome chưa mở, không thể clear data", "WARN")
                return False

            # Mở trang Clear browsing data
            self.driver.get("chrome://settings/clearBrowserData")
            time.sleep(2)

            # JS để click "All time" và "Delete from this device"
            JS_CLEAR_DATA = """
            (function() {
                // Tìm trong shadow DOM của settings page
                function queryShadow(root, selector) {
                    if (!root) return null;
                    let el = root.querySelector(selector);
                    if (el) return el;

                    // Tìm trong shadow roots
                    const elements = root.querySelectorAll('*');
                    for (let i = 0; i < elements.length; i++) {
                        if (elements[i].shadowRoot) {
                            el = queryShadow(elements[i].shadowRoot, selector);
                            if (el) return el;
                        }
                    }
                    return null;
                }

                function findInShadow(selector) {
                    return queryShadow(document, selector);
                }

                // Click "All time" tab
                let allTimeTab = findInShadow('[data-value="4"]');  // 4 = All time
                if (!allTimeTab) {
                    // Thử tìm bằng text
                    const tabs = document.querySelectorAll('cr-tabs');
                    for (let tab of tabs) {
                        if (tab.shadowRoot) {
                            const items = tab.shadowRoot.querySelectorAll('.tab');
                            for (let item of items) {
                                if (item.textContent.includes('All time')) {
                                    item.click();
                                    break;
                                }
                            }
                        }
                    }
                }
                if (allTimeTab) allTimeTab.click();

                return 'SETUP';
            })();
            """

            JS_CLICK_DELETE = """
            (function() {
                function queryShadow(root, selector) {
                    if (!root) return null;
                    let el = root.querySelector(selector);
                    if (el) return el;
                    const elements = root.querySelectorAll('*');
                    for (let i = 0; i < elements.length; i++) {
                        if (elements[i].shadowRoot) {
                            el = queryShadow(elements[i].shadowRoot, selector);
                            if (el) return el;
                        }
                    }
                    return null;
                }

                // Tìm button "Delete from this device" hoặc "Clear data"
                let deleteBtn = queryShadow(document, '#clearBrowsingDataConfirm');
                if (!deleteBtn) {
                    deleteBtn = queryShadow(document, '[id*="clearBrowsingData"]');
                }
                if (!deleteBtn) {
                    // Tìm bằng text
                    const buttons = document.querySelectorAll('cr-button');
                    for (let btn of buttons) {
                        if (btn.textContent.includes('Delete') || btn.textContent.includes('Clear')) {
                            deleteBtn = btn;
                            break;
                        }
                    }
                }

                if (deleteBtn) {
                    deleteBtn.click();
                    return 'CLICKED';
                }
                return 'NOT_FOUND';
            })();
            """

            # Setup - click All time
            try:
                self.driver.run_js(JS_CLEAR_DATA)
                time.sleep(1)
            except Exception as e:
                self.log(f"  JS setup error: {e}")

            # Click Delete button
            for attempt in range(5):
                try:
                    result = self.driver.run_js(JS_CLICK_DELETE)
                    if result == 'CLICKED':
                        self.log("[v] Clicked 'Delete from this device'")
                        time.sleep(3)  # Đợi xóa xong

                        # Reset flags
                        self._t2v_mode_selected = False
                        self._image_mode_selected = False
                        self.log("[v] Chrome data cleared!")
                        self.log("[WARN] Cần login lại Google!")
                        return True
                    else:
                        self.log(f"  Attempt {attempt+1}: {result}")
                        time.sleep(1)
                except Exception as e:
                    self.log(f"  Attempt {attempt+1} error: {e}")
                    time.sleep(1)

            # Fallback: Thử dùng keyboard shortcut
            self.log("  Trying keyboard shortcut...")
            try:
                from DrissionPage.common import Keys
                # Ctrl+Shift+Delete để mở clear data dialog
                self.driver.actions.key_down(Keys.CTRL).key_down(Keys.SHIFT).send_keys(Keys.DELETE).key_up(Keys.SHIFT).key_up(Keys.CTRL)
                time.sleep(2)
                # Enter để confirm
                self.driver.actions.send_keys(Keys.ENTER)
                time.sleep(3)
                self.log("[v] Chrome data cleared (keyboard)!")
                return True
            except Exception as e:
                self.log(f"  Keyboard shortcut failed: {e}")

            self.log("[WARN] Could not clear Chrome data via UI", "WARN")
            return False

        except Exception as e:
            self.log(f"[x] Clear Chrome data failed: {e}", "ERROR")
            return False

    def _force_kill_all_chrome(self):
        """
        Kill TẤT CẢ Chrome processes một cách mạnh mẽ.
        Dùng khi cần xóa sạch data.
        """
        import subprocess
        import platform

        self.log("  [KILL] Force killing ALL Chrome processes...")

        try:
            # 1. Đóng driver trước
            if self.driver:
                try:
                    self.driver.quit()
                except:
                    pass
                self.driver = None

            # 2. Stop proxy bridge
            if hasattr(self, '_proxy_bridge') and self._proxy_bridge:
                try:
                    from proxy_bridge import stop_proxy_bridge
                    stop_proxy_bridge(self._proxy_bridge)
                except:
                    pass
                self._proxy_bridge = None

            time.sleep(1)

            # 3. Force kill tất cả Chrome processes bằng system command
            if platform.system() == 'Windows':
                # Windows: taskkill /F /IM chrome.exe
                for _ in range(3):  # Retry 3 lần
                    subprocess.run(
                        ['taskkill', '/F', '/IM', 'chrome.exe'],
                        capture_output=True, timeout=10
                    )
                    time.sleep(1)
            else:
                # Linux/Mac: killall hoặc pkill
                for _ in range(3):
                    subprocess.run(['pkill', '-9', '-f', 'chrome'], capture_output=True, timeout=10)
                    subprocess.run(['pkill', '-9', '-f', 'chromium'], capture_output=True, timeout=10)
                    time.sleep(1)

            self.log("  [v] Killed all Chrome processes")
            time.sleep(2)  # Đợi processes thực sự tắt

        except Exception as e:
            self.log(f"  [WARN] Kill Chrome error (không sao): {e}")

    def _delete_with_retry(self, path: Path, max_retries: int = 3) -> bool:
        """
        Xóa file/folder với retry và force.
        """
        import shutil

        if not path.exists():
            return True

        for attempt in range(max_retries):
            try:
                if path.is_file():
                    path.unlink()
                else:
                    shutil.rmtree(str(path), ignore_errors=True)

                # Verify deletion
                if not path.exists():
                    return True

            except Exception as e:
                self.log(f"    Retry {attempt + 1}/{max_retries}: {e}")
                time.sleep(1)

        # Final attempt: xóa từng file bên trong
        if path.is_dir():
            try:
                for item in path.rglob('*'):
                    try:
                        if item.is_file():
                            item.unlink()
                    except:
                        pass
                shutil.rmtree(str(path), ignore_errors=True)
            except:
                pass

        return not path.exists()

    def reset_chrome_profile(self) -> bool:
        """
        Xóa dữ liệu Chrome profile để Chrome trắng như mới.

        Đơn giản: Tắt Chrome → Xóa files trong Data/profile/Default/
        File nào không xóa được thì bỏ qua (không sao).

        Returns:
            True nếu xóa thành công
        """
        import shutil

        self.log("[DEL] RESET Chrome Profile...")

        try:
            # 1. Tắt Chrome
            self._force_kill_all_chrome()
            time.sleep(2)

            # 2. Tìm thư mục Default
            default_dir = None

            if hasattr(self, '_chrome_portable') and self._chrome_portable:
                chrome_exe = Path(os.path.expandvars(self._chrome_portable))
                default_dir = chrome_exe.parent / "Data" / "profile" / "Default"
            elif self.profile_dir:
                # Chrome thường: profile_dir thường là Default folder
                if self.profile_dir.name == "Default":
                    default_dir = self.profile_dir
                else:
                    default_dir = self.profile_dir / "Default"

            # 3. Xóa các file trong Default (bỏ qua file không xóa được)
            if default_dir and default_dir.exists():
                self.log(f"  [DIR] Xóa files trong: {default_dir}")

                deleted_count = 0
                skipped_count = 0

                for item in default_dir.iterdir():
                    try:
                        if item.is_file():
                            item.unlink()
                            deleted_count += 1
                        elif item.is_dir():
                            shutil.rmtree(str(item), ignore_errors=True)
                            if not item.exists():
                                deleted_count += 1
                            else:
                                skipped_count += 1
                    except:
                        skipped_count += 1
                        pass  # Bỏ qua file không xóa được

                self.log(f"  [v] Đã xóa {deleted_count} items" + (f", bỏ qua {skipped_count}" if skipped_count else ""))
            else:
                self.log(f"  [WARN] Không tìm thấy thư mục Default")

            # 4. Reset flags
            self._ready = False
            self._t2v_mode_selected = False
            self._image_mode_selected = False
            self._consecutive_403 = 0
            self._cleared_data_for_403 = False
            self.driver = None

            self.log("[v] Chrome TRẮNG - cần đăng nhập lại!")
            return True

        except Exception as e:
            self.log(f"[x] Reset Chrome profile failed: {e}", "ERROR")
            return False

    def full_reset_and_login(self, project_url: str = None) -> bool:
        """
        Reset Chrome triệt để và tự động login lại.
        Dùng khi gặp 403 liên tục không giải quyết được.

        Flow:
        1. reset_chrome_profile() - xóa sạch profile
        2. Khởi động Chrome mới
        3. Auto login Google (nếu có chrome_portable)
        4. Navigate đến project

        Returns:
            True nếu reset và login thành công
        """
        self.log("[SYNC] FULL RESET: Xóa profile + Login lại...")

        # 1. Reset profile
        if not self.reset_chrome_profile():
            self.log("[x] Không reset được profile", "ERROR")
            return False

        time.sleep(2)

        # 2. Khởi động Chrome mới và setup
        try:
            # Nếu có chrome_portable, sẽ tự động copy cookies
            if hasattr(self, '_chrome_portable') and self._chrome_portable:
                self.log("  → Sẽ copy cookies từ Chrome portable")

            # Setup lại
            if project_url:
                success = self.setup(project_url=project_url, skip_mode_selection=True)
            else:
                success = self.setup(skip_mode_selection=True)

            if success:
                self.log("[v] FULL RESET thành công!")
                return True
            else:
                self.log("[x] Setup sau reset thất bại", "ERROR")
                return False

        except Exception as e:
            self.log(f"[x] Full reset failed: {e}", "ERROR")
            return False

    def setup(
        self,
        wait_for_project: bool = True,
        timeout: int = 120,
        warm_up: bool = False,
        project_url: str = None,
        skip_mode_selection: bool = False  # True = không click chọn mode (cho Chrome 2 video)
    ) -> bool:
        """
        Setup Chrome và inject interceptor.
        Giống batch_generator.py - không cần warm_up.

        Args:
            wait_for_project: Đợi user chọn project
            timeout: Timeout đợi project (giây)
            warm_up: Tạo 1 ảnh trong Chrome trước (default False - không cần)
            project_url: URL project cố định (nếu có, sẽ vào thẳng project này)
            skip_mode_selection: Bỏ qua việc click chọn "Tạo hình ảnh" (cho video mode)

        Returns:
            True nếu thành công
        """
        # Lưu skip_mode_selection để dùng khi restart_chrome()
        self._skip_mode_selection = skip_mode_selection

        if not DRISSION_AVAILABLE:
            self.log("DrissionPage không được cài đặt! pip install DrissionPage", "ERROR")
            return False

        self.log("=" * 50)
        self.log("  DRISSION FLOW API - Setup")
        self.log("=" * 50)

        # 2. Khởi tạo Chrome
        self.log("Khoi dong Chrome...")
        try:
            options = ChromiumOptions()
            options.set_local_port(self.chrome_port)

            # === AUTO DETECT CHROME PORTABLE ===
            # Tự động tìm Chrome portable tại: C:\Users\{username}\Documents\ve3\chrome.exe
            chrome_exe = None
            user_data = None
            import platform

            # 1. Ưu tiên chrome_portable từ config (KHÔNG check exists - để fail nếu sai)
            if self._chrome_portable:
                # Expand environment variables như %USERNAME%
                chrome_exe = os.path.expandvars(self._chrome_portable)
                chrome_dir = Path(chrome_exe).parent
                self.log(f"[CHROME] Dùng chrome_portable: {chrome_exe}")
                # User Data: Nếu skip_portable_detection=True, dùng profile_dir thay vì built-in profile
                if self._skip_portable_detection:
                    # Dùng profile_dir riêng (Chrome 2 với profile đã copy)
                    user_data = self.profile_dir
                    self.log(f"[CHROME] Dùng profile riêng: {user_data}")
                else:
                    # User Data có thể ở: ve3/User Data hoặc ve3/Data/profile
                    for data_path in [chrome_dir / "Data" / "profile", chrome_dir / "User Data"]:
                        if data_path.exists():
                            user_data = data_path
                            break

            # 2. Tự động detect Chrome portable (bỏ qua nếu skip_portable_detection=True)
            if not chrome_exe and platform.system() == 'Windows' and not self._skip_portable_detection:
                chrome_locations = []

                # 2a. Ưu tiên: Thư mục tool/GoogleChromePortable/GoogleChromePortable.exe
                tool_dir = Path(__file__).parent.parent  # ve3-tool-simple/
                chrome_locations.append(tool_dir / "GoogleChromePortable" / "GoogleChromePortable.exe")

                # 2b. Fallback: Documents\GoogleChromePortable\
                home = Path.home()
                chrome_locations.append(home / "Documents" / "GoogleChromePortable" / "GoogleChromePortable.exe")

                # 2c. Legacy paths (ve3)
                for chrome_name in ["ve3.exe", "chrome.exe", "Chrome.exe"]:
                    chrome_locations.append(home / "Documents" / "ve3" / chrome_name)

                # Tìm Chrome portable
                for chrome_path in chrome_locations:
                    if chrome_path.exists():
                        chrome_exe = str(chrome_path)
                        chrome_dir = chrome_path.parent
                        # Tìm User Data: Data/profile hoặc User Data
                        for data_path in [chrome_dir / "Data" / "profile", chrome_dir / "User Data"]:
                            if data_path.exists():
                                user_data = data_path
                                break
                        # LƯU LẠI để reset_chrome_profile() có thể tìm đúng Data folder
                        self._chrome_portable = chrome_exe
                        self.log(f"[AUTO] Phat hien Chrome: {chrome_exe}")
                        break

            # 3. Dùng Chrome portable nếu tìm thấy
            if chrome_exe:
                options.set_browser_path(chrome_exe)
                if user_data:
                    options.set_user_data_path(str(user_data))
                    self.log(f"[CHROME] {chrome_exe}")
                    self.log(f"[PROFILE] {user_data}")
                else:
                    self.log(f"[CHROME] {chrome_exe}")
                    self.log(f"[PROFILE] (default)")
            else:
                # === FALLBACK: Chrome thường ===
                if platform.system() == 'Windows':
                    chrome_paths = [
                        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                    ]
                    for chrome_path in chrome_paths:
                        if os.path.exists(chrome_path):
                            options.set_browser_path(chrome_path)
                            self.log(f"[CHROME] {chrome_path}")
                            break
                # Tạo profile mới nếu không có chrome portable
                self.profile_dir.mkdir(parents=True, exist_ok=True)
                options.set_user_data_path(str(self.profile_dir))
                self.log(f"[PROFILE] {self.profile_dir}")

            self.log(f"Chrome port: {self.chrome_port}")

            # === CHROME ARGUMENTS ===
            # Nếu dùng chrome_portable: giữ nguyên như mở bằng tay (ít flags nhất)
            # Nếu không: thêm các flags cần thiết cho automation
            if chrome_exe:
                # Chrome portable - CHỈ thêm flags tối thiểu để automation hoạt động
                options.set_argument('--no-first-run')
                options.set_argument('--no-default-browser-check')
                # KHÔNG disable extensions, gpu, sandbox - giữ nguyên như mở bằng tay
                self.log("[NATIVE MODE] Chrome portable - giữ nguyên settings gốc")
            else:
                # Chrome thường - thêm đầy đủ flags
                options.set_argument('--no-sandbox')
                options.set_argument('--disable-dev-shm-usage')
                options.set_argument('--disable-gpu')
                options.set_argument('--disable-software-rasterizer')
                options.set_argument('--disable-extensions')
                options.set_argument('--no-first-run')
                options.set_argument('--no-default-browser-check')

            # Headless mode - chạy Chrome ẩn
            if self._headless:
                options.headless()  # Dùng method built-in của DrissionPage
                options.set_argument('--window-size=1920,1080')
                options.set_argument('--disable-popup-blocking')
                options.set_argument('--ignore-certificate-errors')
                self.log("[MUTE] Headless mode: ON (Chrome chạy ẩn)")
            else:
                self.log("[EYE] Headless mode: OFF (Chrome hiển thị)")

            # === IPv6 MODE - BẬT NGAY KHI MỞ CHROME ===
            # Dùng IPv6 ngay từ đầu, nếu 403 thì đổi IPv6 khác
            # QUAN TRỌNG: Dùng local SOCKS5 proxy để ÉP Chrome chỉ dùng IPv6
            # CHỈ Chrome 1 (worker_id=0) mới activate/quản lý IPv6
            # Chrome 2+ chỉ dùng proxy đã có (Chrome 1 khởi động)
            _using_ipv6_proxy = False
            try:
                from modules.ipv6_rotator import get_ipv6_rotator
                rotator = get_ipv6_rotator()
                if rotator and rotator.enabled and rotator.ipv6_list:
                    self.log(f"[NET] IPv6 MODE: Có {len(rotator.ipv6_list)} IPs")

                    # Chrome 2+: Chỉ dùng proxy, KHÔNG activate IPv6
                    if self.worker_id > 0:
                        self.log(f"[NET] [Worker{self.worker_id}] Dùng IPv6 proxy từ Chrome 1 (port 1088)")
                        working_ipv6 = rotator.current_ipv6  # Lấy IP hiện tại (Chrome 1 đã set)
                        if not working_ipv6:
                            # Nếu Chrome 1 chưa set, dùng IP đầu tiên
                            working_ipv6 = rotator.ipv6_list[0] if rotator.ipv6_list else None
                            self.log(f"[NET] [Worker{self.worker_id}] Fallback to: {working_ipv6}")
                    else:
                        # Chrome 1: Activate IPv6
                        if not self._ipv6_activated:
                            self.log(f"[NET] Activating IPv6 lần đầu...")
                            working_ipv6 = rotator.init_with_working_ipv6()
                        else:
                            # Đã activated trước đó → giữ nguyên IP hiện tại
                            working_ipv6 = rotator.current_ipv6
                            if working_ipv6:
                                self.log(f"[NET] Giữ nguyên IPv6: {working_ipv6}")

                    if working_ipv6:
                        self._ipv6_activated = True
                        self._ipv6_rotator = rotator
                        self.log(f"[NET] IPv6 ACTIVE: {working_ipv6}")

                        # === START LOCAL SOCKS5 PROXY - ÉP CHROME DÙNG IPv6 ===
                        # PC có cả IPv4+IPv6, Chrome mặc định dùng IPv4
                        # Proxy này ép TẤT CẢ traffic của Chrome đi qua IPv6
                        # QUAN TRỌNG: Dùng CÙNG port 1088 cho TẤT CẢ workers vì proxy là singleton
                        proxy_port = 1088  # Fixed port - shared by all workers
                        try:
                            # CHỈ Chrome 1 mới start proxy, Chrome 2+ dùng proxy đã có
                            if self.worker_id == 0:
                                from modules.ipv6_proxy import start_ipv6_proxy
                                self._ipv6_proxy = start_ipv6_proxy(
                                    ipv6_address=working_ipv6,
                                    port=proxy_port,
                                    log_func=self.log
                                )
                                if self._ipv6_proxy:
                                    self.log(f"[NET] Chrome 1 started IPv6 proxy on port {proxy_port}")
                                else:
                                    self.log(f"[WARN] IPv6 proxy failed to start", "WARN")
                            else:
                                self.log(f"[NET] [Worker{self.worker_id}] Dùng IPv6 proxy từ Chrome 1")
                                self._ipv6_proxy = True  # Mark as using proxy

                            # Cả 2 Chrome đều dùng proxy
                            options.set_argument(f'--proxy-server=socks5://127.0.0.1:{proxy_port}')
                            options.set_argument('--proxy-bypass-list=<-loopback>')
                            self.log(f"[NET] Chrome → SOCKS5 proxy → IPv6 ONLY")
                            self.log(f"   Proxy: socks5://127.0.0.1:{proxy_port}")
                            _using_ipv6_proxy = True
                        except Exception as proxy_err:
                            self.log(f"[WARN] IPv6 proxy error: {proxy_err}", "WARN")
                    else:
                        self.log(f"[WARN] Không tìm được IPv6 hoạt động!", "WARN")
            except Exception as e:
                self.log(f"[WARN] IPv6 activation error: {e}", "WARN")

            if not _using_ipv6_proxy and self._use_webshare and self._webshare_proxy:
                from webshare_proxy import get_proxy_manager
                manager = get_proxy_manager()

                # === CHECK ROTATING ENDPOINT MODE ===
                if manager.is_rotating_mode():
                    # ROTATING RESIDENTIAL: 2 modes
                    # 1. Random IP: username ends with -rotate → mỗi request = IP ngẫu nhiên
                    # 2. Sticky Session: username không -rotate → session ID tự động thêm
                    rotating = manager.rotating_endpoint
                    self._is_rotating_mode = True
                    self._is_random_ip_mode = rotating.base_username.endswith('-rotate')

                    # Session ID từ counter (chỉ dùng cho Sticky Session mode)
                    session_id = self._rotating_session_id
                    session_username = rotating.get_username_for_session(session_id)

                    try:
                        from proxy_bridge import start_proxy_bridge
                        bridge_port = 8800 + self.worker_id
                        self._proxy_bridge = start_proxy_bridge(
                            local_port=bridge_port,
                            remote_host=rotating.host,
                            remote_port=rotating.port,
                            username=session_username,
                            password=rotating.password
                        )
                        self._bridge_port = bridge_port
                        time.sleep(0.5)

                        options.set_argument(f'--proxy-server=http://127.0.0.1:{bridge_port}')
                        options.set_argument('--proxy-bypass-list=<-loopback>')
                        options.set_argument('--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1')

                        if self._is_random_ip_mode:
                            self.log(f"[RAND] RANDOM IP MODE [Worker {self.worker_id}]")
                            self.log(f"  → {rotating.host}:{rotating.port}")
                            self.log(f"  → Username: {session_username} (mỗi request = IP mới)")
                        else:
                            self.log(f"[SYNC] STICKY SESSION [Worker {self.worker_id}]")
                            self.log(f"  → {rotating.host}:{rotating.port}")
                            self.log(f"  → Session: {session_username}")
                        self.log(f"  Local: http://127.0.0.1:{bridge_port}")

                    except Exception as e:
                        self.log(f"Bridge error: {e}", "ERROR")
                        return False
                else:
                    # === DIRECT PROXY LIST MODE ===
                    self._is_rotating_mode = False
                    username, password = self._webshare_proxy.get_chrome_auth(self.worker_id)
                    remote_proxy_url = self._webshare_proxy.get_chrome_proxy_arg(self.worker_id)

                    if username and password:
                        # Có auth → dùng local proxy bridge
                        # QUAN TRỌNG: Lấy proxy cho worker này, không dùng current_proxy global
                        proxy = manager.get_proxy_for_worker(self.worker_id)
                        if not proxy:
                            # Không có proxy khả dụng - chạy không proxy (fallback)
                            self.log(f"[WARN] No proxy available - running WITHOUT proxy", "WARN")
                            self._use_webshare = False
                            # Không set proxy args - Chrome sẽ chạy direct
                        else:
                            try:
                                from proxy_bridge import start_proxy_bridge
                                # Unique bridge port based on worker_id (parallel-safe)
                                bridge_port = 8800 + self.worker_id
                                self._proxy_bridge = start_proxy_bridge(
                                    local_port=bridge_port,
                                    remote_host=proxy.host,
                                    remote_port=proxy.port,
                                    username=proxy.username,
                                    password=proxy.password
                                )
                                self._bridge_port = bridge_port  # LƯU ĐỂ DÙNG TRONG call_api()
                                time.sleep(0.5)  # Đợi bridge start

                                # Chrome kết nối đến local bridge (không cần auth)
                                options.set_argument(f'--proxy-server=http://127.0.0.1:{bridge_port}')
                                options.set_argument('--proxy-bypass-list=<-loopback>')
                                options.set_argument('--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1')

                                self.log(f"Proxy [Worker {self.worker_id}]: Bridge → {proxy.endpoint}")
                                self.log(f"  Local: http://127.0.0.1:{bridge_port}")
                                self.log(f"  Auth: {username}:****")

                            except Exception as e:
                                self.log(f"Bridge error: {e}, using direct proxy", "WARN")
                                options.set_argument(f'--proxy-server={remote_proxy_url}')
                                options.set_argument('--proxy-bypass-list=<-loopback>')
                                self._proxy_auth = (username, password)
                    else:
                        # IP Authorization mode
                        options.set_argument(f'--proxy-server={remote_proxy_url}')
                        options.set_argument('--proxy-bypass-list=<-loopback>')
                        options.set_argument('--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1')
                        self.log(f"Proxy: Webshare ({remote_proxy_url})")
                        self.log(f"  Mode: IP Authorization")
            elif not _using_ipv6_proxy:
                # Không có proxy nào (không có webshare, không có IPv6)
                self._is_rotating_mode = False
                self.log("[WARN] Không có proxy - chạy direct connection", "WARN")

            # Tắt Chrome đang dùng CÙNG profile này trước (tránh conflict)
            # CHÚ Ý: Chỉ kill Chrome dùng profile này, KHÔNG kill Chrome khác
            self._kill_chrome_using_profile()

            # === XÓA TẤT CẢ LOCK FILES ===
            try:
                lock_files = ["SingletonLock", "SingletonSocket", "SingletonCookie", "lockfile"]
                for lock_name in lock_files:
                    lock_file = self.profile_dir / lock_name
                    if lock_file.exists():
                        try:
                            lock_file.unlink()
                            self.log(f"  → Đã xóa {lock_name}")
                        except:
                            pass
            except:
                pass

            # Thử khởi tạo Chrome với retry
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self.driver = ChromiumPage(addr_or_opts=options)
                    self.log("[v] Chrome started")
                    break
                except Exception as chrome_err:
                    self.log(f"Chrome attempt {attempt+1}/{max_retries} failed: {chrome_err}", "WARN")
                    if attempt < max_retries - 1:
                        # Kill Chrome trên port này trước khi thử lại
                        self._kill_chrome_on_port(self.chrome_port)
                        # Thử port khác
                        self.chrome_port = random.randint(9222, 9999)
                        options.set_local_port(self.chrome_port)
                        self.log(f"  → Retry với port {self.chrome_port}...")
                        time.sleep(3)  # Đợi lâu hơn để Chrome cũ tắt hẳn
                    else:
                        raise chrome_err

            # === WINDOW LAYOUT - Chia màn hình theo số workers ===
            if not self._headless and self._total_workers > 0:
                self._setup_window_layout()

            # Setup proxy auth nếu cần (CDP-based)
            if self._use_webshare and hasattr(self, '_proxy_auth') and self._proxy_auth:
                self._setup_proxy_auth()

        except Exception as e:
            self.log(f"[x] Chrome error: {e}", "ERROR")
            return False

        # 3. Vào Google Flow (hoặc project cố định nếu có) - VỚI RETRY
        target_url = project_url if project_url else self.FLOW_URL
        self.log(f"Vào: {target_url[:60]}...")

        max_nav_retries = 3
        nav_success = False

        for nav_attempt in range(max_nav_retries):
            try:
                self.driver.get(target_url)
                # IPv6 cần thời gian load lâu hơn
                wait_time = 6 if getattr(self, '_ipv6_activated', False) else 3
                time.sleep(wait_time)

                # === F5 REFRESH ngay sau khi vào link ===
                # Trang hay bị lag khi mới vào, refresh để load lại cho ổn định
                self.log("[SYNC] Refresh trang (tránh lag)...")
                self.driver.refresh()
                time.sleep(wait_time)

                # Kiểm tra xem trang có load được không
                current_url = self.driver.url
                if not current_url or current_url == "about:blank" or "error" in current_url.lower():
                    raise Exception(f"Page không load được: {current_url}")

                self.log(f"[v] URL: {current_url}")

                # === KIỂM TRA BỊ LOGOUT ===
                if self._is_logged_out():
                    self.log("[WARN] Phát hiện bị LOGOUT khỏi Google!", "WARN")

                    # Thử auto-login
                    if self._auto_login_google():
                        self.log("[v] Auto-login thành công!")
                        self.log("[SYNC] Restart setup từ đầu...")
                        time.sleep(3)

                        # Gọi lại setup() từ đầu (đệ quy)
                        return self.setup(
                            wait_for_project=wait_for_project,
                            timeout=timeout,
                            warm_up=warm_up,
                            project_url=project_url
                        )
                    else:
                        self.log("[x] Auto-login thất bại", "ERROR")
                        return False

                # Lưu project_url để dùng khi retry
                if "/project/" in current_url:
                    self._current_project_url = current_url
                    self.log(f"  → Saved project URL for retry")

                nav_success = True
                break

            except Exception as e:
                error_msg = str(e)
                self.log(f"[x] Navigation error (attempt {nav_attempt+1}/{max_nav_retries}): {error_msg}", "WARN")

                # Kiểm tra lỗi proxy/connection
                is_proxy_error = any(x in error_msg.lower() for x in [
                    "timeout", "connection", "proxy", "10060", "err_proxy", "err_connection"
                ])

                if is_proxy_error and nav_attempt < max_nav_retries - 1:
                    self.log(f"  → Proxy/Connection error, restart Chrome...", "WARN")

                    # Restart Chrome
                    self._kill_chrome()
                    self.close()
                    time.sleep(3)

                    # Restart với cùng config - dùng setup() thay vì _start_chrome()
                    try:
                        saved_project_url = getattr(self, '_current_project_url', None)
                        skip_mode = getattr(self, '_skip_mode_selection', False)
                        if not self.setup(project_url=saved_project_url, skip_mode_selection=skip_mode):
                            self.log("  → Không restart được Chrome", "ERROR")
                            continue
                        self.log("  → Chrome restarted, thử lại...")
                    except Exception as restart_err:
                        self.log(f"  → Restart Chrome lỗi: {restart_err}", "ERROR")
                        continue
                elif nav_attempt >= max_nav_retries - 1:
                    self.log(f"[x] Navigation failed sau {max_nav_retries} lần thử", "ERROR")
                    return False

        if not nav_success:
            # === FALLBACK: Thử đổi proxy mode ===
            fallback_tried = False

            if hasattr(self, '_is_rotating_mode') and self._is_rotating_mode:
                try:
                    from webshare_proxy import get_proxy_manager
                    manager = get_proxy_manager()

                    if manager.is_rotating_mode() and manager.rotating_endpoint:
                        rotating = manager.rotating_endpoint
                        old_username = rotating.base_username

                        # Xác định mode hiện tại và đổi sang mode khác
                        if hasattr(self, '_is_random_ip_mode') and self._is_random_ip_mode:
                            # Đang Random IP → thử Sticky Session
                            self.log("[WARN] Random IP mode failed, thử STICKY SESSION mode...", "WARN")
                            new_username = old_username.replace('-rotate', '')
                            fallback_mode = "Sticky Session"
                        else:
                            # Đang Sticky Session → thử Random IP
                            self.log("[WARN] Sticky Session mode failed, thử RANDOM IP mode...", "WARN")
                            if not old_username.endswith('-rotate'):
                                new_username = old_username + '-rotate'
                            else:
                                new_username = old_username
                            fallback_mode = "Random IP"

                        if new_username != old_username:
                            # Kill everything
                            self._kill_chrome()
                            self.close()
                            time.sleep(2)

                            # Switch mode
                            rotating.base_username = new_username
                            self._is_random_ip_mode = new_username.endswith('-rotate')
                            self.log(f"  → Đổi từ '{old_username}' sang '{new_username}'")

                            if not self._is_random_ip_mode:
                                self.log(f"  → Sticky Session ID: {self._rotating_session_id}")

                            # Restart với mode mới - dùng setup() thay vì _start_chrome()
                            saved_project_url = getattr(self, '_current_project_url', None)
                            skip_mode = getattr(self, '_skip_mode_selection', False)
                            if self.setup(project_url=saved_project_url, skip_mode_selection=skip_mode):
                                # Retry navigation
                                try:
                                    self.driver.get(target_url)
                                    time.sleep(3)
                                    if self.driver.url and self.driver.url != "about:blank":
                                        self.log(f"[v] {fallback_mode} OK! URL: {self.driver.url}")
                                        nav_success = True
                                        fallback_tried = True
                                except Exception as e:
                                    self.log(f"  → {fallback_mode} cũng fail: {e}", "ERROR")
                                    fallback_tried = True

                except Exception as fallback_err:
                    self.log(f"  → Fallback error: {fallback_err}", "ERROR")

            if not nav_success:
                if fallback_tried:
                    self.log("[x] Cả hai proxy modes đều fail!", "ERROR")
                else:
                    self.log("[x] Không thể vào trang Google Flow", "ERROR")
                return False

        # 4. Auto setup project (click "Dự án mới" + chọn "Tạo hình ảnh")
        if wait_for_project:
            # Kiểm tra đã ở trong project chưa
            if "/project/" not in self.driver.url:
                # Nếu có project_url nhưng bị redirect về trang chủ → retry vào project cũ
                if project_url and "/project/" in project_url:
                    self.log(f"[WARN] Bị redirect, retry vào project cũ...")
                    # Retry vào project URL (max 3 lần)
                    for retry in range(3):
                        time.sleep(2)
                        self.driver.get(project_url)
                        time.sleep(3)
                        if "/project/" in self.driver.url:
                            self._current_project_url = self.driver.url
                            self.log(f"[v] Vào lại project thành công!")
                            break
                        self.log(f"  → Retry {retry+1}/3...")
                    else:
                        self.log("[x] Không vào được project cũ, session có thể hết hạn", "ERROR")
                        return False
                else:
                    # Không có project URL → tạo mới
                    self.log("Auto setup project...")
                    if not self._auto_setup_project(timeout):
                        return False
                    # Lưu project URL sau khi tạo mới
                    if "/project/" in self.driver.url:
                        self._current_project_url = self.driver.url
                        self.log(f"  → New project URL saved")
            else:
                self.log("[v] Đã ở trong project!")
                # F5 để load lại trang
                self.log("   → F5 refresh...")
                self.driver.refresh()
                time.sleep(3)

        # 5. Đợi textarea sẵn sàng - TEXTAREA = page đã load xong
        # IPv6 cần thời gian lâu hơn, tự động F5 nếu không thấy
        self.log("Đợi project load (textarea = ready)...")

        # Kiểm tra logout trước
        if self._is_logged_out():
            self.log("[PROJECT] [WARN] Phát hiện bị LOGOUT!")
            if self._auto_login_google():
                self.log("[PROJECT] [v] Đã login lại, quay lại project...")
                self.driver.get(f"https://labs.google/fx/tools/video-fx/projects/{self.project_id}")
                time.sleep(6 if getattr(self, '_ipv6_activated', False) else 3)
            else:
                self.log("[PROJECT] [x] Login lại thất bại", "ERROR")
                return False

        # Đợi textarea - tự động F5 nếu không thấy (IPv6 friendly)
        if not self._wait_for_textarea_visible():
            # Thử navigate lại project 1 lần nữa
            self.log("[PROJECT] [WARN] Không thấy textarea, thử load lại project...")
            try:
                self.driver.get(f"https://labs.google/fx/tools/video-fx/projects/{self.project_id}")
                time.sleep(6 if getattr(self, '_ipv6_activated', False) else 3)
                if not self._wait_for_textarea_visible():
                    self.log("[x] Không thể tìm textarea sau nhiều lần thử", "ERROR")
                    return False
            except Exception as e:
                self.log(f"[PROJECT] Navigate error: {e}", "ERROR")
                return False

        self.log("[v] Project đã sẵn sàng (textarea visible)!")

        # Mode đã được chọn ở _auto_setup_project()
        # Không cần chọn lại ở đây

        # 6. Warm up session (tạo 1 ảnh trong Chrome để activate)
        if warm_up:
            if not self._warm_up_session():
                self.log("[WARN] Warm up không thành công, tiếp tục...", "WARN")

        # 7. Inject interceptor (SAU khi warm up) - với xử lý ContextLostError
        self.log("Inject interceptor...")
        self._reset_tokens()
        for retry_count in range(3):
            try:
                result = self.driver.run_js(JS_INTERCEPTOR)
                self.log(f"[v] Interceptor: {result}")
                break
            except Exception as e:
                if ContextLostError and isinstance(e, ContextLostError):
                    self.log(f"[PAGE] [WARN] Page bị refresh khi inject interceptor (retry {retry_count + 1}/3)")
                    if self._wait_for_page_ready(timeout=30):
                        continue
                else:
                    self.log(f"[PAGE] Lỗi inject: {e}", "WARN")
                    break

        self._ready = True
        return True

    def _find_textarea(self):
        """Tìm textarea input (không click)."""
        for sel in ["tag:textarea", "css:textarea"]:
            try:
                el = self.driver.ele(sel, timeout=2)
                if el:
                    return el
            except:
                pass
        return None

    def _wait_for_textarea_visible(self, timeout: int = None, max_refresh: int = 3) -> bool:
        """
        Đợi textarea xuất hiện VÀ có thể tương tác.
        Textarea là dấu hiệu page đã load xong.
        PHẢI verify textarea thật sự visible, không chỉ có trong DOM.
        """
        # Timeout tối đa 10s là đủ
        if timeout is None:
            timeout = 10

        for refresh_count in range(max_refresh + 1):
            # === CHECK LOGOUT TRƯỚC MỖI VÒNG ===
            if self._is_logged_out():
                self.log(f"[TEXTAREA] [WARN] Phát hiện bị LOGOUT - auto login...")
                if self._auto_login_google():
                    self.log(f"[TEXTAREA] [v] Đã login lại, tiếp tục đợi textarea...")
                    time.sleep(2)
                else:
                    self.log(f"[TEXTAREA] [x] Login thất bại", "ERROR")
                    return False

            self.log(f"[TEXTAREA] Đợi textarea... (timeout={timeout}s, lần {refresh_count + 1}/{max_refresh + 1})")

            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    # Tìm textarea
                    textarea = self.driver.ele('tag:textarea', timeout=2)
                    if textarea:
                        # === VERIFY: Textarea phải THẬT SỰ visible và có thể tương tác ===
                        try:
                            # Check 1: Element phải displayed
                            is_displayed = textarea.states.is_displayed
                            if not is_displayed:
                                time.sleep(0.5)
                                continue

                            # Check 2: Thử click vào textarea để verify có thể tương tác
                            textarea.click()
                            time.sleep(0.3)

                            # Check 3: Verify textarea vẫn còn sau khi click (page không bị redirect)
                            verify = self.driver.ele('tag:textarea', timeout=1)
                            if verify:
                                self.log(f"[TEXTAREA] [v] Textarea visible và interactive!")
                                return True
                        except Exception as verify_err:
                            self.log(f"[TEXTAREA] Element found but not ready: {verify_err}")
                            time.sleep(0.5)
                            continue
                except Exception as e:
                    pass
                time.sleep(0.5)

            # Timeout - thử F5 refresh nếu còn lượt
            if refresh_count < max_refresh:
                self.log(f"[TEXTAREA] [WARN] Không thấy textarea sẵn sàng, F5 refresh...")
                try:
                    self.driver.refresh()
                    # IPv6 cần đợi lâu hơn sau F5
                    wait_time = 6 if getattr(self, '_ipv6_activated', False) else 3
                    time.sleep(wait_time)
                except Exception as e:
                    self.log(f"[TEXTAREA] Refresh error: {e}")

        self.log("[TEXTAREA] [x] Không tìm thấy textarea", "ERROR")
        return False

    def _get_page_load_timeout(self) -> int:
        """Get appropriate timeout based on connection mode (IPv6 slower than IPv4)."""
        if getattr(self, '_ipv6_activated', False):
            return 45  # IPv6 cần thời gian lâu hơn
        return 30

    def _wait_for_page_ready(self, timeout: int = None, max_refresh: int = 2) -> bool:
        """
        Đợi page load xong sau khi bị refresh.
        Kiểm tra document.readyState và có thể truy cập DOM.
        Nếu phát hiện logout → tự động login lại.
        IPv6 mode: timeout lâu hơn, tự động F5 nếu không load được.

        Args:
            timeout: Timeout tối đa (giây), None = auto based on IPv6
            max_refresh: Số lần F5 tối đa nếu timeout

        Returns:
            True nếu page đã sẵn sàng
        """
        if timeout is None:
            timeout = self._get_page_load_timeout()

        for refresh_count in range(max_refresh + 1):
            self.log(f"[PAGE] Đợi page load... (timeout={timeout}s, lần {refresh_count + 1})")

            for i in range(timeout):
                try:
                    # === KIỂM TRA LOGOUT TRƯỚC ===
                    if self._is_logged_out():
                        self.log("[PAGE] [WARN] Phát hiện bị LOGOUT!")
                        if self._auto_login_google():
                            self.log("[PAGE] [v] Đã login lại thành công!")
                            return False  # Return False để trigger retry từ setup()
                        else:
                            self.log("[PAGE] [x] Login lại thất bại", "ERROR")
                            return False

                    # Kiểm tra page ready state
                    ready_state = self.driver.run_js("return document.readyState")
                    if ready_state == "complete":
                        # Thử tìm element cơ bản để đảm bảo DOM sẵn sàng
                        if self._find_textarea():
                            self.log("[PAGE] [v] Page đã sẵn sàng!")
                            return True
                        # Nếu không có textarea, đợi thêm
                        time.sleep(1)
                except Exception as e:
                    # Page vẫn đang load, đợi tiếp
                    time.sleep(1)

            # === TIMEOUT: Kiểm tra logout lần cuối ===
            if self._is_logged_out():
                self.log("[PAGE] [WARN] Timeout do bị LOGOUT!")
                if self._auto_login_google():
                    self.log("[PAGE] [v] Đã login lại!")
                    return False
                else:
                    self.log("[PAGE] [x] Login lại thất bại", "ERROR")
                    return False

            # === TIMEOUT: F5 refresh nếu còn lượt ===
            if refresh_count < max_refresh:
                self.log(f"[PAGE] [WARN] Timeout - F5 refresh để load lại...")
                try:
                    self.driver.refresh()
                    time.sleep(5)  # Đợi sau F5 (IPv6 cần lâu hơn)
                except Exception as e:
                    self.log(f"[PAGE] F5 error: {e}")

        self.log("[PAGE] [WARN] Timeout đợi page load (sau nhiều lần F5)", "WARN")
        return False

    def _safe_run_js(self, script: str, max_retries: int = 3, default=None):
        """
        Wrapper an toàn cho run_js() với retry khi page bị refresh.

        Args:
            script: JavaScript code cần chạy
            max_retries: Số lần retry tối đa khi gặp ContextLostError
            default: Giá trị trả về mặc định nếu thất bại

        Returns:
            Kết quả từ JavaScript hoặc default nếu lỗi
        """
        for attempt in range(max_retries):
            try:
                return self.driver.run_js(script)
            except Exception as e:
                if ContextLostError and isinstance(e, ContextLostError):
                    if attempt < max_retries - 1:
                        self.log(f"[JS] Page refresh, đợi load... (retry {attempt + 1}/{max_retries})")
                        if self._wait_for_page_ready(timeout=15):
                            continue
                    self.log(f"[JS] ContextLostError sau {max_retries} lần retry", "WARN")
                else:
                    self.log(f"[JS] Lỗi: {e}", "WARN")
                return default
        return default

    def _paste_prompt_ctrlv(self, textarea, prompt: str) -> bool:
        """
        Nhập prompt bằng Ctrl+V (pyperclip).

        Args:
            textarea: Element textarea đã tìm thấy
            prompt: Nội dung prompt cần nhập

        Returns:
            True nếu thành công
        """
        try:
            import pyperclip

            # 1. Copy prompt vào clipboard
            pyperclip.copy(prompt)
            self.log(f"→ Copied {len(prompt)} chars to clipboard")

            # 2. Tìm textarea bằng DrissionPage
            textarea = self.driver.ele('tag:textarea', timeout=10)
            if not textarea:
                self.log("[WARN] Không tìm thấy textarea", "WARN")
                return False

            # 3. Click vào textarea để focus
            try:
                textarea.click()
                time.sleep(0.5)
            except:
                pass

            # 4. Clear nội dung cũ bằng Ctrl+A
            from DrissionPage.common import Keys
            try:
                textarea.input(Keys.CTRL_A)
                time.sleep(0.1)
            except:
                pass

            # 5. Paste bằng Ctrl+V
            self.log("→ Pasting with Ctrl+V...")
            textarea.input(Keys.CTRL_V)
            time.sleep(0.5)

            self.log(f"→ Paste done [v]")
            return True

        except Exception as e:
            self.log(f"[WARN] Paste prompt failed: {e}", "WARN")
            return False

    def _paste_prompt_js(self, prompt: str) -> bool:
        """Fallback: Paste prompt bằng JavaScript."""
        try:
            time.sleep(1)
            result = self.driver.run_js(f"""
                (function() {{
                    var textarea = document.querySelector('textarea');
                    if (!textarea) return 'not_found';

                    textarea.scrollIntoView({{block: 'center'}});
                    textarea.focus();
                    textarea.value = {repr(prompt)};
                    textarea.dispatchEvent(new Event('input', {{bubbles: true}}));

                    return 'ok';
                }})();
            """)
            if result == 'ok':
                self.log("→ Pasted with JS [v]")
                return True
            return False
        except Exception as e:
            self.log(f"[WARN] JS paste failed: {e}", "WARN")
            return False

    def _setup_window_layout(self):
        """
        Thiết lập vị trí và kích thước Chrome window dựa trên worker_id và total_workers.

        Layout:
        - 1 worker: Full màn hình
        - 2 workers: Chia đôi ngang (worker 0 = trái, worker 1 = phải)
        - 3+ workers: Chia theo grid
        """
        try:
            # Lấy kích thước màn hình từ JavaScript
            screen_info = self.driver.run_js("""
                return {
                    width: window.screen.availWidth,
                    height: window.screen.availHeight,
                    left: window.screen.availLeft || 0,
                    top: window.screen.availTop || 0
                };
            """)

            if not screen_info:
                # Fallback: assume 1920x1080
                screen_info = {'width': 1920, 'height': 1080, 'left': 0, 'top': 0}

            screen_w = screen_info.get('width', 1920)
            screen_h = screen_info.get('height', 1080)
            screen_left = screen_info.get('left', 0)
            screen_top = screen_info.get('top', 0)

            total = self._total_workers
            worker = self.worker_id

            # Helper để set window position (tương thích nhiều version DrissionPage)
            def set_window_rect(x, y, w, h):
                try:
                    # Thử cách mới: set.window.rect()
                    self.driver.set.window.rect(x, y, w, h)
                except AttributeError:
                    try:
                        # Thử cách cũ: size + position riêng
                        self.driver.set.window.size(w, h)
                        self.driver.set.window.position(x, y)
                    except AttributeError:
                        # Fallback: dùng JavaScript
                        self.driver.run_js(f"window.moveTo({x}, {y}); window.resizeTo({w}, {h});")

            # Fixed Chrome window size (700x550) on right side, stacked vertically
            # This matches the layout in vm_manager.show_chrome_windows()
            chrome_width = 700
            chrome_height = 550

            # Position on right side of screen
            x_start = screen_w - chrome_width - 10  # 10px from right edge
            y_start = 50  # Start 50px from top

            # Stack windows vertically based on worker_id
            win_x = x_start
            win_y = y_start + (worker * (chrome_height + 10))  # 10px gap between windows

            # Make sure it doesn't go off screen
            if win_y + chrome_height > screen_h:
                win_y = y_start  # Reset to top if too low

            set_window_rect(win_x, win_y, chrome_width, chrome_height)
            self.log(f"[WIN] Window: Chrome {worker + 1} ({chrome_width}x{chrome_height} at {win_x},{win_y})")

        except Exception as e:
            self.log(f"[WARN] Window layout error: {e}", "WARN")
            # Don't fallback to maximize - keep Chrome at default size

    def _click_textarea(self, wait_visible: bool = True):
        """
        Click vào textarea để focus - QUAN TRỌNG để nhập prompt.
        Đợi textarea visible trước khi click, nếu không thấy sẽ F5 refresh.

        Args:
            wait_visible: True = đợi textarea visible trước khi click
        """
        try:
            # QUAN TRỌNG: Đợi textarea visible trước khi click
            if wait_visible:
                if not self._wait_for_textarea_visible(timeout=10, max_refresh=2):
                    self.log("[x] Textarea không visible sau khi refresh", "ERROR")
                    return False

            result = self.driver.run_js("""
                (function() {
                    var textarea = document.querySelector('textarea');
                    if (!textarea) return 'not_found';

                    // Kiểm tra visible lần cuối trước khi click
                    var rect = textarea.getBoundingClientRect();
                    if (rect.width <= 0 || rect.height <= 0) return 'not_visible';

                    // Scroll vào view
                    textarea.scrollIntoView({block: 'center', behavior: 'instant'});

                    // Lấy vị trí giữa textarea
                    rect = textarea.getBoundingClientRect();
                    var centerX = rect.left + rect.width / 2;
                    var centerY = rect.top + rect.height / 2;

                    // Tạo và dispatch mousedown event
                    var mousedown = new MouseEvent('mousedown', {
                        bubbles: true, cancelable: true, view: window,
                        clientX: centerX, clientY: centerY
                    });
                    textarea.dispatchEvent(mousedown);

                    // Tạo và dispatch mouseup event
                    var mouseup = new MouseEvent('mouseup', {
                        bubbles: true, cancelable: true, view: window,
                        clientX: centerX, clientY: centerY
                    });
                    textarea.dispatchEvent(mouseup);

                    // Tạo và dispatch click event
                    var click = new MouseEvent('click', {
                        bubbles: true, cancelable: true, view: window,
                        clientX: centerX, clientY: centerY
                    });
                    textarea.dispatchEvent(click);

                    // Focus
                    textarea.focus();

                    return 'clicked';
                })();
            """)

            if result == 'clicked':
                self.log("[v] Clicked textarea (JS) - lần 1")
                # Click lần 2 sau 2s để đảm bảo focus
                time.sleep(2)
                result2 = self.driver.run_js("""
                    (function() {
                        var textarea = document.querySelector('textarea');
                        if (!textarea) return 'not_found';
                        textarea.scrollIntoView({block: 'center', behavior: 'instant'});
                        var rect = textarea.getBoundingClientRect();
                        var centerX = rect.left + rect.width / 2;
                        var centerY = rect.top + rect.height / 2;
                        var click = new MouseEvent('click', {
                            bubbles: true, cancelable: true, view: window,
                            clientX: centerX, clientY: centerY
                        });
                        textarea.dispatchEvent(click);
                        textarea.focus();
                        return 'clicked';
                    })();
                """)
                if result2 == 'clicked':
                    self.log("[v] Clicked textarea (JS) - lần 2")
                time.sleep(0.3)
                return True
            elif result == 'not_found':
                self.log("[x] Textarea not found", "ERROR")
            elif result == 'not_visible':
                self.log("[x] Textarea not visible", "ERROR")
            return False
        except Exception as e:
            self.log(f"[WARN] Click textarea error: {e}", "WARN")
            return False

    def _reset_tokens(self):
        """Reset captured tokens trong browser."""
        self.driver.run_js("""
            window.__interceptReady = false;
            window._tk = null;
            window._pj = null;
            window._xbv = null;
            window._rct = null;
            window._payload = null;
            window._sid = null;
            window._url = null;
            window._response = null;
            window._responseError = null;
            window._requestPending = false;
            window._customPayload = null;
            window._videoResponse = null;
            window._videoError = null;
            window._videoPending = false;
        """)

    def _capture_tokens(self, prompt: str, timeout: int = 10) -> bool:
        """
        Gửi prompt để capture tất cả tokens cần thiết.
        Giống batch_generator.py get_tokens().

        Args:
            prompt: Prompt để gửi
            timeout: Timeout đợi tokens (giây)

        Returns:
            True nếu capture thành công
        """
        self.log(f"    Prompt: {prompt[:50]}...")

        # QUAN TRỌNG: Reset tokens trước khi capture để đợi giá trị MỚI
        # Nếu không reset, sẽ lấy tokens cũ từ lần capture trước!
        self.driver.run_js("""
            window._rct = null;
            window._payload = null;
            window._url = null;
        """)

        # Tìm và gửi prompt
        textarea = self._find_textarea()
        if not textarea:
            self.log("[x] Không tìm thấy textarea", "ERROR")
            return False

        # Paste bằng Ctrl+V (tránh bot detection)
        self._paste_prompt_ctrlv(textarea, prompt)
        time.sleep(0.3)
        textarea.input('\n')  # Enter để gửi
        self.log("    [v] Đã gửi, đợi capture...")

        # Đợi 3 giây theo hướng dẫn (giống batch_generator.py)
        time.sleep(3)

        # Đọc tokens từ window variables
        for i in range(timeout):
            tokens = self.driver.run_js("""
                return {
                    tk: window._tk,
                    pj: window._pj,
                    xbv: window._xbv,
                    rct: window._rct,
                    sid: window._sid,
                    url: window._url
                };
            """)

            # Debug output (giống batch_generator.py)
            if i == 0 or i == 5:
                self.log(f"    [DEBUG] Bearer: {'YES' if tokens.get('tk') else 'NO'}")
                self.log(f"    [DEBUG] recaptcha: {'YES' if tokens.get('rct') else 'NO'}")
                self.log(f"    [DEBUG] projectId: {'YES' if tokens.get('pj') else 'NO'}")
                self.log(f"    [DEBUG] URL: {'YES' if tokens.get('url') else 'NO'}")

            if tokens.get("tk") and tokens.get("rct"):
                self.bearer_token = f"Bearer {tokens['tk']}"
                self.project_id = tokens.get("pj")
                self.session_id = tokens.get("sid")
                self.recaptcha_token = tokens.get("rct")
                self.x_browser_validation = tokens.get("xbv")
                self.captured_url = tokens.get("url")

                self.log("    [v] Got Bearer token!")
                self.log("    [v] Got recaptchaToken!")
                if self.captured_url:
                    self.log(f"    [v] Captured URL: {self.captured_url[:60]}...")
                return True

            time.sleep(1)

        self.log("    [x] Không lấy được đủ tokens", "ERROR")
        return False

    def refresh_recaptcha(self, prompt: str) -> bool:
        """
        Gửi prompt mới để lấy fresh recaptchaToken.
        Giống batch_generator.py refresh_recaptcha().

        Args:
            prompt: Prompt để trigger recaptcha

        Returns:
            True nếu thành công
        """
        # Reset captured data (chỉ rct - giống batch_generator.py)
        self.driver.run_js("window._rct = null;")

        textarea = self._find_textarea()
        if not textarea:
            return False

        # Paste bằng Ctrl+V (tránh bot detection)
        self._paste_prompt_ctrlv(textarea, prompt)
        time.sleep(0.3)
        textarea.input('\n')

        # Đợi 3 giây
        time.sleep(3)

        # Wait for new token
        for i in range(10):
            rct = self.driver.run_js("return window._rct;")
            if rct:
                self.recaptcha_token = rct
                self.log("    [v] Got new recaptchaToken!")
                return True
            time.sleep(1)

        self.log("    [x] Không lấy được recaptchaToken mới", "ERROR")
        return False

    def call_api(self, prompt: str = None, num_images: int = 1, image_inputs: Optional[List[Dict]] = None) -> Tuple[List[GeneratedImage], Optional[str]]:
        """
        Gọi API với captured tokens.
        Giống batch_generator.py - lấy payload từ browser mỗi lần.

        Args:
            prompt: Prompt (nếu None, dùng payload đã capture)
            num_images: Số ảnh cần tạo (mặc định 1)
            image_inputs: List of reference images [{name, inputType}]

        Returns:
            Tuple[list of GeneratedImage, error message]
        """
        if not self.captured_url:
            return [], "No URL captured"

        url = self.captured_url
        self.log(f"→ URL: {url[:80]}...")

        # Lấy payload gốc từ Chrome (giống batch_generator.py)
        original_payload = self.driver.run_js("return window._payload;")
        if not original_payload:
            return [], "No payload captured"

        # Sửa số ảnh trong payload - FORCE đúng số lượng
        # API dùng số lượng items trong array "requests", mỗi request = 1 ảnh
        try:
            payload_data = json.loads(original_payload)

            if "requests" in payload_data and payload_data["requests"]:
                old_count = len(payload_data["requests"])
                if old_count > num_images:
                    # Chỉ giữ lại num_images requests đầu tiên
                    payload_data["requests"] = payload_data["requests"][:num_images]
                    self.log(f"   → requests: {old_count} → {num_images}")
                elif old_count < num_images:
                    self.log(f"   → requests: {old_count} (giữ nguyên, không đủ để tăng)")
                else:
                    self.log(f"   → requests: {old_count} (đã đúng)")

                # === INJECT imageInputs cho reference images ===
                if image_inputs:
                    for req in payload_data["requests"]:
                        req["imageInputs"] = image_inputs
                    self.log(f"   → Injected {len(image_inputs)} reference image(s) into payload")

            original_payload = json.dumps(payload_data)
        except Exception as e:
            self.log(f"[WARN] Không sửa được payload: {e}", "WARN")

        # Headers
        headers = {
            "Authorization": self.bearer_token,
            "Content-Type": "text/plain;charset=UTF-8",
            "Origin": "https://labs.google",
            "Referer": "https://labs.google/",
        }
        if self.x_browser_validation:
            headers["x-browser-validation"] = self.x_browser_validation

        self.log(f"→ Calling API with captured payload ({len(original_payload)} chars)...")

        try:
            # API call qua proxy bridge (127.0.0.1:port) để IP match với Chrome
            # QUAN TRỌNG: Dùng bridge URL, KHÔNG dùng proxy trực tiếp (sẽ bị 407)
            proxies = None
            if self._use_webshare and hasattr(self, '_bridge_port') and self._bridge_port:
                bridge_url = f"http://127.0.0.1:{self._bridge_port}"
                proxies = {"http": bridge_url, "https": bridge_url}
                self.log(f"→ Using proxy bridge: {bridge_url}")

            resp = requests.post(
                url,
                headers=headers,
                data=original_payload,
                timeout=120,
                proxies=proxies
            )

            if resp.status_code == 200:
                return self._parse_response(resp.json()), None
            else:
                error = f"{resp.status_code}: {resp.text[:200]}"
                self.log(f"[x] API Error: {error}", "ERROR")
                return [], error

        except Exception as e:
            self.log(f"[x] Request error: {e}", "ERROR")
            return [], str(e)

    def _parse_response(self, data: Dict) -> List[GeneratedImage]:
        """Parse API response để lấy images."""
        images = []

        for media_item in data.get("media", data.get("images", [])):
            if isinstance(media_item, dict):
                gen_image = media_item.get("image", {}).get("generatedImage", media_item)
                img = GeneratedImage()

                # Base64 encoded image
                if gen_image.get("encodedImage"):
                    img.base64_data = gen_image["encodedImage"]

                # URL
                if gen_image.get("fifeUrl"):
                    img.url = gen_image["fifeUrl"]

                # Media name (for video generation) - check multiple locations
                img.media_name = (
                    media_item.get("name") or
                    media_item.get("mediaName") or
                    gen_image.get("name") or
                    gen_image.get("mediaName") or
                    ""
                )

                # Seed
                if gen_image.get("seed"):
                    img.seed = gen_image["seed"]

                if img.base64_data or img.url:
                    images.append(img)

        self.log(f"[v] Parsed {len(images)} images")
        return images

    def generate_image_forward(
        self,
        prompt: str,
        num_images: int = 1,
        image_inputs: Optional[List[Dict]] = None,
        timeout: int = 60,
        force_model: str = ""
    ) -> Tuple[List[GeneratedImage], Optional[str]]:
        """
        Generate image bằng MODIFY MODE - giữ nguyên Chrome's payload.

        Flow:
        1. Type FULL prompt vào Chrome textarea
        2. Chrome tạo payload với model mới nhất + prompt enhancement + reCAPTCHA
        3. Interceptor chỉ THÊM imageInputs (nếu có) vào payload
        4. Forward request với tất cả settings gốc của Chrome
        5. Capture response

        Ưu điểm so với Custom Payload:
        - Dùng model mới nhất của Google (không hardcode GEM_PIX)
        - Giữ prompt enhancement của Chrome
        - Giữ tất cả settings/parameters của Chrome
        - Chất lượng ảnh tốt hơn

        Args:
            prompt: Prompt mô tả ảnh
            num_images: Số ảnh cần tạo
            image_inputs: Reference images [{name, inputType}] với name = media_id
            timeout: Timeout đợi response (giây)
            force_model: Force model name (GEM_PIX_2, IMAGEN_4, etc.)
                         "" = không force, "auto" = auto-detect và force nếu cần

        Returns:
            Tuple[list of GeneratedImage, error message]
        """
        if not self._ready:
            return [], "API chưa setup! Gọi setup() trước."

        # 1. Reset state
        self.driver.run_js("""
            window._response = null;
            window._responseError = null;
            window._requestPending = false;
            window._modifyConfig = null;
        """)

        # 2. MODIFY MODE: Luôn set imageCount=1, thêm imageInputs nếu có
        # Chrome sẽ dùng model mới nhất, prompt enhancement, tất cả settings
        modify_config = {
            "imageCount": num_images if num_images else 1  # Luôn giới hạn số ảnh
        }

        # Force model nếu được chỉ định (đảm bảo dùng Nano Banana Pro = GEM_PIX_2)
        if force_model:
            if force_model.lower() == "auto":
                # Auto-detect và force nếu Chrome không dùng model tốt
                modify_config["forceModel"] = True
                modify_config["forceModelName"] = "GEM_PIX_2"
                self.log("→ FORCE MODEL: auto (GEM_PIX_2 if needed)")
            elif force_model.lower() == "always":
                # Luôn force model
                modify_config["forceModel"] = "always"
                modify_config["forceModelName"] = "GEM_PIX_2"
                self.log("→ FORCE MODEL: always (GEM_PIX_2)")
            else:
                # Force model cụ thể
                modify_config["forceModel"] = "always"
                modify_config["forceModelName"] = force_model
                self.log(f"→ FORCE MODEL: {force_model}")

        if image_inputs and len(image_inputs) > 0:
            modify_config["imageInputs"] = image_inputs
            self.driver.run_js(f"window._modifyConfig = {json.dumps(modify_config)};")
            self.log(f"→ MODIFY MODE: {len(image_inputs)} reference image(s), {modify_config['imageCount']} image(s)")
            # Log chi tiết từng reference
            for idx, img_inp in enumerate(image_inputs):
                self.log(f"   [IMG_INPUT #{idx+1}] name={img_inp.get('name', 'N/A')[:40]}..., type={img_inp.get('imageInputType', 'N/A')}")
        else:
            self.driver.run_js(f"window._modifyConfig = {json.dumps(modify_config)};")
            self.log(f"→ MODIFY MODE: {modify_config['imageCount']} image(s), no reference")

        # 3. Tìm textarea và nhập prompt bằng Ctrl+V (tránh bot detection)
        self.log(f"→ Prompt: {prompt[:50]}...")
        textarea = self._find_textarea()
        if not textarea:
            return [], "Không tìm thấy textarea"

        # Paste prompt bằng Ctrl+V (như thủ công)
        self._paste_prompt_ctrlv(textarea, prompt)

        # Đợi 2 giây để reCAPTCHA chuẩn bị token
        time.sleep(2)

        # Nhấn Enter để gửi
        textarea.input('\n')
        self.log("→ Pressed Enter to send")
        self.log("→ Chrome đang gửi request...")

        # 4. Đợi response từ browser (không gọi API riêng!)
        start_time = time.time()
        while time.time() - start_time < timeout:
            result = self.driver.run_js("""
                return {
                    pending: window._requestPending,
                    response: window._response,
                    error: window._responseError
                };
            """)

            if result.get('error'):
                error_msg = result['error']
                self.log(f"[x] Browser request error: {error_msg}", "ERROR")
                return [], error_msg

            if result.get('response'):
                response_data = result['response']

                # Check for API errors in response
                if isinstance(response_data, dict):
                    if response_data.get('error'):
                        error_info = response_data['error']
                        error_msg = f"{error_info.get('code', 'unknown')}: {error_info.get('message', str(error_info))}"
                        self.log(f"[x] API Error: {error_msg}", "ERROR")
                        return [], error_msg

                    # Parse successful response
                    images = self._parse_response(response_data)
                    self.log(f"[v] Got {len(images)} images from browser!")

                    # DEBUG: Log URL của từng ảnh
                    for idx, img in enumerate(images):
                        self.log(f"   [IMG {idx}] url={img.url[:60] if img.url else 'None'}...")

                    # Clear modifyConfig for next request
                    self.driver.run_js("window._modifyConfig = null;")

                    # Đợi 3 giây để reCAPTCHA có thời gian regenerate token mới
                    # Nếu không đợi, request tiếp theo sẽ bị 403
                    self.log(f"[DEBUG] Sleeping 3s for reCAPTCHA...")
                    time.sleep(3)
                    self.log(f"[DEBUG] Returning {len(images)} images from generate_image_forward")

                    return images, None

            # Still pending or no response yet
            time.sleep(0.5)

        self.log("[x] Timeout đợi response từ browser", "ERROR")
        return [], "Timeout waiting for browser response"

    def generate_image(
        self,
        prompt: str,
        save_dir: Optional[Path] = None,
        filename: str = None,
        max_retries: int = 3,
        image_inputs: Optional[List[Dict]] = None,
        force_model: str = ""
    ) -> Tuple[bool, List[GeneratedImage], Optional[str]]:
        """
        Generate image - full flow với retry khi gặp 403.

        Args:
            prompt: Prompt mô tả ảnh
            save_dir: Thư mục lưu ảnh (optional)
            filename: Tên file (không có extension)
            max_retries: Số lần retry khi gặp 403 (mặc định 3)
            image_inputs: List of reference images [{name, inputType}]
            force_model: Force model name (GEM_PIX_2, IMAGEN_4, etc.)
                         "" = không force, "auto" = auto-detect

        Returns:
            Tuple[success, list of images, error]
        """
        if not self._ready:
            return False, [], "API chưa setup! Gọi setup() trước."

        # Chọn mode "Tạo hình ảnh" nếu chưa chọn
        if not getattr(self, '_image_mode_selected', False):
            self.log("[Image] Chọn mode 'Tạo hình ảnh'...")
            if self.switch_to_image_mode():
                self._image_mode_selected = True
                self.log("[Image] [v] Đã chọn Image mode")
                time.sleep(0.5)
            else:
                self.log("[Image] [WARN] Không chọn được mode, thử tiếp...", "WARN")

        # Nếu đang dùng fallback model (do quota), override force_model
        if self._use_fallback_model:
            force_model = "GEM_PIX"
            self.log(f"→ FORCE MODEL: GEM_PIX (fallback mode)")

        last_error = None

        # Số lần retry cho 403 (cần nhiều hơn để đi qua: reset x2 → clear data → IPv6 rotation)
        effective_max_retries = max_retries

        # Log reference images if provided
        if image_inputs:
            self.log(f"→ Using {len(image_inputs)} reference image(s)")

        attempt = 0
        while attempt < effective_max_retries:
            # SỬ DỤNG FORWARD MODE - không cancel request
            # reCAPTCHA token được dùng ngay (0.05s không bị expired)
            images, error = self.generate_image_forward(
                prompt=prompt,
                num_images=1,
                image_inputs=image_inputs,
                timeout=90,
                force_model=force_model
            )

            if error:
                last_error = error

                # === ERROR 253/429: Quota exceeded ===
                # Chuyển sang nano banana và tiếp tục (quota sẽ hết sau 1 lúc)
                if "253" in error or "429" in error or "quota" in error.lower() or "exceeds" in error.lower():

                    # Luôn chuyển sang nano banana khi gặp quota (nếu chưa)
                    if not self._use_fallback_model:
                        self.switch_to_fallback_model()
                        force_model = "GEM_PIX"  # Override cho các lần retry sau

                    # Retry với nano banana: đợi 5s → F5 refresh → retry
                    if attempt < effective_max_retries - 1:
                        self.log(f"[WARN] 429 Quota - Đợi 5s, F5 refresh rồi retry...", "WARN")
                        time.sleep(5)
                        # F5 refresh page
                        try:
                            self.driver.refresh()
                            time.sleep(3)  # Đợi page load
                            self.log(f"  → F5 refreshed, retry...")
                        except Exception as e:
                            self.log(f"  → Refresh failed: {e}", "WARN")
                        attempt += 1
                        continue

                    # Hết retry trong hàm này, nhưng KHÔNG return False
                    # Để caller có thể retry tiếp với scene tiếp theo
                    self.log(f"[WARN] 429 sau {max_retries} lần, tiếp tục scene tiếp...", "WARN")
                    return False, [], f"429 quota - tiếp tục với scene tiếp theo"

                # Nếu lỗi 500 (Internal Error), retry với delay
                if "500" in error:
                    self.log(f"[WARN] 500 Internal Error (attempt {attempt+1}/{effective_max_retries})", "WARN")
                    if attempt < effective_max_retries - 1:
                        self.log(f"  → Đợi 3s rồi retry...")
                        time.sleep(3)
                        attempt += 1
                        continue
                    else:
                        return False, [], error

                # === 400 ERROR: Policy violation (prompt bị cấm) ===
                # Retry 1 lần, nếu vẫn 400 thì skip prompt này
                if "400" in error:
                    policy_retry_count = getattr(self, '_policy_retry_count', 0)
                    if policy_retry_count < 1:
                        self._policy_retry_count = policy_retry_count + 1
                        self.log(f"[WARN] 400 Policy Violation - Prompt vi phạm! Retry lần {policy_retry_count + 1}...", "WARN")
                        time.sleep(2)
                        attempt += 1
                        continue
                    else:
                        # Reset counter và skip prompt này
                        self._policy_retry_count = 0
                        self.log(f"[WARN] 400 Policy Violation - SKIP prompt này!", "WARN")
                        return False, [], "POLICY_VIOLATION: Prompt bị cấm, skip"

                # === 403 ERROR HANDLING ===
                # Logic MỚI (cho 2 Chrome parallel):
                # 1. 403 → Reset Chrome (2 lần)
                # 2. Lần 3 → Clear data + login lại
                # 3. Sau clear vẫn 403 → Mark ready_for_rotation
                # 4. CHỈ đổi IPv6 khi CẢ 2 CHROME đều ready!
                if "403" in error:
                    self._consecutive_403 += 1
                    cleared_flag = getattr(self, '_cleared_data_for_403', False)

                    # Get shared tracker
                    try:
                        from modules.shared_403_tracker import get_403_tracker
                        tracker = get_403_tracker(total_workers=self.total_workers)
                        tracker.mark_403(self.worker_id)
                    except Exception as e:
                        self.log(f"[403] Tracker error: {e}", "WARN")
                        tracker = None

                    if self._consecutive_403 < 3 and not cleared_flag:
                        # Bước 1: Reset Chrome (lần 1 và 2)
                        self.log(f"[WARN] 403 error (lần {self._consecutive_403}/3) - RESET CHROME!", "WARN")
                        self._kill_chrome()
                        self.close()
                        time.sleep(2)

                    elif self._consecutive_403 >= 3 and not cleared_flag:
                        # Bước 2: Lần 3 → XÓA TRIỆT ĐỂ PROFILE + đăng nhập lại
                        self.log(f"[WARN] 403 lần {self._consecutive_403} → RESET PROFILE + ĐĂNG NHẬP LẠI!", "WARN")
                        # Dùng reset_chrome_profile() - xóa hoàn toàn thư mục profile
                        self.reset_chrome_profile()
                        time.sleep(1)
                        # Login lại (sẽ tự khởi động Chrome mới)
                        self._auto_login_google()
                        self._cleared_data_for_403 = True
                        self._consecutive_403 = 0  # Reset counter sau khi clear

                        # Mark cleared data in shared tracker
                        if tracker:
                            tracker.mark_cleared_data(self.worker_id)

                    else:
                        # Bước 3: Đã clear data vẫn 403
                        self.log(f"[WARN] 403 sau khi clear data (worker {self.worker_id})", "WARN")

                        # Mark ready for rotation in shared tracker
                        if tracker:
                            tracker.mark_ready_for_rotation(self.worker_id)

                            # CHỈ đổi IPv6 khi CẢ 2 workers đều ready
                            if tracker.should_rotate_ipv6(self.worker_id):
                                self.log(f"  → [NET] CẢ {self.total_workers} Chrome đều ready → ĐỔI IPv6!", "WARN")
                                self._cleared_data_for_403 = False
                                self._consecutive_403 = 0

                                # CHỈ Chrome 1 (worker_id=0) rotate IPv6
                                if self.worker_id == 0 and self._ipv6_rotator and self._ipv6_activated:
                                    new_ip = self._ipv6_rotator.rotate()
                                    if new_ip:
                                        self.log(f"  → [NET] IPv6 mới: {new_ip}")
                                        if hasattr(self, '_ipv6_proxy') and self._ipv6_proxy:
                                            self._ipv6_proxy.set_ipv6(new_ip)
                                    else:
                                        self.log(f"  → [WARN] Không rotate được IPv6!", "WARN")

                                # Reset all workers after rotation
                                tracker.reset_after_rotation()
                            else:
                                # Chưa đủ workers ready → đợi và retry
                                self.log(f"  → [WAIT] Đợi Chrome khác cũng ready... (tiếp tục retry)", "WARN")
                                self._cleared_data_for_403 = False  # Reset để thử lại flow
                                self._consecutive_403 = 0
                        else:
                            # No tracker → fallback to old behavior
                            self.log(f"[WARN] 403 sau khi clear data → ĐỔI IPv6!", "WARN")
                            self._cleared_data_for_403 = False
                            self._consecutive_403 = 0

                            # CHỈ Chrome 1 (worker_id=0) rotate IPv6
                            if self.worker_id == 0 and self._ipv6_rotator and self._ipv6_activated:
                                new_ip = self._ipv6_rotator.rotate()
                                if new_ip:
                                    self.log(f"  → [NET] IPv6 mới: {new_ip}")
                                    if hasattr(self, '_ipv6_proxy') and self._ipv6_proxy:
                                        self._ipv6_proxy.set_ipv6(new_ip)
                                else:
                                    self.log(f"  → [WARN] Không rotate được IPv6!", "WARN")

                    # Extend retries để đủ cho cả flow: reset x2 → clear data → IPv6 rotation
                    if effective_max_retries < 6:
                        effective_max_retries = 6
                        self.log(f"  → Extend retries to {effective_max_retries} for 403 handling")

                    # Restart Chrome
                    if self.restart_chrome(rotate_ipv6=False):
                        self.log("  → Chrome restarted, tiếp tục...")
                        attempt += 1
                        continue
                    else:
                        return False, [], "Không restart được Chrome sau 403"

                # === TIMEOUT ERROR: Restart Chrome và retry ===
                if "timeout" in error.lower():
                    self.log(f"[WARN] Timeout (attempt {attempt+1}/{effective_max_retries}) - RESTART CHROME!", "WARN")

                    # Đổi proxy nếu có
                    if self._use_webshare and self._webshare_proxy:
                        success_rotate, msg = self._webshare_proxy.rotate_ip(self.worker_id, "Timeout")
                        self.log(f"  → Webshare rotate: {msg}", "WARN")

                    # Retry nếu còn lượt
                    if attempt < effective_max_retries - 1:
                        if self.restart_chrome():
                            attempt += 1
                            continue
                        else:
                            return False, [], "Không restart được Chrome sau timeout"

                    return False, [], f"Timeout sau {effective_max_retries} lần retry"

                # Lỗi khác, không retry
                return False, [], error

            if not images:
                return False, [], "Không có ảnh trong response"

            # Thành công!
            break
        else:
            return False, [], last_error or "Max retries exceeded"

        # 3. Download và save nếu cần
        self.log(f"[DEBUG] Starting download phase, save_dir={save_dir}")
        if save_dir:
            save_dir = Path(save_dir)
            save_dir.mkdir(parents=True, exist_ok=True)

            for i, img in enumerate(images):
                self.log(f"[DEBUG] Processing image {i}: has_base64={bool(img.base64_data)}, has_url={bool(img.url)}")
                fname = filename or f"image_{int(time.time())}"
                if len(images) > 1:
                    fname = f"{fname}_{i+1}"

                if img.base64_data:
                    img_path = save_dir / f"{fname}.png"
                    img_path.write_bytes(base64.b64decode(img.base64_data))
                    img.local_path = img_path
                    self.log(f"[v] Saved: {img_path.name}")
                elif img.url:
                    # Download image bằng cách mở tab mới trong Chrome
                    dl_start = time.time()
                    self.log(f"→ Opening image in new tab...")
                    downloaded = False
                    image_tab = None

                    if self.driver and not downloaded:
                        try:
                            # Lưu tab hiện tại (tab chính) - dùng get_tab()
                            original_tab = self.driver.get_tab()

                            # Mở tab mới với URL ảnh - new_tab trả về tab object
                            image_tab = self.driver.new_tab(img.url)
                            image_tab.set.activate()  # Switch sang tab mới
                            time.sleep(2)  # Đợi ảnh load

                            # Đợi ảnh load xong (tối đa 10s)
                            for _ in range(20):
                                img_loaded = image_tab.run_js('''
                                    const img = document.querySelector('img');
                                    return img && img.complete && img.naturalWidth > 0;
                                ''')
                                if img_loaded:
                                    break
                                time.sleep(0.5)

                            # Convert ảnh sang base64 qua canvas
                            result = image_tab.run_js('''
                                const img = document.querySelector('img');
                                if (!img || !img.complete) return { error: "Image not found or not loaded" };

                                const canvas = document.createElement('canvas');
                                canvas.width = img.naturalWidth;
                                canvas.height = img.naturalHeight;
                                const ctx = canvas.getContext('2d');
                                ctx.drawImage(img, 0, 0);

                                try {
                                    const dataUrl = canvas.toDataURL('image/png');
                                    return {
                                        base64: dataUrl.split(',')[1],
                                        width: img.naturalWidth,
                                        height: img.naturalHeight
                                    };
                                } catch(e) {
                                    return { error: e.toString() };
                                }
                            ''')

                            chrome_time = time.time() - dl_start

                            # Đóng tab ảnh, quay về tab chính
                            image_tab.close()  # Đóng tab ảnh
                            original_tab.set.activate()  # Về tab chính

                            if result and result.get('base64'):
                                img.base64_data = result['base64']
                                img_path = save_dir / f"{fname}.png"
                                img_path.write_bytes(base64.b64decode(img.base64_data))
                                img.local_path = img_path
                                w, h = result.get('width', 0), result.get('height', 0)
                                self.log(f"[v] Downloaded: {img_path.name} ({w}x{h}, {chrome_time:.2f}s)")
                                downloaded = True
                            elif result and result.get('error'):
                                self.log(f"   [DEBUG] Chrome tab error: {result['error']}")
                        except Exception as e:
                            self.log(f"   [DEBUG] Chrome tab exception: {e}")
                            # Đảm bảo đóng tab ảnh nếu có lỗi
                            try:
                                if image_tab:
                                    image_tab.close()
                            except:
                                pass

                    # Fallback to requests nếu Chrome fail
                    if not downloaded:
                        try:
                            self.log(f"   Fallback to requests...")
                            resp = requests.get(img.url, timeout=120)
                            req_time = time.time() - dl_start
                            if resp.status_code == 200:
                                img_path = save_dir / f"{fname}.png"
                                img_path.write_bytes(resp.content)
                                img.local_path = img_path
                                img.base64_data = base64.b64encode(resp.content).decode()
                                self.log(f"[v] Downloaded: {img_path.name} ({len(resp.content)} bytes, {req_time:.2f}s)")
                                downloaded = True
                        except Exception as e:
                            self.log(f"[x] Download failed: {e}", "WARN")

        # Restart Chrome sau mỗi ảnh (giống như 403 reset)
        # restart_chrome() đã có sẵn: navigate + inject JS
        self.log("[SYNC] Restarting Chrome...")
        try:
            # Đóng Chrome
            self._kill_chrome()
            self.close()
            time.sleep(2)

            # Restart Chrome (setup() sẽ navigate + inject JS)
            if self.restart_chrome(rotate_ipv6=False):
                self.log("[v] Chrome restarted!")
            else:
                self.log("[WARN] Restart Chrome failed", "WARN")

        except Exception as e:
            self.log(f"[WARN] Restart error: {e}", "WARN")

        # Reset 403 counter khi thành công
        if self._consecutive_403 > 0 or getattr(self, '_cleared_data_for_403', False):
            self.log(f"[IPv6] Reset 403 counter (was {self._consecutive_403})")
            self._consecutive_403 = 0
            self._cleared_data_for_403 = False

            # Reset shared tracker for this worker
            try:
                from modules.shared_403_tracker import get_403_tracker
                tracker = get_403_tracker(total_workers=self.total_workers)
                tracker.reset_worker(self.worker_id)
            except:
                pass

            # Reset policy violation counter on success
            self._policy_retry_count = 0

        return True, images, None

    def generate_batch(
        self,
        prompts: List[str],
        save_dir: Path,
        on_progress: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        Generate batch nhiều ảnh.

        Args:
            prompts: Danh sách prompts
            save_dir: Thư mục lưu ảnh
            on_progress: Callback(index, total, success, error)

        Returns:
            Dict với thống kê
        """
        results = {
            "total": len(prompts),
            "success": 0,
            "failed": 0,
            "images": []
        }

        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

        for i, prompt in enumerate(prompts):
            self.log(f"\n[{i+1}/{len(prompts)}] {prompt[:50]}...")

            # FORWARD MODE: Không cancel request, reCAPTCHA token còn fresh
            images, error = self.generate_image_forward(
                prompt=prompt,
                num_images=1,
                timeout=90
            )

            if error:
                results["failed"] += 1
                if on_progress:
                    on_progress(i+1, len(prompts), False, error)

                # Token hết hạn → dừng
                if "401" in error:
                    self.log("Bearer token hết hạn!", "ERROR")
                    break
                continue

            if images:
                # Save images
                for j, img in enumerate(images):
                    fname = f"batch_{i+1:03d}_{j+1}"
                    if img.base64_data:
                        img_path = save_dir / f"{fname}.png"
                        img_path.write_bytes(base64.b64decode(img.base64_data))
                        img.local_path = img_path

                results["success"] += 1
                results["images"].extend(images)
                if on_progress:
                    on_progress(i+1, len(prompts), True, None)
            else:
                results["failed"] += 1
                if on_progress:
                    on_progress(i+1, len(prompts), False, "No images")

            time.sleep(1)  # Rate limit

        self.log(f"\n{'='*50}")
        self.log(f"DONE: {results['success']}/{results['total']}")
        return results

    def generate_video(
        self,
        media_id: str,
        prompt: str = "Subtle motion, cinematic, slow movement",
        aspect_ratio: str = "VIDEO_ASPECT_RATIO_LANDSCAPE",
        video_model: str = "veo_3_1_r2v_fast_landscape_ultra_relaxed",
        max_wait: int = 180,
        max_retries: int = 3
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Tạo video từ ảnh (I2V) - CÓ RETRY VỚI 403/QUOTA HANDLING như generate_image.

        Args:
            media_id: Media ID của ảnh (từ generate_image)
            prompt: Prompt mô tả chuyển động
            aspect_ratio: Tỷ lệ video
            video_model: Model video (fast hoặc quality)
            max_wait: Thời gian chờ tối đa (giây)
            max_retries: Số lần retry khi gặp 403/quota (mặc định 3)

        Returns:
            Tuple[success, video_url, error]
        """
        if not self._ready:
            return False, None, "API chưa setup! Gọi setup() trước."

        if not media_id:
            return False, None, "Media ID không được để trống"

        self.log(f"[I2V] Creating video from media: {media_id[:50]}...")

        last_error = None

        for attempt in range(max_retries):
            # === QUAN TRỌNG: Capture/Refresh tokens mỗi lần retry ===
            if hasattr(self, 'driver') and self.driver:
                if not self.bearer_token or not self.project_id:
                    self.log("[I2V] Capturing full tokens (bearer, project_id, recaptcha)...")
                    capture_prompt = prompt[:30] if len(prompt) > 30 else prompt
                    if self._capture_tokens(capture_prompt):
                        self.log("[I2V] [v] Got all tokens!")
                    else:
                        self.log("[I2V] [WARN] Không capture được tokens", "WARN")
                        return False, None, "Không capture được tokens từ Chrome"
                else:
                    self.log("[I2V] Refreshing recaptcha token...")
                    if self.refresh_recaptcha(prompt[:30] if len(prompt) > 30 else prompt):
                        self.log("[I2V] [v] Got fresh recaptcha token")
                    else:
                        self.log("[I2V] [WARN] Không refresh được recaptcha", "WARN")
            else:
                self.log("[I2V] Token mode - dùng cached recaptcha")

            # Build request payload
            import uuid
            session_id = f";{int(time.time() * 1000)}"
            scene_id = str(uuid.uuid4())
            recaptcha = getattr(self, 'recaptcha_token', '') or ''

            request_data = {
                "aspectRatio": aspect_ratio,
                "metadata": {"sceneId": scene_id},
                "referenceImages": [{
                    "imageUsageType": "IMAGE_USAGE_TYPE_ASSET",
                    "mediaId": media_id
                }],
                "seed": int(time.time()) % 100000,
                "textInput": {"prompt": prompt},
                "videoModelKey": video_model
            }

            payload = {
                "clientContext": {
                    "projectId": self.project_id,
                    "recaptchaToken": recaptcha,
                    "sessionId": session_id,
                    "tool": "PINHOLE",
                    "userPaygateTier": "PAYGATE_TIER_TWO"
                },
                "requests": [request_data]
            }

            self.log(f"[I2V] recaptchaToken: {'có' if recaptcha else 'KHÔNG CÓ!'}")

            # Video API - project_id trong payload, KHÔNG trong URL
            url = "https://aisandbox-pa.googleapis.com/v1/video:batchAsyncGenerateVideoReferenceImages"

            headers = {
                "Authorization": self.bearer_token,
                "Content-Type": "application/json",
                "Origin": "https://labs.google",
                "Referer": "https://labs.google/",
            }
            if self.x_browser_validation:
                headers["x-browser-validation"] = self.x_browser_validation

            self.log(f"[I2V] Calling video API (attempt {attempt+1}/{max_retries})...")

            try:
                proxies = None
                if self._use_webshare and hasattr(self, '_bridge_port') and self._bridge_port:
                    bridge_url = f"http://127.0.0.1:{self._bridge_port}"
                    proxies = {"http": bridge_url, "https": bridge_url}

                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=60,
                    proxies=proxies
                )

                if resp.status_code != 200:
                    error = f"{resp.status_code}: {resp.text[:200]}"
                    last_error = error
                    self.log(f"[I2V] API Error: {error}", "ERROR")

                    # Project URL cho retry - dùng project_id hiện tại
                    retry_project_url = f"https://labs.google/fx/vi/tools/flow/project/{self.project_id}"

                    # === ERROR 253/403: Quota exceeded ===
                    if "253" in error or "quota" in error.lower() or "exceeds" in error.lower():
                        self.log(f"[I2V] [WARN] QUOTA EXCEEDED - Đổi proxy...", "WARN")

                        self.close()  # Chỉ close driver, không kill hết Chrome

                        if self._use_webshare and self._webshare_proxy:
                            success, msg = self._webshare_proxy.rotate_ip(self.worker_id, "I2V 253 Quota")
                            self.log(f"[I2V] → Webshare rotate: {msg}", "WARN")

                            if success and attempt < max_retries - 1:
                                self.log("[I2V] → Mở Chrome mới với proxy mới...")
                                time.sleep(3)
                                if self.setup(project_url=retry_project_url):
                                    continue
                                else:
                                    return False, None, "Không setup được Chrome mới sau khi đổi proxy"

                        if attempt < max_retries - 1:
                            self.log("[I2V] → Đợi 30s rồi thử lại...", "WARN")
                            time.sleep(30)
                            if self.setup(project_url=retry_project_url):
                                continue
                        return False, None, f"Quota exceeded sau {max_retries} lần thử"

                    # === 403 error - RESET CHROME NGAY ===
                    if "403" in error:
                        # Tăng counter 403 liên tiếp
                        self._consecutive_403 += 1
                        self.log(f"[I2V] [WARN] 403 error (lần {self._consecutive_403}/{self._max_403_before_ipv6}) - RESET CHROME!", "WARN")

                        # Kill Chrome
                        self._kill_chrome()
                        self.close()
                        time.sleep(2)

                        # Đổi proxy nếu có
                        if self._use_webshare and self._webshare_proxy:
                            success, msg = self._webshare_proxy.rotate_ip(self.worker_id, "I2V 403")
                            self.log(f"[I2V] → Webshare rotate: {msg}", "WARN")

                        # === IPv6: Sau N lần 403 liên tiếp, ACTIVATE hoặc ROTATE IPv6 ===
                        # CHỈ Chrome 1 (worker_id=0) mới activate/rotate IPv6
                        rotate_ipv6 = False
                        if self._consecutive_403 >= self._max_403_before_ipv6 and self.worker_id == 0:
                            self._consecutive_403 = 0  # Reset counter

                            if not self._ipv6_activated:
                                # Lần đầu: Activate IPv6
                                self.log(f"[I2V] → [NET] ACTIVATE IPv6 MODE (lần đầu)...")
                                self._activate_ipv6()
                            else:
                                # Đã activate: Rotate sang IP khác
                                self.log(f"[I2V] → [SYNC] Rotate sang IPv6 khác...")
                                rotate_ipv6 = True
                        elif self._consecutive_403 >= self._max_403_before_ipv6:
                            self.log(f"[Worker{self.worker_id}] Skip IPv6 (Chrome 1 quản lý)")
                            self._consecutive_403 = 0

                        # Restart Chrome (có thể kèm IPv6 rotation)
                        if self.restart_chrome(rotate_ipv6=rotate_ipv6):
                            self.log("[I2V] → Chrome restarted, tiếp tục...")
                            continue  # Thử lại 1 lần sau khi reset
                        else:
                            return False, None, "Không restart được Chrome sau 403"

                    # Other errors - simple retry
                    if attempt < max_retries - 1:
                        self.log(f"[I2V] → Retry in 5s...", "WARN")
                        time.sleep(5)
                        continue
                    return False, None, error

                result = resp.json()

                # Log full response để debug
                self.log(f"[I2V] Full response keys: {list(result.keys())}")
                self.log(f"[I2V] Response: {json.dumps(result)[:500]}")

                # Giống image gen - check nếu có video trực tiếp trong response
                # (không cần poll như image gen)
                if "media" in result or "generatedVideos" in result:
                    videos = result.get("generatedVideos", result.get("media", []))
                    if videos:
                        video_url = videos[0].get("video", {}).get("fifeUrl") or videos[0].get("fifeUrl")
                        if video_url:
                            self.log(f"[I2V] [v] Video ready (no poll): {video_url[:60]}...")
                            # Reset 403 counter khi thành công
                            if self._consecutive_403 > 0:
                                self.log(f"[IPv6] Reset 403 counter (was {self._consecutive_403})")
                                self._consecutive_403 = 0
                            return True, video_url, None

                operations = result.get("operations", [])

                if not operations:
                    if attempt < max_retries - 1:
                        time.sleep(5)
                        continue
                    return False, None, "No operations/videos in response"

                self.log(f"[I2V] Got {len(operations)} operations, polling for result...")

                op = operations[0]
                self.log(f"[I2V] Operation status: {op.get('status', 'unknown')}")

                # Truyền full operation data cho poll (không chỉ operation_id)
                video_url = self._poll_video_operation(op, headers, proxies, max_wait)

                if video_url:
                    self.log(f"[I2V] Video ready: {video_url[:60]}...")
                    # Reset 403 counter khi thành công
                    if self._consecutive_403 > 0:
                        self.log(f"[IPv6] Reset 403 counter (was {self._consecutive_403})")
                        self._consecutive_403 = 0
                    return True, video_url, None
                else:
                    last_error = "Timeout waiting for video"
                    if attempt < max_retries - 1:
                        self.log("[I2V] → Timeout, will retry...", "WARN")
                        continue
                    return False, None, last_error

            except Exception as e:
                last_error = str(e)
                self.log(f"[I2V] Error: {e}", "ERROR")

                # Project URL cho retry
                retry_project_url = f"https://labs.google/fx/vi/tools/flow/project/{self.project_id}"

                # Check if exception contains 403/quota error
                if "253" in last_error or "quota" in last_error.lower() or "403" in last_error:
                    self.log("[I2V] [WARN] Exception with 403/quota - Đổi proxy...", "WARN")
                    self.close()  # Chỉ close driver

                    if self._use_webshare and self._webshare_proxy:
                        success, msg = self._webshare_proxy.rotate_ip(self.worker_id, "I2V Exception")
                        self.log(f"[I2V] → Webshare rotate: {msg}", "WARN")

                        if success and attempt < max_retries - 1:
                            time.sleep(3)
                            if self.setup(project_url=retry_project_url):
                                continue

                if attempt < max_retries - 1:
                    time.sleep(5)
                    continue
                return False, None, last_error

        return False, None, last_error or "Failed after all retries"

    def generate_video_chrome(
        self,
        media_id: str,
        prompt: str = "Subtle motion, cinematic, slow movement",
        aspect_ratio: str = "VIDEO_ASPECT_RATIO_LANDSCAPE",
        video_model: str = "veo_3_1_r2v_fast_landscape_ultra_relaxed",
        max_wait: int = 180,
        save_path: Optional[Path] = None,
        max_retries: int = 3
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Tạo video từ ảnh (I2V) sử dụng FORCE MODE.
        Có retry và xử lý 403 + IPv6 như generate_image.

        Flow (FORCE MODE - không cần chuyển mode):
        1. Ở nguyên mode "Tạo hình ảnh"
        2. Set _forceVideoPayload với video config + media_id
        3. Gửi prompt như tạo ảnh
        4. Interceptor convert image request → video request
        5. Chrome gửi VIDEO request với fresh reCAPTCHA
        6. Poll và download video

        Args:
            media_id: Media ID của ảnh đã tạo (từ generate_image)
            prompt: Prompt mô tả chuyển động video
            aspect_ratio: Tỷ lệ video (landscape/portrait/square)
            video_model: Model video (fast/quality)
            max_wait: Thời gian chờ tối đa (giây)
            save_path: Đường dẫn lưu video (optional)
            max_retries: Số lần retry khi gặp 403

        Returns:
            Tuple[success, video_url, error]
        """
        if not self._ready:
            return False, None, "API chưa setup! Gọi setup() trước."

        if not media_id:
            return False, None, "Media ID không được để trống"

        last_error = None

        for attempt in range(max_retries):
            # Thực hiện tạo video
            success, result, error = self._execute_video_chrome(
                media_id=media_id,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                video_model=video_model,
                max_wait=max_wait,
                save_path=save_path
            )

            if success:
                # Reset 403 counter khi thành công
                if self._consecutive_403 > 0:
                    self.log(f"[I2V-Chrome] Reset 403 counter (was {self._consecutive_403})")
                    self._consecutive_403 = 0
                return True, result, None

            if error:
                last_error = error

                # === 403 ERROR: RESET CHROME + IPv6 ===
                if "403" in str(error):
                    self._consecutive_403 += 1
                    self.log(f"[I2V-Chrome] [WARN] 403 error (lần {self._consecutive_403}/{self._max_403_before_ipv6}) - RESET CHROME!", "WARN")

                    # Kill Chrome
                    self._kill_chrome()
                    self.close()
                    time.sleep(2)

                    # Đổi proxy nếu có
                    if self._use_webshare and self._webshare_proxy:
                        success_rotate, msg = self._webshare_proxy.rotate_ip(self.worker_id, "I2V-Chrome 403")
                        self.log(f"[I2V-Chrome] → Webshare rotate: {msg}", "WARN")

                    # === IPv6: CHỈ Chrome 1 (worker_id=0) mới activate/rotate ===
                    rotate_ipv6 = False
                    if self._consecutive_403 >= self._max_403_before_ipv6 and self.worker_id == 0:
                        self._consecutive_403 = 0  # Reset counter

                        if not self._ipv6_activated:
                            self.log(f"[I2V-Chrome] → [NET] ACTIVATE IPv6 MODE (lần đầu)...")
                            self._activate_ipv6()
                        else:
                            self.log(f"[I2V-Chrome] → [SYNC] Rotate sang IPv6 khác...")
                            rotate_ipv6 = True
                    elif self._consecutive_403 >= self._max_403_before_ipv6:
                        self.log(f"[Worker{self.worker_id}] Skip IPv6 (Chrome 1 quản lý)")
                        self._consecutive_403 = 0

                    # Restart Chrome
                    if self.restart_chrome(rotate_ipv6=rotate_ipv6):
                        self.log("[I2V-Chrome] → Chrome restarted, tiếp tục...")
                        continue
                    else:
                        return False, None, "Không restart được Chrome sau 403"

                # === TIMEOUT ERROR ===
                if "timeout" in str(error).lower():
                    self.log(f"[I2V-Chrome] [WARN] Timeout error (attempt {attempt+1}/{max_retries}) - Reset Chrome...", "WARN")
                    self._kill_chrome()
                    self.close()
                    time.sleep(2)

                    if self._use_webshare and self._webshare_proxy:
                        success_rotate, msg = self._webshare_proxy.rotate_ip(self.worker_id, "I2V-Chrome Timeout")
                        self.log(f"[I2V-Chrome] → Webshare rotate: {msg}", "WARN")

                    if attempt < max_retries - 1:
                        if self.restart_chrome():
                            continue

                # === 500 ERROR ===
                if "500" in str(error):
                    self.log(f"[I2V-Chrome] [WARN] 500 Internal Error (attempt {attempt+1}/{max_retries})", "WARN")
                    if attempt < max_retries - 1:
                        time.sleep(3)
                        continue

                return False, None, error

        return False, None, last_error or "Max retries exceeded"

    def _execute_video_chrome(
        self,
        media_id: str,
        prompt: str,
        aspect_ratio: str,
        video_model: str,
        max_wait: int,
        save_path: Optional[Path]
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Thực hiện tạo video Chrome một lần (không retry).
        Được gọi bởi generate_video_chrome với retry logic.
        """
        self.log(f"[I2V-Chrome] Tạo video từ media: {media_id[:50]}...")
        self.log(f"[I2V-Chrome] Prompt: {prompt[:60]}...")

        # FORCE MODE: Không chuyển mode, ở nguyên "Tạo hình ảnh"
        self.log("[I2V-Chrome] FORCE MODE: Ở nguyên 'Tạo hình ảnh', Interceptor convert → video")

        # 1. Reset video state
        self.driver.run_js("""
            window._videoResponse = null;
            window._videoError = null;
            window._videoPending = false;
            window._forceVideoPayload = null;
        """)

        # 2. Chuẩn bị FORCE video payload với media_id
        import uuid
        session_id = f";{int(time.time() * 1000)}"
        scene_id = str(uuid.uuid4())

        video_payload = {
            "clientContext": {
                "projectId": self.project_id or "",
                "recaptchaToken": "",
                "sessionId": session_id,
                "tool": "PINHOLE",
                "userPaygateTier": "PAYGATE_TIER_TWO"
            },
            "requests": [{
                "aspectRatio": aspect_ratio,
                "metadata": {"sceneId": scene_id},
                "referenceImages": [{
                    "imageUsageType": "IMAGE_USAGE_TYPE_ASSET",
                    "mediaId": media_id
                }],
                "seed": int(time.time()) % 100000,
                "textInput": {"prompt": prompt},
                "videoModelKey": video_model
            }]
        }

        self.driver.run_js(f"window._forceVideoPayload = {json.dumps(video_payload)};")
        self.log(f"[I2V-Chrome] [v] FORCE payload ready (mediaId: {media_id[:40]}...)")

        # 3. Tìm textarea và nhập prompt
        textarea = self._find_textarea()
        if not textarea:
            return False, None, "Không tìm thấy textarea"

        self._paste_prompt_ctrlv(textarea, prompt)
        time.sleep(2)

        # 4. Gửi prompt - thử nhiều cách
        # Cách 1: Click nút gửi (nếu có) - giống người dùng nhất
        send_clicked = self.driver.run_js('''
            // Tìm nút gửi (thường là button gần textarea)
            var sendBtn = document.querySelector('button[aria-label*="Send"]')
                       || document.querySelector('button[aria-label*="send"]')
                       || document.querySelector('button[type="submit"]');
            if (sendBtn && !sendBtn.disabled) {
                sendBtn.click();
                return true;
            }
            return false;
        ''')

        if send_clicked:
            self.log("[I2V-Chrome] → Clicked send button")
        else:
            # Cách 2: Nhấn Enter bằng DrissionPage (native keyboard)
            textarea.input('\n')
            self.log("[I2V-Chrome] → Enter key pressed")

        self.log("[I2V-Chrome] → Interceptor converting IMAGE → VIDEO request...")

        # 5. Đợi video response từ browser
        start_time = time.time()
        timeout = 60

        while time.time() - start_time < timeout:
            result = self.driver.run_js("""
                return {
                    pending: window._videoPending,
                    response: window._videoResponse,
                    error: window._videoError
                };
            """)

            if result.get('error'):
                error_msg = result['error']
                self.log(f"[I2V-Chrome] [x] Request error: {error_msg}", "ERROR")
                return False, None, error_msg

            if result.get('response'):
                response_data = result['response']

                if isinstance(response_data, dict):
                    if response_data.get('error'):
                        error_info = response_data['error']
                        error_msg = f"{error_info.get('code', 'unknown')}: {error_info.get('message', str(error_info))}"
                        self.log(f"[I2V-Chrome] [x] API Error: {error_msg}", "ERROR")
                        return False, None, error_msg

                    if "media" in response_data or "generatedVideos" in response_data:
                        videos = response_data.get("generatedVideos", response_data.get("media", []))
                        if videos:
                            video_url = videos[0].get("video", {}).get("fifeUrl") or videos[0].get("fifeUrl")
                            if video_url:
                                self.log(f"[I2V-Chrome] [v] Video ready (no poll): {video_url[:60]}...")
                                return self._download_video_if_needed(video_url, save_path)

                    operations = response_data.get("operations", [])
                    if operations:
                        self.log(f"[I2V-Chrome] Got {len(operations)} operations, polling...")
                        op = operations[0]

                        headers = {
                            "Authorization": self.bearer_token,
                            "Content-Type": "application/json",
                            "Origin": "https://labs.google",
                            "Referer": "https://labs.google/",
                        }
                        if self.x_browser_validation:
                            headers["x-browser-validation"] = self.x_browser_validation

                        proxies = None
                        if self._use_webshare and hasattr(self, '_bridge_port') and self._bridge_port:
                            bridge_url = f"http://127.0.0.1:{self._bridge_port}"
                            proxies = {"http": bridge_url, "https": bridge_url}

                        video_url = self._poll_video_operation(op, headers, proxies, max_wait)

                        if video_url:
                            self.log(f"[I2V-Chrome] [v] Video ready: {video_url[:60]}...")
                            return self._download_video_if_needed(video_url, save_path)
                        else:
                            return False, None, "Timeout hoặc lỗi khi poll video"

                    return False, None, "Không có operations/videos trong response"

            time.sleep(0.5)

        self.log("[I2V-Chrome] [x] Timeout đợi response từ browser", "ERROR")
        return False, None, "Timeout waiting for video response"

    def _download_video_if_needed(
        self,
        video_url: str,
        save_path: Optional[Path]
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Download video nếu có save_path, trả về (success, url, error)."""
        download_success = False
        result_path = video_url

        if save_path:
            try:
                resp = requests.get(video_url, timeout=120)
                if resp.status_code == 200:
                    save_path.parent.mkdir(parents=True, exist_ok=True)
                    save_path.write_bytes(resp.content)
                    self.log(f"[I2V-Chrome] [v] Downloaded: {save_path.name}")
                    download_success = True
                    result_path = str(save_path)
                else:
                    self.log(f"[I2V-Chrome] Download error: HTTP {resp.status_code}", "ERROR")
                    return False, video_url, f"Download failed: HTTP {resp.status_code}"
            except Exception as e:
                self.log(f"[I2V-Chrome] Download error: {e}", "ERROR")
                return False, video_url, str(e)
        else:
            download_success = True

        # F5 refresh sau mỗi video thành công để tránh 403 cho prompt tiếp theo
        if download_success:
            try:
                if self.driver:
                    self.log("[VIDEO] [SYNC] F5 refresh để tránh 403...")
                    self.driver.refresh()
                    # Đợi textarea xuất hiện = page load xong (tự động F5 nếu không thấy)
                    if not self._wait_for_textarea_visible():
                        self.log("[VIDEO] [WARN] Không thấy textarea sau nhiều lần F5", "WARN")

                    # Re-inject JS Interceptor sau khi refresh (bị mất sau F5)
                    self._reset_tokens()
                    self.driver.run_js(JS_INTERCEPTOR)
                    # Click vào textarea để focus
                    self._click_textarea()
                    self.log("[VIDEO] [SYNC] Refreshed + ready")
            except Exception as e:
                self.log(f"[VIDEO] [WARN] Refresh warning: {e}", "WARN")

        # Reset 403 counter khi thành công
        if self._consecutive_403 > 0:
            self.log(f"[IPv6] Reset 403 counter (was {self._consecutive_403})")
            self._consecutive_403 = 0

        return True, result_path, None

    def switch_to_image_mode(self) -> bool:
        """Chuyển Chrome về mode tạo ảnh. Dùng cách giống T2V: click dropdown 2 lần với setTimeout."""
        if not self._ready:
            return False

        MAX_RETRIES = 3

        for attempt in range(MAX_RETRIES):
            try:
                # === CHECK LOGOUT TRƯỚC ===
                if self._is_logged_out():
                    self.log("[Mode] [WARN] Phát hiện bị LOGOUT - auto login...")
                    if self._auto_login_google():
                        self.log("[Mode] [v] Đã login lại")
                        # Re-setup sau khi login
                        time.sleep(2)
                        continue
                    else:
                        self.log("[Mode] [x] Login thất bại", "ERROR")
                        return False

                # === CHECK COMBOBOX TỒN TẠI ===
                has_combobox = self.driver.run_js("""
                    return document.querySelector('button[role="combobox"]') !== null;
                """)

                if not has_combobox:
                    self.log(f"[Mode] [WARN] Không tìm thấy combobox, F5 refresh... (attempt {attempt + 1})")
                    self.driver.refresh()
                    time.sleep(3)
                    # Re-inject JS Interceptor sau refresh
                    self._reset_tokens()
                    self.driver.run_js(JS_INTERCEPTOR)
                    continue

                self.log(f"[Mode] Chuyển sang Image mode (attempt {attempt + 1}/{MAX_RETRIES})...")

                # Dùng JS với setTimeout (đợi dropdown mở)
                self.driver.run_js("window._imageResult = 'PENDING';")
                self.driver.run_js(JS_SELECT_IMAGE_MODE)

                # Đợi JS async hoàn thành (setTimeout 100ms + 300ms = ~500ms)
                time.sleep(0.8)

                # Kiểm tra kết quả
                result = self.driver.run_js("return window._imageResult;")

                if result == 'CLICKED':
                    self.log("[Mode] [v] Đã chuyển sang Image mode")
                    time.sleep(0.3)
                    return True
                else:
                    self.log(f"[Mode] Không tìm thấy Image option: {result}", "WARN")
                    # Click ra ngoài để đóng menu
                    self.driver.run_js('document.body.click();')
                    time.sleep(0.3)
                    continue

            except Exception as e:
                self.log(f"[Mode] Error: {e}", "ERROR")
                time.sleep(0.5)

        self.log("[Mode] [x] Không thể chuyển sang Image mode sau nhiều lần thử", "ERROR")
        return False

    def switch_to_video_mode(self) -> bool:
        """Chuyển Chrome sang mode tạo video từ ảnh. Dùng cách cũ: click dropdown 2 lần với delay."""
        if not self._ready:
            return False

        MAX_RETRIES = 3

        for attempt in range(MAX_RETRIES):
            try:
                self.log(f"[Mode] Chuyển sang Video mode (attempt {attempt + 1}/{MAX_RETRIES})...")

                # Bước 1: Click dropdown lần 1
                self.driver.run_js(JS_SELECT_VIDEO_MODE_STEP1)
                time.sleep(0.5)

                # Bước 2: Click dropdown lần 2 để mở menu
                self.driver.run_js(JS_SELECT_VIDEO_MODE_STEP2)
                time.sleep(0.5)

                # Bước 3: Tìm và click option "Tạo video từ các thành phần"
                option_clicked = self.driver.run_js(JS_SELECT_VIDEO_MODE_STEP3)

                if option_clicked == 'CLICKED':
                    self.log("[Mode] [v] Đã chuyển sang Video mode")
                    time.sleep(0.5)
                    return True
                else:
                    self.log(f"[Mode] Không tìm thấy Video option: {option_clicked}", "WARN")
                    # Click ra ngoài để đóng menu
                    self.driver.run_js('document.body.click();')
                    time.sleep(0.5)
                    continue

            except Exception as e:
                self.log(f"[Mode] Error: {e}", "ERROR")
                time.sleep(0.5)

        self.log("[Mode] [x] Không thể chuyển sang Video mode sau nhiều lần thử", "ERROR")
        return False

    def generate_video_force_mode(
        self,
        media_id: str,
        prompt: str,
        save_path: Optional[Path] = None,
        aspect_ratio: str = "VIDEO_ASPECT_RATIO_LANDSCAPE",
        video_model: str = "veo_3_1_r2v_fast_landscape_ultra_relaxed",
        max_wait: int = 180,
        timeout: int = 60,
        max_retries: int = 3
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Tạo video bằng FORCE MODE - KHÔNG CẦN CLICK CHUYỂN MODE!
        Có retry và xử lý 403 + IPv6 như generate_image.

        Flow thông minh:
        1. Vẫn ở mode "Tạo hình ảnh" (không click chuyển mode)
        2. Set window._forceVideoPayload với video payload đầy đủ
        3. Gửi prompt như bình thường (trigger Chrome gửi request ảnh)
        4. Interceptor detect _forceVideoPayload → ĐỔI URL và PAYLOAD thành video
        5. Chrome gửi VIDEO request với fresh reCAPTCHA!

        Ưu điểm:
        - Không cần click chuyển mode UI (hay lỗi)
        - Sử dụng lại flow tạo ảnh đã hoạt động
        - Fresh reCAPTCHA trong 0.05s
        - Tự động xử lý 403 với IPv6 rotation

        Args:
            media_id: Media ID của ảnh (từ generate_image)
            prompt: Video prompt (mô tả chuyển động)
            save_path: Đường dẫn lưu video
            aspect_ratio: Tỷ lệ video
            video_model: Model video
            max_wait: Thời gian poll tối đa (giây)
            timeout: Timeout đợi response đầu tiên
            max_retries: Số lần retry khi gặp 403

        Returns:
            Tuple[success, video_path_or_url, error]
        """
        if not self._ready:
            return False, None, "API chưa setup! Gọi setup() trước."

        if not media_id:
            return False, None, "Media ID không được để trống"

        last_error = None

        for attempt in range(max_retries):
            # Thực hiện tạo video
            success, result, error = self._execute_video_force_mode(
                media_id=media_id,
                prompt=prompt,
                save_path=save_path,
                aspect_ratio=aspect_ratio,
                video_model=video_model,
                max_wait=max_wait,
                timeout=timeout
            )

            if success:
                # Reset 403 counter khi thành công
                if self._consecutive_403 > 0:
                    self.log(f"[I2V-FORCE] Reset 403 counter (was {self._consecutive_403})")
                    self._consecutive_403 = 0
                return True, result, None

            if error:
                last_error = error

                # === 403 ERROR: RESET CHROME + IPv6 ===
                if "403" in str(error):
                    self._consecutive_403 += 1
                    self.log(f"[I2V-FORCE] [WARN] 403 error (lần {self._consecutive_403}/{self._max_403_before_ipv6}) - RESET CHROME!", "WARN")

                    # Kill Chrome
                    self._kill_chrome()
                    self.close()
                    time.sleep(2)

                    # Đổi proxy nếu có
                    if self._use_webshare and self._webshare_proxy:
                        success_rotate, msg = self._webshare_proxy.rotate_ip(self.worker_id, "I2V-FORCE 403")
                        self.log(f"[I2V-FORCE] → Webshare rotate: {msg}", "WARN")

                    # === IPv6: CHỈ Chrome 1 (worker_id=0) mới activate/rotate ===
                    rotate_ipv6 = False
                    if self._consecutive_403 >= self._max_403_before_ipv6 and self.worker_id == 0:
                        self._consecutive_403 = 0  # Reset counter

                        if not self._ipv6_activated:
                            # Lần đầu: Activate IPv6
                            self.log(f"[I2V-FORCE] → [NET] ACTIVATE IPv6 MODE (lần đầu)...")
                            self._activate_ipv6()
                        else:
                            # Đã activate: Rotate sang IP khác
                            self.log(f"[I2V-FORCE] → [SYNC] Rotate sang IPv6 khác...")
                            rotate_ipv6 = True
                    elif self._consecutive_403 >= self._max_403_before_ipv6:
                        self.log(f"[Worker{self.worker_id}] Skip IPv6 (Chrome 1 quản lý)")
                        self._consecutive_403 = 0

                    # Restart Chrome (có thể kèm IPv6 rotation)
                    if self.restart_chrome(rotate_ipv6=rotate_ipv6):
                        self.log("[I2V-FORCE] → Chrome restarted, tiếp tục...")
                        continue  # Thử lại sau khi reset
                    else:
                        return False, None, "Không restart được Chrome sau 403"

                # === TIMEOUT ERROR: Reset Chrome ===
                if "timeout" in str(error).lower():
                    self.log(f"[I2V-FORCE] [WARN] Timeout error (attempt {attempt+1}/{max_retries}) - Reset Chrome...", "WARN")

                    self._kill_chrome()
                    self.close()
                    time.sleep(2)

                    # Đổi proxy nếu có
                    if self._use_webshare and self._webshare_proxy:
                        success_rotate, msg = self._webshare_proxy.rotate_ip(self.worker_id, "I2V-FORCE Timeout")
                        self.log(f"[I2V-FORCE] → Webshare rotate: {msg}", "WARN")

                    if attempt < max_retries - 1:
                        if self.restart_chrome():
                            continue
                        else:
                            return False, None, "Không restart được Chrome sau timeout"

                # === 500 ERROR: Retry với delay ===
                if "500" in str(error):
                    self.log(f"[I2V-FORCE] [WARN] 500 Internal Error (attempt {attempt+1}/{max_retries})", "WARN")
                    if attempt < max_retries - 1:
                        self.log(f"[I2V-FORCE] → Đợi 3s rồi retry...")
                        time.sleep(3)
                        continue

                # Lỗi khác, không retry
                return False, None, error

        return False, None, last_error or "Max retries exceeded"

    def _execute_video_force_mode(
        self,
        media_id: str,
        prompt: str,
        save_path: Optional[Path] = None,
        aspect_ratio: str = "VIDEO_ASPECT_RATIO_LANDSCAPE",
        video_model: str = "veo_3_1_r2v_fast_landscape_ultra_relaxed",
        max_wait: int = 180,
        timeout: int = 60
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Thực hiện tạo video FORCE MODE một lần (không retry).
        Được gọi bởi generate_video_force_mode với retry logic.
        """
        self.log(f"[I2V-FORCE] Tạo video từ media: {media_id[:50]}...")
        self.log(f"[I2V-FORCE] Prompt: {prompt[:60]}...")

        # 1. Reset video state
        self.driver.run_js("""
            window._videoResponse = null;
            window._videoError = null;
            window._videoPending = false;
            window._forceVideoPayload = null;
        """)

        # 2. Chuẩn bị video payload
        import uuid
        session_id = f";{int(time.time() * 1000)}"
        scene_id = str(uuid.uuid4())

        video_payload = {
            "clientContext": {
                "projectId": self.project_id or "",
                "recaptchaToken": "",  # Sẽ được inject bởi interceptor
                "sessionId": session_id,
                "tool": "PINHOLE",
                "userPaygateTier": "PAYGATE_TIER_TWO"
            },
            "requests": [{
                "aspectRatio": aspect_ratio,
                "metadata": {"sceneId": scene_id},
                "referenceImages": [{
                    "imageUsageType": "IMAGE_USAGE_TYPE_ASSET",
                    "mediaId": media_id
                }],
                "seed": int(time.time()) % 100000,
                "textInput": {"prompt": prompt},
                "videoModelKey": video_model
            }]
        }

        # 3. Set FORCE VIDEO PAYLOAD - Interceptor sẽ đổi URL và payload
        self.driver.run_js(f"window._forceVideoPayload = {json.dumps(video_payload)};")
        self.log(f"[I2V-FORCE] [v] Video payload ready (mediaId: {media_id[:40]}...)")
        self.log(f"[I2V-FORCE] Interceptor sẽ đổi image request → video request")

        # 4. Gửi prompt như tạo ảnh (trigger Chrome gửi request)
        textarea = self._find_textarea()
        if not textarea:
            return False, None, "Không tìm thấy textarea"

        try:
            textarea.click()
            time.sleep(0.3)
        except:
            pass

        # Type prompt with Ctrl+V
        self._paste_prompt_ctrlv(textarea, prompt[:500])

        # Đợi reCAPTCHA chuẩn bị token
        time.sleep(2)

        # 5. Nhấn Enter để gửi (trigger Chrome gửi request - Interceptor đổi thành video)
        self.log("[I2V-FORCE] → Pressed Enter, Interceptor đổi thành VIDEO request...")
        textarea.input('\n')

        # 6. Đợi VIDEO response (từ Interceptor)
        start_time = time.time()
        while time.time() - start_time < timeout:
            # Check video response (được set bởi FORCE-VIDEO mode trong Interceptor)
            response = self.driver.run_js("return window._videoResponse;")
            error = self.driver.run_js("return window._videoError;")
            pending = self.driver.run_js("return window._videoPending;")

            if error:
                self.log(f"[I2V-FORCE] [x] Error: {error}", "ERROR")
                return False, None, error

            if response:
                self.log(f"[I2V-FORCE] Got response!")

                # Check error response
                if isinstance(response, dict):
                    if response.get('error') and response.get('error').get('code'):
                        error_code = response['error']['code']
                        error_msg = response['error'].get('message', '')
                        self.log(f"[I2V-FORCE] [x] API Error {error_code}: {error_msg}", "ERROR")
                        return False, None, f"Error {error_code}: {error_msg}"

                    # Check for operations (async video)
                    if response.get('operations'):
                        operation = response['operations'][0]
                        operation_name = operation.get('name', '')
                        self.log(f"[I2V-FORCE] [v] Video operation started: {operation_name[-30:]}...")

                        # Poll cho video hoàn thành qua Browser
                        video_url = self._poll_video_operation_browser(operation, max_wait)
                        if video_url:
                            self.log(f"[I2V-FORCE] [v] Video ready: {video_url[:60]}...")
                            return self._download_video_if_needed(video_url, save_path)
                        else:
                            return False, None, "Timeout hoặc lỗi khi poll video"

                    # Check for direct video URL
                    if response.get('videos'):
                        video = response['videos'][0]
                        video_url = video.get('videoUri') or video.get('uri')
                        if video_url:
                            self.log(f"[I2V-FORCE] [v] Video ready: {video_url[:60]}...")
                            return self._download_video_if_needed(video_url, save_path)

                return False, None, "Response không có operations/videos"

            time.sleep(0.5)

        self.log("[I2V-FORCE] [x] Timeout đợi video response", "ERROR")
        return False, None, "Timeout waiting for video response"

    def _poll_video_operation_browser(self, operation: Dict, max_wait: int = 180) -> Optional[str]:
        """
        Poll video operation qua Browser (dùng fetch trong browser).
        Không cần gọi API trực tiếp, dùng Chrome's session/cookies.

        Args:
            operation: Operation dict từ response (chứa 'name', 'metadata', etc.)
            max_wait: Thời gian poll tối đa (giây)

        Returns:
            Video URL nếu thành công, None nếu timeout/lỗi
        """
        poll_url = "https://aisandbox-pa.googleapis.com/v1/video:batchCheckAsyncVideoGenerationStatus"

        # Chuẩn bị payload poll
        poll_payload = json.dumps({"operations": [operation]})

        # JS để poll qua browser's fetch (với auth từ interceptor)
        poll_js = f'''
(async function() {{
    window._videoPollResult = null;
    window._videoPollError = null;
    window._videoPollDone = false;

    try {{
        // Lấy auth headers từ interceptor (đã capture khi gửi request)
        var headers = {{
            "Content-Type": "application/json"
        }};

        // Add Bearer token nếu có (captured bởi interceptor)
        if (window._tk) {{
            headers["Authorization"] = "Bearer " + window._tk;
        }}

        // Add x-browser-validation nếu có
        if (window._xbv) {{
            headers["x-browser-validation"] = window._xbv;
        }}

        const response = await fetch("{poll_url}", {{
            method: "POST",
            headers: headers,
            credentials: "include",
            body: {poll_payload!r}
        }});

        const data = await response.json();
        window._videoPollResult = data;
        window._videoPollDone = true;
        console.log('[POLL] Status:', response.status, 'Data:', JSON.stringify(data).substring(0, 200));
    }} catch(e) {{
        window._videoPollError = e.toString();
        window._videoPollDone = true;
        console.log('[POLL] Error:', e);
    }}
}})();
'''

        start_time = time.time()
        poll_interval = 5  # Poll mỗi 5 giây
        poll_count = 0

        while time.time() - start_time < max_wait:
            poll_count += 1
            self.log(f"[I2V-FORCE] Polling video... ({poll_count}, {int(time.time() - start_time)}s)")

            # Run poll JS
            self.driver.run_js(poll_js)

            # Đợi kết quả
            for _ in range(30):  # Max 3s đợi response
                done = self.driver.run_js("return window._videoPollDone;")
                if done:
                    break
                time.sleep(0.1)

            # Check kết quả
            error = self.driver.run_js("return window._videoPollError;")
            if error:
                self.log(f"[I2V-FORCE] Poll error: {error}", "WARN")
                time.sleep(poll_interval)
                continue

            result = self.driver.run_js("return window._videoPollResult;")
            if not result:
                time.sleep(poll_interval)
                continue

            # Check operations status
            if result.get('operations'):
                op_item = result['operations'][0]

                # Format mới: status field thay vì done
                status = op_item.get('status', '')
                op_done = status == 'MEDIA_GENERATION_STATUS_SUCCESSFUL'

                # Operation data nằm trong nested 'operation' object
                op_data = op_item.get('operation', {})
                progress = op_data.get('metadata', {}).get('progressPercent', 0)

                self.log(f"[I2V-FORCE] Status: {status}, Done: {op_done}")

                if op_done:
                    # Video URL ở operation.metadata.video.fifeUrl
                    video_url = op_data.get('metadata', {}).get('video', {}).get('fifeUrl')
                    if video_url:
                        self.log(f"[I2V-FORCE] [v] Video completed!")
                        self.log(f"[I2V-FORCE] URL: {video_url[:80]}...")
                        return video_url
                    else:
                        self.log(f"[I2V-FORCE] [WARN] Video done but URL not found", "WARN")

                # Check error status
                if status == 'MEDIA_GENERATION_STATUS_FAILED':
                    self.log(f"[I2V-FORCE] [x] Video generation failed", "ERROR")
                    return None

            time.sleep(poll_interval)

        self.log(f"[I2V-FORCE] [x] Timeout sau {max_wait}s", "ERROR")
        return None

    def generate_video_t2v_mode(
        self,
        media_id: str,
        prompt: str,
        save_path: Optional[Path] = None,
        video_model: str = "veo_3_1_r2v_fast_landscape_ultra_relaxed",
        max_wait: int = 180,
        timeout: int = 180,  # Tăng từ 60 → 180 giây
        max_retries: int = 3
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Tạo video bằng T2V MODE - Dùng Chrome's Text-to-Video mode, Interceptor convert sang I2V.
        Có retry và xử lý 403 + IPv6 như generate_image.

        Flow thông minh (ý tưởng của user):
        1. Click chuyển sang "Từ văn bản sang video" (T2V mode)
        2. Set window._t2vToI2vConfig với mediaId của ảnh đã upload
        3. Gửi prompt bình thường (trigger Chrome gửi T2V request)
        4. Interceptor catch T2V request và convert sang I2V:
           - Đổi URL: batchAsyncGenerateVideoText → batchAsyncGenerateVideoReferenceImages
           - Thêm referenceImages với mediaId
           - CHỈ đổi model: _t2v_ → _r2v_ (giữ nguyên _landscape_, _relaxed, veo_3_1, etc.)
           - GIỮ seed (I2V cần seed)
        5. Chrome gửi I2V request với fresh reCAPTCHA!

        Args:
            media_id: Media ID của ảnh (từ generate_image)
            prompt: Video prompt (mô tả chuyển động)
            save_path: Đường dẫn lưu video
            video_model: Model video I2V (default: veo_3_0_r2v_fast_ultra)
            max_wait: Thời gian poll tối đa (giây)
            timeout: Timeout đợi response đầu tiên
            max_retries: Số lần retry khi gặp 403

        Returns:
            Tuple[success, video_path_or_url, error]
        """
        if not self._ready:
            return False, None, "API chưa setup! Gọi setup() trước."

        if not media_id:
            return False, None, "Media ID không được để trống"

        last_error = None

        for attempt in range(max_retries):
            success, result, error = self._execute_video_t2v_mode(
                media_id=media_id,
                prompt=prompt,
                save_path=save_path,
                video_model=video_model,
                max_wait=max_wait,
                timeout=timeout
            )

            if success:
                # Reset all error counters on success
                if self._consecutive_403 > 0 or getattr(self, '_cleared_data_for_403', False):
                    self.log(f"[T2V→I2V] Reset 403 counter (was {self._consecutive_403})")
                    self._consecutive_403 = 0
                    self._cleared_data_for_403 = False
                self._timeout_count = 0  # Reset timeout counter

                # Restart Chrome sau mỗi video (giống image generation)
                # Để tránh 403 cho video tiếp theo
                self.log("[T2V→I2V] [SYNC] Restart Chrome sau video thành công...")
                try:
                    self._kill_chrome()
                    self.close()
                    time.sleep(1)
                    if self.restart_chrome(rotate_ipv6=False):
                        self.log("[T2V→I2V] [v] Chrome reset xong")
                    else:
                        self.log("[T2V→I2V] [WARN] Chrome restart failed", "WARN")
                except Exception as e:
                    self.log(f"[T2V→I2V] [WARN] Restart error: {e}", "WARN")

                return True, result, None

            if error:
                last_error = error

                # === 403 ERROR HANDLING ===
                # Logic: 403 → Reset Chrome (3 lần) → Clear data + login lại → Đổi IPv6
                if "403" in str(error):
                    self._consecutive_403 += 1
                    cleared_flag = getattr(self, '_cleared_data_for_403', False)

                    if self._consecutive_403 <= 3 and not cleared_flag:
                        # Bước 1: Reset Chrome (tối đa 3 lần)
                        self.log(f"[T2V→I2V] [WARN] 403 error (lần {self._consecutive_403}/3) - RESET CHROME!", "WARN")
                        self._kill_chrome()
                        self.close()
                        time.sleep(2)

                    elif self._consecutive_403 == 4 or (self._consecutive_403 > 3 and not cleared_flag):
                        # Bước 2: Sau 3 lần reset vẫn 403 → XÓA TRIỆT ĐỂ PROFILE + đăng nhập lại
                        self.log(f"[T2V→I2V] [WARN] 403 sau 3 lần reset → RESET PROFILE + ĐĂNG NHẬP LẠI!", "WARN")
                        # Dùng reset_chrome_profile() - xóa hoàn toàn thư mục profile
                        self.reset_chrome_profile()
                        time.sleep(1)
                        # Login lại (sẽ tự khởi động Chrome mới)
                        self._auto_login_google()
                        self._cleared_data_for_403 = True
                        self._consecutive_403 = 0

                    else:
                        # Bước 3: Đã clear data vẫn 403 → Đổi IPv6
                        self.log(f"[T2V→I2V] [WARN] 403 sau khi clear data → ĐỔI IPv6!", "WARN")
                        self._cleared_data_for_403 = False
                        self._consecutive_403 = 0
                        self._kill_chrome()
                        self.close()
                        time.sleep(2)

                        # CHỈ Chrome 1 (worker_id=0) rotate IPv6
                        if self.worker_id == 0 and self._ipv6_rotator and self._ipv6_activated:
                            new_ip = self._ipv6_rotator.rotate()
                            if new_ip:
                                self.log(f"[T2V→I2V] → [NET] IPv6 mới: {new_ip}")
                                if hasattr(self, '_ipv6_proxy') and self._ipv6_proxy:
                                    self._ipv6_proxy.set_ipv6(new_ip)

                    if self.restart_chrome(rotate_ipv6=False):
                        self.log("[T2V→I2V] → Chrome restarted, tiếp tục...")
                        continue
                    else:
                        return False, None, "Không restart được Chrome sau 403"

                # === TIMEOUT ERROR: Reset + retry 1 lần → skip ===
                if "timeout" in str(error).lower():
                    # Đếm số lần timeout liên tiếp
                    timeout_count = getattr(self, '_timeout_count', 0) + 1
                    self._timeout_count = timeout_count

                    self.log(f"[T2V→I2V] [WARN] Timeout error (lần {timeout_count}) - Reset Chrome...", "WARN")

                    if timeout_count == 1:
                        # LẦN 1: Reset Chrome và retry
                        self.log("[T2V→I2V] → Reset Chrome + retry 1 lần...")
                        self._kill_chrome()
                        self.close()
                        time.sleep(2)

                        if self._use_webshare and self._webshare_proxy:
                            success_rotate, msg = self._webshare_proxy.rotate_ip(self.worker_id, "T2V Timeout")
                            self.log(f"[T2V→I2V] → Webshare rotate: {msg}", "WARN")

                        if self.restart_chrome():
                            continue  # Retry 1 lần
                    else:
                        # LẦN 2+: Reset Chrome rồi skip sang prompt khác
                        self.log("[T2V→I2V] → Timeout 2 lần → RESET CHROME + SKIP!", "WARN")

                        # RESET Chrome trước khi qua prompt mới
                        self._kill_chrome()
                        self.close()
                        time.sleep(2)

                        if self.restart_chrome():
                            self.log("[T2V→I2V] → Chrome reset xong, qua prompt mới")
                        else:
                            self.log("[T2V→I2V] [WARN] Restart Chrome fail", "WARN")

                        self._timeout_count = 0  # Reset counter
                        return False, None, "Timeout 2 lần - skip prompt"

                # === 400 ERROR: Invalid argument - có thể do mediaId hết hạn hoặc payload sai ===
                if "400" in str(error):
                    self._consecutive_403 += 1  # Dùng chung counter với 403
                    self.log(f"[T2V→I2V] [WARN] 400 error (lần {self._consecutive_403}) - Invalid argument!", "WARN")
                    self.log(f"[T2V→I2V] → Error details: {error}", "WARN")

                    # Đợi 3 giây để user thấy lỗi trước khi reset
                    time.sleep(3)

                    # Sau 3 lần liên tiếp, đổi IPv6 và thử lại
                    if self._consecutive_403 >= 3:
                        self.log(f"[T2V→I2V] [SYNC] {self._consecutive_403} lỗi liên tiếp → ROTATE IPv6 + RESET CHROME!")

                        self._kill_chrome()
                        self.close()
                        time.sleep(2)

                        if self._use_webshare and self._webshare_proxy:
                            success_rotate, msg = self._webshare_proxy.rotate_ip(self.worker_id, "T2V 400")
                            self.log(f"[T2V→I2V] → Webshare rotate: {msg}", "WARN")

                        # Rotate IPv6 - CHỈ Chrome 1 (worker_id=0) rotate
                        if self.worker_id == 0:
                            if not self._ipv6_activated:
                                self.log(f"[T2V→I2V] → [NET] ACTIVATE IPv6 MODE (lần đầu)...")
                                self._activate_ipv6()
                            else:
                                self.log(f"[T2V→I2V] → [SYNC] Rotate sang IPv6 khác...")
                                if self._ipv6_rotator:
                                    new_ip = self._ipv6_rotator.rotate()
                                    if new_ip and hasattr(self, '_ipv6_proxy') and self._ipv6_proxy:
                                        self._ipv6_proxy.set_ipv6(new_ip)
                        else:
                            self.log(f"[Worker{self.worker_id}] Skip IPv6 rotation (chỉ Chrome 1 rotate)")

                        self._consecutive_403 = 0

                        if attempt < max_retries - 1:
                            if self.restart_chrome(rotate_ipv6=True):
                                self.log("[T2V→I2V] → Chrome restarted, tiếp tục...")
                                continue
                    else:
                        # Chưa đến 3 lần, chỉ reset Chrome mà không đổi IPv6
                        self._kill_chrome()
                        self.close()
                        time.sleep(2)

                        if attempt < max_retries - 1:
                            if self.restart_chrome():
                                self.log("[T2V→I2V] → Chrome restarted, thử lại...")
                                continue

                    return False, None, error

                # === 500 ERROR ===
                if "500" in str(error):
                    self.log(f"[T2V→I2V] [WARN] 500 Internal Error (attempt {attempt+1}/{max_retries})", "WARN")
                    if attempt < max_retries - 1:
                        time.sleep(3)
                        continue

                # === OTHER ERROR: Đợi để hiển thị lỗi trước khi return ===
                self.log(f"[T2V→I2V] [WARN] Error: {error}", "WARN")
                time.sleep(2)  # Đợi 2 giây để user thấy lỗi
                return False, None, error

        return False, None, last_error or "Max retries exceeded"

    def _execute_video_t2v_mode(
        self,
        media_id: str,
        prompt: str,
        save_path: Optional[Path],
        video_model: str,
        max_wait: int,
        timeout: int
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Thực hiện tạo video T2V mode một lần (không retry)."""

        # === VALIDATION: Kiểm tra input trước khi gửi ===
        if not media_id or len(media_id) < 10:
            return False, None, f"Invalid media_id: '{media_id}' - quá ngắn hoặc rỗng"

        if not prompt or len(prompt.strip()) < 3:
            return False, None, f"Invalid prompt: '{prompt}' - quá ngắn hoặc rỗng"

        # Kiểm tra format media_id (thường bắt đầu bằng số hoặc có dấu /)
        if not any(c.isdigit() for c in media_id):
            self.log(f"[T2V→I2V] [WARN] Media ID không có số: {media_id[:50]} - có thể sai format!", "WARN")

        self.log(f"[T2V→I2V] ══════════════════════════════════════════")
        self.log(f"[T2V→I2V] Tạo video với:")
        self.log(f"[T2V→I2V]   → Media ID: {media_id[:60]}...")
        self.log(f"[T2V→I2V]   → Prompt: {prompt[:60]}...")
        self.log(f"[T2V→I2V]   → Model: Chrome sẽ dùng (interceptor convert _t2v_ → _r2v_)")

        # 1. Chuyển sang T2V mode + Lower Priority model
        # CHỈ LÀM LẦN ĐẦU khi mới mở Chrome - sau F5 refresh không cần làm lại
        if not self._t2v_mode_selected:
            self.log("[T2V→I2V] Chuyển sang mode 'Từ văn bản sang video'...")
            if not self.switch_to_t2v_mode():
                self.log("[T2V→I2V] [WARN] Không chuyển được T2V mode, thử tiếp...", "WARN")

            # 1.5. Chuyển sang Lower Priority model (tránh rate limit)
            self.log("[T2V→I2V] Chuyển sang model Lower Priority...")
            self.switch_to_lower_priority_model()

            # Đánh dấu đã chọn mode/model - không cần chọn lại
            self._t2v_mode_selected = True
            self.log("[T2V→I2V] [v] Mode/Model đã chọn - các video sau sẽ không chọn lại")
        else:
            self.log("[T2V→I2V] Mode/Model đã sẵn sàng (giữ từ lần trước)")

        # 2. Reset video state
        self.driver.run_js("""
            window._videoResponse = null;
            window._videoError = null;
            window._videoPending = false;
            window._t2vToI2vConfig = null;
        """)

        # 2. Set T2V→I2V config
        # QUAN TRỌNG: KHÔNG gửi videoModelKey - để interceptor tự convert từ Chrome model
        # Chrome gửi: veo_3_1_t2v_fast_ultra_relaxed
        # Interceptor sẽ convert: _t2v_ → _r2v_ → veo_3_1_r2v_fast_ultra_relaxed
        # Nếu gửi videoModelKey, sẽ override thành model sai (veo_3_0_r2v_fast_ultra)
        t2v_config = {
            "mediaId": media_id
            # videoModelKey: Bỏ để dùng Chrome model convert (giữ _relaxed, veo_3_1, etc.)
        }
        self.driver.run_js(f"window._t2vToI2vConfig = {json.dumps(t2v_config)};")

        # Verify config được set đúng
        verify_config = self.driver.run_js("return window._t2vToI2vConfig;")
        if not verify_config or not verify_config.get('mediaId'):
            return False, None, "Failed to set T2V→I2V config in browser"

        self.log(f"[T2V→I2V] [v] Config verified (mediaId: {verify_config.get('mediaId', '')[:40]}...)")

        # 3. Tìm textarea và nhập prompt
        textarea = self._find_textarea()
        if not textarea:
            return False, None, "Không tìm thấy textarea"

        try:
            textarea.click()
            time.sleep(0.3)
        except:
            pass

        self._paste_prompt_ctrlv(textarea, prompt[:500])
        time.sleep(2)

        # 5. Nhấn Enter
        self.log("[T2V→I2V] → Pressed Enter, Chrome gửi T2V → Interceptor convert → I2V...")
        textarea.input('\n')

        # 6. Đợi VIDEO response
        start_time = time.time()
        while time.time() - start_time < timeout:
            response = self.driver.run_js("return window._videoResponse;")
            error = self.driver.run_js("return window._videoError;")

            if error:
                self.log(f"[T2V→I2V] [x] Error: {error}", "ERROR")
                return False, None, error

            if response:
                self.log(f"[T2V→I2V] Got response!")

                if isinstance(response, dict):
                    if response.get('error') and response.get('error').get('code'):
                        error_code = response['error']['code']
                        error_msg = response['error'].get('message', '')
                        self.log(f"[T2V→I2V] [x] API Error {error_code}: {error_msg}", "ERROR")
                        return False, None, f"Error {error_code}: {error_msg}"

                    if response.get('operations'):
                        operation = response['operations'][0]
                        operation_name = operation.get('name', '')
                        self.log(f"[T2V→I2V] [v] Video operation started: {operation_name[-30:]}...")

                        # Poll qua Browser (dùng Chrome's auth)
                        video_url = self._poll_video_operation_browser(operation, max_wait)

                        if video_url:
                            self.log(f"[T2V→I2V] [v] Video ready: {video_url[:60]}...")
                            return self._download_video_if_needed(video_url, save_path)
                        else:
                            return False, None, "Timeout hoặc lỗi khi poll video"

                    if response.get('videos'):
                        video = response['videos'][0]
                        video_url = video.get('videoUri') or video.get('uri')
                        if video_url:
                            self.log(f"[T2V→I2V] [v] Video ready: {video_url[:60]}...")
                            return self._download_video_if_needed(video_url, save_path)

                return False, None, "Response không có operations/videos"

            time.sleep(0.5)

        self.log("[T2V→I2V] [x] Timeout đợi video response", "ERROR")
        return False, None, "Timeout waiting for video response"

    def switch_to_t2v_mode(self) -> bool:
        """
        Chuyển Chrome sang mode "Từ văn bản sang video" (Text-to-Video).
        Dùng cách cũ đã hoạt động: click dropdown 2 lần với delay, rồi tìm span.

        Returns:
            True nếu thành công
        """
        if not self._ready:
            return False

        MAX_RETRIES = 3

        for attempt in range(MAX_RETRIES):
            try:
                self.log(f"[Mode] Chuyển sang T2V mode (attempt {attempt + 1}/{MAX_RETRIES})...")

                # Dùng JS ALL-IN-ONE với setTimeout (đợi dropdown mở)
                self.driver.run_js("window._t2vResult = 'PENDING';")
                self.driver.run_js(JS_SELECT_T2V_MODE_ALL)

                # Đợi JS async hoàn thành (setTimeout 100ms + 300ms = ~500ms)
                time.sleep(0.8)

                # Kiểm tra kết quả
                result = self.driver.run_js("return window._t2vResult;")

                if result == 'CLICKED':
                    self.log("[Mode] [v] Đã chuyển sang T2V mode")
                    time.sleep(0.3)
                    return True
                elif result == 'NO_DROPDOWN':
                    self.log("[Mode] Không tìm thấy dropdown button", "WARN")
                else:
                    self.log(f"[Mode] Không tìm thấy T2V option: {result}", "WARN")
                    # Click ra ngoài để đóng menu
                    self.driver.run_js('document.body.click();')
                    time.sleep(0.3)
                    continue

            except Exception as e:
                self.log(f"[Mode] Error: {e}", "ERROR")
                time.sleep(0.5)

        self.log("[Mode] [x] Không thể chuyển sang T2V mode sau nhiều lần thử", "ERROR")
        return False

    def switch_to_lower_priority_model(self) -> bool:
        """
        Chuyển model sang "Veo 3.1 - Fast [Lower Priority]" để tránh rate limit.
        Flow: Click Cài đặt → Click Mô hình dropdown → Select Lower Priority

        Returns:
            True nếu thành công
        """
        if not self._ready:
            return False

        MAX_RETRIES = 2

        for attempt in range(MAX_RETRIES):
            try:
                self.log(f"[Model] Chuyển sang Lower Priority (attempt {attempt + 1}/{MAX_RETRIES})...")

                # Chạy JS ALL-IN-ONE
                self.driver.run_js("window._modelSwitchResult = 'PENDING';")
                self.driver.run_js(JS_SWITCH_TO_LOWER_PRIORITY)

                # Đợi JS async hoàn thành (500ms + 300ms = ~1s)
                time.sleep(1.2)

                # Kiểm tra kết quả
                result = self.driver.run_js("return window._modelSwitchResult;")

                if result == 'SUCCESS':
                    self.log("[Model] [v] Đã chuyển sang Lower Priority")
                    # Click ra ngoài để đóng dialog
                    time.sleep(0.3)
                    self.driver.run_js('document.body.click();')
                    time.sleep(0.3)
                    return True
                else:
                    self.log(f"[Model] Chưa chuyển được: {result}", "WARN")
                    # Click ra ngoài để đóng menu/dialog
                    self.driver.run_js('document.body.click();')
                    time.sleep(0.5)

            except Exception as e:
                self.log(f"[Model] Error: {e}", "ERROR")
                time.sleep(0.5)

        self.log("[Model] [WARN] Không thể chuyển Lower Priority, tiếp tục với model mặc định", "WARN")
        return False

    def generate_video_pure_t2v(
        self,
        prompt: str,
        save_path: Optional[Path] = None,
        max_wait: int = 180,
        timeout: int = 60,
        max_retries: int = 3
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Tạo video bằng PURE TEXT-TO-VIDEO mode - KHÔNG cần ảnh.
        Có retry và xử lý 403 + IPv6 như generate_image.

        Flow (giống như tạo ảnh, nhưng ở mode T2V):
        1. Chuyển sang mode "Từ văn bản sang video" (T2V)
        2. KHÔNG set _t2vToI2vConfig → Chrome gửi T2V request thuần
        3. Type prompt vào textarea
        4. Click Tạo → Chrome gửi batchAsyncGenerateVideoText
        5. Interceptor capture response (không convert)
        6. Poll và download video

        Args:
            prompt: Video prompt (mô tả video muốn tạo)
            save_path: Đường dẫn lưu video
            max_wait: Thời gian poll tối đa (giây)
            timeout: Timeout đợi response đầu tiên
            max_retries: Số lần retry khi gặp 403

        Returns:
            Tuple[success, video_path_or_url, error]
        """
        if not self._ready:
            return False, None, "API chưa setup! Gọi setup() trước."

        last_error = None

        for attempt in range(max_retries):
            success, result, error = self._execute_video_pure_t2v(
                prompt=prompt,
                save_path=save_path,
                max_wait=max_wait,
                timeout=timeout
            )

            if success:
                if self._consecutive_403 > 0:
                    self.log(f"[T2V-PURE] Reset 403 counter (was {self._consecutive_403})")
                    self._consecutive_403 = 0
                return True, result, None

            if error:
                last_error = error

                # === 403 ERROR: RESET CHROME + IPv6 ===
                if "403" in str(error):
                    self._consecutive_403 += 1
                    self.log(f"[T2V-PURE] [WARN] 403 error (lần {self._consecutive_403}/{self._max_403_before_ipv6}) - RESET CHROME!", "WARN")

                    self._kill_chrome()
                    self.close()
                    time.sleep(2)

                    if self._use_webshare and self._webshare_proxy:
                        success_rotate, msg = self._webshare_proxy.rotate_ip(self.worker_id, "T2V-PURE 403")
                        self.log(f"[T2V-PURE] → Webshare rotate: {msg}", "WARN")

                    # CHỈ Chrome 1 (worker_id=0) mới activate/rotate IPv6
                    rotate_ipv6 = False
                    if self._consecutive_403 >= self._max_403_before_ipv6 and self.worker_id == 0:
                        self._consecutive_403 = 0
                        if not self._ipv6_activated:
                            self.log(f"[T2V-PURE] → [NET] ACTIVATE IPv6 MODE (lần đầu)...")
                            self._activate_ipv6()
                        else:
                            self.log(f"[T2V-PURE] → [SYNC] Rotate sang IPv6 khác...")
                            rotate_ipv6 = True
                    elif self._consecutive_403 >= self._max_403_before_ipv6:
                        self.log(f"[Worker{self.worker_id}] Skip IPv6 (Chrome 1 quản lý)")
                        self._consecutive_403 = 0

                    if self.restart_chrome(rotate_ipv6=rotate_ipv6):
                        self.log("[T2V-PURE] → Chrome restarted, tiếp tục...")
                        continue
                    else:
                        return False, None, "Không restart được Chrome sau 403"

                # === TIMEOUT ERROR ===
                if "timeout" in str(error).lower():
                    self.log(f"[T2V-PURE] [WARN] Timeout error (attempt {attempt+1}/{max_retries}) - Reset Chrome...", "WARN")
                    self._kill_chrome()
                    self.close()
                    time.sleep(2)

                    if self._use_webshare and self._webshare_proxy:
                        success_rotate, msg = self._webshare_proxy.rotate_ip(self.worker_id, "T2V-PURE Timeout")
                        self.log(f"[T2V-PURE] → Webshare rotate: {msg}", "WARN")

                    if attempt < max_retries - 1:
                        if self.restart_chrome():
                            continue

                # === 500 ERROR ===
                if "500" in str(error):
                    self.log(f"[T2V-PURE] [WARN] 500 Internal Error (attempt {attempt+1}/{max_retries})", "WARN")
                    if attempt < max_retries - 1:
                        time.sleep(3)
                        continue

                return False, None, error

        return False, None, last_error or "Max retries exceeded"

    def _execute_video_pure_t2v(
        self,
        prompt: str,
        save_path: Optional[Path],
        max_wait: int,
        timeout: int
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Thực hiện tạo video T2V thuần một lần (không retry)."""
        self.log(f"[T2V-PURE] Tạo video từ text prompt...")
        self.log(f"[T2V-PURE] Prompt: {prompt[:80]}...")

        # 1. Chuyển sang T2V mode
        self.log("[T2V-PURE] Chuyển sang mode 'Từ văn bản sang video'...")
        if not self.switch_to_t2v_mode():
            self.log("[T2V-PURE] [WARN] Không chuyển được T2V mode, thử tiếp...", "WARN")

        # 2. Reset video state
        self.driver.run_js("""
            window._videoResponse = null;
            window._videoError = null;
            window._videoPending = false;
            window._t2vToI2vConfig = null;
            window._modifyVideoConfig = null;
            window._customVideoPayload = null;
            window._forceVideoPayload = null;
        """)
        self.log("[T2V-PURE] [v] Pure T2V mode (không convert sang I2V)")

        # 3. Tìm textarea và nhập prompt
        textarea = self._find_textarea()
        if not textarea:
            return False, None, "Không tìm thấy textarea"

        try:
            textarea.click()
            time.sleep(0.3)
        except:
            pass

        self._paste_prompt_ctrlv(textarea, prompt[:500])
        time.sleep(2)

        # 4. Nhấn Enter
        self.log("[T2V-PURE] → Pressed Enter, Chrome gửi batchAsyncGenerateVideoText...")
        textarea.input('\n')

        # 5. Đợi VIDEO response
        start_time = time.time()
        while time.time() - start_time < timeout:
            response = self.driver.run_js("return window._videoResponse;")
            error = self.driver.run_js("return window._videoError;")

            if error:
                self.log(f"[T2V-PURE] [x] Error: {error}", "ERROR")
                return False, None, error

            if response:
                self.log(f"[T2V-PURE] Got response!")

                if isinstance(response, dict):
                    if response.get('error') and response.get('error').get('code'):
                        error_code = response['error']['code']
                        error_msg = response['error'].get('message', '')
                        self.log(f"[T2V-PURE] [x] API Error {error_code}: {error_msg}", "ERROR")
                        return False, None, f"Error {error_code}: {error_msg}"

                    if response.get('operations'):
                        operation = response['operations'][0]
                        self.log(f"[T2V-PURE] [v] Video operation started")

                        headers = {
                            "Authorization": self.bearer_token,
                            "Content-Type": "application/json",
                            "Origin": "https://labs.google",
                            "Referer": "https://labs.google/",
                        }
                        if self.x_browser_validation:
                            headers["x-browser-validation"] = self.x_browser_validation

                        proxies = None
                        if self._use_webshare and hasattr(self, '_bridge_port') and self._bridge_port:
                            bridge_url = f"http://127.0.0.1:{self._bridge_port}"
                            proxies = {"http": bridge_url, "https": bridge_url}

                        video_url = self._poll_video_operation(operation, headers, proxies, max_wait)

                        if video_url:
                            self.log(f"[T2V-PURE] [v] Video ready: {video_url[:60]}...")
                            return self._download_video_if_needed(video_url, save_path)
                        else:
                            return False, None, "Timeout hoặc lỗi khi poll video"

                    if response.get('videos'):
                        video = response['videos'][0]
                        video_url = video.get('videoUri') or video.get('uri')
                        if video_url:
                            self.log(f"[T2V-PURE] [v] Video ready: {video_url[:60]}...")
                            return self._download_video_if_needed(video_url, save_path)

                return False, None, "Response không có operations/videos"

            time.sleep(0.5)

        self.log("[T2V-PURE] [x] Timeout đợi video response", "ERROR")
        return False, None, "Timeout waiting for video response"

    def generate_video_modify_mode(
        self,
        media_id: str,
        prompt: str,
        save_path: Optional[Path] = None,
        max_wait: int = 180,
        timeout: int = 60,
        max_retries: int = 3
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Tạo video bằng MODIFY MODE - GIỐNG HỆT TẠO ẢNH.
        Có retry và xử lý 403 + IPv6 như generate_image.

        Flow:
        1. Chuyển Chrome sang "Tạo video từ các thành phần"
        2. Set _modifyVideoConfig với referenceImages (media_id)
        3. Type prompt vào textarea
        4. Chrome tạo payload với model mới nhất + settings
        5. Interceptor chỉ THÊM referenceImages vào payload
        6. Forward request, poll kết quả, download video

        Args:
            media_id: Media ID của ảnh (từ generate_image)
            prompt: Video prompt (mô tả chuyển động)
            save_path: Đường dẫn lưu video
            max_wait: Thời gian poll tối đa (giây)
            timeout: Timeout đợi response đầu tiên
            max_retries: Số lần retry khi gặp 403

        Returns:
            Tuple[success, video_path_or_url, error]
        """
        if not self._ready:
            return False, None, "API chưa setup! Gọi setup() trước."

        if not media_id:
            return False, None, "Media ID không được để trống"

        last_error = None

        for attempt in range(max_retries):
            success, result, error = self._execute_video_modify_mode(
                media_id=media_id,
                prompt=prompt,
                save_path=save_path,
                max_wait=max_wait,
                timeout=timeout
            )

            if success:
                if self._consecutive_403 > 0:
                    self.log(f"[I2V-MODIFY] Reset 403 counter (was {self._consecutive_403})")
                    self._consecutive_403 = 0
                return True, result, None

            if error:
                last_error = error

                # === 403 ERROR: RESET CHROME + IPv6 ===
                if "403" in str(error):
                    self._consecutive_403 += 1
                    self.log(f"[I2V-MODIFY] [WARN] 403 error (lần {self._consecutive_403}/{self._max_403_before_ipv6}) - RESET CHROME!", "WARN")

                    self._kill_chrome()
                    self.close()
                    time.sleep(2)

                    if self._use_webshare and self._webshare_proxy:
                        success_rotate, msg = self._webshare_proxy.rotate_ip(self.worker_id, "I2V-MODIFY 403")
                        self.log(f"[I2V-MODIFY] → Webshare rotate: {msg}", "WARN")

                    # CHỈ Chrome 1 (worker_id=0) mới activate/rotate IPv6
                    rotate_ipv6 = False
                    if self._consecutive_403 >= self._max_403_before_ipv6 and self.worker_id == 0:
                        self._consecutive_403 = 0
                        if not self._ipv6_activated:
                            self.log(f"[I2V-MODIFY] → [NET] ACTIVATE IPv6 MODE (lần đầu)...")
                            self._activate_ipv6()
                        else:
                            self.log(f"[I2V-MODIFY] → [SYNC] Rotate sang IPv6 khác...")
                            rotate_ipv6 = True
                    elif self._consecutive_403 >= self._max_403_before_ipv6:
                        self.log(f"[Worker{self.worker_id}] Skip IPv6 (Chrome 1 quản lý)")
                        self._consecutive_403 = 0

                    if self.restart_chrome(rotate_ipv6=rotate_ipv6):
                        self.log("[I2V-MODIFY] → Chrome restarted, tiếp tục...")
                        continue
                    else:
                        return False, None, "Không restart được Chrome sau 403"

                # === TIMEOUT ERROR ===
                if "timeout" in str(error).lower():
                    self.log(f"[I2V-MODIFY] [WARN] Timeout error (attempt {attempt+1}/{max_retries}) - Reset Chrome...", "WARN")
                    self._kill_chrome()
                    self.close()
                    time.sleep(2)

                    if self._use_webshare and self._webshare_proxy:
                        success_rotate, msg = self._webshare_proxy.rotate_ip(self.worker_id, "I2V-MODIFY Timeout")
                        self.log(f"[I2V-MODIFY] → Webshare rotate: {msg}", "WARN")

                    if attempt < max_retries - 1:
                        if self.restart_chrome():
                            continue

                # === 500 ERROR ===
                if "500" in str(error):
                    self.log(f"[I2V-MODIFY] [WARN] 500 Internal Error (attempt {attempt+1}/{max_retries})", "WARN")
                    if attempt < max_retries - 1:
                        time.sleep(3)
                        continue

                return False, None, error

        return False, None, last_error or "Max retries exceeded"

    def _execute_video_modify_mode(
        self,
        media_id: str,
        prompt: str,
        save_path: Optional[Path],
        max_wait: int,
        timeout: int
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Thực hiện tạo video MODIFY mode một lần (không retry)."""
        self.log(f"[I2V] Tạo video từ media: {media_id[:50]}...")
        self.log(f"[I2V] Prompt: {prompt[:60]}...")

        # NOTE: Không cần switch_to_video_mode() ở đây
        # Chrome đã được switch sang I2V mode 1 LẦN sau khi load page

        # 1. Reset video state
        self.driver.run_js("""
            window._videoResponse = null;
            window._videoError = null;
            window._videoPending = false;
            window._modifyVideoConfig = null;
            window._customVideoPayload = null;
        """)

        # 3. Set MODIFY CONFIG
        modify_config = {
            "referenceImages": [{
                "imageUsageType": "IMAGE_USAGE_TYPE_ASSET",
                "mediaId": media_id
            }]
        }
        self.driver.run_js(f"window._modifyVideoConfig = {json.dumps(modify_config)};")
        self.log(f"[I2V] [v] MODIFY MODE: referenceImages ready")

        # 4. Tìm textarea và nhập prompt
        textarea = self._find_textarea()
        if not textarea:
            return False, None, "Không tìm thấy textarea"

        self._paste_prompt_ctrlv(textarea, prompt)
        time.sleep(2)

        # Nhấn Enter
        textarea.input('\n')
        self.log("[I2V] → Pressed Enter, Chrome đang gửi request...")

        # 5. Đợi video response
        start_time = time.time()

        while time.time() - start_time < timeout:
            result = self.driver.run_js("""
                return {
                    pending: window._videoPending,
                    response: window._videoResponse,
                    error: window._videoError
                };
            """)

            if result.get('error'):
                error_msg = result['error']
                self.log(f"[I2V] [x] Request error: {error_msg}", "ERROR")
                return False, None, error_msg

            if result.get('response'):
                response_data = result['response']

                if isinstance(response_data, dict):
                    if response_data.get('error'):
                        error_info = response_data['error']
                        error_msg = f"{error_info.get('code', 'unknown')}: {error_info.get('message', str(error_info))}"
                        self.log(f"[I2V] [x] API Error: {error_msg}", "ERROR")
                        return False, None, error_msg

                    if "media" in response_data or "generatedVideos" in response_data:
                        videos = response_data.get("generatedVideos", response_data.get("media", []))
                        if videos:
                            video_url = videos[0].get("video", {}).get("fifeUrl") or videos[0].get("fifeUrl")
                            if video_url:
                                self.log(f"[I2V] [v] Video ready (no poll): {video_url[:60]}...")
                                return self._download_video_if_needed(video_url, save_path)

                    operations = response_data.get("operations", [])
                    if operations:
                        op = operations[0]
                        op_name = op.get('name', '')
                        self.log(f"[I2V] [v] Video operation started: {op_name[-30:]}...")

                        # Poll qua Browser (dùng Chrome's auth)
                        video_url = self._poll_video_operation_browser(op, max_wait)

                        if video_url:
                            self.log(f"[I2V] [v] Video ready: {video_url[:60]}...")
                            return self._download_video_if_needed(video_url, save_path)
                        else:
                            return False, None, "Timeout hoặc lỗi khi poll video"

                    return False, None, "Không có operations/videos trong response"

            time.sleep(0.5)

        self.log("[I2V] [x] Timeout đợi response từ browser", "ERROR")
        return False, None, "Timeout waiting for video response"

    def _poll_video_operation(
        self,
        operation_data: Dict,
        headers: Dict,
        proxies: Optional[Dict],
        max_wait: int
    ) -> Optional[str]:
        """
        Poll cho video operation hoàn thành.
        Dùng POST với body chứa operation info (không phải GET).
        """
        url = "https://aisandbox-pa.googleapis.com/v1/video:batchCheckAsyncVideoGenerationStatus"

        # Payload gửi đi - chứa operation info từ response đầu
        poll_payload = {"operations": [operation_data]}

        start_time = time.time()
        poll_interval = 5  # Poll mỗi 5 giây

        poll_count = 0
        while time.time() - start_time < max_wait:
            try:
                poll_count += 1
                elapsed = int(time.time() - start_time)

                resp = requests.post(
                    url,
                    headers=headers,
                    json=poll_payload,
                    timeout=30,
                    proxies=proxies
                )

                if resp.status_code == 200:
                    data = resp.json()
                    operations = data.get("operations", [])

                    if operations:
                        op = operations[0]
                        status = op.get("status", "")

                        # Log progress
                        if poll_count == 1 or elapsed % 30 < poll_interval:
                            self.log(f"[I2V] Poll #{poll_count}: {status}, {elapsed}s")

                        # Check status
                        if "COMPLETE" in status or "SUCCESS" in status or "DONE" in status:
                            # Video xong - tìm URL (path: operation.metadata.video.fifeUrl)
                            video_url = op.get("operation", {}).get("metadata", {}).get("video", {}).get("fifeUrl")
                            if video_url:
                                return video_url

                            # Log full response để debug
                            self.log(f"[I2V] Complete but no URL: {json.dumps(op)[:500]}")
                            return None

                        elif "FAILED" in status or "ERROR" in status:
                            error_msg = op.get("error", {}).get("message", status)
                            self.log(f"[I2V] Video failed: {error_msg}", "ERROR")
                            return None

                        # Còn đang xử lý - update payload với status mới
                        poll_payload = {"operations": [op]}

                else:
                    self.log(f"[I2V] Poll error: HTTP {resp.status_code} - {resp.text[:200]}", "WARN")

                time.sleep(poll_interval)

            except Exception as e:
                self.log(f"[I2V] Poll error: {e}", "WARN")
                time.sleep(poll_interval)

        self.log(f"[I2V] Timeout after {max_wait}s", "ERROR")
        return None

    def close(self):
        """Đóng Chrome và proxy bridge."""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None

        # Dừng proxy bridge nếu có
        if self._proxy_bridge:
            try:
                self._proxy_bridge.stop()
                self.log("Proxy bridge stopped")
            except:
                pass
            self._proxy_bridge = None
            self._bridge_port = None

        self._ready = False

        # Reset mode state - cần chọn lại khi mở Chrome mới
        self._t2v_mode_selected = False
        self._image_mode_selected = False

    def _auto_kill_conflicting_chrome(self):
        """
        Tự động kill Chrome đang conflict với profile hoặc port.
        Gọi trước khi start Chrome mới.
        MẠNH: Kill TẤT CẢ Chrome có remote-debugging-port để tránh conflict.
        """
        import subprocess
        import platform

        killed_any = False

        if platform.system() == 'Windows':
            try:
                # === CÁCH 1: Kill TẤT CẢ Chrome có remote-debugging-port (tool Chrome) ===
                # Chrome của tool luôn có --remote-debugging-port, Chrome user thường không có
                result = subprocess.run(
                    ['wmic', 'process', 'where', "name='chrome.exe'", 'get', 'commandline,processid'],
                    capture_output=True, text=True, timeout=15
                )

                if result.returncode == 0:
                    lines = result.stdout.strip().split('\n')
                    for line in lines:
                        # Kill Chrome có remote-debugging-port (tool Chrome)
                        # HOẶC Chrome portable/ve3
                        if any(x in line for x in [
                            'remote-debugging-port',  # Tool Chrome
                            'GoogleChromePortable',
                            've3',
                            'chrome_profile',
                            str(self.profile_dir).replace('/', '\\')
                        ]):
                            # Lấy PID ở cuối dòng
                            parts = line.strip().split()
                            if parts:
                                pid = parts[-1]
                                if pid.isdigit():
                                    subprocess.run(['taskkill', '/F', '/PID', pid],
                                                 capture_output=True, timeout=5)
                                    self.log(f"  → Killed Chrome (PID: {pid})")
                                    killed_any = True

                # === CÁCH 2: Kill Chrome trên port 9222 (backup) ===
                if self._kill_chrome_on_port(self.chrome_port):
                    killed_any = True

            except Exception as e:
                self.log(f"  → Kill Chrome error: {e}", "WARN")

        else:
            # Linux/Mac
            try:
                self._kill_chrome_using_profile()
                self._kill_chrome_on_port(self.chrome_port)
            except:
                pass

        if killed_any:
            self.log("  → Đợi Chrome tắt hẳn...")
            time.sleep(3)  # Đợi Chrome tắt hẳn

    def _kill_chrome_on_port(self, port: int) -> bool:
        """
        Kill Chrome đang dùng debug port này.

        Args:
            port: Debug port (e.g., 9222)

        Returns:
            True nếu đã kill được process
        """
        import subprocess
        import platform

        try:
            if platform.system() == 'Windows':
                # Windows: Tìm process dùng port này
                result = subprocess.run(
                    ['netstat', '-ano'],
                    capture_output=True, text=True, timeout=10
                )

                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if f':{port}' in line and 'LISTENING' in line:
                            # Lấy PID ở cuối dòng
                            parts = line.strip().split()
                            if parts:
                                pid = parts[-1]
                                if pid.isdigit():
                                    # Force kill vì đây là Chrome zombie
                                    subprocess.run(
                                        ['taskkill', '/F', '/PID', pid],
                                        capture_output=True, timeout=5
                                    )
                                    self.log(f"  → Killed Chrome trên port {port} (PID: {pid})")
                                    return True
            else:
                # Linux/Mac
                result = subprocess.run(
                    ['lsof', '-t', '-i', f':{port}'],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    pid = result.stdout.strip().split('\n')[0]
                    if pid.isdigit():
                        subprocess.run(['kill', '-9', pid], capture_output=True, timeout=5)
                        self.log(f"  → Killed Chrome trên port {port} (PID: {pid})")
                        return True
        except Exception as e:
            pass

        return False

    def _kill_chrome_using_profile(self):
        """Tắt Chrome đang dùng profile này để tránh conflict."""
        import subprocess
        import platform

        profile_path = str(self.profile_dir.absolute())

        try:
            if platform.system() == 'Windows':
                # Windows: tìm và kill Chrome process dùng profile này
                result = subprocess.run(
                    ['wmic', 'process', 'where', "name='chrome.exe'", 'get', 'commandline,processid'],
                    capture_output=True, text=True, timeout=10
                )

                if result.returncode == 0:
                    lines = result.stdout.strip().split('\n')
                    for line in lines:
                        if profile_path.replace('/', '\\') in line or profile_path in line:
                            # Tìm PID ở cuối dòng
                            parts = line.strip().split()
                            if parts:
                                pid = parts[-1]
                                if pid.isdigit():
                                    # QUAN TRỌNG: Dùng graceful shutdown (không /F)
                                    # Để Chrome có thời gian lưu cookies/session
                                    subprocess.run(['taskkill', '/PID', pid],
                                                 capture_output=True, timeout=5)
                                    time.sleep(2)  # Đợi Chrome lưu dữ liệu
                                    # Nếu vẫn chưa tắt, mới force kill
                                    subprocess.run(['taskkill', '/F', '/PID', pid],
                                                 capture_output=True, timeout=5)
                                    self.log(f"  Đã tắt Chrome cũ (PID: {pid})")
            else:
                # Linux/Mac: dùng SIGTERM trước (graceful), sau đó mới SIGKILL
                result = subprocess.run(
                    ['pgrep', '-f', profile_path],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    pids = result.stdout.strip().split('\n')
                    for pid in pids:
                        if pid.isdigit():
                            # Graceful shutdown trước
                            subprocess.run(['kill', '-15', pid], capture_output=True, timeout=5)
                            time.sleep(2)  # Đợi Chrome lưu dữ liệu
                            # Force kill nếu cần
                            subprocess.run(['kill', '-9', pid], capture_output=True, timeout=5)
                            self.log(f"  Đã tắt Chrome cũ (PID: {pid})")

            # Đợi Chrome tắt hẳn
            time.sleep(1)

        except Exception as e:
            pass  # Không quan trọng nếu không kill được

    def _setup_proxy_auth(self):
        """
        Setup CDP để tự động xử lý proxy authentication.
        Dùng Network.setExtraHTTPHeaders với Proxy-Authorization.
        """
        if not hasattr(self, '_proxy_auth') or not self._proxy_auth:
            return

        username, password = self._proxy_auth
        if not username or not password:
            return

        try:
            import base64
            # Tạo Basic Auth header
            auth_string = f"{username}:{password}"
            auth_bytes = base64.b64encode(auth_string.encode()).decode()

            self.log(f"Setting up proxy auth for: {username}")

            # Thử dùng CDP Fetch API để handle auth challenges
            try:
                self.driver.run_cdp('Fetch.enable', handleAuthRequests=True)
                self.log("[v] CDP Fetch.enable OK")
            except Exception as e:
                self.log(f"CDP Fetch not supported: {e}", "WARN")

            self.log("[v] Proxy auth ready")
            self.log("  [!] Nếu vẫn lỗi, whitelist IP trên Webshare Dashboard")

        except Exception as e:
            self.log(f"[!] Proxy auth error: {e}", "WARN")
            self.log("    → Whitelist IP: 14.224.157.134 trên Webshare")

    def restart_chrome(self, rotate_ipv6: bool = False) -> bool:
        """
        Restart Chrome với proxy mới sau khi rotate.
        Proxy đã được rotate trước khi gọi hàm này.
        setup() sẽ lấy proxy mới từ manager.get_proxy_for_worker(worker_id).

        Args:
            rotate_ipv6: Nếu True, đổi IPv6 trước khi restart Chrome

        Returns:
            True nếu restart thành công
        """
        # === IPv6 ROTATION (khi bị 403 nhiều lần) ===
        # CHỈ Chrome 1 (worker_id=0) mới được rotate IPv6
        # Chrome 2+ chỉ dùng IPv6 hiện tại (do Chrome 1 set)
        if rotate_ipv6 and self.worker_id > 0:
            self.log(f"[Worker{self.worker_id}] Skip IPv6 rotation (chỉ Chrome 1 rotate)")
            rotate_ipv6 = False

        if rotate_ipv6:
            try:
                from modules.ipv6_rotator import get_ipv6_rotator
                rotator = get_ipv6_rotator()
                if rotator and rotator.enabled:
                    self.log("[SYNC] Rotating IPv6 before restart...")
                    new_ip = rotator.rotate()
                    if new_ip:
                        self.log(f"[v] IPv6 changed to: {new_ip}")
                        # Cập nhật SOCKS5 proxy với IPv6 mới
                        if hasattr(self, '_ipv6_proxy') and self._ipv6_proxy:
                            self._ipv6_proxy.set_ipv6(new_ip)
                            self.log(f"[v] SOCKS5 proxy updated")
                    else:
                        self.log("[WARN] IPv6 rotation failed, continuing anyway...")
            except Exception as e:
                self.log(f"[WARN] IPv6 rotation error: {e}")

        if self._use_webshare:
            # Lấy proxy mới để log
            from webshare_proxy import get_proxy_manager
            manager = get_proxy_manager()
            new_proxy = manager.get_proxy_for_worker(self.worker_id)
            if new_proxy:
                self.log(f"[SYNC] Restart Chrome [Worker {self.worker_id}] với proxy mới: {new_proxy.endpoint}")
            else:
                self.log(f"[SYNC] Restart Chrome [Worker {self.worker_id}]...")
        else:
            self.log("[SYNC] Restart Chrome...")

        # Close Chrome và proxy bridge hiện tại
        self.close()

        time.sleep(2)

        # Restart Chrome với proxy mới - setup() sẽ lấy proxy từ manager
        # Lấy saved project URL để vào lại đúng project
        saved_project_url = getattr(self, '_current_project_url', None)
        if saved_project_url:
            self.log(f"  → Reusing project: {saved_project_url[:50]}...")

        # GIỮ NGUYÊN skip_mode_selection từ lần setup đầu tiên
        # Nếu Chrome 2 (video) đã skip mode selection, thì khi restart cũng skip
        skip_mode = getattr(self, '_skip_mode_selection', False)
        if skip_mode:
            self.log("  → Skip mode selection (video mode đã được set)")

        if self.setup(project_url=saved_project_url, skip_mode_selection=skip_mode):
            self.log("[v] Chrome restarted thành công!")

            # Chọn lại mode "Tạo hình ảnh" ngay sau restart (nếu không phải video mode)
            # Đảm bảo mode được set đúng trước khi tiếp tục generate
            if not skip_mode:
                self.log("  → Chọn lại mode 'Tạo hình ảnh'...")
                if self.switch_to_image_mode():
                    self._image_mode_selected = True
                    self.log("  [v] Image mode selected")
                else:
                    self.log("  [WARN] Không chọn được mode, sẽ thử lại khi generate", "WARN")

            return True
        else:
            self.log("[x] Không restart được Chrome", "ERROR")
            return False

    @property
    def is_ready(self) -> bool:
        """Kiểm tra API đã sẵn sàng chưa."""
        return self._ready and self.driver is not None


# Factory function
def create_drission_api(
    profile_dir: str = "./chrome_profile",
    log_callback: Optional[Callable] = None,
    webshare_enabled: bool = True,  # BẬT Webshare by default
    worker_id: int = 0,  # Worker ID cho proxy rotation
    machine_id: int = 1,  # Máy số mấy (1-99) - tránh trùng session
) -> DrissionFlowAPI:
    """
    Tạo DrissionFlowAPI instance.

    Args:
        profile_dir: Thư mục Chrome profile
        log_callback: Callback để log
        webshare_enabled: Dùng Webshare proxy pool (default True)
        worker_id: Worker ID cho proxy rotation (mỗi Chrome có proxy riêng)
        machine_id: Máy số mấy (1-99), mỗi máy cách nhau 30000 session

    Returns:
        DrissionFlowAPI instance
    """
    return DrissionFlowAPI(
        profile_dir=profile_dir,
        log_callback=log_callback,
        webshare_enabled=webshare_enabled,
        worker_id=worker_id,
        machine_id=machine_id,
    )
