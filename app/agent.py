"""两个节点的单 Agent 图，复用原生 LLM SDK 和真实工具。"""

import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .tools import TOOL_DEFINITIONS
from .tool_runtime import SYSTEM_PROMPT, execute_tool
from .citations import resolve_citations
from .llm_stream import collect_stream
from .reliability import log_event


MAX_LLM_CALLS = 4
MAX_TOOLS_PER_ROUND = 8


class AgentLimitError(ValueError):
    """达到 Agent 的调用上限，没有生成有效最终回答。"""


class AgentState(TypedDict):
    messages: list[dict]
    llm_calls: int
    tool_calls: list[dict]
    path: list[str]
    final_answer: str | None
    sources: list[dict]


def build_agent(client, model: str, max_llm_calls: int = MAX_LLM_CALLS, checkpointer=None, on_event=None):
    if isinstance(max_llm_calls, bool) or not isinstance(max_llm_calls, int) or max_llm_calls <= 0:
        raise ValueError("max_llm_calls 必须是正整数")

    def agent_node(state: AgentState) -> dict:
        if state["llm_calls"] >= max_llm_calls:
            raise AgentLimitError("Agent 已达到最大 LLM 调用次数，未获得最终回答")
        kwargs = dict(model=model, messages=state["messages"], tools=TOOL_DEFINITIONS,
                      tool_choice="auto", extra_body={"thinking": {"type": "disabled"}})
        if on_event is not None:
            on_event({"event": "reset", "data": {}})
            message = collect_stream(client, on_event, **kwargs)
        else:
            message = client.chat.completions.create(**kwargs).choices[0].message
        calls = message.tool_calls or []
        count = state["llm_calls"] + 1
        log_event("agent_decision", llm_calls=count, tool_requested=bool(calls))
        if len(calls) > MAX_TOOLS_PER_ROUND:
            raise AgentLimitError("单轮模型请求的工具数量超过上限")
        if not calls and (not message.content or not message.content.strip()):
            raise ValueError("模型没有返回工具调用或有效最终回答")
        assistant = {"role": "assistant", "content": message.content}
        sources = []
        if calls:
            assistant["tool_calls"] = [call.model_dump(exclude_none=True) for call in calls]
        else:
            assistant["content"], sources = resolve_citations(message.content, state["messages"])
            has_retrieval = any(call["name"] == "search_knowledge_base" and call["result"].get("results")
                                for call in state["tool_calls"])
            if has_retrieval and not sources and "没有足够依据" not in assistant["content"]:
                raise ValueError("知识库回答缺少可验证的来源引用")
        return {
            "messages": state["messages"] + [assistant],
            "llm_calls": count, "path": state["path"] + ["agent"],
            "final_answer": None if calls else assistant["content"], "sources": sources,
        }

    def route_after_agent(state: AgentState) -> str:
        if state["messages"][-1].get("tool_calls"):
            # 最后一轮还请求工具时直接失败，不再执行无法回传给模型的工具。
            if state["llm_calls"] >= max_llm_calls:
                raise AgentLimitError("Agent 已达到最大 LLM 调用次数，未获得最终回答")
            log_event("agent_route", node="tools")
            return "tools"
        log_event("agent_route", node="END")
        return END

    def tool_node(state: AgentState) -> dict:
        log_event("tool_execution_started", node="tools")
        messages = list(state["messages"])
        records = list(state["tool_calls"])
        for call in state["messages"][-1]["tool_calls"]:
            name = call["function"]["name"]
            arguments = call["function"]["arguments"]
            if on_event is not None:
                on_event({"event": "tool_start", "data": {"name": name, "arguments": arguments}})
            result = execute_tool(name, arguments)
            if on_event is not None:
                on_event({"event": "tool_end", "data": {"name": name, "result": result}})
            result_json = json.dumps(result, ensure_ascii=False, allow_nan=False)
            log_event("tool_execution_finished", node="tools")
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result_json})
            records.append({"id": call["id"], "name": name, "arguments": arguments, "result": result})
        log_event("agent_route", node="agent")
        return {"messages": messages, "tool_calls": records, "path": state["path"] + ["tools"]}

    builder = StateGraph(AgentState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", tool_node)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", route_after_agent, {"tools": "tools", END: END})
    builder.add_edge("tools", "agent")
    return builder.compile(checkpointer=checkpointer)


def run_agent(client, model: str, user_input: str, max_llm_calls: int = MAX_LLM_CALLS,
              *, session_id: str | None = None, checkpointer=None, on_event=None) -> dict:
    if not isinstance(user_input, str) or not user_input.strip():
        raise ValueError("用户输入不能为空")
    if (session_id is None) != (checkpointer is None):
        raise ValueError("session_id 和 checkpointer 必须一起提供")
    graph = build_agent(client, model, max_llm_calls, checkpointer, on_event)
    config = {"recursion_limit": 2 * max_llm_calls + 2}
    previous = {}
    if session_id is not None:
        config["configurable"] = {"thread_id": session_id}
        previous = graph.get_state(config).values
    messages = list(previous.get("messages", [{"role": "system", "content": SYSTEM_PROMPT}]))
    messages.append({"role": "user", "content": user_input})
    log_event("agent_started", node="START")
    try:
        state = graph.invoke({
            "messages": messages,
            "llm_calls": 0, "tool_calls": [], "path": [], "final_answer": None, "sources": [],
        }, config=config)
    except Exception as error:
        log_event("agent_failed", error=error)
        # 丢弃失败轮的中间 checkpoint，恢复上一轮完整的消息协议。
        if checkpointer is not None:
            checkpointer.delete_thread(session_id)
            if previous:
                graph.update_state(config, previous, as_node="agent")
        raise
    path = ["START"] + state["path"] + ["END"]
    log_event("agent_finished", llm_calls=state["llm_calls"])
    return {"user_input": user_input, "tool_calls": state["tool_calls"],
            "final_answer": state["final_answer"], "path": path, "llm_calls": state["llm_calls"],
            "sources": state["sources"]}
