from __future__ import annotations

from typing import cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from mandatelab_contracts import (
    DecisionResult,
    Mandate,
    TransactionOutcome,
)
from mandatelab_engine import (
    ConstraintDefinitionError,
    MandateConversionError,
    RankingError,
    evaluate_candidate,
    parse_mandate,
    rank_candidates,
    validate_precheckout,
)
from mandatelab_sandbox_executor import InMemorySandboxExecutor
from user_profile.server import router as cold_start_router

from mandatelab_api.models import (
    EvaluateCandidateRequest,
    ExecuteSandboxRequest,
    HealthResponse,
    ParseMandateRequest,
    RankedCandidateResponse,
    RankCandidatesRequest,
    ValidatePrecheckoutRequest,
)


API_PREFIX = "/api/v1"
DOMAIN_ERRORS = (
    ConstraintDefinitionError,
    MandateConversionError,
    RankingError,
)


def create_app(
    *, executor: InMemorySandboxExecutor | None = None
) -> FastAPI:
    application = FastAPI(
        title="MandateLab API",
        version="0.1.0",
        description=(
            "HTTP composition layer for deterministic buyer-alignment and "
            "sandbox transaction execution."
        ),
    )
    application.state.sandbox_executor = (
        executor or InMemorySandboxExecutor()
    )
    application.include_router(cold_start_router, tags=["cold-start"])

    async def domain_error_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        del request
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    for error_type in DOMAIN_ERRORS:
        application.add_exception_handler(
            error_type, domain_error_handler
        )

    @application.get(
        f"{API_PREFIX}/health",
        response_model=HealthResponse,
        tags=["system"],
    )
    def health() -> HealthResponse:
        return HealthResponse()

    @application.post(
        f"{API_PREFIX}/mandates",
        response_model=Mandate,
        tags=["mandates"],
    )
    def create_mandate(request: ParseMandateRequest) -> Mandate:
        return parse_mandate(
            request.intent,
            request.profile,
            default_authorization=request.default_authorization,
            mandate_id=request.mandate_id,
            version=request.version,
        )

    @application.post(
        f"{API_PREFIX}/rankings",
        response_model=list[RankedCandidateResponse],
        tags=["decisions"],
    )
    def rank(request: RankCandidatesRequest) -> list[RankedCandidateResponse]:
        return [
            RankedCandidateResponse(
                candidate=item.candidate,
                explanation=item.explanation,
            )
            for item in rank_candidates(
                request.candidates, request.mandate, request.profile
            )
        ]

    @application.post(
        f"{API_PREFIX}/decisions",
        response_model=DecisionResult,
        tags=["decisions"],
    )
    def decide(request: EvaluateCandidateRequest) -> DecisionResult:
        return evaluate_candidate(
            request.candidate,
            request.mandate,
            decision_id=request.decision_id,
            evaluated_at=request.evaluated_at,
        )

    @application.post(
        f"{API_PREFIX}/precheckout",
        response_model=DecisionResult,
        tags=["checkout"],
    )
    def precheckout(request: ValidatePrecheckoutRequest) -> DecisionResult:
        return validate_precheckout(
            request.cart,
            request.mandate,
            request.approval,
            decision_id=request.decision_id,
            evaluated_at=request.evaluated_at,
        )

    @application.post(
        f"{API_PREFIX}/sandbox/execute",
        response_model=TransactionOutcome,
        tags=["checkout"],
    )
    def execute(
        request: ExecuteSandboxRequest,
        http_request: Request,
    ) -> TransactionOutcome:
        sandbox = cast(
            InMemorySandboxExecutor,
            http_request.app.state.sandbox_executor,
        )
        return sandbox.execute(
            request.cart,
            request.decision,
            occurred_at=request.occurred_at,
            outcome_id=request.outcome_id,
            transaction_id=request.transaction_id,
        )

    return application


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run(
        "mandatelab_api.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
