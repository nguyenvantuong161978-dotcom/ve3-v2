"""
VE3 Tool - Google ImageFX API Module
=====================================
Module để tự động tạo ảnh bằng Google ImageFX (Imagen) API.

API được reverse-engineer từ labs.google/fx/tools/image-fx
Tham khảo: https://github.com/rohitaryal/imageFX-api

Yêu cầu:
- Cookie từ tài khoản Google đã đăng nhập vào labs.google
- Google One Ultra subscription (để có Nano Banana Pro / không giới hạn)

Cách lấy Cookie:
1. Đăng nhập vào https://labs.google/fx/tools/image-fx
2. Mở DevTools (F12) -> Network tab
3. Tạo 1 ảnh bất kỳ
4. Tìm request đến aisandbox-pa.googleapis.com
5. Copy toàn bộ giá trị Cookie từ Request Headers
"""

import json
import time
import base64
import re
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

import requests

from modules.utils import get_logger, sanitize_filename
from modules.excel_manager import Scene, PromptWorkbook


# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================

class ImageModel(Enum):
    """Các model ImageFX hỗ trợ"""
    IMAGEN_3_0 = "IMAGEN_3_0"
    IMAGEN_3_5 = "IMAGEN_3_5"
    IMAGEN_4 = "IMAGEN_4"


class AspectRatio(Enum):
    """Tỷ lệ khung hình"""
    SQUARE = "IMAGE_ASPECT_RATIO_SQUARE"      # 1:1
    PORTRAIT = "IMAGE_ASPECT_RATIO_PORTRAIT"  # 3:4
    LANDSCAPE = "IMAGE_ASPECT_RATIO_LANDSCAPE"  # 4:3
    PORTRAIT_16_9 = "IMAGE_ASPECT_RATIO_PORTRAIT_16_9"  # 9:16
    LANDSCAPE_16_9 = "IMAGE_ASPECT_RATIO_LANDSCAPE_16_9"  # 16:9


# API Endpoints
IMAGEFX_API_BASE = "https://aisandbox-pa.googleapis.com"
IMAGEFX_GENERATE_ENDPOINT = "/v1:runImageFx"
IMAGEFX_FETCH_ENDPOINT = "/v1:fetchMedia"

# Default headers
DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://labs.google",
    "Referer": "https://labs.google/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class GeneratedImage:
    """Đại diện cho một ảnh đã được tạo"""
    media_id: str
    encoded_image: str  # Base64 encoded
    seed: Optional[int] = None
    prompt: Optional[str] = None
    
    def save(self, output_dir: Path, filename: Optional[str] = None) -> Path:
        """
        Lưu ảnh xuống đĩa.
        
        Args:
            output_dir: Thư mục lưu ảnh
            filename: Tên file (nếu None sẽ dùng media_id)
            
        Returns:
            Path đến file đã lưu
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        if filename is None:
            filename = f"{self.media_id}.png"
        
        if not filename.endswith(('.png', '.jpg', '.jpeg', '.webp')):
            filename += '.png'
        
        output_path = output_dir / filename
        
        # Decode base64 và lưu
        image_data = base64.b64decode(self.encoded_image)
        with open(output_path, 'wb') as f:
            f.write(image_data)
        
        return output_path
    
    def get_bytes(self) -> bytes:
        """Trả về binary data của ảnh"""
        return base64.b64decode(self.encoded_image)


@dataclass
class GenerationResult:
    """Kết quả của một lần generate"""
    success: bool
    images: List[GeneratedImage]
    error: Optional[str] = None
    raw_response: Optional[Dict] = None


# ============================================================================
# IMAGEFX CLIENT
# ============================================================================

class ImageFXClient:
    """
    Client để gọi Google ImageFX API.
    
    Sử dụng cookie-based authentication.
    """
    
    def __init__(
        self,
        cookie: str,
        model: str = "IMAGEN_4",
        aspect_ratio: str = "IMAGE_ASPECT_RATIO_LANDSCAPE_16_9",
        timeout: int = 120,
        retry_count: int = 3,
        retry_delay: float = 5.0
    ):
        """
        Khởi tạo ImageFX client.
        
        Args:
            cookie: Google cookie string (từ DevTools)
            model: Model để sử dụng (IMAGEN_3_0, IMAGEN_3_5, IMAGEN_4)
            aspect_ratio: Tỷ lệ khung hình
            timeout: Timeout cho mỗi request (giây)
            retry_count: Số lần retry khi gặp lỗi
            retry_delay: Thời gian chờ giữa các lần retry (giây)
        """
        self.cookie = cookie
        self.model = model
        self.aspect_ratio = aspect_ratio
        self.timeout = timeout
        self.retry_count = retry_count
        self.retry_delay = retry_delay
        
        self.session = requests.Session()
        self.logger = get_logger("imagefx_client")
        
        # Set up session headers
        self._setup_session()
    
    def _setup_session(self) -> None:
        """Cấu hình session với headers và cookies"""
        self.session.headers.update(DEFAULT_HEADERS)
        
        # Parse và set cookies
        if self.cookie:
            self.session.headers["Cookie"] = self.cookie
    
    def _extract_authorization(self) -> Optional[str]:
        """
        Trích xuất authorization token từ __NEXT_DATA__ script.
        
        Một số phiên bản API cần authorization header thay vì cookie.
        """
        try:
            # Fetch trang ImageFX để lấy __NEXT_DATA__
            response = self.session.get(
                "https://labs.google/fx/tools/image-fx",
                timeout=30
            )
            
            if response.status_code != 200:
                return None
            
            # Tìm __NEXT_DATA__ script
            match = re.search(
                r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                response.text,
                re.DOTALL
            )
            
            if match:
                data = json.loads(match.group(1))
                # Navigate to authorization token
                # Path có thể thay đổi tùy phiên bản
                props = data.get("props", {})
                page_props = props.get("pageProps", {})
                return page_props.get("authorization")
            
            return None
            
        except Exception as e:
            self.logger.warning(f"Could not extract authorization: {e}")
            return None
    
    def generate_image(
        self,
        prompt: str,
        count: int = 4,
        seed: Optional[int] = None,
        model: Optional[str] = None,
        aspect_ratio: Optional[str] = None
    ) -> GenerationResult:
        """
        Tạo ảnh từ text prompt.
        
        Args:
            prompt: Text mô tả ảnh cần tạo
            count: Số lượng ảnh (1-4)
            seed: Seed để tạo ảnh reproducible
            model: Override model (nếu None dùng default)
            aspect_ratio: Override aspect ratio
            
        Returns:
            GenerationResult chứa danh sách ảnh hoặc lỗi
        """
        if not prompt:
            return GenerationResult(
                success=False,
                images=[],
                error="Prompt không được để trống"
            )
        
        count = max(1, min(4, count))  # Clamp 1-4
        
        model = model or self.model
        aspect_ratio = aspect_ratio or self.aspect_ratio
        
        # Build request body
        request_body = self._build_request_body(
            prompt=prompt,
            count=count,
            seed=seed,
            model=model,
            aspect_ratio=aspect_ratio
        )
        
        # Execute with retry
        for attempt in range(self.retry_count):
            try:
                self.logger.info(f"Generating image (attempt {attempt + 1}/{self.retry_count})")
                self.logger.debug(f"Prompt: {prompt[:100]}...")
                
                response = self.session.post(
                    f"{IMAGEFX_API_BASE}{IMAGEFX_GENERATE_ENDPOINT}",
                    json=request_body,
                    timeout=self.timeout
                )
                
                if response.status_code == 200:
                    return self._parse_response(response.json(), prompt)
                
                elif response.status_code == 401:
                    self.logger.error("Authentication failed. Cookie có thể đã hết hạn.")
                    return GenerationResult(
                        success=False,
                        images=[],
                        error="Authentication failed - Cookie expired"
                    )
                
                elif response.status_code == 429:
                    self.logger.warning("Rate limited. Waiting...")
                    time.sleep(self.retry_delay * 2)
                    continue
                
                elif response.status_code == 400:
                    error_text = response.text
                    self.logger.error(f"Bad request: {error_text[:500]}")
                    
                    # Check for specific errors
                    if "SAFETY" in error_text.upper() or "BLOCKED" in error_text.upper():
                        return GenerationResult(
                            success=False,
                            images=[],
                            error="Prompt bị chặn bởi safety filter"
                        )
                    
                    return GenerationResult(
                        success=False,
                        images=[],
                        error=f"Bad request: {error_text[:200]}"
                    )
                
                else:
                    self.logger.warning(
                        f"Request failed with status {response.status_code}"
                    )
                    
            except requests.Timeout:
                self.logger.warning(f"Request timeout (attempt {attempt + 1})")
                
            except requests.RequestException as e:
                self.logger.error(f"Request error: {e}")
            
            # Wait before retry
            if attempt < self.retry_count - 1:
                time.sleep(self.retry_delay)
        
        return GenerationResult(
            success=False,
            images=[],
            error=f"Failed after {self.retry_count} attempts"
        )
    
    def _build_request_body(
        self,
        prompt: str,
        count: int,
        seed: Optional[int],
        model: str,
        aspect_ratio: str
    ) -> Dict[str, Any]:
        """Build request body cho ImageFX API"""
        
        # Core request structure (dựa trên reverse engineering)
        body = {
            "userInput": {
                "candidatesCount": count,
                "prompts": [prompt],
                "seed": seed if seed is not None else None,
            },
            "generationParams": {
                "imageGenerationModel": model,
                "aspectRatio": aspect_ratio,
            },
            "clientContext": {
                "sessionId": self._generate_session_id(),
                "tool": "IMAGE_FX"
            }
        }
        
        # Remove None values
        if body["userInput"]["seed"] is None:
            del body["userInput"]["seed"]
        
        return body
    
    def _generate_session_id(self) -> str:
        """Generate một session ID unique"""
        timestamp = str(time.time())
        random_part = hashlib.md5(timestamp.encode()).hexdigest()[:12]
        return f"session_{random_part}"
    
    def _parse_response(
        self,
        response_data: Dict[str, Any],
        prompt: str
    ) -> GenerationResult:
        """Parse response từ API"""
        
        try:
            images = []
            
            # Response structure có thể khác nhau tùy version
            # Thử các paths phổ biến
            
            # Path 1: imagePanels -> generatedImages
            if "imagePanels" in response_data:
                for panel in response_data.get("imagePanels", []):
                    for gen_image in panel.get("generatedImages", []):
                        encoded = gen_image.get("encodedImage")
                        if encoded:
                            images.append(GeneratedImage(
                                media_id=gen_image.get("mediaGenerationId", self._generate_media_id()),
                                encoded_image=encoded,
                                seed=gen_image.get("seed"),
                                prompt=prompt
                            ))
            
            # Path 2: images array trực tiếp
            elif "images" in response_data:
                for img_data in response_data.get("images", []):
                    encoded = img_data.get("encodedImage") or img_data.get("image")
                    if encoded:
                        images.append(GeneratedImage(
                            media_id=img_data.get("id", self._generate_media_id()),
                            encoded_image=encoded,
                            seed=img_data.get("seed"),
                            prompt=prompt
                        ))
            
            # Path 3: generations array
            elif "generations" in response_data:
                for gen in response_data.get("generations", []):
                    encoded = gen.get("encodedImage") or gen.get("base64")
                    if encoded:
                        images.append(GeneratedImage(
                            media_id=gen.get("mediaId", self._generate_media_id()),
                            encoded_image=encoded,
                            seed=gen.get("seed"),
                            prompt=prompt
                        ))
            
            if images:
                self.logger.info(f"Successfully generated {len(images)} images")
                return GenerationResult(
                    success=True,
                    images=images,
                    raw_response=response_data
                )
            else:
                self.logger.warning("No images in response")
                return GenerationResult(
                    success=False,
                    images=[],
                    error="No images returned",
                    raw_response=response_data
                )
                
        except Exception as e:
            self.logger.error(f"Failed to parse response: {e}")
            return GenerationResult(
                success=False,
                images=[],
                error=f"Parse error: {e}",
                raw_response=response_data
            )
    
    def _generate_media_id(self) -> str:
        """Generate một media ID unique"""
        timestamp = str(time.time())
        return hashlib.sha256(timestamp.encode()).hexdigest()[:24]
    
    def fetch_image(self, media_id: str) -> Optional[GeneratedImage]:
        """
        Fetch ảnh đã tạo trước đó bằng media ID.
        
        Args:
            media_id: ID của ảnh cần fetch
            
        Returns:
            GeneratedImage hoặc None nếu không tìm thấy
        """
        try:
            response = self.session.post(
                f"{IMAGEFX_API_BASE}{IMAGEFX_FETCH_ENDPOINT}",
                json={"mediaId": media_id},
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                encoded = data.get("encodedImage") or data.get("image")
                
                if encoded:
                    return GeneratedImage(
                        media_id=media_id,
                        encoded_image=encoded
                    )
            
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to fetch image: {e}")
            return None
    
    def test_connection(self) -> Tuple[bool, str]:
        """
        Kiểm tra kết nối và authentication.
        
        Returns:
            Tuple (success, message)
        """
        try:
            # Thử generate một ảnh đơn giản
            result = self.generate_image(
                prompt="a simple test image of a blue circle",
                count=1
            )
            
            if result.success:
                return True, "Connection successful! Cookie is valid."
            else:
                return False, f"Connection failed: {result.error}"
                
        except Exception as e:
            return False, f"Connection error: {e}"


# ============================================================================
# ALTERNATIVE API APPROACH (Using internal endpoints)
# ============================================================================

class ImageFXClientV2:
    """
    Client sử dụng internal API endpoints.
    
    Một số trường hợp API endpoint chính không hoạt động,
    có thể thử approach này.
    """
    
    # Alternative endpoint (internal)
    ALT_API_BASE = "https://content-aisandbox-pa.googleapis.com"
    
    def __init__(self, cookie: str, **kwargs):
        self.cookie = cookie
        self.logger = get_logger("imagefx_v2")
        self.session = requests.Session()
        
        self.session.headers.update({
            "Content-Type": "application/json+protobuf",
            "Accept": "*/*",
            "Cookie": cookie,
            "Origin": "https://labs.google",
            "Referer": "https://labs.google/fx/tools/image-fx",
            "X-Goog-Api-Key": "",  # Some requests need this
        })
    
    def generate(self, prompt: str, count: int = 4) -> GenerationResult:
        """Generate images using alternative endpoint"""
        
        # Proto-like request format
        # Note: This may need adjustment based on actual API behavior
        
        request_data = [
            prompt,
            None,
            None,
            count,
            None,
            None,
            "IMAGEN_4",  # model
            None,
            None,
            "IMAGE_ASPECT_RATIO_LANDSCAPE_16_9"  # aspect ratio
        ]
        
        try:
            response = self.session.post(
                f"{self.ALT_API_BASE}/$rpc/google.internal.ai.sandbox.v1.ImageFxService/GenerateImages",
                json=request_data,
                timeout=120
            )
            
            if response.status_code == 200:
                return self._parse_alt_response(response.json(), prompt)
            else:
                return GenerationResult(
                    success=False,
                    images=[],
                    error=f"Status {response.status_code}: {response.text[:200]}"
                )
                
        except Exception as e:
            return GenerationResult(
                success=False,
                images=[],
                error=str(e)
            )
    
    def _parse_alt_response(self, data: Any, prompt: str) -> GenerationResult:
        """Parse response từ alternative endpoint"""
        images = []
        
        try:
            # Response format: [[[encoded_base64, media_id, seed], ...], ...]
            if isinstance(data, list) and len(data) > 0:
                image_list = data[0] if isinstance(data[0], list) else data
                
                for item in image_list:
                    if isinstance(item, list) and len(item) >= 2:
                        encoded = item[0]
                        media_id = item[1] if len(item) > 1 else self._gen_id()
                        seed = item[2] if len(item) > 2 else None
                        
                        if encoded and isinstance(encoded, str):
                            images.append(GeneratedImage(
                                media_id=str(media_id),
                                encoded_image=encoded,
                                seed=seed,
                                prompt=prompt
                            ))
            
            if images:
                return GenerationResult(success=True, images=images)
            
            return GenerationResult(
                success=False,
                images=[],
                error="Could not parse images from response"
            )
            
        except Exception as e:
            return GenerationResult(
                success=False,
                images=[],
                error=f"Parse error: {e}"
            )
    
    def _gen_id(self) -> str:
        return hashlib.md5(str(time.time()).encode()).hexdigest()[:16]


# ============================================================================
# HIGH-LEVEL GENERATOR CLASS
# ============================================================================

class ImageFXGenerator:
    """
    High-level class để tích hợp ImageFX vào VE3 Tool pipeline.
    
    Quản lý việc đọc prompts từ Excel, gọi API, và lưu kết quả.
    """
    
    def __init__(
        self,
        cookie: str,
        settings: Dict[str, Any]
    ):
        """
        Khởi tạo generator.
        
        Args:
            cookie: Google cookie string
            settings: Settings dict từ settings.yaml
        """
        self.cookie = cookie
        self.settings = settings
        self.logger = get_logger("imagefx_generator")
        
        # Initialize client
        model = settings.get("imagefx_model", "IMAGEN_4")
        aspect_ratio = settings.get(
            "imagefx_aspect_ratio",
            "IMAGE_ASPECT_RATIO_LANDSCAPE_16_9"
        )
        
        self.client = ImageFXClient(
            cookie=cookie,
            model=model,
            aspect_ratio=aspect_ratio,
            timeout=settings.get("imagefx_timeout", 120),
            retry_count=settings.get("retry_count", 3)
        )
        
        # Rate limiting
        self.delay_between_scenes = settings.get("imagefx_delay", 5.0)
    
    def generate_for_project(
        self,
        project_dir: Path,
        code: str,
        start_scene: Optional[int] = None,
        end_scene: Optional[int] = None,
        overwrite: bool = False
    ) -> Dict[str, Any]:
        """
        Generate ảnh cho toàn bộ project.
        
        Args:
            project_dir: Thư mục project
            code: Mã project
            start_scene: Scene bắt đầu (None = từ đầu)
            end_scene: Scene kết thúc (None = đến cuối)
            overwrite: Ghi đè ảnh đã có
            
        Returns:
            Dict chứa statistics
        """
        project_dir = Path(project_dir)
        
        # Paths
        excel_path = project_dir / "prompts" / f"{code}_prompts.xlsx"
        img_dir = project_dir / "img"
        
        # Ensure output dir exists
        img_dir.mkdir(parents=True, exist_ok=True)
        
        # Load Excel
        if not excel_path.exists():
            self.logger.error(f"Excel file không tồn tại: {excel_path}")
            return {"success": False, "error": "Excel file not found"}
        
        workbook = PromptWorkbook(excel_path).load_or_create()
        
        # Get scenes to process
        if overwrite:
            scenes = workbook.get_scenes()
        else:
            scenes = workbook.get_pending_image_scenes()
        
        # Filter by range
        if start_scene is not None:
            scenes = [s for s in scenes if s.scene_id >= start_scene]
        if end_scene is not None:
            scenes = [s for s in scenes if s.scene_id <= end_scene]
        
        if not scenes:
            self.logger.info("Không có scene nào cần xử lý")
            return {"success": True, "processed": 0, "failed": 0}
        
        self.logger.info(f"Bắt đầu generate {len(scenes)} scenes...")
        
        # Statistics
        stats = {
            "success": True,
            "total": len(scenes),
            "processed": 0,
            "failed": 0,
            "errors": []
        }
        
        # Process each scene
        for i, scene in enumerate(scenes):
            self.logger.info(f"[{i+1}/{len(scenes)}] Scene {scene.scene_id}")
            
            if not scene.img_prompt:
                self.logger.warning(f"Scene {scene.scene_id} không có img_prompt, bỏ qua")
                stats["failed"] += 1
                stats["errors"].append(f"Scene {scene.scene_id}: No prompt")
                continue
            
            # Generate image
            result = self.client.generate_image(
                prompt=scene.img_prompt,
                count=1  # Chỉ cần 1 ảnh cho mỗi scene
            )
            
            if result.success and result.images:
                # Save image
                image = result.images[0]
                filename = f"scene_{scene.scene_id:03d}.png"
                saved_path = image.save(img_dir, filename)
                
                # Update Excel
                workbook.update_scene(
                    scene.scene_id,
                    img_path=filename,
                    status_img="done"
                )
                workbook.save()
                
                self.logger.info(f"  ✓ Saved: {filename}")
                stats["processed"] += 1
                
            else:
                # Mark as error
                workbook.update_scene(
                    scene.scene_id,
                    status_img="error"
                )
                workbook.save()
                
                error_msg = result.error or "Unknown error"
                self.logger.error(f"  ✗ Failed: {error_msg}")
                stats["failed"] += 1
                stats["errors"].append(f"Scene {scene.scene_id}: {error_msg}")
            
            # Rate limiting
            if i < len(scenes) - 1:
                self.logger.debug(f"Waiting {self.delay_between_scenes}s...")
                time.sleep(self.delay_between_scenes)
        
        self.logger.info(
            f"Hoàn tất: {stats['processed']}/{stats['total']} thành công, "
            f"{stats['failed']} thất bại"
        )
        
        return stats
    
    def generate_single_scene(
        self,
        scene: Scene,
        output_dir: Path
    ) -> Optional[Path]:
        """
        Generate ảnh cho một scene đơn lẻ.
        
        Args:
            scene: Scene object
            output_dir: Thư mục lưu ảnh
            
        Returns:
            Path đến ảnh đã tạo hoặc None
        """
        if not scene.img_prompt:
            self.logger.error(f"Scene {scene.scene_id} không có prompt")
            return None
        
        result = self.client.generate_image(
            prompt=scene.img_prompt,
            count=1
        )
        
        if result.success and result.images:
            image = result.images[0]
            filename = f"scene_{scene.scene_id:03d}.png"
            return image.save(output_dir, filename)
        
        return None


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def extract_cookie_guide() -> str:
    """Trả về hướng dẫn lấy cookie"""
    return """
╔═══════════════════════════════════════════════════════════════════════╗
║         HƯỚNG DẪN LẤY GOOGLE COOKIE CHO IMAGEFX                       ║
╠═══════════════════════════════════════════════════════════════════════╣
║                                                                        ║
║  CÁCH 1: Dùng Cookie Editor Extension (Khuyến nghị)                   ║
║  ─────────────────────────────────────────────────────                ║
║  1. Cài extension "Cookie Editor" cho Chrome/Edge/Firefox             ║
║  2. Truy cập https://labs.google/fx/tools/image-fx                    ║
║  3. Đăng nhập với tài khoản Google (có subscription)                  ║
║  4. Click icon Cookie Editor trên toolbar                             ║
║  5. Click "Export" -> chọn "Header String"                            ║
║  6. Copy toàn bộ text và paste vào settings.yaml                      ║
║                                                                        ║
║  CÁCH 2: Dùng DevTools                                                ║
║  ─────────────────────────────────────────────────────                ║
║  1. Truy cập https://labs.google/fx/tools/image-fx                    ║
║  2. Đăng nhập với tài khoản Google                                    ║
║  3. Nhấn F12 để mở DevTools                                           ║
║  4. Chuyển sang tab "Network"                                         ║
║  5. Nhấn Ctrl+L để clear logs                                         ║
║  6. Tạo 1 ảnh bất kỳ (nhập prompt và click Generate)                  ║
║  7. Tìm request đến "aisandbox-pa.googleapis.com"                     ║
║  8. Click vào request đó                                              ║
║  9. Trong "Request Headers", tìm dòng "Cookie:"                       ║
║  10. Copy TOÀN BỘ giá trị sau "Cookie:"                               ║
║  11. Paste vào settings.yaml                                          ║
║                                                                        ║
║  LƯU Ý:                                                               ║
║  - Cookie sẽ hết hạn sau một thời gian (vài ngày đến vài tuần)       ║
║  - Khi hết hạn, cần lấy cookie mới                                    ║
║  - KHÔNG chia sẻ cookie với người khác (bảo mật tài khoản)           ║
║                                                                        ║
╚═══════════════════════════════════════════════════════════════════════╝
"""


def validate_cookie(cookie: str) -> Tuple[bool, str]:
    """
    Validate định dạng cookie cơ bản.
    
    Args:
        cookie: Cookie string
        
    Returns:
        Tuple (valid, message)
    """
    if not cookie:
        return False, "Cookie trống"
    
    if len(cookie) < 100:
        return False, "Cookie quá ngắn, có thể không hợp lệ"
    
    # Check for common cookie keys
    required_keys = ["__Secure-1PSID", "SAPISID", "APISID"]
    found_keys = [key for key in required_keys if key in cookie]
    
    if not found_keys:
        return False, f"Cookie thiếu các key cần thiết ({', '.join(required_keys)})"
    
    return True, f"Cookie hợp lệ (tìm thấy: {', '.join(found_keys)})"


def test_imagefx_connection(cookie: str) -> Tuple[bool, str]:
    """
    Test kết nối đến ImageFX API.
    
    Args:
        cookie: Google cookie
        
    Returns:
        Tuple (success, message)
    """
    client = ImageFXClient(cookie=cookie)
    return client.test_connection()
