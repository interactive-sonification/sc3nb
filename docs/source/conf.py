# Configuration file for the Sphinx documentation builder.
#
# For a full list of options see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html


import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#

sys.path.insert(0, os.path.abspath(os.path.join("..", "..")))

# -- Project information -----------------------------------------------------

project = "sc3nb"
copyright = "2021, Thomas Hermann, Dennis Reinsch"
author = "Thomas Hermann, Dennis Reinsch"

# -- General configuration ---------------------------------------------------

on_rtd = os.environ.get("READTHEDOCS") == "True"

git_rev_exact_match = False
try:
    git_rev = subprocess.check_output(
        ["git", "describe", "--exact-match", "HEAD"], universal_newlines=True
    )
    git_rev_exact_match = True
except subprocess.CalledProcessError:
    try:
        git_rev = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], universal_newlines=True
        )
    except subprocess.CalledProcessError as error:
        print(f"Failed to get git_rev - {error}")
        print(f"Using 'develop' instead")
        git_rev = "develop"
if git_rev:
    git_rev = git_rev.splitlines()[0]
    print(f"Using git_rev={git_rev}")

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = "sphinx_rtd_theme"
html_theme_options = {"collapse_navigation": False}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ["_static"]
html_css_files = [
    "css/custom.css",
]  # custom css to break long signatures. ref https://github.com/sphinx-doc/sphinx/issues/1514

# -- Options for extensions --------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    "sphinx.ext.autosummary",
    "sphinx.ext.doctest",
    "sphinx.ext.autodoc",  # generate doc
    "sphinx.ext.viewcode",  # generate links to source
    "sphinx.ext.intersphinx",  # allows linking to other projects
    "numpydoc",  # numpy docstring support
    "nbsphinx",  # include notebooks in doc
    "nbsphinx_link",  # support notebooks outside of doc/source via .nblink files
    "sphinx.ext.mathjax",
    "autoapi.extension",  # autoapi from https://github.com/readthedocs/sphinx-autoapi
    "sphinx_rtd_theme",  # read the docs theme
    "myst_parser",  # for supporting markdown
]

suppress_warnings = ["myst.mathjax"]

autosummary_generate = True

numpydoc_validation_checks = {"all", "GL01", "GL02", "GL05"}

intersphinx_mapping = {"python": ("https://docs.python.org/dev", None)}

# -- autoapi -----------------------------------------------------------------

autoapi_type = "python"  # autoapi
autoapi_dirs = ["../../src"]
autoapi_root = "autogen/autoapi"
autoapi_add_toctree_entry = False
autoapi_python_class_content = (
    "both"  # TODO remove this when all classes have the right doc style
)
autoapi_template_dir = "./_templates/autoapi/"


# -- nbsphinx ----------------------------------------------------------------

# nbsphinx_allow_errors = True
nbsphinx_execute_arguments = [
    "--InlineBackend.figure_formats={'png', 'svg', 'pdf'}",
]

# This is processed by Jinja2 and inserted before each notebook
nbsphinx_prolog = (
    r"""
{% if env.metadata[env.docname]['nbsphinx-link-target'] %}
{% set docpath = env.docname |replace("autogen/notebooks", "examples") + ".ipynb" %}
{% else %}
{% set docpath = env.doc2path(env.docname, base='docs/source/') %}
{% endif %}

.. only:: html

    .. role:: raw-html(raw)
        :format: html

    .. nbinfo::
        This page was generated from `{{ docpath }}`__.

    __ https://github.com/interactive-sonification/sc3nb/blob/"""
    + git_rev
    + r"""/{{ docpath }}

.. raw:: latex

    \nbsphinxstartnotebook{\scriptsize\noindent\strut
    \textcolor{gray}{The following section was generated from
    \sphinxcode{\sphinxupquote{\strut {{ docpath | escape_latex }}}} \dotfill}}

"""
)

# This is processed by Jinja2 and inserted after each notebook
nbsphinx_epilog = r"""
{% if env.metadata[env.docname]['nbsphinx-link-target'] %}
{% set docpath = env.docname |replace("autogen/notebooks", "examples") + ".ipynb" %}
{% else %}
{% set docpath = env.doc2path(env.docname, base='docs/source/') %}
{% endif %}

.. raw:: latex

    \nbsphinxstopnotebook{\scriptsize\noindent\strut
    \textcolor{gray}{\dotfill\ \sphinxcode{\sphinxupquote{\strut
    {{ docpath | escape_latex }}}} ends here.}}
"""

# TODO currently readthedocs uses ubuntu18.04, this is old
# it also does not support starting supercollider as it lacks X server support.
# https://docs.readthedocs.io/en/stable/config-file/v2.html#build-apt-packages
if on_rtd:
    nbsphinx_execute = "never"

# -- RTD theme lower left ----------------------------------------------------
# Configuration for the menu on the lower left. Thanks to
# https://stackoverflow.com/questions/49331914/enable-versions-in-sidebar-in-sphinx-read-the-docs-theme
# https://tech.michaelaltfield.net/2020/07/23/sphinx-rtd-github-pages-2/

if not on_rtd:
    html_context = {}
    html_context["display_lower_left"] = True

    # SET CURRENT_VERSION
    from git import Repo

    repo = Repo(search_parent_directories=True)

    if git_rev_exact_match:
        current_version = git_rev  # tag
    else:
        current_version = repo.active_branch.name

    # tell the theme which version we're currently on ('current_version' affects
    # the lower-left rtd menu and 'version' affects the logo-area version)
    html_context["current_version"] = current_version
    html_context["version"] = current_version

    # POPULATE LINKS TO OTHER VERSIONS
    html_context["versions"] = [
        ("stable", "https://interactive-sonification.github.io/sc3nb/stable/")
    ]
    versions = [branch.name for branch in repo.branches if branch != "gh-pages"]
    for version in versions:
        html_context["versions"].append(
            (
                version,
                "https://interactive-sonification.github.io/sc3nb/" + version + "/",
            )
        )

# -- Custom code -------------------------------------------------------------

# Preparing notebooks


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
                print(f"Error stripping {notebook}")
            retval += r
    return retval


def extract_notebooks_from_doc(path, subdir):
    print("Extracting notebooks from doc source files")
    all_notebooks = []
    for filepath in Path(path).glob("**/*.md"):
        with open(filepath) as file:
            content = file.read()
        notebooks = [
            line.strip().replace(subdir, "")
            for line in content.split("\n")
            if subdir in line
        ]
        if notebooks:
            print(f"  Extracted from {filepath}")
            for nb in notebooks:
                print(f"    {nb}")
        all_notebooks.extend(notebooks)
    return all_notebooks


def generate_notebook_links(
    notebooks_to_link, notebook_dir, doc_dir, link_subdir, media_dir
):
    print("Linking notebooks to doc source")

    nb_dir = Path(notebook_dir).resolve()
    nb_paths = [
        nb_path
        for nb_path in nb_dir.glob("**/*.ipynb")
        if ".ipynb_checkpoints" not in str(nb_path)
    ]
    links_path = Path(doc_dir + link_subdir)
    if links_path.exists():
        shutil.rmtree(links_path, ignore_errors=True)
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
                project_dir = Path("../..").resolve()
                print(
                    f"  Linked {nb_path.resolve().relative_to(project_dir)} -> {nb_link_path.resolve().relative_to(project_dir)}"
                )
    for nb in [nb_path.as_posix() for nb_path in nb_paths if nb_path not in linked]:
        print(f"> Warning: Notebook {nb} is not linked")


def prepare_notebooks():
    print("Preparing notebooks...")
    notebooks_dir = "../../examples/"
    notebook_doc_build_subdir = "autogen/notebooks/"
    media_dir = notebooks_dir + "media/"
    source = "./"

    retval = strip_notebooks(notebooks_dir)
    if retval > 0:
        raise RuntimeError("Stripping Notebooks failed.")

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
    print("Done preparing notebooks.")


prepare_notebooks()
