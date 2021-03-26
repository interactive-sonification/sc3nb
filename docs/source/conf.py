# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import os
import sys

sys.path.insert(0, os.path.abspath("../.."))

# -- Project information -----------------------------------------------------

project = "sc3nb"
copyright = "2021, Thomas Hermann"
author = "Thomas Hermann"


# -- General configuration ---------------------------------------------------

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
    "sphinx.ext.mathjax",
    "nbsphinx_link",  # support notebooks outside of doc/source via .nblink files
    "autoapi.extension",  # autoapi from https://github.com/readthedocs/sphinx-autoapi
    "sphinx_rtd_theme",  # read the docs theme
]

autosummary_generate = True

numpydoc_validation_checks = {"all", "GL01", "GL02", "GL05"}

intersphinx_mapping = {"python": ("https://docs.python.org/dev", None)}

autoapi_type = "python"  # autoapi
autoapi_dirs = ["../../sc3nb"]
autoapi_root = "autogen/autoapi"
autoapi_add_toctree_entry = False
autoapi_python_class_content = "both"
autoapi_template_dir = "./_templates/autoapi/"

# nbsphinx_allow_errors = True
nbsphinx_execute_arguments = [
    "--InlineBackend.figure_formats={'png', 'svg', 'pdf'}",
]

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
