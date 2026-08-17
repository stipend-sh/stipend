"""Push a release everywhere it needs to go, and say what is left for a human.

On 17 August 2026 four payment fixes sat in this repo while the website served
a tarball five days older, skill.md advertised version 0.43.0 under a name no
registry accepts, and agent.json said 0.45.1. Three files, three different
answers, none of them the code. Nothing had ever published one to the other,
so every copy drifted on its own.

    python3 publish.py --dry-run    show what would change, touch nothing
    python3 publish.py              push, then verify over https
    python3 publish.py --todo       just the list of things needing a human

The version in stipend/__init__.py is the single source of truth. Everything
else is stamped from it, and publishing refuses to run if they disagree.

Honest about its limits. Roughly forty of our listings are pull requests into
other people's repositories and a dozen more are browser-only forms; there is
no API that reaches them. Those are printed as a checklist rather than
pretended away. See platforms.json for which is which and why.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PLATFORMS = os.path.join(HERE, "platforms.json")
SITE = "https://stipend.sh"


def version():
    for line in open(os.path.join(HERE, "stipend", "__init__.py"), encoding="utf-8"):
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("publish: no __version__ found")


def stamped_files(v):
    """Files that name a version, and the version each currently claims."""
    found = {}
    for rel, pattern in (("SKILL.md", r'^version:\s*"([0-9.]+)"'),
                         ("server.json", r'"version":\s*"([0-9.]+)"'),
                         ("agent.json", r'"version":\s*"([0-9.]+)"')):
        path = os.path.join(HERE, rel)
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8").read()
        m = re.search(pattern, text, re.M)
        found[rel] = m.group(1) if m else None
    return found


def check_consistent(v):
    """Every file that names a version must name this one."""
    wrong = {f: got for f, got in stamped_files(v).items() if got != v}
    if wrong:
        print("publish: these disagree with stipend/__init__.py (%s):" % v)
        for f, got in wrong.items():
            print("   %-14s says %s" % (f, got))
        sys.exit("publish: fix them, or the site will advertise a version we "
                 "are not shipping. That is exactly what went wrong on 17 Aug.")
    print("publish: version %s, consistent across %d files"
          % (v, len(stamped_files(v))))


def run(cmd, dry):
    if dry:
        print("   would run: %s" % " ".join(cmd))
        return True
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("   FAILED: %s" % (r.stderr or r.stdout)[:300])
        return False
    return True


def sha_of(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def fetched_sha(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "stipend-publish/1"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return hashlib.sha256(r.read()).hexdigest()
    except Exception as e:
        return "unreachable: %s" % str(e)[:60]


def push_site(target, dry):
    """Copy the canonical files up, then read them back over https.

    The read-back is the point. A copy that appears to succeed and a file that
    is actually being served are different claims, and only the second one is
    what a stranger gets.
    """
    host = target["host"]
    ok = True
    published = []
    for local, remote in target["files"].items():
        src = os.path.join(HERE, local)
        if not os.path.exists(src):
            print("   MISSING %s — run build.py first" % local)
            ok = False
            continue
        print("   %s -> %s" % (local, remote))
        if not run(["scp", "-q", src, "%s:%s" % (host, remote)], dry):
            ok = False
            continue
        run(["ssh", host, "chown www-data:www-data %s && chmod 644 %s"
             % (remote, remote)], dry)
        published.append((local, src, remote))

    if dry:
        return ok

    print("   verifying what the site actually serves:")
    for local, src, remote in published:
        url = SITE + "/" + os.path.basename(remote)
        want, got = sha_of(src), fetched_sha(url)
        mark = "ok " if want == got else "MISMATCH"
        print("     %-8s %-34s %s" % (mark, url, got[:16]))
        if want != got:
            ok = False
    return ok


def todo(platforms, v):
    print()
    print("=" * 68)
    print("NEEDS A HUMAN — %s" % v)
    print("=" * 68)
    n = 0
    for p in platforms.get("manual", []):
        if not p.get("stale_on_release"):
            continue
        n += 1
        print()
        print("%d. %s" % (n, p["name"]))
        print("   %s" % p["url"])
        print("   holds: %s" % p["holds"])
        print("   how  : %s" % p["how"])
        if p.get("note"):
            print("   note : %s" % p["note"])
    print()
    print("Not stale, deliberately left alone:")
    for p in platforms.get("manual", []):
        if not p.get("stale_on_release"):
            print("   - %-22s %s" % (p["name"], p.get("note", "")[:70]))
    for p in platforms.get("static", []):
        count = p.get("count_at_seed")
        label = "%s (%d)" % (p["name"], count) if count else p["name"]
        print("   - %-22s %s" % (label[:22], p.get("note", "")[:70]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--todo", action="store_true", help="only the human list")
    args = ap.parse_args()

    platforms = json.load(open(PLATFORMS, encoding="utf-8"))
    v = version()

    if args.todo:
        todo(platforms, v)
        return 0

    check_consistent(v)

    ok = True
    for target in platforms.get("push", []):
        print()
        print("publish: %s" % target["name"])
        if not push_site(target, args.dry_run):
            ok = False

    todo(platforms, v)
    print()
    if not ok:
        print("publish: something did not land. Nothing above is true until the")
        print("verify line says ok — check it before telling anyone it shipped.")
        return 1
    print("publish: everything automatic is live and verified over https.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
