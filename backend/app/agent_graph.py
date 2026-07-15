# app/agent_graph.py

import json
from typing import TypedDict, Annotated
import operator
from groq import BadRequestError
from pydantic import ValidationError
from langgraph.graph import StateGraph, END
from app.graph import client, tools_schema, AVAILABLE_FUNCTIONS, call_llm_with_retry, critic_check, _save_run
from app.schemas import JobFitVerdict


class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    resume: str
    last_verdict: dict | None
    step_log: list
    iterations: int
    final_result: dict | None


def agent_node(state: AgentState):
    response = call_llm_with_retry(state["messages"])
    reply = response.choices[0].message
    return {"messages": [reply], "iterations": state["iterations"] + 1}


def tool_node(state: AgentState):
    last_message = state["messages"][-1]
    new_messages = []
    new_step_log = []
    updated_last_verdict = state["last_verdict"]

    for tool_call in last_message.tool_calls:
        fn_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)

        if fn_name == "submit_verdict":
            try:
                verdict = JobFitVerdict(**args)
            except ValidationError as e:
                new_messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": f"Invalid format: {e}. Retry."})
                continue

            approved, critique = critic_check(verdict, state["resume"])
            new_step_log.append({"event": "verdict_submitted", "verdict": verdict.model_dump(), "critic_result": critique, "approved": approved})
            updated_last_verdict = verdict.model_dump()

            if approved:
                new_messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": "Approved."})
            else:
                new_messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": f"Critic rejected: {critique}. Revise."})
        else:
            fn = AVAILABLE_FUNCTIONS[fn_name]
            result_data = fn(**args)
            new_step_log.append({"event": "tool_call", "tool": fn_name, "args": args, "result": result_data})
            new_messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": json.dumps(result_data)})

    return {
        "messages": new_messages,
        "step_log": state["step_log"] + new_step_log,
        "last_verdict": updated_last_verdict
    }


def should_continue(state: AgentState):
    last_message = state["messages"][-1]
    if not last_message.tool_calls:
        return "end_no_action"
    if state["iterations"] >= 6:
        return "end_max_iterations"
    return "tools"


def after_tools(state: AgentState):
    step_log = state["step_log"]
    if step_log and step_log[-1].get("event") == "verdict_submitted" and step_log[-1].get("approved"):
        return "end_approved"
    if state["iterations"] >= 6:
        return "end_max_iterations"
    return "agent"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")

    graph.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "end_no_action": END, "end_max_iterations": END}
    )
    graph.add_conditional_edges(
        "tools",
        after_tools,
        {"agent": "agent", "end_approved": END, "end_max_iterations": END}
    )
    return graph.compile()


compiled_graph = build_graph()


def run_agent_langgraph(user_message: str, resume: str):
    if not user_message or len(user_message.strip()) < 5:
        result = {"status": "invalid_input", "message": "Please enter a real request."}
        _save_run(user_message, result, [], 0)
        return result

    system_prompt = f"""My resume:\n{resume}

You are a job-fit assistant. ONLY handle requests related to job search and fit assessment.
When submitting your verdict, fit_score MUST be 0-100.
Use tools to search jobs, get details, then call submit_verdict."""

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

    final_state = compiled_graph.invoke(initial_state)
    step_log = final_state["step_log"]
    last_verdict = final_state["last_verdict"]
    iterations = final_state["iterations"]

    if step_log and step_log[-1].get("event") == "verdict_submitted" and step_log[-1].get("approved"):
        result = {"status": "approved", "verdict": last_verdict}
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

    system_prompt = f"""My resume:\n{resume}

You are a job-fit assistant. ONLY handle requests related to job search and fit assessment.
When submitting your verdict, fit_score MUST be 0-100.
Use tools to search jobs, get details, then call submit_verdict."""

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

    for state in compiled_graph.stream(initial_state, stream_mode="values"):
        final_state = state  # always the full, accumulated state

        # Detect a new agent turn (a new message appended) to emit "Deciding next step"
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
                label = "🔍 Searching for jobs..." if log["tool"] == "search_jobs" else "📋 Getting job details..."
            elif log["event"] == "verdict_submitted":
                label = "✅ Verdict approved!" if log["approved"] else "🧐 Refining the assessment..."
            else:
                label = "⚙️ Processing..."
            yield {"type": "step", "label": label}
        seen_steps = len(new_logs)

    step_log = final_state.get("step_log", [])
    last_verdict = final_state.get("last_verdict")
    iterations = final_state.get("iterations", 0)

    if step_log and step_log[-1].get("event") == "verdict_submitted" and step_log[-1].get("approved"):
        result = {"status": "approved", "verdict": last_verdict}
    elif last_verdict:
        result = {"status": "low_confidence", "verdict": last_verdict}
    else:
        result = {"status": "failed", "verdict": None}

    _save_run(user_message, result, step_log, iterations)
    yield {"type": "final", "result": result}

