"""
BaseStage — abstract base class for all V2 pipeline stages.

Two concrete base classes are provided:

  BaseStage     — non-critical. Failures are caught, stored in
                  context.stage_errors, and the pipeline continues.

  CriticalStage — critical. Failures propagate and abort the pipeline.
                  Use for stages whose failure makes further execution
                  meaningless (e.g. DocumentNormalizerStage).

Stage contract:
  1. Implement `name` property (string identifier used in logs/metrics).
  2. Implement `_run(context) -> context` with the core stage logic.
  3. Optionally override `should_skip(context) -> bool` to opt out.
  4. Call `execute(context)` — never call `_run` directly.
"""
from __future__ import annotations

import abc
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.rule_engine.pipeline.v2.context import PipelineContext

logger = logging.getLogger("rule_engine.pipeline")

__all__ = ["BaseStage", "CriticalStage"]


class BaseStage(abc.ABC):
    """Non-critical pipeline stage. Failure is swallowed; pipeline continues."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable stage identifier used in logs, metrics, and timings."""
        ...

    @abc.abstractmethod
    def _run(self, context: "PipelineContext") -> "PipelineContext":
        """Core stage logic. Must return the (possibly mutated) context."""
        ...

    def should_skip(self, context: "PipelineContext") -> bool:
        """
        Return True to skip this stage.
        Skipped stages are recorded in context.stages_skipped (not as errors).
        """
        return False

    def execute(self, context: "PipelineContext") -> "PipelineContext":
        """
        Public entry point. Handles skip-check, timing, and error swallowing.
        Do NOT override; override _run instead.
        """
        if self.should_skip(context):
            logger.debug("[pipeline] Stage '%s' skipped.", self.name)
            context.mark_skipped(self.name)
            return context

        logger.info("[pipeline] Stage '%s' starting.", self.name)
        t0 = time.monotonic()

        try:
            context = self._run(context)
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            context.stage_timings[self.name] = elapsed_ms
            context.stage_errors[self.name] = f"{type(exc).__name__}: {exc}"
            logger.exception(
                "[pipeline] Stage '%s' raised an exception (non-critical, continuing): %s",
                self.name, exc,
            )
            return context

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        context.stage_timings[self.name] = elapsed_ms
        logger.info("[pipeline] Stage '%s' completed in %dms.", self.name, elapsed_ms)
        return context


class CriticalStage(BaseStage):
    """
    Critical pipeline stage. Failure propagates and aborts the pipeline.

    Use this for stages that produce outputs required by every downstream
    stage (e.g. normalization, rule execution).
    """

    def execute(self, context: "PipelineContext") -> "PipelineContext":
        if self.should_skip(context):
            logger.debug("[pipeline] Critical stage '%s' skipped.", self.name)
            context.mark_skipped(self.name)
            return context

        logger.info("[pipeline] Critical stage '%s' starting.", self.name)
        t0 = time.monotonic()

        try:
            context = self._run(context)
        except Exception:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            context.stage_timings[self.name] = elapsed_ms
            logger.exception(
                "[pipeline] Critical stage '%s' failed — aborting pipeline.", self.name
            )
            raise  # bubble up to AuditPipelineV2.run()

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        context.stage_timings[self.name] = elapsed_ms
        logger.info("[pipeline] Critical stage '%s' completed in %dms.", self.name, elapsed_ms)
        return context
