#!/usr/bin/env python
# coding: utf-8

import sys
import os

import argparse
import json
import subprocess

from pathlib import Path


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
    for filepath in Path(path).glob('**/*.rst'):
        with open(filepath) as file:
            content = file.read()
        notebooks = [line.strip().replace(subdir,"") for line in content.split('\n') if subdir in line]
        print(f"  Extracted from {filepath}")
        for nb in notebooks:
            print(f"    {nb}")
        all_notebooks.extend(notebooks)
    return all_notebooks

def generate_notebook_links(notebooks_to_link,
                            notebook_dir,
                            doc_dir,
                            link_subdir,
                            media_dir):
    print("Linking notebooks to doc source")
    project_dir = Path("..").resolve()

    nb_dir = Path(notebook_dir).resolve()
    nb_paths = [nb_path for nb_path in nb_dir.glob("**/*.ipynb") if ".ipynb_checkpoints" not in str(nb_path)]
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
                nb_link_path = (Path(links_path) / nb_path.relative_to(nb_dir)).with_suffix(".nblink").resolve()
                nb_relative_to_link = Path(os.path.relpath(nb_path, nb_link_path.parent)).as_posix()
                media_dir_relative = Path(os.path.relpath(media_dir, nb_link_path.parent)).as_posix()
                content = {"path": nb_relative_to_link, "extra-media": [media_dir_relative]}
                nb_link_path.parent.mkdir(parents=True, exist_ok=True)
                nb_link_path.write_text(json.dumps(content))
            except Exception as excep:
                print(excep)
            else:
                linked.append(nb_path)
                print(f"  Linked {nb_path.relative_to(project_dir)} -> {nb_link_path.relative_to(project_dir)}")
    for nb in [nb_path.as_posix() for nb_path in nb_paths if nb_path not in linked]:
        print(f"> Warning: Notebook {nb} is not linked")

def make(target, subprocess_args):
    print(f"make {target}")
    process = subprocess.Popen(["make", target], **subprocess_args)
    return process.wait()
    
def main():
    parser = argparse.ArgumentParser(description="Generates documentation sources")
    parser.add_argument('-a', '--all', action='store_true', help='do all steps')
    parser.add_argument('-s', '--strip', action='store_true', help='strip notebooks')
    parser.add_argument('-l', '--link', action='store_true', help='link notebooks')
    parser.add_argument('-b', '--build', action='store_true', help='build doc')
    args = parser.parse_args()
    if not any(vars(args).values()):
        parser.error('No arguments provided.')
        sys.exit(1)
    # checking dir
    os.chdir(os.path.dirname(sys.argv[0]))
    current_path = Path().resolve()
    if current_path.parts[-2:] != ('sc3nb', 'docs'):
        raise RuntimeWarning(f"Wrong current working dir! Have you moved this script?")

    docs_dir = "./source/"
    notebook_doc_subdir = "autogen/notebooks/"
    notebooks_dir = "../examples/"
    media_dir = notebooks_dir + "media/"

    retval = 0

    # Strip notebooks
    if args.strip or args.all:
        retval += strip_notebooks(notebooks_dir)

    # link notebooks
    if args.link or args.all:
        notebooks_to_link = extract_notebooks_from_doc(docs_dir, notebook_doc_subdir)
        generate_notebook_links(notebooks_to_link,
                                notebooks_dir,
                                docs_dir,
                                notebook_doc_subdir,
                                media_dir)

    # build doc
    if args.build or args.all:
        subprocess_args = dict(cwd="../docs/",
                               stdout=sys.stdout,
                               stderr=subprocess.STDOUT,
                               shell=True)
        retval += make("clean", subprocess_args)
        retval += make("html", subprocess_args)
    return retval

if __name__ == "__main__":
    sys.exit(main())
