from sqlalchemy import select
from sqlalchemy.orm import Session


class HealthRepository:
    def __init__(self, session: Session):
        self.session = session

    def check(self) -> None:
        self.session.execute(select(1))
