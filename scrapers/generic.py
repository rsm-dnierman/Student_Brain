import os
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from .utils import ROOT_DIR, FILE_EXTS


def generate_scraper_code(url, html, api_key, model="claude-sonnet-4-6"):
    """Ask Claude to write a scrape() function for the given page HTML."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    prompt = f"""You are an expert web scraping engineer. Analyze this page and write a Python scraper.

URL: {url}

HTML (first 8000 characters):
{html[:8000]}

Write a Python function with EXACTLY this signature:

def scrape(session, base_url, save_dir, log):
    pass

Parameters:
- session: requests.Session() — use for ALL HTTP requests, never requests.get() directly
- base_url: str — starting URL ({url})
- save_dir: str — directory to save all output
- log: callable(str) — call this to report every action

Requirements:
- Download all valuable files (PDFs, notebooks, datasets, zips, slides)
- Save meaningful text content as .txt files
- Follow pagination links if present
- Use os.makedirs(path, exist_ok=True) before writing any file
- Wrap each download in try/except and call log() on both success and failure
- Derive filenames from URLs or link text; strip special characters
- Only follow links on the same domain

Available in scope (do NOT import): requests, os, BeautifulSoup, urljoin, re, FILE_EXTS

Return ONLY the Python function. No markdown fences, no explanation, no import statements."""

    msg = client.messages.create(
        model=model,
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    code = msg.content[0].text.strip()
    # Strip accidental markdown fences
    code = re.sub(r"^```(?:python)?\n?", "", code)
    code = re.sub(r"\n?```$", "", code)
    return code.strip()


def scrape_generic(site, log, show_code_fn=None):
    """Fetch a page, ask Claude to write a scraper, then execute it."""
    url = site["url"]
    api_key = site["api_key"]
    model = site.get("model", "claude-sonnet-4-6")
    save_dir = os.path.join(ROOT_DIR, site["name"])

    log(f"Fetching page HTML from {url}...")
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; CourseScraper/1.0)"})
    r = session.get(url, timeout=15)
    r.raise_for_status()
    html = r.text
    log(f"Got {len(html):,} characters of HTML")

    log(f"Asking {model} to generate a scraper...")
    code = generate_scraper_code(url, html, api_key, model)

    if show_code_fn:
        show_code_fn(code)

    log("Executing generated scraper...")
    namespace = {
        "requests": requests,
        "os": os,
        "BeautifulSoup": BeautifulSoup,
        "urljoin": urljoin,
        "re": re,
        "FILE_EXTS": FILE_EXTS,
    }
    exec(code, namespace)  # noqa: S102
    scrape_fn = namespace.get("scrape")
    if not scrape_fn:
        raise RuntimeError("Generated code did not define a `scrape` function.")
    scrape_fn(session, url, save_dir, log)
