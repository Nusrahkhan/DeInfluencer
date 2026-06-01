"""
🧴 Expert Dermatologist Query Resolver
Fixes applied:
  1. research_node: replaced List[EvidenceItem] structured output with EvidencePack wrapper
  2. research_node: fixed 'dedup used before assignment' bug
  3. Profile keys: normalised to snake_case throughout (matches FastAPI input)
  4. Prompts: personalised to user profile for better chatbot experience
  5. Lip-tint / product queries: concern_category now covers product_recommendation
"""

import json as _json
import operator
import os
import time
from typing import Annotated, Any, List, Literal, Optional, TypedDict
from unittest import result

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

class LinkCard(BaseModel):
    title: str
    url: str
    favicon: Optional[str] = None


class ImageCard(BaseModel):
    title: str
    image_url: str
    click_url: Optional[str] = None


class TableData(BaseModel):
    columns: List[str]
    rows: List[List[str]]

class ProductCard(BaseModel):
    name: str
    brand: Optional[str] = None
    image_url: Optional[str] = None
    product_url: Optional[str] = None
    reason: Optional[str] = None


class UICard(BaseModel):
    type: Literal[
        "bullet_list",
        "product_grid",
        "comparison_table",
        "warning",
    ]

    title: str

    bullets: Optional[List[str]] = None

    products: Optional[List[ProductCard]] = None

    table: Optional[TableData] = None

    images: Optional[List[ImageCard]] = None

    links: Optional[List[LinkCard]] = None


class Hero(BaseModel):
    title: str
    subtitle: str
    confidence: Literal["high", "medium", "low"]


class UIPlan(BaseModel):

    hero: Hero

    cards: List[UICard]

    sources: List[LinkCard] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    title: str
    url: str

    image_url: Optional[str] = None
    snippet: Optional[str] = None

    source_type: Optional[str] = None
    published_at: Optional[str] = None


# FIX 1: Wrap List[EvidenceItem] in a proper Pydantic model so
# with_structured_output() gets a class, not a generic alias.
class EvidencePack(BaseModel):
    evidence: List[EvidenceItem] = Field(default_factory=list)


class RouterDecision(BaseModel):
    queries: List[str] = Field(..., description="3-5 targeted search queries")
    skin_type_focus: Optional[str] = None
    concern_category: Literal[
        "ingredient_safety", "product_comparison", "routine_advice",
        "skin_condition", "makeup_compatibility", "product_recommendation", "general"
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
    profile: dict
    concern_category: str
    queries: List[str]
    evidence: List[EvidenceItem]

    plan: Optional[UIPlan]

    final: dict


# ─────────────────────────────────────────────────────────────────────────────
# 2. ROUTER
# ─────────────────────────────────────────────────────────────────────────────

ROUTER_SYSTEM = """You are a dermatology & beauty research planner.

Given a skincare or makeup/beauty question plus a user profile, generate 4-8
focused search queries that surface high-quality evidence from:
- PubMed / clinical studies
- Dermatologist-authored blogs (dermnetnz.org, AAD, etc.)
- Beauty/skincare product review and recommendation sites

FOR PRODUCT RECOMMENDATIONS, include:
- Specific product names + user's skin type + skin concern
- Brand-specific official sites (never generic "product finder" sites)
- User's budget range + preferred brands explicitly

AVOID generating queries that lead to:
- Unverified lifestyle blogs
- AI-generated content farms
- Verified retailer sites (Sephora, Nykaa, official brand websites only)
- Drop-shipping aggregator sites
- Affiliate marketing content without expertise
- Social media posts without source verification


Also classify the concern_category. Use "product_recommendation" for
shopping/suggestion queries.
"""


def router_node(state: State) -> dict:
    llm: ChatGroq = state["llm"]
    decider = llm.with_structured_output(RouterDecision)
    profile = state["profile"]
    decision = structured_invoke_with_retry(decider, [
        SystemMessage(content=ROUTER_SYSTEM),
        HumanMessage(content=f"""
Question: {state['question']}

User Profile:
- Skin type: {profile.get('skin_type', 'unknown')}
- Concerns: {profile.get('concerns', 'none')}
- Budget: {profile.get('budget', 'any')}
- Preferred brands: {profile.get('preferred_brands', 'none')}
"""),
    ])
    return {
        "queries": decision.queries,
        "concern_category": decision.concern_category,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. RESEARCH
# ─────────────────────────────────────────────────────────────────────────────

def _tavily_search(query: str, max_results: int = 5) -> List[dict]:
    tool = TavilySearchResults(max_results=max_results)
    results = tool.invoke({"query": query})
    normalized = []
    for r in results or []:
        normalized.append({
            "title":        r.get("title", ""),
            "url":          r.get("url", ""),
            "snippet":      r.get("content") or r.get("snippet", ""),
            "published_at": r.get("published_date") or r.get("published_at"),
            "source":       r.get("source"),
        })
    return normalized


RESEARCH_SYSTEM = """You are a dermatology & beauty evidence synthesizer.

CRITICAL URL VALIDATION RULES (NON-NEGOTIABLE):
1. ONLY INCLUDE URLS EXPLICITLY PROVIDED IN THE NUMBERED RESULTS
2. NEVER INVENT, FABRICATE, GUESS, OR "HALLUCINATE" URLS
3. NEVER MODIFY OR "CORRECT" URLS—use exactly as provided
4. If a URL appears malformed, OMIT it entirely
5. Never suggest what a URL "should be"—only use what actually exists in results
6. DEDUPLICATE by exact URL match

Given numbered web results, return a JSON object with exactly one key "evidence"
whose value is an array. No markdown fences, no explanation.

For each result, extract EXACTLY:
  "title"        : string (exact title from result)
  "url"          : string (EXACT URL as provided—validate it's complete)
  "snippet"      : string (exact snippet from result, max 120 chars)
  "published_at" : string YYYY-MM-DD format (if available, else null)
  "source_type"  : string one of:
    - "clinical_study" (PubMed, journal articles)
    - "dermatology_expert" (AAD, dermatologist blogs with credentials)
    - "dermatology_association" (AAD.org, DermNetNZ.org, etc.)
    - "beauty_expert_review" (credentialed reviewers with expertise)
    - "other"

VALIDATION CHECKLIST:
□ URL is complete and non-empty
□ URL comes directly from provided results
□ No URL fabrication under any circumstance
□ Title matches the actual article/page
□ Snippet is accurate quote, not synthesized
Return maximum 10 validated items. Skip any with missing/invalid URLs.

"""


def research_node(state: State) -> dict:
    llm: ChatGroq = state["llm"]
    queries = (state.get("queries", []) or [])[:10]

    raw_results: List[dict] = []
    for q in queries:
        raw_results.extend(_tavily_search(q, max_results=6))

    if not raw_results:
        return {"evidence": []}

    formatted = "\n".join(
        f"{i+1}. {r['title'][:80]} | {r['url']} | {r['snippet'][:120]}"
        for i, r in enumerate(raw_results[:15])
        if r.get("url")
    )

    # FIX 1: use EvidencePack (a proper class) instead of List[EvidenceItem]
    extractor = llm.with_structured_output(EvidencePack)
    pack: EvidencePack = structured_invoke_with_retry(extractor, [
        SystemMessage(content=RESEARCH_SYSTEM),
        HumanMessage(content=f"Results:\n{formatted}"),
    ])

    evidence_items: List[EvidenceItem] = pack.evidence if isinstance(pack, EvidencePack) else []

    # FIX 2: define dedup BEFORE using it
    dedup: dict = {}
    for e in evidence_items:
        if e.url and e.url not in dedup:
            dedup[e.url] = e

    return {"evidence": list(dedup.values())}


# ─────────────────────────────────────────────────────────────────────────────
# 4. ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

ORCH_SYSTEM = """
You are a board-certified dermatologist and cosmetic chemist creating 
a React UI response.

CRITICAL: NEVER INVENT LINKS. NEVER CREATE FAKE URLS.

LINK GENERATION RULES (ABSOLUTE):
1. ONLY use URLs that appear in the Evidence section below
2. If a product/brand is mentioned, ONLY include links if they exist in Evidence
3. Never give a product_url from websites like (Sephora, Nykaa, official sites)
4. Give links of blogs/studies ONLY make your answer Evidence-based, never for "additional reading" or "further info"
4. For links in link cards: ONLY use URLs from Evidence
5. NEVER suggest what a URL "might be"—if it's not in Evidence, don't include it
6. Format citations exactly as: [Title](evidence_url)

EVIDENCE-BACKED CONTENT RULES:
- Every claim must be grounded in provided evidence
- If you cite a study, use its exact URL from Evidence
- If you recommend a product, ONLY include if:
  a) It appears in Evidence
  b) The link comes directly from the Evidence section

CARD STRUCTURE (REQUIRED):
Every card MUST have:
  1. "type" (exactly one of: bullet_list, product_grid, comparison_table, warning)
  2. "title" (string, concise, max 50 chars)

Card-specific rules:
- bullet_list: type, title, bullets (2-3 bullets, each <15 words, no links unless in Evidence)
- product_grid: type, title, products (max 6, ONLY include product_url if it's from Evidence)
- comparison_table: type, title, table (max 4 rows, max 3 columns)
- warning: type, title, content (bullet points highlighting risks/cautions)

HERO SECTION:
- title: 5-10 words, directly answers the question
- subtitle: 10-15 words, mentions key factors (skin type, ingredient, benefit)
- confidence: "high" (multiple peer-reviewed sources), "medium" (general consensus), 
  "low" (limited evidence or conflicting info)

SOURCES SECTION:
- ONLY include URLs from Evidence
- Include badge: 🔬 (study), 👨‍⚕️ (expert), 📄 (article)
- Maximum 4 sources
- Never include placeholder URLs or "visit [brand] site" without a real link

ANSWER PERSONALIZATION:
- Mention user's skin type, concerns, budget where relevant
- For product recommendations: "Best for [skin type + concern], fits [budget]"
- Ground every recommendation in Evidence
- Be honest about limitations: "Limited evidence suggests..." or "Expert consensus indicates..."

DO NOT:
- Invent product prices
- Create fake retailer domains
- Suggest variations of URLs you think exist
- Use placeholder links like "[click here](url)"
- Write as a blog—keep to cards optimized for React UI

USER PROFILE CONTEXT (personalize but verify):
- Skin type: {profile_skin_type}
- Concerns: {profile_concerns}
- Budget: {profile_budget}
- Preferred brands: {profile_brands}

Only recommend products matching their profile IF they appear in Evidence with real links.
"""


def orchestrator_node(state: State) -> dict:
    llm: ChatGroq = state["llm"]
    planner = llm.with_structured_output(UIPlan)
    evidence = state.get("evidence", [])
    profile  = state["profile"]

    evidence_context = "\n".join(
        f"- [{e.source_type}] {e.title} | {e.snippet} | {e.url}"
        for e in evidence[:8]
    )

    plan = structured_invoke_with_retry(planner, [
        SystemMessage(content=ORCH_SYSTEM),
        HumanMessage(content=(
            f"Question: {state['question']}\n\n"
            f"User Profile:\n"
            f"  Skin type: {profile.get('skin_type')}\n"
            f"  Concerns: {profile.get('concerns')}\n"
            f"  Budget: {profile.get('budget')}\n"
            f"  Preferred brands: {profile.get('preferred_brands')}\n\n"
            f"Concern category: {state.get('concern_category', 'general')}\n\n"
            f"Evidence:\n{evidence_context}"
        )),
    ])
    return {"plan": plan}


# ─────────────────────────────────────────────────────────────────────────────
# 6. REDUCER
# ─────────────────────────────────────────────────────────────────────────────

def reducer_node(state: State):

    plan = state["plan"]

    return {
        "final": plan.model_dump()
    }

# ─────────────────────────────────────────────────────────────────────────────
# 7. BUILD GRAPH
# ─────────────────────────────────────────────────────────────────────────────

def build_app():
    g = StateGraph(State)
    g.add_node("router",       router_node)
    g.add_node("research",     research_node)
    g.add_node("orchestrator", orchestrator_node)
    g.add_node("reducer",      reducer_node)

    g.add_edge(START,        "router")
    g.add_edge("router",     "research")
    g.add_edge("research",   "orchestrator")
    g.add_edge("orchestrator",     "reducer")
    g.add_edge("reducer",    END)

    return g.compile()


# ─────────────────────────────────────────────────────────────────────────────
# 8. PUBLIC ENTRY POINT  (called by FastAPI)
# ─────────────────────────────────────────────────────────────────────────────

def run_derm_agent(question: str, profile: dict) -> dict:
    """
    profile keys (snake_case, matches FastAPI Profile model):
        skin_type, concerns, budget, preferred_brands
    """
    llm_instance = ChatGroq(model="llama-3.3-70b-versatile")

    app = build_app()

    initial_state: State = {
        "llm":              llm_instance,
        "question":         question,
        "profile":          profile,   # pass through as-is (snake_case)
        "concern_category": "general",
        "queries":          [],
        "evidence":         [],
        "plan":             None,
        "final":            "",
    }

    result = app.invoke(initial_state)
    return result["final"]