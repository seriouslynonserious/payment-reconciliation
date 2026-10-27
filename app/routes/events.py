from typing import Annotated

from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Response

from app.database import get_session
from app.schemas import IngestionResult, PaymentEvent
from app.services.ingestion import ingest_event

router = APIRouter(tags=['Events'])


@router.post(
    '/events',
    response_model=IngestionResult,
    status_code=201,
    responses={
        200: {
            'model': IngestionResult,
            'description': 'Identical event already accepted',
        },
        409: {'description': 'Event ID or transaction identity conflict'},
        503: {'description': 'Database unavailable or busy; retry the same event ID'},
    },
)
def create_event(
    event: PaymentEvent,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
) -> IngestionResult:
    result = ingest_event(session, event)
    if result.duplicate:
        response.status_code = 200
    else:
        response.status_code = 201
    return result
