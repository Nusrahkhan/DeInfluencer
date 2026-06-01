import requests
import sqlite3
import csv
import time
import re
from urllib.parse import quote_plus


# ─── Config ───────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; The-OrdinaryReviewBot/1.0)",
    "Accept": "application/json",
}

# Subreddits to search — ordered by relevance
SUBREDDITS = [
    "SkincareAddiction",
    "IndianSkincareAddicts",
    "AsianBeauty",
    "beauty",
    "MakeupAddiction",
]

MAX_BODY_LENGTH     = 5000
DELAY_BETWEEN_CALLS = 2   # seconds between Reddit API calls

# Broad queries to catch all The Ordinary product discussions — no product classification
SEARCH_QUERIES = [
    '"The Ordinary" review',
    '"The Ordinary" water sleeping mask',
    '"The Ordinary" lip sleeping mask',
    '"The Ordinary" toner',
    '"The Ordinary" cleanser',
    '"The Ordinary" cream skin',
]


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
    """Fetch a post's body and all its comments including nested replies."""
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

def init_db(db_path: str = "the_ordinary_reviews.db") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    # No product table — classification happens later during cleaning
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
            url           TEXT    UNIQUE,   -- deduplication key
            scraped_at    TEXT    DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_url ON reviews(url)")
    conn.commit()
    return conn


def insert_review(conn: sqlite3.Connection, review: dict) -> bool:
    """Insert a review. Returns False if URL already exists (duplicate)."""
    try:
        conn.execute("""
            INSERT INTO reviews
                (source, subreddit, reviewer_name, review_title,
                 review_body, review_date, helpful_count, url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            review.get("source"),
            review.get("subreddit"),
            review.get("reviewer_name"),
            review.get("review_title", ""),
            review.get("review_body"),
            review.get("review_date"),
            review.get("helpful_count", 0),
            review.get("url"),
        ))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # duplicate URL — skip silently


# ─── Core scraper ─────────────────────────────────────────────────────────────

def scrape_subreddit(subreddit: str, query: str, conn: sqlite3.Connection) -> int:
    """Search one subreddit for one query and save all the ordinary posts + comments."""
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

        # Sanity check — must actually mention the ordinary
        if "the ordinary" not in title.lower():
            print(f"      ✗ Skipped: {title[:70]}")
            continue

        post_url = f"https://reddit.com{permalink}"
        print(f"      ✓ Matched: {title[:70]}")

        post_body, comments = fetch_post_comments(permalink)
        time.sleep(DELAY_BETWEEN_CALLS)

        # Save the post body
        if post_body:
            if insert_review(conn, {
                "source":        "reddit_post",
                "subreddit":     subreddit,
                "reviewer_name": d.get("author", ""),
                "review_title":  title,
                "review_body":   post_body,
                "review_date":   str(d.get("created_utc", "")),
                "helpful_count": d.get("score", 0),
                "url":           post_url,
            }):
                saved += 1

        # Save every comment
        for comment in comments:
            comment_url = (
                f"https://reddit.com{comment['permalink']}"
                if comment["permalink"] else post_url
            )
            if insert_review(conn, {
                "source":        "reddit_comment",
                "subreddit":     subreddit,
                "reviewer_name": comment["author"],
                "review_title":  title,
                "review_body":   comment["body"],
                "review_date":   comment["created_utc"],
                "helpful_count": comment["score"],
                "url":           comment_url,
            }):
                saved += 1

        print(f"        → {len(comments)} comments | {saved} new rows this query")

    return saved


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    db_path = "the_ordinary_reviews.db"
    conn    = init_db(db_path)
    print(f"Database initialised → {db_path}")
    print(f"Scraping {len(SUBREDDITS)} subreddits × {len(SEARCH_QUERIES)} queries\n")

    total_saved = 0

    for subreddit in SUBREDDITS:
        print(f"\n{'='*60}")
        print(f"Subreddit : r/{subreddit}")

        for query in SEARCH_QUERIES:
            print(f"\n  Query: {query}")
            saved        = scrape_subreddit(subreddit, query, conn)
            total_saved += saved
            print(f"  → {saved} new rows saved")
            time.sleep(DELAY_BETWEEN_CALLS)

    # ── Summary ──
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM reviews")
    total_in_db = cur.fetchone()[0]
    print(f"\n{'='*60}")
    print(f"Done!  {total_in_db} total rows in DB  ({total_saved} newly added this run)")

    # ── CSV export — no Product column, ready for manual classification later ──
    cur.execute("""
        SELECT source, subreddit, reviewer_name, review_title,
               review_body, review_date, helpful_count, url
        FROM reviews
        ORDER BY review_date DESC
    """)
    csv_path = "the_ordinary_reviews_export.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Source", "Subreddit", "Reviewer", "Title", "Body", "Date", "Upvotes", "URL"])
        w.writerows(cur.fetchall())
    print(f"CSV export → {csv_path}")
    conn.close()


if __name__ == "__main__":
    main()