from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Merchant


class MerchantRepository:
    def __init__(self, session: Session):
        self.session = session

    def ensure_exists(self, merchant_id: str, merchant_name: str) -> None:
        statement = insert(Merchant).values(
            merchant_id=merchant_id, merchant_name=merchant_name
        )
        self.session.execute(
            statement.on_conflict_do_nothing(index_elements=['merchant_id'])
        )
