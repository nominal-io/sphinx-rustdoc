# sphinx-rustdoc

A Sphinx extension that builds an API reference for Rust crates from rustdoc's JSON output. The pages render in the site's theme, link to the rest of the docs, and go into the site's search and `objects.inv`.

[DESIGN.md](DESIGN.md) explains how it works and why it reads rustdoc's JSON.

## Use it

Install it from GitHub, and add it to `conf.py`:

```python
extensions = [..., "sphinx_rustdoc"]

rustdoc_crates = {
    # the Cargo package to document; the workspace is found from the docs folder
    "mycrate": {"package": "mycrate"},
}
```

Then add the crate's page to a toctree. Pages are written under `ref/rust/` in the source folder, one folder per crate, named as in Rust code: `my_crate` for the package `my-crate`.

````md
```{toctree}
ref/rust/mycrate/index
```
````

Add the output folder to `.gitignore`: each build writes it again.

Building the JSON runs `cargo rustdoc` on the package, with `RUSTC_BOOTSTRAP=1`, because rustdoc's JSON output is unstable. sphinx-rustdoc reads JSON format version 60, which Rust 1.98 writes, and stops the build on any other.

### Settings

| Setting | Default | Sets |
| --- | --- | --- |
| `rustdoc_crates` | `{}` | The crates to document. Each takes a `package` to build, or a `json` file built earlier, relative to `conf.py`. |
| `rustdoc_output` | `"ref/rust"` | The folder the pages are written to, inside the source folder. A build deletes any page there it didn't write. |
| `rustdoc_unlinked_crates` | `[]` | Crates whose items show as text, with no link to their docs |
| `rustdoc_crate_urls` | `{}` | Crates another project documents with sphinx-rustdoc, each with the URL of its pages, such as `{"mycrate_core": "/core/ref/rust/"}`. Links to their items go to those pages, as Sphinx's `dirhtml` builder serves them. |

### Link to items

The `rust` domain links to items by path, such as ``{rust:struct}`mycrate::Client` ``. The end of a path is enough when only one item of the role's type ends that way: ``{rust:struct}`Client` ``. A role that finds no item is a build warning. Roles: `any`, `mod`, `struct`, `enum`, `union`, `trait`, `type`, `fn`, `method`, `field`, `variant`, `const`, `static` and `macro`.

Items in other crates link to their docs: a crate in `rustdoc_crates` to its pages in the same build, a crate in `rustdoc_crate_urls` to its pages there, the standard library's to doc.rust-lang.org, and others to docs.rs.

## Develop

```shell
just setup
just test
```

The tests build pages from `tests/fixture/`, a crate with one of each case. Its JSON is committed as `tests/fixture/fixture.json`, so the tests need no Rust toolchain. After changing the fixture, or moving to a Rust release that writes another JSON format version, run `just fixture`.
