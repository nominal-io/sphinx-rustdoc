"""sphinx-rustdoc: a Sphinx API reference for Rust crates, built from rustdoc's JSON output."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from sphinx.application import Sphinx
from sphinx.errors import ExtensionError
from sphinx.util import logging

from . import pages
from .domain import (
    LOADED,
    ItemDirective,
    MembersDirective,
    ReexportsDirective,
    RustDomain,
    SummaryDirective,
)
from .model import Crate

__version__ = "0.1.0"

logger = logging.getLogger(__name__)


def _cargo(arguments: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    try:
        result = subprocess.run(
            ["cargo", *arguments], cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", check=False
        )
    except FileNotFoundError as error:
        raise ExtensionError("sphinx-rustdoc: cargo isn't on PATH; install Rust, or set the crate's `json`") from error
    if result.returncode != 0:
        raise ExtensionError(f"sphinx-rustdoc: `cargo {' '.join(arguments)}` failed:\n{result.stderr}")
    return result.stdout


def build_json(package: str, cwd: Path) -> Path:
    """Run rustdoc's JSON output for a package's library, and return the file it wrote."""
    metadata = json.loads(_cargo(["metadata", "--format-version", "1", "--no-deps"], cwd))
    found = next((p for p in metadata["packages"] if p["name"] == package), None)
    if found is None:
        raise ExtensionError(f"sphinx-rustdoc: no package {package!r} in the Cargo workspace at {cwd}")
    lib = next((t for t in found["targets"] if {"lib", "rlib", "proc-macro"} & set(t["kind"])), None)
    if lib is None:
        raise ExtensionError(f"sphinx-rustdoc: package {package!r} has no library to document")
    logger.info(f"sphinx-rustdoc: building rustdoc JSON for {package}")
    # rustdoc's JSON output is unstable; RUSTC_BOOTSTRAP lets a stable toolchain write it. Its own
    # target folder keeps cargo builds without RUSTC_BOOTSTRAP from making it rebuild every dependency.
    target = Path(metadata["target_directory"]) / "sphinx-rustdoc"
    env = {**os.environ, "RUSTC_BOOTSTRAP": "1", "CARGO_TARGET_DIR": str(target)}
    _cargo(["rustdoc", "-p", package, "--lib", "--", "-Z", "unstable-options", "--output-format", "json"], cwd, env)
    return json_file(target, lib["name"].replace("-", "_"))


def json_file(target: Path, lib: str) -> Path:
    """The JSON `cargo rustdoc` wrote: in `target/doc/`, or `target/<triple>/doc/` when the Cargo
    config sets `build.target`."""
    found = [*target.glob(f"doc/{lib}.json"), *target.glob(f"*/doc/{lib}.json")]
    if not found:
        raise ExtensionError(f"sphinx-rustdoc: `cargo rustdoc` wrote no {lib}.json under {target}")
    # the newest, since JSON for another target from an earlier build can be there too
    return max(found, key=lambda path: path.stat().st_mtime)


def generate(app: Sphinx) -> None:
    """Load each crate's JSON and write its pages, before Sphinx reads the source folder."""
    LOADED.clear()
    output = Path(app.srcdir) / app.config.rustdoc_output
    # cleanup deletes every page there that this build didn't write, so it can't be the source folder
    source = Path(app.srcdir).resolve()
    if source not in output.resolve().parents:
        value = app.config.rustdoc_output
        raise ExtensionError(
            f"sphinx-rustdoc: rustdoc_output must be a folder inside the docs source folder, not {value!r}"
        )
    unlinked = frozenset(app.config.rustdoc_unlinked_crates)
    written: set[Path] = set()
    for label, options in app.config.rustdoc_crates.items():
        if "json" in options:
            json_path = Path(app.confdir) / options["json"]
            if not json_path.is_file():
                raise ExtensionError(f"sphinx-rustdoc: rustdoc_crates[{label!r}]: no JSON file at {json_path}")
        elif "package" in options:
            json_path = build_json(options["package"], Path(app.confdir))
        else:
            raise ExtensionError(f"sphinx-rustdoc: rustdoc_crates[{label!r}] needs a `package` or a `json` file")
        raw = json_path.read_bytes()
        crate = Crate(json.loads(raw), unlinked)
        LOADED[crate.name] = crate
        crate_pages = pages.write(crate, output, hashlib.sha256(raw).hexdigest()[:16])
        written.update(crate_pages)
        logger.info(f"sphinx-rustdoc: {crate.name}: {len(crate_pages)} pages")
    # after every crate, so pages of a crate taken out of rustdoc_crates go too
    if output.is_dir():
        pages.remove_stale(output, written)


def setup(app: Sphinx) -> dict[str, Any]:
    app.setup_extension("myst_parser")
    # crate label: {"package": the Cargo package to document} or {"json": a rustdoc JSON file}
    app.add_config_value("rustdoc_crates", {}, "env", dict)
    # the generated pages' folder, under the source folder
    app.add_config_value("rustdoc_output", "ref/rust", "env", str)
    # crates whose items render as text, with no link to their docs
    app.add_config_value("rustdoc_unlinked_crates", [], "env", list)
    app.add_domain(RustDomain)
    app.add_directive_to_domain("rust", "item", ItemDirective)
    app.add_directive_to_domain("rust", "members", MembersDirective)
    app.add_directive_to_domain("rust", "summary", SummaryDirective)
    app.add_directive_to_domain("rust", "reexports", ReexportsDirective)
    app.connect("builder-inited", generate)
    return {"version": __version__, "env_version": 1, "parallel_read_safe": True, "parallel_write_safe": True}
