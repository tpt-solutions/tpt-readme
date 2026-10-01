#!/usr/bin/env python3
"""Count todo.md checkboxes across an org and refresh the README progress block.

Usage:  python scripts/progress.py [--org tpt-solutions] [--readme README.md]
Env:    GITHUB_TOKEN (optional; raises the API rate limit, needed in CI)

Only the standard library is used. Writes PROGRESS.md and replaces everything
between <!-- PROGRESS:START --> and <!-- PROGRESS:END --> in the README.
"""
import argparse
import concurrent.futures as cf
import datetime
import json
import os
import re
import urllib.error
import urllib.request

DONE = re.compile(r"^\s*[-*+]\s+\[[xX]\]", re.M)
OPEN = re.compile(r"^\s*[-*+]\s+\[ \]", re.M)
TODO_NAMES = ("todo.md", "TODO.md", "Todo.md")


def get(url, token=None):
    req = urllib.request.Request(url, headers={"User-Agent": "tpt-progress"})
    if token and "api.github.com" in url:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def list_repos(org, token):
    repos, page = [], 1
    while True:
        batch = json.loads(get(
            f"https://api.github.com/orgs/{org}/repos?per_page=100&page={page}&type=public", token))
        if not batch:
            return repos
        repos += [r for r in batch if not r["archived"] and not r["fork"] and r["name"] != ".github"]
        page += 1


def count(org, repo):
    branch = repo["default_branch"]
    for name in TODO_NAMES:
        try:
            text = get(f"https://raw.githubusercontent.com/{org}/{repo['name']}/{branch}/{name}")
        except urllib.error.HTTPError:
            continue
        done, left = len(DONE.findall(text)), len(OPEN.findall(text))
        return repo["name"], done, left
    return repo["name"], None, None


def bar(pct, width=10):
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def status(d, l):
    """Short inline marker for one repo."""
    if d is None or d + l == 0:
        return "❔"
    if l == 0:
        return "✅"
    pct = int(100 * d / (d + l))
    return f"🚧 {pct}%" if d else "⏳ 0%"


def annotate(text, org, rows):
    """Append a status marker after every repo link outside the progress block."""
    by_name = {n: status(d, l) for n, d, l in rows}
    link = re.compile(
        r"(\[[^\]]+\]\(https://github\.com/" + re.escape(org) + r"/(tpt-[\w.-]+)\))(?:<!--s-->.*?<!--/s-->)?")

    def sub(m):
        st = by_name.get(m.group(2))
        return m.group(1) if st is None else f"{m.group(1)}<!--s--> {st}<!--/s-->"

    head, rest = text.split("<!-- PROGRESS:START -->", 1)
    block, tail = rest.split("<!-- PROGRESS:END -->", 1)
    return (link.sub(sub, head) + "<!-- PROGRESS:START -->" + block
            + "<!-- PROGRESS:END -->" + link.sub(sub, tail))


def render(org, rows):
    tracked = [(n, d, l) for n, d, l in rows if d is not None and d + l > 0]
    untracked = sorted(n for n, d, l in rows if d is None or d + l == 0)
    done = sum(d for _, d, _ in tracked)
    left = sum(l for _, _, l in tracked)
    total = done + left
    pct = 100 * done / total if total else 0
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    out = [
        f"**{done:,} of {total:,} tasks complete — {pct:.1f}%** `{bar(pct, 20)}`",
        "",
        "| Completed | Remaining | Total | Repos tracked | Repos with no `todo.md` |",
        "|---:|---:|---:|---:|---:|",
        f"| {done:,} | {left:,} | {total:,} | {len(tracked)} | {len(untracked)} |",
        "",
        f"<sub>Counted from `- [x]` / `- [ ]` checkboxes in each repo's `todo.md`. Updated {stamp} (UTC).</sub>",
        "",
        "<details><summary>Per-repo progress</summary>",
        "",
        "| Repo | Done | Left | Progress |",
        "|---|---:|---:|---|",
    ]
    for n, d, l in sorted(tracked, key=lambda r: (-(r[1] / (r[1] + r[2])), r[0])):
        p = 100 * d / (d + l)
        out.append(f"| [{n}](https://github.com/{org}/{n}) | {d} | {l} | `{bar(p)}` {p:.0f}% |")
    out += ["", "</details>"]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--org", default="tpt-solutions")
    ap.add_argument("--readme", default="README.md")
    args = ap.parse_args()
    token = os.environ.get("GITHUB_TOKEN")

    repos = list_repos(args.org, token)
    with cf.ThreadPoolExecutor(16) as ex:
        rows = list(ex.map(lambda r: count(args.org, r), repos))
    block = render(args.org, rows)

    with open(args.readme, encoding="utf-8") as f:
        text = f.read()
    pat = re.compile(r"(<!-- PROGRESS:START -->).*?(<!-- PROGRESS:END -->)", re.S)
    if not pat.search(text):
        raise SystemExit("README is missing the PROGRESS:START/END markers")
    text = pat.sub(lambda m: f"{m.group(1)}\n{block}\n{m.group(2)}", text)
    text = annotate(text, args.org, rows)
    with open(args.readme, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(block.splitlines()[0].split("`")[0].strip())


if __name__ == "__main__":
    main()
