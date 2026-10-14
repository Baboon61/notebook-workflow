"""Conservative source analysis; never imports or executes notebook code.

Python uses the standard AST. R supports ordinary assignments and expressions
through lexical analysis; functions, control flow and dynamic evaluation are
explicitly uncertain. Both notebook versions contribute dependency edges.
"""

from __future__ import annotations

import ast
from collections import defaultdict, deque
from dataclasses import dataclass, field
import re


@dataclass
class Facts:
    reads: set[str] = field(default_factory=set)
    writes: set[str] = field(default_factory=set)
    mutations: set[str] = field(default_factory=set)
    aliases: dict[str, str] = field(default_factory=dict)
    deferred: dict[str, set[str]] = field(default_factory=dict)
    fingerprints: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    signature: str = ""


PURE_CALLS = {"print", "len", "abs", "round", "min", "max", "sum", "sorted",
              "range", "enumerate", "zip", "int", "float", "str", "bool",
              "list", "tuple", "dict", "set", "cat", "plot", "mean", "c"}
DYNAMIC_PYTHON = {"eval", "exec", "globals", "locals", "vars", "getattr",
                  "setattr", "delattr", "__import__"}


def _root(node):
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


class PythonFacts(ast.NodeVisitor):
    def __init__(self):
        self.facts = Facts()

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            self.facts.reads.add(node.id)
        else:
            self.facts.writes.add(node.id)

    def visit_Attribute(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)) and _root(node):
            self.facts.mutations.add(_root(node))
        self.generic_visit(node)

    visit_Subscript = visit_Attribute

    def visit_AugAssign(self, node):
        name = _root(node.target)
        if name:
            self.facts.reads.add(name)
            self.facts.mutations.add(name)
        self.generic_visit(node)

    def visit_Assign(self, node):
        self.generic_visit(node)
        if isinstance(node.value, ast.Name):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.facts.aliases[target.id] = node.value.id

    def visit_Import(self, node):
        self.facts.writes.update(alias.asname or alias.name.split(".")[0] for alias in node.names)

    def visit_ImportFrom(self, node):
        if any(alias.name == "*" for alias in node.names):
            self.facts.warnings.append("Wildcard imports can hide dependencies.")
        self.facts.writes.update(alias.asname or alias.name for alias in node.names if alias.name != "*")

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            name = node.func.id
            if name in DYNAMIC_PYTHON or name == "get_ipython":
                self.facts.warnings.append("Dynamic Python evaluation or notebook magic.")
            if name not in PURE_CALLS:
                self.facts.mutations.update(filter(None, (_root(arg) for arg in node.args)))
                self.facts.mutations.update(filter(None, (_root(arg.value) for arg in node.keywords)))
        elif isinstance(node.func, ast.Attribute):
            name = _root(node.func.value)
            if name:
                self.facts.mutations.add(name)
            self.facts.mutations.update(filter(None, (_root(arg) for arg in node.args)))
            self.facts.mutations.update(filter(None, (_root(arg.value) for arg in node.keywords)))
            if node.func.attr in {"eval", "exec", "run_line_magic", "run_cell_magic"}:
                self.facts.warnings.append("Dynamic Python evaluation or notebook magic.")
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self.facts.writes.add(node.name)
        # Defaults and decorators run when defining a function. Body globals
        # are resolved when a later cell reads/calls the function.
        for value in [*node.decorator_list, *node.args.defaults,
                      *(value for value in node.args.kw_defaults if value is not None)]:
            self.visit(value)
        nodes = [item for statement in node.body for item in ast.walk(statement)]
        local = {item.id for item in nodes if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store)}
        local.update(arg.arg for arg in ast.walk(node.args) if isinstance(arg, ast.arg))
        local.update(item.name for item in nodes if isinstance(item, (ast.FunctionDef, ast.ClassDef)))
        local.update(alias.asname or alias.name.split(".")[0] for item in nodes
                     if isinstance(item, (ast.Import, ast.ImportFrom)) for alias in item.names)
        reads = {item.id for item in nodes if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)}
        self.facts.deferred[node.name] = reads - local
        if any(isinstance(item, (ast.Global, ast.Nonlocal)) or
               isinstance(item, (ast.Attribute, ast.Subscript)) and isinstance(item.ctx, (ast.Store, ast.Del)) or
               isinstance(item, ast.Call) and (isinstance(item.func, ast.Attribute) or
                 isinstance(item.func, ast.Name) and item.func.id not in PURE_CALLS)
               for item in nodes):
            self.facts.warnings.append("Function body may change state indirectly.")

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self.facts.writes.add(node.name)
        self.facts.warnings.append("Class bodies and methods can hide state dependencies.")
        for value in [*node.bases, *node.decorator_list]:
            self.visit(value)

    def visit_With(self, node):
        self.facts.warnings.append("Context managers can change state indirectly.")
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_For(self, node):
        self.facts.warnings.append("Control flow may conditionally redefine notebook variables.")
        self.generic_visit(node)

    visit_AsyncFor = visit_For
    visit_While = visit_For
    visit_If = visit_For
    visit_Try = visit_For
    visit_Match = visit_For

    def visit_ListComp(self, node):
        self.facts.warnings.append("Comprehension scope requires conservative dependency handling.")
        self.generic_visit(node)

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def visit_Lambda(self, node):
        self.facts.warnings.append("Lambda scope requires conservative dependency handling.")
        self.generic_visit(node)


def _python(source):
    facts = Facts()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        facts.signature = "\n".join(line for line in source.splitlines()
                                    if not line.lstrip().startswith("#")).strip()
        facts.warnings.append("Python source is not statically parseable (possibly notebook magic).")
        return facts
    facts.signature = ast.dump(tree, include_attributes=False)
    for statement in tree.body:
        visitor = PythonFacts()
        visitor.visit(statement)
        part = visitor.facts
        facts.reads.update(part.reads)
        facts.writes.update(part.writes)
        facts.mutations.update(part.mutations)
        facts.aliases.update(part.aliases)
        facts.deferred.update(part.deferred)
        facts.warnings.extend(part.warnings)
        fingerprint = ast.dump(statement, include_attributes=False)
        for name in part.writes | part.mutations:
            facts.fingerprints.setdefault(name, []).append(fingerprint)
    return facts


# Strings/comments remain tokens for fingerprints but cannot create identifiers.
R_TOKEN = re.compile(r"""#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[A-Za-z_.][A-Za-z0-9_.]*|[0-9]+(?:\.[0-9]+)?|<<-|->>|<-|->|:=|:::{0,1}|%[^%\n]*%|\|>|==|!=|<=|>=|&&|\|\||\n|[^\s]""")
R_NAME = re.compile(r"^[A-Za-z_.][A-Za-z0-9_.]*$")
R_KEYWORDS = {"TRUE", "FALSE", "NULL", "NA", "NaN", "Inf", "NA_real_", "NA_integer_", "NA_character_"}
R_DYNAMIC = {"function", "if", "else", "for", "while", "repeat", "switch",
             "eval", "evalq", "parse", "get", "mget", "assign", "source", "load",
             "attach", "detach", "do.call", "substitute", "library", "require",
             "globalenv", "parent.frame", "environment", "py_run_string",
             "py_run_file", "py_eval", "py_exec", "Sys.setenv", "Sys.unsetenv",
             "setwd", "options", "set.seed", "rm", "remove", "system", "system2", "sink"}


def _r(source):
    facts = Facts()
    tokens = [token for token in R_TOKEN.findall(source) if not token.startswith("#")]
    facts.signature = repr([token for token in tokens if token != "\n"])
    if any(token in R_DYNAMIC or token in {"<<-", "->>", ":=", "~", "|>"} or token.startswith("%")
           or token == chr(96) for token in tokens):
        facts.warnings.append("R functions, control flow, nonstandard evaluation or dynamic state.")
    if any(token in {"'", '"', "{"} for token in tokens):
        facts.warnings.append("R syntax needs conservative dependency handling.")
    groups, group, depth = [], [], 0
    for token in tokens:
        if token in {"(", "[", "{"}:
            depth += 1
        elif token in {")", "]", "}"}:
            depth -= 1
        continued = group and (group[-1] in {"<-", "=", "->", "+", "-", "*", "/", "^", "|>",
                                            "&&", "||", "&", "|", "==", "!=", "<", ">", "<=", ">="}
                               or group[-1].startswith("%"))
        if token == "\n" and depth == 0 and continued:
            continue
        if token in {"\n", ";"} and depth == 0:
            if group:
                groups.append(group)
            group = []
        elif token != "\n":
            group.append(token)
    if group:
        groups.append(group)
    if depth != 0:
        facts.warnings.append("R source has unbalanced delimiters.")
    facts.signature = repr(groups)
    for group in groups:
        assigned, mutated, aliases = set(), set(), {}
        if sum(token in {"<-", "->"} for token in group) > 1:
            facts.warnings.append("Chained R assignment requires conservative handling.")
        # Precise write identification is limited to straight-line assignments.
        if len(group) >= 3 and R_NAME.match(group[0]) and group[1] in {"<-", "="}:
            assigned.add(group[0])
            if len(group) == 3 and R_NAME.match(group[2]):
                aliases[group[0]] = group[2]
        elif len(group) >= 3 and group[-2] == "->" and R_NAME.match(group[-1]):
            assigned.add(group[-1])
        elif any(token in {"<-", "=", "->"} for token in group):
            # Named arguments such as plot(x=...) do not define notebook x.
            if "<-" in group or "->" in group:
                facts.warnings.append("Complex R assignment target.")
        for index, token in enumerate(group):
            if not R_NAME.match(token) or token in R_KEYWORDS or token in assigned:
                continue
            if index and group[index - 1] in {"$", "@", "::", ":::"}:
                continue
            if index + 1 < len(group) and group[index + 1] == "=":
                continue
            facts.reads.add(token)
        # Unknown calls can mutate their inputs. Conservatively give those
        # inputs a new provenance, while common output/math calls are read-only.
        calls = {group[index] for index in range(len(group) - 1)
                 if R_NAME.match(group[index]) and group[index + 1] == "("}
        if calls - PURE_CALLS:
            mutated.update(token for token in group if R_NAME.match(token)
                           and token not in calls | assigned | R_KEYWORDS)
        # x <- x + 1 reads the previous x as well.
        for name in assigned:
            if group.count(name) > 1:
                facts.reads.add(name)
        facts.writes.update(assigned)
        facts.mutations.update(mutated)
        facts.aliases.update(aliases)
        for name in assigned | mutated:
            facts.fingerprints.setdefault(name, []).append(repr(group))
    return facts


def _graph(cells, facts):
    graph = defaultdict(set)
    providers, first, functions, aliases = {}, {}, {}, {}
    for cell, info in zip(cells, facts):
        for name in info.writes | info.mutations:
            first.setdefault(name, (cell["label"], name))
        for name, reads in info.deferred.items():
            functions[(cell["label"], name)] = reads
    for cell, info in zip(cells, facts):
        label = cell["label"]
        reads, pending = set(info.reads), list(info.reads)
        while pending:
            name = pending.pop()
            node = providers.get(name, first.get(name))
            for free in functions.get(node, set()) - reads:
                reads.add(free)
                pending.append(free)
        dependencies = {providers.get(name, first.get(name)) for name in reads}
        dependencies.discard(None)
        output = (label, None)
        for dependency in dependencies:
            graph[dependency].add(output)
        mutations = set(info.mutations)
        for name in info.mutations:
            mutations.update(aliases.get(name, {name}))
        for name in info.writes | mutations:
            node = (label, name)
            for dependency in dependencies:
                graph[dependency].add(node)
            if name in mutations and name not in info.mutations:
                for owner in info.mutations:
                    graph[(label, owner)].add(node)
            providers[name] = node
        # Reassignment breaks an alias; mutation keeps the object alias group.
        for name in info.writes - info.mutations:
            old = aliases.pop(name, {name})
            for other in old - {name}:
                aliases[other] = old - {name}
        for name, owner in info.aliases.items():
            group = aliases.get(owner, {owner}) | {name}
            for other in group:
                aliases[other] = group
    return graph


def invalidation(before, after, language, policy="conservative"):
    """Return code-cell numbers needing output invalidation and compact reasons."""
    if policy == "changed-only":
        return [], {"dependency_policy": policy, "dependency_fallback": [], "dependency_warnings": []}
    analyzer = _python if language == "python" else _r
    # Label newly added cells locally; these IDs never enter the notebook/script.
    after = [{**cell, "label": cell["label"] or f"new-{index}"} for index, cell in enumerate(after)]
    old = {cell["label"]: cell for cell in before}
    new = {cell["label"]: cell for cell in after}
    old_facts = [analyzer(cell["source"]) if cell["cell_type"] == "code" else Facts() for cell in before]
    new_facts = [analyzer(cell["source"]) if cell["cell_type"] == "code" else Facts() for cell in after]
    old_info = dict(zip(old, old_facts))
    new_info = dict(zip(new, new_facts))
    old_order = [cell["label"] for cell in before if cell["label"] in new and cell["cell_type"] == "code"]
    new_order = [cell["label"] for cell in after if cell["label"] in old and cell["cell_type"] == "code"]
    ranks = {label: index for index, label in enumerate(new_order)}
    moved = set()
    for index, left in enumerate(old_order):
        for right in old_order[index + 1:]:
            if left in ranks and right in ranks and ranks[left] > ranks[right]:
                moved.update((left, right))
    roots, changed_positions = set(), []
    for label in old.keys() | new.keys():
        a, b = old_info.get(label, Facts()), new_info.get(label, Facts())
        if a.signature == b.signature and label not in moved:
            continue
        position = next((index for index, cell in enumerate(after) if cell["label"] == label), None)
        if position is None:
            position = next(index for index, cell in enumerate(before) if cell["label"] == label)
        changed_positions.append(position)
        names = a.writes | a.mutations | b.writes | b.mutations
        roots.update((label, name) for name in names if label in moved or
                     a.fingerprints.get(name) != b.fingerprints.get(name))
        if label in moved:
            roots.add((label, None))
    graph = _graph(before, old_facts)
    for node, children in _graph(after, new_facts).items():
        graph[node].update(children)
    visited, pending = set(roots), deque(roots)
    while pending:
        for node in graph[pending.popleft()] - visited:
            visited.add(node)
            pending.append(node)
    affected = {index + 1 for index, cell in enumerate(after)
                if cell["cell_type"] == "code" and (cell["label"], None) in visited}
    warnings = [{"cell": index + 1, "reason": reason}
                for index, info in enumerate(new_facts)
                for reason in sorted(set(info.warnings))]
    # Deleted dynamic cells matter too; only a compact reason is returned.
    for index, cell in enumerate(before):
        if cell["label"] not in new or old_info[cell["label"]].warnings != new_info[cell["label"]].warnings:
            warnings.extend({"original_cell": index + 1, "reason": reason}
                            for reason in sorted(set(old_facts[index].warnings)))
    fallback = []
    if policy == "conservative" and changed_positions and any(info.warnings for info in old_facts + new_facts):
        start = min(changed_positions)
        fallback = [index + 1 for index, cell in enumerate(after)
                    if index >= start and cell["cell_type"] == "code"]
        affected.update(fallback)
    return sorted(affected), {"dependency_policy": policy, "dependency_fallback": fallback,
                             "dependency_warnings": warnings if changed_positions else []}
