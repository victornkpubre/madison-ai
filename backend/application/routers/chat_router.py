from fastapi import APIRouter
from langchain_core.messages import HumanMessage
from fastapi.responses import StreamingResponse
from backend.application.requests import ChatRequest, ResumeRequest
from backend.application.streamer import stream_graph

router = APIRouter()

@router.post("/chat")
async def chat(req: ChatRequest):
    """
    Universal entry point for all agent conversations.
    The supervisor routes to assist_agent, idea_agent, or reply_agent
    based on the message content and whether chat_id is present.
    """
    config = {"configurable": {"thread_id": req.thread_id}}
    graph_input = {
        "messages": [HumanMessage(req.message)],
        "chat_id":  req.chat_id,
    }
    ep = {
        "endpoint":  "POST /chat",
        "thread_id": req.thread_id[:8] + "…",
        "graph":     "main_graph",
        "input":     f"HumanMessage({req.message[:50]!r})",
    }
    return StreamingResponse(
        stream_graph(main_graph, graph_input, config, ep, _MAIN_NODES),
        media_type="text/event-stream")


@router.post("/resume")
async def resume(req: ResumeRequest):
    """
    Resume any interrupted graph — capture slices, creator questions,
    viewer reply approvals, or idea generator prompts.
    The same endpoint handles all interrupt types because the thread_id
    and checkpoint identify exactly which sub-agent was paused.
    """
    config = {"configurable": {"thread_id": req.thread_id}}
    val    = req.value or {}
    if "records" in val:
        inp = (f"Command(resume={{records: {len(val['records'])}, "
               f"found: {val.get('found', True)}}})")
    elif "answer" in val:
        inp = f"Command(resume={{answer: {val['answer'][:40]!r}}})"
    else:
        inp = f"Command(resume={req.action!r})"
    ep = {
        "endpoint":  "POST /resume",
        "thread_id": req.thread_id[:8] + "…",
        "graph":     "main_graph",
        "input":      inp,
    }
    return StreamingResponse(
        stream_graph(main_graph, _resume_command(req), config, ep, _MAIN_NODES),
        media_type="text/event-stream")

