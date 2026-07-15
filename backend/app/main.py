from fastapi import FastAPI
from pydantic import BaseModel, field_validator
from app.graph import run_agent, run_agent_stream
from app.db import init_db, get_session, AgentRun
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import json
from app.agent_graph import run_agent_langgraph, run_agent_langgraph_stream


app = FastAPI(title="AI Job-Fit Analyzer")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://ai-jobfit-agent.vercel.app/"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()  # creates the .db file and table on startup if they don't exist


class AnalyzeRequest(BaseModel):
    message: str
    resume: str

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v):
        if not v or len(v.strip()) < 5:
            raise ValueError("Message must be at least 5 characters")
        return v

    @field_validator("resume")
    @classmethod
    def resume_not_empty(cls, v):
        if not v or len(v.strip()) < 50:
            raise ValueError("Resume seems too short — please paste your full resume text")
        return v


@app.get("/")
def health_check():
    return {"status": "ok", "message": "AI Job-Fit Analyzer is running"}



@app.post("/analyze")
def analyze(request: AnalyzeRequest):
    result = run_agent_langgraph(request.message, request.resume)
    return result

@app.post("/analyze-stream")
def analyze_stream(request: AnalyzeRequest):
    def event_generator():
        for event in run_agent_langgraph_stream(request.message, request.resume):
            yield f"data: {json.dumps(event)}\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")

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



