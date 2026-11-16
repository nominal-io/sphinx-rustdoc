"""The `rust` Sphinx domain, and the directives that render a generated page's parts."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any, ClassVar

from docutils import nodes
from docutils.nodes import Element, Node
from docutils.statemachine import StringList
from sphinx import addnodes
from sphinx.domains import Domain, ObjType
from sphinx.roles import XRefRole
from sphinx.util.docutils import SphinxDirective
from sphinx.util.nodes import make_refnode

from . import markdown, render
from .model import URL_PREFIX, Crate, kind_of

# Kinds documented in full on their module's page, rather than on a page of their own
MODULE_LEVEL = ("function", "constant", "static", "macro", "proc_macro")

# Kinds a module page lists in another kind's section
SECTION_OF = {"proc_macro": "macro"}

AUTO_TRAITS = ("Send", "Sync", "Unpin", "UnwindSafe", "RefUnwindSafe")

# Crates loaded for this build, by name. Directives read them while Sphinx reads the generated pages.
LOADED: dict[str, Crate] = {}

OBJTYPE = {
    "module": "module",
    "struct": "struct",
    "enum": "enum",
    "union": "union",
    "trait": "trait",
    "type_alias": "type",
    "function": "function",
    "constant": "constant",
    "static": "static",
    "macro": "macro",
    "proc_macro": "macro",
}

# The role each object type is linked with
ROLE = {
    "module": "mod",
    "struct": "struct",
    "enum": "enum",
    "union": "union",
    "trait": "trait",
    "type": "type",
    "function": "fn",
    "method": "method",
    "field": "field",
    "variant": "variant",
    "constant": "const",
    "static": "static",
    "macro": "macro",
    "associated_type": "type",
    "associated_constant": "const",
}

# Module page sections, in order: the kind, its heading, and whether its items are listed or shown in full
SECTIONS = [
    ("module", "Modules", "list"),
    ("macro", "Macros", "full"),
    ("struct", "Structs", "list"),
    ("enum", "Enums", "list"),
    ("union", "Unions", "list"),
    ("trait", "Traits", "list"),
    ("type_alias", "Type aliases", "list"),
    ("function", "Functions", "full"),
    ("constant", "Constants", "full"),
    ("static", "Statics", "full"),
]


class RustXRefRole(XRefRole):
    innernodeclass = nodes.literal

    def __init__(self) -> None:
        # a role whose item isn't found warns, so a typo fails a build run with -W
        super().__init__(warn_dangling=True)


class RustDomain(Domain):
    """Rust items, linked by path, such as `mycrate::Client`."""

    name = "rust"
    label = "Rust"
    object_types: ClassVar[dict[str, ObjType]] = {
        name: ObjType(name.replace("_", " "), "any", role) for name, role in ROLE.items()
    }
    roles: ClassVar[dict[str, XRefRole]] = {role: RustXRefRole() for role in {"any", *ROLE.values()}}
    initial_data: ClassVar[dict[str, Any]] = {"objects": {}}
    # objects are keyed by path and object type; an environment saved with an older layout is rebuilt
    data_version = 1

    @property
    def objects(self) -> dict[tuple[str, str], tuple[str, str]]:
        """Each object's document and anchor, by its path and object type.

        Items of different kinds can share a path, such as a field and a method, or a module and a
        function.
        """
        return self.data.setdefault("objects", {})

    def note_object(self, path: str, objtype: str, node_id: str) -> None:
        self.objects[path, objtype] = (self.env.current_document.docname, node_id)

    def clear_doc(self, docname: str) -> None:
        for key, (doc, _) in list(self.objects.items()):
            if doc == docname:
                del self.objects[key]

    def merge_domaindata(self, docnames: Iterable[str], otherdata: dict[str, Any]) -> None:
        wanted = set(docnames)
        for key, entry in otherdata["objects"].items():
            if entry[0] in wanted:
                self.objects[key] = entry

    def find(self, target: str, role: str = "any") -> list[tuple[str, str]]:
        """The objects a target names, as (path, object type): those with its full path, or else
        those whose path ends with it, if only one path ends that way.

        A role other than `any` only finds objects of the types it links.
        """
        target = target.strip().removeprefix("crate::")
        fits = [(path, objtype) for path, objtype in self.objects if role == "any" or ROLE[objtype] == role]
        exact = [key for key in fits if key[0] == target]
        if exact:
            return exact
        ends = [key for key in fits if key[0].endswith(f"::{target}")]
        return ends if len({path for path, _ in ends}) == 1 else []

    def resolve_xref(self, env, fromdocname, builder, typ, target, node, contnode) -> Element | None:
        found = self.find(target, typ)
        if not found:
            return None
        docname, node_id = self.objects[found[0]]
        return make_refnode(builder, fromdocname, docname, node_id, contnode, found[0][0])

    def resolve_any_xref(self, env, fromdocname, builder, target, node, contnode) -> list[tuple[str, Element]]:
        # more than one is ambiguous, such as a field and a method of the same name; Sphinx warns
        out = []
        for path, objtype in self.find(target):
            docname, node_id = self.objects[path, objtype]
            out.append((f"rust:{ROLE[objtype]}", make_refnode(builder, fromdocname, docname, node_id, contnode, path)))
        return out

    def get_objects(self) -> Iterator[tuple[str, str, str, str, str, int]]:
        for (path, objtype), (docname, node_id) in self.objects.items():
            yield path, path, objtype, docname, node_id, 1


# -- directives -----------------------------------------------------------------------------------


class RustDirective(SphinxDirective):
    """Renders part of a generated page from an item: `crate:id`, as the page names it."""

    required_arguments = 1
    optional_arguments = 1
    has_content = False

    def target(self) -> tuple[Crate, int]:
        crate_name, _, item_id = self.arguments[0].partition(":")
        crate = LOADED.get(crate_name)
        if crate is None:
            raise self.error(f"sphinx-rustdoc: no crate {crate_name!r} in rustdoc_crates")
        return crate, int(item_id)

    @property
    def domain(self) -> RustDomain:
        return self.env.domains["rust"]

    # -- links --

    def link(self, crate: Crate, item_id: int | None, children: list[Node]) -> Node:
        """A link to an item: in these docs, in another crate's docs, or plain text."""
        path = crate.path_of(item_id)
        if path is not None:
            # the item's own role, since items of different kinds can share a path
            member = crate.members.get(item_id)
            objtype = member.objtype if member else OBJTYPE.get(kind_of(crate.index[str(item_id)]), "")
            xref = addnodes.pending_xref(
                "", refdomain="rust", reftype=ROLE.get(objtype, "any"), reftarget=path, refexplicit=True, refwarn=False
            )
            xref += children
            return xref
        # an item of another crate this build documents links to its page here, not to docs.rs
        other = in_loaded_crate(crate, item_id)
        if other is not None:
            return self.link(*other, children)
        url = crate.external_url(item_id)
        if url is not None:
            reference = nodes.reference("", "", refuri=url, internal=False)
            reference += children
            return reference
        inline = nodes.inline()
        inline += children
        return inline

    def placeholder(self, crate: Crate, destination: str, children: list[Node], anchors: dict[str, str]) -> Node | None:
        """The real link for a placeholder destination from `markdown.prepare`, or None.

        `anchors` maps a heading's id, as the doc comment links to it, to the id it has on the page.
        """
        if destination.startswith(markdown.LINK_SCHEME):
            return self.link(crate, int(destination.removeprefix(markdown.LINK_SCHEME)), children)
        if destination.startswith(markdown.ANCHOR_SCHEME):
            anchor = destination.removeprefix(markdown.ANCHOR_SCHEME)
            reference = nodes.reference("", "", refuri=f"#{anchors.get(anchor, anchor)}")
            reference["internal"] = True
            reference += children
            return reference
        return None

    def resolve_placeholders(self, crate: Crate, node: Element, anchors: dict[str, str]) -> None:
        for xref in list(node.findall(addnodes.pending_xref)):
            replacement = self.placeholder(crate, xref.get("reftarget", ""), xref.children, anchors)
            if replacement is not None:
                xref.replace_self(replacement)
        for reference in list(node.findall(nodes.reference)):
            replacement = self.placeholder(crate, reference.get("refuri", ""), reference.children, anchors)
            if replacement is not None:
                reference.replace_self(replacement)

    def parse(self, crate: Crate, text: str) -> list[Node]:
        if not text.strip():
            return []
        holder = nodes.Element()
        self.state.nested_parse(StringList(text.splitlines(), source=self.env.docname), 0, holder)
        # a doc comment's headings become rubrics; give each the id rustdoc would, for links to it.
        # Items on one page can share a heading, so a repeat is numbered, as rustdoc does: examples-1.
        document = self.state.document
        anchors: dict[str, str] = {}
        for rubric in holder.findall(nodes.rubric):
            base = markdown.heading_id(rubric.astext())
            if not base:
                continue
            heading_id, count = base, 0
            while heading_id in document.ids:
                count += 1
                heading_id = f"{base}-{count}"
            rubric["ids"].append(heading_id)
            document.ids[heading_id] = rubric
            anchors.setdefault(base, heading_id)
        self.resolve_placeholders(crate, holder, anchors)
        return list(holder.children)

    def docs(self, crate: Crate, item: dict) -> list[Node]:
        out: list[Node] = []
        deprecation = item.get("deprecation")
        if deprecation:
            title = "Deprecated" + (f" since {deprecation['since']}" if deprecation.get("since") else "")
            admonition = nodes.admonition(classes=["deprecated"])
            admonition += nodes.title(title, title)
            admonition += self.parse(crate, deprecation.get("note") or "")
            out.append(admonition)
        return out + self.parse(crate, markdown.prepare(item.get("docs"), item.get("links", {})))

    def signature_nodes(self, crate: Crate, toks: render.Toks) -> list[Node]:
        out: list[Node] = []
        for tok in toks:
            match tok.kind:
                case "keyword":
                    out.append(addnodes.desc_sig_keyword(tok.text, tok.text))
                case "name":
                    out.append(addnodes.desc_name(tok.text, tok.text))
                case "punct":
                    out.append(addnodes.desc_sig_punctuation(tok.text, tok.text))
                case "space":
                    out.append(addnodes.desc_sig_space())
                case "type":
                    out.append(addnodes.desc_sig_keyword_type(tok.text, tok.text))
                case "param":
                    out.append(addnodes.desc_sig_name(tok.text, tok.text))
                case "link":
                    # an item's own name becomes the one it's documented under, which a re-export can
                    # change, as readers import it; a `use` line's path stays as written
                    item = crate.item(tok.target)
                    text = tok.text
                    if tok.target in crate.canonical and item is not None and tok.text == item["name"]:
                        text = crate.display_name(tok.target)
                    # wrapped, since themes treat a link directly in a signature as a [source] link
                    wrapper = nodes.inline()
                    wrapper += self.link(crate, tok.target, [nodes.Text(text)])
                    out.append(wrapper)
                case _:
                    out.append(nodes.Text(tok.text))
        return out

    def describe(
        self,
        crate: Crate,
        objtype: str,
        toks: render.Toks,
        content: list[Node],
        path: str | None = None,
        anchor: str | None = None,
        toc_name: str | None = None,
        page: bool = False,
    ) -> addnodes.desc:
        """A description: the signature, and under it the content. With a path, it's an object.

        The item a page is about links to the page itself, and stays out of the page's contents,
        where its title already is.
        """
        desc = addnodes.desc(domain="rust", objtype=objtype, desctype=objtype, classes=["rust", objtype])
        sig = addnodes.desc_signature("", "")
        sig += self.signature_nodes(crate, toks)
        if path is not None and anchor is not None:
            sig["ids"].append(anchor)
            sig["fullname"] = path
            if not page:
                sig["_toc_parts"] = tuple(path.split("::"))
                sig["_toc_name"] = toc_name or path.rsplit("::", 1)[-1]
            self.domain.note_object(path, objtype, "" if page else anchor)
        desc += sig
        body = addnodes.desc_content()
        body += content
        desc += body
        return desc

    def member(self, crate: Crate, member_id: int, extra: list[Node] | None = None) -> addnodes.desc:
        item = crate.index[str(member_id)]
        member = crate.members.get(member_id)
        toks = render.signature(crate, member_id)
        content = self.docs(crate, item) + (extra or [])
        if member is None:
            return self.describe(crate, kind_of(item), toks, content)
        name = member.path.rsplit("::", 1)[-1]
        toc_name = f"{name}()" if member.objtype == "method" else name
        return self.describe(crate, member.objtype, toks, content, member.path, member.anchor, toc_name)


class ItemDirective(RustDirective):
    """An item's declaration and docs, at the top of its page or in its module's page."""

    def run(self) -> list[Node]:
        crate, item_id = self.target()
        item = crate.index[str(item_id)]
        kind = kind_of(item)
        path = crate.path_of(item_id)
        if kind == "module":
            self.domain.note_object(path, "module", "")
            return self.docs(crate, item)
        objtype = OBJTYPE.get(kind, kind)
        name = crate.display_name(item_id)
        # module-level items share their module's page, so each needs its own anchor
        anchor = f"{URL_PREFIX[kind]}.{name}" if kind in MODULE_LEVEL else objtype
        content = self.docs(crate, item)
        if kind == "macro":
            source = nodes.literal_block(item["inner"]["macro"], item["inner"]["macro"], language="rust")
            content = [source, *content]
        toc_name = f"{name}()" if kind == "function" else name
        toks = render.signature(crate, item_id, name)
        page = kind not in MODULE_LEVEL
        return [self.describe(crate, objtype, toks, content, path, anchor, toc_name, page)]


class MembersDirective(RustDirective):
    """One group of an item's members: fields, variants, methods, trait items or implementations."""

    def run(self) -> list[Node]:
        crate, item_id = self.target()
        group = self.arguments[1] if len(self.arguments) > 1 else ""
        item = crate.index[str(item_id)]
        match group:
            case "fields":
                return [self.member(crate, f) for f in crate.fields(item_id)]
            case "variants":
                out = []
                for variant_id in item["inner"]["enum"]["variants"]:
                    fields = [self.member(crate, f) for f in crate.variant_fields(variant_id)]
                    out.append(self.member(crate, variant_id, fields))
                return out
            case "methods":
                return [self.impl(crate, i, members=True) for i in crate.impls(item_id).inherent]
            case "required" | "provided":
                return [self.member(crate, m) for m in self.trait_items(crate, item, group)]
            case "traits":
                return self.trait_impls(crate, item_id)
            case "implementors":
                return [
                    self.describe(crate, "impl", render.impl_header(crate, i), [])
                    for i in item["inner"]["trait"]["implementations"]
                    if crate.item(i) is not None
                ]
        raise self.error(f"sphinx-rustdoc: unknown member group {group!r}")

    @staticmethod
    def trait_items(crate: Crate, item: dict, group: str) -> list[int]:
        required, provided = [], []
        for member_id in item["inner"]["trait"]["items"]:
            member = crate.item(member_id)
            if member is None:
                continue
            (provided if has_default(member) else required).append(member_id)
        return required if group == "required" else provided

    def impl(self, crate: Crate, impl_id: int, members: bool) -> addnodes.desc:
        impl = crate.index[str(impl_id)]
        content = self.parse(crate, markdown.prepare(impl.get("docs"), impl.get("links", {})))
        for member_id in crate.impl_items(impl_id, public_only=members):
            if members:
                content.append(self.member(crate, member_id))
            else:
                member = crate.index[str(member_id)]
                content.append(
                    self.describe(crate, kind_of(member), render.signature(crate, member_id), self.docs(crate, member))
                )
        return self.describe(crate, "impl", render.impl_header(crate, impl_id), content)

    def trait_impls(self, crate: Crate, item_id: int) -> list[Node]:
        impls = crate.impls(item_id)
        out: list[Node] = [self.impl(crate, i, members=False) for i in impls.traits]
        # the stable auto traits, in docs.rs's order; the others are compiler internals
        auto = {crate.index[str(i)]["inner"]["impl"]["trait"]["path"]: i for i in impls.auto}
        auto_ids = [auto[name] for name in AUTO_TRAITS if name in auto]
        for label, ids in (("Derived", impls.derived), ("Auto traits", auto_ids)):
            if not ids:
                continue
            paragraph = nodes.paragraph()
            paragraph += nodes.strong(label, label)
            paragraph += nodes.Text(": ")
            for i, impl_id in enumerate(ids):
                inner = crate.index[str(impl_id)]["inner"]["impl"]
                if i:
                    paragraph += nodes.Text(", ")
                trait = inner["trait"]
                name = ("!" if inner["is_negative"] else "") + trait["path"].rsplit("::", 1)[-1]
                paragraph += self.link(crate, trait["id"], [nodes.literal(name, name)])
            out.append(paragraph)
        return out


class SummaryDirective(RustDirective):
    """A module's items of one kind, each with the first paragraph of its docs."""

    def run(self) -> list[Node]:
        crate, module_id = self.target()
        kind = self.arguments[1]
        lines = []
        for entry_id in documented_here(crate, module_id, kind):
            item = crate.index[str(entry_id)]
            name = crate.display_name(entry_id)
            summary = markdown.summary(item.get("docs"), item.get("links", {}))
            lines.append(f"- [`{name}`]({markdown.LINK_SCHEME}{entry_id})" + (f": {summary}" if summary else ""))
        return self.parse(crate, "\n".join(lines))


class ReexportsDirective(RustDirective):
    """A module's re-exports of items documented elsewhere, as `pub use` lines."""

    def run(self) -> list[Node]:
        crate, module_id = self.target()
        out: list[Node] = []
        for use in reexports(crate, module_id):
            out.append(self.describe(crate, "use", render.reexport(use), self.docs(crate, use)))
        return out


def has_default(member: dict) -> bool:
    """Whether a trait item is provided: a method with a body, or an associated item with a default."""
    kind = kind_of(member)
    inner = member["inner"][kind]
    if kind == "function":
        return inner["has_body"]
    if kind == "assoc_type":
        return inner["type"] is not None
    if kind == "assoc_const":
        return inner["value"] is not None
    return False


def in_loaded_crate(crate: Crate, item_id: int | None) -> tuple[Crate, int] | None:
    """Another crate's item as (that crate, its id there), if this build documents that crate too."""
    summary = crate.paths.get(str(item_id)) if item_id is not None else None
    if summary is None or summary["crate_id"] == 0:
        return None
    other = LOADED.get(crate.external_crates.get(str(summary["crate_id"]), {}).get("name", ""))
    if other is None or other is crate:
        return None
    other_id = other.by_path.get((tuple(summary["path"]), summary["kind"]))
    return None if other_id is None else (other, other_id)


def documented_here(crate: Crate, module_id: int, kind: str) -> list[int]:
    """The items of one kind a module's page documents, in source order."""
    path = crate.canonical[module_id]
    out = []
    for entry in crate.listings[module_id]:
        item = crate.item(entry.id)
        if item is None or item["crate_id"] != 0 or SECTION_OF.get(kind_of(item), kind_of(item)) != kind:
            continue
        if crate.canonical.get(entry.id) == (*path, entry.name) and entry.id not in out:
            out.append(entry.id)
    return out


def reexports(crate: Crate, module_id: int) -> list[dict]:
    """The `use` items a module lists that re-export something documented elsewhere."""
    path = crate.canonical[module_id]
    out: list[dict] = []
    for entry in crate.listings[module_id]:
        if entry.use is None or entry.use in out:
            continue
        if entry.id is not None and crate.canonical.get(entry.id) == (*path, entry.name):
            continue
        out.append(entry.use)
    return out
