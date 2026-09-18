"""Repository-scoped review guidance, read without checking out a branch."""

import stat
from pathlib import Path, PurePosixPath


def projectGuidance(repo, revision, changedPaths, limit=80000):
    tree = repo[revision].tree
    directories = {""}
    for path in changedPaths:
        directories.update(str(p) if str(p) != "." else "" for p in PurePosixPath(path).parents)
    candidates = set()
    patterns = (".claude/rules", ".cursor/rules", ".claude/skills", ".agents/skills", ".codex/skills")
    root = Path(repo.workdir).resolve() if repo.workdir else None

    def visit(subtree, prefix):
        for entry in subtree:
            path = prefix + "/" + entry.name
            if stat.S_ISDIR(entry.filemode):
                visit(repo[entry.id], path)
            elif entry.name == "SKILL.md" or ("/rules/" in path and path.endswith((".md", ".mdc"))):
                candidates.add(path)

    for directory in directories:
        prefix = directory + "/" if directory else ""
        candidates.update(prefix + name for name in ("AGENTS.md", "AGENTS.override.md", "CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md", ".cursorrules"))
        for pattern in patterns:
            path = prefix + pattern
            try:
                entry = tree[path]
                if stat.S_ISDIR(entry.filemode):
                    visit(repo[entry.id], path)
            except KeyError:
                pass
            if root:
                localDir = root / path
                if localDir.is_dir() and localDir.resolve().is_relative_to(root):
                    for local in localDir.rglob("*"):
                        if local.name == "SKILL.md" or ("/rules/" in local.as_posix() and local.suffix in (".md", ".mdc")):
                            candidates.add(local.relative_to(root).as_posix())

    included, omitted, sections = [], [], []
    remaining = limit
    for path in sorted(candidates, key=lambda p: (p.count("/"), p)):
        source = f"{revision[:10]}:{path}"
        data = None
        try:
            entry = tree[path]
            if not stat.S_ISREG(entry.filemode):
                continue
            blob = repo[entry.id]
            if blob.size > min(20000, remaining):
                omitted.append(source + " (size limit)")
                continue
            data = blob.data
        except KeyError:
            # Include local guidance that isn't tracked in this revision, such as
            # a developer's ignored .claude/skills. Never follow links outside the repo.
            if root:
                local = root / path
                try:
                    if local.is_file() and local.resolve().is_relative_to(root):
                        source = f"Local working tree:{path}"
                        if local.stat().st_size > min(20000, remaining):
                            omitted.append(source + " (size limit)")
                            continue
                        data = local.read_bytes()
                except OSError:
                    omitted.append(source + " (unreadable)")
        if data is not None:
            remaining -= len(data)
            included.append(source)
            sections.append(f"--- {source} ---\n{data.decode('utf-8', errors='replace')}")
    return "\n\n".join(sections), included, omitted
