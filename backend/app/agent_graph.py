import json
import re
from typing import TypedDict, Annotated
import operator
from groq import BadRequestError
from pydantic import ValidationError
from langgraph.graph import StateGraph, END
from app.graph import client, tools_schema, AVAILABLE_FUNCTIONS, call_llm_with_retry, _save_run, GROQ_STAGE1_MODEL
from app.schemas import MultiJobFitVerdict


def extract_json(content: str) -> dict:
    """Safely extracts and parses JSON even if wrapped in markdown codeblocks or surrounded by text."""
    if not content:
        return {}
    text = content.strip()
    text = re.sub(r'^```json\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^```\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
    return {}


class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    resume: str
    last_verdict: dict | None
    step_log: list
    iterations: int
    final_result: dict | None


def clean_messages(messages):
    cleaned = []
    for msg in messages:
        if isinstance(msg, dict):
            cleaned.append(msg)
        elif hasattr(msg, "tool_calls") and msg.tool_calls:
            cleaned.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in msg.tool_calls
                ]
            })
        elif hasattr(msg, "content"):
            cleaned.append({
                "role": getattr(msg, "role", "assistant"),
                "content": msg.content or ""
            })
    return cleaned


def agent_node(state: AgentState):
    msgs = clean_messages(state["messages"])
    has_tool_result = any(m.get("role") == "tool" for m in msgs)

    if has_tool_result:
        tool_content = next((m["content"] for m in reversed(msgs) if m.get("role") == "tool"), "[]")
        try:
            raw_jobs = json.loads(tool_content)
        except Exception:
            raw_jobs = []

        if not isinstance(raw_jobs, list) or len(raw_jobs) == 0:
            empty_verdict = {"verdicts": []}
            return {
                "messages": msgs,
                "iterations": state["iterations"] + 1,
                "last_verdict": empty_verdict,
                "step_log": state["step_log"] + [{
                    "event": "verdict_submitted",
                    "verdict": empty_verdict,
                    "critic_result": "No jobs found",
                    "approved": True
                }]
            }

        # Slim payload: send only title, tags, and an 80-char summary to save tokens
        compact_jobs = [
            {
                "id": j.get("id"),
                "title": j.get("title"),
                "tags": j.get("tags", [])[:8],
                "summary": (j.get("description", ""))[:80]
            }
            for j in raw_jobs
        ]

        stage1_messages = [
            {
                "role": "system",
                "content": (
                    f"Resume:\n{state['resume']}\n\n"
                    "You are a job-fit screening AI. Score each job 0-100 against the resume.\n"
                    "Scoring Rubric: Domain match (35pts) + Technical/Hard skills (35pts) + Seniority (20pts) + Soft skills (10pts).\n"
                    "If a job is in a completely different profession, score MUST be <= 15.\n"
                    "Respond with a JSON object containing a 'shortlist' array with 'id' and 'estimated_fit'."
                )
            },
            {
                "role": "user",
                "content": (
                    f"Score these {len(compact_jobs)} jobs against my resume.\n"
                    'Return JSON format: {"shortlist": [{"id": 123, "estimated_fit": 80}]}\n\n'
                    f"Jobs:\n{json.dumps(compact_jobs)}"
                )
            }
        ]

        stage1_response = call_llm_with_retry(stage1_messages, response_format={"type": "json_object"}, model_override=GROQ_STAGE1_MODEL)
        stage1_content = stage1_response.choices[0].message.content or "{}"

        s1_items = []
        try:
            s1_data = extract_json(stage1_content)
            if isinstance(s1_data, list):
                s1_items = s1_data
            else:
                s1_items = s1_data.get("shortlist", []) or s1_data.get("jobs", []) or []
        except Exception as e:
            print(f"Error parsing Stage 1 shortlist: {e}")

        def extract_s1_score(item):
            if not isinstance(item, dict):
                return 0
            val = item.get("estimated_fit") or item.get("score") or item.get("fit_score") or item.get("fit") or 0
            try:
                return float(val)
            except (ValueError, TypeError):
                return 0

        # Check for qualified jobs with score >= 50%
        qualified_s1 = [item for item in s1_items if extract_s1_score(item) >= 50]

        # FAST EXIT: If no jobs scored >= 50%, skip Stage 2 entirely
        if not qualified_s1:
            # Only surface partial matches if they score >= 25% AND domain_match is True (or not explicitly False)
            # This prevents completely unrelated jobs (Copywriter, Sales) from showing as partials for a candidate
            PARTIAL_FLOOR = 25
            domain_adjacent = [
                item for item in s1_items
                if extract_s1_score(item) >= PARTIAL_FLOOR and item.get("domain_match") is not False
            ]
            top_partial = domain_adjacent[:3] if domain_adjacent else []
            raw_lookup = {j["id"]: j for j in raw_jobs}

            if top_partial:
                partial_verdicts = []
                for item in top_partial:
                    raw = raw_lookup.get(item.get("id"), {})
                    partial_verdicts.append({
                        "job_title": item.get("title") or raw.get("title", "Untitled Role"),
                        "company": item.get("company") or raw.get("company", "Unknown Company"),
                        "fit_score": extract_s1_score(item) or 25,
                        "matching_skills": item.get("matching_skills", []),
                        "missing_skills": item.get("missing_skills", []),
                        "reasoning": item.get("quick_reason", "Partial domain alignment — some relevant skills found but key competencies are missing."),
                        "url": raw.get("url")
                    })
                v_dict = {"verdicts": partial_verdicts}
                status_note = f"Stage 1 found 0 jobs >= 50%. Returning {len(partial_verdicts)} closest domain-adjacent partial matches (>= {PARTIAL_FLOOR}%) without Stage 2."
            else:
                # All top results are in a completely different domain — don't mislead the user
                v_dict = {"verdicts": []}
                status_note = f"Stage 1 found 0 jobs >= {PARTIAL_FLOOR}% in the candidate's domain. No partial matches to show."

            print(status_note)
            return {
                "messages": msgs,
                "iterations": state["iterations"] + 1,
                "last_verdict": v_dict,
                "step_log": state["step_log"] + [
                    {"event": "stage1_shortlist", "count": 0, "total": len(raw_jobs)},
                    {
                        "event": "verdict_submitted",
                        "verdict": v_dict,
                        "critic_result": status_note,
                        "approved": False,
                        "low_confidence": True
                    }
                ]
            }

        # Otherwise, take top 4-6 qualified jobs for STAGE 2 deep dive!
        shortlist_ids = [item["id"] for item in qualified_s1 if "id" in item]
        shortlisted_jobs = [j for j in raw_jobs if j.get("id") in shortlist_ids][:6]

        print(f"Stage 1 shortlisted {len(shortlisted_jobs)} relevant roles (>=50%) from {len(raw_jobs)} candidates.")

        # ------------------------------------------------------------
        # STAGE 2: Deep-Dive Re-Evaluation with Full Descriptions
        # ------------------------------------------------------------
        detailed_jobs = [
            {
                "id": j.get("id"),
                "title": j.get("title"),
                "company": j.get("company"),
                "url": j.get("url"),
                "tags": j.get("tags", []),
                "full_description": j.get("full_description") or j.get("description", "")
            }
            for j in shortlisted_jobs
        ]

        stage2_messages = [
            {
                "role": "system",
                "content": (
                    f"My resume:\n{state['resume']}\n\n"
                    "You are a universal job-fit evaluation AI assessing candidate fit across all career paths "
                    "(HR, Sales, Marketing, Finance, Tech, Design, Operations, Customer Success, Legal, Healthcare, etc.).\n\n"
                    "UNIVERSAL EVALUATION RUBRIC:\n"
                    "1. Domain & Core Function (35%): Role must match candidate's profession.\n"
                    "2. Specialized Domain Skills & Tools (35%): ATS/Payroll for HR, CRM/Prospecting for Sales, Figma/Adobe for Design, Tech Stack for Devs, GAAP/Excel for Finance, Campaigns for Marketing, etc.\n"
                    "3. Seniority & Scope (20%): Match experience level. If years are not stated, assume entry-level and note it in reasoning.\n"
                    "4. Soft Skills & Culture (10%): Communication/collaboration only supplements a matching core domain; it never substitutes for domain mismatch.\n\n"
                    "- 80-100% (High Fit): Strong alignment on domain, core role competencies, and seniority.\n"
                    "- 50-79% (Moderate Fit): Same professional domain with transferable core skills, but secondary tool or experience gaps.\n"
                    "- 0-49% (Low/Weak Fit): Mismatched profession, unrelated domain, or missing essential core competencies.\n\n"
                    "You must always output a valid JSON object."
                )
            },
            {
                "role": "user",
                "content": (
                    f"Here are the full detailed job descriptions for the {len(detailed_jobs)} shortlisted candidate roles:\n"
                    f"{json.dumps(detailed_jobs)}\n\n"
                    "Evaluate each shortlisted job against my resume using the universal rubric.\n"
                    "Output a valid JSON object with key 'verdicts' matching this structure:\n"
                    "{\n"
                    '  "verdicts": [\n'
                    '    {\n'
                    '      "job_title": "...",\n'
                    '      "company": "...",\n'
                    '      "fit_score": 85,\n'
                    '      "matching_skills": ["Exact skills/tools from resume relevant to role"],\n'
                    '      "missing_skills": ["Key job requirements absent from resume"],\n'
                    '      "reasoning": "2-3 concise sentences on domain match, core strengths, and gaps.",\n'
                    '      "url": "..."\n'
                    '    }\n'
                    '  ]\n'
                    "}"
                )
            }
        ]

        stage2_response = call_llm_with_retry(stage2_messages, response_format={"type": "json_object"})
        reply = stage2_response.choices[0].message
        content = reply.content or "{}"
        try:
            data = extract_json(content)
            verdict = MultiJobFitVerdict(**data)
            v_dict = verdict.model_dump()

            # Filter out weak matches (< 50%) in Stage 2 results
            original_count = len(v_dict.get("verdicts", []))
            v_dict["verdicts"] = [j for j in v_dict.get("verdicts", []) if j.get("fit_score", 0) >= 50]
            filtered_count = original_count - len(v_dict["verdicts"])
            if filtered_count > 0:
                print(f"Filtered out {filtered_count} weak matches (< 50%) from {original_count} evaluated.")

            return {
                "messages": [reply],
                "iterations": state["iterations"] + 1,
                "last_verdict": v_dict,
                "step_log": state["step_log"] + [
                    {"event": "stage1_shortlist", "count": len(shortlisted_jobs), "total": len(raw_jobs)},
                    {"event": "stage2_deepdive", "count": len(v_dict["verdicts"])},
                    {
                        "event": "verdict_submitted",
                        "verdict": v_dict,
                        "critic_result": "Auto-approved",
                        "approved": True
                    }
                ]
            }
        except Exception as e:
            print(f"Error parsing MultiJobFitVerdict from JSON: {e}")
            return {"messages": [reply], "iterations": state["iterations"] + 1}
    else:
        # First step: search jobs
        response = call_llm_with_retry(msgs, tools=tools_schema)
        reply = response.choices[0].message
        return {"messages": [reply], "iterations": state["iterations"] + 1}


def tool_node(state: AgentState):
    last_message = state["messages"][-1]
    new_messages = []
    new_step_log = []

    if getattr(last_message, "tool_calls", None):
        for tool_call in last_message.tool_calls:
            fn_name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            if fn_name in AVAILABLE_FUNCTIONS:
                fn = AVAILABLE_FUNCTIONS[fn_name]
                result_data = fn(**args)
                new_step_log.append({"event": "tool_call", "tool": fn_name, "args": args, "result": result_data})
                new_messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": json.dumps(result_data)})

    return {
        "messages": new_messages,
        "step_log": state["step_log"] + new_step_log,
        "last_verdict": state["last_verdict"]
    }


def should_continue(state: AgentState):
    if state.get("last_verdict"):
        return "end_approved"
    last_message = state["messages"][-1]
    if getattr(last_message, "tool_calls", None):
        return "tools"
    if state["iterations"] >= 6:
        return "end_max_iterations"
    return "end_no_action"


def after_tools(state: AgentState):
    if state.get("last_verdict"):
        return "end_approved"
    return "agent"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")

    graph.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "end_approved": END, "end_no_action": END, "end_max_iterations": END}
    )
    graph.add_conditional_edges(
        "tools",
        after_tools,
        {"agent": "agent", "end_approved": END}
    )
    return graph.compile()


compiled_graph = build_graph()

# ============================================================
# ACTIVE IMPLEMENTATION — LangGraph-based agent
# ============================================================
# This is the current, live implementation used by /analyze and
# /analyze-stream (see app/main.py). It replaces the hand-built
# loop originally written in app/graph.py (run_agent /
# run_agent_stream), which is kept there for reference only.
#
# Built using LangGraph's StateGraph: an `agent` node (decides
# what to do next) and a `tools` node (executes tool calls / the
# Critic check), connected by conditional edges that route based
# on tool-call presence, Critic approval, and iteration limits.
# ============================================================

def run_agent_langgraph(user_message: str, resume: str):
    if not user_message or len(user_message.strip()) < 5:
        result = {"status": "invalid_input", "message": "Please enter a real request."}
        _save_run(user_message, result, [], 0)
        return result

    system_prompt = f"""My resume:
{resume}

You are an expert job-fit assistant.
Step 1: Search live remote jobs using `search_jobs` with relevant keywords.
Step 2: When search results are returned, evaluate the jobs against the resume and output a JSON object with key "verdicts" containing at least 5 to 10 evaluated jobs sorted by `fit_score` descending (0-100).
For each job include: `job_title`, `company`, `fit_score`, `matching_skills`, `missing_skills`, `reasoning` (1-2 sentences), and `url`."""

    initial_state = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "resume": resume,
        "last_verdict": None,
        "step_log": [],
        "iterations": 0,
        "final_result": None
    }

    try:
        final_state = compiled_graph.invoke(initial_state)
    except RuntimeError as e:
        if str(e) == "RATE_LIMIT":
            result = {
                "status": "error",
                "message": "The AI service is temporarily rate-limited. Please try again in a minute."
            }
            _save_run(user_message, result, [], 0)
            return result
        raise

    step_log = final_state["step_log"]
    last_verdict = final_state["last_verdict"]
    iterations = final_state["iterations"]

    has_approved_jobs = bool(
        last_verdict and isinstance(last_verdict.get("verdicts"), list) and 
        any(j.get("fit_score", 0) >= 50 for j in last_verdict["verdicts"])
    )

    if step_log and step_log[-1].get("event") == "verdict_submitted":
        if has_approved_jobs and step_log[-1].get("approved"):
            result = {"status": "approved", "verdict": last_verdict}
        elif last_verdict and last_verdict.get("verdicts"):
            result = {
                "status": "low_confidence",
                "verdict": last_verdict,
                "message": "No strong matches (≥50%) found on live remote boards. Showing closest available listings below with identified gaps:"
            }
        else:
            result = {
                "status": "no_match",
                "verdict": {"verdicts": []},
                "message": "No jobs met the minimum score for your resume."
            }
    elif last_verdict:
        result = {"status": "low_confidence", "verdict": last_verdict}
    else:
        result = {"status": "failed", "verdict": None}

    _save_run(user_message, result, step_log, iterations)
    return result

def run_agent_langgraph_stream(user_message: str, resume: str):
    if not user_message or len(user_message.strip()) < 5:
        yield {"type": "final", "result": {"status": "invalid_input", "message": "Please enter a real request."}}
        return

    system_prompt = f"""My resume:
{resume}

You are an expert job-fit assistant.
Step 1: Search live remote jobs using `search_jobs` with relevant keywords.
Step 2: When search results are returned, evaluate the jobs against the resume and output a JSON object with key "verdicts" containing at least 5 to 10 evaluated jobs sorted by `fit_score` descending (0-100).
For each job include: `job_title`, `company`, `fit_score`, `matching_skills`, `missing_skills`, `reasoning` (1-2 sentences), and `url`."""

    initial_state = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "resume": resume,
        "last_verdict": None,
        "step_log": [],
        "iterations": 0,
        "final_result": None
    }

    final_state = initial_state
    seen_steps = 0
    last_seen_message_count = 0

    try:
        for state in compiled_graph.stream(initial_state, stream_mode="values"):
            final_state = state  # always the full, accumulated state

            messages = state.get("messages", [])
            if len(messages) > last_seen_message_count:
                last_msg = messages[-1]
                if getattr(last_msg, "tool_calls", None) is not None or (
                    isinstance(last_msg, dict) and last_msg.get("role") == "assistant"
                ):
                    yield {"type": "step", "label": "🤔 Deciding next step..."}
                last_seen_message_count = len(messages)

            new_logs = state.get("step_log", [])
            for log in new_logs[seen_steps:]:
                if log["event"] == "tool_call":
                    label = "🔍 Searching live jobs on remote boards..." if log["tool"] == "search_jobs" else "📋 Getting job details..."
                elif log["event"] == "stage1_shortlist":
                    if log.get("count", 0) > 0:
                        label = f"📊 Stage 1: Shortlisted {log.get('count')} roles from {log.get('total', 'all')} candidates..."
                    else:
                        label = f"📊 Stage 1: Screened {log.get('total', 'all')} candidates (no high-confidence matches)..."
                elif log["event"] == "stage2_deepdive":
                    label = "🔬 Stage 2: Deep-dive assessment on shortlisted roles..."
                elif log["event"] == "verdict_submitted":
                    label = "✅ Verdict approved!" if log.get("approved") else "📋 Formulating gap analysis..."
                else:
                    label = "⚙️ Processing..."
                yield {"type": "step", "label": label}
            seen_steps = len(new_logs)
    except RuntimeError as e:
        if str(e) == "RATE_LIMIT":
            result = {
                "status": "error",
                "message": "The AI service is temporarily rate-limited. Please try again in a minute."
            }
            _save_run(user_message, result, [], 0)
            yield {"type": "final", "result": result}
            return
        raise

    step_log = final_state.get("step_log", [])
    last_verdict = final_state.get("last_verdict")
    iterations = final_state.get("iterations", 0)
    messages = final_state.get("messages", [])

    has_approved_jobs = bool(
        last_verdict and isinstance(last_verdict.get("verdicts"), list) and 
        any(j.get("fit_score", 0) >= 50 for j in last_verdict["verdicts"])
    )

    if step_log and step_log[-1].get("event") == "verdict_submitted":
        if has_approved_jobs and step_log[-1].get("approved"):
            result = {"status": "approved", "verdict": last_verdict}
        elif last_verdict and last_verdict.get("verdicts"):
            result = {
                "status": "low_confidence",
                "verdict": last_verdict,
                "message": "No strong matches (≥50%) found on live remote boards. Showing closest available listings below with identified gaps:"
            }
        else:
            result = {
                "status": "no_match",
                "verdict": {"verdicts": []},
                "message": "No jobs met the minimum score for your resume."
            }
    elif last_verdict:
        result = {"status": "low_confidence", "verdict": last_verdict}
    elif messages and not getattr(messages[-1], "tool_calls", None) and getattr(messages[-1], "content", None):
        result = {"status": "no_action", "message": messages[-1].content}
    elif iterations >= 6:
        result = {
            "status": "failed",
            "verdict": None,
            "message": "Reached the maximum number of steps without producing a fit assessment. Try rephrasing your request or narrowing the job search."
        }
    else:
        result = {
            "status": "failed",
            "verdict": None,
            "message": "Something unexpected happened and no result could be produced."
        }

    _save_run(user_message, result, step_log, iterations)
    yield {"type": "final", "result": result}

