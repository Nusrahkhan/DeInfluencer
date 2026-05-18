"""
Reddit Product Comment Scraper
Scrapes top 100 posts + comments about a given skincare/makeup product.
Uses Reddit's built-in JSON API — no API key, no Selenium needed.
"""

import requests
import time
import json
from datetime import datetime
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ProductScraper/1.0)",
    "Accept": "application/json",
}

SKINCARE_SUBREDDITS = [
    "IndianSkincareAddicts",
    "SkincareAddiction",
    "MakeupAddiction",
    "Sephora",
    "AsianBeauty",
    "beauty",
]


def fetch_reddit_posts(product_name: str, subreddit: str, limit: int = 25) -> list:
    """Fetch posts from a subreddit matching the product name."""
    url = f"https://www.reddit.com/r/{subreddit}/search.json"
    params = {
        "q": f'"{product_name}"',        
        "restrict_sr": "on",   # search only this subreddit
        "sort": "relevance",
        "limit": limit,
        "type": "link",
    }
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=10)
        if resp.status_code == 429:
            print("    [Reddit] Rate limited — sleeping 60s...")
            time.sleep(60)
            resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        posts = data.get("data", {}).get("children", [])
        return [p["data"] for p in posts]
    except Exception as e:
        print(f"  [!] Error fetching posts from r/{subreddit}: {e}")
        return []


def fetch_comments(post: dict, max_comments: int = 10) -> list:
    """Fetch top-level comments for a given post."""
    # Reddit JSON API: append .json to any post URL
    post_id = post.get("id", "")
    subreddit = post.get("subreddit", "")
    url = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}.json"
    params = {"limit": max_comments, "depth": 1, "sort": "top"}
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=10)
        if resp.status_code == 429:
            print("    [Reddit] Rate limited — sleeping 60s...")
            time.sleep(60)
            resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        # data[1] contains the comments listing
        comments_listing = data[1]["data"]["children"]
        comments = []
        for c in comments_listing:
            if c["kind"] != "t1":   # t1 = comment
                continue
            cd = c["data"]
            comments.append({
                "source":    "reddit_comment",
                "subreddit": subreddit,
                "title":     post.get("title", ""),
                "body":      cd.get("body", "").strip(),
                "author":    cd.get("author", "[deleted]"),
                "score":     cd.get("score", 0),
                "date":      datetime.utcfromtimestamp(cd.get("created_utc", 0)).strftime("%Y-%m-%d"),
                "url":       f"https://www.reddit.com{cd.get('permalink', '')}",
            })
        return comments
    except Exception as e:
        print(f"  [!] Error fetching comments for post {post_id}: {e}")
        return []

def normalize(text):
    return re.sub(r"\s+", " ", text.lower()).strip()

def scrape_product_reviews(product_name: str, target: int = 100) -> list:
    """
    Main function. Given a product name, returns up to `target` records
    (posts + comments) from skincare/makeup subreddits.

    Each record has the shape:
        {
            "source":    "reddit_comment",
            "subreddit": str,
            "title":     str,
            "body":      str,
            "author":    str,
            "score":     int,
            "date":      str,   # YYYY-MM-DD
            "url":       str,
        }
    """
    results = []
    seen_ids = set()   # deduplicate by post/comment URL

    print(f"\n🔍 Searching Reddit for: '{product_name}'")
    print(f"   Target: {target} records\n")

    for subreddit in SKINCARE_SUBREDDITS:
        if len(results) >= target:
            break

        print(f"  → r/{subreddit} ...")
        posts = fetch_reddit_posts(product_name, subreddit, limit=10)
        print(f"     Found {len(posts)} posts mentioning '{product_name}'")

        for post in posts:
            title_norm = normalize(post.get("title", ""))
            body_norm  = normalize(post.get("selftext", ""))
            product_norm = normalize(product_name)
            print(title_norm)
            print(body_norm)
            print(product_norm)

            if product_norm not in title_norm and product_norm not in body_norm:
                continue

            if len(results) >= target:
                break

            post_url = f"https://www.reddit.com{post.get('permalink', '')}"

            # ── 1. Add the post itself as a record ──────────────────────
            if post_url not in seen_ids:
                seen_ids.add(post_url)
                body = post.get("selftext", "").strip() or post.get("title", "")
                record = {
                    "source":    "reddit_comment",
                    "subreddit": post.get("subreddit", subreddit),
                    "title":     post.get("title", ""),
                    "body":      body,
                    "author":    post.get("author", "[deleted]"),
                    "score":     post.get("score", 0),
                    "date":      datetime.utcfromtimestamp(
                                     post.get("created_utc", 0)
                                 ).strftime("%Y-%m-%d"),
                    "url":       post_url,
                }
                results.append(record)
                print(f"     [post]    {post.get('title', '')[:60]}")

            # ── 2. Fetch comments for this post ─────────────────────────
            time.sleep(1)   # be polite to Reddit's servers
            comments = fetch_comments(post, max_comments=10)
            for comment in comments:
                if len(results) >= target:
                    break
                if comment["url"] not in seen_ids:
                    seen_ids.add(comment["url"])
                    results.append(comment)

            print(f"     [comments] +{len(comments)} | total so far: {len(results)}")

        time.sleep(1.5)   # pause between subreddits

    print(f"\n✅ Done! Collected {len(results)} records for '{product_name}'.")
    return results[:target]


# ── CLI / demo ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    product = "Simple Face Wash"
    product_norm = normalize(product)
    records = scrape_product_reviews(product_norm, target=60)
    

    # Save to JSON
    out_file = f"{product.replace(' ', '_').lower()}_reddit.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    print(f"\n💾 Saved {len(records)} records → {out_file}")

    # Preview first 3
    print("\n── Preview (first 3 records) ──")
    for r in records[:3]:
        print(json.dumps(r, indent=2))