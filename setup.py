# Minimal setup.py to allow editable installs via pip intstall --editable .
# See https://setuptools.readthedocs.io/en/latest/userguide/quickstart.html#development-mode
import setuptools

setuptools.setup(
    use_scm_version=True,
)
