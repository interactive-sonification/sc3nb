# How to contribute

You can contribute by creating issues, making pull requests, improving the documentation or creating examples.

Please get in touch with us if you wish to contribute. We are happy to be involved in the discussion of new features and to receive pull requests and also looking forward to include notebooks using sc3nb in our examples.

We will honor contributors in our [Contributors list](CONTRIBUTORS.md). If you contribute with a pull request feel free to add yourself to the list.

## How to test / set up the development environment

Additional dependencies for sc3nb can be installed via the following extras:
tests, development, building docs, running test.


| Install        | Purpose                                                                      |
|:---------------|:-----------------------------------------------------------------------------|
| `[test]`       | running tox for tests and other things                                       |
| `[dev]`        | using the pre-commit hooks and installing other useful tools for development |
| `[docs]`       | building the docs                                                            |
| `[localtests]` | running pytest directly without tox, also used in tox as dependencies        |


## Development Guidelines

[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://pre-commit.com/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

To ensure standards are followed please install [pre-commit](https://pre-commit.com/)

We use:
* [black](https://github.com/psf/black) and [isort](https://github.com/PyCQA/isort) for formatting code
* [python type hints](https://docs.python.org/3/library/typing.html)
* [numpydoc](https://numpydoc.readthedocs.io/en/latest/example.html) docstring format. Also see [How to Document](https://numpy.org/doc/stable/docs/howto_document.html)


## How to contributing an example notebook

Feel free to suggest new example notebooks using sc3nb for all possible applications like sonification, music making or sound design.

Please use

```
import sc3nb as scn
sc = scn.startup()
```
 to import sc3nb and start the SC instance.

Also add `sc.exit()` to all notebooks at the end.

Please also try to make sure they work when using the doc generation script.


## How to prepare a release

The following checks should all be successful before creating a new release.

- run tests
  ```
  tox
  ```

- test build
  ```
  pip install --upgrade build
  python -m build
  ```

- test building the docs

  For building the documentation for the current branch use:
  ```
  tox -e docs
  ```
  Controll the output in `build/docs/html/`


Actual Release

- update changelog

  should contain information about the commits between the versions

- create a new git tag for this version

  We use [semantic versioning](https://semver.org/).
  Please always use 3 numbers like v1.0.0 for [setuptools_scm](https://github.com/pypa/setuptools_scm/#semantic-versioning-semver)

- clear build files
  ```
  rm dist build
  ```

- build
  ```
  pip install --upgrade build
  python -m build
  ```

- upload testpypi
  ```
  pip install --user --upgrade twine
  python -m twine upload --repository testpypi dist/*
  ```

- check [testpypi](https://test.pypi.org/project/sc3nb/)
  ```
  pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple sc3nb
  ```

- upload pypi
  ```
  python -m twine upload dist/*
  ```

- check [pypi](https://pypi.org/project/sc3nb/)
  ```
  pip install sc3nb
  ```

- build github-pages docs (after pushing the tag)

  Create the gh-pages documentation with
  ```
  tox -e docs -- --github
  ```
  Controll the output in `build/docs/gh-pages/repo/`.
  Push the changes
