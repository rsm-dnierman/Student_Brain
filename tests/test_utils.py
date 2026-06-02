"""Tests for scrapers/utils.py — shared download and text-extraction helpers."""
import os
import pytest
from unittest.mock import MagicMock, patch, mock_open


# ── download_file ─────────────────────────────────────────────────────────────

class TestDownloadFile:
    def test_writes_chunks_to_disk(self, tmp_path):
        from scrapers.utils import download_file

        session = MagicMock()
        response = MagicMock()
        response.iter_content.return_value = [b"hello ", b"world"]
        session.get.return_value = response

        save_path = str(tmp_path / "out.pdf")
        download_file(session, "https://example.com/file.pdf", save_path, lambda m: None)

        assert open(save_path, "rb").read() == b"hello world"

    def test_creates_parent_directories(self, tmp_path):
        from scrapers.utils import download_file

        session = MagicMock()
        response = MagicMock()
        response.iter_content.return_value = [b"data"]
        session.get.return_value = response

        deep_path = str(tmp_path / "a" / "b" / "c" / "file.txt")
        download_file(session, "https://example.com/file.txt", deep_path, lambda m: None)

        assert os.path.exists(deep_path)

    def test_uses_dict_headers_when_no_session(self, tmp_path):
        from scrapers.utils import download_file

        headers = {"Authorization": "Bearer token123"}
        response = MagicMock()
        response.iter_content.return_value = [b"content"]
        save_path = str(tmp_path / "file.pdf")

        with patch("requests.get", return_value=response) as mock_get:
            download_file(headers, "https://example.com/file.pdf", save_path, lambda m: None)
            mock_get.assert_called_once_with(
                "https://example.com/file.pdf", headers=headers, stream=True
            )

    def test_log_reports_filename_and_size(self, tmp_path):
        from scrapers.utils import download_file

        session = MagicMock()
        response = MagicMock()
        response.iter_content.return_value = [b"x" * 1024]
        session.get.return_value = response

        messages = []
        save_path = str(tmp_path / "report.pdf")
        download_file(session, "https://example.com/report.pdf", save_path, messages.append)

        assert any("report.pdf" in m for m in messages)
        assert any("1 KB" in m for m in messages)

    def test_raises_on_http_error(self, tmp_path):
        from scrapers.utils import download_file
        import requests

        session = MagicMock()
        response = MagicMock()
        response.raise_for_status.side_effect = requests.HTTPError("404")
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            download_file(session, "https://example.com/missing.pdf",
                          str(tmp_path / "f.pdf"), lambda m: None)


# ── save_page_text ────────────────────────────────────────────────────────────

class TestSavePageText:
    HTML = """
    <html><body><main>
      <h1>Course Overview</h1>
      <h2>Objectives</h2>
      <p>Learn to build AI workflows.</p>
      <ul><li>Understand RAG</li><li>Use MCP</li></ul>
    </main></body></html>
    """

    def _mock_session(self, html, status=200):
        session = MagicMock()
        response = MagicMock()
        response.status_code = status
        response.text = html
        session.get.return_value = response
        return session

    def test_writes_text_file(self, tmp_path):
        from scrapers.utils import save_page_text

        session = self._mock_session(self.HTML)
        save_path = str(tmp_path / "page.txt")
        save_page_text(session, "https://example.com/module01/", save_path, lambda m: None)

        content = open(save_path).read()
        assert "Course Overview" in content
        assert "Objectives" in content
        assert "Learn to build AI workflows" in content

    def test_headings_get_markdown_prefix(self, tmp_path):
        from scrapers.utils import save_page_text

        session = self._mock_session(self.HTML)
        save_path = str(tmp_path / "page.txt")
        save_page_text(session, "https://example.com/page/", save_path, lambda m: None)

        content = open(save_path).read()
        assert "# Course Overview" in content
        assert "## Objectives" in content

    def test_list_items_get_dash_prefix(self, tmp_path):
        from scrapers.utils import save_page_text

        session = self._mock_session(self.HTML)
        save_path = str(tmp_path / "page.txt")
        save_page_text(session, "https://example.com/page/", save_path, lambda m: None)

        content = open(save_path).read()
        assert "- Understand RAG" in content

    def test_skips_on_non_200(self, tmp_path):
        from scrapers.utils import save_page_text

        session = self._mock_session("", status=404)
        save_path = str(tmp_path / "page.txt")
        save_page_text(session, "https://example.com/missing/", save_path, lambda m: None)

        assert not os.path.exists(save_path)

    def test_filters_short_text(self, tmp_path):
        from scrapers.utils import save_page_text

        html = "<html><body><main><p>Hi</p><p>This is a real paragraph with enough text.</p></main></body></html>"
        session = self._mock_session(html)
        save_path = str(tmp_path / "page.txt")
        save_page_text(session, "https://example.com/", save_path, lambda m: None)

        content = open(save_path).read()
        assert "Hi" not in content
        assert "real paragraph" in content
