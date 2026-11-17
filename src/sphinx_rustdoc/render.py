"""Render signatures from rustdoc's type trees, as tokens that can carry links."""

from __future__ import annotations

from dataclasses import dataclass

from .model import Crate, kind_of


@dataclass(frozen=True)
class Tok:
    text: str
    # keyword, name (the item's own), punct, space, link, type (unlinked: primitives, generics,
    # lifetimes), param (a parameter's name) or text
    kind: str = "text"
    # the item a link token points to
    target: int | None = None


Toks = list[Tok]

SPACE = Tok(" ", "space")


def kw(text: str) -> Toks:
    return [Tok(text, "keyword"), SPACE]


def punct(text: str) -> Tok:
    return Tok(text, "punct")


def text(toks: Toks) -> str:
    return "".join(t.text for t in toks)


def joined(parts: list[Toks], separator: str) -> Toks:
    out: Toks = []
    for i, part in enumerate(parts):
        if i:
            out.append(punct(separator.rstrip()))
            if separator.endswith(" "):
                out.append(SPACE)
        out.extend(part)
    return out


def visibility(item: dict) -> Toks:
    vis = item["visibility"]
    if vis == "public":
        return kw("pub")
    if vis == "crate":
        return [Tok("pub", "keyword"), punct("("), Tok("crate", "keyword"), punct(")"), SPACE]
    if isinstance(vis, dict) and "restricted" in vis:
        return [Tok("pub", "keyword"), punct("("), Tok(f"in {vis['restricted']['path']}"), punct(")"), SPACE]
    return []


# -- types ----------------------------------------------------------------------------------------


def type_(t: dict | str | None) -> Toks:
    if t is None:
        return []
    if isinstance(t, str):
        # "infer"
        return [Tok("_")]
    ((kind, value),) = t.items()
    match kind:
        case "resolved_path":
            return path(value)
        case "generic" | "primitive":
            return [Tok(value, "type")]
        case "tuple":
            parts = [type_(v) for v in value]
            out = [punct("("), *joined(parts, ", ")]
            if len(parts) == 1:
                out.append(punct(","))
            return [*out, punct(")")]
        case "slice":
            return [punct("["), *type_(value), punct("]")]
        case "array":
            return [punct("["), *type_(value["type"]), punct(";"), SPACE, Tok(value["len"]), punct("]")]
        case "pat":
            return type_(value["type"])
        case "borrowed_ref":
            out = [punct("&")]
            if value["lifetime"]:
                out += [Tok(value["lifetime"], "type"), SPACE]
            if value["is_mutable"]:
                out += kw("mut")
            return out + type_(value["type"])
        case "raw_pointer":
            return [punct("*"), *kw("mut" if value["is_mutable"] else "const"), *type_(value["type"])]
        case "impl_trait":
            return [*kw("impl"), *bounds(value)]
        case "dyn_trait":
            parts = [[*for_lifetimes(p["generic_params"]), *path(p["trait"])] for p in value["traits"]]
            if value["lifetime"]:
                parts.append([Tok(value["lifetime"], "type")])
            return [*kw("dyn"), *joined(parts, " + ")]
        case "function_pointer":
            return [*for_lifetimes(value["generic_params"]), *header(value["header"]), *fn_tail("fn", value["sig"])]
        case "qualified_path":
            name = value["name"]
            self_type = value["self_type"]
            trait = value["trait"]
            if self_type == {"generic": "Self"} or trait is None or not trait.get("path"):
                return [*type_(self_type), punct("::"), Tok(name, "type"), *generic_args(value["args"])]
            return [
                punct("<"),
                *type_(self_type),
                SPACE,
                *kw("as"),
                *path(trait),
                punct(">"),
                punct("::"),
                Tok(name, "type"),
                *generic_args(value["args"]),
            ]
    return [Tok("_")]


def path(p: dict) -> Toks:
    name = p["path"].rsplit("::", 1)[-1]
    return [Tok(name, "link", p.get("id")), *generic_args(p.get("args"))]


def generic_args(args: dict | str | None) -> Toks:
    if not args or not isinstance(args, dict):
        return []
    if "parenthesized" in args:
        value = args["parenthesized"]
        out = [punct("("), *joined([type_(t) for t in value["inputs"]], ", "), punct(")")]
        if value["output"] is not None:
            out += [SPACE, punct("->"), SPACE, *type_(value["output"])]
        return out
    value = args.get("angle_bracketed")
    if not value:
        return []
    parts: list[Toks] = []
    for arg in value["args"]:
        if isinstance(arg, str):
            parts.append([Tok("_")])
        elif "lifetime" in arg:
            parts.append([Tok(arg["lifetime"], "type")])
        elif "type" in arg:
            parts.append(type_(arg["type"]))
        elif "const" in arg:
            parts.append([Tok(arg["const"].get("expr", "_"))])
    for constraint in value["constraints"]:
        part = [Tok(constraint["name"], "type"), *generic_args(constraint.get("args"))]
        binding = constraint["binding"]
        if "equality" in binding:
            term = binding["equality"]
            part += [SPACE, punct("="), SPACE]
            part += type_(term["type"]) if "type" in term else [Tok(term.get("constant", {}).get("expr", "_"))]
        else:
            part += [punct(":"), SPACE, *bounds(binding["constraint"])]
        parts.append(part)
    if not parts:
        return []
    return [punct("<"), *joined(parts, ", "), punct(">")]


def for_lifetimes(params: list[dict]) -> Toks:
    if not params:
        return []
    return [
        Tok("for", "keyword"),
        punct("<"),
        *joined([[Tok(p["name"], "type")] for p in params], ", "),
        punct(">"),
        SPACE,
    ]


def bounds(items: list[dict]) -> Toks:
    parts: list[Toks] = []
    for bound in items:
        if "trait_bound" in bound:
            value = bound["trait_bound"]
            modifier = {"maybe": [punct("?")], "maybe_const": [Tok("~const"), SPACE]}.get(value["modifier"], [])
            parts.append([*for_lifetimes(value["generic_params"]), *modifier, *path(value["trait"])])
        elif "outlives" in bound:
            parts.append([Tok(bound["outlives"], "type")])
        elif "use" in bound:
            names = [u if isinstance(u, str) else next(iter(u.values())) for u in bound["use"]]
            parts.append([Tok("use"), punct("<"), *joined([[Tok(n, "type")] for n in names], ", "), punct(">")])
    return joined(parts, " + ")


# -- generics -------------------------------------------------------------------------------------


def generic_params(generics: dict) -> Toks:
    parts: list[Toks] = []
    for param in generics["params"]:
        ((kind, value),) = param["kind"].items()
        if kind == "lifetime":
            part = [Tok(param["name"], "type")]
            if value["outlives"]:
                part += [punct(":"), SPACE, *joined([[Tok(o, "type")] for o in value["outlives"]], " + ")]
        elif kind == "type":
            if value["is_synthetic"]:
                continue
            part = [Tok(param["name"], "type")]
            if value["bounds"]:
                part += [punct(":"), SPACE, *bounds(value["bounds"])]
            if value["default"] is not None:
                part += [SPACE, punct("="), SPACE, *type_(value["default"])]
        else:
            part = [*kw("const"), Tok(param["name"], "type"), punct(":"), SPACE, *type_(value["type"])]
            if value.get("default") is not None:
                part += [SPACE, punct("="), SPACE, Tok(value["default"])]
        parts.append(part)
    if not parts:
        return []
    return [punct("<"), *joined(parts, ", "), punct(">")]


def where_clause(generics: dict) -> Toks:
    parts: list[Toks] = []
    for predicate in generics["where_predicates"]:
        ((kind, value),) = predicate.items()
        if kind == "bound_predicate":
            parts.append(
                [
                    *for_lifetimes(value["generic_params"]),
                    *type_(value["type"]),
                    punct(":"),
                    SPACE,
                    *bounds(value["bounds"]),
                ]
            )
        elif kind == "lifetime_predicate":
            parts.append(
                [
                    Tok(value["lifetime"], "type"),
                    punct(":"),
                    SPACE,
                    *joined([[Tok(o, "type")] for o in value["outlives"]], " + "),
                ]
            )
        elif kind == "eq_predicate":
            rhs = value["rhs"]
            rhs_toks = type_(rhs["type"]) if "type" in rhs else [Tok(rhs.get("constant", {}).get("expr", "_"))]
            parts.append([*type_(value["lhs"]), SPACE, punct("="), SPACE, *rhs_toks])
    if not parts:
        return []
    return [SPACE, *kw("where"), *joined(parts, ", ")]


# -- functions ------------------------------------------------------------------------------------

ABI_NAMES = {"C": "C", "System": "system"}


def header(h: dict) -> Toks:
    out: Toks = []
    if h["is_const"]:
        out += kw("const")
    if h["is_async"]:
        out += kw("async")
    if h["is_unsafe"]:
        out += kw("unsafe")
    abi = h["abi"]
    if abi != "Rust":
        if isinstance(abi, dict):
            ((name, value),) = abi.items()
            if name == "Other":
                name = value
            else:
                name = ABI_NAMES.get(name, name.lower())
                # rustdoc records `extern "C-unwind"` as {"C": {"unwind": true}}
                if isinstance(value, dict) and value.get("unwind"):
                    name += "-unwind"
        else:
            name = str(abi)
        out += [*kw("extern"), Tok(f'"{name}"'), SPACE]
    return out


def self_param(t: dict) -> Toks | None:
    if t == {"generic": "Self"}:
        return [Tok("self", "keyword")]
    ref = t.get("borrowed_ref")
    if ref and ref["type"] == {"generic": "Self"}:
        out = [punct("&")]
        if ref["lifetime"]:
            out += [Tok(ref["lifetime"], "type"), SPACE]
        if ref["is_mutable"]:
            out += kw("mut")
        return [*out, Tok("self", "keyword")]
    return None


def fn_tail(name: str, sig: dict, name_kind: str = "keyword", generics: dict | None = None) -> Toks:
    """`name<generics>(params) -> output`, with `fn` as the name for a function pointer."""
    params: list[Toks] = []
    for pname, ptype in sig["inputs"]:
        if pname == "self":
            short = self_param(ptype)
            params.append(short if short is not None else [Tok("self", "keyword"), punct(":"), SPACE, *type_(ptype)])
        elif pname == "_" and name_kind == "keyword":
            params.append(type_(ptype))
        else:
            params.append([Tok(pname, "param"), punct(":"), SPACE, *type_(ptype)])
    if sig["is_c_variadic"]:
        params.append([punct("...")])
    out = [Tok(name, name_kind)]
    if generics is not None:
        out += generic_params(generics)
    out += [punct("("), *joined(params, ", "), punct(")")]
    if sig["output"] is not None:
        out += [SPACE, punct("->"), SPACE, *type_(sig["output"])]
    return out


# -- items ----------------------------------------------------------------------------------------


def attributes(item: dict) -> Toks:
    """The attributes an item's declaration shows. `#[non_exhaustive]` is the one that changes how
    other crates can use a struct, enum or variant.
    """
    # other attributes are dicts, such as {"other": "#[attr = Inline(Hint)]"}
    if "non_exhaustive" in item["attrs"]:
        return [punct("#["), Tok("non_exhaustive"), punct("]"), SPACE]
    return []


def signature(crate: Crate, item_id: int, name: str | None = None) -> Toks:
    """The declaration of an item, as on docs.rs, without fields or bodies."""
    return [*attributes(crate.index[str(item_id)]), *declaration(crate, item_id, name)]


def declaration(crate: Crate, item_id: int, name: str | None = None) -> Toks:
    item = crate.index[str(item_id)]
    kind = kind_of(item)
    inner = item["inner"][kind]
    name = name or item["name"]
    vis = visibility(item)
    match kind:
        case "function":
            return [
                *vis,
                *header(inner["header"]),
                *kw("fn"),
                *fn_tail(name, inner["sig"], "name", inner["generics"]),
                *where_clause(inner["generics"]),
            ]
        case "struct":
            out = [*vis, *kw("struct"), Tok(name, "name"), *generic_params(inner["generics"])]
            shape = inner["kind"]
            if isinstance(shape, dict) and "tuple" in shape:
                fields = []
                for field_id in shape["tuple"]:
                    field = crate.item(field_id)
                    fields.append(
                        [Tok("_")] if field is None else [*visibility(field), *type_(field["inner"]["struct_field"])]
                    )
                out += [punct("("), *joined(fields, ", "), punct(")")]
            return [*out, *where_clause(inner["generics"])]
        case "enum" | "union":
            return [
                *vis,
                *kw(kind),
                Tok(name, "name"),
                *generic_params(inner["generics"]),
                *where_clause(inner["generics"]),
            ]
        case "trait":
            out = [*vis]
            if inner["is_unsafe"]:
                out += kw("unsafe")
            if inner["is_auto"]:
                out += kw("auto")
            out += [*kw("trait"), Tok(name, "name"), *generic_params(inner["generics"])]
            if inner["bounds"]:
                out += [punct(":"), SPACE, *bounds(inner["bounds"])]
            return [*out, *where_clause(inner["generics"])]
        case "type_alias":
            return [
                *vis,
                *kw("type"),
                Tok(name, "name"),
                *generic_params(inner["generics"]),
                *where_clause(inner["generics"]),
                SPACE,
                punct("="),
                SPACE,
                *type_(inner["type"]),
            ]
        case "constant":
            out = [*vis, *kw("const"), Tok(name, "name"), punct(":"), SPACE, *type_(inner["type"])]
            expr = inner["const"]["expr"]
            if expr and expr != "_":
                out += [SPACE, punct("="), SPACE, Tok(expr)]
            return out
        case "static":
            out = [*vis, *kw("static")]
            if inner["is_mutable"]:
                out += kw("mut")
            return [*out, Tok(name, "name"), punct(":"), SPACE, *type_(inner["type"])]
        case "struct_field":
            return [*vis, Tok(name, "name"), punct(":"), SPACE, *type_(inner)]
        case "variant":
            out = [Tok(name, "name")]
            shape = inner["kind"]
            if isinstance(shape, dict) and "tuple" in shape:
                fields = [
                    type_(crate.index[str(f)]["inner"]["struct_field"]) if crate.item(f) else [Tok("_")]
                    for f in shape["tuple"]
                ]
                out += [punct("("), *joined(fields, ", "), punct(")")]
            if inner["discriminant"]:
                out += [SPACE, punct("="), SPACE, Tok(inner["discriminant"]["expr"])]
            return out
        case "assoc_type":
            out = [*kw("type"), Tok(name, "name"), *generic_params(inner["generics"])]
            if inner["bounds"]:
                out += [punct(":"), SPACE, *bounds(inner["bounds"])]
            out += where_clause(inner["generics"])
            if inner["type"] is not None:
                out += [SPACE, punct("="), SPACE, *type_(inner["type"])]
            return out
        case "assoc_const":
            out = [*kw("const"), Tok(name, "name"), punct(":"), SPACE, *type_(inner["type"])]
            if inner["value"] is not None:
                out += [SPACE, punct("="), SPACE, Tok(inner["value"])]
            return out
        case "macro":
            return [*kw("macro_rules!"), Tok(name, "name")]
        case "proc_macro":
            if inner["kind"] == "attr":
                return [punct("#["), Tok(name, "name"), punct("]")]
            if inner["kind"] == "derive":
                return [punct("#["), Tok("derive"), punct("("), Tok(name, "name"), punct(")]")]
            return [Tok(name, "name"), punct("!")]
        case "module":
            return [*vis, *kw("mod"), Tok(name, "name")]
    return [Tok(name, "name")]


def impl_header(crate: Crate, impl_id: int) -> Toks:
    inner = crate.index[str(impl_id)]["inner"]["impl"]
    out: Toks = []
    if inner["is_unsafe"]:
        out += kw("unsafe")
    out += [Tok("impl", "keyword"), *generic_params(inner["generics"]), SPACE]
    if inner["trait"] is not None:
        if inner["is_negative"]:
            out.append(punct("!"))
        out += [*path(inner["trait"]), SPACE, *kw("for")]
    return [*out, *type_(inner["for"]), *where_clause(inner["generics"])]


def reexport(entry_use: dict) -> Toks:
    use = entry_use["inner"]["use"]
    source = use["source"]
    if use["is_glob"]:
        return [*kw("pub"), *kw("use"), Tok(source, "link", use["id"]), punct("::*"), punct(";")]
    out = [*kw("pub"), *kw("use"), Tok(source, "link", use["id"])]
    if source.rsplit("::", 1)[-1] != use["name"]:
        out += [SPACE, *kw("as"), Tok(use["name"])]
    return [*out, punct(";")]
