# Recipes run in PowerShell on Windows (no bash or cygpath needed) and sh elsewhere.
[windows]
set shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# list the recipes
default:
    @just --list

# install the package and its test dependencies
setup:
    uv sync --group dev

# run the tests and lint, as in CI
test:
    uv run --group dev pytest
    uv run --group dev ruff check
    uv run --group dev ruff format --check

# regenerate tests/fixture/fixture.json and user.json after changing the fixture crates or the Rust toolchain
[windows]
fixture:
    $env:RUSTC_BOOTSTRAP = '1'; cargo rustdoc --manifest-path tests/fixture/Cargo.toml --lib -- -Z unstable-options --output-format json
    uv run python -I tests/fixture/scrub.py tests/fixture/target/doc/fixture.json tests/fixture/fixture.json
    $env:RUSTC_BOOTSTRAP = '1'; cargo rustdoc --manifest-path tests/fixture/user/Cargo.toml --lib -- -Z unstable-options --output-format json
    uv run python -I tests/fixture/scrub.py tests/fixture/target/doc/user.json tests/fixture/user.json

[unix]
fixture:
    RUSTC_BOOTSTRAP=1 cargo rustdoc --manifest-path tests/fixture/Cargo.toml --lib -- -Z unstable-options --output-format json
    uv run python -I tests/fixture/scrub.py tests/fixture/target/doc/fixture.json tests/fixture/fixture.json
    RUSTC_BOOTSTRAP=1 cargo rustdoc --manifest-path tests/fixture/user/Cargo.toml --lib -- -Z unstable-options --output-format json
    uv run python -I tests/fixture/scrub.py tests/fixture/target/doc/user.json tests/fixture/user.json

# build the wheel and sdist into dist/
build:
    uv build
