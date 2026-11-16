"""The fixture crate's pages: where each item is documented, and what its page shows."""

import json
import os
import re

import pytest
from conftest import FIXTURE_JSON, Site, build
from sphinx.errors import ExtensionError
from sphinx.util.inventory import InventoryFile

from sphinx_rustdoc import json_file, markdown, render
from sphinx_rustdoc.domain import reexports
from sphinx_rustdoc.model import Crate

PAGES = "ref/rust/fixture"


def links(site: Site, docname: str) -> dict[str, list[str]]:
    """Each link's text on a page, and where it goes."""
    found: dict[str, list[str]] = {}
    for href, label in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', site.html(docname), re.DOTALL):
        found.setdefault(" ".join(re.sub(r"<[^>]+>", "", label).split()), []).append(href)
    return found


def test_builds_without_warnings(site: Site) -> None:
    assert "WARNING" not in site.result.stderr


def test_items_are_documented_at_their_public_path(site: Site) -> None:
    pages = sorted(p.relative_to(site.source / PAGES).as_posix() for p in (site.source / PAGES).rglob("*.md"))
    assert pages == [
        "edge/a/b/index.md",
        "edge/a/index.md",
        "edge/enum.Level.md",
        "edge/index.md",
        # re-exported by a module re-exported from a private one: shallower than edge::a::b's re-export
        "edge/shortcut/index.md",
        "edge/shortcut/struct.Deep.md",
        "edge/struct.Counter.md",
        # a module with the same name as a function
        "edge/total/index.md",
        "enum.Error.md",
        "index.md",
        "prelude/index.md",
        # re-exported from a private module, renamed
        "shapes/index.md",
        "shapes/struct.Circle.md",
        "shapes/struct.Grid.md",
        "shapes/struct.Unit.md",
        # defined in a public module, so documented there, not at the crate root's re-export
        "shapes/trait.Shape.md",
        "struct.Builder.md",
        # re-exported from a private module
        "struct.Client.md",
        "struct.Rid.md",
        "trait.Identified.md",
        "type.Result.md",
    ]


def test_signatures_render_from_the_type_tree(site: Site) -> None:
    client = site.page(f"{PAGES}/struct.Client")
    assert "pub struct Client" in client
    assert "pub async fn get(&self, rid: Rid) -> Result<String>" in client
    assert "pub fn set_timeout(&mut self, seconds: u64) -> &mut Self" in client
    assert "pub fn new(base_url: impl Into<String>) -> Self" in client
    crate = site.page(f"{PAGES}/index")
    assert (
        "pub async fn first<'a, T>(items: &'a [T], key: impl AsRef<str>) -> Option<&'a T> "
        "where T: Clone + Send + 'static"
    ) in crate
    assert (
        "pub fn apply(f: fn(i32) -> i32, g: &dyn Fn(&str) -> bool, h: Box<dyn Iterator<Item = u8> + Send>) "
        "-> (i32, bool)"
    ) in crate
    assert "pub const ANSWER: u32 = 42" in crate
    assert "pub static NAME: &str" in crate
    assert "macro_rules! square" in crate
    assert "pub struct Builder<T = ()> where T: Default" in site.page(f"{PAGES}/struct.Builder")
    assert "pub struct Rid(pub u64)" in site.page(f"{PAGES}/struct.Rid")
    assert "pub struct Grid<const N: usize>" in site.page(f"{PAGES}/shapes/struct.Grid")
    assert "pub type Result<T> = Result<T, Error>" in site.page(f"{PAGES}/type.Result")
    identified = site.page(f"{PAGES}/trait.Identified")
    assert "fn label(&self) -> String where Self::Id: Display" in identified
    assert "const COUNT: usize = 1" in identified
    assert "type Id: Clone" in identified


def test_enum_variants_and_their_fields(site: Site) -> None:
    error = site.page(f"{PAGES}/enum.Error")
    assert "Timeout(u64)" in error
    assert "message: String" in error
    assert "What the server said." in error


def test_doc_comments(site: Site) -> None:
    crate = site.page(f"{PAGES}/index")
    # rustdoc hides `# ` lines in Rust examples, and `##` shows a line starting with `#`
    assert "let hidden" not in crate
    assert "# let shown = 2;" in crate
    assert "# not hidden: this block isn't Rust" in crate
    client = site.html(f"{PAGES}/struct.Client")
    # a heading becomes a rubric, with the id rustdoc gives the heading
    assert '<p class="rubric" id="examples">Examples</p>' in client
    assert "highlight-rust" in client
    # the deprecation note
    assert "Deprecated since 0.2.0" in crate


def test_intra_doc_links(site: Site) -> None:
    client = links(site, f"{PAGES}/struct.Client")
    assert "struct.Builder.html" in client["Builder"]
    assert "#method.get" in client["Client::get"]
    assert "#method.set_timeout" in client["set_timeout"]
    assert "enum.Error.html#variant.NotFound" in client["Error::NotFound"]
    crate = links(site, f"{PAGES}/index")
    assert "shapes/trait.Shape.html" in crate["shapes::Shape"]


def test_signature_links(site: Site) -> None:
    client = links(site, f"{PAGES}/struct.Client")
    assert "struct.Rid.html" in client["Rid"]
    assert "https://doc.rust-lang.org/1.98.1/alloc/string/struct.String.html" in client["String"]
    crate = links(site, f"{PAGES}/index")
    assert (
        "https://doc.rust-lang.org/1.98.1/std/collections/hash/map/struct.HashMap.html"
        in crate["std::collections::HashMap"]
    )


def test_trait_implementations(site: Site) -> None:
    client = site.page(f"{PAGES}/struct.Client")
    assert "impl Identified for Client" in client
    assert "impl Display for Client" in client
    assert "Derived: Debug, Clone" in client
    assert "Auto traits: Send, Sync, Unpin, UnwindSafe, RefUnwindSafe" in client
    # blanket implementations apply to nearly every type, so they're left out
    for blanket in ("impl<T> From<T>", "Borrow<T>", "impl<T, U> Into<U>", "Any for"):
        assert blanket not in client
    assert "impl Shape for Circle" in site.page(f"{PAGES}/shapes/trait.Shape")


def test_module_page_lists_and_reexports(site: Site) -> None:
    crate = site.page(f"{PAGES}/index")
    assert "Client: A client." in crate
    assert "pub use shapes::Shape;" in crate
    assert "pub use std::collections::HashMap as Map;" in crate
    assert "pub use crate::shapes::*;" in site.page(f"{PAGES}/prelude/index")


def test_objects_inventory(site: Site) -> None:
    with open(site.output / "objects.inv", "rb") as f:
        inventory = InventoryFile.load(f, "", lambda base, uri: uri)
    objects = {(kind, name): entry for kind, names in inventory.items() for name, entry in names.items()}
    assert ("rust:struct", "fixture::Client") in objects
    assert ("rust:method", "fixture::Client::get") in objects
    assert ("rust:trait", "fixture::shapes::Shape") in objects
    assert ("rust:variant", "fixture::Error::NotFound") in objects
    assert ("rust:field", "fixture::Client::base_url") in objects
    assert ("rust:function", "fixture::add") in objects


def test_roles_link_by_path_or_its_end(site: Site) -> None:
    index = links(site, "index")
    assert f"{PAGES}/struct.Client.html" in index["Client"]
    assert f"{PAGES}/index.html#fn.add" in index["fixture::add"]


def test_unsupported_format_version_stops_the_build() -> None:
    doc = json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
    doc["format_version"] = 59
    with pytest.raises(ExtensionError, match="format version 59.*reads version 60"):
        Crate(doc)


def test_unlinked_crates_render_as_text(tmp_path) -> None:
    site = build(tmp_path, conf="rustdoc_unlinked_crates = ['alloc']")
    assert site.result.returncode == 0, site.result.stdout + site.result.stderr
    client = links(site, f"{PAGES}/struct.Client")
    assert "String" not in client
    assert "https://doc.rust-lang.org/1.98.1/core/convert/trait.Into.html" in client["Into"]


def test_summary_resolves_reference_definitions() -> None:
    docs = "Use [Client].\n\nMore.\n\n[Client]: crate::Client"
    assert markdown.summary(docs, {"crate::Client": 5}) == f"Use [Client]({markdown.LINK_SCHEME}5)."


def test_glob_of_another_crate_is_a_reexport() -> None:
    doc = json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
    prelude = next(k for k, v in doc["index"].items() if v["name"] == "prelude")
    glob = doc["index"][str(doc["index"][prelude]["inner"]["module"]["items"][0])]["inner"]["use"]
    glob["id"] = None
    glob["source"] = "other::module"
    crate = Crate(doc)
    assert [use["inner"]["use"]["source"] for use in reexports(crate, int(prelude))] == ["other::module"]


def test_roles_that_dont_resolve_warn(tmp_path) -> None:
    site = build(tmp_path, index="{rust:struct}`Nope` and {rust:fn}`Client`")
    assert "rust:struct reference target not found: Nope" in site.result.stderr
    assert "rust:fn reference target not found: Client" in site.result.stderr


def fixture_item(doc: dict, name: str, kind: str) -> dict:
    return next(v for v in doc["index"].values() if v["name"] == name and kind in v["inner"])


@pytest.mark.parametrize(
    ("kind", "shown"), [("bang", "square!"), ("attr", "#[square]"), ("derive", "#[derive(square)]")]
)
def test_proc_macros_are_documented(tmp_path, kind: str, shown: str) -> None:
    doc = json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
    fixture_item(doc, "square", "macro")["inner"] = {"proc_macro": {"kind": kind, "helpers": []}}
    site = build(tmp_path, index="{rust:macro}`square`", doc=doc)
    assert site.result.returncode == 0, site.result.stdout + site.result.stderr
    assert shown in site.page(f"{PAGES}/index")


def test_headings_with_code_and_links(tmp_path) -> None:
    doc = json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
    fixture_item(doc, "Client", "struct")["docs"] = "A client.\n\n# Using [`Builder`](crate::Builder)\n\nText."
    site = build(tmp_path, doc=doc)
    assert site.result.returncode == 0, site.result.stdout + site.result.stderr
    assert '<p class="rubric" id="using-builder">' in site.html(f"{PAGES}/struct.Client")
    assert "struct.Builder.html" in links(site, f"{PAGES}/struct.Client")["Builder"]


@pytest.mark.parametrize(
    ("info", "language"),
    [
        ("", "rust"),
        ("no_run", "rust"),
        ("compile_fail,E0277", "rust"),
        ("toml", "toml"),
        # rustdoc shows a language Pygments doesn't know as plain code
        ("not-a-language", "text"),
    ],
)
def test_code_block_languages(info: str, language: str) -> None:
    assert markdown.code_language(info) == language


def test_links_rustdoc_couldnt_resolve_keep_their_text() -> None:
    assert markdown.prepare("See [gone](crate::Gone) or [this](Self::gone).", {}) == "See gone or this."
    assert markdown.prepare("See [the site](https://example.com).", {}) == "See [the site](https://example.com)."
    reference_style = "See [Gone] and [the other][gone2].\n\n[Gone]: crate::Gone\n[gone2]: Self::gone"
    assert markdown.prepare(reference_style, {}) == "See Gone and the other.\n"
    site = "See [the site].\n\n[the site]: https://example.com"
    assert markdown.prepare(site, {}) == site


def test_links_that_wrap_onto_the_next_line(tmp_path) -> None:
    doc = json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
    client = fixture_item(doc, "Client", "struct")
    client["docs"] = "A client. To change how long it waits, call [the timeout\nsetter](Self::set_timeout)."
    site = build(tmp_path, doc=doc)
    assert site.result.returncode == 0, site.result.stdout + site.result.stderr
    assert "#method.set_timeout" in links(site, f"{PAGES}/struct.Client")["the timeout setter"]


@pytest.mark.parametrize(
    ("abi", "shown"),
    [
        # as rustdoc's JSON format 60 records each ABI
        ({"C": {"unwind": False}}, 'extern "C"'),
        ({"C": {"unwind": True}}, 'extern "C-unwind"'),
        ({"System": {"unwind": False}}, 'extern "system"'),
    ],
)
def test_extern_abis(abi: dict, shown: str) -> None:
    header = {"is_const": False, "is_async": False, "is_unsafe": False, "abi": abi}
    assert render.text(render.header(header)).strip() == shown


def test_backticks_with_no_closing_run_leave_later_links_alone() -> None:
    assert markdown.prepare("A ` on its own, then [Client].", {"Client": 5}) == (
        f"A ` on its own, then [Client]({markdown.LINK_SCHEME}5)."
    )


def test_warning_blocks(tmp_path) -> None:
    doc = json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
    client = fixture_item(doc, "Client", "struct")
    # rustdoc's two forms: text right inside the div, and Markdown between blank lines
    client["docs"] = (
        'A client.\n\n<div class="warning">Not thread-safe.</div>\n\n'
        '<div class="warning">\n\nBuild it with [`Builder`](crate::Builder).\n\n```\nlet a = 1;\n```\n\n</div>'
    )
    site = build(tmp_path, doc=doc)
    assert site.result.returncode == 0, site.result.stdout + site.result.stderr
    page = site.html(f"{PAGES}/struct.Client")
    assert page.count('class="admonition warning"') == 2
    assert "Not thread-safe." in site.page(f"{PAGES}/struct.Client")
    assert "struct.Builder.html" in links(site, f"{PAGES}/struct.Client")["Builder"]
    assert '<div class="warning">' not in page
    # a code block shows the tag as it is
    code = '```html\n<div class="warning">\n```'
    assert markdown.prepare(code, {}) == code


def test_items_that_share_a_path(tmp_path) -> None:
    roles = (
        "{rust:field}`Counter::count`, {rust:method}`Counter::count`, {rust:fn}`edge::total`, {rust:mod}`edge::total`"
    )
    site = build(tmp_path, index=roles)
    assert site.result.returncode == 0, site.result.stdout + site.result.stderr
    with open(site.output / "objects.inv", "rb") as f:
        inventory = InventoryFile.load(f, "", lambda base, uri: uri)
    objects = {(kind, name) for kind, names in inventory.items() for name in names}
    for kind in ("field", "method"):
        assert (f"rust:{kind}", "fixture::edge::Counter::count") in objects
    for kind in ("function", "module"):
        assert (f"rust:{kind}", "fixture::edge::total") in objects


def test_code_blocks_in_blockquotes(site: Site) -> None:
    quoted = "> ```no_run\n> # let hidden = 1;\n> let quoted = 2;\n> ```\n>\n> [Client]"
    assert markdown.prepare(quoted, {"Client": 5}) == (
        f"> ```rust\n> let quoted = 2;\n> ```\n>\n> [Client]({markdown.LINK_SCHEME}5)"
    )
    counter = site.page(f"{PAGES}/edge/struct.Counter")
    assert "let quoted = 2;" in counter
    assert "quoted_hidden" not in counter


def test_reexported_enum_variants(site: Site) -> None:
    assert "pub use Level::Low;" in site.page(f"{PAGES}/edge/index")
    total = links(site, f"{PAGES}/edge/index")
    for label in ("Level::Low", "Low"):
        assert any("enum.Level.html#variant.Low" in href for href in total[label]), total.get(label)


def test_reference_links_without_a_definition(site: Site) -> None:
    text = "Count with [the counter][Counter] or [`Counter`][]."
    assert markdown.prepare(text, {"Counter": 2, "`Counter`": 2}) == (
        f"Count with [the counter]({markdown.LINK_SCHEME}2) or [`Counter`]({markdown.LINK_SCHEME}2)."
    )
    counter = links(site, f"{PAGES}/edge/struct.Counter")
    assert "the counter" in counter
    assert "[]" not in site.page(f"{PAGES}/edge/struct.Counter")


def test_signatures_use_reexported_names(site: Site) -> None:
    builder = site.page(f"{PAGES}/struct.Builder")
    assert "impl<T: Default> Builder<T>" in builder
    assert "ClientBuilder" not in builder


def test_crates_in_one_build_link_to_each_other(tmp_path) -> None:
    user = FIXTURE_JSON.with_name("user.json")
    site = build(
        tmp_path,
        index="```{toctree}\nref/rust/user/index\n```",
        conf=f"rustdoc_crates['user'] = {{'json': {str(user)!r}}}",
    )
    assert site.result.returncode == 0, site.result.stdout + site.result.stderr
    client = links(site, "ref/rust/user/index")["Client"]
    assert client
    assert all(href.endswith("fixture/struct.Client.html") and "docs.rs" not in href for href in client), client


def test_json_file_for_a_configured_target(tmp_path) -> None:
    host = tmp_path / "doc" / "mycrate.json"
    cross = tmp_path / "aarch64-unknown-linux-gnu" / "doc" / "mycrate.json"
    for path, mtime in ((host, 1_000), (cross, 2_000)):
        path.parent.mkdir(parents=True)
        path.write_text("{}", encoding="utf-8")
        os.utime(path, (mtime, mtime))
    # cargo writes under the target's triple when the Cargo config sets build.target
    assert json_file(tmp_path, "mycrate") == cross
    os.utime(host, (3_000, 3_000))
    assert json_file(tmp_path, "mycrate") == host
    with pytest.raises(ExtensionError, match="wrote no other.json"):
        json_file(tmp_path, "other")


def test_indented_code_blocks_are_rust(site: Site) -> None:
    assert markdown.prepare("Text.\n\n    # let hidden = 1;\n    let x = 2;\n\nMore.", {}) == (
        "Text.\n\n```rust\nlet x = 2;\n```\n\nMore."
    )
    # a list item's indented paragraph isn't code
    in_list = "- An item.\n\n    More about it."
    assert markdown.prepare(in_list, {}) == in_list
    counter = site.page(f"{PAGES}/edge/struct.Counter")
    assert "let indented = 2;" in counter
    assert "let hidden = 1;" not in counter


def test_repeated_headings_on_one_page(site: Site) -> None:
    edge = site.html(f"{PAGES}/edge/index")
    assert 'id="examples"' in edge
    assert 'id="examples-1"' in edge
    # each function's link goes to its own heading
    assert sorted(links(site, f"{PAGES}/edge/index")["the examples"]) == ["#examples", "#examples-1"]


def test_rustdoc_output_must_be_inside_the_source_folder(tmp_path) -> None:
    site = build(tmp_path, conf="rustdoc_output = ''")
    assert site.result.returncode != 0
    assert "rustdoc_output must be a folder inside the docs source folder, not ''" in site.result.stderr
