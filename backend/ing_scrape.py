import requests
from bs4 import BeautifulSoup
import time
import re
import os
from dotenv import load_dotenv
from fastapi import HTTPException

# Load environment variables
load_dotenv()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

BASE_URL = "https://incidecoder.com"


# ─────────────────────────────────────────────
# HELPERS (unchanged from your original)
# ─────────────────────────────────────────────

def get_comedogenicity(soup):
    com_scores = []
    for row in soup.select("table tr"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        irr_com_cell = cells[2].get_text(strip=True)
        m = re.match(r'^(\d+)\s*,\s*(\d+)$', irr_com_cell)
        if m:
            com_scores.append(int(m.group(2)))

    if not com_scores:
        for el in soup.find_all(True, {"title": re.compile(r'comedogen', re.I)}):
            digits = re.findall(r'\d+', el.get("title", ""))
            if digits:
                com_scores.append(int(digits[-1]))

    if not com_scores:
        return "No comment"
    max_score = max(com_scores)
    return f"Yes (max: {max_score}/5)" if max_score >= 1 else "No"


def get_ingredients(soup):
    JUNK_PHRASES = {
        "read more on", "how to read", "ingredient list",
        "what-it-does", "also-called", "irr.", "id-rating", "superstar", "goodie"
    }

    def is_junk(text):
        t = text.lower().strip()
        return not t or any(p in t for p in JUNK_PHRASES)

    container = (
        soup.find(id=re.compile(r'ingred', re.I)) or
        soup.find(id=re.compile(r'inci', re.I)) or
        soup.find(class_=re.compile(r'ingred-list', re.I)) or
        soup.find(class_=re.compile(r'inci-list', re.I))
    )

    if container:
        items = container.find_all("li")
        if items:
            names = []
            for li in items:
                a = li.find("a")
                span = li.find(class_=re.compile(r'ingr|inci|ingredient', re.I))
                text = (span or a or li).get_text(strip=True)
                if not is_junk(text):
                    names.append(text)
            if names:
                return ", ".join(names)

        lines = [ln.strip() for ln in container.get_text(separator="\n").splitlines()]
        clean = [ln for ln in lines if not is_junk(ln) and len(ln) > 1]
        if clean:
            return ", ".join(clean)

    for sel in [
        "span.ingr-name", "a.ingr-name",
        "span.ingredient-name", "a.ingredient-name",
        "[class*='ingr-name']", "[class*='ingredient-name']",
    ]:
        els = soup.select(sel)
        if els:
            names = [el.get_text(strip=True) for el in els if not is_junk(el.get_text(strip=True))]
            if names:
                return ", ".join(names)

    return ""


def get_picture(soup) -> str:
    picture_url = ""
    img_el = soup.find("img", class_=re.compile(r"product|image|main", re.I))
    if not img_el:
        img_el = soup.find("img")
    if img_el:
        src = img_el.get("src", "")
        if src:
            if src.startswith("/"):
                picture_url = BASE_URL + src
            elif not src.startswith("http"):
                picture_url = BASE_URL + "/" + src
            else:
                picture_url = src
    return picture_url


# ─────────────────────────────────────────────
# CORE: Search INCIDecoder by product name
# ─────────────────────────────────────────────

def search_incidecoder(product_name: str) -> dict | None:
    search_url = f"{BASE_URL}/search?query={requests.utils.quote(product_name)}"
    print(f"🔍 Searching INCIDecoder: {search_url}")

    try:
        r = requests.get(search_url, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"❌ Search request failed: {e}")
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    result = soup.select_one("a[href*='/products/']")
    if not result:
        print("❌ No results found on INCIDecoder")
        return None

    product_url = BASE_URL + result["href"]
    print(f"✅ Found: {product_url}")
    return {"url": product_url}  # ← no brand here, let the product page handle it


def scrape_product_by_url(url: str, brand_name: str = "Unknown") -> dict:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch product page: {e}")

    soup = BeautifulSoup(r.text, "html.parser")

    h1 = soup.find("h1")
    name = h1.get_text(strip=True) if h1 else "Unknown"

    # This is where brand is actually reliably available
    brand_el = soup.find("span", id="product-brand-title")
    if brand_el:
        a_tag = brand_el.find("a")
        brand_name = (a_tag or brand_el).get_text(strip=True)

    return {
        "product_name": name,
        "brand_name": brand_name,
        "ingredients": get_ingredients(soup),
        "comedogenic_score": get_comedogenicity(soup),
        "product_picture": get_picture(soup),
        "source_url": url,
    }