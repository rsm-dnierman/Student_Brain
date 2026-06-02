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
    r = requests.get(f"{domain}/api/v1/courses/{course_id}/files", headers=headers)
    if r.status_code != 200:
        return
    for f in r.json():
        save_path = os.path.join(course_dir, "Files", f["filename"])
        try:
            download_file(headers, f["url"], save_path, log)
        except Exception as e:
            log(f"  ✗ {f['filename']}: {e}")


def _download_module_files(domain, course_id, course_dir, headers, log):
    r = requests.get(f"{domain}/api/v1/courses/{course_id}/modules", headers=headers)
    if r.status_code != 200:
        return
    for mod in r.json():
        r2 = requests.get(
            f"{domain}/api/v1/courses/{course_id}/modules/{mod['id']}/items",
            headers=headers,
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
            file_url = meta_r.json().get("url") or meta_r.json().get("download_url")
            if not file_url:
                continue
            save_path = os.path.join(course_dir, "Modules", item.get("title") or str(fid))
            try:
                download_file(headers, file_url, save_path, log)
            except Exception as e:
                log(f"  ✗ {item.get('title')}: {e}")
