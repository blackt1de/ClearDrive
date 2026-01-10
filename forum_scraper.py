"""
Forum Scraper for ClearDrive
Reddit as FALLBACK source only - used when reliable sources don't have data.
Only scrapes repair-focused subreddits.
"""

import httpx
import json
import re
import time
from pathlib import Path
from datetime import datetime

SCRAPED_DATA_FILE = Path(__file__).parent / "forum_cache.json"

# Only repair-focused subreddits
REPAIR_SUBREDDITS = [
    "MechanicAdvice",
    "AskMechanics",
    "Cartalk",
    "AutoRepair",
]

HEADERS = {
    "User-Agent": "ClearDrive/1.0 (Vehicle Diagnostic Tool)"
}

# Keywords that indicate useful repair content
REPAIR_KEYWORDS = [
    "fix", "fixed", "repair", "replaced", "replace",
    "cause", "caused", "problem", "issue", "solution",
    "mechanic", "shop", "dealer", "cost", "quote",
    "sensor", "solenoid", "valve", "gasket",
    "check", "checked", "tested", "diagnosed",
]

EXCLUDE_KEYWORDS = [
    "idiot", "crash", "accident", "meme", "funny", "lol",
    "spotted", "photo", "pic", "just bought", "new car",
    "wrap", "stance", "wheel", "rim", "tint",
    "for sale", "selling", "wtb", "wts",
]


def load_cache() -> dict:
    if SCRAPED_DATA_FILE.exists():
        with open(SCRAPED_DATA_FILE, "r") as f:
            return json.load(f)
    return {"queries": {}, "last_updated": None}


def save_cache(data: dict):
    data["last_updated"] = datetime.now().isoformat()
    with open(SCRAPED_DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def is_quality_content(text: str, code: str) -> bool:
    """Check if content is relevant and useful."""
    text_lower = text.lower()
    code_lower = code.lower()
    
    # Must mention the code
    if code_lower not in text_lower:
        return False
    
    # Check for exclude keywords
    for keyword in EXCLUDE_KEYWORDS:
        if keyword in text_lower:
            return False
    
    # Must have repair-related content
    repair_count = sum(1 for kw in REPAIR_KEYWORDS if kw in text_lower)
    return repair_count >= 2


async def search_reddit(query: str, subreddit: str, limit: int = 5) -> list:
    """Search a subreddit for posts."""
    try:
        url = f"https://www.reddit.com/r/{subreddit}/search.json"
        params = {"q": query, "restrict_sr": "on", "limit": limit, "sort": "relevance"}
        
        time.sleep(1)  # Rate limiting
        
        async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
            response = await client.get(url, params=params)
            if response.status_code != 200:
                return []
            data = response.json()
        
        posts = []
        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            posts.append({
                "title": post.get("title", ""),
                "text": post.get("selftext", "")[:1000],
                "subreddit": post.get("subreddit", ""),
                "score": post.get("score", 0),
                "url": f"https://reddit.com{post.get('permalink', '')}"
            })
        
        return posts
    except Exception as e:
        print(f"[ForumScraper] Error: {e}")
        return []


async def get_post_comments(permalink: str, limit: int = 10) -> list:
    """Get top comments from a post."""
    try:
        url = f"https://www.reddit.com{permalink}.json"
        params = {"limit": limit, "sort": "top"}
        
        time.sleep(1)
        
        async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
            response = await client.get(url, params=params)
            if response.status_code != 200:
                return []
            data = response.json()
        
        comments = []
        if len(data) > 1:
            for child in data[1].get("data", {}).get("children", [])[:limit]:
                comment = child.get("data", {})
                body = comment.get("body", "")
                score = comment.get("score", 0)
                if body and score >= 1 and len(body) > 30:
                    comments.append(body[:400])
        
        return comments
    except:
        return []


async def scrape_reddit_fallback(code: str, make: str, model: str, year: str = None) -> dict:
    """
    Scrape Reddit as a FALLBACK source.
    Only called when reliable sources don't have enough data.
    Returns only high-quality, relevant content.
    """
    print(f"[ForumScraper] Checking Reddit for {code} on {make} {model}...")
    
    cache = load_cache()
    cache_key = f"{make}_{model}_{code}".lower().replace(" ", "_")
    
    # Check cache (7 days)
    if cache_key in cache.get("queries", {}):
        cached = cache["queries"][cache_key]
        cached_time = datetime.fromisoformat(cached.get("cached_at", "2000-01-01"))
        if (datetime.now() - cached_time).days < 7:
            print(f"[ForumScraper] Using cached Reddit data")
            return cached
    
    all_posts = []
    queries = [
        f"{make} {model} {code}",
        f"{code} {make}",
        code,
    ]
    
    # Search repair subreddits
    for subreddit in REPAIR_SUBREDDITS:
        for query in queries[:2]:
            posts = await search_reddit(query, subreddit, limit=5)
            all_posts.extend(posts)
    
    # Filter to quality posts that mention the code
    quality_posts = [p for p in all_posts if is_quality_content(f"{p['title']} {p['text']}", code)]
    
    # Remove duplicates
    seen = set()
    unique_posts = []
    for p in quality_posts:
        if p["url"] not in seen:
            seen.add(p["url"])
            unique_posts.append(p)
    
    # Sort by score
    unique_posts.sort(key=lambda x: x["score"], reverse=True)
    
    # Get comments from top posts
    insights = []
    for post in unique_posts[:3]:
        comments = await get_post_comments(post["url"].replace("https://reddit.com", ""))
        quality_comments = [c for c in comments if is_quality_content(c, code)][:2]
        
        if quality_comments:
            insights.append({
                "title": post["title"],
                "comments": quality_comments,
                "subreddit": post["subreddit"]
            })
    
    result = {
        "code": code,
        "make": make,
        "model": model,
        "insights": insights,
        "cached_at": datetime.now().isoformat()
    }
    
    # Cache
    if "queries" not in cache:
        cache["queries"] = {}
    cache["queries"][cache_key] = result
    save_cache(cache)
    
    if insights:
        print(f"[ForumScraper] Found {len(insights)} quality Reddit discussions")
    else:
        print(f"[ForumScraper] No quality Reddit data found")
    
    return result


def format_reddit_context(reddit_data: dict) -> str:
    """Format Reddit data into context for SLM. Only if useful."""
    insights = reddit_data.get("insights", [])
    
    if not insights:
        return ""
    
    parts = ["COMMUNITY REPORTS (from Reddit repair forums):"]
    
    for insight in insights[:2]:
        for comment in insight["comments"][:1]:
            clean = comment.replace("\n", " ").strip()[:200]
            parts.append(f'  - "{clean}..."')
    
    if len(parts) == 1:
        return ""
    
    return "\n".join(parts)


# CLI for testing
if __name__ == "__main__":
    import sys
    import asyncio
    
    if len(sys.argv) < 4:
        print("Usage: python forum_scraper.py <code> <make> <model> [year]")
        print("Example: python forum_scraper.py P0420 Honda Accord 2018")
        sys.exit(1)
    
    code = sys.argv[1]
    make = sys.argv[2]
    model = sys.argv[3]
    year = sys.argv[4] if len(sys.argv) > 4 else None
    
    result = asyncio.run(scrape_reddit_fallback(code, make, model, year))
    
    print("\n" + "="*50)
    print("REDDIT DATA:")
    print("="*50)
    print(format_reddit_context(result) or "No quality data found")