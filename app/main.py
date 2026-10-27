import logging
from typing import Annotated

import psycopg
from sqlalchemy.exc import DBAPIError, TimeoutError as PoolTimeoutError
from sqlalchemy.orm import Session
from app.repositories.health import HealthRepository
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from app.database import get_session
from app.routes.events import router
from app.routes.transactions import router as transactions_router
from app.routes.reconciliation import router as reconciliation_router
from app.services.ingestion import EventConflict

logger = logging.getLogger(__name__)
app = FastAPI(title='Payment Reconciliation', version='0.1.0')
app.include_router(router)
app.include_router(transactions_router)
app.include_router(reconciliation_router)


@app.exception_handler(EventConflict)
async def event_conflict_handler(request: Request, exc: EventConflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={'detail': {'code': exc.code, 'message': str(exc)}})


@app.exception_handler(DBAPIError)
@app.exception_handler(PoolTimeoutError)
async def database_error_handler(request: Request, exc: DBAPIError | PoolTimeoutError) -> JSONResponse:
    logger.exception('Database operation failed')
    original = exc.orig if isinstance(exc, DBAPIError) else exc
    transient = isinstance(original, (psycopg.OperationalError, psycopg.errors.QueryCanceled, PoolTimeoutError))
    return JSONResponse(
        status_code=503 if transient else 500,
        content={'detail': {'code': 'database_unavailable' if transient else 'internal_error',
                            'message': 'Database unavailable or busy.' if transient else 'Internal server error.'}},
    )


@app.get('/health', tags=['Health'])
def health(session: Annotated[Session, Depends(get_session)]) -> dict:
    HealthRepository(session).check()
    return {'status': 'ok'}
