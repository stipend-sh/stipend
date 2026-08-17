"""Build stipend.tar.gz — the thing people actually install.

This exists because on 17 August 2026 the repo had four payment fixes in it and
the tarball on the website was five days older than all of them. Every install
for five days got a client that could not pay a spec-compliant server. Nobody
noticed, because committing felt like shipping.

So: one command, it builds from committed state only, and it refuses to build
anything the self-tests do not pass.

    python3 build.py                 build ./dist/stipend.tar.gz
    python3 build.py --allow-dirty   build from the working tree instead

Deploy is a separate step on purpose — see DEPLOY at the bottom of the output.
"""

import hashlib
import io
import os
import subprocess
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "dist", "stipend.tar.gz")

# What an installed copy needs, and nothing else. The installer unpacks these
# straight into the install directory, so there is no wrapping folder.
INCLUDE_FILES = [
    "FOR_YOUR_HUMAN.md",
    "LICENSE",
    "README.md",
    "SKILL.md",
    "requirements.txt",
]
INCLUDE_PACKAGE = "stipend"

# Kept out deliberately: .git, build.py itself, the Dockerfile and the registry
# manifests (server.json, glama.json, AGENTS.md) describe the project to
# directories and are no use on a machine that has already installed it.
EXCLUDE_NAMES = {"__pycache__", ".git", ".gitignore", ".DS_Store"}


def run(*cmd):
    return subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)


def version():
    path = os.path.join(HERE, INCLUDE_PACKAGE, "__init__.py")
    for line in open(path, encoding="utf-8"):
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("build: no __version__ in %s" % path)


def check_clean():
    r = run("git", "status", "--porcelain")
    if r.returncode != 0:
        print("build: not a git checkout — building from the working tree")
        return
    dirty = [l for l in r.stdout.splitlines() if l.strip()]
    if dirty:
        print("build: the working tree has uncommitted changes:")
        for l in dirty[:20]:
            print("   " + l)
        sys.exit("build: refusing to ship something that is not committed. "
                 "Commit it, or pass --allow-dirty if you know why.")


def check_tests():
    print("build: running the self-tests")
    r = subprocess.run([sys.executable, "-c",
                        "import sys; sys.path.insert(0, '.'); "
                        "from stipend import selftest; selftest.run()"],
                       cwd=HERE, capture_output=True, text=True)
    tail = (r.stdout or "").strip().splitlines()[-3:]
    for line in tail:
        print("   " + line)
    if r.returncode != 0:
        sys.exit("build: self-tests failed — nothing built. "
                 "A failing suite is the one thing that should stop a release.")


def add(tar, path, arcname):
    def filt(info):
        base = os.path.basename(info.name)
        if base in EXCLUDE_NAMES or base.endswith(".pyc"):
            return None
        # Reproducible: the same commit should produce the same bytes, so the
        # sha256 printed below means something.
        info.uid = info.gid = 0
        info.uname = info.gname = "stipend"
        info.mtime = 0
        return info
    tar.add(path, arcname=arcname, filter=filt, recursive=True)


def main():
    allow_dirty = "--allow-dirty" in sys.argv
    if not allow_dirty:
        check_clean()
    check_tests()

    v = version()
    missing = [f for f in INCLUDE_FILES if not os.path.exists(os.path.join(HERE, f))]
    if missing:
        sys.exit("build: missing %s" % ", ".join(missing))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for f in INCLUDE_FILES:
            add(tar, os.path.join(HERE, f), f)
        add(tar, os.path.join(HERE, INCLUDE_PACKAGE), INCLUDE_PACKAGE)
    blob = buf.getvalue()
    with open(OUT, "wb") as fh:
        fh.write(blob)

    digest = hashlib.sha256(blob).hexdigest()
    print()
    print("build: stipend %s" % v)
    print("build: %s" % OUT)
    print("build: %d KB, sha256 %s" % (len(blob) // 1024, digest))
    print()
    print("DEPLOY:")
    print("  scp dist/stipend.tar.gz root@43.229.62.98:/var/www/stipend.sh/stipend.tar.gz")
    print("  then check the live copy reports the same sha256:")
    print("  curl -s https://stipend.sh/stipend.tar.gz | sha256sum")


if __name__ == "__main__":
    main()
