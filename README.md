# sc3nb

sc3nb - SuperCollider3 interface for python and jupyter notebooks

For more information, please read the documentation.

#### Building the Documentation

First you will need to install make, [sphinx](http://www.sphinx-doc.org/en/stable/tutorial.html) and the [sphinx napoleon plugin](https://pypi.python.org/pypi/sphinxcontrib-napoleon).

Then, cd into the docs directory:

```bash
cd sc3nb/docs
```

After that, you build the documentation easily with

```bash
make html
```

And find the index page under .../sc3nb/docs/build/html/index.html


#### Installation of sc3nb

To install, cd to the root directory of sc3nb and then:
```bash
pip install -e .
```
This will install the library in development mode (i.e. changes to sc3nb code will automatically be "re-installed").
For more information, please refer to the documentation.
