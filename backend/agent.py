"""
🧴 Expert Dermatologist Query Resolver — Streamlit App
Run: streamlit run derm_agent.py
Requires:
  pip install streamlit langgraph langchain-groq langchain-community \
              tavily-python pydantic python-dotenv
"""

import json as _json
import operator
import os
import re as _re
import time
from datetime import date
from typing import Annotated, Any, List, Literal, Optional, TypedDict

import streamlit as st
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# RATE-LIMIT-SAFE LLM WRAPPER
# ─────────────────────────────────────────────────────────────────────────────

def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc)
    return "429" in msg or "rate_limit_exceeded" in msg or "Rate limit" in msg


def llm_invoke_with_retry(llm, messages, max_attempts: int = 6):
    delay = 5.0
    for attempt in range(max_attempts):
        try:
            return llm.invoke(messages)
        except Exception as exc:
            if _is_rate_limit(exc) and attempt < max_attempts - 1:
                time.sleep(delay)
                delay = min(delay * 2, 60)
            else:
                raise


def structured_invoke_with_retry(chain, messages, max_attempts: int = 6):
    delay = 5.0
    for attempt in range(max_attempts):
        try:
            return chain.invoke(messages)
        except Exception as exc:
            if _is_rate_limit(exc) and attempt < max_attempts - 1:
                time.sleep(delay)
                delay = min(delay * 2, 60)
            else:
                raise


# ─────────────────────────────────────────────────────────────────────────────
# 1. SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────

class EvidenceItem(BaseModel):
    title: str
    url: str
    published_at: Optional[str] = None
    snippet: Optional[str] = None
    source_type: Optional[str] = None   # "study" | "expert_blog" | "dermatology_article"


class RouterDecision(BaseModel):
    queries: List[str] = Field(..., description="4-8 targeted search queries for dermatology sources")
    skin_type_focus: Optional[str] = None
    concern_category: Literal[
        "ingredient_safety", "product_comparison", "routine_advice",
        "skin_condition", "makeup_compatibility", "general"
    ] = "general"


class AnswerSection(BaseModel):
    id: int
    heading: str
    content_points: List[str] = Field(..., min_length=2, max_length=6)

    @field_validator("content_points", mode="before")
    @classmethod
    def ensure_min_points(cls, v):
        if isinstance(v, list) and len(v) < 2:
            while len(v) < 2:
                v.append("Consult a dermatologist for personalised advice.")
        return v


class AnswerPlan(BaseModel):
    verdict: str = Field(..., description="3-5 sentence direct answer to the question.")
    confidence: Literal["high", "medium", "low"] = "medium"
    caution_note: Optional[str] = None
    sections: List[AnswerSection]


# ── State ─────────────────────────────────────────────────────────────────────

class State(TypedDict):
    llm: Any
    question: str
    concern_category: str
    queries: List[str]
    evidence: List[EvidenceItem]
    plan: Optional[AnswerPlan]
    sections: Annotated[List[tuple], operator.add]
    final: str


# ─────────────────────────────────────────────────────────────────────────────
# 2. ROUTER  —  generates dermatology-specific search queries
# ─────────────────────────────────────────────────────────────────────────────

ROUTER_SYSTEM = """You are a dermatology research planner.

Given a skincare or makeup question, generate 4-8 focused search queries that will
surface high-quality evidence from:
- PubMed / clinical studies ("site:ncbi.nlm.nih.gov" style intent)
- Dermatologist-authored blogs (dermnetnz.org, American Academy of Dermatology, etc.)
- Peer-reviewed cosmetic dermatology articles or research pages (journals, research institutes, etc.)

Also classify the concern_category and note any skin_type_focus from the question.
"""


def router_node(state: State) -> dict:
    llm: ChatGroq = state["llm"]
    decider = llm.with_structured_output(RouterDecision)
    decision = structured_invoke_with_retry(decider, [
        SystemMessage(content=ROUTER_SYSTEM),
        HumanMessage(content=f"Question: {state['question']}"),
    ])
    return {
        "queries": decision.queries,
        "concern_category": decision.concern_category,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. RESEARCH  —  Tavily-powered evidence gathering
# ─────────────────────────────────────────────────────────────────────────────

def _tavily_search(query: str, max_results: int = 5) -> List[dict]:

  tool = TavilySearchResults(max_results = max_results)
  results = tool.invoke({"query": query})

  normalized: List[dict] = []
  for r in results or []:
    normalized.append(
        {
        "title": r.get("title", "") or "",
        "url": r.get("url", "") or "",
        "snippet": r.get("content") or r.get("snippet", "") or "",
        "published_at": r.get("published_date") or r.get("published_at"),
        "source": r.get("source"),
        }
    )
    return normalized


RESEARCH_SYSTEM = """You are a dermatology evidence synthesizer.

Given numbered web results, respond with ONLY a JSON array — no markdown fences,
no explanation, nothing else before or after the array.

Each element must have exactly these keys:
  "title"        : string (keep short)
  "url"          : string (non-empty)
  "snippet"      : string (max 120 chars, preserve key dermatological claims)
  "published_at" : string YYYY-MM-DD or null
  "source_type"  : one of "study" | "expert_blog" | "dermatology_article" | "other"

Prioritise:
1. Clinical studies / PubMed links  → source_type="study"
2. Dermatologist-authored content   → source_type="expert_blog"
3. Medical dermatology sites        → source_type="dermatology_article"

Rules:
- Omit any item whose url is empty.
- Deduplicate by url (keep first occurrence).
- Return at most 10 items.
"""


class EvidencePack(BaseModel):
    evidence: List[EvidenceItem]

def research_node(state: State) -> dict:
    llm: ChatGroq = state["llm"]
    queries = (state.get("queries", []) or [])[:10]

    raw_results: List[dict] = []
    for q in queries:
        raw_results.extend(_tavily_search(q, max_results=6))

    if not raw_results:
        return {"evidence": []}

    # Format cleanly so the LLM doesn't get a raw dict blob
    formatted = "\n".join(
        f"{i+1}. {r['title'][:80]} | {r['url']} | {r['snippet'][:120]}"
        for i, r in enumerate(raw_results[:15])
        if r.get("url")
    )

    extractor = llm.with_structured_output(EvidenceItem)
    pack = structured_invoke_with_retry(extractor, [
        SystemMessage(content=RESEARCH_SYSTEM),
        HumanMessage(content=f"Results:\n{formatted}"),
    ])

    dedup = {}
    for e in pack.evidence:
        if e.url and e.url not in dedup:
            dedup[e.url] = e

    return {"evidence": list(dedup.values())}


# ─────────────────────────────────────────────────────────────────────────────
# 4. ORCHESTRATOR  —  builds a structured answer plan
# ─────────────────────────────────────────────────────────────────────────────

ORCH_SYSTEM = """You are a board-certified dermatologist and cosmetic chemist.

Given a skincare / makeup question and research evidence, create a structured
answer plan with these rules:

- verdict: direct 3-5 sentence answer (yes/no/it-depends + key reason).
- confidence: "high" if multiple studies agree, "medium" if expert consensus,
  "low" if conflicting evidence.
- caution_note: include ONLY if there is a genuine safety concern or important caveat.
- sections: 3-5 sections covering relevant aspects such as:
    • How the ingredient/product works mechanistically
    • Evidence summary (what studies say)
    • Skin type / condition-specific guidance
    • How to use / best practices
    • What to avoid / interactions / contraindications
  Each section needs 2-5 concrete, evidence-grounded bullet points.

IMPORTANT:
- Never give a diagnosis or replace professional medical advice.
- Ground every claim in the provided evidence where possible.
- Be concise — users want clarity, not a textbook.
"""


def orchestrator_node(state: State) -> dict:
    llm: ChatGroq = state["llm"]
    planner = llm.with_structured_output(AnswerPlan)
    evidence = state.get("evidence", [])

    evidence_context = "\n".join(
        f"- [{e.source_type}] {e.title} | {e.snippet} | {e.url}"
        for e in evidence[:8]
    )

    plan = structured_invoke_with_retry(planner, [
        SystemMessage(content=ORCH_SYSTEM),
        HumanMessage(content=(
            f"Question: {state['question']}\n"
            f"Concern category: {state.get('concern_category', 'general')}\n\n"
            f"Evidence:\n{evidence_context}"
        )),
    ])
    return {"plan": plan}


# ─────────────────────────────────────────────────────────────────────────────
# 5. FANOUT + WORKER  —  parallel section writing
# ─────────────────────────────────────────────────────────────────────────────

def fanout(state: State):
    return [
        Send("worker", {
            "llm":      state["llm"],
            "section":  sec.model_dump(),
            "question": state["question"],
            "plan":     state["plan"].model_dump(),
            "evidence": [e.model_dump() for e in state.get("evidence", [])],
        })
        for sec in state["plan"].sections
    ]


def worker_node(payload: dict) -> dict:
    llm: ChatGroq = payload["llm"]
    section  = AnswerSection(**payload["section"])
    question = payload["question"]
    plan     = AnswerPlan(**payload["plan"])
    evidence = [EvidenceItem(**e) for e in payload.get("evidence", [])]

    evidence_text = "\n".join(
        f"- {e.title} ({e.source_type}) | {e.snippet} | {e.url}"
        for e in evidence[:6]
    )

    points_text = "\n".join(f"• {p}" for p in section.content_points)

    time.sleep(1)

    section_md = llm_invoke_with_retry(llm, [
        SystemMessage(content=(
            "You are a dermatologist writing a clear, evidence-based skincare answer. "
            "Write one Markdown section. Be concise, friendly, and scientific. "
            "Cite sources inline as [Source Name](url) where relevant. "
            "Never diagnose. Never invent URLs."
        )),
        HumanMessage(content=(
            f"Original question: {question}\n"
            f"Overall verdict: {plan.verdict}\n\n"
            f"Section heading: {section.heading}\n"
            f"Key points to cover:\n{points_text}\n\n"
            f"Evidence available (use ONLY these URLs):\n{evidence_text}\n\n"
            "Return ONLY the section content in Markdown. "
            "Use the heading as a ## header. Keep it under 200 words."
        )),
    ]).content.strip()

    return {"sections": [(section.id, section_md)]}


# ─────────────────────────────────────────────────────────────────────────────
# 6. REDUCER  —  assembles the final answer
# ─────────────────────────────────────────────────────────────────────────────

def reducer_node(state: State) -> dict:
    plan = state["plan"]

    # Build verdict block
    confidence_emoji = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(plan.confidence, "🟡")
    verdict_block = (
        f"> {confidence_emoji} **{plan.verdict}**\n"
        f"> Confidence: **{plan.confidence.upper()}**"
    )
    if plan.caution_note:
        verdict_block += f"\n>\n> ⚠️ *{plan.caution_note}*"

    # Ordered sections
    ordered = [md for _, md in sorted(state["sections"], key=lambda x: x[0])]
    body = "\n\n".join(ordered).strip()

    # Sources section
    evidence = state.get("evidence", [])
    if evidence:
        sources_md = "\n---\n### 📚 Sources\n"
        for e in evidence[:8]:
            badge = {"study": "🔬", "expert_blog": "👩‍⚕️", "dermatology_article": "📄"}.get(
                e.source_type, "🔗"
            )
            date_str = f" *(published: {e.published_at})*" if e.published_at else ""
            sources_md += f"- {badge} [{e.title}]({e.url}){date_str}\n"
    else:
        sources_md = ""

    disclaimer = (
        "\n---\n*⚕️ This information is for educational purposes only and does not "
        "constitute medical advice. Please consult a licensed dermatologist for "
        "personalised recommendations.*"
    )

    final = f"{verdict_block}\n\n{body}\n{sources_md}{disclaimer}\n"
    return {"final": final}


# ─────────────────────────────────────────────────────────────────────────────
# 7. BUILD GRAPH
# ─────────────────────────────────────────────────────────────────────────────

def build_app():
    g = StateGraph(State)
    g.add_node("router",       router_node)
    g.add_node("research",     research_node)
    g.add_node("orchestrator", orchestrator_node)
    g.add_node("worker",       worker_node)
    g.add_node("reducer",      reducer_node)

    g.add_edge(START,        "router")
    g.add_edge("router",     "research")
    g.add_edge("research",   "orchestrator")
    g.add_conditional_edges("orchestrator", fanout, ["worker"])
    g.add_edge("worker",     "reducer")
    g.add_edge("reducer",    END)

    return g.compile()


# ─────────────────────────────────────────────────────────────────────────────
# 8. STREAMLIT UI
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="DermAI — Skincare Expert",
    page_icon="🧴",
    layout="wide",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}
h1, h2, h3 {
    font-family: 'DM Serif Display', serif;
}
.verdict-box {
    background: linear-gradient(135deg, #fdf6f0 0%, #fce8d8 100%);
    border-left: 4px solid #e07b54;
    border-radius: 8px;
    padding: 1rem 1.5rem;
    margin: 1rem 0;
}
.source-badge {
    display: inline-block;
    background: #f0f4ff;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 0.8rem;
    color: #3a5cb8;
    margin-right: 4px;
}
</style>
""", unsafe_allow_html=True)

st.title("🧴 DermAI — Expert Skincare Advisor")
st.caption("Evidence-based answers powered by LangGraph · Groq · Tavily dermatology research")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("🔑 API Keys")
    st.markdown("Keys live only in this browser session — never stored.")

    groq_key   = st.text_input("Groq API Key *",   type="password", placeholder="gsk_...",  help="console.groq.com")
    tavily_key = st.text_input("Tavily API Key *",  type="password", placeholder="tvly-...", help="tavily.com")

    keys_ready = bool(groq_key.strip() and tavily_key.strip())
    if keys_ready:
        st.success("✅ Ready to answer!")
    else:
        st.warning("Enter both API keys to continue.")

    st.divider()
    st.markdown("**What can I ask?**")
    st.markdown("""
- *"Is niacinamide safe for rosacea?"*
- *"Can I layer retinol with vitamin C?"*
- *"Best SPF for oily acne-prone skin?"*
- *"Does hyaluronic acid cause breakouts?"*
- *"Is tretinoin safe during pregnancy?"*
""")
    st.divider()
    st.caption("Model: `llama-3.3-70b-versatile` (Groq)")
    st.info(
        "**Free tier limit:** 12 000 tokens/min.\n\n"
        "Auto-retries 429 errors with backoff.",
        icon="⚠️",
    )

# ── Question input ────────────────────────────────────────────────────────────
st.subheader("💬 Ask Your Skincare Question")

question = st.text_input(
    "Question",
    placeholder="e.g. Is niacinamide good for sensitive skin?",
    disabled=not keys_ready,
    label_visibility="collapsed",
)

ask_btn = st.button(
    "🔍 Get Expert Answer",
    disabled=not (keys_ready and bool(question.strip())),
    use_container_width=True,
    type="primary",
)

# ── Run agent ─────────────────────────────────────────────────────────────────
if ask_btn and keys_ready and question.strip():

    os.environ["GROQ_API_KEY"]   = groq_key
    os.environ["TAVILY_API_KEY"] = tavily_key

    llm_instance = ChatGroq(model="llama-3.3-70b-versatile", api_key=groq_key)

    initial_state: State = {
        "llm":              llm_instance,
        "question":         question.strip(),
        "concern_category": "general",
        "queries":          [],
        "evidence":         [],
        "plan":             None,
        "sections":         [],
        "final":            "",
    }

    ICONS = {
        "router":       "🔀 Planning search queries...",
        "research":     "🔍 Searching dermatology sources...",
        "orchestrator": "📋 Structuring answer...",
        "worker":       "✏️ Writing sections...",
        "reducer":      "🔗 Assembling final answer...",
    }

    with st.status("🤖 Consulting dermatology literature...", expanded=True) as status:
        try:
            app = build_app()
            out = None

            for state_snapshot in app.stream(initial_state, stream_mode="values"):
                changed = [
                    k for k in state_snapshot
                    if k not in ("llm",)
                    and state_snapshot.get(k) != initial_state.get(k)
                ]

                node_name = "worker"
                if "queries" in changed and not state_snapshot.get("evidence"):
                    node_name = "router"
                elif "evidence" in changed:
                    node_name = "research"
                elif "plan" in changed:
                    node_name = "orchestrator"
                elif "final" in changed:
                    node_name = "reducer"

                st.write(ICONS.get(node_name, "⚙️ Processing..."))
                out = state_snapshot

            st.session_state["derm_result"] = out
            status.update(label="✅ Answer ready!", state="complete")

        except Exception as exc:
            status.update(label="❌ Failed", state="error")
            st.error(f"**Error:** {exc}")
            st.stop()

# ── Display result ────────────────────────────────────────────────────────────
if "derm_result" in st.session_state:
    out      = st.session_state["derm_result"]
    final_md = out.get("final", "")
    plan     = out.get("plan")
    evidence = out.get("evidence", [])

    st.divider()

    # Metrics row
    if plan and evidence:
        c1, c2, c3, c4 = st.columns(4)
        confidence_label = {"high": "🟢 High", "medium": "🟡 Medium", "low": "🔴 Low"}.get(
            plan.confidence, plan.confidence
        )
        c1.metric("Confidence",   confidence_label)
        c2.metric("Sources Found", len(evidence))
        studies   = sum(1 for e in evidence if e.source_type == "study")
        expert    = sum(1 for e in evidence if e.source_type == "expert_blog")
        c3.metric("Studies",      studies)
        c4.metric("Expert Blogs", expert)

    # Tabs
    tab_answer, tab_sources, tab_raw = st.tabs(["💡 Answer", "📚 Sources", "📄 Raw Markdown"])

    with tab_answer:
        st.markdown(final_md, unsafe_allow_html=False)

    with tab_sources:
        if evidence:
            for e in evidence:
                badge_map = {
                    "study":               ("🔬", "Clinical Study"),
                    "expert_blog":         ("👩‍⚕️", "Expert Blog"),
                    "dermatology_article": ("📄", "Derm Article"),
                    "other":               ("🔗", "Source"),
                }
                icon, label = badge_map.get(e.source_type, ("🔗", "Source"))
                with st.expander(f"{icon} {e.title[:80]}"):
                    st.markdown(f"**Type:** {label}")
                    if e.published_at:
                        st.markdown(f"**Published:** {e.published_at}")
                    if e.snippet:
                        st.markdown(f"**Excerpt:** _{e.snippet}_")
                    st.markdown(f"**URL:** [{e.url}]({e.url})")
        else:
            st.info("No sources found.")

    with tab_raw:
        st.code(final_md, language="markdown")