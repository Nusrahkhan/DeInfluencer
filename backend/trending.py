"""
Skincare Trending Products Bulletin Agent
-----------------------------------------
Pipeline:
  trend_finder → researcher → blog_writer → END

1. trend_finder  – searches the web for 1-2 trending skincare/makeup products of this week on social media platforms, Reddit, tiktok etc. Focuses on viral momentum and buzz signals, not just popularity.
2. researcher    – for each product, fetches dermatologist insights, ingredients & skin-type info
3. blog_writer   – compiles everything into a bulletin-style Markdown blog
"""

import os, time, getpass, operator
from datetime import date
from typing import Any, List, Optional, Annotated

from pydantic import BaseModel, Field
from typing_extensions import TypedDict, Literal

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_community.tools.tavily_search import TavilySearchResults
from langgraph.graph import StateGraph, START, END
import os
from dotenv import load_dotenv

load_dotenv()

# ── Pydantic models ────────────────────────────────────────────────────────────

class TrendingProduct(BaseModel):
    name: str
    brand: str
    hype_summary: str = Field(..., description="1-2 sentences on why it is trending this week")
    trend_source: Optional[str] = None          # e.g. "TikTok", "Reddit SkincareAddiction"


class TrendFinderOutput(BaseModel):
    products: List[TrendingProduct] = Field(..., min_length=1, max_length=2)


class Ingredient(BaseModel):
    name: str
    role: str                                   # e.g. "humectant", "exfoliant"
    benefit: str


class DermInsight(BaseModel):
    product_name: str
    key_ingredients: List[Ingredient]
    good_for_skin_types: List[str]              # e.g. ["oily", "combination"]
    avoid_if: Optional[str] = None              # e.g. "sensitive skin, rosacea"
    dermatologist_verdict: str                  # 2-3 sentences, evidence-based
    source_urls: List[str]                      # verifiable URLs used


class ResearchOutput(BaseModel):
    insights: List[DermInsight]


# ── State ──────────────────────────────────────────────────────────────────────

class State(TypedDict):
    llm: Any
    products: List[TrendingProduct]
    insights: List[DermInsight]
    blog: str


# ── Helpers ────────────────────────────────────────────────────────────────────

def _search(query: str, max_results: int = 6) -> List[dict]:
    """Thin wrapper around Tavily."""
    tool = TavilySearchResults(max_results=max_results)
    results = tool.invoke({"query": query}) or []
    out = []
    for r in results:
        out.append({
            "title":   r.get("title", ""),
            "url":     r.get("url", ""),
            "snippet": (r.get("content") or r.get("snippet", ""))[:200],
        })
    return out


def _fmt(results: List[dict]) -> str:
    return "\n".join(
        f"{i+1}. {r['title']} | {r['url']}\n   {r['snippet']}"
        for i, r in enumerate(results)
        if r.get("url")
    )


def _invoke(llm, messages, model_cls):
    """Structured output call with one retry."""
    structured = llm.with_structured_output(model_cls)
    for attempt in range(2):
        try:
            return structured.invoke(messages)
        except Exception as e:
            if attempt == 0:
                time.sleep(3)
            else:
                raise e


# ── Node 1: trend_finder ───────────────────────────────────────────────────────

TREND_SYSTEM = """You are a beauty trend analyst.

Search results below are from this week. Identify exactly 1 or 2 skincare or makeup
products that are genuinely trending and viral RIGHT NOW on social media platforms, Reddit, TikTok etc. (not evergreen classics).
These products need not be new launches — they could be older products that suddenly blew up due to a viral TikTok, celebrity endorsement, Reddit thread, instagram influencers etc.

A product should ONLY be selected if:
- multiple sources mention it repeatedly
- attention is accelerating this week
- discussions feel time-sensitive and viral
- there is evidence of unusual consumer buzz

Prioritize:
- sudden mention spikes
- repeated creator/influencer mentions
- cross-platform discussion
- “TikTok made me buy it” style momentum
- products appearing in multiple trend lists/videos/posts
- products going viral in asian communities or brown skin communities

Avoid:
- generic recommendations
- old bestselling products without new momentum
- sponsored products with no viral signals

For each product provide:
- name & brand
- hype_summary: why it exploded this week (viral TikTok, celebrity, Reddit thread, etc.)
- trend_source: where the buzz originated (TikTok, Reddit, Instagram, Youtube etc.)

Return ONLY the structured output. Do not invent products not mentioned in the results.
"""

def trend_finder_node(state: State) -> dict:
    llm: ChatGroq = state["llm"]
    today = date.today().strftime("%B %Y")

    queries = [
        f"trending skincare products this week {today}",
        f"viral makeup product {today} TikTok Reddit Youtube Instagram",
        #f"new skincare launch hype {today}",
    ]

    raw = []
    for q in queries:
        raw.extend(_search(q, max_results=5))

    result = _invoke(llm, [
        SystemMessage(content=TREND_SYSTEM),
        HumanMessage(content=f"Search results:\n{_fmt(raw[:18])}"),
    ], TrendFinderOutput)

    print(f"[trend_finder] Found {len(result.products)} trending product(s)")
    for p in result.products:
        print(f"  • {p.brand} – {p.name}")

    return {"products": result.products}


# ── Node 2: researcher ─────────────────────────────────────────────────────────

RESEARCH_SYSTEM = """You are a cosmetic dermatologist and cosmetic chemist.

Given web search results about a skincare/makeup product, extract:
- key_ingredients: list each active with its role (e.g. humectant, retinoid) and benefit
- good_for_skin_types: which skin types genuinely benefit
- avoid_if: contraindications or skin types that should skip it (null if none)
- dermatologist_verdict: 2-3 evidence-based sentences; cite what studies or expert
  sources say; be honest about hype vs reality
- source_urls: list the URLs you drew facts from (only real URLs from the results)

Be conservative — only claim what the evidence supports.
"""

def researcher_node(state: State) -> dict:
    llm: ChatGroq = state["llm"]
    all_insights: List[DermInsight] = []

    for product in state["products"]:
        queries = [
            f"{product.name} {product.brand} ingredients dermatologist review",
            f"{product.name} {product.brand} skin type suitable ncbi pubmed",
            f"site:aad.org OR site:dermnetnz.org OR site:ncbi.nlm.nih.gov {product.name} ingredients",
        ]

        raw = []
        for q in queries:
            raw.extend(_search(q, max_results=5))
            time.sleep(0.5)

        prompt = (
            f"Product: {product.brand} – {product.name}\n"
            f"Why it's trending: {product.hype_summary}\n\n"
            f"Search results:\n{_fmt(raw[:15])}"
        )

        insight = _invoke(llm, [
            SystemMessage(content=RESEARCH_SYSTEM),
            HumanMessage(content=prompt),
        ], DermInsight)

        # Ensure product name is set correctly
        insight.product_name = f"{product.brand} {product.name}"
        all_insights.append(insight)

        print(f"[researcher] Done: {insight.product_name} | "
              f"{len(insight.key_ingredients)} ingredients | "
              f"sources: {len(insight.source_urls)}")

    return {"insights": all_insights}


# ── Node 3: blog_writer ────────────────────────────────────────────────────────

BLOG_SYSTEM = """You are a beauty editor writing a weekly skincare bulletin for
a well-informed audience that wants both the cultural buzz AND the real science.

Write a bulletin-style Markdown blog post with this exact structure:

---
# 🧴 This Week in Skincare: What's Actually Worth the Hype

## 📢 The Weekly Radar
One short paragraph (3-4 sentences) setting the scene for the week.

---

Then for EACH product, create a section like this:

## [EMOJI] [Product Name] by [Brand]
### 💬 Why Everyone's Talking About It
(2-3 sentences on the social buzz, trend origin)

### 🔬 What's Actually In It
Markdown table with columns: Ingredient | Role | Benefit

### 🧑‍⚕️ Dermatologist's Take
(The honest evidence-based verdict, 3-4 sentences)

### ✅ Who Should Try It
- **Best for:** [skin types]
- **Skip if:** [contraindications or "No major concerns"]

### 📚 Sources
(bullet list of [Source Title](url) from the verifiable URLs)

---

## ⚖️ Bottom Line
One paragraph comparing the products and giving a clear recommendation.

---
*This bulletin is for educational purposes only. Consult a dermatologist for
personalised advice.*

Rules:
- Keep the total under 800 words
- Be honest: separate hype from evidence
- Never invent URLs — only use the ones provided
- Tone: smart, friendly, slightly editorial
"""


def blog_writer_node(state: State) -> dict:
    llm: ChatGroq = state["llm"]

    # Serialize insights for the prompt
    def serialise(insight: DermInsight) -> str:
        ingr = "\n".join(
            f"  - {i.name}: {i.role} — {i.benefit}"
            for i in insight.key_ingredients
        )
        urls = "\n".join(f"  - {u}" for u in insight.source_urls)
        return (
            f"PRODUCT: {insight.product_name}\n"
            f"Ingredients:\n{ingr}\n"
            f"Good for: {', '.join(insight.good_for_skin_types)}\n"
            f"Avoid if: {insight.avoid_if or 'N/A'}\n"
            f"Derm verdict: {insight.dermatologist_verdict}\n"
            f"Sources:\n{urls}"
        )

    # Include hype context from the trend finder
    hype_block = "\n\n".join(
        f"PRODUCT: {p.brand} {p.name}\n"
        f"Hype summary: {p.hype_summary}\n"
        f"Trend source: {p.trend_source or 'various'}"
        for p in state["products"]
    )

    research_block = "\n\n---\n\n".join(
        serialise(ins) for ins in state["insights"]
    )

    blog_md = llm.invoke([
        SystemMessage(content=BLOG_SYSTEM),
        HumanMessage(content=(
            f"TREND DATA:\n{hype_block}\n\n"
            f"RESEARCH DATA:\n{research_block}"
        )),
    ]).content.strip()

    print("[blog_writer] Blog written ✓")
    return {"blog": blog_md}


# ── Graph ──────────────────────────────────────────────────────────────────────

g = StateGraph(State)
g.add_node("trend_finder", trend_finder_node)
g.add_node("researcher",   researcher_node)
g.add_node("blog_writer",  blog_writer_node)

g.add_edge(START,          "trend_finder")
g.add_edge("trend_finder", "researcher")
g.add_edge("researcher",   "blog_writer")
g.add_edge("blog_writer",  END)

app = g.compile()


# ── Runner ─────────────────────────────────────────────────────────────────────

def run():
    """Collect API keys and run the agent."""

    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        api_key=os.environ["GROQ_API_KEY"],
    )

    out = app.invoke({
        "llm":      llm,
        "products": [],
        "insights": [],
        "blog":     "",
    })

    print("\n" + "=" * 60)
    print(out["blog"])
    print("=" * 60)
    return out


if __name__ == "__main__":
    run()