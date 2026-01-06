"""
VE3 Tool - Ken Burns Effects Module
===================================
Tạo hiệu ứng zoom/pan mượt mà cho ảnh tĩnh.
Chất lượng như CapCut - không giật, không chóng mặt.

Các hiệu ứng:
- zoom_in: Zoom từ xa vào gần (focus vào trung tâm)
- zoom_out: Zoom từ gần ra xa (reveal toàn cảnh)
- pan_left: Di chuyển từ phải sang trái
- pan_right: Di chuyển từ trái sang phải
- pan_up: Di chuyển từ dưới lên trên
- pan_down: Di chuyển từ trên xuống dưới
- zoom_in_pan_left: Zoom in + pan trái
- zoom_in_pan_right: Zoom in + pan phải
- zoom_out_pan: Zoom out + pan nhẹ
"""

import random
from typing import Tuple, Optional
from dataclasses import dataclass
from enum import Enum


class KenBurnsEffect(Enum):
    """Các loại hiệu ứng Ken Burns."""
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    PAN_UP = "pan_up"
    PAN_DOWN = "pan_down"
    ZOOM_IN_PAN_LEFT = "zoom_in_pan_left"
    ZOOM_IN_PAN_RIGHT = "zoom_in_pan_right"
    ZOOM_OUT_PAN_LEFT = "zoom_out_pan_left"
    ZOOM_OUT_PAN_RIGHT = "zoom_out_pan_right"
    SUBTLE_DRIFT = "subtle_drift"  # Rất nhẹ, gần như tĩnh


@dataclass
class KenBurnsConfig:
    """Cấu hình cho hiệu ứng Ken Burns."""
    # Zoom settings
    zoom_start: float = 1.0  # Zoom ban đầu (1.0 = 100%)
    zoom_end: float = 1.15   # Zoom cuối (1.15 = 115%, nhẹ nhàng)

    # Pan settings (tỷ lệ % của kích thước ảnh)
    pan_x_start: float = 0.5  # Vị trí X ban đầu (0.5 = giữa)
    pan_x_end: float = 0.5    # Vị trí X cuối
    pan_y_start: float = 0.5  # Vị trí Y ban đầu
    pan_y_end: float = 0.5    # Vị trí Y cuối

    # Easing (mượt mà)
    use_easing: bool = True   # Sử dụng easing để mượt hơn


class KenBurnsIntensity:
    """Cường độ hiệu ứng Ken Burns."""
    SUBTLE = "subtle"    # Rất nhẹ - zoom 6%, pan 4% (clip dài 15-20s)
    NORMAL = "normal"    # Cân bằng - zoom 10%, pan 6% (clip 10-15s)
    STRONG = "strong"    # Mạnh - zoom 15%, pan 10% (clip ngắn 5-8s)


# Mapping intensity to values
# Điều chỉnh cho mượt như CapCut - chuyển động nhẹ nhàng, không chóng mặt
# Clip 5-8s cần zoom/pan ít hơn để không bị giật
INTENSITY_VALUES = {
    KenBurnsIntensity.SUBTLE: {"zoom": 0.04, "pan": 0.03, "subtle": 0.015},  # Rất nhẹ
    KenBurnsIntensity.NORMAL: {"zoom": 0.06, "pan": 0.04, "subtle": 0.02},   # 6% zoom, 4% pan (mượt)
    KenBurnsIntensity.STRONG: {"zoom": 0.08, "pan": 0.05, "subtle": 0.025},  # 8% zoom, 5% pan (rõ ràng nhưng không giật)
}


class KenBurnsGenerator:
    """
    Tạo FFmpeg filter cho hiệu ứng Ken Burns.

    Sử dụng zoompan filter với các tham số được tính toán để:
    - Không bị giật (smooth interpolation)
    - Không chóng mặt (tốc độ vừa phải)
    - Không bị cắt viền đen (scale đủ lớn trước khi pan)
    """

    # FPS cho zoompan (30 fps cho mượt như CapCut)
    ZOOMPAN_FPS = 30

    def __init__(
        self,
        output_width: int = 1920,
        output_height: int = 1080,
        intensity: str = KenBurnsIntensity.NORMAL
    ):
        """
        Khởi tạo generator.

        Args:
            output_width: Chiều rộng video output
            output_height: Chiều cao video output
            intensity: Cường độ hiệu ứng ("subtle", "normal", "strong")
        """
        self.output_width = output_width
        self.output_height = output_height

        # Set intensity values
        self.set_intensity(intensity)

    def set_intensity(self, intensity: str):
        """Đặt cường độ hiệu ứng."""
        intensity = intensity.lower() if intensity else KenBurnsIntensity.NORMAL
        values = INTENSITY_VALUES.get(intensity, INTENSITY_VALUES[KenBurnsIntensity.NORMAL])

        self.ZOOM_AMOUNT = values["zoom"]
        self.PAN_AMOUNT = values["pan"]
        self.SUBTLE_AMOUNT = values["subtle"]

    # Pattern xen kẽ có logic: zoom → pan → zoom → pan
    # Mỗi loại có 2 biến thể, xen kẽ để đa dạng nhưng không loạn
    EFFECT_PATTERN = [
        KenBurnsEffect.ZOOM_IN,      # 1. Zoom vào
        KenBurnsEffect.PAN_LEFT,     # 2. Pan trái
        KenBurnsEffect.ZOOM_OUT,     # 3. Zoom ra
        KenBurnsEffect.PAN_RIGHT,    # 4. Pan phải
        KenBurnsEffect.ZOOM_IN,      # 5. Zoom vào
        KenBurnsEffect.PAN_UP,       # 6. Pan lên
        KenBurnsEffect.ZOOM_OUT,     # 7. Zoom ra
        KenBurnsEffect.PAN_DOWN,     # 8. Pan xuống
    ]
    _effect_index = 0

    def get_random_effect(self, exclude_last: Optional[KenBurnsEffect] = None) -> KenBurnsEffect:
        """
        Chọn hiệu ứng theo pattern có logic (xen kẽ zoom và pan).
        Pattern: zoom_in → pan_left → zoom_out → pan_right → zoom_in → pan_up → zoom_out → pan_down → lặp lại

        Args:
            exclude_last: Không dùng (giữ để tương thích)

        Returns:
            KenBurnsEffect tiếp theo trong pattern
        """
        # Lấy effect từ pattern
        effect = self.EFFECT_PATTERN[self._effect_index]

        # Tăng index, quay vòng khi hết
        self._effect_index = (self._effect_index + 1) % len(self.EFFECT_PATTERN)

        return effect

    def reset_pattern(self):
        """Reset pattern về đầu (gọi khi bắt đầu video mới)."""
        self._effect_index = 0

    def get_config(self, effect: KenBurnsEffect) -> KenBurnsConfig:
        """
        Lấy cấu hình cho một hiệu ứng cụ thể.

        Args:
            effect: Loại hiệu ứng

        Returns:
            KenBurnsConfig với các tham số phù hợp
        """
        config = KenBurnsConfig()

        if effect == KenBurnsEffect.ZOOM_IN:
            # Zoom từ 1.0 đến 1.12 (từ xa vào gần)
            config.zoom_start = 1.0
            config.zoom_end = 1.0 + self.ZOOM_AMOUNT

        elif effect == KenBurnsEffect.ZOOM_OUT:
            # Zoom từ 1.12 xuống 1.0 (từ gần ra xa)
            config.zoom_start = 1.0 + self.ZOOM_AMOUNT
            config.zoom_end = 1.0

        elif effect == KenBurnsEffect.PAN_LEFT:
            # Pan từ phải sang trái (giữ zoom 1.15 để không bị viền đen)
            config.zoom_start = 1.0 + self.ZOOM_AMOUNT
            config.zoom_end = 1.0 + self.ZOOM_AMOUNT
            config.pan_x_start = 0.5 + self.PAN_AMOUNT
            config.pan_x_end = 0.5 - self.PAN_AMOUNT

        elif effect == KenBurnsEffect.PAN_RIGHT:
            # Pan từ trái sang phải
            config.zoom_start = 1.0 + self.ZOOM_AMOUNT
            config.zoom_end = 1.0 + self.ZOOM_AMOUNT
            config.pan_x_start = 0.5 - self.PAN_AMOUNT
            config.pan_x_end = 0.5 + self.PAN_AMOUNT

        elif effect == KenBurnsEffect.PAN_UP:
            # Pan từ dưới lên trên
            config.zoom_start = 1.0 + self.ZOOM_AMOUNT
            config.zoom_end = 1.0 + self.ZOOM_AMOUNT
            config.pan_y_start = 0.5 + self.PAN_AMOUNT
            config.pan_y_end = 0.5 - self.PAN_AMOUNT

        elif effect == KenBurnsEffect.PAN_DOWN:
            # Pan từ trên xuống dưới
            config.zoom_start = 1.0 + self.ZOOM_AMOUNT
            config.zoom_end = 1.0 + self.ZOOM_AMOUNT
            config.pan_y_start = 0.5 - self.PAN_AMOUNT
            config.pan_y_end = 0.5 + self.PAN_AMOUNT

        elif effect == KenBurnsEffect.ZOOM_IN_PAN_LEFT:
            # Zoom in + pan trái
            config.zoom_start = 1.0
            config.zoom_end = 1.0 + self.ZOOM_AMOUNT
            config.pan_x_start = 0.5 + self.PAN_AMOUNT / 2
            config.pan_x_end = 0.5 - self.PAN_AMOUNT / 2

        elif effect == KenBurnsEffect.ZOOM_IN_PAN_RIGHT:
            # Zoom in + pan phải
            config.zoom_start = 1.0
            config.zoom_end = 1.0 + self.ZOOM_AMOUNT
            config.pan_x_start = 0.5 - self.PAN_AMOUNT / 2
            config.pan_x_end = 0.5 + self.PAN_AMOUNT / 2

        elif effect == KenBurnsEffect.ZOOM_OUT_PAN_LEFT:
            # Zoom out + pan trái
            config.zoom_start = 1.0 + self.ZOOM_AMOUNT
            config.zoom_end = 1.0
            config.pan_x_start = 0.5 + self.PAN_AMOUNT / 2
            config.pan_x_end = 0.5 - self.PAN_AMOUNT / 2

        elif effect == KenBurnsEffect.ZOOM_OUT_PAN_RIGHT:
            # Zoom out + pan phải
            config.zoom_start = 1.0 + self.ZOOM_AMOUNT
            config.zoom_end = 1.0
            config.pan_x_start = 0.5 - self.PAN_AMOUNT / 2
            config.pan_x_end = 0.5 + self.PAN_AMOUNT / 2

        elif effect == KenBurnsEffect.SUBTLE_DRIFT:
            # Rất nhẹ - gần như tĩnh nhưng có chút chuyển động
            config.zoom_start = 1.0 + self.SUBTLE_AMOUNT / 2
            config.zoom_end = 1.0 + self.SUBTLE_AMOUNT
            # Random drift direction
            drift_x = random.uniform(-self.SUBTLE_AMOUNT, self.SUBTLE_AMOUNT)
            drift_y = random.uniform(-self.SUBTLE_AMOUNT, self.SUBTLE_AMOUNT)
            config.pan_x_start = 0.5
            config.pan_x_end = 0.5 + drift_x
            config.pan_y_start = 0.5
            config.pan_y_end = 0.5 + drift_y

        return config

    def generate_filter(
        self,
        effect: KenBurnsEffect,
        duration: float,
        fade_duration: float = 0.4,
        simple_mode: bool = False
    ) -> str:
        """
        Tạo FFmpeg filter string cho hiệu ứng Ken Burns.

        Args:
            effect: Loại hiệu ứng
            duration: Thời lượng clip (giây)
            fade_duration: Thời lượng fade in/out (giây)
            simple_mode: True = use fast crop method (for balanced mode)

        Returns:
            FFmpeg filter string
        """
        config = self.get_config(effect)
        fade_out_start = max(0, duration - fade_duration)
        fade = f"fade=t=in:st=0:d={fade_duration},fade=t=out:st={fade_out_start}:d={fade_duration}"

        if simple_mode:
            # === BALANCED MODE: Dùng zoompan nhưng với ít frame hơn để nhanh hơn ===
            # Thay vì crop animation (gây giật), dùng zoompan với FPS thấp hơn
            # zoompan tạo chuyển động mượt thật sự vì nó thay đổi scale

            fps = 24  # Giảm FPS để nhanh hơn (24 thay vì 30)
            total_frames = int(duration * fps)

            # Margin nhỏ hơn cho chuyển động nhẹ nhàng
            zoom_pct = 0.05  # 5% zoom
            pan_pct = 0.03   # 3% pan

            # Cosine ease: mượt mà từ đầu đến cuối
            ease = f"(0.5-0.5*cos(PI*on/{total_frames}))"

            if effect == KenBurnsEffect.ZOOM_IN:
                # Zoom in: từ 1.0 đến 1.05 (zoom vào trung tâm)
                zoom_expr = f"1+{zoom_pct}*{ease}"
                x_expr = "(iw-iw/zoom)/2"
                y_expr = "(ih-ih/zoom)/2"
            elif effect == KenBurnsEffect.ZOOM_OUT:
                # Zoom out: từ 1.05 về 1.0
                zoom_expr = f"1+{zoom_pct}*(1-{ease})"
                x_expr = "(iw-iw/zoom)/2"
                y_expr = "(ih-ih/zoom)/2"
            elif effect == KenBurnsEffect.PAN_LEFT:
                # Pan left: giữ zoom 1.06 để không bị viền đen, x đi từ phải sang trái
                zoom_expr = "1.06"
                x_expr = f"(iw-iw/zoom)*(0.5+{pan_pct}-{pan_pct}*2*{ease})"
                y_expr = "(ih-ih/zoom)/2"
            elif effect == KenBurnsEffect.PAN_RIGHT:
                # Pan right: x đi từ trái sang phải
                zoom_expr = "1.06"
                x_expr = f"(iw-iw/zoom)*(0.5-{pan_pct}+{pan_pct}*2*{ease})"
                y_expr = "(ih-ih/zoom)/2"
            elif effect == KenBurnsEffect.PAN_UP:
                # Pan up: y đi từ dưới lên trên
                zoom_expr = "1.06"
                x_expr = "(iw-iw/zoom)/2"
                y_expr = f"(ih-ih/zoom)*(0.5+{pan_pct}-{pan_pct}*2*{ease})"
            elif effect == KenBurnsEffect.PAN_DOWN:
                # Pan down: y đi từ trên xuống dưới
                zoom_expr = "1.06"
                x_expr = "(iw-iw/zoom)/2"
                y_expr = f"(ih-ih/zoom)*(0.5-{pan_pct}+{pan_pct}*2*{ease})"
            else:
                # Default: subtle drift
                zoom_expr = f"1+0.02*{ease}"
                x_expr = "(iw-iw/zoom)/2"
                y_expr = "(ih-ih/zoom)/2"

            # Scale ảnh lên trước để zoompan có không gian làm việc
            scale_factor = 1.15
            scaled_w = int(self.output_width * scale_factor)
            scaled_h = int(self.output_height * scale_factor)

            zoompan = (
                f"zoompan="
                f"z='{zoom_expr}':"
                f"x='{x_expr}':"
                f"y='{y_expr}':"
                f"d={total_frames}:"
                f"s={self.output_width}x{self.output_height}:"
                f"fps={fps}"
            )

            full_filter = (
                f"scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=increase,"
                f"crop={scaled_w}:{scaled_h},"
                f"{zoompan},"
                f"{fade}"
            )
        else:
            # === QUALITY MODE: Dùng zoompan (mượt hơn nhưng chậm hơn) ===
            fps = self.ZOOMPAN_FPS
            total_frames = int(duration * fps)

            zoom_diff = config.zoom_end - config.zoom_start
            # Smooth ease-in-out
            zoom_expr = f"{config.zoom_start}+{zoom_diff}*(0.5-0.5*cos(PI*on/{total_frames}))"

            pan_x_diff = config.pan_x_end - config.pan_x_start
            pan_x_ratio = f"{config.pan_x_start}+{pan_x_diff}*(0.5-0.5*cos(PI*on/{total_frames}))"
            x_expr = f"(iw-iw/zoom)*({pan_x_ratio})"

            pan_y_diff = config.pan_y_end - config.pan_y_start
            pan_y_ratio = f"{config.pan_y_start}+{pan_y_diff}*(0.5-0.5*cos(PI*on/{total_frames}))"
            y_expr = f"(ih-ih/zoom)*({pan_y_ratio})"

            scale_factor = 1.25
            scaled_w = int(self.output_width * scale_factor)
            scaled_h = int(self.output_height * scale_factor)

            zoompan = (
                f"zoompan="
                f"z='{zoom_expr}':"
                f"x='{x_expr}':"
                f"y='{y_expr}':"
                f"d={total_frames}:"
                f"s={self.output_width}x{self.output_height}:"
                f"fps={fps}"
            )

            full_filter = (
                f"scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=increase,"
                f"crop={scaled_w}:{scaled_h},"
                f"{zoompan},"
                f"{fade}"
        )

        return full_filter

    def generate_static_filter(self, duration: float, fade_duration: float = 0.4) -> str:
        """
        Tạo filter cho ảnh tĩnh (không có Ken Burns).
        Dùng khi muốn một số ảnh không có hiệu ứng.

        Args:
            duration: Thời lượng clip
            fade_duration: Thời lượng fade

        Returns:
            FFmpeg filter string
        """
        fade_out_start = max(0, duration - fade_duration)
        return (
            f"scale={self.output_width}:{self.output_height}:"
            f"force_original_aspect_ratio=decrease,"
            f"pad={self.output_width}:{self.output_height}:(ow-iw)/2:(oh-ih)/2,"
            f"fade=t=in:st=0:d={fade_duration},"
            f"fade=t=out:st={fade_out_start}:d={fade_duration}"
        )


def get_ken_burns_filter(
    duration: float,
    effect: Optional[KenBurnsEffect] = None,
    exclude_last: Optional[KenBurnsEffect] = None,
    output_width: int = 1920,
    output_height: int = 1080,
    fade_duration: float = 0.4
) -> Tuple[str, KenBurnsEffect]:
    """
    Convenience function để tạo Ken Burns filter.

    Args:
        duration: Thời lượng clip (giây)
        effect: Hiệu ứng cụ thể (None = random)
        exclude_last: Hiệu ứng cuối để tránh lặp
        output_width: Chiều rộng output
        output_height: Chiều cao output
        fade_duration: Thời lượng fade

    Returns:
        Tuple (filter_string, selected_effect)
    """
    generator = KenBurnsGenerator(output_width, output_height)

    if effect is None:
        effect = generator.get_random_effect(exclude_last)

    filter_str = generator.generate_filter(effect, duration, fade_duration)

    return filter_str, effect


# Shorthand for common effects
def zoom_in_filter(duration: float, fade: float = 0.4) -> str:
    """Tạo filter zoom in."""
    gen = KenBurnsGenerator()
    return gen.generate_filter(KenBurnsEffect.ZOOM_IN, duration, fade)


def zoom_out_filter(duration: float, fade: float = 0.4) -> str:
    """Tạo filter zoom out."""
    gen = KenBurnsGenerator()
    return gen.generate_filter(KenBurnsEffect.ZOOM_OUT, duration, fade)


def pan_left_filter(duration: float, fade: float = 0.4) -> str:
    """Tạo filter pan left."""
    gen = KenBurnsGenerator()
    return gen.generate_filter(KenBurnsEffect.PAN_LEFT, duration, fade)


def pan_right_filter(duration: float, fade: float = 0.4) -> str:
    """Tạo filter pan right."""
    gen = KenBurnsGenerator()
    return gen.generate_filter(KenBurnsEffect.PAN_RIGHT, duration, fade)
