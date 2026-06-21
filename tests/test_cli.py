"""Tests for the CLI — agent functions mocked, no real network."""

from __future__ import annotations

import argparse
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _ok_result(url: str = "https://example.com") -> dict:
    return {
        "url": url,
        "title": "Test Page",
        "content": "Page content here.",
        "success": True,
        "strategy_used": "fast",
        "error": None,
    }


def _fail_result(url: str = "https://example.com") -> dict:
    return {
        "url": url,
        "title": None,
        "content": None,
        "success": False,
        "strategy_used": "fast",
        "error": "timeout",
    }


# ── parser ─────────────────────────────────────────────────────────────────────

class TestBuildParser:
    def test_read_subcommand_exists(self):
        from web4agent.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["read", "https://example.com"])
        assert args.command == "read"
        assert args.url == "https://example.com"

    def test_read_default_strategy(self):
        from web4agent.cli import _build_parser
        args = _build_parser().parse_args(["read", "https://example.com"])
        assert args.strategy == "auto"

    def test_read_custom_strategy(self):
        from web4agent.cli import _build_parser
        args = _build_parser().parse_args(["read", "https://example.com", "--strategy", "fast"])
        assert args.strategy == "fast"

    def test_read_default_max_content_chars(self):
        from web4agent.cli import _build_parser
        args = _build_parser().parse_args(["read", "https://example.com"])
        assert args.max_content_chars == 1200

    def test_many_subcommand_exists(self):
        from web4agent.cli import _build_parser
        args = _build_parser().parse_args(["many", "https://a.com", "https://b.com"])
        assert args.command == "many"
        assert args.urls == ["https://a.com", "https://b.com"]

    def test_many_default_concurrency(self):
        from web4agent.cli import _build_parser
        args = _build_parser().parse_args(["many", "https://a.com"])
        assert args.concurrency == 5

    def test_many_custom_concurrency(self):
        from web4agent.cli import _build_parser
        args = _build_parser().parse_args(["many", "https://a.com", "--concurrency", "10"])
        assert args.concurrency == 10

    def test_links_subcommand_exists(self):
        from web4agent.cli import _build_parser
        args = _build_parser().parse_args(["links", "https://example.com"])
        assert args.command == "links"

    def test_links_same_domain_flag(self):
        from web4agent.cli import _build_parser
        args = _build_parser().parse_args(["links", "https://example.com", "--same-domain"])
        assert args.same_domain is True

    def test_links_default_same_domain_false(self):
        from web4agent.cli import _build_parser
        args = _build_parser().parse_args(["links", "https://example.com"])
        assert args.same_domain is False

    def test_links_max_links(self):
        from web4agent.cli import _build_parser
        args = _build_parser().parse_args(["links", "https://example.com", "--max-links", "20"])
        assert args.max_links == 20

    def test_doctor_subcommand_exists(self):
        from web4agent.cli import _build_parser
        args = _build_parser().parse_args(["doctor"])
        assert args.command == "doctor"
        assert args.json is False

    def test_doctor_json_flag(self):
        from web4agent.cli import _build_parser
        args = _build_parser().parse_args(["doctor", "--json"])
        assert args.json is True


# ── _run_read ──────────────────────────────────────────────────────────────────

class TestRunRead:
    @pytest.mark.asyncio
    async def test_returns_0_on_success(self, capsys):
        args = argparse.Namespace(url="https://example.com", strategy="auto", max_content_chars=1200)
        with patch("web4agent.cli.agent_read_url", AsyncMock(return_value=_ok_result())):
            from web4agent.cli import _run_read
            code = await _run_read(args)
        assert code == 0

    @pytest.mark.asyncio
    async def test_returns_1_on_failure(self, capsys):
        args = argparse.Namespace(url="https://example.com", strategy="auto", max_content_chars=1200)
        with patch("web4agent.cli.agent_read_url", AsyncMock(return_value=_fail_result())):
            from web4agent.cli import _run_read
            code = await _run_read(args)
        assert code == 1

    @pytest.mark.asyncio
    async def test_output_is_valid_json(self, capsys):
        args = argparse.Namespace(url="https://example.com", strategy="auto", max_content_chars=1200)
        with patch("web4agent.cli.agent_read_url", AsyncMock(return_value=_ok_result())):
            from web4agent.cli import _run_read
            await _run_read(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_content_truncated_to_max_chars(self, capsys):
        result = _ok_result()
        result["content"] = "x" * 5000
        args = argparse.Namespace(url="https://example.com", strategy="auto", max_content_chars=100)
        with patch("web4agent.cli.agent_read_url", AsyncMock(return_value=result)):
            from web4agent.cli import _run_read
            await _run_read(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert len(data["content"]) == 100

    @pytest.mark.asyncio
    async def test_strategy_forwarded(self, capsys):
        args = argparse.Namespace(url="https://example.com", strategy="fast", max_content_chars=1200)
        with patch("web4agent.cli.agent_read_url", AsyncMock(return_value=_ok_result())) as mock:
            from web4agent.cli import _run_read
            await _run_read(args)
        mock.assert_called_once_with("https://example.com", strategy="fast")


# ── _run_many ──────────────────────────────────────────────────────────────────

class TestRunMany:
    def _summary(self, succeeded: int = 2, failed: int = 0) -> dict:
        results = [_ok_result(f"https://url{i}.com") for i in range(succeeded)]
        results += [_fail_result(f"https://fail{i}.com") for i in range(failed)]
        return {
            "results": results,
            "total": succeeded + failed,
            "succeeded": succeeded,
            "failed": failed,
        }

    @pytest.mark.asyncio
    async def test_returns_0_when_all_succeed(self, capsys):
        args = argparse.Namespace(
            urls=["https://a.com", "https://b.com"],
            strategy="auto",
            concurrency=5,
            max_content_chars=300,
        )
        with patch("web4agent.cli.agent_read_urls", AsyncMock(return_value=self._summary(2, 0))):
            from web4agent.cli import _run_many
            code = await _run_many(args)
        assert code == 0

    @pytest.mark.asyncio
    async def test_returns_1_when_any_fails(self, capsys):
        args = argparse.Namespace(
            urls=["https://a.com", "https://b.com"],
            strategy="auto",
            concurrency=5,
            max_content_chars=300,
        )
        with patch("web4agent.cli.agent_read_urls", AsyncMock(return_value=self._summary(1, 1))):
            from web4agent.cli import _run_many
            code = await _run_many(args)
        assert code == 1

    @pytest.mark.asyncio
    async def test_output_is_valid_json(self, capsys):
        args = argparse.Namespace(
            urls=["https://a.com"],
            strategy="auto",
            concurrency=5,
            max_content_chars=300,
        )
        with patch("web4agent.cli.agent_read_urls", AsyncMock(return_value=self._summary(1, 0))):
            from web4agent.cli import _run_many
            await _run_many(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "results" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_content_truncated_per_result(self, capsys):
        summary = self._summary(1, 0)
        summary["results"][0]["content"] = "x" * 2000
        args = argparse.Namespace(
            urls=["https://a.com"],
            strategy="auto",
            concurrency=5,
            max_content_chars=50,
        )
        with patch("web4agent.cli.agent_read_urls", AsyncMock(return_value=summary)):
            from web4agent.cli import _run_many
            await _run_many(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert len(data["results"][0]["content"]) == 50


# ── _run_links ─────────────────────────────────────────────────────────────────

class TestRunLinks:
    @pytest.mark.asyncio
    async def test_returns_0(self, capsys):
        args = argparse.Namespace(url="https://example.com", same_domain=True, max_links=50)
        with patch("web4agent.cli.discover_links", AsyncMock(return_value=["https://example.com/a"])):
            from web4agent.cli import _run_links
            code = await _run_links(args)
        assert code == 0

    @pytest.mark.asyncio
    async def test_output_contains_links(self, capsys):
        links = ["https://example.com/a", "https://example.com/b"]
        args = argparse.Namespace(url="https://example.com", same_domain=False, max_links=50)
        with patch("web4agent.cli.discover_links", AsyncMock(return_value=links)):
            from web4agent.cli import _run_links
            await _run_links(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["count"] == 2
        assert data["links"] == links
        assert data["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_same_domain_forwarded(self, capsys):
        args = argparse.Namespace(url="https://example.com", same_domain=True, max_links=10)
        with patch("web4agent.cli.discover_links", AsyncMock(return_value=[])) as mock:
            from web4agent.cli import _run_links
            await _run_links(args)
        mock.assert_called_once_with("https://example.com", same_domain=True, max_links=10)


# ── _run_search ──────────────────────────────────────────────────────────────────


_SEARCH_RESULT = {
    "query": "test query",
    "results": [
        {"url": "https://a.com", "title": "A", "content": "Content A", "extracted": True},
        {"url": "https://b.com", "title": "B", "content": "Content B", "extracted": True},
    ],
    "hits": 2,
    "extracted": 2,
}


class TestRunSearch:
    @pytest.mark.asyncio
    async def test_returns_0_when_results_found(self, capsys):
        args = argparse.Namespace(
            query=["test", "query"],
            max_results=10,
            extract_strategy="auto",
            concurrency=5,
            instance=None,
        )
        with patch("web4agent.cli.agent_search", AsyncMock(return_value=_SEARCH_RESULT)):
            from web4agent.cli import _run_search
            code = await _run_search(args)
        assert code == 0

    @pytest.mark.asyncio
    async def test_returns_1_when_no_results(self, capsys):
        empty = {"query": "x", "results": [], "hits": 0, "extracted": 0}
        args = argparse.Namespace(
            query=["x"], max_results=10, extract_strategy="auto", concurrency=5, instance=None,
        )
        with patch("web4agent.cli.agent_search", AsyncMock(return_value=empty)):
            from web4agent.cli import _run_search
            code = await _run_search(args)
        assert code == 1

    @pytest.mark.asyncio
    async def test_query_words_joined(self, capsys):
        args = argparse.Namespace(
            query=["python", "web", "scraping"],
            max_results=5,
            extract_strategy="fast",
            concurrency=3,
            instance=None,
        )
        with patch("web4agent.cli.agent_search", AsyncMock(return_value=_SEARCH_RESULT)) as mock:
            from web4agent.cli import _run_search
            await _run_search(args)
        mock.assert_called_once_with(
            "python web scraping",
            max_results=5,
            extract_strategy="fast",
            extract_concurrency=3,
            instance=None,
        )


# ── _run_doctor ──────────────────────────────────────────────────────────────────

_DOCTOR_REPORT = {
    "dependencies": [{"name": "crawl4ai", "module": "crawl4ai", "installed": True}],
    "connectivity": [{"target": "wayback", "url": "https://archive.org", "reachable": True}],
    "circuit_breakers": [],
}


class TestRunDoctor:
    @pytest.mark.asyncio
    async def test_returns_0(self, capsys):
        args = argparse.Namespace(json=False)
        with patch("web4agent.cli.run_doctor", AsyncMock(return_value=_DOCTOR_REPORT)):
            from web4agent.cli import _run_doctor
            code = await _run_doctor(args)
        assert code == 0

    @pytest.mark.asyncio
    async def test_human_readable_by_default(self, capsys):
        args = argparse.Namespace(json=False)
        with patch("web4agent.cli.run_doctor", AsyncMock(return_value=_DOCTOR_REPORT)):
            from web4agent.cli import _run_doctor
            await _run_doctor(args)
        out = capsys.readouterr().out
        assert "Dependencies:" in out

    @pytest.mark.asyncio
    async def test_json_flag_prints_json(self, capsys):
        args = argparse.Namespace(json=True)
        with patch("web4agent.cli.run_doctor", AsyncMock(return_value=_DOCTOR_REPORT)):
            from web4agent.cli import _run_doctor
            await _run_doctor(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data == _DOCTOR_REPORT


# ── main() dispatch ─────────────────────────────────────────────────────────────


def _make_args(command: str) -> MagicMock:
    args = MagicMock()
    args.command = command
    return args


class TestMain:
    def _run_main_with_command(self, command: str, exit_code: int = 0):
        from web4agent.cli import main
        args = _make_args(command)
        with patch("web4agent.cli._build_parser") as mock_parser:
            mock_parser.return_value.parse_args.return_value = args
            with patch("web4agent.cli.asyncio.run", return_value=exit_code):
                with pytest.raises(SystemExit) as exc_info:
                    main()
        return exc_info.value.code

    def test_dispatches_read_command(self):
        code = self._run_main_with_command("read", exit_code=0)
        assert code == 0

    def test_dispatches_many_command(self):
        code = self._run_main_with_command("many", exit_code=0)
        assert code == 0

    def test_dispatches_links_command(self):
        code = self._run_main_with_command("links", exit_code=0)
        assert code == 0

    def test_dispatches_search_command(self):
        code = self._run_main_with_command("search", exit_code=0)
        assert code == 0

    def test_dispatches_doctor_command(self):
        code = self._run_main_with_command("doctor", exit_code=0)
        assert code == 0

    def test_unsupported_command_calls_parser_error(self):
        from web4agent.cli import main
        args = _make_args("unknown_cmd")
        with patch("web4agent.cli._build_parser") as mock_parser:
            mock_parser.return_value.parse_args.return_value = args
            mock_parser.return_value.error = MagicMock(side_effect=SystemExit(2))
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 2
        mock_parser.return_value.error.assert_called_once()
