import os
import shutil
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEEDED_DB_PATH = PROJECT_ROOT / "database" / "trade_intelligence.db"
RUNTIME_DB_DIR = PROJECT_ROOT / ".runtime"
RUNTIME_DB_PATH = RUNTIME_DB_DIR / "trade_intelligence.db"


def _default_sqlite_url():
    RUNTIME_DB_DIR.mkdir(parents=True, exist_ok=True)
    if SEEDED_DB_PATH.exists() and not RUNTIME_DB_PATH.exists():
        shutil.copy2(SEEDED_DB_PATH, RUNTIME_DB_PATH)
    return f"sqlite:///{RUNTIME_DB_PATH.as_posix()}"


DATABASE_URL = os.getenv("DATABASE_URL") or _default_sqlite_url()

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
