from pydantic import BaseModel, Field
from typing import List

class JobFitVerdict(BaseModel):
    job_title: str
    company: str
    fit_score: int = Field(..., ge=0, le=100, description="0-100 how well the candidate fits")
    matching_skills: List[str]
    missing_skills: List[str]
    reasoning: str