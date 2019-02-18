# sc3nb

sc3nb - SuperCollider3 interface for python and jupyter notebooks

For more information, please read the documentation.


#### Building the Documentation

First you will need to install make, [sphinx](http://www.sphinx-doc.org/en/stable/tutorial.html) and the [sphinx napoleon plugin](https://pypi.python.org/pypi/sphinxcontrib-napoleon).

Then, cd into the docs directory:

```bash
cd PySon/docs
```

After that, you build the documentation easily with

```bash
make html
```

And find the index page under .../PySon/docs/build/html/index.html


#### Installation of sc3nb

To install, cd to the root directory of PySon and then:
```bash
pip install -e .
```
This will install the library in development mode (changes to sc3nb code will automatically be "re-installed").
For more information, please refer to the documentation.
