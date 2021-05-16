#!/usr/bin/env python

import argparse
import errno
import glob
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from sys import platform
from typing import Optional

SILENCE = "> /dev/null 2>&1"

# you usually want to run:
#   python docs/generate --doctree --publish --clean --no-show


def main():
    git_root = subprocess.check_output(
        f"git -C {os.path.dirname(__file__)} rev-parse --show-toplevel".split(" ")
    )
    git_root = str(git_root, "utf-8").strip()
    # checking dir
    os.chdir(git_root)
    current_path = Path().resolve()
    if current_path.parts[-1:] != ("sc3nb",):
        raise RuntimeWarning(
            f"Wrong current working dir! {current_path} Have you moved this script? Script must be in sc3nb project folder"
        )
    parser = argparse.ArgumentParser(description="Generates Sphinx documentation")
    parser.add_argument("--doctree", action="store_true", help="build complete doctree")
    parser.add_argument(
        "--publish", action="store_true", help="build and publish doctree"
    )
    parser.add_argument(
        "--no-show", action="store_true", help="do not open browser after build"
    )
    parser.add_argument(
        "--branches",
        nargs="*",
        default=["master", "develop"],
        help="limit doctree to these branches",
    )
    parser.add_argument(
        "--tags", nargs="*", default=None, help="limit doctree to these tags"
    )
    parser.add_argument(
        "--input",
        default=f"{git_root}/docs/source/",
        help="input folder (ignored for doctree)",
    )
    parser.add_argument("--out", default=f"{git_root}/build/", help="output folder")
    parser.add_argument(
        "--template-folder",
        default=f"{git_root}/docs/source/_templates",
        help="templates used for doctree",
    )
    parser.add_argument(
        "--clean", action="store_true", help="removes out folder before building doc"
    )
    args = parser.parse_args()
    args.doctree = args.doctree if not args.publish else True
    if args.clean and os.path.exists(args.out):
        print(f"Cleaning {args.out}")
        shutil.rmtree(args.out, ignore_errors=False, onerror=_handle_remove_readonly)
    os.makedirs(args.out, exist_ok=True)
    if not args.doctree:
        target = "html"
        build_doc(source=args.input, out=args.out, target=target)
        if not args.no_show:
            url = f"{args.out}/{target}/index.{target}"
            if platform == "darwin":
                os.system(f"open {url}")
            elif platform == "win32":
                os.startfile(url)
            else:
                raise NotImplementedError("'show' is not available for your platform")

    else:
        generate_gh_pages(
            out_folder=args.out,
            publish=args.publish,
            branches=args.branches,
            tags=args.tags,
            template_folder=args.template_folder,
            show=not args.no_show,
        )


def _handle_remove_readonly(func, path, exc):
    excvalue = exc[1]
    if (
        func in (os.rmdir, os.remove, os.unlink, os.scandir)
        and excvalue.errno == errno.EACCES
    ):
        os.chmod(path, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)  # 0777
        func(path)
    else:
        raise RuntimeError(f"Failed to remove {path}")


def strip_notebooks(path):
    print("Stripping notebooks")
    extra_keys = "metadata.kernelspec metadata.language_info"
    retval = 0
    for notebook in Path(path).glob("**/*.ipynb"):
        if ".ipynb_checkpoints" not in str(notebook):
            r = os.system(f'nbstripout {str(notebook)} --extra-keys "{extra_keys}"')
            if r == 0:
                print(f"  Stripped {notebook} - {r}")
            else:
                print("Error stripping {notebook}")
            retval += r
    return retval


def extract_notebooks_from_doc(path, subdir):
    print("Extracting notebooks from doc source files (.rst)")
    all_notebooks = []
    for filepath in Path(path).glob("**/*.rst"):
        with open(filepath) as file:
            content = file.read()
        notebooks = [
            line.strip().replace(subdir, "")
            for line in content.split("\n")
            if subdir in line
        ]
        print(f"  Extracted from {filepath}")
        for nb in notebooks:
            print(f"    {nb}")
        all_notebooks.extend(notebooks)
    return all_notebooks


def generate_notebook_links(
    notebooks_to_link, notebook_dir, doc_dir, link_subdir, media_dir
):
    print("Linking notebooks to doc source")
    project_dir = Path("..").resolve()

    nb_dir = Path(notebook_dir).resolve()
    nb_paths = [
        nb_path
        for nb_path in nb_dir.glob("**/*.ipynb")
        if ".ipynb_checkpoints" not in str(nb_path)
    ]
    links_path = Path(doc_dir + link_subdir)

    linked = []
    for notebook in notebooks_to_link:
        matches = [nb_path for nb_path in nb_paths if notebook in nb_path.as_posix()]
        if len(matches) < 1:
            print(f"> Warning: Could not find {notebook} in {nb_dir}")
        elif len(matches) > 1:
            raise RuntimeError(f"Found {notebook} multiple times {matches}")
        else:
            nb_path = matches[0]
            try:
                nb_path = nb_path.resolve()
                nb_link_path = (
                    (Path(links_path) / nb_path.relative_to(nb_dir))
                    .with_suffix(".nblink")
                    .resolve()
                )
                nb_relative_to_link = Path(
                    os.path.relpath(nb_path, nb_link_path.parent)
                ).as_posix()
                media_dir_relative = Path(
                    os.path.relpath(media_dir, nb_link_path.parent)
                ).as_posix()
                content = {
                    "path": nb_relative_to_link,
                    "extra-media": [media_dir_relative],
                }
                nb_link_path.parent.mkdir(parents=True, exist_ok=True)
                nb_link_path.write_text(json.dumps(content))
            except Exception as excep:
                print(excep)
            else:
                linked.append(nb_path)
                print(
                    f"  Linked {nb_path.relative_to(project_dir)} -> {nb_link_path.relative_to(project_dir)}"
                )
    for nb in [nb_path.as_posix() for nb_path in nb_paths if nb_path not in linked]:
        print(f"> Warning: Notebook {nb} is not linked")


def build_doc(
    source, out, target, strip=True, link=True, override: Optional[str] = None
):
    print(
        f"Generating documentation for {f'{target}/{override}' if override else f'{target}'}..."
    )

    # paths relative to gitroot
    notebooks_dir = "./examples/"
    notebook_doc_build_subdir = "autogen/notebooks/"
    media_dir = notebooks_dir + "media/"

    # Strip notebooks
    if strip:
        retval = strip_notebooks(notebooks_dir)
        if retval > 0:
            raise RuntimeError("Stripping Notebooks failed.")

    # link notebooks
    if link:
        notebooks_to_link = extract_notebooks_from_doc(
            source, subdir=notebook_doc_build_subdir
        )
        generate_notebook_links(
            notebooks_to_link,
            notebooks_dir,
            source,
            notebook_doc_build_subdir,
            media_dir,
        )

    # prevents __pycache__ files which we don't need when code runs only once.
    sys.dont_write_bytecode = True
    exec_str = f'sphinx-build -b {target} {f"-D {override}" if override else ""} {source} {out}/{target}'
    print(exec_str)
    res = os.system(exec_str)
    if res != 0:
        raise RuntimeError(
            f'Could not generate documentation for {f"{target}/{override}" if override else f"{target}"}. Build returned status code {res}!'
        )


def generate_gh_pages(
    out_folder,
    publish=False,
    branches=["master", "develop"],
    tags=None,
    template_folder=None,
    show=False,
):
    print("Generate github pages")
    gh_pages_root = f"{out_folder}gh-pages/"
    build_folder = f"{gh_pages_root}out/"
    os.makedirs(build_folder, exist_ok=True)

    repo = f"{gh_pages_root}sc3nb/"
    print(f"Check repo ({repo})")

    # update or clone repo
    if not os.path.exists(repo):
        os.system(
            f"git clone https://github.com/interactive-sonification/sc3nb.git {repo}"
        )
    else:
        if os.system(f"git -C {repo} checkout master") != 0:
            raise RuntimeError("Checking out master failed")
        if os.system(f"git -C {repo} pull --all") != 0:
            raise RuntimeError("Pulling {repo} failed")
        status = str(
            subprocess.check_output(f"git -C {repo} status --porcelain".split(" ")),
            "utf8",
        )
        if status != "":
            print(status)
            raise RuntimeError("Repo is dirty")

    if tags is None:
        out = subprocess.check_output(f"git -C {repo} show-ref --tags".split(" "))
        tags = [
            str(line.split(b" ")[1].split(b"/")[2], "utf-8")
            for line in out.split(b"\n")[::-1]
            if len(line)
        ]

    # first, check which documentation to generate
    def _has_docs(name):
        if os.system(f"git -C {repo} checkout -q {name}") != 0:
            raise RuntimeError("checking for docs failed")
        return os.path.exists(f"{repo}/docs")

    branches = [b for b in branches if _has_docs(b)]
    tags = [t for t in tags if _has_docs("tags/" + t)]
    print(f"Will generate documentation for:\n  Branches: {branches}\n  Tags: {tags}")

    # fix order of dropdown elements (most recent tag first, then branches and older tags)
    doclist = tags[:1] + branches + tags[1:]
    print("doclist={doclist}")
    # generate documentation; all versions have to be known for the dropdown menu
    for d in doclist:
        print(f"Generating documentation for {d} ...")
        target = d if d in branches else "tags/" + d
        res = os.system(f"git -C {repo} checkout {target} -f")
        if res != 0:
            raise RuntimeError(
                f"Could not checkout {d}. Git returned status code {res}!"
            )
        if template_folder:
            if os.path.exists(f"{repo}/docs/source/_templates"):
                shutil.rmtree(f"{repo}/docs/source/_templates")
            shutil.copytree(template_folder, f"{repo}/docs/source/_templates")

        override = f"version={d} -A versions={','.join(doclist)}"
        build_doc(
            source=os.path.join(repo, "docs/source/"),
            out=os.path.join(build_folder, d),
            target="html",
            override=override,
        )

    # create index html to forward to last tagged version
    if doclist:
        with open(f"{build_folder}/index.html", "w") as fp:
            fp.write(
                f"""<!DOCTYPE html>
<html>
  <head>
    <meta http-equiv="refresh" content="0; url={doclist[0]}/">
  </head>
</html>
"""
            )

    # prepare gh-pages
    os.system(f'git -C {repo} checkout -f "gh-pages"')
    print("Merging documentation...")
    for item in os.listdir(build_folder):
        s = os.path.join(build_folder, item)
        d = os.path.join(repo, item)
        print(f"Copying {item}")
        if os.path.isdir(s):
            s = os.path.join(s, "html")
            if os.path.exists(d):
                shutil.rmtree(d, ignore_errors=True)
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)
    print(f"Documentation tree has been written to {repo}")
    print("Current git status:")
    os.system(f"git -C {repo} status")

    # commit and push changes when publish has been passed
    if publish:
        os.system(f"git -C {repo} add -A")
        os.system(f'git -C {repo} commit -a -m "Update docs"')
        os.system(f"git -C {repo} push")

    if show:
        _run_webserver(os.path.normpath(repo))


def _run_webserver(root):
    import http.server
    import socketserver
    import threading
    import time

    def _delayed_open():
        url = f"http://localhost:8181/{os.path.basename(root)}/index.html"
        time.sleep(0.2)
        if sys.platform == "darwin":
            os.system(f"open {url}")
        elif sys.platform == "win32":
            os.startfile(url)
        else:
            raise NotImplementedError("'show' is not available for your platform")

    t = threading.Thread(target=_delayed_open)
    t.start()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=root + "/../", **kwargs)

        def log_message(self, format, *args):
            pass

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", 8181), Handler) as httpd:
        try:
            print("Starting preview webserver (disable with --no-show)...")
            print("Ctrl+C to kill server")
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("Exiting...")
            httpd.shutdown()


if __name__ == "__main__":
    main()
