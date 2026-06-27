"""
Reddit Product Scraper — Arctic-Shift Version
Uses arctic-shift.photon-reddit.com (free Reddit archive API, no auth needed)
Docs: https://github.com/ArthurHeitmann/arctic_shift/blob/master/api/README.md
"""

import requests
import time
import csv
import re
from datetime import datetime

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
BASE_URL = "https://arctic-shift.photon-reddit.com/api"

SKINCARE_SUBREDDITS = [
    "IndianSkincareAddicts", "SkincareAddiction",
    "MakeupAddiction", "Sephora", "AsianBeauty", "beauty", "IndianMakeupAddicts"
]

MAX_RETRIES = 3
RETRY_BACKOFF = 5  # seconds, doubles each retry


def normalize(text):
    return re.sub(r"\s+", " ", text.lower()).strip()


def safe_get(url, params, max_retries=MAX_RETRIES):
    """GET with retry/backoff so a single flaky call doesn't kill the run."""
    delay = RETRY_BACKOFF
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"     [!] Attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                time.sleep(delay)
                delay *= 2
    return None


def fetch_posts(product_name: str, subreddit: str, limit: int = 25) -> list:
    """
    Arctic-Shift submission search.
    Searching 'title' covers most product-mention cases; selftext search
    is slower/limited, so we filter selftext locally after fetching.
    """
    url = f"{BASE_URL}/posts/search"
    params = {
        "title": product_name,
        "subreddit": subreddit,
        "limit": limit,
        "sort": "desc",
    }
    data = safe_get(url, params)
    if data is None:
        return []
    return data.get("data", [])


def fetch_comments(post_id: str, subreddit: str, post_title: str, limit: int = 10) -> list:
    """
    Arctic-Shift comment search scoped to a specific submission via link_id.
    Arctic-Shift expects link_id as the base36 post id (no t3_ prefix needed,
    but it's tolerated if present).
    """
    url = f"{BASE_URL}/comments/search"
    params = {
        "link_id": post_id,
        "limit": limit,
        "sort": "desc",
    }
    data = safe_get(url, params)
    if data is None:
        return []

    raw = data.get("data", [])
    comments = []
    for c in raw:
        comments.append({
            "source":    "reddit_comment",
            "subreddit": subreddit,
            "title":     post_title,
            "body":      (c.get("body") or "").strip(),
            "author":    c.get("author", "[deleted]"),
            "score":     c.get("score", 0),
            "date":      datetime.utcfromtimestamp(
                             c.get("created_utc", 0)
                         ).strftime("%Y-%m-%d"),
            "url":       f"https://reddit.com/r/{subreddit}/comments/{post_id}",
        })
    return comments


def scrape_product_reviews(product_name: str, target: int = 100) -> list:
    results  = []
    seen_ids = set()
    product_norm = normalize(product_name)

    print(f"\n🔍 Searching Reddit (via Arctic-Shift) for: '{product_name}'")
    print(f"   Target: {target} records\n")

    for subreddit in SKINCARE_SUBREDDITS:
        if len(results) >= target:
            break

        print(f"  → r/{subreddit} ...")
        posts = fetch_posts(product_name, subreddit, limit=10)
        print(f"     Found {len(posts)} posts")

        for post in posts:
            if len(results) >= target:
                break

            title_norm = normalize(post.get("title", ""))
            body_norm  = normalize(post.get("selftext", "") or "")
            if product_norm not in title_norm and product_norm not in body_norm:
                continue

            post_id  = post.get("id", "")
            post_url = f"https://reddit.com/r/{subreddit}/comments/{post_id}"

            # 1. Add post itself
            if post_url not in seen_ids:
                seen_ids.add(post_url)
                results.append({
                    "source":    "reddit_comment",
                    "subreddit": post.get("subreddit", subreddit),
                    "title":     post.get("title", ""),
                    "body":      (post.get("selftext") or "").strip() or post.get("title", ""),
                    "author":    post.get("author", "[deleted]"),
                    "score":     post.get("score", 0),
                    "date":      datetime.utcfromtimestamp(
                                     post.get("created_utc", 0)
                                 ).strftime("%Y-%m-%d"),
                    "url":       post_url,
                })
                print(f"     [post] {post.get('title', '')[:60]}")

            # 2. Fetch comments
            time.sleep(0.5)  # Arctic-Shift is generally faster/laxer than pullpush was
            comments = fetch_comments(post_id, subreddit, post.get("title", ""), limit=10)
            for comment in comments:
                if len(results) >= target:
                    break
                if comment["url"] not in seen_ids:
                    seen_ids.add(comment["url"])
                    results.append(comment)

            print(f"     [comments] +{len(comments)} | total: {len(results)}")

        time.sleep(0.8)

    print(f"\n✅ Done! Collected {len(results)} records for '{product_name}'.")
    return results[:target]


CSV_FIELDS = ["source", "subreddit", "title", "body", "reviewer", "upvotes", "date", "url"]


def save_to_csv(records: list, out_file: str):
    with open(out_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in records:
            writer.writerow(row)


if __name__ == "__main__":
    product = "Klairs Vitamin C Serum"
    records = scrape_product_reviews(product, target=120)

    out_file = f"{product.replace(' ', '_').lower()}_reddit.csv"
    save_to_csv(records, out_file)
    print(f"\n💾 Saved {len(records)} records → {out_file}")