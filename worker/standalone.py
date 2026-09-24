"""Standalone local batch runner for ODIS Creator (TASK-013).

This module is the offline entry point for the Lamborghini workstation. It
combines the persistent GFF orchestrator, local text cleaning, local vision,
and the UI workflow without starting FastAPI or making HTTP requests.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import List, Optional, Sequence

from controller.config import Settings, get_settings
from controller.logger_service import LoggerService
from controller.orchestrator import GFFOrchestrator, SessionState, TaskStatus
from controller.text_cleaner import TextCleaner
from worker.local_vision import LocalVisionEngine
from worker.screen_capture import ScreenCapture
from worker.ui_driver import UIDriver
from worker.workflow_runner import ControllerClient, WorkflowRunner

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StandaloneOptions:
    """Runtime options for a standalone batch."""

    dry_run: bool = False
    input_file: Optional[Path] = None
    max_tasks: Optional[int] = None
    force_new: bool = False
    verbose: bool = False


class StandaloneRunner:
    """Execute the local workflow against a persistent GFF queue."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        options: Optional[StandaloneOptions] = None,
        orchestrator: Optional[GFFOrchestrator] = None,
        workflow_runner: Optional[WorkflowRunner] = None,
        logger_service: Optional[LoggerService] = None,
    ):
        self.settings = settings or get_settings()
        self.options = options or StandaloneOptions()
        if self.options.max_tasks is not None and self.options.max_tasks < 1:
            raise ValueError("max_tasks must be greater than zero.")

        logs_dir = self.settings.logs_dir
        self.logger_service = logger_service or LoggerService(
            settings=self.settings,
            logs_dir=logs_dir,
        )
        self.orchestrator = orchestrator or GFFOrchestrator(
            settings=self.settings,
            logs_dir=logs_dir,
            logger_service=self.logger_service,
        )
        self.workflow_runner = workflow_runner or self._build_local_workflow()

    def _build_local_workflow(self) -> WorkflowRunner:
        """Construct the fully in-process workflow dependency graph."""
        ui_driver = UIDriver(
            settings=self.settings,
            dry_run=self.options.dry_run,
        )
        local_vision = LocalVisionEngine(
            settings=self.settings,
        )
        controller_client = ControllerClient(
            base_url=self.settings.controller_api_url,
            timeout=self.settings.timeout,
            text_cleaner=TextCleaner(settings=self.settings),
        )
        return WorkflowRunner(
            settings=self.settings,
            ui_driver=ui_driver,
            screen_capture=ScreenCapture(settings=self.settings),
            controller_client=controller_client,
            local_vision_engine=local_vision,
            dry_run=self.options.dry_run,
        )

    def start_session(self) -> SessionState:
        """Create or resume the persistent local session."""
        return self.orchestrator.start_session(
            input_file=self.options.input_file,
            resume=not self.options.force_new,
            force_new=self.options.force_new,
        )

    def run(self) -> SessionState:
        """Process the queue sequentially and return the final session state.

        A task is marked ``IN_PROGRESS`` before the workflow starts. If the
        process is interrupted, that checkpoint remains on disk and the next
        invocation resets it to ``PENDING`` through the orchestrator resume
        path.
        """
        state = self.start_session()
        processed = 0
        mode = "DRY_RUN" if self.options.dry_run else "LIVE"
        self.logger_service.info(f"Standalone execution mode: {mode}")

        try:
            while self.options.max_tasks is None or processed < self.options.max_tasks:
                task = self.orchestrator.get_next_task()
                if task is None:
                    break

                logger.info("Processing %s (%s)", task.task_id, task.name)
                result = self.workflow_runner.run_task(task.task_id, task.name)
                status = TaskStatus.SUCCESS if result.status == "SUCCESS" else TaskStatus.FAILED
                self.orchestrator.complete_task(
                    task_id=task.task_id,
                    status=status,
                    blocks_modified=result.blocks_modified,
                    duration_seconds=result.duration_seconds,
                    error_details=result.error_details,
                    error_screenshot_base64=result.error_screenshot_base64,
                )
                processed += 1

        except KeyboardInterrupt:
            # GFFOrchestrator already persisted IN_PROGRESS before dispatch.
            # Persist once more so active_task_id and timestamps are durable.
            logger.warning("Interrupt received; preserving current task for resume.")
            if self.orchestrator.current_session is not None:
                self.orchestrator.save_state()
        finally:
            self.logger_service.close()

        final_state = self.orchestrator.get_current_session()
        if final_state is None:
            raise RuntimeError("Standalone session disappeared during execution.")
        return final_state


def build_parser() -> argparse.ArgumentParser:
    """Build the standalone command-line parser."""
    parser = argparse.ArgumentParser(description="Run ODIS Obliterator locally without a controller server.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate UI actions without sending physical mouse/keyboard input.",
    )
    mode.add_argument(
        "--no-dry-run",
        "--live",
        dest="live",
        action="store_true",
        help="Run against the live ODIS Creator UI.",
    )
    parser.add_argument(
        "--input-file",
        "-i",
        type=Path,
        default=None,
        help="Input GFF file (default: data/input_gff.txt).",
    )
    parser.add_argument(
        "--max-tasks",
        "-n",
        type=int,
        default=None,
        help="Maximum number of tasks to process in this invocation.",
    )
    parser.add_argument(
        "--force-new",
        action="store_true",
        help="Ignore the latest checkpoint and create a new session.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable DEBUG console logging.",
    )
    return parser


def configure_logging(verbose: bool = False) -> None:
    """Configure console logging without replacing the session file handler."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point for ``python -m worker.standalone``."""
    args = build_parser().parse_args(argv)
    if args.max_tasks is not None and args.max_tasks < 1:
        raise SystemExit("--max-tasks must be greater than zero")

    configure_logging(args.verbose)
    settings = get_settings()
    options = StandaloneOptions(
        dry_run=bool(args.dry_run),
        input_file=args.input_file,
        max_tasks=args.max_tasks,
        force_new=bool(args.force_new),
        verbose=bool(args.verbose),
    )
    state = StandaloneRunner(settings=settings, options=options).run()
    logger.info(
        "Standalone batch %s finished: success=%s failed=%s pending=%s",
        state.session_id,
        state.success_count,
        state.failed_count,
        state.pending_count,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
