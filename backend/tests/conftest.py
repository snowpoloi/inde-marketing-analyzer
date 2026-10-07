import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def db():
    url = os.environ.get("SUPPLIER_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set SUPPLIER_TEST_DATABASE_URL to an isolated, migrated PostgreSQL test database.")
    engine = create_engine(url)
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(connection, autoflush=False, join_transaction_mode="create_savepoint")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0011_supplier_catalog"
        yield session
        session.close()
        transaction.rollback()
    engine.dispose()
