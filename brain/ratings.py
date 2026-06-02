"""
Log and load thumbs-up / thumbs-down ratings for brain answers.
Stored as newline-delimited JSON in ratings.jsonl.
"""
import json
import os
from datetime import datetime

RATINGS_FILE = "./ratings.jsonl"


def log_rating(question: str, answer: str, rating: str, sources: list[dict]) -> None:
    """rating: 'up' or 'down'"""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "question":  question,
        "answer":    answer[:300],
        "rating":    rating,
        "sources":   [s.get("source", "") for s in sources[:5]],
    }
    with open(RATINGS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_ratings() -> list[dict]:
    if not os.path.exists(RATINGS_FILE):
        return []
    ratings = []
    with open(RATINGS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    ratings.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return ratings


def rating_summary() -> dict:
    ratings = get_ratings()
    ups   = sum(1 for r in ratings if r.get("rating") == "up")
    downs = sum(1 for r in ratings if r.get("rating") == "down")
    return {"total": len(ratings), "up": ups, "down": downs}
