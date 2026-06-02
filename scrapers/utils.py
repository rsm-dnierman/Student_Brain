import os
import requests
from bs4 import BeautifulSoup

ROOT_DIR = "./Courses"

FILE_EXTS = (
    ".pdf", ".xlsx", ".xls", ".csv", ".zip",
    ".ipynb", ".py", ".docx", ".pptx", ".txt", ".json", ".mp4",
)


def download_file(session_or_headers, url, save_path, log):
    """Download a file using either a requests.Session or a headers dict."""
    if isinstance(session_or_headers, dict):
        r = requests.get(url, headers=session_or_headers, stream=True)
    else:
        r = session_or_headers.get(url, stream=True)
    r.raise_for_status()
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    kb = os.path.getsize(save_path) / 1024
    log(f"  ✓ {os.path.basename(save_path)} ({kb:.0f} KB)")


def save_page_text(session, url, save_path, log):
    """Fetch a page and save its readable text content as a .txt file."""
    r = session.get(url)
    if r.status_code != 200:
        return
    soup = BeautifulSoup(r.text, "html.parser")
    main = soup.find("main") or soup.body
    lines = []
    for tag in (main or soup).find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        t = tag.get_text(strip=True)
        if t and len(t) > 3:
            prefix = {
                "h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### "
            }.get(tag.name, "- " if tag.name == "li" else "")
            lines.append(prefix + t)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "w") as f:
        f.write("\n".join(lines))
    log(f"  ✓ {os.path.basename(save_path)} (page text)")
