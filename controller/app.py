"""FastAPI Application Server for ODIS Obliterator Controller (TASK-005).

Exposes REST APIs for Worker agent orchestration, canvas vision analysis via Kelpie AI Gateway,
text sanitization, and batch lifecycle tracking.
"""

from contextlib import asynccontextmanager
import logging
from typing import Any, Dict, List, Optional
from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from controller.config import Settings, get_settings
from controller.kelpie_client import KelpieClient, KelpieError
from controller.logger_service import LoggerService, get_logger_service
from controller.orchestrator import (
    GFFOrchestrator,
    GFFTask,
    SessionState,
    SessionSummary,
    TaskStatus,
)
from controller.text_cleaner import (
    TextCleanRequest,
    TextCleanResponse,
    TextCleaner,
)
from controller.vision_engine import (
    CanvasAnalysisRequest,
    CanvasAnalysisResponse,
    PopupDetectionResult,
    VisionEngine,
)

logger = logging.getLogger("controller.app")


# --- API Models ---


class HealthResponse(BaseModel):
    """Health check status response."""

    status: str = Field(..., description="Overall controller status ('ok', 'degraded', 'error').")
    kelpie: str = Field(..., description="Kelpie gateway connection state.")
    model: str = Field(..., description="Configured multimodal model identifier.")
    session_active: bool = Field(..., description="Whether an active batch session exists.")
    session_id: Optional[str] = Field(default=None, description="Active session ID if any.")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Detailed diagnostic info.")


class SessionStartRequest(BaseModel):
    """Payload for starting or resuming a batch processing session."""

    session_id: Optional[str] = Field(
        default=None,
        description="Optional custom session identifier. If omitted, generated automatically.",
    )
    gff_list: Optional[List[str]] = Field(
        default=None,
        description="Optional explicit list of GFF function names to process.",
    )
    input_file: Optional[str] = Field(
        default=None,
        description="Optional custom path to input GFF text file.",
    )
    resume: bool = Field(
        default=True,
        description="Whether to resume from existing session checkpoint if available.",
    )
    force_new: bool = Field(
        default=False,
        description="If True, force initialization of a brand new session even if state exists.",
    )


class SessionStartResponse(BaseModel):
    """Response returned upon starting or resuming a session."""

    session_id: str = Field(..., description="Active session identifier.")
    total_gff: int = Field(..., description="Total number of GFF tasks in batch.")
    pending: int = Field(..., description="Count of remaining pending tasks.")
    in_progress: int = Field(default=0, description="Count of tasks currently executing.")
    completed: int = Field(default=0, description="Count of successfully finished tasks.")
    failed: int = Field(default=0, description="Count of failed tasks.")
    resumed: bool = Field(default=False, description="Whether this session was resumed from disk.")


class NextTaskResponse(BaseModel):
    """Response containing next GFF diagnostic task to execute."""

    task_id: str = Field(..., description="Unique task identifier (e.g. GFF_001, GFF_042).")
    name: str = Field(..., description="Diagnostic object / GFF function name.")


class TaskCompleteRequest(BaseModel):
    """Notification payload sent by Worker when a GFF task finishes."""

    task_id: str = Field(..., description="Unique task identifier.")
    status: str = Field(..., description="Terminal status ('SUCCESS', 'FAILED', 'SKIPPED').")
    blocks_modified: Optional[Dict[str, int]] = Field(
        default=None,
        description="Counts of modified blocks: {'message': 1, 'comment': 1, 'question': 0}.",
    )
    duration_seconds: Optional[float] = Field(
        default=None,
        description="Duration of task execution in seconds.",
    )
    error_details: Optional[str] = Field(
        default=None,
        description="Error message or diagnostic details in case of failure.",
    )
    error_screenshot_base64: Optional[str] = Field(
        default=None,
        description="Optional Base64 encoded screenshot captured at the time of failure.",
    )


class TaskCompleteResponse(BaseModel):
    """Confirmation response after recording task completion."""

    status: str = Field(default="recorded", description="Confirmation status.")
    task_id: str = Field(..., description="Completed task identifier.")
    session_id: str = Field(..., description="Active session identifier.")
    task_status: str = Field(..., description="Recorded terminal status.")
    remaining: int = Field(..., description="Count of pending tasks remaining in queue.")
    session_completed: bool = Field(..., description="Whether all tasks in session are finished.")


class PopupDetectRequest(BaseModel):
    """Request payload for popup and modal dialog detection."""

    image_base64: str = Field(..., description="Base64 encoded screenshot of full screen / window.")
    custom_prompt: Optional[str] = Field(default=None, description="Optional prompt override.")


# --- Dependency Singletons ---

_orchestrator_instance: Optional[GFFOrchestrator] = None
_kelpie_client_instance: Optional[KelpieClient] = None
_vision_engine_instance: Optional[VisionEngine] = None
_text_cleaner_instance: Optional[TextCleaner] = None
_logger_service_instance: Optional[LoggerService] = None


def get_logger_service() -> LoggerService:
    """Dependency provider for LoggerService singleton."""
    global _logger_service_instance
    if _logger_service_instance is None:
        _logger_service_instance = LoggerService()
    return _logger_service_instance


def get_orchestrator() -> GFFOrchestrator:
    """Dependency provider for GFFOrchestrator singleton."""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = GFFOrchestrator(logger_service=get_logger_service())
    return _orchestrator_instance


def get_kelpie_client() -> KelpieClient:
    """Dependency provider for KelpieClient singleton."""
    global _kelpie_client_instance
    if _kelpie_client_instance is None:
        _kelpie_client_instance = KelpieClient()
    return _kelpie_client_instance


def get_vision_engine(
    kelpie_client: KelpieClient = Depends(get_kelpie_client),
) -> VisionEngine:
    """Dependency provider for VisionEngine."""
    global _vision_engine_instance
    if _vision_engine_instance is None:
        _vision_engine_instance = VisionEngine(kelpie_client=kelpie_client)
    return _vision_engine_instance


def get_text_cleaner() -> TextCleaner:
    """Dependency provider for TextCleaner."""
    global _text_cleaner_instance
    if _text_cleaner_instance is None:
        _text_cleaner_instance = TextCleaner()
    return _text_cleaner_instance


# --- Application Setup ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for FastAPI application."""
    logger.info("Starting ODIS Obliterator Controller Server...")
    # Initialize orchestrator and try restoring previous session if present
    orchestrator = get_orchestrator()
    try:
        latest = orchestrator.find_latest_session_state()
        if latest and latest.exists():
            resumed = orchestrator.start_session(resume=True)
            if resumed:
                logger.info(f"Auto-resumed latest session: {resumed.session_id}")
    except Exception as exc:
        logger.warning(f"Could not auto-resume session on startup: {exc}")
    yield
    logger.info("Shutting down ODIS Obliterator Controller Server.")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    cfg = settings or get_settings()

    application = FastAPI(
        title="ODIS Obliterator Controller API",
        description=(
            "Distributed automation controller for batch sanitization of ODIS Creator "
            "diagnostic objects, flowchart vision parsing, and keyword eradication."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    # Enable CORS for local cross-machine LAN access
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- REST Endpoints ---

    @application.get(
        "/api/v1/health",
        response_model=HealthResponse,
        tags=["System"],
        summary="Check controller and AI gateway health status",
    )
    async def health_check(
        orchestrator: GFFOrchestrator = Depends(get_orchestrator),
        kelpie_client: KelpieClient = Depends(get_kelpie_client),
    ) -> HealthResponse:
        """Verify connectivity to Controller and Kelpie Gateway."""
        kelpie_status = kelpie_client.check_health()
        current_sess = orchestrator.get_current_session()

        is_healthy = kelpie_status.get("status") in ("ok", "connected")
        status_str = "ok" if is_healthy else "degraded"
        kelpie_str = kelpie_status.get("kelpie", "unknown")

        return HealthResponse(
            status=status_str,
            kelpie=kelpie_str,
            model=cfg.kelpie_model,
            session_active=(current_sess is not None),
            session_id=current_sess.session_id if current_sess else None,
            details=kelpie_status,
        )

    @application.post(
        "/api/v1/session/start",
        response_model=SessionStartResponse,
        tags=["Session & Queue"],
        summary="Initialize a new batch session or resume an interrupted one",
    )
    async def start_session(
        request: SessionStartRequest = SessionStartRequest(),
        orchestrator: GFFOrchestrator = Depends(get_orchestrator),
    ) -> SessionStartResponse:
        """Start a new batch processing session or resume from state checkpoint."""
        try:
            prev_session = orchestrator.get_current_session()
            session = orchestrator.start_session(
                session_id=request.session_id,
                gff_list=request.gff_list,
                input_file=request.input_file,
                resume=request.resume,
                force_new=request.force_new,
            )

            was_resumed = (
                request.resume
                and not request.force_new
                and (prev_session is not None or session.success_count > 0 or session.failed_count > 0)
            )

            return SessionStartResponse(
                session_id=session.session_id,
                total_gff=session.total_gff,
                pending=session.pending_count,
                in_progress=session.in_progress_count,
                completed=session.success_count,
                failed=session.failed_count,
                resumed=was_resumed,
            )
        except Exception as exc:
            logger.error(f"Error starting session: {exc}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to start session: {exc}",
            )

    @application.get(
        "/api/v1/tasks/next",
        response_model=NextTaskResponse,
        responses={
            status.HTTP_200_OK: {"model": NextTaskResponse, "description": "Next task dispatched."},
            status.HTTP_204_NO_CONTENT: {"description": "No pending tasks remaining in queue."},
        },
        tags=["Session & Queue"],
        summary="Get next GFF diagnostic task to process",
    )
    async def get_next_task(
        orchestrator: GFFOrchestrator = Depends(get_orchestrator),
    ):
        """Fetch next pending task. Returns 204 No Content when queue is empty."""
        task = orchestrator.get_next_task()
        if task is None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        return NextTaskResponse(task_id=task.task_id, name=task.name)

    @application.post(
        "/api/v1/vision/analyze-canvas",
        response_model=CanvasAnalysisResponse,
        tags=["Vision & AI"],
        summary="Analyze flowchart canvas screenshot and identify target blocks",
    )
    async def analyze_canvas_endpoint(
        request: CanvasAnalysisRequest,
        vision_engine: VisionEngine = Depends(get_vision_engine),
    ) -> CanvasAnalysisResponse:
        """Process canvas screenshot and return detected target blocks (MESSAGE, QUESTION, COMMENT)."""
        try:
            return vision_engine.analyze_canvas(
                image=request.image_base64,
                canvas_bbox=request.canvas_bbox,
                task_id=request.task_id,
            )
        except KelpieError as exc:
            logger.error(f"Kelpie vision analysis error: {exc}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Kelpie gateway error: {exc}",
            )
        except Exception as exc:
            logger.error(f"Canvas analysis failed: {exc}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Canvas analysis failed: {exc}",
            )

    @application.post(
        "/api/v1/vision/detect-popup",
        response_model=PopupDetectionResult,
        tags=["Vision & AI"],
        summary="Detect and classify modal popups/dialogs in screenshot",
    )
    async def detect_popup_endpoint(
        request: PopupDetectRequest,
        vision_engine: VisionEngine = Depends(get_vision_engine),
    ) -> PopupDetectionResult:
        """Detect modal dialogs (such as Validation error or Search ended) in a screenshot."""
        try:
            return vision_engine.detect_popup(
                image=request.image_base64,
                custom_prompt=request.custom_prompt,
            )
        except Exception as exc:
            logger.error(f"Popup detection failed: {exc}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Popup detection failed: {exc}",
            )

    @application.post(
        "/api/v1/text/clean",
        response_model=TextCleanResponse,
        tags=["Text Sanitization"],
        summary="Sanitize block text by removing target keyword",
    )
    async def clean_text_endpoint(
        request: TextCleanRequest,
        cleaner: TextCleaner = Depends(get_text_cleaner),
    ) -> TextCleanResponse:
        """Sanitize text block by removing target keyword while protecting macros and variables."""
        result = cleaner.clean(
            raw_text=request.raw_text,
            block_type=request.block_type,
            target_keyword=request.target_keyword,
        )
        return result.to_response()

    @application.post(
        "/api/v1/tasks/complete",
        response_model=TaskCompleteResponse,
        tags=["Session & Queue"],
        summary="Record completion status and metrics for a GFF task",
    )
    async def complete_task_endpoint(
        request: TaskCompleteRequest,
        orchestrator: GFFOrchestrator = Depends(get_orchestrator),
    ) -> TaskCompleteResponse:
        """Record task result, execution metrics, and optional failure screenshots."""
        try:
            completed_task = orchestrator.complete_task(
                task_id=request.task_id,
                status=request.status,
                blocks_modified=request.blocks_modified,
                duration_seconds=request.duration_seconds,
                error_details=request.error_details,
                error_screenshot_base64=request.error_screenshot_base64,
            )

            session = orchestrator.get_current_session()
            assert session is not None

            return TaskCompleteResponse(
                status="recorded",
                task_id=completed_task.task_id,
                session_id=session.session_id,
                task_status=completed_task.status.value,
                remaining=session.pending_count,
                session_completed=session.is_completed,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )
        except Exception as exc:
            logger.error(f"Error completing task {request.task_id}: {exc}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to record task completion: {exc}",
            )

    @application.get(
        "/api/v1/session/status",
        response_model=SessionSummary,
        tags=["Session & Queue"],
        summary="Get overall batch session execution summary and progress metrics",
    )
    async def get_session_status(
        orchestrator: GFFOrchestrator = Depends(get_orchestrator),
    ) -> SessionSummary:
        """Return summary progress metrics of the active session."""
        session = orchestrator.get_current_session()
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active batch session found.",
            )
        return session.get_summary()

    @application.get(
        "/api/v1/tasks/{task_id}",
        response_model=GFFTask,
        tags=["Session & Queue"],
        summary="Get details of a specific GFF task",
    )
    async def get_task_by_id(
        task_id: str,
        orchestrator: GFFOrchestrator = Depends(get_orchestrator),
    ) -> GFFTask:
        """Lookup details of a specific task by ID."""
        task = orchestrator.get_task(task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task '{task_id}' not found.",
            )
        return task

    @application.get(
        "/",
        tags=["System"],
        summary="Root information endpoint",
    )
    async def root_info() -> Dict[str, Any]:
        """Root API landing endpoint."""
        return {
            "name": "ODIS Obliterator Controller",
            "version": "1.0.0",
            "docs": "/docs",
            "health": "/api/v1/health",
        }

    return application


# Global default application instance for uvicorn runner
app = create_app()


if __name__ == "__main__":
    import uvicorn

    server_settings = get_settings()
    uvicorn.run(
        "controller.app:app",
        host=server_settings.host,
        port=server_settings.port,
        reload=False,
    )
