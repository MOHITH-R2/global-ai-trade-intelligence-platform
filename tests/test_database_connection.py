from database.connection import get_db


def test_get_db_session_generator():
    generator = get_db()
    session = next(generator)
    assert session is not None
    session.close()
