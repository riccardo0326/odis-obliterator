"""ODIS Obliterator Controller package."""

from controller.config import Settings, get_settings, reload_settings, settings
from controller.kelpie_client import (
    KelpieAuthError,
    KelpieClient,
    KelpieError,
    KelpieRequestError,
    KelpieResponseError,
    normalize_image_to_base64,
    strip_markdown_codeblocks,
)
from controller.text_cleaner import (
    TextCleanRequest,
    TextCleanResponse,
    TextCleanResult,
    TextCleaner,
    clean_text,
)
from controller.vision_engine import (
    BlockType,
    CanvasAnalysisRequest,
    CanvasAnalysisResponse,
    CanvasBoundingBox,
    DetectedBlock,
    PopupDetectionResult,
    PopupType,
    VisionEngine,
    analyze_canvas,
    map_relative_to_screen,
    map_screen_to_relative,
    normalize_block_type,
)

__all__ = [
    "Settings",
    "get_settings",
    "reload_settings",
    "settings",
    "KelpieClient",
    "KelpieError",
    "KelpieAuthError",
    "KelpieRequestError",
    "KelpieResponseError",
    "normalize_image_to_base64",
    "strip_markdown_codeblocks",
    "TextCleaner",
    "clean_text",
    "TextCleanRequest",
    "TextCleanResponse",
    "TextCleanResult",
    "BlockType",
    "CanvasBoundingBox",
    "DetectedBlock",
    "CanvasAnalysisRequest",
    "CanvasAnalysisResponse",
    "PopupType",
    "PopupDetectionResult",
    "VisionEngine",
    "analyze_canvas",
    "map_relative_to_screen",
    "map_screen_to_relative",
    "normalize_block_type",
]

