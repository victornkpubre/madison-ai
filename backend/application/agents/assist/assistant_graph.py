"""
assistant_graph.py
══════════════════
The creator's assistant. The creator specifies WHICH fields to capture
(e.g. tiktok_username, telegram, age, location) and HOW MANY records. The agent
must have BOTH before capturing; if either is missing it asks.

The COUNT is authoritative — enforced in code here, not left to the model:
capture_node keeps requesting slices and accumulating records in state until
`target` is reached (or a safety cap / empty stream stops it), then ends.

  agent (tools: start_capture, ask_creator)
     |                         |
     | start_capture(fields,N) | ask_creator(question)
     v                         v
  capture --interrupt loop-->  ask --interrupt--> answer --+
     |  accumulate records                                  |
     |  until len(records) >= target                        |
     ^------------------------------------------------------+
     v  (target reached / stream gone)
   summarise -> END
"""
import json

from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from config import settings
from telegram_tools import send_message_to_user, broadcast_to_usernames

MAX_SLICES = 40
KNOWN_FIELDS = ["tiktok_username", "telegram", "email", "age", "location"]


# ── email + template tools ────────────────────────────────────────────────────

@tool
async def connect_email_account(email: str,
                                 password: str,
                                 display_name: str = "") -> str:
    """
    Connect an email account so the system can send emails from it.
    Uses SMTP with an application password — works with Gmail, Outlook, Yahoo, and most
    other providers. No OAuth or Google Cloud setup required.

    How to get an application password:
      Gmail:   myaccount.google.com → Security → App passwords → generate one
      Outlook: account.microsoft.com → Security → Advanced → App passwords

    Args:
        email:        the email address to connect, e.g. victor@gmail.com
        password:     the application password (16 characters, spaces are fine)
        display_name: optional name shown as the sender, e.g. "Victor"
    """
    from email_client import verify_smtp_credentials, save_smtp_account, get_smtp_preset

    password = password.replace(" ", "")
    preset   = get_smtp_preset(email)
    host     = preset["smtp_host"]
    port     = preset["smtp_port"]

    test = await verify_smtp_credentials(email, password, host, port)
    if not test["ok"]:
        return (
            f"✗ Could not connect {email}.\n"
            f"  Error: {test['error']}\n"
            f"  Make sure you are using an application password, not your real password.\n"
            f"  Gmail: myaccount.google.com/apppasswords\n"
            f"  Outlook: account.microsoft.com → Security → App passwords"
        )

    save_smtp_account(
        email        = email,
        password     = password,
        display_name = display_name or email.split("@")[0].capitalize(),
        smtp_host    = host,
        smtp_port    = port,
        imap_host    = preset["imap_host"],
        imap_port    = preset["imap_port"],
    )
    return (
        f"✓ {email} connected successfully via {host}.\n"
        f"  You can now use it to send emails."
    )


@tool
def list_connected_senders() -> str:
    """
    List all email accounts connected to the system that can be used to send emails.
    Always call this before send_emails_from_template to confirm a sender is available.
    Returns each connected address and its provider (smtp, gmail, outlook).
    """
    from email_client import list_email_accounts
    accounts = list_email_accounts()
    if not accounts:
        return (
            "No email accounts are connected yet.\n"
            "Ask the creator for their email address and application password,\n"
            "then call connect_email_account to add one."
        )
    lines = ["Connected sender accounts:"]
    for a in accounts:
        lines.append(f"  • {a['email']}  ({a.get('provider', 'unknown')})")
    return "\n".join(lines)


@tool
def list_email_templates() -> str:
    """
    List all available email message templates.
    Call this before asking the creator which template to use.
    Returns each template's name, subject line, and the variables it uses.
    """
    from templates import list_templates_for_channel
    templates = list_templates_for_channel("email")
    if not templates:
        return "No templates found. Use create_email_template to make one, or use 'default_intro'."
    lines = []
    for t in templates:
        label = " (default)" if t.get("is_default") else ""
        lines.append(f"• {t['name']}{label}")
        if t.get("subject"):
            lines.append(f"  subject: {t['subject']}")
        vars_ = t.get("variables", [])
        if vars_:
            lines.append(f"  uses: {', '.join(vars_)}")
    return "\n".join(lines)


@tool
def create_email_template(name: str, subject: str, body: str) -> str:
    """
    Save a new email template.
    Use {{variable}} placeholders for dynamic content.

    Available variables: {{first_name}}, {{last_name}}, {{email}},
    {{creator_name}}, {{creator_bio}}, {{creator_cta}}

    Args:
        name:    short unique name, e.g. 'networking_intro'
        subject: email subject line (can contain variables)
        body:    email body text (can contain variables)
    """
    from templates import save_template
    t = save_template(name, "email", body, subject)
    vars_ = t.get("variables", [])
    return (f"✓ Template '{name}' saved.\n"
            f"  Variables detected: {', '.join(vars_) or 'none'}\n"
            f"  Subject: {subject}")


@tool
async def send_emails_from_template(emails: list[str],
                                     template_name: str,
                                     from_email: str) -> str:
    """
    Send an email to each address using a named template.
    Resolves {{variables}} using the contact's captured data and the
    creator's stored profile (name, bio, cta).

    Args:
        emails:        list of recipient email addresses from captured records
        template_name: name of the template to use (use list_email_templates first)
        from_email:    the connected sender email address (must be connected via
                       POST /email/connect before calling this)
    """
    from templates import get_template, build_context, render_template
    from email_client import send_smtp, get_smtp_account
    import httpx

    # Verify template exists
    template = get_template(template_name)
    if not template:
        return (f"✗ Template '{template_name}' not found. "
                f"Use list_email_templates to see available options.")

    # Verify sender is connected
    account = get_smtp_account(from_email)
    if not account:
        return (f"✗ No email account connected for {from_email}. "
                f"Connect it first via POST /email/connect.")

    # Load creator profile for template variables
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("http://localhost:8000/creator/profile")
        creator_profile = r.json() if r.status_code == 200 else {}
    except Exception:
        creator_profile = {}

    sent, failed = 0, []

    for email in emails:
        contact = {"email": email}
        context  = build_context(contact, creator_profile)
        rendered = render_template(template, context)

        result = await send_smtp(
            account_email = from_email,
            to_email      = email,
            subject       = rendered["subject_rendered"],
            body          = rendered["body_rendered"],
        )
        if result["ok"]:
            sent += 1
        else:
            failed.append(f"{email} ({result.get('error', 'unknown')})")

    lines = [f"✓ Sent to {sent}/{len(emails)} recipients using template '{template_name}'."]
    if failed:
        lines.append(f"✗ Failed: {', '.join(failed)}")
    return "\n".join(lines)


# ── knowledge bridge tools ────────────────────────────────────────────────────

@tool
def get_knowledge_gaps() -> str:
    """
    Find topics your audience is actively asking about that have no answer
    in your knowledge base yet.

    Returns each gap with the EXACT questions viewers sent — pulled directly
    from the audience signals database. Nothing is generated or suggested.
    Use this to discover what information to add next.
    """
    from idea_tools import load_topic_analytics, _signals
    from graph import load_knowledge_entries

    # Topics the audience has asked questions about
    all_topics = load_topic_analytics(40)
    has_interest = [t for t in all_topics
                    if t.get("question_count", 0) > 0
                    or t.get("request_count", 0) > 0]

    if not has_interest:
        return (
            "No audience signals have been analysed yet.\n"
            "Run analyze_audience() in the idea generator first, "
            "or send viewer messages to the Telegram bot to start building signals."
        )

    # Topics already covered in the knowledge base
    entries     = load_knowledge_entries()
    known       = {e["topic"].lower() for e in entries}

    gaps = []
    for t in has_interest:
        name = t["topic"].lower()
        # Consider a topic covered if any knowledge entry shares a word with it
        covered = any(
            name in kt or kt in name or
            bool(set(name.split()) & set(kt.split()))
            for kt in known
        )
        if covered:
            continue

        # Pull the ACTUAL viewer messages about this topic from audience_signals
        if settings.database_url:
            from database import load_signals_by_topic
            viewer_msgs = load_signals_by_topic(name, ["question", "request"], 5)
        else:
            viewer_msgs = [
                s["content"] for s in _signals
                if s.get("topic") == name
                and s.get("signal_type") in ("question", "request")
            ][:5]

        gaps.append({
            "topic":    t["topic"],
            "count":    t.get("question_count", 0) + t.get("request_count", 0),
            "messages": viewer_msgs,
        })

    if not gaps:
        return (
            "Your knowledge base already covers all active audience topics.\n"
            "Check back after more viewer messages have been collected."
        )

    lines = [
        f"{len(gaps)} topic(s) your audience keeps asking about "
        f"with no answer in your knowledge base:\n"
    ]
    for i, g in enumerate(gaps[:8], 1):
        lines.append(f"{i}. {g['topic'].upper()}  "
                     f"({g['count']} viewer message(s))")
        if g["messages"]:
            lines.append("   What viewers actually said:")
            for msg in g["messages"]:
                lines.append(f'   — "{msg}"')
        else:
            lines.append("   (messages not yet loaded — run analyze_audience() first)")
        lines.append("")

    return "\n".join(lines)


@tool
def save_to_knowledge_base(topic: str, answer: str) -> str:
    """
    Save the creator's own answer to the knowledge base.

    This must ONLY be called with the creator's exact words.
    Never call this with LLM-drafted content — the knowledge base
    must contain what the creator actually said, not a generated answer.

    Args:
        topic:  short label for this piece of knowledge, e.g. 'filming setup'
        answer: the creator's own answer, exactly as they said it
    """
    from graph import save_knowledge_entry
    save_knowledge_entry(topic.lower().strip(), answer, source="gap_fill")
    return f"✓ Saved to knowledge base: '{topic}'"


@tool
def start_capture(fields: list[str], target: int) -> str:
    """Begin capturing viewer records from the creator's TikTok LIVE chat.
    fields: which fields to collect, from tiktok_username, telegram, age, location.
    target: how many records to collect. Only call this once you know BOTH the
    fields and the target count — otherwise call ask_creator first."""
    return ""   # intercepted by capture_node


@tool
def ask_creator(question: str) -> str:
    """Ask the creator a question and wait for their answer. Use this when you do
    not yet know which fields to capture or how many records they want."""
    return ""   # intercepted by ask_node


# ── onboarding tools ──────────────────────────────────────────────────────────

@tool
def check_onboarding_status() -> str:
    """
    Check what is missing from the creator's setup.
    Call this at the start of a new conversation to decide whether to run
    onboarding before handling the creator's request.

    Returns the status of:
      - creator profile (name, bio, cta)
      - knowledge base (number of entries)
    """
    import httpx, asyncio

    # Creator profile
    profile_set   = False
    profile_name  = ""
    try:
        r = httpx.get("http://localhost:8000/creator/profile", timeout=3)
        p = r.json()
        if p.get("name"):
            profile_set  = True
            profile_name = p["name"]
    except Exception:
        pass

    # Knowledge base
    kb_count = 0
    try:
        r = httpx.get("http://localhost:8000/knowledge", timeout=3)
        kb_count = len(r.json().get("entries", []))
    except Exception:
        pass

    lines = ["Onboarding status:"]
    if profile_set:
        lines.append(f"  ✓  Creator profile set — name: {profile_name}")
    else:
        lines.append("  ○  Creator profile not set (name, bio, call to action)")

    if kb_count > 0:
        lines.append(f"  ✓  Knowledge base has {kb_count} entries")
    else:
        lines.append("  ○  Knowledge base is empty")

    if not profile_set or kb_count == 0:
        lines.append("\nOnboarding is incomplete. Collect missing information "
                     "conversationally before handling the creator's request.")
    else:
        lines.append("\nSetup complete. Proceed with the creator's request.")

    return "\n".join(lines)


@tool
async def save_creator_profile(name: str, bio: str, cta: str,
                                email: str = "") -> str:
    """
    Save the creator's public profile.
    This is used to personalise email templates and Telegram messages —
    {{creator_name}}, {{creator_bio}}, and {{creator_cta}} are filled from here.

    Collect these conversationally — one or two questions at a time, not a form.

    Args:
        name:  what the creator wants to be called, e.g. 'Victor'
        bio:   one sentence about what they creators,
               e.g. 'I help people pay off debt on any income'
        cta:   a call to action for messages,
               e.g. 'Follow me on TikTok @victor for daily tips'
        email: their connected sender email (optional — skip if not known)
    """
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(
                "http://localhost:8000/creator/profile",
                json={"name": name, "bio": bio, "cta": cta,
                      "email": email or None},
            )
        if r.status_code == 200:
            return (f"✓ Profile saved.\n"
                    f"  Name: {name}\n"
                    f"  Bio:  {bio}\n"
                    f"  CTA:  {cta}")
        return f"✗ Failed to save profile: {r.text}"
    except Exception as e:
        return f"✗ Error saving profile: {e}"


SYSTEM_PROMPT = (
    "You are the assistant for a TikTok LIVE creator, inside their desktop application.\n\n"

    "── Onboarding ─────────────────────────────────────────────────────────────\n"
    "On the FIRST message of any new conversation, call check_onboarding_status()\n"
    "to see what is missing. If anything is incomplete, collect it before handling\n"
    "the creator's original request.\n\n"
    "Profile (name, bio, cta) — if not set:\n"
    "  Ask conversationally, two fields at a time. Example first question:\n"
    "  'Before we start — what should I call you, and what do you creators?'\n"
    "  Then: 'What call to action should I put in messages to your viewers?'\n"
    "  Once you have all three, call save_creator_profile(name, bio, cta).\n\n"
    "Knowledge base — if empty:\n"
    "  Say: 'Your viewer bot has nothing to work with yet. What are the top\n"
    "  questions your audience always asks you? Tell me 5-10 and I will save\n"
    "  each one as an answer your bot can use.'\n"
    "  For each question-answer pair the creator gives, call\n"
    "  save_to_knowledge_base(topic, answer) with their exact words.\n"
    "  Do NOT suggest answers. Only save what the creator actually says.\n"
    "After onboarding is complete, proceed with what the creator originally asked.\n\n"

    "── Capturing records ──────────────────────────────────────────────────────\n"
    "You need TWO things before capturing:\n"
    f"  1. fields — which of these to collect: {', '.join(KNOWN_FIELDS)}\n"
    "  2. target — how many records to capture (a number)\n\n"
    "Rules:\n"
    "- If the creator gave both, call start_capture(fields, target) immediately.\n"
    "  Do NOT ask for confirmation when both are present in the message.\n"
    "- Only call ask_creator when something is genuinely missing or ambiguous.\n"
    "- Map common phrases directly:\n"
    "    'email addresses' or 'emails'      → fields=['email']\n"
    "    'telegram numbers' or 'telegrams'  → fields=['telegram']\n"
    "    'usernames'                        → fields=['tiktok_username']\n"
    "    'all fields'                       → fields=['tiktok_username','telegram','email']\n"
    "  Numbers like '5', 'five', 'first 5' → target=5\n"
    "- If the creator says 'capture 5 emails', that is fields=['email'], target=5. Call\n"
    "  start_capture immediately — no clarification needed.\n\n"

    "── Filling knowledge gaps ──────────────────────────────────────────────────\n"
    "Tools: get_knowledge_gaps(), save_to_knowledge_base(topic, answer)\n\n"
    "When the creator asks what to add to their knowledge base, what their\n"
    "audience is asking, or wants to fill gaps:\n"
    "  1. Call get_knowledge_gaps(). It returns topics with REAL viewer questions.\n"
    "  2. For each gap, use ask_creator to show the actual viewer questions and\n"
    "     ask the creator for THEIR OWN answer in their own words.\n"
    "     Example: 'Viewers are asking about your filming setup:\n"
    '     - "what phone do you use"\n'
    '     - "do you need a ring light"\n'
    "     What would you like your bot to tell them?'\n"
    "  3. Call save_to_knowledge_base(topic, answer) with EXACTLY what they said.\n"
    "  4. Move to the next gap or ask if they want to continue.\n\n"
    "CRITICAL: NEVER draft or suggest an answer yourself. The knowledge base\n"
    "must contain the creator's own words — not generated content. If the\n"
    "creator says 'you decide' or 'make something up', explain that their bot\n"
    "should only share information they have verified is accurate, and ask them\n"
    "to provide the real answer even if it is brief.\n\n"
    "Tools: connect_email_account(email, password, display_name),\n"
    "       list_connected_senders(), list_email_templates(),\n"
    "       create_email_template(name, subject, body),\n"
    "       send_emails_from_template(emails, template_name, from_email)\n\n"
    "If the creator asks to connect their email, call connect_email_account.\n"
    "Ask for their email address and application password if not provided. Remind them\n"
    "that this is an application password (not their real password) generated from their\n"
    "account security settings.\n\n"
    "Flow when the creator asks to send emails:\n"
    "  1. Call list_connected_senders() FIRST. If none are connected, use\n"
    "     ask_creator to request their email and application password, then call\n"
    "     connect_email_account before proceeding.\n"
    "  2. Call list_email_templates() to see what is available.\n"
    "  3. Use ask_creator to confirm the template. If only one sender is\n"
    "     connected, use it automatically without asking.\n"
    "     If they say 'default', use 'default_intro'.\n"
    "  4. Call send_emails_from_template.\n"
    "  5. Report the delivery summary.\n"
    "NEVER guess or invent an email address as the sender.\n\n"
    "Tools available: send_message_to_user(username, text)\n"
    "                 broadcast_to_usernames(usernames, text)\n\n"
    "CRITICAL CONSTRAINT: Telegram only allows the bot to contact users who have\n"
    "already started it by tapping the /start link. A username captured from the\n"
    "TikTok chat does NOT mean that person is reachable — they must have\n"
    "separately opened the bot on Telegram first.\n\n"
    "Before calling any send or broadcast tool you MUST use ask_creator to:\n"
    "  1. Tell the creator to share the bot /start link in the stream.\n"
    "  2. Ask them to confirm once viewers have had time to tap it.\n"
    "Only after the creator confirms, call broadcast_to_usernames with the\n"
    "captured telegram usernames and the message text.\n\n"
    "After broadcasting, report the full delivery summary: how many were\n"
    "delivered, which usernames are not yet registered, and suggest resharing\n"
    "the link for anyone who missed it."
)

model = ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key,
                   temperature=0.1)
# parallel_tool_calls=False prevents gpt-4o-mini from returning multiple tool
# calls in one AIMessage. If it called both ask_creator and start_capture (or
# two ask_creators) at once, the router handles only one; the other's
# tool_call_id would have no ToolMessage response, causing a 400 on the next
# agent invocation.
model_with_tools = model.bind_tools(
    [start_capture, ask_creator,
     check_onboarding_status, save_creator_profile,
     get_knowledge_gaps, save_to_knowledge_base,
     send_message_to_user, broadcast_to_usernames,
     connect_email_account, list_connected_senders,
     list_email_templates, create_email_template, send_emails_from_template],
    parallel_tool_calls=False
)


class State(MessagesState):
    fields: list
    target: int
    records: list
    slices_done: int
    capture_tool_id: str   # declared so LangGraph persists it; was _tool_id (dropped)


def agent_node(state: State) -> dict:
    messages = [SystemMessage(SYSTEM_PROMPT)] + state["messages"]
    return {"messages": [model_with_tools.invoke(messages)]}


def capture_node(state: State) -> dict:
    """Drive the capture loop. Initialises from the start_capture tool call the
    FIRST time it sees a new call, then accumulates records in state across
    re-entries until `target` is reached."""
    last = state["messages"][-1]

    # Is there a start_capture tool call on the latest message?
    new_call = None
    if getattr(last, "tool_calls", None):
        new_call = next((c for c in last.tool_calls if c["name"] == "start_capture"), None)

    # A NEW capture = a tool call whose id we haven't started yet. Otherwise we're
    # mid-loop and must read the running totals from state (never reset them).
    if new_call and new_call["id"] != state.get("capture_tool_id"):
        args = new_call.get("args", {})
        fields = [f for f in args.get("fields", []) if f in KNOWN_FIELDS] or ["tiktok_username"]
        target = int(args.get("target", 0) or 0)
        tool_id = new_call["id"]
        records, done = [], 0
    else:
        fields  = state.get("fields", ["tiktok_username"])
        target  = state.get("target", 0)
        tool_id = state.get("capture_tool_id")
        records = list(state.get("records", []))
        done    = state.get("slices_done", 0)

    # Stop conditions checked in CODE (authoritative).
    if len(records) >= target or done >= MAX_SLICES:
        return _finish(records, fields, target, done, tool_id, state,
                       stopped="target reached" if len(records) >= target
                               else "safety limit")

    # Request ONE more slice from the client.
    result = interrupt({
        "action": "record_screen",
        "mode": "records",
        "fields": fields,
        "target": target,
        "have": len(records),
        "slice": done,
        "tool_call_id": tool_id,
    })
    new = (result or {}).get("records", [])
    found = (result or {}).get("found", True)
    records.extend(new)

    if not found:
        return _finish(records, fields, target, done + 1, tool_id, state,
                       stopped="no chat on screen")

    # Persist progress and loop again (route_after_capture re-enters this node).
    return {"fields": fields, "target": target, "records": records,
            "slices_done": done + 1, "capture_tool_id": tool_id}


def _finish(records, fields, target, done, tool_id, state, stopped="target reached"):
    payload = json.dumps({
        "records": records[:target],
        "collected": len(records[:target]),
        "target": target,
        "fields": fields,
        "stopped": stopped,
    })[:8000]
    tid = tool_id or state.get("capture_tool_id")
    return {"fields": fields, "target": target, "records": records,
            "slices_done": done,
            "messages": [ToolMessage(content=payload, tool_call_id=tid)]}


def ask_node(state: State) -> dict:
    last = state["messages"][-1]
    call = next(c for c in last.tool_calls if c["name"] == "ask_creator")
    answer = interrupt({"action": "ask_user",
                        "question": call.get("args", {}).get("question", ""),
                        "tool_call_id": call["id"]})
    if isinstance(answer, dict):
        answer = answer.get("answer", "")
    return {"messages": [ToolMessage(content=str(answer), tool_call_id=call["id"])]}


_ONBOARDING_TOOLS = {"check_onboarding_status", "save_creator_profile"}
_TELEGRAM_TOOLS   = {"send_message_to_user", "broadcast_to_usernames"}
_EMAIL_TOOLS    = {"connect_email_account", "list_connected_senders",
                   "list_email_templates", "create_email_template",
                   "send_emails_from_template"}
_KNOWLEDGE_TOOLS = {"get_knowledge_gaps", "save_to_knowledge_base"}
_DIRECT_TOOLS    = _ONBOARDING_TOOLS | _TELEGRAM_TOOLS | _EMAIL_TOOLS | _KNOWLEDGE_TOOLS


def route_after_agent(state: State) -> str:
    calls = getattr(state["messages"][-1], "tool_calls", None) or []
    if any(c["name"] == "start_capture" for c in calls):
        return "capture"
    if any(c["name"] == "ask_creator" for c in calls):
        return "ask"
    if any(c["name"] in _DIRECT_TOOLS for c in calls):
        return "telegram"   # ToolNode handles all direct-execute tools
    return END


def route_after_capture(state: State) -> str:
    """If the last message is a ToolMessage, capture finished -> back to agent to
    summarise. Otherwise we just stored a slice -> loop for the next slice."""
    last = state["messages"][-1]
    return "agent" if isinstance(last, ToolMessage) else "capture"


def build_assistant_graph(checkpointer):
    b = StateGraph(State)
    b.add_node("agent",    agent_node)
    b.add_node("capture",  capture_node)
    b.add_node("ask",      ask_node)
    b.add_node("telegram", ToolNode([
        check_onboarding_status, save_creator_profile,
        get_knowledge_gaps, save_to_knowledge_base,
        send_message_to_user, broadcast_to_usernames,
        connect_email_account, list_connected_senders,
        list_email_templates, create_email_template, send_emails_from_template,
    ]))
    b.add_edge(START, "agent")
    b.add_conditional_edges("agent", route_after_agent,
                             ["capture", "ask", "telegram", END])
    b.add_conditional_edges("capture", route_after_capture, ["capture", "agent"])
    b.add_edge("ask",      "agent")
    b.add_edge("telegram", "agent")   # LLM sees delivery result and reports it
    return b.compile(checkpointer=checkpointer)
