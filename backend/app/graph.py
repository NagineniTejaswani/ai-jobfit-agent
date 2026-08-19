import os
import json
import time
from dotenv import load_dotenv
from groq import Groq, BadRequestError , RateLimitError
from pydantic import ValidationError
from app.tools import search_jobs, get_job_details
from app.schemas import JobFitVerdict, MultiJobFitVerdict
from datetime import datetime, timezone
from app.db import AgentRun, get_session, init_db

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY", "missing-key"))
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_STAGE1_MODEL = os.getenv("GROQ_STAGE1_MODEL", "openai/gpt-oss-20b")




tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "search_jobs",
            "description": "Search live remote job listings by keyword. Returns job title, company, URL, description snippet, and tags for each result.",
            "parameters": {
                "type": "object",
                "properties": {"keywords": {"type": "string"}},
                "required": ["keywords"]
            }
        }
    }
]

AVAILABLE_FUNCTIONS = {"search_jobs": search_jobs}


def call_llm_with_retry(messages, max_retries=3, model_override=None, **kwargs):
    """Wraps the Groq call with retries and handles tools / response_format kwargs."""
    model = model_override or GROQ_MODEL
    current_kwargs = dict(kwargs)
    for attempt in range(max_retries + 1):
        try:
            return client.chat.completions.create(
                model=model,
                messages=messages,
                **current_kwargs
            )
        except BadRequestError as e:
            err_str = str(e)
            if ("tool_use_failed" in err_str or "json_validate_failed" in err_str) and attempt < max_retries:
                wait_time = (attempt + 1) * 1.5
                print(f"Groq validation/tool error ({err_str[:80]}), retrying ({attempt + 1}/{max_retries}) after {wait_time}s...")
                time.sleep(wait_time)
                # If json_validate_failed persists on retries, drop response_format constraint so model can return text JSON
                if "json_validate_failed" in err_str and "response_format" in current_kwargs:
                    current_kwargs.pop("response_format", None)
                continue
            raise
        except RateLimitError as e:
            if attempt < max_retries:
                wait_time = (attempt + 1) * 10  # 10s, 20s, 30s backoff
                print(f"Groq rate limit hit, retrying ({attempt + 1}/{max_retries}) after {wait_time}s... Error: {e}")
                time.sleep(wait_time)
                continue
            print(f"Groq rate limit hit on all retries: {e}")
            raise RuntimeError("RATE_LIMIT") from e

def _save_run(user_message: str, result: dict, step_log: list, iterations_used: int):
    """Persist this run to the database."""
    session = get_session()
    try:
        run = AgentRun(
            user_message=user_message,
            status=result.get("status"),
            verdict_json=json.dumps(result.get("verdict")) if result.get("verdict") else None,
            step_log=json.dumps(step_log),
            iterations_used=iterations_used
        )
        session.add(run)
        session.commit()
        print(f"Run saved to database (id={run.id})")
    except Exception as e:
        print(f"Failed to save run to database: {e}")
    finally:
        session.close()



