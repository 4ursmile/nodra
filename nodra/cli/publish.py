"""`nodra dev publish` as a git wrapper: commit this package and push it to the repository it lives in (LFS if needed). Nothing else."""
import os


from . import gitx, ui

LFS_MB = 50


def toplevel(root):
    return gitx.run(["rev-parse", "--show-toplevel"], cwd=root, check=False) if gitx.is_repo(root) else None


def ensure_gitignore(root):
    f = os.path.join(root, ".gitignore")
    want = ["dist/", ".DS_Store", "__pycache__/", "*.pyc", ".venv/", "node_modules/"]
    have = open(f).read().splitlines() if os.path.exists(f) else []
    add = [w for w in want if w not in have]
    if add or not os.path.exists(f):
        with open(f, "a", newline="\n") as fh:
            fh.write(("\n" if have and have[-1] else "") + "\n".join(add) + "\n")
        return True
    return False


def _lfs_tracked(top, files):
    """Subset of `files` that .gitattributes already sends to LFS."""
    out = gitx.run(["check-attr", "filter", "--"] + files, cwd=top, check=False)
    return {ln.rsplit(": filter:", 1)[0] for ln in out.splitlines() if ln.rstrip().endswith(": lfs")}


def _lfs(top):
    """Track this package's own large files with git-lfs. `top` is the PACKAGE folder: in a monorepo a package never sees
    (or reports) another package's files, and files already in LFS are left alone, so a later publish says nothing."""
    big = gitx.large_files(top, LFS_MB)
    if big:
        done = _lfs_tracked(top, big)
        big = [f for f in big if f not in done]
    if not big:
        return []
    if gitx.run(["lfs", "version"], cwd=top, check=False) == "":
        raise ValueError("%d file(s) over %d MB (%s) but git-lfs is not installed; install it or shrink them"
                         % (len(big), LFS_MB, ", ".join(big[:3])))
    gitx.run(["lfs", "install", "--local"], cwd=top)
    for f in big:
        gitx.run(["lfs", "track", f], cwd=top)
    return big


SKIP_DIRS = {"node_modules", "dist", "build", "__pycache__", "venv"}


def discover(root, depth=4):
    """Package folders (those holding a nodra.toml) in `root` or below it. A folder with a manifest is a leaf: nothing under it is searched."""
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return []
    if os.path.isfile(os.path.join(root, "nodra.toml")):
        return [root]
    found = []
    if depth > 0:
        for n in sorted(os.listdir(root)):
            d = os.path.join(root, n)
            if os.path.isdir(d) and not n.startswith(".") and n not in SKIP_DIRS and not os.path.islink(d):
                found += discover(d, depth - 1)
    return found


def enclosing(d):
    """Nearest folder above `d` (inside the same git repo, or up to 6 levels when there is none) that holds a nodra.toml, else None."""
    d = os.path.abspath(d)
    live = d
    while not os.path.isdir(live) and os.path.dirname(live) != live:     # the folder may not exist yet (init)
        live = os.path.dirname(live)
    stop = toplevel(live) if gitx.is_repo(live) else None
    cur = d
    for _ in range(6):
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent
        if os.path.isfile(os.path.join(cur, "nodra.toml")):
            return cur
        if stop and os.path.realpath(cur) == os.path.realpath(stop):
            return None
    return None


def push(root):
    """Push the current branch of the repo holding `root` (sets the upstream the first time)."""
    top = toplevel(root)
    branch = gitx.run(["symbolic-ref", "--short", "HEAD"], cwd=top)
    has_up = gitx.run(["rev-parse", "--abbrev-ref", "@{u}"], cwd=top, check=False)
    with ui.Spinner("Pushing to %s" % branch):
        gitx.run(["push", "-q"] + ([] if has_up else ["-u", "origin", branch]), cwd=top)


def commit_staged(top, items):
    """ONE commit for everything staged by `publish(commit_now=False)` in the repo `top`; `items` = [(package folder, info)].
    Sets `commit` on each info. The message names the packages that actually changed, so history still says what was released.
    Nothing staged = no commit (HEAD is reported)."""
    if gitx.run(["diff", "--cached", "--name-only"], cwd=top):
        changed = [i for d, i in items if gitx.run(["diff", "--cached", "--name-only", "--", "."], cwd=d)] or [i for _, i in items]
        if len(changed) == 1:
            msg = "publish %s %s" % (changed[0]["package"], changed[0]["version"])
        else:
            msg = "publish %d packages\n\n%s" % (len(changed), "\n".join("- %s %s" % (i["package"], i["version"]) for i in changed))
        gitx.run(["commit", "-q", "-m", msg], cwd=top)
    head = gitx.run(["rev-parse", "HEAD"], cwd=top)
    for _, i in items:
        i["commit"] = head
    return head


def publish(root, m, bump=None, push_now=True, commit_now=True):
    """Commit this package folder (and push unless push_now=False, so several packages can share one push).
    commit_now=False only stages it (`git add`) and leaves `commit` empty: the caller makes ONE commit for all packages
    with `commit_staged` (and must push after it). Returns {"package", "version", "commit", "remote", "branch"}."""
    if not gitx.available():
        raise ValueError("git is not installed")
    created = False
    if not gitx.is_repo(root):
        gitx.run(["init", "-q", "-b", "main"], cwd=root)
        created = True
    top = toplevel(root)
    origin, branch = gitx.remote_info(top)
    if created or not branch:
        gitx.run(["checkout", "-q", "-B", "main"], cwd=top, check=False)
        origin, branch = gitx.remote_info(top)
    if not origin and push_now and commit_now:
        ui.note("this repository has no remote 'origin': the commit is made, nothing is pushed (git remote add origin <url>)")
        push_now = False
    ensure_gitignore(root)
    lfs = _lfs(root)
    if lfs:
        ui.note("tracking %d large file(s) with git-lfs" % len(lfs))
    gitx.run(["add", "-A", "--", "."], cwd=root)
    pkg = m["package"]
    commit = ""
    if commit_now:
        if gitx.run(["status", "--porcelain", "--", "."], cwd=root):
            gitx.run(["commit", "-q", "-m", "publish %s %s" % (pkg["name"], pkg["version"])], cwd=root)
        if push_now:
            push(root)
        commit = gitx.run(["rev-parse", "HEAD"], cwd=top, check=False)
    return {"package": pkg["name"], "version": pkg["version"], "commit": commit, "remote": gitx.redact_url(origin or ""), "branch": branch or "main"}
