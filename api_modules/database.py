from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
import os
from sqlalchemy.pool import QueuePool

load_dotenv()

DATABASE_URL = "sqlite:///ia_database.db"

# Update engine configuration for production
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,  # Use connection pooling
    pool_size=10,  # Adjust based on your workload
    max_overflow=20,
    pool_timeout=30,
    pool_pre_ping=True  # Enable connection health checks
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
