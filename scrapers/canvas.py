import os
import requests
from .utils import ROOT_DIR, download_file


def scrape_canvas(site, log):
    """Download all files and module content from a Canvas LMS instance."""
    token = site["token"]
    domain = site["url"].rstrip("/")
    headers = {"Authorization": f"Bearer {token}"}

    log("Fetching course list...")
    courses, page = [], 1
    while True:
        params = [
            ("enrollment_state[]", "active"),
            ("enrollment_state[]", "completed"),
            ("per_page", 50),
            ("page", page),
        ]
        r = requests.get(f"{domain}/api/v1/users/self/courses", headers=headers, params=params)
        if r.status_code != 200:
            log(f"Canvas API error {r.status_code}: {r.text[:200]}")
            break
        data = r.json()
        if not data or not isinstance(data, list):
            break
        courses.extend(data)
        if len(data) < 50:
            break
        page += 1
    log(f"Found {len(courses)} courses")

    for course in courses:
        cid = course.get("id")
        cname = course.get("original_name") or course.get("name") or str(cid)
        log(f"\n[{cname}]")
        course_dir = os.path.join(ROOT_DIR, cname)

        _download_course_files(domain, cid, course_dir, headers, log)
        _download_module_files(domain, cid, course_dir, headers, log)


def _download_course_files(domain, course_id, course_dir, headers, log):
    page = 1
    while True:
        r = requests.get(
            f"{domain}/api/v1/courses/{course_id}/files",
            headers=headers,
            params=[("per_page", 100), ("page", page)],
        )
        if r.status_code == 401:
            log("  (files restricted — skipping)")
            return
        if r.status_code != 200:
            log(f"  (files API {r.status_code} — skipping)")
            return
        data = r.json()
        if not data or not isinstance(data, list):
            break
        for f in data:
            fname = f.get("filename") or f.get("display_name") or str(f.get("id"))
            file_url = f.get("url") or f.get("download_url")
            if not file_url:
                continue
            save_path = os.path.join(course_dir, "Files", fname)
            try:
                download_file(headers, file_url, save_path, log)
            except Exception as e:
                log(f"  ✗ {fname}: {e}")
        if len(data) < 100:
            break
        page += 1


def _download_module_files(domain, course_id, course_dir, headers, log):
    r = requests.get(
        f"{domain}/api/v1/courses/{course_id}/modules",
        headers=headers,
        params=[("per_page", 100)],
    )
    if r.status_code == 401:
        log("  (modules restricted — skipping)")
        return
    if r.status_code != 200:
        log(f"  (modules API {r.status_code} — skipping)")
        return
    for mod in r.json():
        r2 = requests.get(
            f"{domain}/api/v1/courses/{course_id}/modules/{mod['id']}/items",
            headers=headers,
            params=[("per_page", 100)],
        )
        if r2.status_code != 200:
            continue
        for item in r2.json():
            if item.get("type") != "File":
                continue
            fid = item.get("content_id")
            if not fid:
                continue
            meta_r = requests.get(f"{domain}/api/v1/files/{fid}", headers=headers)
            if meta_r.status_code != 200:
                continue
            meta = meta_r.json()
            file_url = meta.get("url") or meta.get("download_url")
            if not file_url:
                continue
            fname = meta.get("filename") or meta.get("display_name") or item.get("title") or str(fid)
            save_path = os.path.join(course_dir, "Modules", fname)
            try:
                download_file(headers, file_url, save_path, log)
            except Exception as e:
                log(f"  ✗ {fname}: {e}")
