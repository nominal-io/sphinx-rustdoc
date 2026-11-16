"""Build a small Sphinx site from the fixture crate's rustdoc JSON."""

import html
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

FIXTURE_JSON = Path(__file__).parent / "fixture" / "fixture.json"


@dataclass
class Site:
    source: Path
    output: Path
    result: subprocess.CompletedProcess[str]

    def page(self, docname: str) -> str:
        """A built page's text, without tags, with whitespace collapsed."""
        raw = (self.output / f"{docname}.html").read_text(encoding="utf-8")
        body = raw.split("<article", 1)[-1]
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", body)))

    def html(self, docname: str) -> str:
        return (self.output / f"{docname}.html").read_text(encoding="utf-8")


def build(tmp_path: Path, index: str = "", conf: str = "", doc: dict | None = None) -> Site:
    """Build the fixture's pages. `doc` replaces its JSON, for a case the fixture crate doesn't have."""
    json_path = FIXTURE_JSON
    if doc is not None:
        json_path = tmp_path / "fixture.json"
        json_path.write_text(json.dumps(doc), encoding="utf-8")
    source = tmp_path / "src"
    source.mkdir()
    (source / "conf.py").write_text(
        f"extensions = ['sphinx_rustdoc']\nrustdoc_crates = {{'fixture': {{'json': {str(json_path)!r}}}}}\n{conf}\n",
        encoding="utf-8",
    )
    (source / "index.md").write_text(
        f"# Fixture\n\n{index}\n\n```{{toctree}}\nref/rust/fixture/index\n```\n", encoding="utf-8"
    )
    output = tmp_path / "html"
    result = subprocess.run(
        [sys.executable, "-m", "sphinx", "-W", "--keep-going", "-E", "-b", "html", str(source), str(output)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return Site(source, output, result)


@pytest.fixture(scope="session")
def site(tmp_path_factory: pytest.TempPathFactory) -> Site:
    built = build(
        tmp_path_factory.mktemp("site"),
        index="See {rust:struct}`Client` and {rust:fn}`fixture::add`.",
    )
    assert built.result.returncode == 0, built.result.stdout + built.result.stderr
    return built
