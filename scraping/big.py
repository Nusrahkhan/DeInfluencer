"""
multi_brand_scraper.py
======================
Scrapes Reddit reviews for multiple beauty/skincare brands,
then uses Gemini API (free tier) to classify each review to the correct product.

Brands: Laneige, Clinique, Estee Lauder, Forest Essentials, Chanel,
        La Mer, The Ordinary, Charlotte Tilbury, MAC, Huda Beauty, Dior

Output per brand:
  - {brand}_reviews_raw.db       (SQLite, all scraped rows)
  - {brand}_reviews_raw.csv      (CSV export of raw rows)
  - {brand}_reviews_sorted.csv   (Gemini-classified, product_name column added)

Setup:
    pip install requests google-generativeai
    Get a free Gemini API key at: https://aistudio.google.com/app/apikey
    Set it in your environment:
        export GEMINI_API_KEY=your_key_here     (Mac/Linux)
        set GEMINI_API_KEY=your_key_here        (Windows)
    Or paste it directly into GEMINI_API_KEY below.

Usage:
    python scraper.py                          # all brands
    python scraper.py --brand "Laneige"        # one brand
    python scraper.py --brand "Laneige" --skip-scrape   # classify only
"""

import argparse
import csv
import json
import os
import re
import sqlite3
import time
from urllib.parse import quote_plus

import requests

# ─── Gemini setup ─────────────────────────────────────────────────────────────
# Paste your key here OR set the GEMINI_API_KEY environment variable.
# Free tier: https://aistudio.google.com/app/apikey
GEMINI_API_KEY = "AIzaSyCoUN4fYT2lWPdwAdrcLPCp_dOzu15o0w0"  # ← paste key here if needed

if not GEMINI_API_KEY:
    raise SystemExit(
        "\n✗ GEMINI_API_KEY is not set.\n"
        "  Get a free key at: https://aistudio.google.com/app/apikey\n"
        "  Then run:  export GEMINI_API_KEY=your_key_here\n"
        "  Or paste it directly into GEMINI_API_KEY in scraper.py\n"
    )

GEMINI_MODEL   = "gemini-2.0-flash"          # stable free-tier model
GEMINI_API_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
)
GEMINI_HEADERS = {"Content-Type": "application/json"}


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SkincareReviewBot/1.0)",
    "Accept": "application/json",
}

DELAY_BETWEEN_CALLS = 2       # seconds between Reddit API calls
MAX_BODY_LENGTH     = 5000    # truncate very long posts
GEMINI_BATCH_SIZE   = 30      # reviews per Gemini call (smaller = safer on free tier)
GEMINI_DELAY        = 6       # seconds between Gemini calls (free tier: 15 RPM = 4s min, 6s = safe margin)
OUTPUT_DIR          = "output" # folder for all CSVs and DBs

SUBREDDITS = [
    "SkincareAddiction",
    "IndianSkincareAddicts",
    "AsianBeauty"
]

# ── Brand definitions ─────────────────────────────────────────────────────────
# search_queries: broad Reddit search terms that will surface discussions
# brand_keywords:  what must appear in the post title/body for it to be relevant
BRANDS = {
    "Laneige": {
        "search_queries": [
            '"Laneige"', '"Laneige" review'
        ],
        "brand_keywords": ["laneige"],
    },
    "Clinique": {
        "search_queries": [
            '"Clinique" review', '"Clinique" moisturizer', '"Clinique" foundation',
            '"Clinique" serum', '"Clinique" eye cream', '"Clinique" cleanser',
            '"Clinique" dramatically different', '"Clinique" black honey',
            '"Clinique" smart clinical', '"Clinique" acne solutions',
        ],
        "brand_keywords": ["clinique"],
    },
    "Estee Lauder": {
        "search_queries": [
            '"Estee Lauder" review', '"Estee Lauder" advanced night repair',
            '"Estee Lauder" double wear', '"Estee Lauder" serum',
            '"Estee Lauder" moisturizer', '"Estee Lauder" eye cream',
            '"Estee Lauder" sunscreen', '"Estee Lauder" foundation',
        ],
        "brand_keywords": ["estee lauder", "estée lauder"],
    },
    "Forest Essentials": {
        "search_queries": [
            '"Forest Essentials" review', '"Forest Essentials" moisturizer',
            '"Forest Essentials" cleanser', '"Forest Essentials" serum',
            '"Forest Essentials" sunscreen', '"Forest Essentials" face wash',
            '"Forest Essentials" toner',
        ],
        "brand_keywords": ["forest essentials"],
    },
    "Chanel": {
        "search_queries": [
            '"Chanel beauty" review', '"Chanel" skincare review',
            '"Chanel" foundation review', '"Chanel" N°1 skincare',
            '"Chanel" sublimage', '"Chanel" hydra beauty', '"Chanel" le lift',
            '"Chanel" les beiges', '"Chanel" serum review',
        ],
        "brand_keywords": ["chanel"],
    },
    "La Mer": {
        "search_queries": [
            '"La Mer" review', '"La Mer" moisturizer', '"La Mer" cream',
            '"La Mer" serum', '"La Mer" eye cream', '"La Mer" worth it',
            '"La Mer" creme de la mer', '"La Mer" regenerating serum',
        ],
        "brand_keywords": ["la mer", "la-mer", "creme de la mer"],
    },
    "The Ordinary": {
        "search_queries": [
            '"The Ordinary" review', '"The Ordinary" niacinamide',
            '"The Ordinary" retinol', '"The Ordinary" AHA BHA',
            '"The Ordinary" vitamin C', '"The Ordinary" hyaluronic acid',
            '"The Ordinary" peeling solution', '"The Ordinary" squalane',
            '"The Ordinary" serum', '"The Ordinary" moisturizer',
        ],
        "brand_keywords": ["the ordinary", "ordinary"],
    },
    "Charlotte Tilbury": {
        "search_queries": [
            '"Charlotte Tilbury" review', '"Charlotte Tilbury" magic cream',
            '"Charlotte Tilbury" foundation', '"Charlotte Tilbury" serum',
            '"Charlotte Tilbury" pillow talk', '"Charlotte Tilbury" flawless filter',
            '"Charlotte Tilbury" moisturizer', '"Charlotte Tilbury" eye cream',
        ],
        "brand_keywords": ["charlotte tilbury"],
    },
    "MAC": {
        "search_queries": [
            '"MAC Cosmetics" review', '"MAC" foundation review',
            '"MAC" lipstick review', '"MAC" studio fix', '"MAC" prep prime',
            '"MAC" eyeshadow', '"MAC" blush review', '"MAC" skincare',
        ],
        "brand_keywords": ["mac cosmetics", "mac makeup", "mac foundation",
                           "mac lipstick", "mac studio fix", "mac eyeshadow",
                           "mac blush", "mac prep prime"],
    },
    "Huda Beauty": {
        "search_queries": [
            '"Huda Beauty" review', '"Huda Beauty" foundation',
            '"Huda Beauty" eyeshadow', '"Huda Beauty" lipstick',
            '"Huda Beauty" setting spray', '"Huda Beauty" concealer',
            '"Huda Beauty" mascara', '"Huda Beauty" #fauxfilter',
        ],
        "brand_keywords": ["huda beauty", "hudabeauty"],
    },
    "Dior": {
        "search_queries": [
            '"Dior beauty" review', '"Dior" skincare review',
            '"Dior" foundation review', '"Dior" prestige skincare',
            '"Dior" capture totale', '"Dior" forever foundation',
            '"Dior" lip glow', '"Dior" backstage', '"Dior" rouge dior',
            '"Dior" serum review',
        ],
        "brand_keywords": ["dior beauty", "dior skincare", "dior makeup",
                           "dior foundation", "dior lip", "dior rouge",
                           "capture totale", "dior prestige", "dior forever"],
    },
}

# ─── Irrelevance filter (same logic as CeraVe pipeline) ──────────────────────

def is_irrelevant(review: str) -> bool:
    r  = review.strip()
    rl = r.lower()
    if len(r) < 15:
        return True
    if not re.search(r'[a-zA-Z]{2,}', r):
        return True
    SOCIAL = [
        r'^(thanks?|thank you|thankyou|ty|thx|tq)[\s.!,]*$',
        r'^(ok|okay|sure|alright|gotcha|will do|noted|understood)[\s.!,]*$',
        r'^(yes|yeah|yep|yup|nope|nah|no|true|correct|right|exactly|agreed|same)[\s.!,]*$',
        r'^(lol+|haha+|hehe+|lmao|rofl)[\s.!]*$',
        r'^(wow|nice|great|amazing|awesome|cool|good|bad|sad)[\s.!,]*$',
        r'^(same here|same tbh|same lol|me too)[\s.!]*$',
        r'^(congratulations|congrats)[\s.!]*$',
    ]
    for pat in SOCIAL:
        if re.match(pat, rl):
            return True
    if re.search(r'(love|like).{0,20}(your|ur)\s+(eyebrow|eyelash|hair|makeup|septum|piercing)', rl):
        return True
    if re.search(r'(you|ur)\s+(look|are)\s+(so\s+)?(pretty|beautiful|gorgeous|stunning)', rl):
        return True
    if re.search(r'do you have a (boyfriend|girlfriend|partner)', rl):
        return True
    if re.search(r'(just here to say|came here to say).{0,40}(look|eye|hair|pretty|beautiful)', rl):
        return True
    if re.search(r'stretch(ing)? (your )?(septum|piercing|lobe)', rl):
        return True
    if re.search(r'are you brand new to skincare', rl):
        return True
    if re.search(r'best place to start is (our|the) sc', rl):
        return True
    if re.search(r'join us for an ama with', rl):
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# REDDIT SCRAPER
# ═══════════════════════════════════════════════════════════════════════════════

def reddit_get(url: str) -> dict:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 429:
            print("    [Reddit] Rate limited — sleeping 60s...")
            time.sleep(60)
            r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"    [Reddit] Error: {e}")
        return {}


def clean_body(body: str) -> str:
    body = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)
    body = re.sub(r"[*_~`>#]+", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = body.replace("\r\n", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", body).strip()[:MAX_BODY_LENGTH]


def extract_comments_recursive(children: list, result: list, depth: int = 0):
    if depth > 10:
        return
    for child in children:
        if child.get("kind") == "more":
            continue
        d    = child.get("data", {})
        body = d.get("body", "").strip()
        if body and body not in ("[deleted]", "[removed]"):
            result.append({
                "author":      d.get("author", ""),
                "body":        clean_body(body),
                "score":       d.get("score", 0),
                "created_utc": str(d.get("created_utc", "")),
                "permalink":   d.get("permalink", ""),
            })
        replies = d.get("replies", {})
        if isinstance(replies, dict):
            reply_children = replies.get("data", {}).get("children", [])
            if reply_children:
                extract_comments_recursive(reply_children, result, depth + 1)


def fetch_post_comments(permalink: str) -> tuple[str, list[dict]]:
    url  = f"https://www.reddit.com{permalink}.json?limit=500"
    data = reddit_get(url)
    if not data or not isinstance(data, list) or len(data) < 2:
        return "", []
    post_items = data[0].get("data", {}).get("children", [])
    post_body  = clean_body(post_items[0].get("data", {}).get("selftext", "")) if post_items else ""
    comments   = []
    extract_comments_recursive(data[1].get("data", {}).get("children", []), comments)
    return post_body, comments


def init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            source        TEXT,
            subreddit     TEXT,
            reviewer_name TEXT,
            review_title  TEXT,
            review_body   TEXT,
            review_date   TEXT,
            helpful_count INTEGER DEFAULT 0,
            url           TEXT UNIQUE,
            scraped_at    TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_url ON reviews(url)")
    conn.commit()
    return conn


def insert_review(conn: sqlite3.Connection, row: dict) -> bool:
    try:
        conn.execute("""
            INSERT INTO reviews
                (source, subreddit, reviewer_name, review_title,
                 review_body, review_date, helpful_count, url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (row["source"], row["subreddit"], row["reviewer_name"],
              row["review_title"], row["review_body"],
              row["review_date"], row["helpful_count"], row["url"]))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def scrape_subreddit(subreddit: str, query: str, brand_keywords: list,
                     conn: sqlite3.Connection) -> int:
    encoded = quote_plus(query)
    url = (
        f"https://www.reddit.com/r/{subreddit}/search.json"
        f"?q={encoded}&restrict_sr=1&sort=relevance&type=link&limit=25"
    )
    data  = reddit_get(url)
    posts = data.get("data", {}).get("children", []) if data else []
    saved = 0

    for post in posts:
        d         = post.get("data", {})
        title     = d.get("title", "")
        permalink = d.get("permalink", "")
        if not permalink:
            continue

        # Must mention at least one brand keyword in title
        title_lower = title.lower()
        if not any(kw in title_lower for kw in brand_keywords):
            print(f"      ✗ Skipped: {title[:70]}")
            continue

        post_url = f"https://reddit.com{permalink}"
        print(f"      ✓ {title[:70]}")

        post_body, comments = fetch_post_comments(permalink)
        time.sleep(DELAY_BETWEEN_CALLS)

        if post_body:
            if insert_review(conn, {
                "source": "reddit_post", "subreddit": subreddit,
                "reviewer_name": d.get("author", ""),
                "review_title": title, "review_body": post_body,
                "review_date": str(d.get("created_utc", "")),
                "helpful_count": d.get("score", 0), "url": post_url,
            }):
                saved += 1

        for comment in comments:
            c_url = (f"https://reddit.com{comment['permalink']}"
                     if comment["permalink"] else post_url)
            if insert_review(conn, {
                "source": "reddit_comment", "subreddit": subreddit,
                "reviewer_name": comment["author"],
                "review_title": title, "review_body": comment["body"],
                "review_date": comment["created_utc"],
                "helpful_count": comment["score"], "url": c_url,
            }):
                saved += 1

    return saved


def scrape_brand(brand_name: str, cfg: dict, db_path: str) -> str:
    """Scrape all subreddits for a brand. Returns path to raw CSV."""
    conn = init_db(db_path)
    print(f"\n{'='*60}")
    print(f"  Scraping Reddit for: {brand_name}")
    print(f"{'='*60}")
    total = 0

    for subreddit in SUBREDDITS:
        print(f"\n  r/{subreddit}")
        for query in cfg["search_queries"]:
            print(f"    Query: {query}")
            saved  = scrape_subreddit(subreddit, query, cfg["brand_keywords"], conn)
            total += saved
            print(f"    → {saved} new rows")
            time.sleep(DELAY_BETWEEN_CALLS)

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM reviews")
    in_db = cur.fetchone()[0]
    print(f"\n  ✅ {brand_name}: {in_db} total rows in DB ({total} new this run)")

    # Export raw CSV
    slug     = brand_name.lower().replace(" ", "_").replace("'", "")
    csv_path = os.path.join(OUTPUT_DIR, f"{slug}_reviews_raw.csv")
    cur.execute("""
        SELECT source, subreddit, reviewer_name, review_title,
               review_body, review_date, helpful_count, url
        FROM reviews ORDER BY review_date DESC
    """)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Source", "Subreddit", "Reviewer", "Title", "Body", "Date", "Upvotes", "URL"])
        w.writerows(cur.fetchall())

    conn.close()
    print(f"  Raw CSV → {csv_path}")
    return csv_path


# ═══════════════════════════════════════════════════════════════════════════════
# GEMINI CLASSIFIER
# ═══════════════════════════════════════════════════════════════════════════════


def test_gemini_key() -> bool:
    """Verify the API key and model work before processing thousands of rows."""
    print("  Testing Gemini API key...", end=" ", flush=True)
    payload = {"contents": [{"parts": [{"text": "Reply with just: ok"}]}]}
    try:
        r = requests.post(GEMINI_API_URL, headers=GEMINI_HEADERS, json=payload, timeout=20)
        if r.status_code == 200:
            print("OK - key works")
            return True
        err = r.json().get("error", {}).get("message", r.text[:200])
        if r.status_code == 400:
            print(f"\nERROR - Model not found: {err}")
            print("  Edit GEMINI_MODEL in scraper.py")
            print("  Try: gemini-1.5-flash | gemini-1.5-pro | gemini-pro")
        elif r.status_code == 403:
            print("\nERROR - Invalid key or API not enabled.")
            print("  Get a free key: https://aistudio.google.com/app/apikey")
        elif r.status_code == 429:
            print("\nERROR - Rate limited on first call. Wait 60s then retry.")
        else:
            print(f"\nERROR - HTTP {r.status_code}: {err}")
        return False
    except Exception as e:
        print(f"\nERROR - {e}")
        return False

# Tracks the last time a Gemini call was made — used by throttle_gemini_rate()
_last_gemini_call_time: float = 0.0


def throttle_gemini_rate():
    """Enforce minimum gap between Gemini calls regardless of call duration."""
    global _last_gemini_call_time
    elapsed = time.time() - _last_gemini_call_time
    gap_needed = GEMINI_DELAY - elapsed
    if gap_needed > 0:
        time.sleep(gap_needed)
    _last_gemini_call_time = time.time()


def call_gemini(prompt: str) -> str | None:
    """Call Gemini API with rate throttling and exponential backoff on 429s."""
    throttle_gemini_rate()
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
    }
    wait_times = [15, 30, 60, 120]  # exponential backoff in seconds
    for attempt, wait in enumerate(wait_times):
        try:
            r = requests.post(GEMINI_API_URL, headers=GEMINI_HEADERS,
                              json=payload, timeout=60)
            if r.status_code == 429:
                if attempt < len(wait_times) - 1:
                    print(f"    [Gemini] Rate limited — sleeping {wait}s "
                          f"(attempt {attempt+1}/{len(wait_times)})...")
                    time.sleep(wait)
                    continue
                print("    [Gemini] Still rate limited after all retries.")
                print("    Tip: Increase GEMINI_DELAY at top of scraper.py (currently 5s)")
                return None
            if r.status_code == 400:
                err = r.json().get("error", {}).get("message", r.text[:200])
                print(f"    [Gemini] Bad request: {err}")
                print("    -> Try changing GEMINI_MODEL to: gemini-1.5-pro or gemini-pro")
                return None
            r.raise_for_status()
            data = r.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "")
            print(f"    [Gemini] Empty response: {str(data)[:200]}")
            return None
        except requests.exceptions.Timeout:
            print(f"    [Gemini] Timeout attempt {attempt+1} — retrying in 10s...")
            time.sleep(10)
        except Exception as e:
            print(f"    [Gemini] Error: {e}")
            return None
    return None


def extract_product_names_from_csv(csv_path: str, brand_name: str) -> list[str]:
    """
    Auto-detect product names by analysing thread titles with Gemini.
    Returns a list of exact product name strings for this brand.
    """
    titles = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            t = row.get("Title", "").strip()
            if t and t not in titles:
                titles.append(t)

    titles_sample = "\n".join(titles[:80])

    prompt = f"""You are a skincare/beauty expert. Based on the Reddit thread titles below (which are discussions about {brand_name} products), generate a comprehensive list of {brand_name} product names that are being discussed.

Reddit thread titles:
{titles_sample}

Return ONLY a JSON array of product name strings — exact product names as sold (e.g. "Laneige Water Sleeping Mask", "Laneige Lip Sleeping Mask Vanilla"). Include all variants you can identify from the titles. Be specific (include shade names or sizes only if they are clearly distinct products).

No explanation. No markdown. Just the raw JSON array."""

    result = call_gemini(prompt)
    if not result:
        return []

    try:
        clean = result.replace("```json", "").replace("```", "").strip()
        products = json.loads(clean)
        if isinstance(products, list):
            print(f"  Gemini identified {len(products)} products for {brand_name}")
            return [p.strip() for p in products if isinstance(p, str) and p.strip()]
    except Exception as e:
        print(f"  ✗ Failed to parse product list from Gemini: {e}")
        print(f"  Raw response: {result[:300]}")
    return []


def classify_batch(product_list: list[str], batch: list[dict]) -> list[str | None]:
    """Send a batch of reviews to Gemini for product classification."""
    product_list_str = "\n".join(f"- {p}" for p in product_list)
    review_items = "\n\n".join(
        f'[{i}] TITLE: {row["Title"][:150]}\n    BODY: {row["Body"][:300]}'
        for i, row in enumerate(batch)
    )

    prompt = f"""You are matching Reddit reviews to specific beauty/skincare products.

PRODUCT LIST (use EXACT names from this list only):
{product_list_str}

REVIEWS TO CLASSIFY:
{review_items}

TASK: For each review [0] to [{len(batch)-1}], determine which product it is specifically about.

RULES:
- Match ONLY if the review explicitly mentions or is clearly about that specific product.
- The TITLE is the Reddit thread context (strong signal). The BODY is the comment (must be relevant).
- If a review is generic, about a different product, or cannot be confidently matched → return null.
- Use EXACT product names from the list. Do not paraphrase or invent names.

Return ONLY a JSON array of {len(batch)} elements.
Each element: exact product_name string OR null.
No explanation. No markdown. Just the raw JSON array.

Example: ["Laneige Water Sleeping Mask", null, "Laneige Lip Sleeping Mask Vanilla"]"""

    result = call_gemini(prompt)
    if not result:
        return [None] * len(batch)

    try:
        clean = result.replace("```json", "").replace("```", "").strip()
        labels = json.loads(clean)
        if isinstance(labels, list) and len(labels) == len(batch):
            return labels
    except Exception as e:
        print(f"    ✗ Parse error: {e} | Response: {result[:200]}")
    return [None] * len(batch)


def classify_brand(brand_name: str, raw_csv_path: str) -> str:
    """
    Read raw CSV, classify each review to a product using Gemini.
    Returns path to sorted output CSV.
    """
    print(f"\n{'='*60}")
    print(f"  Classifying reviews for: {brand_name}")
    print(f"{'='*60}")

    # Load raw rows
    if not test_gemini_key():
        return ""
    time.sleep(GEMINI_DELAY)  # space out from key test call

    with open(raw_csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"  Loaded {len(rows)} raw rows")

    # Filter irrelevant content first
    rows = [r for r in rows if not is_irrelevant(r.get("Body", ""))]
    rows = [r for r in rows if len(r.get("Body", "").strip()) >= 30]
    print(f"  {len(rows)} rows after relevance filter")

    if not rows:
        print("  ✗ No rows to classify")
        return ""

    # Step 1: Get product list from Gemini by analysing the titles
    print(f"\n  Step 1: Detecting {brand_name} products from thread titles...")
    product_list = extract_product_names_from_csv(raw_csv_path, brand_name)
    time.sleep(GEMINI_DELAY)  # space out before batch classification starts
    if not product_list:
        print("  ✗ Could not generate product list — aborting classification")
        return ""
    print(f"  Products identified: {len(product_list)}")
    for p in product_list:
        print(f"    • {p}")

    # Step 2: Classify in batches
    print(f"\n  Step 2: Classifying {len(rows)} reviews in batches of {GEMINI_BATCH_SIZE}...")
    matched_rows  = []
    total_matched = 0
    total_batches = (len(rows) + GEMINI_BATCH_SIZE - 1) // GEMINI_BATCH_SIZE

    for i in range(0, len(rows), GEMINI_BATCH_SIZE):
        batch     = rows[i: i + GEMINI_BATCH_SIZE]
        batch_num = i // GEMINI_BATCH_SIZE + 1
        print(f"    Batch {batch_num}/{total_batches} ({len(batch)} reviews)...", end=" ", flush=True)

        assignments = classify_batch(product_list, batch)

        for row, product_name in zip(batch, assignments):
            if product_name and product_name in product_list:
                matched_rows.append({
                    "product_name": product_name,
                    "review":       row.get("Body", "").strip(),
                    "title":        row.get("Title", "").strip(),
                    "subreddit":    row.get("Subreddit", ""),
                    "source":       row.get("Source", ""),
                    "reviewer":     row.get("Reviewer", ""),
                    "url":          row.get("URL", ""),
                })
                total_matched += 1

        pct = 100 * total_matched / (i + len(batch))
        print(f"{total_matched} matched so far ({pct:.0f}%)")
        # Rate limiting handled by throttle_gemini_rate() inside call_gemini()

    # Step 3: Write sorted CSV
    slug     = brand_name.lower().replace(" ", "_").replace("'", "")
    out_path = os.path.join(OUTPUT_DIR, f"{slug}_reviews_sorted.csv")
    out_cols = ["product_name", "review", "title", "subreddit", "source", "reviewer", "url"]

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_cols)
        writer.writeheader()
        writer.writerows(matched_rows)

    pct = 100 * total_matched / len(rows) if rows else 0
    print(f"\n  ✅ {total_matched}/{len(rows)} reviews classified ({pct:.0f}%) → {out_path}")

    # Print per-product summary
    from collections import Counter
    counts = Counter(r["product_name"] for r in matched_rows)
    print(f"\n  Product breakdown ({len(counts)} products with reviews):")
    for prod, cnt in counts.most_common():
        print(f"    {cnt:5d}  {prod}")

    return out_path


# ═══════════════════════════════════════════════════════════════════════════════
# PIPELINE ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════════

def run_brand(brand_name: str, skip_scrape: bool = False):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    slug    = brand_name.lower().replace(" ", "_").replace("'", "")
    db_path = os.path.join(OUTPUT_DIR, f"{slug}_reviews_raw.db")
    raw_csv = os.path.join(OUTPUT_DIR, f"{slug}_reviews_raw.csv")
    cfg     = BRANDS[brand_name]

    print(f"\n{'#'*65}")
    print(f"  PIPELINE: {brand_name}")
    print(f"{'#'*65}")

    # Step 1: Scrape
    if not skip_scrape:
        raw_csv = scrape_brand(brand_name, cfg, db_path)
    else:
        print(f"\n  [SKIP] Reddit scrape — using existing: {raw_csv}")
        if not os.path.exists(raw_csv):
            print(f"  ✗ Raw CSV not found: {raw_csv}")
            return

    # Step 2: Classify
    classify_brand(brand_name, raw_csv)


def main():
    parser = argparse.ArgumentParser(description="Multi-brand beauty review scraper + classifier")
    parser.add_argument("--brand",        type=str,  help="Single brand name (must match BRANDS key)")
    parser.add_argument("--all",          action="store_true", help="Run all brands")
    parser.add_argument("--skip-scrape",  action="store_true", help="Skip Reddit scrape, classify existing CSV only")
    parser.add_argument("--list-brands",  action="store_true", help="Print available brands")
    args = parser.parse_args()

    if args.list_brands:
        print("Available brands:")
        for b in BRANDS:
            print(f"  • {b}")
        return

    if args.all:
        for brand in BRANDS:
            run_brand(brand, skip_scrape=args.skip_scrape)
    elif args.brand:
        if args.brand not in BRANDS:
            print(f"✗ Brand '{args.brand}' not found.")
            print(f"  Available: {', '.join(BRANDS.keys())}")
        else:
            run_brand(args.brand, skip_scrape=args.skip_scrape)
    else:
        parser.print_help()
        print("\nAvailable brands:")
        for b in BRANDS:
            print(f"  • {b}")


if __name__ == "__main__":
    main()