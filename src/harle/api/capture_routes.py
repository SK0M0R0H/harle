"""HTTP routes for the Vault Capture interview API.

Provides ``/capture/interview/start`` and ``/capture/interview/respond``
endpoints that drive the conversational interview loop. The Go CLI
calls these endpoints in a request-response loop to conduct the
interview interactively.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from harle.api.capture_models import (
    InterviewProgressResponse,
    InterviewRespondRequest,
    InterviewResponse,
    InterviewStartRequest,
)
from harle.capture.engine import CaptureEngine, InterviewResponse as EngineResponse
from harle.db.connection import Database

logger = logging.getLogger(__name__)

HARLE_CLIENT_HEADER = "X-Harle-Client"


def _harle_client_from_request(http_request: Request) -> str:
    label = (http_request.headers.get(HARLE_CLIENT_HEADER) or "").strip()
    return label or "unknown"


def _engine_to_api(resp: EngineResponse) -> InterviewResponse:
    """Convert engine response dataclass to API response model."""
    progress = InterviewProgressResponse(**resp.progress) if resp.progress else InterviewProgressResponse()
    return InterviewResponse(
        run_id=resp.run_id,
        action=resp.action,
        message=resp.message,
        topic_id=resp.topic_id,
        topic_name=resp.topic_name,
        draft_content=resp.draft_content,
        capability_note=resp.capability_note,
        progress=progress,
    )


def build_capture_router(
    *,
    engine: CaptureEngine,
    db: Database,
) -> APIRouter:
    """Create capture API routes bound to the CaptureEngine.

    Args:
        engine: The configured CaptureEngine instance.
        db: Database connection for session persistence.

    Returns:
        An APIRouter with capture endpoints.
    """
    router = APIRouter(prefix="/capture", tags=["capture"])

    @router.post("/interview/start", response_model=InterviewResponse)
    def start_interview(
        http_request: Request,
        request: InterviewStartRequest,
    ) -> InterviewResponse:
        """Start a new interview session or resume a paused one.

        Creates a capture run, selects topics from the registry based
        on scope and tiers, and returns the first question.
        """
        logger.info(
            "POST /capture/interview/start",
            extra={"harle_client": _harle_client_from_request(http_request)},
        )
        try:
            with db.session() as session:
                result = engine.start_interview(
                    session,
                    scope=request.scope,
                    tiers=request.tiers,
                    resume=request.resume,
                )
                return _engine_to_api(result)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Interview start failed")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to start interview: {exc}",
            ) from exc

    @router.post("/interview/respond", response_model=InterviewResponse)
    def respond_interview(
        http_request: Request,
        request: InterviewRespondRequest,
    ) -> InterviewResponse:
        """Send a response to the current interview question or draft.

        Advances the interview state machine and returns the next
        action (question, draft, tier_break, complete, etc.).
        """
        logger.info(
            "POST /capture/interview/respond",
            extra={"harle_client": _harle_client_from_request(http_request)},
        )
        try:
            with db.session() as session:
                result = engine.process_response(
                    session,
                    request.run_id,
                    user_response=request.response,
                    action=request.action,
                )
                return _engine_to_api(result)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Interview respond failed")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to process response: {exc}",
            ) from exc

    return router
