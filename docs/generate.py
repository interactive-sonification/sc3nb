#!/usr/bin/env python

import argparse
import copy
import errno
import glob
import os
import shutil
import stat
import sys
from pathlib import Path
from sys import platform
from typing import Optional, Sequence

from bs4 import BeautifulSoup
from git import Repo


def main():
    repo = Repo(search_parent_directories=True)
    git_root = repo.working_dir
    if git_root is None:
        raise RuntimeError("No git working dir found.")
    os.chdir(git_root)

    parser = argparse.ArgumentParser(description="Generates Sphinx documentation")
    parser.add_argument("--github", action="store_true", help="build gh-pages")
    parser.add_argument(
        "--commit", action="store_true", help="create a commit (only when --github)"
    )
    parser.add_argument(
        "--show", action="store_true", help="open in browser after build"
    )
    parser.add_argument(
        "--branches",
        nargs="*",
        default=["master", "develop"],
        help="limit build to these branches (only when --github)",
    )
    parser.add_argument(
        "--tags",
        nargs="*",
        default=None,
        help="limit build to these tags (only when --github)",
    )
    parser.add_argument(
        "--input",
        default=f"{git_root}/docs/source/",
        help="input folder (ignored for gh-pages)",
    )
    parser.add_argument(
        "--output", default=f"{git_root}/build/docs/", help="output folder"
    )
    parser.add_argument(
        "--clean", action="store_true", help="removes out folder before building doc"
    )
    args = parser.parse_args()

    # preparing output folder
    if args.clean and os.path.exists(args.output):
        print(f"Cleaning {args.output}")
        rm_dir(args.output)
    os.makedirs(args.output, exist_ok=True)

    if not args.github:
        target = "html"
        docs_root = build_doc(
            source=Path(args.input), out=Path(args.output), target=target
        )
    else:
        docs_root = generate_gh_pages(
            repo=repo,
            out_folder=Path(args.output),
            branches=args.branches,
            tags=args.tags,
            commit=args.commit,
            clean=args.clean,
        )
    if args.show:
        url = docs_root
        if platform == "darwin":
            os.system(f"open {url}")
        elif platform == "win32":
            os.startfile(url)
        else:
            raise NotImplementedError("'show' is not available for your platform")

    # if args.show:
    #    _run_webserver(os.path.normpath(repo))


def fix_all_links(path, versions):
    def change_dd_tag(tag, rst_version):
        new_tag = copy.copy(tag)
        splits = new_tag.a["href"].split("/")
        splits[-2] = rst_version
        new_tag.a["href"] = "/".join(splits)
        new_tag.a.string = rst_version
        return new_tag

    def _fix_links(path, versions):
        with open(path, "r", encoding="utf8", errors="ignore") as file:
            content = file.read()
            soup = BeautifulSoup(content, features="html.parser")
        divs = soup.find_all("div", class_="rst-versions")
        if len(divs) != 1:
            print(f"Matched {len(divs)} divs in file: {path}")
        else:
            div = divs[0]
            if "/repo/stable/" in Path(path).as_posix():
                current_version = "stable"
            else:
                current_version = (
                    div.find("span", class_="rst-current-version")
                    .contents[2]
                    .strip()
                    .split()[1]
                )
            dl = div.find("dl")
            dt = dl.dt.extract()
            dd = dl.dd.extract()
            dds = [change_dd_tag(dd, version) for version in versions]
            dl.clear()
            dl.insert(0, dt)
            dl.extend(dds)
            for dd in dds:
                if dd.text == current_version:
                    strong = soup.new_tag("strong")
                    dd.wrap(strong)
            # write file
            with open(path, "w", encoding="utf8") as file:
                file.write(str(soup))

    files = glob.glob(f"{path}/**/*.html", recursive=True)
    for file in files:
        print(f"Fixing links in {file}")
        _fix_links(file, versions)


def _handle_remove_readonly(func, path, exc):
    excvalue = exc[1]
    if (
        func not in (os.rmdir, os.remove, os.unlink, os.scandir)
        or excvalue.errno != errno.EACCES
    ):
        raise RuntimeError(f"Failed to remove {path}")

    os.chmod(path, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)  # 0777
    func(path)


def rm_dir(path):
    shutil.rmtree(path, ignore_errors=False, onerror=_handle_remove_readonly)


def build_doc(
    source: Path, out: Path, target: str, additional_options: Optional[str] = ""
):
    print(f"Starting sphinx-build for target {target} {additional_options} ...")
    # prevents __pycache__ files which we don't need when code runs only once.
    docs_out = out / target
    sys.dont_write_bytecode = True
    exec_str = f"sphinx-build -b {target} {additional_options} {source} {docs_out}"
    print(exec_str)
    res = os.system(exec_str)
    if res != 0:
        raise RuntimeError(
            f"Could not generate documentation for {target} {additional_options}. Build returned status code {res}!"
        )
    print(f"Done generating documentation for {target} {additional_options}.")
    return docs_out


def generate_gh_pages(
    repo: Repo,
    out_folder: Path,
    branches: Sequence[str] = ("master", "develop"),
    tags: Sequence[str] = (),
    commit: bool = False,
    clean: bool = False,
):
    print("Generate github pages")
    gh_pages_root = out_folder / "gh-pages"
    build_folder = gh_pages_root / "out"
    if build_folder.exists():
        rm_dir(build_folder)
    os.makedirs(build_folder)

    tmp_repo_path = gh_pages_root / "repo"
    if tmp_repo_path.exists() and not clean:
        tmp_repo = Repo(tmp_repo_path)
        tmp_repo.git.checkout("--guess", "gh-pages", "--")
        print(f"Pulling repo...")
        tmp_repo.git.pull("-a")
    else:
        print(f"Cloning repo...")
        tmp_repo = Repo.clone_from(repo.remote().url, tmp_repo_path)

    print("Checking repo...")
    tmp_repo.git.clean("--force", "-d", "-x")
    tmp_repo.git.checkout("--guess", "gh-pages", "--")

    documented = [
        p.name
        for p in tmp_repo_path.iterdir()
        if p.is_dir() and p.parent == tmp_repo_path and not p.name.startswith(".")
    ]

    if not tags:

        def check_version(tag, min_version):
            return tuple(map(int, tag[1:].split("."))) >= min_version

        tags = [tag.name for tag in tmp_repo.tags if check_version(tag.name, (1, 0, 1))]

    # first, check which documentation to generate
    def has_docs(name):
        previous_branch = tmp_repo.active_branch
        tmp_repo.git.checkout("--guess", name, "--")
        docs_found = (tmp_repo_path / "docs").exists()
        tmp_repo.git.checkout("--guess", previous_branch, "--")
        return docs_found

    branches = [b for b in branches if has_docs(b)]
    tags = [t for t in tags if has_docs("tags/" + t) and t[1:] not in documented]
    print(
        f"Will generate documentation for:\n  already documented: {documented}\n  Branches: {branches}\n  Tags: {tags}"
    )
    stable = tags[-1] if tags else None
    print(f"new stable version {stable}")
    # fix order of dropdown elements (most recent tag first, then branches and older tags)
    doclist = branches + tags
    print(f"doclist={doclist}")
    # generate documentation; all versions have to be known for the dropdown menu
    for d in doclist:
        print(f"Generating documentation for {d} ...")
        target = d if d in branches else "tags/" + d
        tmp_repo.git.checkout("--guess", target, "--")
        tmp_repo.git.clean("--force", "-d", "-x")
        build_doc(
            source=tmp_repo_path / "docs/source",
            out=build_folder / d,
            target="html",
        )

    # create index html to forward to last tagged version
    with open(f"{build_folder}/index.html", "w") as fp:
        fp.write(
            f"""<!DOCTYPE html>
<html>
  <head>
    <meta http-equiv="refresh" content="0; url=stable/">
  </head>
</html>
"""
        )

    # prepare gh-pages
    tmp_repo.git.checkout("--guess", "gh-pages", "--")
    tmp_repo.git.clean("--force", "-d", "-x")

    print(f"Merging documentation in {tmp_repo_path}...")
    for item in build_folder.iterdir():
        s = build_folder / item.name
        d = tmp_repo_path / item.name
        print(f" - {item.name}: {s} -> {d}")
        if s.is_dir():
            s = s / "html"
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
            shutil.copytree(s, d, copy_function=shutil.copy)
        else:
            shutil.copy(s, d)
        if stable is not None and item == stable:
            print(f"Copying {s} as new stable version")
            stable_path = tmp_repo_path / "stable"
            shutil.rmtree(stable_path, ignore_errors=True)
            shutil.copytree(s, stable_path, copy_function=shutil.copy)

    print(f"Documentation has been merged in {tmp_repo.working_dir}")
    # refresh the documented list
    documented = [
        p.name
        for p in tmp_repo_path.iterdir()
        if p.is_dir() and p.parent == tmp_repo_path and not p.name.startswith(".")
    ]
    print(f"Fixing links to other versions {documented}")
    fix_all_links(tmp_repo.working_dir, versions=documented)
    print("Current git status:")
    status = tmp_repo.git.status("--short")
    print(status)
    if commit and status:
        print("Creating commit")
        with tmp_repo.config_writer() as writer:
            writer.set_value(
                "user", "name", repo.config_reader().get_value("user", "name")
            )
            writer.set_value(
                "user", "email", repo.config_reader().get_value("user", "email")
            )
        tmp_repo.git.add(".")
        tmp_repo.git.commit("-m Update docs")
        print(f"Control the commit in {tmp_repo.working_dir}")

    return gh_pages_root


if __name__ == "__main__":
    main()
