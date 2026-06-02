import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from .utils import ROOT_DIR, FILE_EXTS, download_file, save_page_text


def login(base_url, slug, email, password):
    """Authenticate to a Django-allauth site and return an authenticated session."""
    session = requests.Session()
    login_url = f"{base_url}/{slug}/accounts/login/"
    session.get(login_url)
    csrf = session.cookies.get("csrftoken")
    if not csrf:
        raise RuntimeError(f"Could not retrieve CSRF token from {login_url}")
    session.post(
        login_url,
        data={
            "csrfmiddlewaretoken": csrf,
            "login": email,
            "password": password,
            "remember": "on",
        },
        headers={"Referer": login_url},
    )
    return session


def scrape_django(site, log):
    """Download all files and page text from an RSM Django course site."""
    base = site["url"].rstrip("/")
    slug = site["slug"]

    log(f"Logging in to {base}/{slug}/...")
    session = login(base, slug, site["email"], site["password"])
    course_dir = os.path.join(ROOT_DIR, site["name"])

    _scrape_downloads_index(session, base, slug, course_dir, log)
    _scrape_module_file_pages(session, base, slug, course_dir, log)
    _scrape_page_text(session, base, slug, course_dir, log)


def _scrape_downloads_index(session, base, slug, course_dir, log):
    """Check for a central downloads page and download everything found there."""
    found = []
    for path in [f"/{slug}/downloads/", f"/{slug}/student/files/"]:
        r = session.get(base + path)
        if r.status_code != 200:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/downloads/file/" in href or "/download/" in href:
                fname = href.split("/")[-1].split("?")[0]
                found.append((fname, urljoin(base, href)))

    if not found:
        log("No central downloads page — will scan module pages instead")
        return

    log(f"Found {len(found)} files in downloads index")
    for fname, url in found:
        save_path = os.path.join(course_dir, "files", fname)
        try:
            download_file(session, url, save_path, log)
        except Exception as e:
            log(f"  ✗ {fname}: {e}")


def _scrape_module_file_pages(session, base, slug, course_dir, log):
    """Scan per-module student file pages for downloadable files."""
    for i in range(1, 16):
        mod = f"module{i:02d}"
        r = session.get(f"{base}/{slug}/student/files/{mod}")
        if r.status_code == 404:
            break
        if r.status_code != 200:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            is_file = "/download/" in href or any(
                href.lower().endswith(ext) for ext in FILE_EXTS
            )
            if not is_file:
                continue
            fname = href.split("/")[-1].split("?")[0]
            if not fname:
                continue
            url = urljoin(base, href)
            save_path = os.path.join(course_dir, mod, fname)
            if os.path.exists(save_path):
                continue
            try:
                download_file(session, url, save_path, log)
            except Exception as e:
                log(f"  ✗ {fname}: {e}")


def _scrape_page_text(session, base, slug, course_dir, log):
    """Save structured text from module, case, assignment, and resource pages."""
    log("\nSaving page text (objectives, rubrics, tasks)...")
    for prefix, count in [("module", 15), ("case", 10), ("assignment", 6)]:
        for i in range(1, count + 1):
            page_slug = f"{prefix}{i:02d}"
            url = f"{base}/{slug}/{page_slug}/"
            r = session.get(url)
            if r.status_code == 404:
                break
            save_path = os.path.join(course_dir, page_slug, f"{page_slug}-page.txt")
            if not os.path.exists(save_path):
                save_page_text(session, url, save_path, log)

    for res in ["syllabus", "grading-policy", "genai-policy", "computing", "links"]:
        url = f"{base}/{slug}/resources/{res}/"
        if session.get(url).status_code == 200:
            save_page_text(
                session, url,
                os.path.join(course_dir, "resources", f"{res}.txt"),
                log,
            )
