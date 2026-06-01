import sqlite3
import csv
import time
import re
import os
import requests
from urllib.parse import quote_plus

# ─── Config ───────────────────────────────────────────────────────────────────

# Get your free API key at: https://console.developers.google.com
# Enable "YouTube Data API v3" for your project
# Paste the key below or set it as an environment variable YOUTUBE_API_KEY
YOUTUBE_API_KEY = "AIzaSyBBY3is5OLbBwEodDkqxmupElnX25PV43g"

YOUTUBE_SEARCH_URL  = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL  = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_COMMENTS_URL = "https://www.googleapis.com/youtube/v3/commentThreads"

MAX_VIDEOS_PER_PRODUCT  = 5    # top N review videos to fetch
MAX_COMMENTS_PER_VIDEO  = 50   # top comments per video
DELAY_BETWEEN_CALLS     = 1    # seconds between API calls


# ─── YouTube API helpers ──────────────────────────────────────────────────────

def yt_get(url: str, params: dict) -> dict:
    """Make one YouTube API call. Returns parsed JSON or {} on error."""
    params["key"] = YOUTUBE_API_KEY
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"    [YouTube] API error: {e}")
        return {}


def search_review_videos(product_name: str) -> list[dict]:
    """
    Search YouTube for review videos of the product.
    Returns list of dicts with video_id, title, channel, published_at, view_count.
    """
    query  = f"Dot & Key {product_name.replace('Dot & Key', '').strip()} review"
    params = {
        "part":       "snippet",
        "q":          query,
        "type":       "video",
        "maxResults": MAX_VIDEOS_PER_PRODUCT,
        "order":      "relevance",
        "relevanceLanguage": "en",
        "regionCode": "IN",       # India — most Dot & Key reviews are Indian
    }
    data  = yt_get(YOUTUBE_SEARCH_URL, params)
    items = data.get("items", [])

    if not items:
        return []

    # Fetch view counts in a single batch call
    video_ids = [item["id"]["videoId"] for item in items if item.get("id", {}).get("videoId")]
    stats     = fetch_video_stats(video_ids)

    videos = []
    for item in items:
        vid_id = item.get("id", {}).get("videoId")
        if not vid_id:
            continue
        snippet = item.get("snippet", {})
        videos.append({
            "video_id":     vid_id,
            "title":        snippet.get("title", ""),
            "channel":      snippet.get("channelTitle", ""),
            "published_at": snippet.get("publishedAt", ""),
            "url":          f"https://www.youtube.com/watch?v={vid_id}",
            "view_count":   stats.get(vid_id, {}).get("viewCount", 0),
            "like_count":   stats.get(vid_id, {}).get("likeCount", 0),
            "description":  snippet.get("description", "")[:500],
        })

    time.sleep(DELAY_BETWEEN_CALLS)
    return videos


def fetch_video_stats(video_ids: list[str]) -> dict:
    """Batch fetch view/like counts for a list of video IDs."""
    if not video_ids:
        return {}
    params = {
        "part": "statistics",
        "id":   ",".join(video_ids),
    }
    data  = yt_get(YOUTUBE_VIDEOS_URL, params)
    stats = {}
    for item in data.get("items", []):
        vid_id = item["id"]
        s      = item.get("statistics", {})
        stats[vid_id] = {
            "viewCount": int(s.get("viewCount", 0)),
            "likeCount": int(s.get("likeCount", 0)),
        }
    return stats


def fetch_video_comments(video_id: str, max_comments: int = 50) -> list[dict]:
    """
    Fetch top comments for a video, sorted by relevance.
    Returns list of comment dicts.
    """
    comments = []
    params   = {
        "part":       "snippet",
        "videoId":    video_id,
        "order":      "relevance",   # top/most-relevant comments first
        "maxResults": min(max_comments, 100),   # API max per page is 100
        "textFormat": "plainText",
    }

    while len(comments) < max_comments:
        data  = yt_get(YOUTUBE_COMMENTS_URL, params)
        items = data.get("items", [])

        if not items:
            break

        for item in items:
            top = item.get("snippet", {}).get("topLevelComment", {})
            s   = top.get("snippet", {})
            comments.append({
                "comment_id":   top.get("id", ""),
                "author":       s.get("authorDisplayName", ""),
                "text":         s.get("textDisplay", ""),
                "like_count":   s.get("likeCount", 0),
                "published_at": s.get("publishedAt", ""),
                "reply_count":  item.get("snippet", {}).get("totalReplyCount", 0),
            })

        # Paginate if needed and more comments available
        next_page = data.get("nextPageToken")
        if not next_page or len(comments) >= max_comments:
            break
        params["pageToken"] = next_page
        time.sleep(DELAY_BETWEEN_CALLS)

    return comments[:max_comments]


# ─── Database ─────────────────────────────────────────────────────────────────

def init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()

    # Extend existing products table (created by Reddit scraper) or create fresh
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL UNIQUE,
            brand      TEXT    DEFAULT 'Dot & Key',
            created_at TEXT    DEFAULT (datetime('now'))
        )
    """)

    # YouTube-specific tables
    cur.execute("""
        CREATE TABLE IF NOT EXISTS yt_videos (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id   INTEGER NOT NULL REFERENCES products(id),
            video_id     TEXT    NOT NULL UNIQUE,
            title        TEXT,
            channel      TEXT,
            published_at TEXT,
            url          TEXT,
            view_count   INTEGER DEFAULT 0,
            like_count   INTEGER DEFAULT 0,
            description  TEXT,
            scraped_at   TEXT DEFAULT (datetime('now'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS yt_comments (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id     TEXT    NOT NULL REFERENCES yt_videos(video_id),
            product_id   INTEGER NOT NULL REFERENCES products(id),
            comment_id   TEXT    UNIQUE,
            author       TEXT,
            text         TEXT,
            like_count   INTEGER DEFAULT 0,
            reply_count  INTEGER DEFAULT 0,
            published_at TEXT,
            scraped_at   TEXT DEFAULT (datetime('now'))
        )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_yt_comments_product ON yt_comments(product_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_yt_videos_product   ON yt_videos(product_id)")
    conn.commit()
    return conn


def upsert_product(conn, name: str) -> int:
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO products(name) VALUES(?)", (name,))
    conn.commit()
    cur.execute("SELECT id FROM products WHERE name=?", (name,))
    return cur.fetchone()[0]


def insert_video(conn, product_id: int, video: dict) -> bool:
    """Insert video row. Returns False if already exists (skip comments too)."""
    try:
        conn.execute("""
            INSERT OR IGNORE INTO yt_videos
                (product_id, video_id, title, channel, published_at,
                 url, view_count, like_count, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            product_id, video["video_id"], video["title"], video["channel"],
            video["published_at"], video["url"], video["view_count"],
            video["like_count"], video["description"],
        ))
        conn.commit()
        return conn.execute(
            "SELECT changes()"
        ).fetchone()[0] > 0   # True = newly inserted
    except Exception as e:
        print(f"    [DB] Video insert error: {e}")
        return False


def insert_comment(conn, product_id: int, video_id: str, comment: dict):
    try:
        conn.execute("""
            INSERT OR IGNORE INTO yt_comments
                (video_id, product_id, comment_id, author, text,
                 like_count, reply_count, published_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            video_id, product_id,
            comment["comment_id"], comment["author"], comment["text"],
            comment["like_count"], comment["reply_count"], comment["published_at"],
        ))
        conn.commit()
    except Exception as e:
        print(f"    [DB] Comment insert error: {e}")


# ─── Per-product scraper ──────────────────────────────────────────────────────

def fetch_youtube_reviews(product_name: str, product_id: int, conn: sqlite3.Connection):
    print(f"    [YouTube] Searching videos for: {product_name}")

    videos = search_review_videos(product_name)
    if not videos:
        print("    [YouTube] No videos found.")
        return

    total_comments = 0
    for i, video in enumerate(videos, 1):
        print(f"    Video {i}/{len(videos)}: {video['title'][:60]}...")
        print(f"             Views: {video['view_count']:,}  |  {video['url']}")

        is_new = insert_video(conn, product_id, video)

        # Fetch comments (even if video existed, comments may be new)
        comments = fetch_video_comments(video["video_id"], MAX_COMMENTS_PER_VIDEO)
        for comment in comments:
            insert_comment(conn, product_id, video["video_id"], comment)

        total_comments += len(comments)
        print(f"             → {len(comments)} comments fetched")
        time.sleep(DELAY_BETWEEN_CALLS)

    print(f"    [YouTube] Total: {len(videos)} videos, {total_comments} comments")


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
    if YOUTUBE_API_KEY == "YOUR_API_KEY_HERE":
        print("ERROR: Set your YouTube API key in the script or via:")
        print("  export YOUTUBE_API_KEY='your_key_here'")
        return

    # Shares the same DB as the Reddit scraper — all data in one place
    db_path = "dotkey_reviews.db"
    conn    = init_db(db_path)
    print(f"Database: {db_path}")
    print(f"Fetching top {MAX_VIDEOS_PER_PRODUCT} videos × {MAX_COMMENTS_PER_VIDEO} comments per product\n")

    for product_name in PRODUCTS:
        print(f"\n{'='*60}")
        print(f"Product : {product_name}")
        product_id = upsert_product(conn, product_name)
        fetch_youtube_reviews(product_name, product_id, conn)

    # ── Summary ───────────────────────────────────────────────────
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM yt_videos")
    total_videos = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM yt_comments")
    total_comments = cur.fetchone()[0]
    print(f"\n{'='*60}")
    print(f"Done! {total_videos} videos, {total_comments} comments stored in {db_path}")

    # ── CSV export: videos ─────────────────────────────────────────
    cur.execute("""
        SELECT p.name, v.title, v.channel, v.view_count, v.like_count,
               v.published_at, v.url, v.description
        FROM yt_videos v
        JOIN products p ON p.id = v.product_id
        ORDER BY p.name, v.view_count DESC
    """)
    with open("dotkey_yt_videos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Product", "Video Title", "Channel", "Views", "Likes",
                    "Published", "URL", "Description"])
        w.writerows(cur.fetchall())
    print("CSV export → dotkey_yt_videos.csv")

    # ── CSV export: comments ───────────────────────────────────────
    cur.execute("""
        SELECT p.name, v.title, v.channel, c.author, c.text,
               c.like_count, c.reply_count, c.published_at
        FROM yt_comments c
        JOIN yt_videos  v ON v.video_id   = c.video_id
        JOIN products   p ON p.id         = c.product_id
        ORDER BY p.name, v.view_count DESC, c.like_count DESC
    """)
    with open("dotkey_yt_comments.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Product", "Video Title", "Channel", "Commenter",
                    "Comment", "Likes", "Replies", "Published"])
        w.writerows(cur.fetchall())
    print("CSV export → dotkey_yt_comments.csv")
    conn.close()


if __name__ == "__main__":
    main()