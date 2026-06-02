"""Tests for scrapers/django.py — RSM Django course site scraper."""
import pytest
from unittest.mock import MagicMock, patch, call


def _session_with_cookies(csrf="testcsrf123"):
    session = MagicMock()
    session.cookies.get.return_value = csrf
    response = MagicMock()
    response.status_code = 200
    response.url = "https://rsm-django-02.ucsd.edu/mgta495/"
    session.get.return_value = response
    session.post.return_value = response
    return session


class TestLogin:
    def test_gets_login_page_first(self):
        """Must GET the login page before POSTing so Django sets the CSRF cookie."""
        from scrapers.django import login

        with patch("scrapers.django.requests.Session", return_value=_session_with_cookies()) as _:
            session = login("https://example.com", "mgta495", "user@test.com", "pass")

        session.get.assert_called_once_with("https://example.com/mgta495/accounts/login/")

    def test_posts_csrf_token(self):
        """The POST payload must include the csrfmiddlewaretoken from the cookie."""
        from scrapers.django import login

        mock_session = _session_with_cookies(csrf="mycsrftoken")
        with patch("scrapers.django.requests.Session", return_value=mock_session):
            login("https://example.com", "mgta495", "user@test.com", "secret")

        post_data = mock_session.post.call_args.kwargs["data"]
        assert post_data["csrfmiddlewaretoken"] == "mycsrftoken"

    def test_posts_credentials(self):
        """Email and password must be in the POST payload under 'login' and 'password'."""
        from scrapers.django import login

        mock_session = _session_with_cookies()
        with patch("scrapers.django.requests.Session", return_value=mock_session):
            login("https://example.com", "mgta495", "david@ucsd.edu", "hunter2")

        post_data = mock_session.post.call_args.kwargs["data"]
        assert post_data["login"] == "david@ucsd.edu"
        assert post_data["password"] == "hunter2"

    def test_posts_to_correct_login_url(self):
        """Login POST must go to /<slug>/accounts/login/."""
        from scrapers.django import login

        mock_session = _session_with_cookies()
        with patch("scrapers.django.requests.Session", return_value=mock_session):
            login("https://example.com", "mgta455", "u@test.com", "p")

        post_url = mock_session.post.call_args.args[0]
        assert post_url == "https://example.com/mgta455/accounts/login/"

    def test_raises_if_no_csrf_token(self):
        """Should raise RuntimeError if the CSRF cookie is missing (login page blocked)."""
        from scrapers.django import login

        mock_session = _session_with_cookies(csrf=None)
        mock_session.cookies.get.return_value = None
        with patch("scrapers.django.requests.Session", return_value=mock_session):
            with pytest.raises(RuntimeError, match="CSRF"):
                login("https://example.com", "mgta495", "u@test.com", "p")


class TestScrapeDownloadsIndex:
    def _make_html_with_links(self, hrefs):
        links = "".join(f'<a href="{h}">file</a>' for h in hrefs)
        return f"<html><body>{links}</body></html>"

    def test_discovers_files_from_downloads_page(self):
        from scrapers.django import _scrape_downloads_index

        html = self._make_html_with_links([
            "/mgta455/downloads/file/module04.pdf",
            "/mgta455/downloads/file/data.csv",
        ])
        session = MagicMock()
        r_ok = MagicMock()
        r_ok.status_code = 200
        r_ok.text = html
        r_404 = MagicMock()
        r_404.status_code = 404
        session.get.side_effect = [r_ok, r_404]

        downloaded = []
        with patch("scrapers.django.download_file",
                   side_effect=lambda s, url, path, log: downloaded.append(url)):
            _scrape_downloads_index(session, "https://rsm.ucsd.edu", "mgta455",
                                    "/tmp/course", lambda m: None)

        assert any("module04.pdf" in u for u in downloaded)
        assert any("data.csv" in u for u in downloaded)

    def test_logs_count_when_files_found(self):
        from scrapers.django import _scrape_downloads_index

        html = self._make_html_with_links(["/mgta455/downloads/file/a.pdf"])
        session = MagicMock()
        r_ok = MagicMock()
        r_ok.status_code = 200
        r_ok.text = html
        r_404 = MagicMock()
        r_404.status_code = 404
        session.get.side_effect = [r_ok, r_404]

        logs = []
        with patch("scrapers.django.download_file"):
            _scrape_downloads_index(session, "https://rsm.ucsd.edu", "mgta455",
                                    "/tmp/course", logs.append)

        assert any("1 files" in m for m in logs)

    def test_logs_fallback_message_when_no_downloads_page(self):
        from scrapers.django import _scrape_downloads_index

        session = MagicMock()
        r_404 = MagicMock()
        r_404.status_code = 404
        session.get.return_value = r_404

        logs = []
        _scrape_downloads_index(session, "https://rsm.ucsd.edu", "mgta495",
                                "/tmp/course", logs.append)

        assert any("module pages" in m.lower() for m in logs)


class TestScrapeModuleFilePages:
    def test_stops_at_first_404(self):
        """Should stop scanning module pages when a 404 is returned."""
        from scrapers.django import _scrape_module_file_pages

        session = MagicMock()
        r_404 = MagicMock()
        r_404.status_code = 404
        session.get.return_value = r_404

        with patch("scrapers.django.download_file") as mock_dl:
            _scrape_module_file_pages(session, "https://rsm.ucsd.edu", "mgta495",
                                      "/tmp/course", lambda m: None)

        # Only module01 should have been checked before stopping
        session.get.assert_called_once_with(
            "https://rsm.ucsd.edu/mgta495/student/files/module01"
        )
        mock_dl.assert_not_called()

    def test_downloads_pdf_links(self, tmp_path):
        """PDF links on a module page should trigger a download."""
        from scrapers.django import _scrape_module_file_pages

        html = '<html><body><a href="/mgta495/student/files/download/module01/slides.pdf">slides</a></body></html>'
        session = MagicMock()
        r_ok = MagicMock()
        r_ok.status_code = 200
        r_ok.text = html
        r_404 = MagicMock()
        r_404.status_code = 404
        session.get.side_effect = [r_ok, r_404]

        downloaded = []
        with patch("scrapers.django.download_file",
                   side_effect=lambda s, url, path, log: downloaded.append(url)):
            _scrape_module_file_pages(session, "https://rsm.ucsd.edu", "mgta495",
                                      str(tmp_path), lambda m: None)

        assert any("slides.pdf" in u for u in downloaded)
