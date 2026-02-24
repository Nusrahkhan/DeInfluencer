import requests
import json
import csv
import time
import re

# ─── Product List ─────────────────────────────────────────────────────────────
# Each entry: (product_key, search_terms_for_reddit)
# search_terms are short unique identifiers used in the Reddit search query.
# We keep them distinct enough so results don't bleed across products.

DOT_KEY_PRODUCTS = [
    ("10% Vitamin C Serum With 5% Niacinamide",          "dot key vitamin C niacinamide serum"),
    ("10% Niacinamide Strawberry Brightening Serum",     "dot key strawberry niacinamide brightening serum"),
    ("10% Niacinamide Serum",                            "dot key 10% niacinamide serum"),
    ("10% Vitamin C+E Super Bright Face Serum",          "dot key vitamin C+E super bright serum"),
    ("12% Barrier Boost Serum Ceramides Niacinamide",    "dot key 12% barrier boost serum ceramides"),
    ("2% Salicylic Acid Cica Anti Acne Serum Zinc",      "dot key salicylic acid cica acne serum zinc"),
    ("20% Vitamin C Serum",                              "dot key 20% vitamin C serum"),
    ("5% AHA Toner Skin Clarifying Exfoliant",           "dot key AHA toner skin clarifying"),
    ("72 Hour Hydrating Gel Probiotics",                 "dot key 72 hour hydrating gel probiotics"),
    ("72hr Hydrating Lightweight Gel Moisturizer",       "dot key 72hr hydrating gel moisturizer"),
    ("AHA BHA Hydro Peel Exfoliating Serum",             "dot key AHA BHA hydro peel serum"),
    ("AHA BHA Pineapple Foaming Face Wash",              "dot key pineapple foaming face wash"),
    ("Acne Spot Corrector",                              "dot key acne spot corrector"),
    ("Age Defense Night Glow Serum",                     "dot key age defense night glow serum"),
    ("AHA Exfoliating Sleeping Mask",                    "dot key AHA exfoliating sleeping mask"),
    ("Alpha Arbutin Azelaic Biphasic Serum",             "dot key alpha arbutin azelaic biphasic serum"),
    ("Barrier Repair Hydrating Gentle Face Wash",        "dot key barrier repair face wash"),
    ("Barrier Repair Cream",                             "dot key barrier repair cream ceramides"),
    ("Barrier Repair Face Moisturizer Ceramides",        "dot key barrier repair moisturizer ceramides"),
    ("Barrier Repair Hyaluronic Body Lotion",            "dot key barrier repair body lotion"),
    ("Barrier Repair Lip Balm SPF 50+",                  "dot key barrier repair lip balm SPF"),
    ("Barrier Repair Intense Moisturizer Ceramides",     "dot key barrier repair intense moisturizer"),
    ("Barrier Repair Oil-free Moisturizer Ceramides",    "dot key barrier repair oil free moisturizer"),
    ("Barrier Repair Sunscreen SPF 50+ PA++++",          "dot key barrier repair sunscreen SPF 50"),
    ("Blueberry Hydrate Barrier Boost Serum 7 Ceramides","dot key blueberry hydrate serum ceramides"),
    ("Blueberry Hydrate Barrier Repair Milk Toner",      "dot key blueberry hydrate milk toner"),
    ("Blueberry Hydrate Oil-free Moisturizer",           "dot key blueberry hydrate oil free moisturizer"),
    ("Booty Polish Walnut Coffee",                       "dot key booty polish walnut coffee"),
    ("Ceramides Hyaluronic Barrier Repair Moisturizer",  "dot key ceramides hyaluronic barrier repair"),
    ("Charcoal Detox Mousse Clay Mask",                  "dot key charcoal detox mousse mask"),
    ("Chocolate Glow Mousse Face Mask",                  "dot key chocolate glow mousse mask"),
    ("Cica 1% Salicylic Acid Shower Gel",                "dot key cica salicylic acid shower gel"),
    ("Cica 10% Niacinamide Serum",                       "dot key cica niacinamide serum"),
    ("Cica 2% Salicylic Face Wash Green Tea",            "dot key cica salicylic face wash green tea"),
    ("Cica Niacinamide Anti Acne Gel Face Pack",         "dot key cica niacinamide anti acne gel pack"),
]

SUBREDDITS = [
    "IndianSkincareAddicts",
    "SkincareAddiction",
    "AsianBeauty",
    "IndianBeautyDeals",
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; skincare-research-bot/1.0)',
    'Accept': 'application/json',
}

MAX_THREADS_PER_PRODUCT = 5    # search results to check per subreddit
MAX_COMMENTS_PER_THREAD = 20   # top comments to keep per thread


# ─── Relevance Check ──────────────────────────────────────────────────────────

def is_dot_key_relevant(text: str, product_key: str) -> bool:
    """
    Returns True only if the text explicitly mentions 'dot' and 'key'
    together (case-insensitive). This is the hard gate — if a post/comment
    doesn't say 'dot & key', 'dot n key', 'dot and key', we skip it entirely.
    """
    text_lower = text.lower()
    brand_mentioned = bool(re.search(r'dot\s*[&nand]+\s*key|dotnkey|dot\.key', text_lower))
    return brand_mentioned


# ─── Reddit Search ────────────────────────────────────────────────────────────

def search_threads(search_query: str, subreddit: str) -> list[dict]:
    """Use Reddit JSON search API. Returns raw post data."""
    url = (
        f"https://www.reddit.com/r/{subreddit}/search.json"
        f"?q={requests.utils.quote(search_query)}&restrict_sr=1&sort=relevance&limit={MAX_THREADS_PER_PRODUCT}"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        posts = r.json().get("data", {}).get("children", [])
        return [p["data"] for p in posts]
    except Exception as e:
        print(f"      [Search error] r/{subreddit}: {e}")
        return []


# ─── Comment Fetcher ──────────────────────────────────────────────────────────

def fetch_comments(permalink: str) -> list[dict]:
    """
    Fetch comments from a thread via Reddit JSON API.
    Only returns comments that explicitly mention Dot & Key.
    """
    json_url = f"https://www.reddit.com{permalink}.json?limit=100&depth=2"
    all_comments = []

    try:
        r = requests.get(json_url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        data = r.json()
        if len(data) > 1:
            children = data[1].get("data", {}).get("children", [])
            _walk_comments(children, all_comments, depth=0)
    except Exception as e:
        print(f"      [Comment fetch error]: {e}")

    # Filter: only keep comments that mention Dot & Key AND are substantive
    filtered = [
        c for c in all_comments
        if c["body"] not in ("[deleted]", "[removed]", "")
        and len(c["body"]) > 40
        and is_dot_key_relevant(c["body"], "")
    ]
    # Sort by score descending, return top N
    filtered.sort(key=lambda x: x["score"], reverse=True)
    return filtered[:MAX_COMMENTS_PER_THREAD]


def _walk_comments(children: list, result: list, depth: int) -> None:
    for child in children:
        if child.get("kind") != "t1":
            continue
        d = child["data"]
        result.append({
            "author": d.get("author", ""),
            "body": d.get("body", "").strip(),
            "score": d.get("score", 0),
            "depth": depth,
        })
        replies = d.get("replies", "")
        if isinstance(replies, dict):
            _walk_comments(replies.get("data", {}).get("children", []), result, depth + 1)


# ─── Per-Product Scraper ──────────────────────────────────────────────────────

def scrape_product(product_name: str, search_query: str) -> dict:
    product_data = {
        "product": f"Dot & Key {product_name}",
        "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "threads": [],
    }

    for subreddit in SUBREDDITS:
        print(f"    Searching r/{subreddit}...")
        posts = search_threads(search_query, subreddit)
        time.sleep(2)

        for post in posts:
            title = post.get("title", "")
            selftext = post.get("selftext", "")
            combined_text = title + " " + selftext

            # HARD GATE: skip if post doesn't mention Dot & Key at all
            if not is_dot_key_relevant(combined_text, product_name):
                print(f"      Skipped (no brand mention): {title[:60]}")
                continue

            num_comments = post.get("num_comments", 0)
            permalink = post.get("permalink", "")
            print(f"      Fetching: {title[:65]}... ({num_comments} comments)")

            comments = fetch_comments(permalink) if num_comments > 0 else []
            time.sleep(2)

            # Only add thread if we got at least the post itself mentioning brand
            # OR if we found brand-mentioning comments
            post_body_clean = selftext.strip()[:1200]
            product_data["threads"].append({
                "subreddit": subreddit,
                "title": title,
                "url": f"https://www.reddit.com{permalink}",
                "post_score": post.get("score", 0),
                "post_body": post_body_clean,
                "num_comments_total": num_comments,
                "dot_key_comments_found": len(comments),
                "top_comments": comments,
            })

    return product_data


# ─── Save Outputs ─────────────────────────────────────────────────────────────

def save_json(all_data: list[dict], filename: str = "dot_key_reviews.json") -> None:
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=4)
    print(f"\nJSON → {filename}")


def save_csv(all_data: list[dict], filename: str = "dot_key_reviews.csv") -> None:
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Product", "Subreddit", "Thread Title", "Thread URL",
            "Post Body (Original)", "Comment Author", "Comment Body",
            "Comment Score", "Scraped At"
        ])
        for pd in all_data:
            product = pd["product"]
            scraped_at = pd["scraped_at"]
            for thread in pd["threads"]:
                if not thread["top_comments"]:
                    # Write thread row even with no comments (post body is useful)
                    if thread["post_body"]:
                        writer.writerow([
                            product, thread["subreddit"], thread["title"],
                            thread["url"], thread["post_body"],
                            "[post author]", thread["post_body"],
                            thread["post_score"], scraped_at
                        ])
                else:
                    for c in thread["top_comments"]:
                        writer.writerow([
                            product, thread["subreddit"], thread["title"],
                            thread["url"], thread["post_body"],
                            c["author"], c["body"], c["score"], scraped_at
                        ])
    print(f"CSV  → {filename}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    all_data = []
    total_threads = 0
    total_comments = 0

    print(f"Scraping {len(DOT_KEY_PRODUCTS)} Dot & Key products...\n")

    for i, (product_name, search_query) in enumerate(DOT_KEY_PRODUCTS, 1):
        print(f"\n[{i}/{len(DOT_KEY_PRODUCTS)}] {product_name}")
        data = scrape_product(product_name, search_query)

        t = len(data["threads"])
        c = sum(th["dot_key_comments_found"] for th in data["threads"])
        total_threads += t
        total_comments += c
        print(f"  → {t} relevant threads | {c} Dot & Key comments")

        all_data.append(data)
        time.sleep(3)

    print(f"\n{'='*55}")
    print(f"Done: {total_threads} threads | {total_comments} comments")
    save_json(all_data)
    save_csv(all_data)


if __name__ == "__main__":
    main()