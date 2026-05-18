from urllib import response

from click import prompt
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from typing import List, Dict
import os
from dotenv import load_dotenv
from google import genai
import json
import re

from ing_scrape import scrape_product_by_url, search_incidecoder
import final_scrape
from sentiment import (
    analyze_reviews_from_records,
    resolve_gemini_api_key
)

# Load environment variables from .env file
load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Configure Gemini API
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))  # ✅ new SDK

@app.get("/")
def home():
    return {"message": "Hello from FastAPI"}

@app.get("/search-product")
def search_product(query: str) -> Dict:
    """
    Search for products by name and fetch their sentiment data
    """
    try:
        # Search in products table for matching product names
        products_response = supabase.table("products").select("*").ilike("product_name", f"%{query}%").execute()
        products = products_response.data
        
        if not products:
            not_in_db_response = not_in_db(query)
            return not_in_db_response
        
        # Get the first product and its ID
        product = products[0]
        product_id = int(product["id"])
        print(product_id)
        
        # Fetch sentiment data for these products
        sentiment_response = supabase.table("product_sentiment").select("*").eq("product_id", product_id).execute()
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
            return {"status": "nothing", "message": "No reviews scraped from Reddit"}
        
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
            return {"error": str(e)}

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
            formatted_records.append(formatted_record)

        # Step 5: Insert into reddit_reviews table
        try:
            # Insert records into reddit_reviews table
            #response = supabase.table("reddit_reviews").insert(formatted_records).execute()
            
            print(f"✅ Successfully inserted {len(cleaned_records)} reviews into reddit_reviews!")
            
        except Exception as e:
            print(f"❌ Error inserting into Supabase: {e}")
            return {"error": str(e)}
        
        # Step 6: Perform sentiment analysis
        print(f"📊 Performing sentiment analysis...")
        gemini_api_key = resolve_gemini_api_key()

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

        # Normalize keys: "Average Sentiment" -> "average_sentiment"
        sentiment = {k.lower().replace(" ", "_"): v for k, v in sentiment_raw.items()}

        print("Normalized keys:", list(sentiment.keys()))  # debug: confirm key names

        print(sentiment.get("average_sentiment"))


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
