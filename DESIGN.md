# sphinx-rustdoc design

sphinx-rustdoc is a Sphinx extension that builds an API reference for Rust crates from rustdoc's JSON
output. The pages render in the site's theme, link to the rest of the docs, and go into the site's
search and `objects.inv`.

## Why rustdoc JSON

`cargo doc` runs the compiler's front end: it expands macros, resolves names, checks types and
works out trait impls. Its HTML and JSON renderers read the same model, so the JSON has what
docs.rs shows:

- every public item, with its doc comment as Markdown and its intra-doc links resolved to items
- signatures as typed trees, with each path resolved to an item, in this crate or another
- all impls: inherent, trait, derived, blanket and auto-trait (`Send`, `Sync` and so on)

Tools that parse source with `syn` see none of that resolution: no macro-generated items, no
derived or blanket impls, and paths only as written.

### Costs

- The JSON format is unstable. It needs nightly, or `RUSTC_BOOTSTRAP=1` on stable, and its
  `format_version` changes between Rust releases. sphinx-rustdoc supports a set of format versions
  and stops the build, naming the version, on any other. Pin the Rust toolchain that builds the docs.
- Generating it compiles the crate's dependencies, as `cargo doc` does.
- The JSON is per target (`target.triple`). `#[cfg]`-gated items follow the target it was built on.

## What a repo sets up

```python
extensions = [..., "sphinx_rustdoc"]

rustdoc_crates = {
    # a label: the Cargo package to document; the workspace is found from the docs folder
    "mycrate": {"package": "mycrate"},
}
rustdoc_output = "ref/rust"  # generated pages, under the source folder; not committed
```

````md
```{toctree}
ref/rust/mycrate/index
```
````

When the build starts, sphinx-rustdoc runs, for each crate:

```shell
RUSTC_BOOTSTRAP=1 cargo rustdoc -p <package> --lib -- -Z unstable-options --output-format json
```

A crate can name a JSON file with `json` in place of `package`, so CI can build it in an earlier step
or cache it. Cargo skips the compile when nothing changed, so live preview stays quick.

## Pages

One page per module, struct, enum, trait, union and type alias, at the item's public path:
`ref/rust/mycrate/struct.Client` for `mycrate::Client`. Free functions, constants, statics and
macros are documented on their module's page, since most are short.

A type's page has, in order:

1. the declaration, with fields or variants and their docs
2. inherent methods (`impl Client { ... }`)
3. trait implementations written in the crate, each with its methods
4. derived implementations, as one line: `Clone`, `Debug`, `PartialEq`
5. auto traits, as one line: `Send`, `Sync`, `Unpin`, `UnwindSafe`, `RefUnwindSafe`

Blanket implementations (`From<T>`, `Into`, `Any`) are left out: they apply to nearly every type.

Module pages list their items by kind with each one's first paragraph, like rustdoc's module pages,
and list re-exports.

### Public paths

rustdoc JSON gives each item its defining path (`mycrate::client::inner::Client`), not the path
users import (`mycrate::Client`). sphinx-rustdoc walks the crate from its root through public
modules and `pub use` items, as rustdoc's HTML renderer does:

- An item reached only through re-exports is documented at the shallowest re-export's path, under
  the name it's re-exported as.
- An item in a public module is documented there; other re-exports of it link to that page.
- `#[doc(hidden)]` items are left out, since rustdoc leaves them out of the JSON.
- Glob re-exports (`pub use x::*`) are expanded.

## Rendering

### Doc comments

Doc comments are Markdown, parsed with MyST. Intra-doc links (``[`Self::get`]``, ``[`Config`]``)
come resolved in the item's `links` map; each becomes a cross-reference to the target's page. Code
blocks with rustdoc attributes (`rust,no_run`, `ignore`, a bare `no_run`) become `rust` blocks,
without the lines rustdoc hides (`# ` at the start). Headings in doc comments become rubrics, with
the ids rustdoc gives them, so a doc comment's links to its own headings work. A heading repeated
on the same page, such as two functions' `# Examples`, is numbered as rustdoc numbers a repeat:
`examples-1`. rustdoc's warning
blocks (`<div class="warning">`) become `warning` admonitions, with the Markdown inside them parsed
like the rest.

### Signatures

Signatures render from the JSON's type tree, not from source text, so every path is resolved and
shown as users write it: `fn config(&self) -> Config`, not the source's `crate::config::Config`.
The renderer covers generics and bounds, `where` clauses, lifetimes, references, `impl Trait`,
`dyn Trait`, tuples, slices, arrays, function pointers, qualified paths (`<T as Trait>::Output`),
and `async`, `const` and `unsafe`.

### Links to other crates

A path into another crate links to that crate's docs:

1. the crate's pages in the same build, if it's in `rustdoc_crates`, found by the path and kind
   both crates' JSON records for the item
2. the crate's `html_root_url`, which the JSON records, as it does for the standard library
3. otherwise docs.rs: `https://docs.rs/<crate>/latest/<path>/<kind>.<Name>.html`, built from the
   JSON's path and kind for the item

`rustdoc_unlinked_crates` lists crates whose paths render as text, with no link, such as a crate
whose docs.rs build failed.

## The `rust` domain

sphinx-rustdoc registers a `rust` Sphinx domain, so the pages are ordinary Sphinx objects:

- Object types: module, struct, enum, union, trait, type alias, function, method, field, variant,
  constant, static, macro, associated type and associated constant.
- Roles for writing guides: ``{rust:struct}`mycrate::Client` ``, or ``{rust:struct}`Client` `` when
  only one struct's path ends that way. A role that finds no item is a build warning.
- Each object goes into `objects.inv`, so another site can link to it through intersphinx.
- Pages produce standard `desc` nodes, with `dl.rust` classes.

## Styling

sphinx-rustdoc ships no CSS. Its entries are Sphinx's standard description nodes, so a theme that
styles API entries styles them, and a theme can target Rust entries with `dl.rust`. In signatures,
keywords, unlinked types (primitives, generics, lifetimes) and parameter names carry Pygments'
token classes: `k`, `kt` and `n`. Every link in a signature is a type.

## Testing

- A fixture crate in `tests/fixture/` covers each rendering case: re-exports through private
  modules, globs, generics and `where` clauses, `impl Trait`, async, derived and blanket impls,
  intra-doc links and links to another crate.
- Its JSON is committed, so tests run without a Rust toolchain. A recipe regenerates it when the
  supported format version moves.
- Tests build the fixture's pages with Sphinx and check the HTML and `objects.inv`.
