import requests
import sqlite3
import csv
import time
import re
from urllib.parse import quote_plus


# ─── Config ───────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DotKeyReviewBot/1.0)",
    "Accept": "application/json",
}

PRIMARY_SUBREDDIT  = "IndianSkincareAddicts"
FALLBACK_SUBREDDIT = "SkincareAddiction"

MAX_BODY_LENGTH     = 5000
DELAY_BETWEEN_CALLS = 2

FORM_TYPES = [
    "serum", "toner", "moisturizer", "moisturiser", "cleanser",
    "facewash", "sunscreen", "mask", "lotion", "balm", "cream",
    "wash", "gel",
]

INGREDIENT_PHRASES = [
    "vitamin c", "vitamin e", "alpha arbutin", "hyaluronic acid",
    "salicylic acid", "azelaic acid", "aha", "bha", "niacinamide",
    "ceramide", "ceramides", "cica", "probiotics", "zinc", "retinol",
    "rice water", "tea tree", "spf",
]

# Words with NO discriminating power — excluded from keyword extraction
# NOTE: fruit/flavour names like "strawberry", "blueberry" are NOT here
# because "Strawberry Brightening Serum" vs plain "Niacinamide Serum" need
# strawberry to be a distinguishing keyword
STOPWORDS = {
    "dot", "key", "with", "and", "for", "the", "face", "skin",
    "anti", "plus", "free", "mild", "daily", "gentle", "light",
    "repair", "boost", "hydrating", "lightweight", "intense",
    "oil", "foaming", "polish", "glow",
    "brightening", "clarifying", "sleeping", "concentrate",
    "radiance", "defense", "barrier", "hydrate",
    "pineapple", "walnut", "coffee", "charcoal", "shower", "body",
    "prone", "oily", "acne", "age", "night", "super", "bright",
    "liquid", "corrector", "spot", "milk", "tea", "green", "pack",
    "200", "100", "560", "50", "72", "hr", "hrs", "hour",
    "pa", "g", "ml",
}

# Fruit/flavour names kept as valid keywords — they distinguish product variants
FLAVOUR_KEYWORDS = {
    "strawberry", "blueberry", "chocolate", "watermelon",
    "pineapple", "coffee", "charcoal", "walnut",
}


# ─── Keyword extraction ───────────────────────────────────────────────────────

def extract_product_keywords(product_name: str) -> dict:
    """
    Extracts two sets of keywords:

    'required' — ALL must appear in the post title for it to be a match.
                 Includes: ingredient phrases, concentrations, form type,
                 and flavour/variant keywords (strawberry, blueberry etc.)

    'query'    — Top 2 keywords used for the Reddit search query.

    Examples:
      "Dot & Key 10% Niacinamide + Strawberry Brightening Face Serum"
        → required: ["niacinamide", "10%", "strawberry", "serum"]
        → query:    '"Dot & Key" niacinamide strawberry'

      "Dot & Key Cica & 10% Niacinamide Serum"
        → required: ["cica", "niacinamide", "10%", "serum"]
        → query:    '"Dot & Key" cica niacinamide'

      "Dot & Key 10% Vitamin C Serum With 5% Niacinamide"
        → required: ["vitamin c", "niacinamide", "10%", "serum"]
        → query:    '"Dot & Key" vitamin c niacinamide'
    """
    text = product_name.lower()
    text = re.sub(r"dot\s*&\s*key", "", text)
    text = re.sub(r"[+&()]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # 1. Ingredient phrases (multi-word, e.g. "vitamin c", "salicylic acid")
    found_phrases = [p for p in INGREDIENT_PHRASES if p in text]

    # 2. Percentage concentrations (e.g. "10%", "5%", "2%")
    concentrations = [c.replace(" ", "") for c in re.findall(r"\d+\s*%", text)]

    # 3. Flavour/variant keywords (e.g. "strawberry", "blueberry")
    #    These distinguish product variants with the same ingredients
    flavours = [f for f in FLAVOUR_KEYWORDS if f in text]

    # 4. Product form type (e.g. "serum", "toner", "wash")
    form_type = next((f for f in FORM_TYPES if f in text), None)

    # Build required: ingredients → concentrations → flavours → form type
    required = list(dict.fromkeys(found_phrases + concentrations + flavours))[:4]
    if form_type and form_type not in required:
        required.append(form_type)

    # Fallback for products with none of the above (e.g. "Barrier Repair Cream")
    if not required:
        words        = re.findall(r"[a-z]+", text)
        single_words = [w for w in words if len(w) > 3 and w not in STOPWORDS]
        required     = list(dict.fromkeys(single_words))[:3]
        if form_type and form_type not in required:
            required.append(form_type)

    # Query uses ingredient phrases + flavours (most specific and searchable)
    query_terms = list(dict.fromkeys(found_phrases + flavours + concentrations))[:2]
    if not query_terms:
        query_terms = required[:2]

    return {"required": required, "query_terms": query_terms}


# ─── Post title matching ──────────────────────────────────────────────────────

def post_title_matches(title: str, keyword_dict: dict) -> bool:
    """
    A post title must contain:
      1. "dot" or "key" (brand mention)
      2. ALL required keywords

    Requiring ALL keywords in the title ensures:
      - "Dot & Key niacinamide 10% serum" ✓ matches "10% Niacinamide Serum"
      - "Dot & Key niacinamide 10% serum" ✗ does NOT match "Strawberry Niacinamide Serum"
        because "strawberry" is required but absent from the title
      - "Minimalist niacinamide review" ✗ rejected (no brand)

    Title-level matching is reliable because post titles are short and specific —
    people writing about a product almost always name it precisely in the title.
    """
    text     = title.lower()
    required = keyword_dict["required"]

    # Brand must appear
    if "dot" not in text and "key" not in text:
        return False

    # ALL required keywords must appear in the title
    return all(kw in text for kw in required)


# ─── Reddit API ──────────────────────────────────────────────────────────────

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


def fetch_post_comments(permalink: str) -> tuple[str, list[dict]]:
    """
    Fetch a post's body and ALL its comments (including nested replies).
    Reddit returns [post_listing, comments_listing] as a 2-element array.
    """
    url  = f"https://www.reddit.com{permalink}.json?limit=500"
    data = reddit_get(url)

    if not data or not isinstance(data, list) or len(data) < 2:
        return "", []

    post_items = data[0].get("data", {}).get("children", [])
    post_body  = ""
    if post_items:
        post_body = post_items[0].get("data", {}).get("selftext", "")

    comments     = []
    comment_tree = data[1].get("data", {}).get("children", [])
    extract_comments_recursive(comment_tree, comments)

    return clean_body(post_body), comments


def extract_comments_recursive(children: list, result: list, depth: int = 0):
    """Flatten Reddit's nested comment tree into a single list."""
    if depth > 10:
        return
    for child in children:
        if child.get("kind") == "more":
            continue
        d    = child.get("data", {})
        body = d.get("body", "").strip()
        if body and body != "[deleted]" and body != "[removed]":
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


def clean_body(body: str) -> str:
    body = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)
    body = re.sub(r"[*_~`>#]+", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()[:MAX_BODY_LENGTH]


# ─── Database ─────────────────────────────────────────────────────────────────

def init_db(db_path="dotkey_reviews.db"):
    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL UNIQUE,
            brand      TEXT    DEFAULT 'Dot & Key',
            created_at TEXT    DEFAULT (datetime('now'))
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id    INTEGER NOT NULL REFERENCES products(id),
            source        TEXT,
            reviewer_name TEXT,
            review_title  TEXT,
            review_body   TEXT,
            review_date   TEXT,
            helpful_count INTEGER DEFAULT 0,
            url           TEXT,
            scraped_at    TEXT    DEFAULT (datetime('now'))
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_reviews_product ON reviews(product_id)")
    conn.commit()
    return conn


def upsert_product(conn, name: str) -> int:
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO products(name) VALUES(?)", (name,))
    conn.commit()
    cur.execute("SELECT id FROM products WHERE name=?", (name,))
    return cur.fetchone()[0]


def insert_review(conn, review: dict):
    conn.execute("""
        INSERT INTO reviews
            (product_id, source, reviewer_name, review_title,
             review_body, review_date, helpful_count, url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        review["product_id"], review.get("source", "reddit"),
        review.get("reviewer_name"), review.get("review_title", ""),
        review.get("review_body"), review.get("review_date"),
        review.get("helpful_count", 0), review.get("url"),
    ))
    conn.commit()


# ─── Per-product scraper ──────────────────────────────────────────────────────

def build_query(keyword_dict: dict) -> str:
    terms = keyword_dict["query_terms"]
    core  = " ".join(terms)
    return f'"Dot & Key" {core}'.strip()


def fetch_reddit_reviews(product_name: str, product_id_db: int, conn: sqlite3.Connection) -> int:
    keyword_dict = extract_product_keywords(product_name)
    query        = build_query(keyword_dict)
    encoded      = quote_plus(query)

    print(f"    Required : {keyword_dict['required']}")
    print(f"    Query    : {query}")

    seen_permalinks = set()
    total_saved     = 0

    def search_and_process(subreddit: str):
        nonlocal total_saved
        url  = (f"https://www.reddit.com/r/{subreddit}/search.json"
                f"?q={encoded}&restrict_sr=1&sort=relevance&type=link&limit=10")
        data  = reddit_get(url)
        posts = data.get("data", {}).get("children", []) if data else []

        matched = 0
        for post in posts:
            d         = post.get("data", {})
            title     = d.get("title", "")
            permalink = d.get("permalink", "")

            if not permalink or permalink in seen_permalinks:
                continue

            # ALL required keywords must be in the post title
            if not post_title_matches(title, keyword_dict):
                print(f"      ✗ Skipped: {title[:70]}")
                continue

            seen_permalinks.add(permalink)
            matched += 1
            post_url = f"https://reddit.com{permalink}"
            print(f"      ✓ Matched: {title[:70]}")

            post_body, comments = fetch_post_comments(permalink)
            time.sleep(DELAY_BETWEEN_CALLS)

            if post_body:
                insert_review(conn, {
                    "product_id":    product_id_db,
                    "source":        "reddit_post",
                    "reviewer_name": d.get("author", ""),
                    "review_title":  title,
                    "review_body":   post_body,
                    "review_date":   str(d.get("created_utc", "")),
                    "helpful_count": d.get("score", 0),
                    "url":           post_url,
                })
                total_saved += 1

            for comment in comments:
                insert_review(conn, {
                    "product_id":    product_id_db,
                    "source":        "reddit_comment",
                    "reviewer_name": comment["author"],
                    "review_title":  title,
                    "review_body":   comment["body"],
                    "review_date":   comment["created_utc"],
                    "helpful_count": comment["score"],
                    "url":           f"https://reddit.com{comment['permalink']}" if comment["permalink"] else post_url,
                })
                total_saved += 1

            print(f"        → {len(comments)} comments saved")

        return matched

    matched = search_and_process(PRIMARY_SUBREDDIT)
    time.sleep(DELAY_BETWEEN_CALLS)

    if matched == 0:
        print(f"      No matches in r/{PRIMARY_SUBREDDIT}, trying r/{FALLBACK_SUBREDDIT}...")
        search_and_process(FALLBACK_SUBREDDIT)
        time.sleep(DELAY_BETWEEN_CALLS)

    print(f"    → total saved: {total_saved}")
    return total_saved


# ─── Products ─────────────────────────────────────────────────────────────────

PRODUCTS = [
    "Dot & Key 10% Vitamin C Serum With 5% Niacinamide",
    "Dot & Key 10% Niacinamide + Strawberry Brightening Face Serum",
    "Dot & Key 10% Niacinamide Serum",
    "Dot & Key 10% Vitamin C+E Super Bright Face Serum",
    "Dot & Key 12% Barrier Boost Serum With Ceramides + Niacinamide",
    "Dot & Key 2% Salicylic Acid + Cica Anti Acne Face Serum With Zinc For Oily Acne Prone Skin",
    "Dot & Key 20% Vitamin C Serum",
    "Dot & Key 5% AHA Toner Skin Clarifying Liquid Exfoliant",
    "Dot & Key 72 Hour Hydrating Gel + Probiotics",
    "Dot & Key 72 Hr Hydrating Gel Moisturizer + Probiotics",
    "Dot & Key 72 Hrs Hydrating Moisturizer",
    "Dot & Key 72hr Hydrating Gel Moisturizer",
    "Dot & Key 72hr Hydrating Lightweight Gel Moisturizer",
    "Dot & Key AHA + BHA Hydro Peel Exfoliating Serum",
    "Dot & Key AHA BHA & Pineapple Foaming Face Wash",
    "Dot & Key Acne Spot Corrector",
    "Dot & Key Age Defense Night Glow Serum",
    "Dot & Key AHA Exfoliating Sleeping Mask",
    "Dot & Key Alpha Arbutin + Azelaic Biphasic Serum Radiance Concentrate",
    "Dot & Key Barrier Repair Hydrating Gentle Face Wash",
    "Dot & Key Barrier Repair Cream",
    "Dot & Key Barrier Repair Face Moisturizer With Ceramides",
    "Dot & Key Barrier Repair Facewash",
    "Dot & Key Barrier Repair Gentle Hydrating Face Wash",
    "Dot & Key Barrier Repair Hyaluronic Body Lotion",
    "Dot & Key Barrier Repair Hydrating Lip Balm SPF 50+",
    "Dot & Key Barrier Repair Intense Moisturizer With Ceramides",
    "Dot & Key Barrier Repair Moisturiser",
    "Dot & Key Barrier Repair Oil-free Moisturizer With Ceramides",
    "Dot & Key Barrier Repair Sunscreen SPF 50+ PA++++",
    "Dot & Key Blueberry Hydrate 12% Barrier Boost Face Serum",
    "Dot & Key Blueberry Hydrate Barrier Repair Milk Face Toner",
    "Dot & Key Blueberry Hydrate Barrier Repair Oil-free Moisturizer",
    "Dot & Key Body Lotion",
    "Dot & Key Booty Polish Walnut & Coffee",
    "Dot & Key Ceramides & Hyaluronic Barrier Repair Moisturizer With Probiotics & Rice Water",
    "Dot & Key Ceramides & Hyaluronic Hydrating Face Cream With Probiotic",
    "Dot & Key Charcoal Detox Mousse Clay Mask",
    "Dot & Key Chocolate Glow Mousse Face Mask",
    "Dot & Key Cica & 1% Salicylic Acid Shower Gel",
    "Dot & Key Cica & 10% Niacinamide Serum",
    "Dot & Key Cica & 2% Salicylic Face Wash With Green Tea & Tea Tree Oil",
    "Dot & Key Cica & Niacinamide Anti Acne Gel Face Pack",
]


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    db_path = "dotkey_reviews.db"
    conn    = init_db(db_path)
    print(f"Database initialised → {db_path}\n")

    for product_name in PRODUCTS:
        print(f"\n{'='*60}")
        print(f"Product : {product_name}")
        product_id_db = upsert_product(conn, product_name)
        fetch_reddit_reviews(product_name, product_id_db, conn)

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM reviews")
    total = cur.fetchone()[0]
    print(f"\n{'='*60}")
    print(f"Done! {total} rows stored in {db_path}")

    cur.execute("""
        SELECT p.name, r.source, r.reviewer_name, r.review_title,
               r.review_body, r.review_date, r.helpful_count, r.url
        FROM reviews r
        JOIN products p ON p.id = r.product_id
        ORDER BY p.name, r.review_date DESC
    """)
    with open("dotkey_reviews_export.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Product", "Source", "Reviewer", "Title", "Body", "Date", "Upvotes", "URL"])
        w.writerows(cur.fetchall())
    print("CSV export → dotkey_reviews_export.csv")
    conn.close()


if __name__ == "__main__":
    main()