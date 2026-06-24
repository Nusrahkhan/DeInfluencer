"""
Reddit Product Scraper — No API Key Version
Uses pullpush.io (free Reddit archive API, no auth needed)
"""

import requests
import time
import json
import re
from datetime import datetime

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

SKINCARE_SUBREDDITS = [
    "IndianSkincareAddicts", "SkincareAddiction",
    "MakeupAddiction", "Sephora", "AsianBeauty", "beauty",
]

def normalize(text):
    return re.sub(r"\s+", " ", text.lower()).strip()

def fetch_posts(product_name: str, subreddit: str, limit: int = 25) -> list:
    url = "https://api.pullpush.io/reddit/search/submission/"
    params = {
        "q": product_name,
        "subreddit": subreddit,
        "size": limit,
        "sort_type": "score",
        "sort": "desc",
    }
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json().get("data", [])
    except Exception as e:
        print(f"  [!] Error fetching posts from r/{subreddit}: {e}")
        return []

def fetch_comments(post_id: str, subreddit: str, post_title: str, limit: int = 10) -> list:
    url = "https://api.pullpush.io/reddit/search/comment/"
    params = {"link_id": post_id, "size": limit, "sort_type": "score", "sort": "desc"}
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        raw = resp.json().get("data", [])
        comments = []
        for c in raw:
            comments.append({
                "source":    "reddit_comment",
                "subreddit": subreddit,
                "title":     post_title,
                "body":      c.get("body", "").strip(),
                "author":    c.get("author", "[deleted]"),
                "score":     c.get("score", 0),
                "date":      datetime.utcfromtimestamp(
                                 c.get("created_utc", 0)
                             ).strftime("%Y-%m-%d"),
                "url":       f"https://reddit.com/r/{subreddit}/comments/{post_id}",
            })
        return comments
    except Exception as e:
        print(f"  [!] Error fetching comments for {post_id}: {e}")
        return []

def scrape_product_reviews(product_name: str, target: int = 100) -> list:
    results  = []
    seen_ids = set()
    product_norm = normalize(product_name)

    print(f"\n🔍 Searching Reddit for: '{product_name}'")
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
            body_norm  = normalize(post.get("selftext", ""))
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
                    "body":      post.get("selftext", "").strip() or post.get("title", ""),
                    "author":    post.get("author", "[deleted]"),
                    "score":     post.get("score", 0),
                    "date":      datetime.utcfromtimestamp(
                                     post.get("created_utc", 0)
                                 ).strftime("%Y-%m-%d"),
                    "url":       post_url,
                })
                print(f"     [post] {post.get('title', '')[:60]}")

            # 2. Fetch comments
            time.sleep(0.8)
            comments = fetch_comments(post_id, subreddit, post.get("title", ""), limit=10)
            for comment in comments:
                if len(results) >= target:
                    break
                if comment["url"] not in seen_ids:
                    seen_ids.add(comment["url"])
                    results.append(comment)

            print(f"     [comments] +{len(comments)} | total: {len(results)}")

        time.sleep(1.0)

    print(f"\n✅ Done! Collected {len(results)} records for '{product_name}'.")
    return results[:target]


if __name__ == "__main__":
    product = "aqualogica detan sunscreen"
    records = scrape_product_reviews(product, target=60)

    out_file = f"{product.replace(' ', '_').lower()}_reddit.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Saved {len(records)} records → {out_file}")