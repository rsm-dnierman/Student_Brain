"""Tests for scrapers/canvas.py — Canvas LMS scraper."""
import pytest
from unittest.mock import MagicMock, patch, call


def _make_response(json_data=None, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_data or []
    return r


class TestScrapeCanvas:
    SITE = {
        "url": "https://canvas.example.edu/",
        "token": "test-token-abc",
    }

    def test_fetches_all_course_pages(self):
        """Pagination: stops when a page returns fewer items than per_page (50)."""
        from scrapers.canvas import scrape_canvas

        # Full page of 50 → more pages expected
        page1 = _make_response([{"id": i, "name": f"Course {i}"} for i in range(50)])
        # Partial page → last page
        page2 = _make_response([{"id": 50, "name": "Course 50"}])
        empty = _make_response([])

        with patch("requests.get", side_effect=[page1, page2] + [empty] * 200) as mock_get:
            scrape_canvas(self.SITE, lambda m: None)

        course_calls = [c for c in mock_get.call_args_list
                        if "users/self/courses" in str(c)]
        assert len(course_calls) == 2

    def test_auth_header_sent_on_every_request(self):
        """Every request must include the Bearer token."""
        from scrapers.canvas import scrape_canvas

        empty = _make_response([])
        with patch("requests.get", return_value=empty) as mock_get:
            scrape_canvas(self.SITE, lambda m: None)

        for c in mock_get.call_args_list:
            headers = c.kwargs.get("headers") or (c.args[1] if len(c.args) > 1 else {})
            assert "Authorization" in headers
            assert headers["Authorization"] == "Bearer test-token-abc"

    def test_logs_course_names(self):
        """Each course name should appear in the log output."""
        from scrapers.canvas import scrape_canvas

        courses = _make_response([
            {"id": 10, "name": "Data Science 101"},
            {"id": 11, "original_name": "Analytics 202"},
        ])
        done = _make_response([])
        empty = _make_response([])

        logs = []
        with patch("requests.get", side_effect=[courses, done,
                                                empty, empty, empty, empty]):
            scrape_canvas(self.SITE, logs.append)

        assert any("Data Science 101" in m for m in logs)
        assert any("Analytics 202" in m for m in logs)

    def test_uses_original_name_over_name(self):
        """original_name takes precedence over name when both are present."""
        from scrapers.canvas import scrape_canvas

        courses = _make_response([{"id": 1, "name": "Short", "original_name": "Full Name"}])
        done = _make_response([])
        empty = _make_response([])

        logs = []
        with patch("requests.get", side_effect=[courses, done, empty, empty]):
            scrape_canvas(self.SITE, logs.append)

        assert any("Full Name" in m for m in logs)
        assert not any("Short" in m for m in logs)

    def test_skips_file_download_on_api_error(self, tmp_path):
        """A non-200 files response should be silently skipped."""
        from scrapers.canvas import _download_course_files

        error_r = _make_response(status=401)
        logs = []
        with patch("requests.get", return_value=error_r):
            _download_course_files(
                "https://canvas.example.edu", 42,
                str(tmp_path), {"Authorization": "Bearer t"}, logs.append
            )

        assert not any("✓" in m for m in logs)

    def test_module_items_skips_non_file_types(self, tmp_path):
        """Only items with type=='File' should trigger a download."""
        from scrapers.canvas import _download_module_files

        modules_r = _make_response([{"id": 99}])
        items_r = _make_response([
            {"type": "Page", "title": "Intro"},
            {"type": "ExternalUrl", "title": "Link"},
        ])

        logs = []
        with patch("requests.get", side_effect=[modules_r, items_r]):
            _download_module_files(
                "https://canvas.example.edu", 1,
                str(tmp_path), {"Authorization": "Bearer t"}, logs.append
            )

        assert not any("✓" in m for m in logs)


class TestDownloadCourseFiles:
    def test_downloads_each_file(self, tmp_path):
        from scrapers.canvas import _download_course_files
        from unittest.mock import patch

        files_r = _make_response([
            {"filename": "lecture1.pdf", "url": "https://cdn.example.com/lecture1.pdf"},
            {"filename": "data.csv", "url": "https://cdn.example.com/data.csv"},
        ])

        downloaded = []

        def fake_download(headers, url, path, log):
            downloaded.append(url)

        with patch("requests.get", return_value=files_r), \
             patch("scrapers.canvas.download_file", side_effect=fake_download):
            _download_course_files(
                "https://canvas.example.edu", 1,
                str(tmp_path), {"Authorization": "Bearer t"}, lambda m: None
            )

        assert "https://cdn.example.com/lecture1.pdf" in downloaded
        assert "https://cdn.example.com/data.csv" in downloaded
