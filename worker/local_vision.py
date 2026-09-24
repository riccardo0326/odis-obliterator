"""Local Vision Engine using 2D Template Matching for ODIS Obliterator (TASK-011).

Provides 100% offline, standalone visual detection of target blocks (MESSAGE, QUESTION, COMMENT)
within ODIS Creator flowchart canvas screenshots. Uses icon template matching with proximity
clustering deduplication (NMS) and relative-to-screen coordinate normalization. Zero external network
calls or AI gateway dependencies.
"""

from dataclasses import dataclass
import io
import logging
import math
import os
from pathlib import Path
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from PIL import Image, ImageDraw

from controller.config import Settings, get_settings
from controller.vision_engine import (
    BlockType,
    CanvasBoundingBox,
    DetectedBlock,
    CanvasAnalysisResponse,
)
from worker.screen_capture import base64_to_image

logger = logging.getLogger(__name__)

DEFAULT_CONFIDENCE_THRESHOLD: float = 0.80
DEFAULT_PROXIMITY_RADIUS: int = 15
DEFAULT_SEARCH_STEP: int = 2

# Standard template filenames per BlockType
TEMPLATE_PATTERNS: Dict[BlockType, List[str]] = {
    BlockType.MESSAGE: ["icon_message.png", "icon_msg.png", "message.png"],
    BlockType.QUESTION: ["icon_question.png", "icon_quest.png", "question.png"],
    BlockType.COMMENT: ["icon_comment.png", "icon_memo.png", "comment.png"],
}


def create_default_icon_assets(icons_dir: Union[str, Path]) -> Dict[BlockType, Path]:
    """Generate default 24x24 pixel icon template PNGs if not present on disk.

    Args:
        icons_dir: Destination directory for icon assets.

    Returns:
        Dictionary mapping BlockType to generated/existing file Path.
    """
    target_dir = Path(icons_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    created_paths: Dict[BlockType, Path] = {}

    # 1. MESSAGE: Green parchment sheet with folded corner
    msg_path = target_dir / "icon_message.png"
    if not msg_path.exists():
        msg_img = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
        d = ImageDraw.Draw(msg_img)
        # Parchment body polygon: (3,3) -> (16,3) -> (20,7) -> (20,21) -> (3,21)
        parchment_poly = [(3, 3), (16, 3), (20, 7), (20, 21), (3, 21)]
        d.polygon(parchment_poly, fill=(129, 199, 132, 255), outline=(46, 125, 50, 255))
        # Folded corner triangle: (16,3) -> (20,7) -> (16,7)
        d.polygon([(16, 3), (20, 7), (16, 7)], fill=(200, 230, 201, 255), outline=(46, 125, 50, 255))
        # Inner text lines
        d.line([(6, 10), (14, 10)], fill=(27, 94, 32, 255), width=1)
        d.line([(6, 13), (17, 13)], fill=(27, 94, 32, 255), width=1)
        d.line([(6, 16), (15, 16)], fill=(27, 94, 32, 255), width=1)
        d.line([(6, 19), (12, 19)], fill=(27, 94, 32, 255), width=1)
        msg_img.save(str(msg_path), "PNG")
        logger.debug(f"Created default icon template: {msg_path}")
    created_paths[BlockType.MESSAGE] = msg_path

    # 2. QUESTION: Green circular speech bubble with '?'
    q_path = target_dir / "icon_question.png"
    if not q_path.exists():
        q_img = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
        d = ImageDraw.Draw(q_img)
        # Speech bubble oval and tail
        d.ellipse([(2, 2), (21, 19)], fill=(67, 160, 71, 255), outline=(27, 94, 32, 255))
        d.polygon([(5, 17), (2, 22), (10, 18)], fill=(67, 160, 71, 255), outline=(27, 94, 32, 255))
        d.polygon([(5, 16), (4, 19), (9, 17)], fill=(67, 160, 71, 255))
        # Question mark
        d.line([(8, 6), (12, 5), (14, 7), (14, 9), (12, 11), (11, 12)], fill=(255, 255, 255, 255), width=2)
        d.rectangle([(10, 14), (12, 16)], fill=(255, 255, 255, 255))
        q_img.save(str(q_path), "PNG")
        logger.debug(f"Created default icon template: {q_path}")
    created_paths[BlockType.QUESTION] = q_path

    # 3. COMMENT: Cyan memo notepad
    c_path = target_dir / "icon_comment.png"
    if not c_path.exists():
        c_img = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
        d = ImageDraw.Draw(c_img)
        # Memo pad body
        d.rectangle([(3, 3), (20, 21)], fill=(224, 247, 250, 255), outline=(0, 131, 143, 255))
        # Header strip (cyan)
        d.rectangle([(4, 4), (19, 7)], fill=(0, 188, 212, 255))
        # Horizontal note lines
        d.line([(6, 11), (17, 11)], fill=(0, 151, 167, 255), width=1)
        d.line([(6, 14), (17, 14)], fill=(0, 151, 167, 255), width=1)
        d.line([(6, 17), (14, 17)], fill=(0, 151, 167, 255), width=1)
        # Small yellow tag hint
        d.rectangle([(16, 2), (18, 5)], fill=(255, 179, 0, 255), outline=(255, 143, 0, 255))
        c_img.save(str(c_path), "PNG")
        logger.debug(f"Created default icon template: {c_path}")
    created_paths[BlockType.COMMENT] = c_path

    return created_paths


@dataclass
class RawMatch:
    """Represents an un-clustered candidate match found on canvas."""

    block_type: BlockType
    x: int
    y: int
    width: int
    height: int
    confidence: float

    @property
    def center_x(self) -> float:
        """Horizontal center coordinate."""
        return self.x + (self.width / 2.0)

    @property
    def center_y(self) -> float:
        """Vertical center coordinate."""
        return self.y + (self.height / 2.0)


@dataclass
class TemplateModel:
    """Preprocessed template model for rapid pixel-level correlation."""

    block_type: BlockType
    name: str
    image: Image.Image
    width: int
    height: int
    opaque_pixels: List[Tuple[int, int, int, int, int]]  # (x, y, r, g, b)
    primary_anchor: Tuple[int, int, int, int, int]  # (ax, ay, r, g, b)
    secondary_anchors: List[Tuple[int, int, int, int, int]]
    total_opaque: int
    max_diff_sum: float


class LocalVisionEngine:
    """Local, offline Template Matching vision engine for ODIS Creator flowchart canvas."""

    def __init__(
        self,
        icons_dir: Optional[Union[str, Path]] = None,
        settings: Optional[Settings] = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        proximity_radius: int = DEFAULT_PROXIMITY_RADIUS,
        step: int = DEFAULT_SEARCH_STEP,
        auto_create_templates: bool = True,
    ):
        """Initialize LocalVisionEngine.

        Args:
            icons_dir: Directory containing template icons (defaults to settings.icons_dir).
            settings: Optional Settings instance.
            confidence_threshold: Minimum match confidence score [0.0, 1.0]. Defaults to 0.80.
            proximity_radius: Pixel radius for proximity clustering / deduplication. Defaults to 15.
            step: Stride step in pixels for candidate screening. Defaults to 2.
            auto_create_templates: Whether to generate missing default icons on init.
        """
        self.settings = settings or get_settings()
        self.icons_dir = Path(icons_dir or self.settings.icons_dir).resolve()
        self.confidence_threshold = max(0.0, min(1.0, float(confidence_threshold)))
        self.proximity_radius = max(1, int(proximity_radius))
        self.step = max(1, int(step))
        self.auto_create_templates = auto_create_templates

        if self.auto_create_templates:
            create_default_icon_assets(self.icons_dir)

        self.templates: List[TemplateModel] = []
        self.load_templates()

    def _build_template_model(
        self,
        block_type: BlockType,
        name: str,
        icon_img: Image.Image,
    ) -> TemplateModel:
        """Convert a PIL template image into an optimized TemplateModel.

        Args:
            block_type: Target block type.
            name: Template identifier or filename.
            icon_img: PIL Image object.

        Returns:
            Configured TemplateModel instance.
        """
        rgba_img = icon_img.convert("RGBA")
        w, h = rgba_img.size
        pixels = rgba_img.load()

        opaque_pixels: List[Tuple[int, int, int, int, int]] = []
        for y in range(h):
            for x in range(w):
                r, g, b, a = pixels[x, y]
                if a > 120:  # Opaque/semi-opaque feature pixel
                    opaque_pixels.append((x, y, r, g, b))

        # If image was completely transparent or empty, fallback to all pixels
        if not opaque_pixels:
            for y in range(h):
                for x in range(w):
                    r, g, b, _ = pixels[x, y]
                    opaque_pixels.append((x, y, r, g, b))

        # Select distinct anchor points (highest color saturation/contrast)
        def color_prominence(p: Tuple[int, int, int, int, int]) -> int:
            r, g, b = p[2], p[3], p[4]
            return max(abs(r - g), abs(g - b), abs(r - b))

        sorted_by_prominence = sorted(opaque_pixels, key=color_prominence, reverse=True)
        anchors: List[Tuple[int, int, int, int, int]] = []
        for p in sorted_by_prominence:
            # Ensure spatial dispersion between anchor points
            if all(math.hypot(p[0] - a[0], p[1] - a[1]) >= 4 for a in anchors):
                anchors.append(p)
                if len(anchors) >= 5:
                    break

        if not anchors:
            anchors = opaque_pixels[:5]

        primary_anchor = anchors[0]
        secondary_anchors = anchors[1:]
        total_opaque = len(opaque_pixels)
        max_diff_sum = float(total_opaque * 255 * 3)

        return TemplateModel(
            block_type=block_type,
            name=name,
            image=rgba_img,
            width=w,
            height=h,
            opaque_pixels=opaque_pixels,
            primary_anchor=primary_anchor,
            secondary_anchors=secondary_anchors,
            total_opaque=total_opaque,
            max_diff_sum=max_diff_sum,
        )

    def load_templates(self) -> List[TemplateModel]:
        """Scan icons_dir and load all template models for target block types.

        Returns:
            List of loaded TemplateModel instances.
        """
        self.templates.clear()

        if not self.icons_dir.exists():
            if self.auto_create_templates:
                create_default_icon_assets(self.icons_dir)
            else:
                logger.warning(f"Icons directory does not exist: {self.icons_dir}")
                return []

        loaded_types = set()

        for block_type, filenames in TEMPLATE_PATTERNS.items():
            for fname in filenames:
                file_path = self.icons_dir / fname
                if file_path.exists() and file_path.is_file():
                    try:
                        with Image.open(file_path) as img:
                            model = self._build_template_model(block_type, fname, img)
                            self.templates.append(model)
                            loaded_types.add(block_type)
                            logger.debug(f"Loaded template '{fname}' for {block_type.value} ({model.width}x{model.height})")
                    except Exception as exc:
                        logger.warning(f"Failed to load template file '{file_path}': {exc}")

        # Also search for any additional .png files in icons_dir matching pattern
        for png_file in self.icons_dir.glob("*.png"):
            fname_lower = png_file.name.lower()
            matching_type: Optional[BlockType] = None
            if "message" in fname_lower or "msg" in fname_lower:
                matching_type = BlockType.MESSAGE
            elif "question" in fname_lower or "quest" in fname_lower:
                matching_type = BlockType.QUESTION
            elif "comment" in fname_lower or "memo" in fname_lower:
                matching_type = BlockType.COMMENT

            if matching_type and not any(t.name == png_file.name for t in self.templates):
                try:
                    with Image.open(png_file) as img:
                        model = self._build_template_model(matching_type, png_file.name, img)
                        self.templates.append(model)
                        loaded_types.add(matching_type)
                        logger.debug(f"Loaded extra template '{png_file.name}' for {matching_type.value}")
                except Exception as exc:
                    logger.warning(f"Failed to load extra template '{png_file}': {exc}")

        logger.info(f"Loaded {len(self.templates)} icon templates covering {len(loaded_types)} block types.")
        return self.templates

    def _normalize_image_input(self, image_input: Union[str, bytes, Image.Image]) -> Image.Image:
        """Convert input image (base64 string, bytes, or PIL Image) to RGB PIL Image.

        Args:
            image_input: Input image.

        Returns:
            RGB PIL Image.

        Raises:
            ValueError: If image input cannot be decoded or is invalid.
        """
        if isinstance(image_input, Image.Image):
            return image_input.convert("RGB")
        if isinstance(image_input, bytes):
            try:
                return Image.open(io.BytesIO(image_input)).convert("RGB")
            except Exception as exc:
                raise ValueError(f"Failed to load image from bytes: {exc}") from exc
        if isinstance(image_input, str):
            try:
                img = base64_to_image(image_input)
                return img.convert("RGB")
            except Exception as exc:
                raise ValueError(f"Failed to decode base64 image: {exc}") from exc

        raise ValueError(f"Unsupported image input type: {type(image_input)}")

    def scan_canvas_raw_matches(
        self,
        canvas_rgb: Image.Image,
        confidence_threshold: Optional[float] = None,
    ) -> List[RawMatch]:
        """Perform 2D multi-template search over the canvas image.

        Args:
            canvas_rgb: RGB PIL Image of the canvas.
            confidence_threshold: Optional minimum confidence override.

        Returns:
            List of unclustered RawMatch objects.
        """
        if not self.templates:
            self.load_templates()
            if not self.templates:
                logger.warning("No templates loaded for LocalVisionEngine.")
                return []

        threshold = confidence_threshold if confidence_threshold is not None else self.confidence_threshold
        canvas_w, canvas_h = canvas_rgb.size
        canvas_pixels = canvas_rgb.load()

        step = self.step
        raw_candidates: List[Tuple[TemplateModel, int, int]] = []

        # 1. Fast candidate screening pass using anchor points with stride step
        for tpl in self.templates:
            tw, th = tpl.width, tpl.height
            if canvas_w < tw or canvas_h < th:
                continue

            pax, pay, par, pag, pab = tpl.primary_anchor
            sec_anchors = tpl.secondary_anchors

            for y in range(0, canvas_h - th + 1, step):
                for x in range(0, canvas_w - tw + 1, step):
                    # Primary anchor check with color tolerance
                    pr, pg, pb = canvas_pixels[x + pax, y + pay]
                    if abs(pr - par) > 42 or abs(pg - pag) > 42 or abs(pb - pab) > 42:
                        continue

                    # Secondary anchors check
                    matched_sec = True
                    for sax, say, sar, sag, sab in sec_anchors:
                        spr, spg, spb = canvas_pixels[x + sax, y + say]
                        if abs(spr - sar) > 48 or abs(spg - sag) > 48 or abs(spb - sab) > 48:
                            matched_sec = False
                            break
                    if not matched_sec:
                        continue

                    raw_candidates.append((tpl, x, y))

        # 2. Local peak refinement around candidate locations (+- step)
        raw_matches: List[RawMatch] = []
        for tpl, cx, cy in raw_candidates:
            tw, th = tpl.width, tpl.height
            opaque_pix = tpl.opaque_pixels
            max_diff = tpl.max_diff_sum
            if max_diff <= 0:
                continue

            best_conf = 0.0
            best_x, best_y = cx, cy

            for dy in range(-step, step + 1):
                ny = cy + dy
                if ny < 0 or ny > canvas_h - th:
                    continue
                for dx in range(-step, step + 1):
                    nx = cx + dx
                    if nx < 0 or nx > canvas_w - tw:
                        continue

                    diff_sum = 0
                    for ox, oy, or_, og, ob in opaque_pix:
                        cpr, cpg, cpb = canvas_pixels[nx + ox, ny + oy]
                        diff_sum += abs(cpr - or_) + abs(cpg - og) + abs(cpb - ob)

                    conf = 1.0 - (diff_sum / max_diff)
                    if conf > best_conf:
                        best_conf = conf
                        best_x, best_y = nx, ny

            if best_conf >= threshold:
                raw_matches.append(
                    RawMatch(
                        block_type=tpl.block_type,
                        x=best_x,
                        y=best_y,
                        width=tw,
                        height=th,
                        confidence=best_conf,
                    )
                )

        return raw_matches

    def deduplicate_matches(
        self,
        matches: List[RawMatch],
        proximity_radius: Optional[int] = None,
    ) -> List[RawMatch]:
        """Apply Non-Maximum Suppression (NMS) and proximity clustering to eliminate duplicate detections.

        Args:
            matches: List of raw candidate matches.
            proximity_radius: Minimum distance radius between distinct block detections.

        Returns:
            Deduplicated list of RawMatch objects.
        """
        radius = proximity_radius if proximity_radius is not None else self.proximity_radius
        if not matches:
            return []

        # Sort matches by confidence descending
        sorted_matches = sorted(matches, key=lambda m: m.confidence, reverse=True)
        retained: List[RawMatch] = []

        for candidate in sorted_matches:
            is_duplicate = False
            for existing in retained:
                dist = math.hypot(
                    candidate.center_x - existing.center_x,
                    candidate.center_y - existing.center_y,
                )
                # Same block type within proximity radius OR any block heavily overlapping
                if dist <= radius and (candidate.block_type == existing.block_type or dist <= radius / 1.5):
                    is_duplicate = True
                    break

            if not is_duplicate:
                retained.append(candidate)

        return retained

    def detect_blocks(
        self,
        image: Union[str, bytes, Image.Image],
        canvas_bbox: Optional[CanvasBoundingBox] = None,
        confidence_threshold: Optional[float] = None,
    ) -> List[DetectedBlock]:
        """Detect target blocks on canvas image and map to normalized/screen coordinates.

        Args:
            image: Canvas screenshot (base64 string, bytes, or PIL Image).
            canvas_bbox: Optional CanvasBoundingBox for computing absolute screen coordinates.
            confidence_threshold: Optional confidence threshold override.

        Returns:
            List of DetectedBlock instances sorted in top-to-bottom flowchart sequence.
        """
        canvas_rgb = self._normalize_image_input(image)
        canvas_w, canvas_h = canvas_rgb.size
        if canvas_w == 0 or canvas_h == 0:
            return []

        # 1. Scan for raw template matches
        raw_matches = self.scan_canvas_raw_matches(
            canvas_rgb,
            confidence_threshold=confidence_threshold,
        )

        # 2. Deduplicate using proximity clustering (NMS)
        clustered_matches = self.deduplicate_matches(raw_matches)

        # 3. Convert to DetectedBlock with relative and screen coordinates
        detected_blocks: List[DetectedBlock] = []
        for match in clustered_matches:
            rel_x = max(0.0, min(1.0, round(match.center_x / float(canvas_w), 4)))
            rel_y = max(0.0, min(1.0, round(match.center_y / float(canvas_h), 4)))

            screen_x: Optional[int] = None
            screen_y: Optional[int] = None
            if canvas_bbox is not None:
                screen_x, screen_y = canvas_bbox.to_screen_coords(rel_x, rel_y)

            label = f"{match.block_type.value} Block"
            block = DetectedBlock(
                type=match.block_type,
                relative_x=rel_x,
                relative_y=rel_y,
                label=label,
                screen_x=screen_x,
                screen_y=screen_y,
                confidence=round(match.confidence, 4),
            )
            detected_blocks.append(block)

        # 4. Sort top-to-bottom, left-to-right (flowchart order)
        detected_blocks.sort(key=lambda b: (round(b.relative_y, 2), round(b.relative_x, 2)))

        logger.debug(f"LocalVisionEngine detected {len(detected_blocks)} blocks on canvas ({canvas_w}x{canvas_h}).")
        return detected_blocks

    def analyze_canvas(
        self,
        image: Union[str, bytes, Image.Image],
        canvas_bbox: Optional[CanvasBoundingBox] = None,
        task_id: Optional[str] = None,
        confidence_threshold: Optional[float] = None,
    ) -> CanvasAnalysisResponse:
        """Analyze canvas screenshot and return CanvasAnalysisResponse.

        Compatible interface with VisionEngine and Controller API.

        Args:
            image: Canvas screenshot (base64 string, bytes, or PIL Image).
            canvas_bbox: Optional CanvasBoundingBox for absolute screen coordinates.
            task_id: Optional diagnostic task identifier.
            confidence_threshold: Optional confidence threshold override.

        Returns:
            CanvasAnalysisResponse containing detected target blocks and execution timing.
        """
        start_time = time.time()
        blocks = self.detect_blocks(
            image=image,
            canvas_bbox=canvas_bbox,
            confidence_threshold=confidence_threshold,
        )
        duration = round(time.time() - start_time, 3)

        return CanvasAnalysisResponse(
            blocks=blocks,
            task_id=task_id,
            total_detected=len(blocks),
            execution_time_seconds=duration,
        )


# Global default instance
_default_local_vision_engine: Optional[LocalVisionEngine] = None


def get_local_vision_engine(
    icons_dir: Optional[Union[str, Path]] = None,
    settings: Optional[Settings] = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    proximity_radius: int = DEFAULT_PROXIMITY_RADIUS,
    step: int = DEFAULT_SEARCH_STEP,
) -> LocalVisionEngine:
    """Return singleton LocalVisionEngine instance.

    Args:
        icons_dir: Optional icon templates directory.
        settings: Optional Settings instance.
        confidence_threshold: Minimum match confidence.
        proximity_radius: Proximity clustering radius.
        step: Stride search step.

    Returns:
        LocalVisionEngine singleton instance.
    """
    global _default_local_vision_engine
    if _default_local_vision_engine is None:
        _default_local_vision_engine = LocalVisionEngine(
            icons_dir=icons_dir,
            settings=settings,
            confidence_threshold=confidence_threshold,
            proximity_radius=proximity_radius,
            step=step,
        )
    return _default_local_vision_engine


def analyze_canvas_local(
    image: Union[str, bytes, Image.Image],
    canvas_bbox: Optional[CanvasBoundingBox] = None,
    task_id: Optional[str] = None,
    confidence_threshold: Optional[float] = None,
) -> CanvasAnalysisResponse:
    """Convenience function to analyze canvas using default LocalVisionEngine.

    Args:
        image: Canvas screenshot.
        canvas_bbox: Optional canvas bounding box.
        task_id: Optional task identifier.
        confidence_threshold: Optional confidence override.

    Returns:
        CanvasAnalysisResponse instance.
    """
    engine = get_local_vision_engine()
    return engine.analyze_canvas(
        image=image,
        canvas_bbox=canvas_bbox,
        task_id=task_id,
        confidence_threshold=confidence_threshold,
    )
