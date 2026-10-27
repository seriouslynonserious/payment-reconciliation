from typing import Annotated
from uuid import UUID

from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import get_session
from app.schemas import TransactionDetail, TransactionFilters, TransactionPage
from app.services.transactions import get_transaction, list_transactions

router = APIRouter(prefix='/transactions', tags=['Transactions'])
Database = Annotated[Session, Depends(get_session)]


@router.get('', response_model=TransactionPage)
def transaction_list(filters: Annotated[TransactionFilters, Query()], session: Database) -> TransactionPage:
    """Filter by payment status and earliest event time: date_from inclusive, date_to exclusive."""
    return list_transactions(session, filters)


@router.get('/{transaction_id}', response_model=TransactionDetail,
            responses={404: {'description': 'Transaction does not exist'}})
def transaction_detail(transaction_id: UUID, session: Database) -> TransactionDetail:
    """Return merchant information, current state, and unique events in occurrence order."""
    result = get_transaction(session, transaction_id)
    if result is None:
        raise HTTPException(status_code=404, detail={
            'code': 'transaction_not_found', 'message': 'Transaction does not exist.',
        })
    return result
