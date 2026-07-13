from fastapi import FastAPI
from pydantic import BaseModel
from app.graph import run_agent
from app.db import init_db, get_session, AgentRun
import json

app = FastAPI(title="AI Job-Fit Analyzer")

init_db()  # creates the .db file and table on startup if they don't exist


class AnalyzeRequest(BaseModel):
    message: str


@app.get("/")
def health_check():
    return {"status": "ok", "message": "AI Job-Fit Analyzer is running"}


@app.post("/analyze")
def analyze(request: AnalyzeRequest):
    result = run_agent(request.message)
    return result


@app.get("/history")
def get_history(limit: int = 10):
    session = get_session()
    try:
        runs = session.query(AgentRun).order_by(AgentRun.id.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "timestamp": r.timestamp,
                "user_message": r.user_message,
                "status": r.status,
                "verdict": json.loads(r.verdict_json) if r.verdict_json else None,
                "iterations_used": r.iterations_used,
                "step_log": json.loads(r.step_log)
            }
            for r in runs
        ]
    finally:
        session.close()