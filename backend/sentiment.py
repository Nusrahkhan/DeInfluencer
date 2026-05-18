from __future__ import annotations

import argparse
import math
import os
import re
from collections import Counter
from pathlib import Path

import pandas as pd
import requests


POSITIVE_WORDS = {
    "amazing", "awesome", "best", "better", "clean", "comfortable", "effective",
    "excellent", "favorite", "fantastic", "good", "great", "happy", "helpful",
    "impressed", "light", "love", "lovely", "nice", "perfect", "pleasant",
    "positive", "premium", "recommend", "satisfying", "smooth", "soft", "superb",
    "useful", "well", "works", "worth", "affordable", "hydrating", "soothing",
    "gentle", "glowy", "glow", "nonsticky", "nongreasy", "absorbs", "absorbed",
    "noticeable", "noticeably", "repurchase", "repurchasing", "saves", "cheap",
    "cheaper", "value",
}

NEGATIVE_WORDS = {
    "awful", "bad", "broke", "broken", "clogged", "clogs", "clogging", "dry",
    "dull", "expensive", "fake", "greasy", "heavy", "horrible", "irritating",
    "itchy", "itching", "issue", "issues", "lacking", "late", "leaky", "messy",
    "negative", "oily", "poor", "problem", "problems", "rough", "sticky",
    "stings", "sting", "sucks", "terrible", "thick", "uncomfortable", "uneven",
    "weak", "worse", "worst", "waste", "breakout", "breakouts", "comedone",
    "comedones", "fragrance", "smell", "odor", "odour", "allergic", "burning",
    "burns", "rash", "refund", "return", "tacky", "dried", "drying", "didnt",
    "doesnt", "not", "never",
}

NEGATION_WORDS = {"not", "no", "never", "none", "hardly", "rarely", "without"}
INTENSIFIERS = {"very", "really", "so", "too", "extremely", "super", "quite", "totally"}

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "because", "been", "but", "by",
    "for", "from", "had", "has", "have", "he", "her", "his", "i", "if", "in",
    "into", "is", "it", "its", "me", "my", "of", "on", "or", "our", "out",
    "she", "so", "that", "the", "their", "them", "then", "there", "these",
    "they", "this", "those", "to", "up", "us", "was", "we", "were", "what",
    "when", "where", "which", "who", "why", "with", "would", "you", "your",
    "minimalist", "product", "products", "review", "reviews", "comment", "comments",
    "brand", "skin", "face", "hair", "body", "routine", "use", "using", "used",
    "works", "work", "worked", "good", "great", "bad", "thing", "things",
}

ASPECT_PATTERNS: dict[str, tuple[str, ...]] = {
    "texture and feel": (
        "texture", "feel", "lightweight", "heavy", "thick", "smooth", "greasy", "sticky",
        "tacky", "absorbs", "absorbed", "absorb", "finish", "sinks in", "non greasy", "nongreasy",
    ),
    "hydration and moisture": (
        "hydrating", "hydration", "moisturizing", "moisturising", "moisture", "dry",
        "dryness", "nourishing", "soothing", "soft", "plump",
    ),
    "effectiveness and results": (
        "works", "worked", "effective", "helped", "helpful", "results", "result",
        "improvement", "improved", "repurchase", "repurchasing", "recommend", "worth",
    ),
    "irritation and breakouts": (
        "breakout", "breakouts", "acne", "clog", "clogs", "clogging", "comedone", "comedones",
        "irritating", "irritation", "sting", "stings", "burn", "burns", "rash", "allergic",
    ),
    "fragrance and smell": (
        "fragrance", "smell", "scent", "odor", "odour", "perfume", "perfumed", "fragrant",
    ),
    "value and pricing": (
        "price", "priced", "cheap", "cheaper", "expensive", "value", "worth", "cost",
        "affordable", "budget", "money", "deal",
    ),
    "packaging and usability": (
        "packaging", "bottle", "tube", "pump", "cap", "leak", "leaky", "messy", "travel",
        "easy", "convenient", "useful", "application", "apply", "applying",
    ),
    "sunscreen finish": (
        "sunscreen", "spf", "matte", "dewy", "shine", "shiny", "no white cast",
    ),
    "hair feel and control": (
        "frizz", "frizzy", "soft", "smooth", "shine", "breakage", "split ends", "scalp",
        "oily scalp", "dandruff", "hair fall", "manageability",
    ),
}

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z\-']+")
GEMINI_WARNING_PRINTED = False


def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_gemini_api_key() -> str | None:
    candidate_names = [
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_GENAI_API_KEY",
        "GEMINI_KEY",
    ]
    for name in candidate_names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def normalize_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in WORD_RE.findall(text.lower())]


def resolve_columns(frame: pd.DataFrame) -> tuple[str, str, str | None]:
    lowered = {column.lower().strip(): column for column in frame.columns}

    product_candidates = ["product", "product name", "item", "title"]
    text_candidates = ["comment", "body", "review", "content", "text", "message"]
    title_candidates = ["title", "post title", "review title"]

    product_column = next((lowered[name] for name in product_candidates if name in lowered), None)
    text_column = next((lowered[name] for name in text_candidates if name in lowered), None)
    title_column = next((lowered[name] for name in title_candidates if name in lowered), None)

    if product_column is None:
        raise ValueError(
            "Could not find a product column. Expected something like Product or Product Name."
        )
    if text_column is None:
        raise ValueError(
            "Could not find a text column. Expected something like Comment, Body, or Review."
        )

    return product_column, text_column, title_column


def build_review_text(frame: pd.DataFrame, text_column: str, title_column: str | None) -> pd.Series:
    if title_column and title_column != text_column:
        combined = frame[[title_column, text_column]].fillna("").agg(" ".join, axis=1)
        return combined.map(normalize_text)
    return frame[text_column].map(normalize_text)


def score_text(text: str) -> float:
    tokens = tokenize(text)
    if not tokens:
        return 0.0

    score = 0.0
    token_count = len(tokens)
    lower_text = text.lower()

    for index, token in enumerate(tokens):
        base = 0.0
        if token in POSITIVE_WORDS:
            base = 1.0
        elif token in NEGATIVE_WORDS:
            base = -1.0

        if base == 0.0:
            continue

        window_start = max(0, index - 3)
        window = tokens[window_start:index]
        if any(word in NEGATION_WORDS for word in window):
            base *= -1.0
        if any(word in INTENSIFIERS for word in window):
            base *= 1.25

        score += base

    if "white cast" in lower_text:
        score -= 1.5

    normalized = math.tanh(score / max(3.0, token_count / 12.0))
    return max(-1.0, min(1.0, normalized))


def extract_phrases(texts: list[str], product_name: str, max_phrases: int = 4) -> list[str]:
    phrase_counts: Counter[str] = Counter()
    product_tokens = {token for token in tokenize(product_name) if len(token) > 2}

    for text in texts:
        tokens = [token for token in tokenize(text) if token not in STOPWORDS and token not in product_tokens]
        if not tokens:
            continue

        for size in (3, 2):
            if len(tokens) < size:
                continue
            for start in range(len(tokens) - size + 1):
                phrase_tokens = tokens[start:start + size]
                if any(len(token) <= 2 for token in phrase_tokens):
                    continue
                if phrase_tokens[0] in STOPWORDS or phrase_tokens[-1] in STOPWORDS:
                    continue
                phrase = " ".join(phrase_tokens)
                phrase_counts[phrase] += 1

    selected: list[str] = []
    for phrase, _ in phrase_counts.most_common():
        if phrase not in selected:
            selected.append(phrase)
        if len(selected) >= max_phrases:
            break
    return selected


def extract_aspects(texts: list[str]) -> list[str]:
    aspect_counts: Counter[str] = Counter()
    combined_text = " \n ".join(texts).lower()

    for aspect_name, patterns in ASPECT_PATTERNS.items():
        matches = 0
        for pattern in patterns:
            matches += combined_text.count(pattern)
        if matches:
            aspect_counts[aspect_name] = matches

    return [aspect for aspect, _ in aspect_counts.most_common()]


def has_white_cast_complaint(texts: list[str]) -> bool:
    for text in texts:
        lower_text = text.lower()
        if "white cast" not in lower_text:
            continue
        if re.search(r"\b(no|not|without|less|little|minimal)\s+white cast\b", lower_text):
            continue
        return True
    return False


def select_snippets(review_texts: list[str], scores: list[float], limit: int = 7) -> list[str]:
    paired = list(zip(review_texts, scores))
    paired.sort(key=lambda item: abs(item[1]), reverse=True)

    snippets: list[str] = []
    for text, _ in paired:
        trimmed = re.sub(r"\s+", " ", text).strip()
        if not trimmed:
            continue
        snippets.append(trimmed[:220])
        if len(snippets) >= limit:
            break
    return snippets


def generate_gemini_summary(
    api_key: str,
    model: str,
    product_name: str,
    overall_score_5: float,
    positive_share: float,
    negative_share: float,
    neutral_share: float,
    positive_themes: list[str],
    negative_themes: list[str],
    review_texts: list[str],
    scores: list[float],
) -> str | None:
    global GEMINI_WARNING_PRINTED
    snippets = select_snippets(review_texts, scores, limit=7)
    if not snippets:
        return None

    prompt = (
        "You are writing an e-commerce style review summary for one product. "
        "Return plain text only, max 4 sentences, simple and helpful. "
        "Do not mention number of comments or percentages unless needed. "
        "Treat white cast in sunscreen as a negative issue.\n\n"
        f"Product: {product_name}\n"
        f"Score: {overall_score_5}/5\n"
        f"Sentiment split: positive={positive_share}%, negative={negative_share}%, neutral={neutral_share}%\n"
        f"Positive themes: {', '.join(positive_themes[:5]) if positive_themes else 'none'}\n"
        f"Negative themes: {', '.join(negative_themes[:5]) if negative_themes else 'none'}\n"
        "Review snippets:\n"
        + "\n".join(f"- {snippet}" for snippet in snippets)
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 220},
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        if response.status_code != 200:
            if not GEMINI_WARNING_PRINTED:
                reason = "Gemini API request failed"
                if response.status_code == 429:
                    reason = "Gemini quota exceeded (HTTP 429). Using heuristic fallback summaries."
                elif response.status_code in (401, 403):
                    reason = "Gemini API auth error (HTTP 401/403). Check API key and permissions."
                print(reason)
                GEMINI_WARNING_PRINTED = True
            return None

        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return None

        parts = candidates[0].get("content", {}).get("parts", [])
        summary = " ".join(part.get("text", "").strip() for part in parts if part.get("text"))
        summary = re.sub(r"\s+", " ", summary).strip()
        return summary or None
    except Exception:
        if not GEMINI_WARNING_PRINTED:
            print("Gemini request failed due to a network/runtime issue. Using heuristic fallback summaries.")
            GEMINI_WARNING_PRINTED = True
        return None


def summarize_product(
    product_name: str,
    review_texts: list[str],
    scores: list[float],
    use_ai_summary: bool,
    gemini_api_key: str | None,
    gemini_model: str,
) -> dict[str, object]:
    review_count = len(review_texts)
    positive_texts = [text for text, score in zip(review_texts, scores) if score > 0.15]
    negative_texts = [text for text, score in zip(review_texts, scores) if score < -0.15]
    neutral_texts = [text for text, score in zip(review_texts, scores) if -0.15 <= score <= 0.15]

    positive_share = round((len(positive_texts) / review_count) * 100, 1) if review_count else 0.0
    negative_share = round((len(negative_texts) / review_count) * 100, 1) if review_count else 0.0
    neutral_share = round((len(neutral_texts) / review_count) * 100, 1) if review_count else 0.0

    average_score = sum(scores) / review_count if review_count else 0.0
    overall_score_5 = round(((average_score + 1.0) / 2.0) * 5.0, 1)

    positive_themes = extract_aspects(positive_texts)
    negative_themes = extract_aspects(negative_texts)
    all_themes = extract_aspects(review_texts)

    if not positive_themes:
        positive_themes = extract_phrases(positive_texts, product_name, max_phrases=3)
    if not negative_themes:
        negative_themes = extract_phrases(negative_texts, product_name, max_phrases=3)
    if not all_themes:
        all_themes = extract_phrases(review_texts, product_name, max_phrases=4)

    sentiment_label = "mixed"
    if overall_score_5 >= 3.8:
        sentiment_label = "mostly positive"
    elif overall_score_5 <= 2.2:
        sentiment_label = "mostly negative"

    summary_parts: list[str] = []

    # Build a concise, scannable summary
    if overall_score_5 >= 4.2:
        intro = f"Highly rated at {overall_score_5}/5. "
    elif overall_score_5 >= 3.5:
        intro = f"Well-received at {overall_score_5}/5. "
    elif overall_score_5 >= 2.8:
        intro = f"Mixed reviews at {overall_score_5}/5. "
    else:
        intro = f"Poorly received at {overall_score_5}/5. "

    # Add the main selling points or issues
    if positive_themes and negative_themes:
        main = f"Praised for {positive_themes[0].lower()}"
        if len(positive_themes) > 1:
            main += f" and {positive_themes[1].lower()}"
        main += f", but criticized for {negative_themes[0].lower()}."
        summary_parts.append(intro + main)
    elif positive_themes:
        summary_parts.append(intro + f"Praised for {', '.join(positive_themes[:2]).lower()}.")
    elif negative_themes:
        summary_parts.append(intro + f"Main concerns are {', '.join(negative_themes[:2]).lower()}.")
    else:
        summary_parts.append(intro.strip() + ".")

    # Add white cast issue if present
    if has_white_cast_complaint(review_texts):
        summary_parts.append("White cast is a significant concern for some users.")

    # Add sentiment split only if meaningful
    if review_count >= 5:
        if positive_share >= 70:
            summary_parts.append(f"Most reviewers ({positive_share}%) are positive.")
        elif negative_share >= 70:
            summary_parts.append(f"Most reviewers ({negative_share}%) report problems.")
        elif abs(positive_share - negative_share) >= 20:
            summary_parts.append(f"Opinions lean {('positive' if positive_share > negative_share else 'negative')} ({int(max(positive_share, negative_share))}% vs {int(min(positive_share, negative_share))}%).")

    ai_summary = None
    if use_ai_summary and gemini_api_key:
        ai_summary = generate_gemini_summary(
            api_key=gemini_api_key,
            model=gemini_model,
            product_name=product_name,
            overall_score_5=overall_score_5,
            positive_share=positive_share,
            negative_share=negative_share,
            neutral_share=neutral_share,
            positive_themes=positive_themes,
            negative_themes=negative_themes,
            review_texts=review_texts,
            scores=scores,
        )

    final_summary = ai_summary if ai_summary else " ".join(summary_parts)

    return {
        "Product": product_name,
        "Review Count": review_count,
        "Average Sentiment": round(average_score, 3),
        "Score / 5": overall_score_5,
        "Positive %": positive_share,
        "Negative %": negative_share,
        "Neutral %": neutral_share,
        "Positive Themes": ", ".join(positive_themes),
        "Negative Themes": ", ".join(negative_themes + (["white cast"] if has_white_cast_complaint(review_texts) else [])),
        "Summary": final_summary,
    }


def analyze_reviews(
    input_path: Path,
    output_path: Path,
    use_ai_summary: bool,
    gemini_api_key: str | None,
    gemini_model: str,
) -> pd.DataFrame:
    frame = pd.read_csv(input_path)
    product_column, text_column, title_column = resolve_columns(frame)
    review_text = build_review_text(frame, text_column, title_column)

    working = frame.copy()
    working["__product__"] = working[product_column].map(normalize_text)
    working["__review_text__"] = review_text
    working = working[working["__product__"].astype(bool) & working["__review_text__"].astype(bool)]

    rows: list[dict[str, object]] = []
    for product_name, group in working.groupby("__product__", sort=True):
        texts = group["__review_text__"].tolist()
        scores = [score_text(text) for text in texts]
        rows.append(
            summarize_product(
                product_name,
                texts,
                scores,
                use_ai_summary=use_ai_summary,
                gemini_api_key=gemini_api_key,
                gemini_model=gemini_model,
            )
        )

    report = pd.DataFrame(rows).sort_values(["Score / 5", "Review Count"], ascending=[False, False])
    report.to_csv(output_path, index=False)
    return report

def analyze_reviews_from_records(
    records: list[dict],
    use_ai_summary: bool = True,
    gemini_api_key: str | None = None,
    gemini_model: str = "gemini-2.5-flash-lite",
) -> pd.DataFrame:

    if not records:
        return pd.DataFrame()

    frame = pd.DataFrame(records)

    # Expected columns
    # product -> product name
    # body -> review text
    # title -> optional title

    if "product" not in frame.columns:
        raise ValueError("Missing 'product' field")

    if "body" not in frame.columns:
        raise ValueError("Missing 'body' field")

    frame["__product__"] = frame["product"].map(normalize_text)

    if "title" in frame.columns:
        frame["__review_text__"] = build_review_text(
            frame,
            text_column="body",
            title_column="title"
        )
    else:
        frame["__review_text__"] = frame["body"].map(normalize_text)

    frame = frame[
        frame["__product__"].astype(bool)
        & frame["__review_text__"].astype(bool)
    ]

    rows = []

    for product_name, group in frame.groupby("__product__", sort=True):
        texts = group["__review_text__"].tolist()
        scores = [score_text(text) for text in texts]

        rows.append(
            summarize_product(
                product_name=product_name,
                review_texts=texts,
                scores=scores,
                use_ai_summary=use_ai_summary,
                gemini_api_key=gemini_api_key,
                gemini_model=gemini_model,
            )
        )

    report = pd.DataFrame(rows)

    return report

def default_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}_sentiment_report_5pt.csv")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Score product reviews/comments and generate an Amazon-style summary per product."
    )
    parser.add_argument(
        "--input",
        default="minimalist_reviews_cleaned.csv",
        help="Path to a CSV containing product reviews/comments.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path for the generated per-product sentiment report CSV.",
    )
    parser.add_argument(
        "--no-ai-summary",
        action="store_true",
        help="Disable Gemini AI summaries and use heuristic summaries only.",
    )
    parser.add_argument(
        "--gemini-model",
        default="gemini-2.5-flash-lite",
        help="Gemini model ID for summary generation (for example: gemini-2.5-flash-lite).",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else default_output_path(input_path)
    load_dotenv(Path(".env"))

    gemini_api_key = resolve_gemini_api_key()
    use_ai_summary = not args.no_ai_summary

    report = analyze_reviews(
        input_path,
        output_path,
        use_ai_summary=use_ai_summary,
        gemini_api_key=gemini_api_key,
        gemini_model=args.gemini_model,
    )
    print(f"Analyzed {len(report)} products from {input_path}")
    print(f"Saved report to {output_path}")
    if use_ai_summary and not gemini_api_key:
        print("GEMINI_API_KEY not found in environment or .env. Used heuristic summary fallback.")


if __name__ == "__main__":
    main()