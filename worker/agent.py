"""Worker Agent for ODIS Obliterator (TASK-009 / Client Worker).

Runs on the Worker machine (Lamborghini PC).
Connects to Controller REST API over Wi-Fi LAN, polls for pending GFF diagnostic tasks,
executes the 14-step workflow (with support for Dry-Run mode), and reports completion status.
"""

import argparse
from datetime import datetime, timezone
import logging
import os
import signal
import sys
import time
from typing import Any, Dict, List, Optional

from controller.config import Settings, get_settings
from worker.workflow_runner import (
    ControllerClient,
    WorkflowExecutionResult,
    WorkflowRunner,
    get_workflow_runner,
)

logger = logging.getLogger("worker.agent")


class WorkerAgent:
    """Worker polling client that receives GFF tasks from Controller and executes them."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        controller_client: Optional[ControllerClient] = None,
        workflow_runner: Optional[WorkflowRunner] = None,
        dry_run: Optional[bool] = None,
        poll_interval: Optional[float] = None,
        max_consecutive_errors: int = 5,
        stop_on_empty_queue: bool = True,
    ):
        """Initialize WorkerAgent.

        Args:
            settings: Settings instance (defaults to global settings).
            controller_client: ControllerClient instance.
            workflow_runner: WorkflowRunner instance.
            dry_run: Override dry-run mode (if None, reads from settings.dry_run).
            poll_interval: Polling interval in seconds (if None, reads from settings).
            max_consecutive_errors: Maximum allowable consecutive connection/API errors before aborting.
            stop_on_empty_queue: If True, stop agent loop when Controller returns 204 No Content.
        """
        self.settings = settings or get_settings()
        self.dry_run = dry_run if dry_run is not None else self.settings.dry_run
        self.poll_interval = poll_interval if poll_interval is not None else self.settings.worker_poll_interval
        self.max_consecutive_errors = max_consecutive_errors
        self.stop_on_empty_queue = stop_on_empty_queue

        self.client = controller_client or ControllerClient(
            base_url=self.settings.controller_api_url,
            timeout=self.settings.timeout,
        )
        self.runner = workflow_runner or WorkflowRunner(
            settings=self.settings,
            controller_client=self.client,
            dry_run=self.dry_run,
        )

        # State tracking
        self.is_running = False
        self.tasks_processed = 0
        self.tasks_succeeded = 0
        self.tasks_failed = 0
        self.consecutive_errors = 0
        self.total_blocks_modified = 0
        self.execution_history: List[WorkflowExecutionResult] = []

    def verify_connectivity(self) -> Dict[str, Any]:
        """Check Controller health status and network connectivity.

        Returns:
            Dictionary containing health response.

        Raises:
            ConnectionError: If Controller is unreachable or degraded.
        """
        try:
            health = self.client.check_health()
            logger.info(f"Connected to Controller at {self.client.base_url}: status={health.get('status')}")
            return health
        except Exception as exc:
            logger.error(f"Cannot reach Controller at {self.client.base_url}: {exc}")
            raise ConnectionError(f"Failed to connect to Controller: {exc}") from exc

    def poll_and_execute_next(self) -> Optional[WorkflowExecutionResult]:
        """Poll for next task from Controller, execute 14-step workflow, and report completion.

        Returns:
            WorkflowExecutionResult if a task was processed, or None if queue is empty.
        """
        try:
            task_info = self.client.get_next_task()
            self.consecutive_errors = 0
        except Exception as exc:
            self.consecutive_errors += 1
            logger.warning(
                f"Error fetching next task from Controller (consecutive errors: {self.consecutive_errors}): {exc}"
            )
            if self.consecutive_errors >= self.max_consecutive_errors:
                logger.error(f"Exceeded max consecutive errors ({self.max_consecutive_errors}). Stopping.")
                self.is_running = False
            return None

        if task_info is None:
            logger.info("No pending tasks in Controller queue.")
            return None

        task_id = task_info.get("task_id", "")
        gff_name = task_info.get("name", "")

        logger.info(f"Received task {task_id}: '{gff_name}' (dry_run={self.dry_run})")

        # Execute 14-step workflow
        task_result = self.runner.run_task(task_id=task_id, gff_name=gff_name)
        self.tasks_processed += 1
        self.execution_history.append(task_result)

        if task_result.status == "SUCCESS":
            self.tasks_succeeded += 1
            self.total_blocks_modified += task_result.total_blocks_modified
        else:
            self.tasks_failed += 1

        # Report task completion to Controller
        try:
            self.client.complete_task(
                task_id=task_result.task_id,
                status=task_result.status,
                blocks_modified=task_result.blocks_modified,
                duration_seconds=task_result.duration_seconds,
                error_details=task_result.error_details,
                error_screenshot_base64=task_result.error_screenshot_base64,
            )
            logger.info(f"Reported completion for task {task_id} with status {task_result.status}")
        except Exception as exc:
            logger.warning(f"Could not report task {task_id} completion to Controller: {exc}")

        return task_result

    def run(
        self,
        max_tasks: Optional[int] = None,
        duration_limit_seconds: Optional[float] = None,
        stop_on_empty_queue: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Start worker polling and execution loop.

        Args:
            max_tasks: Optional maximum number of tasks to process before exiting.
            duration_limit_seconds: Optional maximum runtime in seconds.
            stop_on_empty_queue: Optional override for whether to stop when queue is empty.

        Returns:
            Batch execution summary dictionary.
        """
        stop_on_empty = (
            stop_on_empty_queue if stop_on_empty_queue is not None else self.stop_on_empty_queue
        )
        logger.info(
            f"Starting WorkerAgent loop (controller={self.client.base_url}, "
            f"dry_run={self.dry_run}, poll_interval={self.poll_interval}s, max_tasks={max_tasks})"
        )

        start_time = time.time()
        self.is_running = True
        self.tasks_processed = 0
        self.tasks_succeeded = 0
        self.tasks_failed = 0
        self.consecutive_errors = 0
        self.total_blocks_modified = 0
        self.execution_history.clear()

        # Handle signals for graceful termination
        def _signal_handler(sig, frame):
            logger.warning("Interrupt signal received. Stopping WorkerAgent gracefully...")
            self.is_running = False

        prev_sigint = None
        try:
            prev_sigint = signal.signal(signal.SIGINT, _signal_handler)
        except (ValueError, AttributeError):
            pass

        try:
            while self.is_running:
                # Check task limit
                if max_tasks is not None and self.tasks_processed >= max_tasks:
                    logger.info(f"Reached maximum tasks limit ({max_tasks}). Exiting loop.")
                    break

                # Check duration limit
                if duration_limit_seconds is not None:
                    elapsed = time.time() - start_time
                    if elapsed >= duration_limit_seconds:
                        logger.info(f"Reached duration limit ({duration_limit_seconds}s). Exiting loop.")
                        break

                result = self.poll_and_execute_next()

                if result is None:
                    if not self.is_running:
                        break
                    if stop_on_empty and self.consecutive_errors == 0:
                        logger.info("Queue is empty and stop_on_empty_queue is True. Batch complete.")
                        break
                    # Wait before next poll
                    time.sleep(self.poll_interval)
                else:
                    # Brief inter-task delay
                    if self.poll_interval > 0:
                        time.sleep(min(self.poll_interval, 0.5))

        finally:
            self.is_running = False
            if prev_sigint is not None:
                try:
                    signal.signal(signal.SIGINT, prev_sigint)
                except (ValueError, AttributeError):
                    pass

        total_duration = round(time.time() - start_time, 2)
        summary = {
            "dry_run": self.dry_run,
            "tasks_processed": self.tasks_processed,
            "tasks_succeeded": self.tasks_succeeded,
            "tasks_failed": self.tasks_failed,
            "total_blocks_modified": self.total_blocks_modified,
            "total_duration_seconds": total_duration,
        }
        logger.info(f"WorkerAgent finished: {summary}")
        return summary

    def stop(self) -> None:
        """Signal the worker agent loop to terminate after the current task."""
        self.is_running = False


def main() -> None:
    """CLI entry point for Worker Agent."""
    parser = argparse.ArgumentParser(
        description="ODIS Obliterator Worker Agent (Runs on Lamborghini PC)",
    )
    parser.add_argument(
        "--controller-url",
        "-c",
        type=str,
        default=None,
        help="Controller API base URL (e.g. http://192.168.1.100:8000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="Run in Dry-Run mode without sending physical clicks/text to ODIS",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_false",
        dest="dry_run",
        help="Run in Live production mode",
    )
    parser.add_argument(
        "--poll-interval",
        "-p",
        type=float,
        default=None,
        help="Polling interval in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--max-tasks",
        "-n",
        type=int,
        default=None,
        help="Maximum number of tasks to process before exiting",
    )
    parser.add_argument(
        "--health-only",
        action="store_true",
        help="Only verify connectivity to Controller and exit",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable detailed debug logging",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    settings = get_settings()
    controller_url = args.controller_url or settings.controller_api_url
    client = ControllerClient(base_url=controller_url, timeout=settings.timeout)

    agent = WorkerAgent(
        settings=settings,
        controller_client=client,
        dry_run=args.dry_run,
        poll_interval=args.poll_interval,
    )

    if args.health_only:
        try:
            health = agent.verify_connectivity()
            print(f"Controller Health: {health}")
            sys.exit(0)
        except Exception as exc:
            print(f"Health check failed: {exc}", file=sys.stderr)
            sys.exit(1)

    try:
        agent.verify_connectivity()
    except Exception as exc:
        logger.error(f"Cannot start agent: {exc}")
        sys.exit(1)

    agent.run(max_tasks=args.max_tasks)


if __name__ == "__main__":
    main()
