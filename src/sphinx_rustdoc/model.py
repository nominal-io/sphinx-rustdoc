"""Load a crate's rustdoc JSON, and work out where each public item is documented."""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from sphinx.errors import ExtensionError

SUPPORTED_FORMAT_VERSIONS = frozenset({60})

# Item kinds with a page of their own, and the start of the page's file name, as on docs.rs
PAGE_PREFIX = {"struct": "struct", "enum": "enum", "union": "union", "trait": "trait", "type_alias": "type"}

# Item kinds documented at a path of their own: a page, or an entry on their module's page. Others,
# such as an enum variant, are documented on their owner's page even when a `use` re-exports them.
OWN_PATH = frozenset({"module", *PAGE_PREFIX, "function", "constant", "static", "macro", "proc_macro"})

# docs.rs's file name prefix for each kind, for links to other crates' items
URL_PREFIX = {
    **PAGE_PREFIX,
    "function": "fn",
    "constant": "constant",
    "static": "static",
    "macro": "macro",
    "proc_macro": "macro",
    # how `paths` names another crate's attribute and derive macros
    "proc_attribute": "attr",
    "proc_derive": "derive",
    "trait_alias": "traitalias",
    "primitive": "primitive",
}

# rustdoc doesn't publish JSON for the standard library's crates; their docs are on doc.rust-lang.org
STD_CRATES = frozenset({"std", "core", "alloc", "proc_macro", "test"})


def kind_of(item: dict) -> str:
    return next(iter(item["inner"]))


@dataclass(frozen=True)
class Entry:
    """An item a module lists: one defined there, or one it re-exports."""

    name: str
    # the item; None when rustdoc couldn't resolve a re-export
    id: int | None
    # the `use` item, for a re-export
    use: dict | None = None


@dataclass(frozen=True)
class Member:
    """A field, variant or associated item, documented on its owner's page."""

    owner: int
    anchor: str
    path: str
    objtype: str


@dataclass(frozen=True)
class Impls:
    """A type's implementations, in the groups its page shows."""

    inherent: list[int]
    traits: list[int]
    derived: list[int]
    auto: list[int]


class Crate:
    """One crate's rustdoc JSON, with the public path of each item it documents."""

    def __init__(
        self, doc: dict, unlinked_crates: frozenset[str] = frozenset(), crate_urls: dict[str, str] | None = None
    ):
        version = doc.get("format_version")
        if version not in SUPPORTED_FORMAT_VERSIONS:
            # checked first: another format version's JSON may not have the fields read below
            name = doc.get("index", {}).get(str(doc.get("root")), {}).get("name", "the crate")
            supported = ", ".join(str(v) for v in sorted(SUPPORTED_FORMAT_VERSIONS))
            raise ExtensionError(
                f"sphinx-rustdoc: the rustdoc JSON for {name} is format version {version}, "
                f"and sphinx-rustdoc reads version {supported}. "
                "Build the JSON with a Rust toolchain that writes a supported version."
            )
        self.index: dict[str, dict] = doc["index"]
        self.root: int = doc["root"]
        self.name: str = self.index[str(self.root)]["name"]
        self.version: str | None = doc.get("crate_version")
        self.paths: dict[str, dict] = doc["paths"]
        # this crate's items by the path and kind rustdoc records, as other crates' JSON names them too
        self.by_path: dict[tuple[tuple[str, ...], str], int] = {
            (tuple(s["path"]), s["kind"]): int(i) for i, s in self.paths.items() if s["crate_id"] == 0
        }
        self.external_crates: dict[str, dict] = doc["external_crates"]
        self.unlinked_crates = unlinked_crates
        # crates another project publishes sphinx-rustdoc pages for, by name: where those pages are
        self.crate_urls: dict[str, str] = crate_urls or {}
        # the public path each documented item is shown at, crate name first
        self.canonical: dict[int, tuple[str, ...]] = {}
        # each public module's entries, in source order
        self.listings: dict[int, list[Entry]] = {}
        self.members: dict[int, Member] = {}
        # each owner's member anchors so far, as (owner, anchor)
        self._anchors: set[tuple[int, str]] = set()
        self._walk()
        self._collect_members()

    def item(self, item_id: int | None) -> dict | None:
        return None if item_id is None else self.index.get(str(item_id))

    def display_name(self, item_id: int) -> str:
        """The item's name where it's documented, which a re-export can change."""
        if item_id in self.canonical:
            return self.canonical[item_id][-1]
        return self.index[str(item_id)]["name"]

    # -- public paths ------------------------------------------------------------------------------

    def _walk(self) -> None:
        # Items defined in a public module are documented there, even when a shallower module
        # re-exports them. An item only reachable through re-exports is documented at the shallowest.
        order: list[int] = []
        self._place(self.root, (self.name,), order)
        position = 0
        while position < len(order):
            self._assign_defined(order[position], order)
            position += 1
        # Then re-exports, from the shallowest module down, including modules placed along the way, so
        # an item re-exported more than once gets the shallowest path
        queue: list[tuple[int, int, int]] = []
        queued = 0
        while True:
            for position in range(queued, len(order)):
                heapq.heappush(queue, (len(self.canonical[order[position]]), position, order[position]))
            queued = len(order)
            if not queue:
                break
            _, _, module_id = heapq.heappop(queue)
            self._assign_defined(module_id, order)
            path = self.canonical[module_id]
            for entry in self.listings[module_id]:
                target = self.item(entry.id)
                if entry.use is None or target is None or target["crate_id"] != 0 or entry.id in self.canonical:
                    continue
                if kind_of(target) == "module":
                    self._place(entry.id, (*path, entry.name), order)
                elif kind_of(target) in OWN_PATH:
                    self.canonical[entry.id] = (*path, entry.name)

    def _place(self, module_id: int, path: tuple[str, ...], order: list[int]) -> None:
        self.canonical[module_id] = path
        self.listings[module_id] = self._entries(module_id, frozenset())
        order.append(module_id)

    def _assign_defined(self, module_id: int, order: list[int]) -> None:
        path = self.canonical[module_id]
        for entry in self.listings[module_id]:
            if entry.use is not None or entry.id in self.canonical:
                continue
            if kind_of(self.index[str(entry.id)]) == "module":
                self._place(entry.id, (*path, entry.name), order)
            else:
                self.canonical[entry.id] = (*path, entry.name)

    def _entries(self, module_id: int, seen: frozenset[int]) -> list[Entry]:
        entries: list[Entry] = []
        for child_id in self.index[str(module_id)]["inner"]["module"]["items"]:
            child = self.item(child_id)
            if child is None:
                continue
            kind = kind_of(child)
            if kind == "impl":
                continue
            if kind != "use":
                entries.append(Entry(child["name"], child_id))
                continue
            use = child["inner"]["use"]
            if not use["is_glob"]:
                entries.append(Entry(use["name"], use["id"], child))
                continue
            target = self.item(use["id"])
            if target is not None and kind_of(target) == "module" and use["id"] not in seen:
                for entry in self._entries(use["id"], seen | {module_id}):
                    entries.append(Entry(entry.name, entry.id, child))
            else:
                # a glob of another crate's module, or of an enum's variants: listed as the `use` itself
                entries.append(Entry("*", None, child))
        return entries

    # -- members -----------------------------------------------------------------------------------

    def _collect_members(self) -> None:
        for item_id, path in list(self.canonical.items()):
            item = self.index[str(item_id)]
            kind = kind_of(item)
            owner = "::".join(path)
            if kind in ("struct", "union"):
                for field_id in self.fields(item_id):
                    name = self.index[str(field_id)]["name"]
                    self.members[field_id] = Member(item_id, f"structfield.{name}", f"{owner}::{name}", "field")
            if kind == "enum":
                for variant_id in item["inner"]["enum"]["variants"]:
                    variant = self.index[str(variant_id)]
                    vname = variant["name"]
                    self.members[variant_id] = Member(item_id, f"variant.{vname}", f"{owner}::{vname}", "variant")
                    for field_id in self.variant_fields(variant_id):
                        fname = self.index[str(field_id)]["name"]
                        self.members[field_id] = Member(
                            item_id, f"variant.{vname}.field.{fname}", f"{owner}::{vname}::{fname}", "field"
                        )
            if kind in ("struct", "union", "enum"):
                for impl_id in self.impls(item_id).inherent:
                    for member_id in self.impl_items(impl_id, public_only=True):
                        self._add_member(item_id, owner, member_id)
            if kind == "trait":
                for member_id in item["inner"]["trait"]["items"]:
                    self._add_member(item_id, owner, member_id)

    def _add_member(self, owner_id: int, owner: str, member_id: int) -> None:
        member = self.index[str(member_id)]
        kind = kind_of(member)
        anchor_kind, objtype = {
            "function": ("method", "method"),
            "assoc_const": ("associatedconstant", "associated_constant"),
            "assoc_type": ("associatedtype", "associated_type"),
        }.get(kind, (kind, kind))
        name = member["name"]
        # inherent impls for different generic arguments can each define a method of the same name;
        # number the later ones, as rustdoc does, so each keeps its own anchor
        base = anchor = f"{anchor_kind}.{name}"
        count = 0
        while (owner_id, anchor) in self._anchors:
            count += 1
            anchor = f"{base}-{count}"
        self._anchors.add((owner_id, anchor))
        self.members[member_id] = Member(owner_id, anchor, f"{owner}::{name}", objtype)

    # -- structure ---------------------------------------------------------------------------------

    def fields(self, item_id: int) -> list[int]:
        """A struct's or union's public named fields."""
        inner = self.index[str(item_id)]["inner"]
        kind = kind_of(self.index[str(item_id)])
        if kind == "union":
            return [f for f in inner["union"]["fields"] if self._public(f)]
        shape = inner["struct"]["kind"]
        if isinstance(shape, dict) and "plain" in shape:
            return [f for f in shape["plain"]["fields"] if self._public(f)]
        return []

    def variant_fields(self, variant_id: int) -> list[int]:
        shape = self.index[str(variant_id)]["inner"]["variant"]["kind"]
        if isinstance(shape, dict) and "struct" in shape:
            return list(shape["struct"]["fields"])
        return []

    def _public(self, item_id: int) -> bool:
        item = self.item(item_id)
        return item is not None and item["visibility"] == "public"

    def impls(self, item_id: int) -> Impls:
        item = self.index[str(item_id)]
        groups = Impls([], [], [], [])
        for impl_id in item["inner"][kind_of(item)].get("impls", []):
            impl = self.item(impl_id)
            if impl is None:
                continue
            inner = impl["inner"]["impl"]
            if inner["blanket_impl"] is not None:
                continue
            if inner["is_synthetic"]:
                groups.auto.append(impl_id)
            elif inner["trait"] is None:
                groups.inherent.append(impl_id)
            elif "automatically_derived" in impl["attrs"]:
                groups.derived.append(impl_id)
            else:
                groups.traits.append(impl_id)
        return groups

    def impl_items(self, impl_id: int, public_only: bool) -> list[int]:
        items = self.index[str(impl_id)]["inner"]["impl"]["items"]
        return [i for i in items if self.item(i) is not None and (not public_only or self._public(i))]

    # -- links -------------------------------------------------------------------------------------

    def path_of(self, item_id: int | None) -> str | None:
        """The documented path of a local item or member, or None if it isn't documented."""
        if item_id in self.canonical:
            return "::".join(self.canonical[item_id])
        if item_id in self.members:
            return self.members[item_id].path
        return None

    def external_url(self, item_id: int | None) -> str | None:
        """A link to another crate's item, on its own docs."""
        if item_id is None:
            return None
        summary = self.paths.get(str(item_id))
        if summary is None or summary["crate_id"] == 0:
            return None
        crate = self.external_crates.get(str(summary["crate_id"]))
        if crate is None or crate["name"] in self.unlinked_crates:
            return None
        if crate["name"] in self.crate_urls:
            return pages_url(self.crate_urls[crate["name"]], summary["path"], summary["kind"])
        root = crate.get("html_root_url")
        if not root:
            if crate["name"] in STD_CRATES:
                root = "https://doc.rust-lang.org/stable/"
            else:
                root = f"https://docs.rs/{crate['name']}/latest/"
        if not root.endswith("/"):
            root += "/"
        path, kind = summary["path"], summary["kind"]
        if kind == "module":
            return f"{root}{'/'.join(path)}/index.html"
        if kind == "variant":
            *modules, enum, variant = path
            return f"{root}{'/'.join(modules)}/enum.{enum}.html#variant.{variant}"
        prefix = URL_PREFIX.get(kind)
        if prefix is None:
            return None
        *modules, name = path
        return f"{root}{'/'.join(modules)}/{prefix}.{name}.html"


def pages_url(root: str, path: list[str], kind: str) -> str | None:
    """An item's place in another project's sphinx-rustdoc pages, as Sphinx's dirhtml builder serves
    them: a page for each module and each kind in PAGE_PREFIX, and an entry on its module's page,
    anchored as the domain anchors it, for a module-level item."""
    if not root.endswith("/"):
        root += "/"
    if kind == "module":
        return f"{root}{'/'.join(path)}/"
    if kind == "variant":
        *modules, enum, variant = path
        return f"{root}{'/'.join(modules)}/enum.{enum}/#variant.{variant}"
    *modules, name = path
    if kind in PAGE_PREFIX:
        return f"{root}{'/'.join(modules)}/{PAGE_PREFIX[kind]}.{name}/"
    prefix = URL_PREFIX.get(kind)
    if prefix is None:
        return None
    return f"{root}{'/'.join(modules)}/#{prefix}.{name}"
