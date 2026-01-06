"""
VE3 Tool - Image Quality Evaluator
===================================
Danh gia chat luong anh de chon anh tot nhat va quyet dinh co can tao lai khong.

Tieu chi danh gia:
1. Sharpness (do net) - Laplacian variance
2. Brightness (do sang) - khong qua toi/qua sang
3. Contrast (do tuong phan)
4. Resolution (kich thuoc)
5. File size (kich thuoc file - proxy cho chi tiet)
6. Face detection (phat hien khuon mat neu la anh nhan vat)

Usage:
    from modules.image_evaluator import ImageEvaluator

    evaluator = ImageEvaluator()

    # Danh gia 1 anh
    score, details = evaluator.evaluate(image_path)

    # Chon anh tot nhat tu nhieu anh
    best_path, best_score = evaluator.select_best([img1, img2])

    # Kiem tra co dat chuan khong
    if evaluator.meets_threshold(image_path, min_score=60):
        print("Anh dat chuan!")
"""

import os
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Any
from dataclasses import dataclass

# Optional imports - graceful fallback if not available
try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    cv2 = None
    np = None

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    Image = None


@dataclass
class ImageScore:
    """Ket qua danh gia anh."""
    path: Path
    total_score: float  # 0-100
    sharpness: float    # 0-100 (do net)
    brightness: float   # 0-100 (do sang phu hop)
    contrast: float     # 0-100 (do tuong phan)
    resolution: float   # 0-100 (kich thuoc)
    file_size: float    # 0-100 (kich thuoc file)
    has_face: bool      # Co khuon mat khong
    face_score: float   # 0-100 (diem khuon mat)
    details: Dict[str, Any]  # Chi tiet bo sung

    @property
    def is_good(self) -> bool:
        """Anh co dat chuan khong (>= 60 diem)."""
        return self.total_score >= 60

    @property
    def grade(self) -> str:
        """Xep loai anh."""
        if self.total_score >= 80:
            return "A"
        elif self.total_score >= 70:
            return "B"
        elif self.total_score >= 60:
            return "C"
        elif self.total_score >= 50:
            return "D"
        else:
            return "F"


class ImageEvaluator:
    """
    Danh gia chat luong anh.

    Trong so mac dinh:
    - Sharpness: 30% (quan trong nhat)
    - Brightness: 15%
    - Contrast: 15%
    - Resolution: 15%
    - File size: 15%
    - Face quality: 10% (neu la anh nhan vat)
    """

    # Trong so cho tung tieu chi
    DEFAULT_WEIGHTS = {
        "sharpness": 0.30,
        "brightness": 0.15,
        "contrast": 0.15,
        "resolution": 0.15,
        "file_size": 0.15,
        "face": 0.10
    }

    # Nguong cho cac tieu chi
    THRESHOLDS = {
        "min_resolution": (512, 512),      # Kich thuoc toi thieu
        "ideal_resolution": (1024, 1024),  # Kich thuoc ly tuong
        "min_file_size": 50 * 1024,        # 50KB
        "ideal_file_size": 500 * 1024,     # 500KB
        "min_brightness": 30,               # Khong qua toi
        "max_brightness": 220,              # Khong qua sang
        "ideal_brightness": 128,            # Sang trung binh
        "min_sharpness": 50,                # Laplacian variance toi thieu
        "ideal_sharpness": 500,             # Laplacian variance ly tuong
    }

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        verbose: bool = False,
        check_faces: bool = True
    ):
        """
        Khoi tao evaluator.

        Args:
            weights: Trong so tuy chinh cho tung tieu chi
            verbose: In chi tiet debug
            check_faces: Kiem tra khuon mat (cham hon)
        """
        self.weights = weights or self.DEFAULT_WEIGHTS.copy()
        self.verbose = verbose
        self.check_faces = check_faces and HAS_CV2

        # Load face cascade nếu cần
        self.face_cascade = None
        if self.check_faces and HAS_CV2:
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            if os.path.exists(cascade_path):
                self.face_cascade = cv2.CascadeClassifier(cascade_path)

        self._log(f"ImageEvaluator initialized (cv2={HAS_CV2}, PIL={HAS_PIL}, faces={self.check_faces})")

    def _log(self, msg: str, level: str = "info") -> None:
        """Log message if verbose."""
        if self.verbose:
            icons = {"info": "ℹ️", "success": "✅", "warn": "⚠️", "error": "❌"}
            print(f"{icons.get(level, '•')} [Evaluator] {msg}")

    def evaluate(self, image_path: Path, is_character: bool = False) -> Tuple[float, ImageScore]:
        """
        Danh gia chat luong 1 anh.

        Args:
            image_path: Duong dan anh
            is_character: Co phai anh nhan vat khong (de uu tien face detection)

        Returns:
            Tuple[total_score, ImageScore object]
        """
        image_path = Path(image_path)

        if not image_path.exists():
            self._log(f"File not found: {image_path}", "error")
            return 0, self._empty_score(image_path)

        details = {}

        # === 1. FILE SIZE ===
        file_size = image_path.stat().st_size
        file_size_score = self._score_file_size(file_size)
        details["file_size_bytes"] = file_size
        details["file_size_kb"] = file_size / 1024

        # === 2. RESOLUTION ===
        width, height = self._get_resolution(image_path)
        resolution_score = self._score_resolution(width, height)
        details["width"] = width
        details["height"] = height

        # === 3-5. IMAGE ANALYSIS (require CV2) ===
        if HAS_CV2:
            img = cv2.imread(str(image_path))
            if img is not None:
                # Sharpness (Laplacian variance)
                sharpness_val = self._calculate_sharpness(img)
                sharpness_score = self._score_sharpness(sharpness_val)
                details["sharpness_value"] = sharpness_val

                # Brightness
                brightness_val = self._calculate_brightness(img)
                brightness_score = self._score_brightness(brightness_val)
                details["brightness_value"] = brightness_val

                # Contrast
                contrast_val = self._calculate_contrast(img)
                contrast_score = self._score_contrast(contrast_val)
                details["contrast_value"] = contrast_val

                # Face detection (if character image)
                has_face = False
                face_score = 50  # Default score if no face expected

                if self.check_faces and (is_character or self._looks_like_character(image_path)):
                    faces = self._detect_faces(img)
                    has_face = len(faces) > 0
                    face_score = self._score_faces(faces, width, height)
                    details["faces_found"] = len(faces)
                    details["face_regions"] = faces
            else:
                sharpness_score = 50
                brightness_score = 50
                contrast_score = 50
                has_face = False
                face_score = 50
        else:
            # Fallback: use file size as proxy
            sharpness_score = file_size_score
            brightness_score = 50
            contrast_score = 50
            has_face = False
            face_score = 50

        # === CALCULATE TOTAL SCORE ===
        total_score = (
            sharpness_score * self.weights["sharpness"] +
            brightness_score * self.weights["brightness"] +
            contrast_score * self.weights["contrast"] +
            resolution_score * self.weights["resolution"] +
            file_size_score * self.weights["file_size"] +
            face_score * self.weights["face"]
        )

        score = ImageScore(
            path=image_path,
            total_score=round(total_score, 1),
            sharpness=round(sharpness_score, 1),
            brightness=round(brightness_score, 1),
            contrast=round(contrast_score, 1),
            resolution=round(resolution_score, 1),
            file_size=round(file_size_score, 1),
            has_face=has_face,
            face_score=round(face_score, 1),
            details=details
        )

        self._log(f"Evaluated {image_path.name}: {score.total_score} ({score.grade})")

        return score.total_score, score

    def select_best(
        self,
        image_paths: List[Path],
        is_character: bool = False
    ) -> Tuple[Path, ImageScore]:
        """
        Chon anh tot nhat tu danh sach.

        Args:
            image_paths: List duong dan anh
            is_character: Co phai anh nhan vat khong

        Returns:
            Tuple[best_path, ImageScore]
        """
        if not image_paths:
            return None, None

        if len(image_paths) == 1:
            _, score = self.evaluate(image_paths[0], is_character)
            return image_paths[0], score

        scores = []
        for path in image_paths:
            _, score = self.evaluate(path, is_character)
            scores.append(score)

        # Sort by total score (descending)
        scores.sort(key=lambda s: s.total_score, reverse=True)

        best = scores[0]

        self._log(f"Best image: {best.path.name} ({best.total_score})")

        # Log comparison
        if len(scores) > 1:
            comparison = ", ".join([f"{s.path.name}={s.total_score}" for s in scores])
            self._log(f"  Comparison: {comparison}")

        return best.path, best

    def meets_threshold(
        self,
        image_path: Path,
        min_score: float = 60,
        is_character: bool = False
    ) -> Tuple[bool, ImageScore]:
        """
        Kiem tra anh co dat nguong chat luong khong.

        Args:
            image_path: Duong dan anh
            min_score: Diem toi thieu (0-100)
            is_character: Co phai anh nhan vat khong

        Returns:
            Tuple[passes, ImageScore]
        """
        _, score = self.evaluate(image_path, is_character)
        passes = score.total_score >= min_score

        if not passes:
            self._log(f"Image {image_path.name} below threshold: {score.total_score} < {min_score}", "warn")

        return passes, score

    def evaluate_batch(
        self,
        image_paths: List[Path],
        min_score: float = 60
    ) -> Dict[str, Any]:
        """
        Danh gia hang loat anh.

        Args:
            image_paths: List duong dan anh
            min_score: Diem toi thieu

        Returns:
            Dict voi thong ke va danh sach anh can tao lai
        """
        results = {
            "total": len(image_paths),
            "passed": 0,
            "failed": 0,
            "scores": [],
            "need_regeneration": [],
            "average_score": 0
        }

        total_score = 0

        for path in image_paths:
            is_char = self._looks_like_character(path)
            _, score = self.evaluate(path, is_char)
            results["scores"].append(score)
            total_score += score.total_score

            if score.total_score >= min_score:
                results["passed"] += 1
            else:
                results["failed"] += 1
                results["need_regeneration"].append(path)

        if image_paths:
            results["average_score"] = round(total_score / len(image_paths), 1)

        self._log(f"Batch evaluation: {results['passed']}/{results['total']} passed, avg={results['average_score']}")

        return results

    # =========================================================================
    # PRIVATE METHODS - Calculations
    # =========================================================================

    def _empty_score(self, path: Path) -> ImageScore:
        """Return empty score for missing file."""
        return ImageScore(
            path=path, total_score=0, sharpness=0, brightness=0,
            contrast=0, resolution=0, file_size=0, has_face=False,
            face_score=0, details={"error": "File not found"}
        )

    def _get_resolution(self, image_path: Path) -> Tuple[int, int]:
        """Get image resolution."""
        if HAS_PIL:
            try:
                with Image.open(image_path) as img:
                    return img.size
            except:
                pass

        if HAS_CV2:
            try:
                img = cv2.imread(str(image_path))
                if img is not None:
                    h, w = img.shape[:2]
                    return w, h
            except:
                pass

        return 0, 0

    def _calculate_sharpness(self, img) -> float:
        """Calculate sharpness using Laplacian variance."""
        if not HAS_CV2 or img is None:
            return 0

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        variance = laplacian.var()
        return variance

    def _calculate_brightness(self, img) -> float:
        """Calculate average brightness."""
        if not HAS_CV2 or img is None:
            return 128

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return np.mean(gray)

    def _calculate_contrast(self, img) -> float:
        """Calculate contrast (standard deviation of brightness)."""
        if not HAS_CV2 or img is None:
            return 50

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return np.std(gray)

    def _detect_faces(self, img) -> List[Tuple[int, int, int, int]]:
        """Detect faces in image."""
        if not HAS_CV2 or img is None or self.face_cascade is None:
            return []

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30)
        )

        return [tuple(f) for f in faces]

    def _looks_like_character(self, path: Path) -> bool:
        """Check if path looks like a character image."""
        name = path.stem.lower()
        return name.startswith('nv') or name.startswith('loc')

    # =========================================================================
    # PRIVATE METHODS - Scoring
    # =========================================================================

    def _score_file_size(self, size: int) -> float:
        """Score file size (0-100)."""
        min_size = self.THRESHOLDS["min_file_size"]
        ideal_size = self.THRESHOLDS["ideal_file_size"]

        if size < min_size:
            return (size / min_size) * 50
        elif size >= ideal_size:
            return 100
        else:
            return 50 + ((size - min_size) / (ideal_size - min_size)) * 50

    def _score_resolution(self, width: int, height: int) -> float:
        """Score resolution (0-100)."""
        min_w, min_h = self.THRESHOLDS["min_resolution"]
        ideal_w, ideal_h = self.THRESHOLDS["ideal_resolution"]

        if width < min_w or height < min_h:
            ratio = min(width / min_w, height / min_h)
            return ratio * 50
        elif width >= ideal_w and height >= ideal_h:
            return 100
        else:
            ratio_w = (width - min_w) / (ideal_w - min_w)
            ratio_h = (height - min_h) / (ideal_h - min_h)
            return 50 + min(ratio_w, ratio_h) * 50

    def _score_sharpness(self, variance: float) -> float:
        """Score sharpness (0-100)."""
        min_val = self.THRESHOLDS["min_sharpness"]
        ideal_val = self.THRESHOLDS["ideal_sharpness"]

        if variance < min_val:
            return (variance / min_val) * 50
        elif variance >= ideal_val:
            return 100
        else:
            return 50 + ((variance - min_val) / (ideal_val - min_val)) * 50

    def _score_brightness(self, brightness: float) -> float:
        """Score brightness (0-100). Ideal is around 128."""
        min_b = self.THRESHOLDS["min_brightness"]
        max_b = self.THRESHOLDS["max_brightness"]
        ideal_b = self.THRESHOLDS["ideal_brightness"]

        if brightness < min_b or brightness > max_b:
            # Too dark or too bright
            if brightness < min_b:
                return (brightness / min_b) * 30
            else:
                return max(0, (255 - brightness) / (255 - max_b) * 30)
        else:
            # Calculate distance from ideal
            distance = abs(brightness - ideal_b)
            max_distance = max(ideal_b - min_b, max_b - ideal_b)
            return 100 - (distance / max_distance) * 40

    def _score_contrast(self, std: float) -> float:
        """Score contrast (0-100). Ideal is 40-80."""
        if std < 20:
            return (std / 20) * 50
        elif std > 100:
            return max(50, 100 - (std - 100) / 2)
        elif 40 <= std <= 80:
            return 100
        else:
            if std < 40:
                return 70 + (std - 20) / 20 * 30
            else:
                return 70 + (100 - std) / 20 * 30

    def _score_faces(
        self,
        faces: List[Tuple],
        img_width: int,
        img_height: int
    ) -> float:
        """Score face detection quality (0-100)."""
        if not faces:
            return 30  # Penalty for no face in character image

        # At least one face found
        score = 70

        # Bonus for face size (larger is better for character images)
        total_face_area = sum(w * h for (x, y, w, h) in faces)
        img_area = img_width * img_height

        if img_area > 0:
            face_ratio = total_face_area / img_area
            # Ideal: face takes up 10-40% of image
            if 0.1 <= face_ratio <= 0.4:
                score += 30
            elif face_ratio > 0.4:
                score += 20
            else:
                score += face_ratio / 0.1 * 20

        return min(100, score)


# =========================================================================
# CONVENIENCE FUNCTIONS
# =========================================================================

def evaluate_image(image_path: Path, verbose: bool = False) -> Tuple[float, ImageScore]:
    """Quick evaluate single image."""
    evaluator = ImageEvaluator(verbose=verbose)
    return evaluator.evaluate(image_path)


def select_best_image(
    image_paths: List[Path],
    verbose: bool = False
) -> Tuple[Path, ImageScore]:
    """Quick select best image from list."""
    evaluator = ImageEvaluator(verbose=verbose)
    return evaluator.select_best(image_paths)


def needs_regeneration(
    image_path: Path,
    min_score: float = 60,
    verbose: bool = False
) -> bool:
    """Check if image needs regeneration."""
    evaluator = ImageEvaluator(verbose=verbose)
    passes, _ = evaluator.meets_threshold(image_path, min_score)
    return not passes


# =========================================================================
# CLI
# =========================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python image_evaluator.py <image_path> [image_path2 ...]")
        print("\nEvaluate image quality and select best.")
        sys.exit(1)

    evaluator = ImageEvaluator(verbose=True, check_faces=True)

    paths = [Path(p) for p in sys.argv[1:]]

    if len(paths) == 1:
        # Single image
        score, result = evaluator.evaluate(paths[0])
        print(f"\n{'='*50}")
        print(f"Image: {paths[0].name}")
        print(f"Score: {result.total_score}/100 (Grade {result.grade})")
        print(f"{'='*50}")
        print(f"  Sharpness:  {result.sharpness}")
        print(f"  Brightness: {result.brightness}")
        print(f"  Contrast:   {result.contrast}")
        print(f"  Resolution: {result.resolution}")
        print(f"  File size:  {result.file_size}")
        print(f"  Face:       {result.face_score} (found={result.has_face})")
        print(f"{'='*50}")
        print(f"Needs regeneration: {'YES' if not result.is_good else 'NO'}")
    else:
        # Multiple images - select best
        best_path, best_score = evaluator.select_best(paths)
        print(f"\n{'='*50}")
        print(f"Best image: {best_path.name}")
        print(f"Score: {best_score.total_score}/100 (Grade {best_score.grade})")
        print(f"{'='*50}")
