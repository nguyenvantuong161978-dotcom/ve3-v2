"""
VE3 Tool - Image to Video Converter
====================================
Chuyển đổi ảnh sang video sử dụng Google Veo 3 API.

Flow:
1. Đọc ảnh từ thư mục img/
2. Upload ảnh lên Google Flow để lấy mediaId
3. Tạo video từ ảnh (I2V) qua API
4. Download video và thay thế ảnh gốc

IMPORTANT: Uses GoogleFlowAPI internally for video generation
to ensure same code path as working testvideo.py script.
"""

import os
import time
import json
import shutil
import requests
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Callable
from datetime import datetime
from dataclasses import dataclass
import base64

# Import GoogleFlowAPI - the working implementation
from .google_flow_api import (
    GoogleFlowAPI,
    VideoAspectRatio,
    VideoModel,
    PaygateTier
)


@dataclass
class VideoConversionResult:
    """Kết quả chuyển đổi ảnh sang video."""
    image_path: Path
    video_path: Optional[Path] = None
    video_url: Optional[str] = None
    media_id: Optional[str] = None
    status: str = "pending"  # pending, uploading, generating, downloading, completed, failed
    error: Optional[str] = None
    prompt: str = ""

    @property
    def is_completed(self) -> bool:
        return self.status == "completed" and self.video_path and self.video_path.exists()

    @property
    def is_failed(self) -> bool:
        return self.status == "failed"


class ImageToVideoConverter:
    """
    Chuyển đổi ảnh sang video sử dụng Google Veo 3 API.

    IMPORTANT: Uses GoogleFlowAPI internally - same code path as testvideo.py
    that has been verified to work.

    Hỗ trợ:
    - Direct API (cần bearer token)
    - Proxy API (nanoai.pics - bypass captcha)
    """

    GOOGLE_BASE = "https://aisandbox-pa.googleapis.com"
    PROXY_BASE = "https://flow-api.nanoai.pics/api/fix"

    # Video models
    I2V_MODEL_FAST = "veo_3_0_r2v_fast_ultra"
    I2V_MODEL_QUALITY = "veo_3_0_r2v"

    def __init__(
        self,
        project_path: str,
        bearer_token: str,
        project_id: str,
        proxy_token: Optional[str] = None,
        use_proxy: bool = True,
        video_model: str = None,
        log_callback: Optional[Callable] = None
    ):
        """
        Khởi tạo converter.

        Args:
            project_path: Đường dẫn thư mục project
            bearer_token: Google Flow bearer token (ya29.xxx)
            project_id: Google Flow project ID
            proxy_token: Token cho proxy API (nanoai.pics)
            use_proxy: Sử dụng proxy để bypass captcha
            video_model: Model video (fast/quality)
            log_callback: Function để log
        """
        self.project_path = Path(project_path)
        self.bearer_token = bearer_token
        self.project_id = project_id
        self.proxy_token = proxy_token
        self.use_proxy = use_proxy and bool(proxy_token)
        self.video_model = video_model or self.I2V_MODEL_FAST
        self.log_callback = log_callback

        # Thư mục
        self.img_dir = self.project_path / "img"
        self.video_dir = self.project_path / "video"
        self.backup_dir = self.project_path / "img_backup"

        # Create GoogleFlowAPI instance - SAME AS TESTVIDEO.PY
        self._flow_api = GoogleFlowAPI(
            bearer_token=self.bearer_token,
            project_id=self.project_id,
            proxy_api_token=self.proxy_token,
            use_proxy=self.use_proxy,
            verbose=True,
            timeout=300  # 5 minutes timeout
        )

    def _log(self, message: str, level: str = "info"):
        """Log message."""
        if self.log_callback:
            self.log_callback(message, level)
        else:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] [{level.upper()}] {message}")

    def check_proxy_available(self) -> bool:
        """Kiểm tra proxy API có hoạt động không."""
        if not self.use_proxy:
            return True  # Không dùng proxy thì ok

        try:
            response = requests.get(
                f"{self.PROXY_BASE}/task-status?taskId=health-check",
                headers=self._proxy_headers(),
                timeout=10
            )
            # 401/403 = proxy hoạt động nhưng taskId không valid (ok)
            # 500/503 = proxy down
            if response.status_code in [200, 400, 401, 403, 404]:
                return True
            self._log(f"Proxy không hoạt động: {response.status_code}", "error")
            return False
        except Exception as e:
            self._log(f"Không thể kết nối proxy: {e}", "error")
            return False

    def _google_headers(self) -> Dict[str, str]:
        """Headers cho Google API."""
        return {
            "Authorization": f"Bearer {self.bearer_token}",
            "Content-Type": "application/json"
        }

    def _proxy_headers(self) -> Dict[str, str]:
        """Headers cho Proxy API."""
        return {
            "Authorization": f"Bearer {self.proxy_token}",
            "Content-Type": "application/json"
        }

    def get_images_to_convert(self, count: int = None, full: bool = False) -> List[Path]:
        """
        Lấy danh sách ảnh cần chuyển sang video.

        Args:
            count: Số lượng ảnh (None = tất cả)
            full: True = tất cả ảnh

        Returns:
            Danh sách đường dẫn ảnh
        """
        if not self.img_dir.exists():
            self._log(f"Thư mục img không tồn tại: {self.img_dir}", "error")
            return []

        # Lấy tất cả ảnh (png, jpg, jpeg, webp)
        images = []
        for ext in ["*.png", "*.jpg", "*.jpeg", "*.webp"]:
            images.extend(self.img_dir.glob(ext))

        # Sắp xếp theo tên (scene_1, scene_2, ...)
        images = sorted(images, key=lambda p: p.stem)

        if full or count is None:
            return images

        return images[:count]

    def upload_image_for_media_id(self, image_path: Path) -> Optional[str]:
        """
        Upload ảnh lên Google Flow để lấy mediaId.

        QUAN TRỌNG: Dùng GoogleFlowAPI.upload_image() để upload đúng cách.
        Endpoint đúng là flowMedia:uploadImage với tool=ASSET_MANAGER.

        Args:
            image_path: Đường dẫn ảnh

        Returns:
            mediaId (name) hoặc None nếu lỗi
        """
        self._log(f"Uploading image via GoogleFlowAPI: {image_path.name}")

        try:
            # Dùng GoogleFlowAPI.upload_image() - endpoint đúng!
            from .google_flow_api import ImageInputType
            success, img_input, error = self._flow_api.upload_image(
                image_path=image_path,
                image_type=ImageInputType.REFERENCE
            )

            if success and img_input and img_input.name:
                self._log(f"Upload successful: {img_input.name[:60]}...")
                return img_input.name
            else:
                self._log(f"Upload failed: {error}", "error")
                # Fallback: try proxy upload
                return self._upload_via_proxy_fallback(image_path)

        except Exception as e:
            self._log(f"Upload error: {e}", "error")
            # Fallback: try proxy upload
            return self._upload_via_proxy_fallback(image_path)

    def _upload_via_proxy_fallback(self, image_path: Path) -> Optional[str]:
        """
        Fallback: Upload qua proxy API khi direct upload thất bại.
        Dùng endpoint flowMedia:uploadImage đúng cách.
        """
        self._log(f"Trying proxy upload fallback...")

        try:
            # Đọc ảnh và encode base64
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode()

            # Xác định mime type
            ext = image_path.suffix.lower()
            mime_types = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp"
            }
            mime_type = mime_types.get(ext, "image/png")

            # Detect aspect ratio from image
            from PIL import Image
            with Image.open(image_path) as img:
                w, h = img.size
                if w > h:
                    aspect = "IMAGE_ASPECT_RATIO_LANDSCAPE"
                elif h > w:
                    aspect = "IMAGE_ASPECT_RATIO_PORTRAIT"
                else:
                    aspect = "IMAGE_ASPECT_RATIO_SQUARE"

            # Build correct upload request - dùng ASSET_MANAGER tool
            body_json = {
                "clientContext": {
                    "sessionId": f";{int(time.time() * 1000)}",
                    "tool": "ASSET_MANAGER"
                },
                "imageInput": {
                    "aspectRatio": aspect,
                    "isUserUploaded": True,
                    "mimeType": mime_type,
                    "rawImageBytes": image_data
                }
            }

            payload = {
                "body_json": body_json,
                "flow_auth_token": self.bearer_token,
                "flow_url": f"{self.GOOGLE_BASE}/v1/projects/{self.project_id}/flowMedia:uploadImage"
            }

            response = requests.post(
                f"{self.PROXY_BASE}/create-image-veo3",
                headers=self._proxy_headers(),
                json=payload,
                timeout=60
            )

            if response.status_code != 200:
                self._log(f"Proxy upload failed: {response.status_code}", "error")
                return None

            task_id = response.json().get("taskId")
            if not task_id:
                self._log("No taskId in proxy response", "error")
                return None

            # Poll for result
            for i in range(60):
                status_resp = requests.get(
                    f"{self.PROXY_BASE}/task-status?taskId={task_id}",
                    headers=self._proxy_headers(),
                    timeout=30
                )

                if status_resp.status_code == 200:
                    status_json = status_resp.json()
                    result = status_json.get("result", {})

                    # Check for error
                    if "error" in result:
                        self._log(f"Proxy upload error: {result['error']}", "error")
                        return None

                    # Try to extract name from various formats
                    media_name = None

                    if "name" in result:
                        media_name = result["name"]
                    elif "media" in result:
                        media = result["media"]
                        if isinstance(media, list) and len(media) > 0:
                            media_name = media[0].get("name")
                        elif isinstance(media, dict):
                            media_name = media.get("name")
                    elif "imageInput" in result:
                        media_name = result["imageInput"].get("name")
                    elif "mediaName" in result:
                        media_name = result["mediaName"]

                    if media_name:
                        self._log(f"Proxy upload successful: {media_name[:60]}...")
                        return media_name

                if i % 10 == 0:
                    self._log(f"Waiting for upload result... ({i*2}s)")

                time.sleep(2)

            self._log("Upload timeout", "error")
            return None

        except Exception as e:
            self._log(f"Proxy upload fallback error: {e}", "error")
            return None

    def create_video_from_image(
        self,
        media_id: str,
        prompt: str = "",
        aspect_ratio: str = "VIDEO_ASPECT_RATIO_LANDSCAPE"
    ) -> Tuple[Optional[str], Optional[List[Dict]]]:
        """
        Tạo video từ ảnh đã upload.

        Args:
            media_id: Media ID của ảnh
            prompt: Prompt mô tả chuyển động
            aspect_ratio: Tỷ lệ video

        Returns:
            Tuple[video_url, operations] hoặc (None, None) nếu lỗi
        """
        self._log(f"Creating video from media: {media_id[:50]}...")

        session_id = f";{int(time.time() * 1000)}"
        scene_id = f"scene-{int(time.time())}"

        # Default prompt nếu không có
        if not prompt:
            prompt = "Subtle motion, cinematic, slow movement"

        # Build request - KHÔNG có recaptchaToken trong proxy mode
        request_data = {
            "aspectRatio": aspect_ratio,
            "metadata": {"sceneId": scene_id},
            "referenceImages": [{
                "imageUsageType": "IMAGE_USAGE_TYPE_ASSET",
                "mediaId": media_id
            }],
            "seed": int(time.time()) % 100000,
            "textInput": {"prompt": prompt},
            "videoModelKey": self.video_model
        }

        body_json = {
            "clientContext": {
                "sessionId": session_id,
                "projectId": self.project_id,
                "tool": "PINHOLE",
                "userPaygateTier": "PAYGATE_TIER_TWO"
            },
            "requests": [request_data]
        }

        try:
            if self.use_proxy:
                result = self._create_video_via_proxy(body_json)
                if result and result[1]:  # Has operations
                    return result
                # Fallback to direct when proxy fails
                self._log("Proxy failed, trying direct video creation...", "warn")
                return self._create_video_direct(body_json)
            else:
                return self._create_video_direct(body_json)
        except Exception as e:
            self._log(f"Create video error: {e}", "error")
            return None, None

    def _create_video_direct(self, body_json: Dict) -> Tuple[Optional[str], Optional[List[Dict]]]:
        """Tạo video trực tiếp qua Google API."""
        url = f"{self.GOOGLE_BASE}/v1/video:batchAsyncGenerateVideoReferenceImages"

        response = requests.post(
            url,
            headers=self._google_headers(),
            json=body_json,
            timeout=60
        )

        if response.status_code != 200:
            self._log(f"Create video failed: {response.status_code}", "error")
            return None, None

        result = response.json()
        operations = result.get("operations", [])

        if operations:
            return None, operations  # Cần poll để lấy video URL

        return None, None

    def _create_video_via_proxy(self, body_json: Dict) -> Tuple[Optional[str], Optional[List[Dict]]]:
        """Tạo video qua proxy API - format giống GoogleFlowAPI."""

        # === DEBUG: Log full request ===
        self._log(f"[I2V] === REQUEST BODY ===")
        self._log(f"[I2V] body_json: {json.dumps(body_json)[:800]}")

        payload = {
            "body_json": body_json,
            "flow_auth_token": self.bearer_token,
            "flow_url": f"{self.GOOGLE_BASE}/v1/video:batchAsyncGenerateVideoReferenceImages"
        }

        self._log(f"[I2V] Calling proxy API...")
        self._log(f"[I2V] flow_url: {payload['flow_url']}")

        response = requests.post(
            f"{self.PROXY_BASE}/create-video-veo3",
            headers=self._proxy_headers(),
            json=payload,
            timeout=60
        )

        if response.status_code != 200:
            self._log(f"[I2V] Proxy failed: {response.status_code} - {response.text[:200]}", "error")
            return None, None

        resp_json = response.json()
        task_id = resp_json.get("taskId")
        if not task_id:
            self._log(f"[I2V] No taskId in response: {resp_json}", "error")
            return None, None

        self._log(f"[I2V] Task created: {task_id}")

        # Poll proxy để lấy operations
        for i in range(30):
            status_resp = requests.get(
                f"{self.PROXY_BASE}/task-status?taskId={task_id}",
                headers=self._proxy_headers(),
                timeout=30
            )

            if status_resp.status_code == 200:
                status_json = status_resp.json()
                result = status_json.get("result", {})

                # Check for error in result - log full error details
                if "error" in result:
                    error_info = result.get("error", {})
                    if isinstance(error_info, dict):
                        error_msg = error_info.get("message", str(error_info))
                        error_code = error_info.get("code", "")
                        error_status = error_info.get("status", "")
                        self._log(f"[I2V] API Error: {error_msg}", "error")
                        self._log(f"[I2V] Error code: {error_code}, status: {error_status}")
                        # Log full error for debugging
                        self._log(f"[I2V] Full error: {json.dumps(error_info)[:500]}")
                    else:
                        self._log(f"[I2V] API Error: {error_info}", "error")
                    return None, None

                operations = result.get("operations", [])
                if operations:
                    self._log(f"[I2V] Got operations, starting video generation...")
                    return None, operations

                # Still processing
                if i % 5 == 0:
                    self._log(f"[I2V] Waiting for operations... ({i*3}s)")

            time.sleep(3)

        self._log(f"[I2V] Timeout waiting for operations", "error")
        return None, None

    def poll_video_status(self, operations: List[Dict], timeout: int = 300) -> Optional[str]:
        """
        Poll Google API để lấy video URL.

        Args:
            operations: Operations array từ create video
            timeout: Timeout (giây) - video cần 3-5 phút

        Returns:
            Video URL hoặc None
        """
        self._log("Polling video status...")

        url = f"{self.GOOGLE_BASE}/v1/video:batchCheckAsyncVideoGenerationStatus"
        start_time = time.time()

        # Extract operation names từ operations array
        operation_names = []
        for op in operations:
            op_obj = op.get("operation", {})
            op_name = op_obj.get("name")
            if op_name:
                operation_names.append(op_name)

        if not operation_names:
            self._log("No operation names found in operations", "error")
            return None

        self._log(f"Polling operation: {operation_names[0][:60]}...")

        while time.time() - start_time < timeout:
            try:
                # Dùng operationNames thay vì operations
                response = requests.post(
                    url,
                    headers=self._google_headers(),
                    json={"operationNames": operation_names},
                    timeout=30
                )

                if response.status_code == 200:
                    result = response.json()
                    ops = result.get("operations", [])

                    if ops:
                        op = ops[0]
                        status = op.get("status", "")

                        # Check for success - API trả về SUCCEEDED không phải SUCCESSFUL
                        if status in ["MEDIA_GENERATION_STATUS_SUCCEEDED", "MEDIA_GENERATION_STATUS_COMPLETE"]:
                            # Video URL nằm trong op.media[0].video.url
                            video_url = None
                            media_list = op.get("media", [])
                            if media_list:
                                video_info = media_list[0].get("video", {})
                                video_url = video_info.get("url") or video_info.get("videoUrl") or video_info.get("fifeUrl")

                            # Fallback: thử path cũ
                            if not video_url:
                                video_url = op.get("operation", {}).get("metadata", {}).get("video", {}).get("fifeUrl")

                            if video_url:
                                self._log("Video generation completed!")
                                return video_url
                            else:
                                self._log(f"Video completed but no URL found in response", "warn")
                                self._log(f"Response: {json.dumps(op)[:500]}")

                        elif "ERROR" in status or "FAILED" in status:
                            error_msg = op.get("error", status)
                            self._log(f"Video generation failed: {error_msg}", "error")
                            return None

                        elif status == "MEDIA_GENERATION_STATUS_PENDING":
                            # Still processing
                            elapsed = int(time.time() - start_time)
                            if elapsed % 15 == 0:  # Log mỗi 15 giây
                                self._log(f"Video generating... ({elapsed}s)")

                elif response.status_code == 401:
                    self._log("Token expired!", "error")
                    return None
                else:
                    self._log(f"Poll response: {response.status_code}", "warn")

            except Exception as e:
                self._log(f"Poll error: {e}", "warn")

            time.sleep(5)

        self._log("Video generation timeout!", "error")
        return None

    def download_video(self, video_url: str, output_path: Path) -> bool:
        """
        Download video từ URL.

        Args:
            video_url: URL video
            output_path: Đường dẫn lưu

        Returns:
            True nếu thành công
        """
        self._log(f"Downloading video to: {output_path.name}")

        try:
            response = requests.get(video_url, stream=True, timeout=120)

            if response.status_code == 200:
                output_path.parent.mkdir(parents=True, exist_ok=True)

                with open(output_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                self._log(f"Downloaded: {output_path.name}")
                return True
            else:
                self._log(f"Download failed: {response.status_code}", "error")
                return False

        except Exception as e:
            self._log(f"Download error: {e}", "error")
            return False

    def convert_image_to_video(
        self,
        image_path: Path,
        prompt: str = "",
        replace_image: bool = True,
        cached_media_name: str = ""
    ) -> VideoConversionResult:
        """
        Chuyển đổi một ảnh sang video.

        IMPORTANT: Uses GoogleFlowAPI.generate_video() internally
        - Same code path as testvideo.py that has been verified to work

        Args:
            image_path: Đường dẫn ảnh
            prompt: Prompt mô tả chuyển động
            replace_image: Thay thế ảnh bằng video
            cached_media_name: Media name đã cache từ lúc tạo ảnh (bỏ qua upload)

        Returns:
            VideoConversionResult
        """
        result = VideoConversionResult(image_path=image_path, prompt=prompt)

        try:
            # Step 1: Get media_id - dùng cached nếu có, không thì upload
            if cached_media_name:
                # Dùng media_name đã cache từ lúc tạo ảnh - KHÔNG CẦN UPLOAD LẠI
                self._log(f"Sử dụng cached media_name: {cached_media_name[:50]}...")
                result.status = "cached"
                media_id = cached_media_name
            else:
                # Không có cache - phải upload ảnh để lấy media_id mới
                result.status = "uploading"
                media_id = self.upload_image_for_media_id(image_path)

                if not media_id:
                    result.status = "failed"
                    result.error = "Failed to upload image"
                    return result

            result.media_id = media_id

            # Step 2: Generate video using GoogleFlowAPI (SAME AS TESTVIDEO.PY)
            result.status = "generating"

            # Default prompt if not provided
            if not prompt:
                prompt = "Subtle motion, cinematic, slow movement"

            self._log(f"[I2V] Using GoogleFlowAPI.generate_video...")
            self._log(f"[I2V] reference_image_id: {media_id[:60]}...")
            self._log(f"[I2V] prompt: {prompt[:80]}...")

            # Call GoogleFlowAPI.generate_video - EXACTLY LIKE TESTVIDEO.PY
            success, video_result, error = self._flow_api.generate_video(
                prompt=prompt,
                aspect_ratio=VideoAspectRatio.LANDSCAPE,
                reference_image_id=media_id  # Use media_name as reference - SAME AS TESTVIDEO.PY LINE 115
            )

            if not success:
                result.status = "failed"
                result.error = f"Video generation failed: {error}"
                self._log(f"[I2V] Failed: {error}", "error")
                return result

            if not video_result.video_url:
                result.status = "failed"
                result.error = "Video generation completed but no URL returned"
                return result

            result.video_url = video_result.video_url
            self._log(f"[I2V] Video URL: {video_result.video_url[:60]}...")

            # Step 3: Download video
            result.status = "downloading"
            video_filename = image_path.stem + ".mp4"
            video_path = self.video_dir / video_filename

            # Use GoogleFlowAPI download method
            downloaded_path = self._flow_api.download_video(video_result, self.video_dir, image_path.stem)
            if not downloaded_path:
                result.status = "failed"
                result.error = "Failed to download video"
                return result

            result.video_path = downloaded_path

            # Step 4: Replace image with video (optional)
            if replace_image:
                # Backup ảnh gốc
                self.backup_dir.mkdir(parents=True, exist_ok=True)
                backup_path = self.backup_dir / image_path.name
                shutil.copy2(image_path, backup_path)

                # Xóa ảnh gốc
                image_path.unlink()

                # Copy video vào thư mục img (với tên giống ảnh nhưng .mp4)
                img_video_path = self.img_dir / video_filename
                shutil.copy2(downloaded_path, img_video_path)

                self._log(f"Replaced {image_path.name} with {video_filename}")

            result.status = "completed"
            self._log(f"[I2V] Completed: {video_filename}")
            return result

        except Exception as e:
            result.status = "failed"
            result.error = str(e)
            self._log(f"Conversion error: {e}", "error")
            return result

    def convert_batch(
        self,
        count: int = None,
        full: bool = False,
        prompt: str = "",
        replace_images: bool = True,
        progress_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        Chuyển đổi nhiều ảnh sang video.

        Args:
            count: Số lượng ảnh (None = tất cả)
            full: True = tất cả ảnh
            prompt: Prompt chung cho tất cả
            replace_images: Thay thế ảnh bằng video
            progress_callback: Callback(current, total, result)

        Returns:
            Dict với thống kê
        """
        images = self.get_images_to_convert(count, full)

        if not images:
            self._log("Không có ảnh để chuyển đổi!", "warn")
            return {"success": 0, "failed": 0, "total": 0}

        self._log(f"Bắt đầu chuyển {len(images)} ảnh sang video...")

        # Tạo thư mục video
        self.video_dir.mkdir(parents=True, exist_ok=True)

        results = []
        success_count = 0
        failed_count = 0

        for i, image_path in enumerate(images):
            self._log(f"[{i+1}/{len(images)}] Processing: {image_path.name}")

            result = self.convert_image_to_video(
                image_path,
                prompt=prompt,
                replace_image=replace_images
            )

            results.append(result)

            if result.is_completed:
                success_count += 1
            else:
                failed_count += 1

            if progress_callback:
                progress_callback(i + 1, len(images), result)

            # Delay giữa các request
            if i < len(images) - 1:
                time.sleep(2)

        self._log(f"Hoàn thành: {success_count} thành công, {failed_count} thất bại")

        return {
            "success": success_count,
            "failed": failed_count,
            "total": len(images),
            "results": results
        }


def create_video_converter(
    project_path: str,
    config: Dict[str, Any],
    log_callback: Optional[Callable] = None
) -> Optional[ImageToVideoConverter]:
    """
    Factory function để tạo converter từ config.

    Args:
        project_path: Đường dẫn project
        config: Config dict (từ settings.yaml)
        log_callback: Log callback

    Returns:
        ImageToVideoConverter hoặc None
    """
    bearer_token = config.get("flow_bearer_token", "")
    project_id = config.get("flow_project_id", "")
    proxy_token = config.get("proxy_api_token", "")

    if not bearer_token:
        if log_callback:
            log_callback("Thiếu flow_bearer_token!", "error")
        return None

    if not project_id:
        # Tạo project ID mới
        import uuid
        project_id = str(uuid.uuid4())

    video_model = config.get("video_model", "fast")
    model_map = {
        "fast": ImageToVideoConverter.I2V_MODEL_FAST,
        "quality": ImageToVideoConverter.I2V_MODEL_QUALITY
    }

    return ImageToVideoConverter(
        project_path=project_path,
        bearer_token=bearer_token,
        project_id=project_id,
        proxy_token=proxy_token,
        use_proxy=bool(proxy_token),
        video_model=model_map.get(video_model, ImageToVideoConverter.I2V_MODEL_FAST),
        log_callback=log_callback
    )
