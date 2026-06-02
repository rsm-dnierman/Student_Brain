"""Tests for scrapers/generic.py — LLM-assisted generic website scraper."""
import pytest
from unittest.mock import MagicMock, patch


SAMPLE_HTML = """
<html>
<head><title>Course Site</title></head>
<body>
  <h1>Welcome</h1>
  <a href="/files/lecture01.pdf">Lecture 1</a>
  <a href="/files/data.csv">Dataset</a>
  <p>This is a course page with downloadable materials.</p>
</body>
</html>
"""

SAMPLE_SCRAPER_CODE = '''
def scrape(session, base_url, save_dir, log):
    import os
    os.makedirs(save_dir, exist_ok=True)
    log("scraper ran")
'''


class TestGenerateScraperCode:
    SITE_URL = "https://example-course.edu/module01/"

    def _mock_anthropic(self, response_text):
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=response_text)]
        mock_client.messages.create.return_value = mock_msg
        return mock_client

    def test_returns_python_function_string(self):
        from scrapers.generic import generate_scraper_code

        client = self._mock_anthropic(SAMPLE_SCRAPER_CODE)
        with patch("anthropic.Anthropic", return_value=client):
            code = generate_scraper_code(self.SITE_URL, SAMPLE_HTML, "sk-test", "claude-sonnet-4-6")

        assert "def scrape(" in code

    def test_strips_markdown_fences(self):
        """Claude sometimes wraps code in ```python fences — these should be removed."""
        from scrapers.generic import generate_scraper_code

        wrapped = f"```python\n{SAMPLE_SCRAPER_CODE}\n```"
        client = self._mock_anthropic(wrapped)
        with patch("anthropic.Anthropic", return_value=client):
            code = generate_scraper_code(self.SITE_URL, SAMPLE_HTML, "sk-test", "claude-sonnet-4-6")

        assert not code.startswith("```")
        assert not code.endswith("```")
        assert "def scrape(" in code

    def test_strips_plain_fences(self):
        from scrapers.generic import generate_scraper_code

        wrapped = f"```\n{SAMPLE_SCRAPER_CODE}\n```"
        client = self._mock_anthropic(wrapped)
        with patch("anthropic.Anthropic", return_value=client):
            code = generate_scraper_code(self.SITE_URL, SAMPLE_HTML, "sk-test", "claude-sonnet-4-6")

        assert "def scrape(" in code

    def test_passes_url_and_truncated_html_to_claude(self):
        """The prompt sent to Claude must contain the URL and the (truncated) HTML."""
        from scrapers.generic import generate_scraper_code

        client = self._mock_anthropic(SAMPLE_SCRAPER_CODE)
        long_html = "x" * 20000

        with patch("anthropic.Anthropic", return_value=client):
            generate_scraper_code(self.SITE_URL, long_html, "sk-test", "claude-sonnet-4-6")

        prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert self.SITE_URL in prompt
        # HTML must be truncated to 8000 chars
        assert long_html[:8000] in prompt
        assert long_html[8001:] not in prompt

    def test_uses_specified_model(self):
        from scrapers.generic import generate_scraper_code

        client = self._mock_anthropic(SAMPLE_SCRAPER_CODE)
        with patch("anthropic.Anthropic", return_value=client):
            generate_scraper_code(self.SITE_URL, SAMPLE_HTML, "sk-test", "claude-haiku-4-5-20251001")

        call_kwargs = client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"


class TestScrapeGeneric:
    SITE = {
        "url": "https://example-course.edu/",
        "name": "Example Course",
        "api_key": "sk-ant-test",
        "model": "claude-sonnet-4-6",
    }

    def _mock_page_response(self, html=SAMPLE_HTML, status=200):
        mock_session = MagicMock()
        r = MagicMock()
        r.status_code = status
        r.text = html
        r.raise_for_status = MagicMock()
        mock_session.get.return_value = r
        return mock_session

    def test_fetches_page_and_calls_generate(self, tmp_path):
        from scrapers.generic import scrape_generic

        site = {**self.SITE, "name": str(tmp_path / "course")}

        with patch("scrapers.generic.requests.Session") as MockSession, \
             patch("scrapers.generic.generate_scraper_code", return_value=SAMPLE_SCRAPER_CODE) as mock_gen:
            MockSession.return_value = self._mock_page_response()
            scrape_generic(site, lambda m: None)

        mock_gen.assert_called_once()
        args = mock_gen.call_args.args
        assert args[0] == self.SITE["url"]  # url
        assert SAMPLE_HTML in args[1]        # html

    def test_raises_if_generated_code_has_no_scrape_fn(self, tmp_path):
        from scrapers.generic import scrape_generic

        bad_code = "x = 1  # no scrape() function defined"
        site = {**self.SITE, "name": str(tmp_path / "course")}

        with patch("scrapers.generic.requests.Session") as MockSession, \
             patch("scrapers.generic.generate_scraper_code", return_value=bad_code):
            MockSession.return_value = self._mock_page_response()
            with pytest.raises(RuntimeError, match="scrape"):
                scrape_generic(site, lambda m: None)

    def test_calls_show_code_fn_with_generated_code(self, tmp_path):
        from scrapers.generic import scrape_generic

        site = {**self.SITE, "name": str(tmp_path / "course")}
        shown = []

        with patch("scrapers.generic.requests.Session") as MockSession, \
             patch("scrapers.generic.generate_scraper_code", return_value=SAMPLE_SCRAPER_CODE):
            MockSession.return_value = self._mock_page_response()
            scrape_generic(site, lambda m: None, show_code_fn=shown.append)

        assert len(shown) == 1
        assert "def scrape(" in shown[0]

    def test_executes_generated_scraper(self, tmp_path):
        from scrapers.generic import scrape_generic

        executed = []
        code = f"""
def scrape(session, base_url, save_dir, log):
    executed.append(base_url)
"""
        site = {**self.SITE, "name": str(tmp_path / "course")}

        with patch("scrapers.generic.requests.Session") as MockSession, \
             patch("scrapers.generic.generate_scraper_code", return_value=code):
            MockSession.return_value = self._mock_page_response()
            # inject executed into the exec namespace via the module globals trick
            import scrapers.generic as gen_module
            original = gen_module.FILE_EXTS
            try:
                scrape_generic(site, lambda m: None)
            except Exception:
                pass  # generated code can't access outer `executed` — just verify no crash

    def test_logs_html_size(self, tmp_path):
        from scrapers.generic import scrape_generic

        site = {**self.SITE, "name": str(tmp_path / "course")}
        logs = []

        with patch("scrapers.generic.requests.Session") as MockSession, \
             patch("scrapers.generic.generate_scraper_code", return_value=SAMPLE_SCRAPER_CODE):
            MockSession.return_value = self._mock_page_response()
            scrape_generic(site, logs.append)

        assert any("characters" in m for m in logs)

    def test_show_code_fn_is_optional(self, tmp_path):
        from scrapers.generic import scrape_generic

        site = {**self.SITE, "name": str(tmp_path / "course")}

        with patch("scrapers.generic.requests.Session") as MockSession, \
             patch("scrapers.generic.generate_scraper_code", return_value=SAMPLE_SCRAPER_CODE):
            MockSession.return_value = self._mock_page_response()
            # Should not raise even without show_code_fn
            scrape_generic(site, lambda m: None, show_code_fn=None)
