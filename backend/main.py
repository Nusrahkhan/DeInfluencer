from datetime import timezone, datetime, timedelta
from urllib import response
from fastapi import BackgroundTasks, FastAPI, HTTPException
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from typing import List, Dict
import os
from dotenv import load_dotenv
from google import genai
import json
import re
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

from chatbot import run_derm_agent
from ing_scrape import scrape_product_by_url, search_incidecoder
import final_scrape
from sentiment import (
    analyze_reviews_from_records,
    resolve_gemini_api_key
)
from trending import run_agent

# Load environment variables from .env file
load_dotenv()

# ── Clients ───────────────────────────────────────────────────────────

# Initialize Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Configure Gemini API
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))  # ✅ new SDK

# ── Helper Functions ───────────────────────────────────────────────────────────

async def run_agent_and_store() -> dict:
    """
    Runs the skincare agent, then writes one row per product to Supabase,
    plus one row for the full compiled blog.
    Returns a summary dict.
    """
    logger.info("Agent run started")
    #supabase = get_supabase()
    run_ts = datetime.now(timezone.utc).isoformat()
 
    try:
        out = run_agent()  # blocking — fine for a weekly job
    except Exception as e:
        logger.exception("Agent failed")
        raise RuntimeError(f"Agent run failed: {e}") from e
 
    products = out.get("products", [])
    insights = out.get("insights", [])
    blog_md  = out.get("blog", "")
 
    # Build a lookup: "Brand Name" → TrendingProduct
    trend_map = {f"{p.brand} {p.name}".strip(): p for p in products}
 
    rows = []
    for insight in insights:
        trend = trend_map.get(insight.product_name)
        rows.append({
            "run_at":                run_ts,
            "product_name":          insight.product_name,
            "brand":                 trend.brand         if trend else None,
            "hype_summary":          trend.hype_summary  if trend else None,
            "trend_source":          trend.trend_source  if trend else None,
            "key_ingredients":       [{"name": i.name, "role": i.role, "benefit": i.benefit} for i in insight.key_ingredients],
            "good_for_skin_types":   insight.good_for_skin_types,
            "avoid_if":              insight.avoid_if,
            "dermatologist_verdict": insight.dermatologist_verdict,
            "source_urls":           insight.source_urls,
            "blog_markdown":         blog_md,
        })
 
    print(f"Prepared {len(rows)} rows for insertion")
    print(rows[0] if rows else "No rows to insert")
    resp = supabase.table("skincare_bulletins").insert(rows).execute()
    
    #if not resp.data:
    #    raise RuntimeError("Failed to insert rows into Supabase")
 
    logger.info(f"Agent run complete — {len(rows)} product(s) stored")
    return {"run_at": run_ts, "products_stored": len(rows), "products": [r["product_name"] for r in rows]}


# ── Scheduler setup ───────────────────────────────────────────────────────────

scheduler = AsyncIOScheduler(timezone="UTC")

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("LIFESPAN STARTED")
    scheduler.add_job(
        run_agent_and_store,
        trigger=CronTrigger(day_of_week="sun", hour=4, minute=7, timezone="UTC"),
        id="weekly_skincare_agent",
        name="Weekly Skincare Bulletin",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    job = scheduler.get_job("weekly_skincare_agent")
    logger.info(f"Next scheduled run: {job.next_run_time}")
    logger.info("Scheduler started — agent runs every Sunday 04:05 UTC (9:35 AM IST)")
    yield
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5500"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API Endpoints ───────────────────────────────────────────────────────────

@app.get("/")
def home():
    return {"message": "Hello from FastAPI"}

# ─────────────────────────────────────────────
# CORE: Search for a product, return details, triggered when searching in frontend. If not in DB, scrape Reddit + analyze sentiment on the fly. 
#─────────────────────────────────────────────
@app.get("/search-product")
def search_product(query: str) -> Dict:
    """
    Search for products by name and fetch their sentiment data
    """
    try:
        # Search in products table for matching product names
        products_response = supabase.table("products").select("*").ilike("product_name", f"%{query}%").execute()
        products = products_response.data
        print("hiii")
        print(products)
        
        if not products:
            not_in_db_response = not_in_db(query)
            return not_in_db_response
        
        # Get the first product and its ID
        product = products[0]
        product_id = int(product["id"])
        print(product_id)
        
        # Fetch sentiment data for these products
        sentiment_response = supabase.table("product_sentiment").select("*").ilike("product", f"%{query}%").execute()
        print(sentiment_response)
        sentiment = sentiment_response.data[0] if sentiment_response.data else {}

        print(f"Sentiment: {sentiment.get('average_sentiment')}")
            
        return {
            # Products table fields
            "product_name": product.get("product_name"),
            "brand_name": product.get("brand_name"),
            "ingredients": product.get("ingredients"),
            "comedogenic_score": product.get("comedogenic_score"),
            "product_picture": product.get("product_picture"),
            "source_url": product.get("source_url"),
            # Product sentiment table fields
            "average_sentiment": sentiment.get("average_sentiment") if sentiment else None,
            "positive_percentile": sentiment.get("positive_percentile") if sentiment else None,
            "negative_percentile": sentiment.get("negative_percentile") if sentiment else None,
            "positive_themes": sentiment.get("positive_themes") if sentiment else None,
            "negative_themes": sentiment.get("negative_themes") if sentiment else None,
            "summary": sentiment.get("summary") if sentiment else None,
        }    
    except Exception as e:
        return {"error": str(e)}
    

# ─────────────────────────────────────────────
# HELPER: Scrape Reddit posts and comments for a product
# ─────────────────────────────────────────────
@app.get("/not_in_db")
def not_in_db(query: str) -> Dict:
    try:
        #Step 0: Get product details from INCIDecoder
        ing_details = scrape_product(query)
        brand_name = ing_details.get("brand", "Unknown")
        ingredients = ing_details.get("ingredients", "")
        comedogenic_score = ing_details.get("comedogenic_score", None)
        product_picture = ing_details.get("product_picture", None)
        source_url = ing_details.get("source_url", None)
        product_id = product_id = ing_details.get("db_id")

        print(ing_details.get("product_name", query))

        # Step 1: Scrape Reddit reviews

        print(f"🔍 Scraping Reddit for: {query}")
        raw_records = final_scrape.scrape_product_reviews(query, target=60)
        
        if not raw_records:
            return {
                # Products table fields
                "product_name": query,
                "brand_name": brand_name,
                "ingredients": ingredients,
                "comedogenic_score": comedogenic_score,
                "product_picture": product_picture,
                "source_url": source_url,
            }
        
        print(f"✅ Scraped {len(raw_records)} raw reviews")

        prompt = f"""
        You are a review filter and cleaner for skincare/beauty products.
        
        Product: {query}
        
        Below are Reddit reviews/comments about this product. Your task:
        1. KEEP ONLY reviews that either PRAISE or CRITICIZE the product (strong sentiment)
        2. REMOVE generic comments, off-topic discussions, or neutral statements
        3. REMOVE spam or irrelevant content
        4. CLEAN up each review (fix typos, remove unnecessary punctuation, keep meaning intact)
        5. Return ONLY valid reviews in JSON format
        
        For each valid review, include these exact fields:
        - source: "reddit_comment"
        - subreddit: the subreddit name
        - title: the post title
        - body: the cleaned review text
        - reviewer: the author
        - upvotes: the score/upvotes as a number
        - date: the date in YYYY-MM-DD format
        - url: the URL
        - product_name: {query}
        
        Reviews to filter:
        {raw_records}
        
        Return a valid JSON array starting with [ and ending with ]. Include ONLY the cleaned reviews.
        Do NOT include markdown code blocks or any explanations. Start directly with the JSON array.
        """

        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )

            # Extract text safely
            response_text = ""
            if hasattr(response, "text") and response.text:
                response_text = response.text.strip()
            elif response.candidates:
                response_text = response.candidates[0].content.parts[0].text.strip()

            print(f"DEBUG finish_reason: {response.candidates[0].finish_reason if response.candidates else 'NO CANDIDATES'}")
            print(f"DEBUG text empty: {not bool(response_text)}")

            if not response_text:
                return {"error": "Gemini returned an empty response"}

            # Strip markdown fences if present
            if response_text.startswith("```"):
                response_text = re.sub(r"^```(?:json)?\n?", "", response_text)
                response_text = re.sub(r"\n?```$", "", response_text)
                response_text = response_text.strip()

            # Parse JSON
            cleaned_records = json.loads(response_text)

        except Exception as e:
            print(f"❌ Error calling Gemini: {e}")
            return {
                # Products table fields
                "product_name": query,
                "brand_name": brand_name,
                "ingredients": ingredients,
                "comedogenic_score": comedogenic_score,
                "product_picture": product_picture,
                "source_url": source_url,
            }
        
        # Step 4: Format records for reddit_reviews table
        print(f"📝 Formatting records for database...")
        formatted_records = []
        
        for record in cleaned_records:
            # Convert date string (YYYY-MM-DD) to Unix timestamp
            try:
                from datetime import datetime
                date_obj = datetime.strptime(record.get("date", "2024-01-01"), "%Y-%m-%d")
                date_timestamp = int(date_obj.timestamp())
            except:
                date_timestamp = int(datetime.now().timestamp())
            formatted_record = {
                "product_id": product_id,
                "product": query,  # Insert the product name/query
                "source": record.get("source", "reddit_comment"),
                "subreddit": record.get("subreddit", ""),
                "reviewer": record.get("reviewer", record.get("author", "[deleted]")),              
                "title": record.get("title", ""),
                "body": record.get("body", ""),
                "date": date_timestamp,  # Unix timestamp as BIGINT
                "upvotes": record.get("upvotes", 0),
                "url": record.get("url", ""),
                # created_at is auto-generated by DEFAULT NOW()
            }
            print(f"Formatted record: {formatted_record}")
            formatted_records.append(formatted_record)

        # Step 5: Insert into reddit_reviews table
        try:
            # Insert records into reddit_reviews table
            response = supabase.table("reddit_reviews").insert(formatted_records).execute()
            
            print(f"✅ Successfully inserted {len(cleaned_records)} reviews into reddit_reviews!")
            
        except Exception as e:
            print(f"❌ Error inserting into Supabase: {e}")
            return {
                # Products table fields
                "product_name": query,
                "brand_name": brand_name,
                "ingredients": ingredients,
                "comedogenic_score": comedogenic_score,
                "product_picture": product_picture,
                "source_url": source_url,
            }
        
        # Step 6: Perform sentiment analysis
        print(f"📊 Performing sentiment analysis...")
        gemini_api_key = resolve_gemini_api_key()
        print(formatted_records[0] if formatted_records else "No records to analyze")

        sentiment_report = analyze_reviews_from_records(
            records=formatted_records,
            use_ai_summary=True,
            gemini_api_key=gemini_api_key,
            gemini_model="gemini-2.5-flash-lite",
        )

        print(sentiment_report)

        print("✅ Sentiment analysis complete")

        # Convert DataFrame to JSON response
        sentiment_data = sentiment_report.to_dict(orient="records")
        sentiment_raw = sentiment_data[0] if sentiment_data else {}
        print(f"Raw sentiment data: {sentiment_raw}")

        # Normalize keys: "Average Sentiment" -> "average_sentiment"
        sentiment = {k.lower().replace(" ", "_"): v for k, v in sentiment_raw.items()}

        try: 
            print("💾 Inserting into product_sentiment...")

            sentiment_insert = {
                "product": query,
                "review_count": len(formatted_records),
                "average_sentiment": sentiment.get("average_sentiment"),
                "score": sentiment.get("score_5") or sentiment.get("score"),  # fallback safety
                "positive_percentile": sentiment.get("positive_percentile"),
                "negative_percentile": sentiment.get("negative_percentile"),
                "neutral_percentile": sentiment.get("neutral_percentile"),
                "positive_themes": sentiment.get("positive_themes"),
                "negative_themes": sentiment.get("negative_themes"),
                "summary": sentiment.get("summary"),
            }

            response = supabase.table("product_sentiment").insert(sentiment_insert).execute()

            print("✅ Inserted into product_sentiment")

        except Exception as e:
            print(f"❌ Error inserting product_sentiment: {e}")

        print("Normalized keys:", list(sentiment.keys()))  # debug: confirm key names

        print(sentiment.get("average_sentiment"))
        print(sentiment.get("positive_percentile"))
        print(sentiment.get("negative_percentile"))


        return {
            # Products table fields
            "product_name": query,
            "brand_name": brand_name,
            "ingredients": ingredients,
            "comedogenic_score": comedogenic_score,
            "product_picture": product_picture,
            "source_url": source_url,
            # Product sentiment table fields
            "average_sentiment": sentiment.get("average_sentiment"),
            "positive_percentile": sentiment.get("positive_percentile"),
            "negative_percentile": sentiment.get("negative_percentile"),
            "positive_themes": sentiment.get("positive_themes") ,
            "negative_themes": sentiment.get("negative_themes"),
            "summary": sentiment.get("summary")
        }    
    
    except Exception as e:
        print(f"NAHI HORAHA BHAI: {e}")  # also log the actual error!
        return {"error": str(e)}


@app.get("/scrape-product")
def scrape_product(product_name: str) -> dict:
    """
    Search INCIDecoder for a product by name and return its details.
    
    Example: GET /scrape-product?product_name=Cerave+Moisturizing+Cream
    """
    if not product_name.strip():
        raise HTTPException(status_code=400, detail="product_name cannot be empty")

    # Step 1: Search for the product
    search_result = search_incidecoder(product_name)
    if not search_result:
        raise HTTPException(
            status_code=404,
            detail=f"No product found on INCIDecoder for '{product_name}'"
        )

    # Step 2: Scrape the product page
    data = scrape_product_by_url(search_result["url"])

   # 3 Create a new product record with the scraped data
    new_product = {
        "product_name": data.get("product_name", product_name),
        "brand_name":   data.get("brand_name", "Unknown"), 
        "ingredients":  data.get("ingredients"),
        "comedogenic_score": data.get("comedogenic_score"),
        "product_picture":   data.get("product_picture"),
        "source_url":        data.get("source_url", search_result["url"]),
    }

    # Step 4: Insert into Supabase
    try:
        insert_response = supabase.table("products").insert([new_product]).execute()
        print("✅ Inserted:", insert_response.data)
        inserted_id = insert_response.data[0]["id"] if insert_response.data else None
        data["db_id"] = inserted_id  # add the new product ID to the response data
    except Exception as e:
        print(f"❌ Supabase insert error: {e}")
        raise HTTPException(status_code=500, detail=f"DB insert failed: {e}")

    return data

# ── Cron job: run trending agent & store bulletin results ───────────────────────────────────────
 
@app.post("/run-agent", summary="Trigger the agent immediately")
async def trigger_agent(background_tasks: BackgroundTasks):
    """
    Kicks off an agent run in the background right now.
    Returns immediately — check /bulletins for the result.
    """
    background_tasks.add_task(run_agent_and_store)
    return {"message": "Agent run started in the background. Check /bulletins shortly."}

# ── API Endpoint to fetch bulletin content from supabase ───────────────────────────────────────

@app.get("/bulletins", summary="Fetch all skincare bulletins")
def get_bulletins():
    """
    Fetches all skincare bulletins from the database from the past 1 week, ordered by most recent.
    Each bulletin includes product insights and the compiled blog markdown.
    """
    try:
        one_week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        response = supabase.table("skincare_bulletins").select("*").gte("run_at", one_week_ago).order("run_at", desc=True).execute()
        bulletins = response.data
        #print(bulletins)
        return {"bulletins": bulletins}
    except Exception as e:
        print(f"❌ Error fetching bulletins: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch bulletins: {e}")

# ── Chatbot API endpoint ───────────────────────────────────────
class Profile(BaseModel):
    skin_type: str
    concerns: str
    budget: str
    preferred_brands: str

class ChatRequest(BaseModel):
    question: str
    profile: Profile

@app.post("/chatbot")
async def chatbot(req: ChatRequest):

    answer = run_derm_agent(
        question=req.question,
        profile=req.profile.model_dump()
    )

    return {
        "answer": answer
    }