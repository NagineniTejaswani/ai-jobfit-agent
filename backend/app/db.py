from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone

DATABASE_URL = "sqlite:///./jobfit_agent.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    user_message = Column(Text)
    status = Column(String)              # approved / low_confidence / failed / no_action / invalid_input
    verdict_json = Column(Text, nullable=True)   # the final verdict, if any, as JSON text
    step_log = Column(Text)              # full trail: tool calls, critic feedback, etc — as JSON text
    iterations_used = Column(Integer)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_session():
    return SessionLocal()