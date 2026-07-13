import os
import json
import time
from dotenv import load_dotenv
from groq import Groq, BadRequestError
from pydantic import ValidationError
from app.tools import search_jobs, get_job_details
from app.schemas import JobFitVerdict
from datetime import datetime, timezone
from app.db import AgentRun, get_session, init_db

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

MY_RESUME = """
Software Development Engineer with 1+ year experience in Python/FastAPI backend,
GenAI/LLM applications, RAG pipelines, ChromaDB, LangChain, prompt engineering,
REST APIs, React.js, MongoDB, JWT auth, Docker.
"""

tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "search_jobs",
            "description": "Search live remote job listings by keyword",
            "parameters": {
                "type": "object",
                "properties": {"keywords": {"type": "string"}},
                "required": ["keywords"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_job_details",
            "description": "Get full details of one job using its job id",
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "integer"}},
                "required": ["job_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "submit_verdict",
            "description": "Submit your final structured fit assessment once you have enough information",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_title": {"type": "string"},
                    "company": {"type": "string"},
                    "fit_score": {"type": "integer"},
                    "matching_skills": {"type": "array", "items": {"type": "string"}},
                    "missing_skills": {"type": "array", "items": {"type": "string"}},
                    "reasoning": {"type": "string"}
                },
                "required": ["job_title", "company", "fit_score", "matching_skills", "missing_skills", "reasoning"]
            }
        }
    }
]

AVAILABLE_FUNCTIONS = {"search_jobs": search_jobs, "get_job_details": get_job_details}


def call_llm_with_retry(messages, max_retries=3):
    """Wraps the Groq call so intermittent tool-call formatting failures don't crash the whole agent."""
    for attempt in range(max_retries + 1):
        try:
            return client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                tools=tools_schema,
                tool_choice="auto"
            )
        except BadRequestError as e:
            if "tool_use_failed" in str(e) and attempt < max_retries:
                wait_time = (attempt + 1) * 1.5
                print(f"⚠️ Tool call formatting failed, retrying ({attempt + 1}/{max_retries}) after {wait_time}s...")
                time.sleep(wait_time)
                continue
            raise

def critic_check(verdict: JobFitVerdict) -> tuple[bool, str]:
    """A second, independent LLM call that judges the verdict against a concrete rubric."""
    critique_prompt = f"""
    Evaluate this job-fit verdict against these criteria. Check each one:

    1. Does matching_skills contain at least 2 skills that clearly relate to something in the resume below? 
       (Minor phrasing differences are FINE — e.g. "backend" matching "Python/FastAPI backend", 
       or "React" matching "React.js" both COUNT as valid matches. Only reject if the skill 
       is genuinely absent from the resume, not for wording differences.)
    2. Does missing_skills contain at least 2 skills that clearly relate to something in the job's tags/description,
       using the same flexible matching as above?
    3. Does the reasoning explicitly name at least 2 specific skills (not vague phrases like "strong foundation")?
    4. Is fit_score between 0-100 and roughly consistent with the number of matching vs missing skills?

    Resume: {MY_RESUME}
    Verdict: {verdict.model_dump_json()}

    Check all 4 criteria. Reply with exactly:
    APPROVE if ALL 4 criteria pass.
    REJECT: <criterion number that failed> - <what specifically is missing, be concise>
    """
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": critique_prompt}]
    )
    text = response.choices[0].message.content
    approved = text.strip().upper().startswith("APPROVE")
    return approved, text

def run_agent(user_message: str, max_iterations: int = 6):
    step_log = []  # ← NEW: collects everything that happens this run

    if not user_message or len(user_message.strip()) < 5:
        result = {"status": "invalid_input", "message": "Please enter a real request, e.g. 'find me backend jobs'."}
        _save_run(user_message, result, step_log, 0)
        return result

    system_prompt = f"""My resume:\n{MY_RESUME}

You are a job-fit assistant. ONLY handle requests related to job search and fit assessment.
If the user's message is unrelated to jobs/career (e.g. random text, unrelated topics),
do NOT call any tools — instead reply with plain text explaining you can only help with job search.

When submitting your verdict, fit_score MUST be a number from 0 to 100 (not 0-10),
where 0 = no fit at all and 100 = perfect fit.

Otherwise, use tools to search jobs, get details, then call submit_verdict with your structured assessment."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]

    last_verdict = None

    for step in range(max_iterations):
        print(f"\n--- Loop iteration {step + 1} ---")

        try:
            response = call_llm_with_retry(messages)
        except BadRequestError as e:
            step_log.append({"step": step + 1, "event": "llm_call_failed", "detail": str(e)})
            result = {"status": "low_confidence", "verdict": last_verdict.model_dump() if last_verdict else None} \
                if last_verdict else {"status": "failed", "message": "LLM provider error, please try again."}
            _save_run(user_message, result, step_log, step + 1)
            return result

        reply = response.choices[0].message
        messages.append(reply)

        if not reply.tool_calls:
            print(f"LLM responded without a tool call: {reply.content}")
            step_log.append({"step": step + 1, "event": "no_tool_call", "content": reply.content})
            result = {"status": "no_action", "message": reply.content}
            _save_run(user_message, result, step_log, step + 1)
            return result

        for tool_call in reply.tool_calls:
            fn_name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            print(f"LLM wants to call: {fn_name} with {args}")

            if fn_name == "submit_verdict":
                try:
                    verdict = JobFitVerdict(**args)
                except ValidationError as e:
                    print(f"Verdict failed schema validation: {e}")
                    step_log.append({"step": step + 1, "event": "verdict_validation_failed", "detail": str(e)})
                    messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": f"Invalid format: {e}. Please retry."})
                    continue

                last_verdict = verdict
                print(f"Verdict received, sending to Critic...")
                approved, critique = critic_check(verdict)
                print(f"Critic says: {critique}")
                step_log.append({
                    "step": step + 1, "event": "verdict_submitted",
                    "verdict": verdict.model_dump(), "critic_result": critique, "approved": approved
                })

                if approved:
                    print("\n FINAL VERDICT (approved):")
                    print(verdict.model_dump_json(indent=2))
                    result = {"status": "approved", "verdict": verdict.model_dump()}
                    _save_run(user_message, result, step_log, step + 1)
                    return result
                else:
                    messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": f"Critic rejected: {critique}. Please revise and resubmit."})
            else:
                fn = AVAILABLE_FUNCTIONS[fn_name]
                result_data = fn(**args)
                print(f" Tool result: {result_data}")
                step_log.append({"step": step + 1, "event": "tool_call", "tool": fn_name, "args": args, "result": result_data})
                messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": json.dumps(result_data)})

    if last_verdict:
        print("\n Max iterations reached. Returning last (unverified) attempt.")
        result = {"status": "low_confidence", "verdict": last_verdict.model_dump()}
    else:
        print("\n Max iterations reached with no usable verdict at all.")
        result = {"status": "failed", "verdict": None}

    _save_run(user_message, result, step_log, max_iterations)
    return result


def _save_run(user_message: str, result: dict, step_log: list, iterations_used: int):
    """Persist this run to the database — this is the actual DB/memory skill this project targets."""
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


# if __name__ == "__main__":
#     result = run_agent("Find me 1 remote backend engineer job and assess my fit for it")
#     print("\n\n=== FINAL RESULT ===")
#     print(result)