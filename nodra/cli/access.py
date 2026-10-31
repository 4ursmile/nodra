"""Git access helpers: remember logins through our credential helper, ask once on a terminal when a source needs one."""
import os
import subprocess

from . import gitx, paths, tls, ui


def _git(*args, **kw):
    try:
        return subprocess.run(["git"] + list(args), capture_output=True, text=True, **kw, **gitx.popen_kw())
    except FileNotFoundError:
        return subprocess.CompletedProcess(["git"] + list(args), 127, "", gitx.NO_GIT)


def ensure_helper(urls=()):
    """Make git remember logins for source hosts through our own helper (`nodra credential`, see credhelper). Only those
    hosts are touched; helpers you configured for other hosts stay as they are. Idempotent: a host already set up is left alone.
    Returns (changed, already_ok) host lists."""
    from . import credhelper
    try:
        return credhelper.register(urls)
    except Exception:
        return [], []


def store_git(host_url, username, token, quiet=False):
    """Save a credential the USER typed to the credential store (credhelper), IN THIS PROCESS and then read it back: a git helper
    run by `git credential approve` fails silently (shim missing, PATH, quoting) while git still exits 0. The helper is registered
    too, so git finds the login. One entry per host (key = `host[:port]`, no userinfo), so a new token replaces the old one.
    Returns True only when the stored login reads back identical; otherwise False (and says why unless quiet)."""
    from . import credhelper
    if not (username and token and host_url):
        return False
    host = credhelper.host_of(host_url)
    ensure_helper([host_url])
    ok = bool(host) and credhelper.save(host, username, token)
    if ok:
        ok = credhelper.lookup(host) == (username, token)
    if not ok and not quiet:
        ui.bad("could not store the git login for %s in %s (nothing was saved)" % (host or gitx.redact_url(host_url), credhelper.describe()))
        ui.info(gitx.HINT.strip() + " check that ~/.nodra is writable and the keychain is unlocked, then retry; verify with: nodra vault test %s" % (host or "HOST"))
    return ok


_AUTH_WORDS = ("authentication", "could not read", "denied", "403", "401", "terminal prompts disabled")


def is_auth_error(err):
    return any(w in gitx.strip_hints(str(err)).lower() for w in _AUTH_WORDS)       # our own hint lines never count


NO_PROMPT = False       # unattended work (package updates): never ask for a git login, just fail


def with_access(url, fn):
    """Run fn() (a git operation on `url`) for any remote, whatever its host: the index, a package repo, another team's repo.
    The helper is registered for that host first (idempotent, other hosts untouched). If fn fails for lack of credentials and a
    person is at a terminal, ask once for this host, store the login in its own entry and retry. Hosts already known never prompt."""
    if (url or "").startswith("http"):
        ensure_helper([url])
    try:
        return fn()
    except gitx.GitError as e:
        if not (is_auth_error(e) and ui.INTERACTIVE and not NO_PROMPT and (url or "").startswith("http")):
            raise
        ensure_git_access(url)
        return fn()


def ensure_git_access(url):
    """Make sure `git ls-remote url` works; if it needs credentials we do not have, ask for them once. No git installed = nothing to check."""
    if not gitx.available():
        return True
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", **tls.git_env())
    r = _git("ls-remote", "--exit-code", "-h", url, "HEAD", env=env)
    if r.returncode in (0, 2):
        return True
    if not is_auth_error(r.stderr):
        raise gitx.GitError(gitx.explain(gitx.redact_url(r.stderr.strip()) or "git ls-remote failed (exit %d)" % r.returncode, url))
    if not ui.INTERACTIVE or not url.startswith("http"):
        raise gitx.GitError(gitx.explain("git credentials are needed for %s" % gitx.redact_url(url), url, "auth"))
    import getpass
    from . import credhelper
    host = credhelper.host_of(url)
    ui.note("Git needs credentials for %s" % host)
    ui.info("If the account uses 2FA, the password is a personal access token, not the account password.")
    known = paths.load("vault.json", {})
    last = (known.get(host) or {}).get("username", "") if isinstance(known, dict) else ""
    for attempt in (0, 1):
        user = input("username%s: " % (" [%s]" % last if last else "")).strip() or last
        if not user:
            user = input("username (required): ").strip()
        if not user:
            raise gitx.GitError(gitx.explain("a username is needed for %s (with 2FA: your username and a personal access token)" % host, url, "auth"))
        tok = getpass.getpass("token/password: ")
        store_git(url, user, tok)
        r = _git("ls-remote", "--exit-code", "-h", url, "HEAD", env=env)
        if r.returncode in (0, 2):
            return True
        if attempt == 0 and is_auth_error(r.stderr):
            ui.bad("%s rejected that login. With 2FA enabled the host wants a personal access token instead of the account password; try again." % host)
            last = user
            continue
        return False
    return False
