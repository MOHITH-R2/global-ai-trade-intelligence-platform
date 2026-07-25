from database.connection import get_db
from database.connection import SessionLocal, engine
from database.models import Base, ThreatAlert, TradeRoute, UserAccount, Vessel
from backend.main import initialize_database


def test_get_db_session_generator():
    generator = get_db()
    session = next(generator)
    assert session is not None
    session.close()


def test_initialize_database_seeds_fresh_deployment_database():
    Base.metadata.drop_all(bind=engine)

    initialize_database()

    db = SessionLocal()
    try:
        assert db.query(TradeRoute).count() >= 5
        assert db.query(Vessel).count() >= 5
        assert db.query(ThreatAlert).count() >= 3
        assert db.query(UserAccount).count() >= 3
    finally:
        db.close()
