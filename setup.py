from setuptools import find_packages, setup

with open("README.md", "r", encoding="utf-8") as file:
    long_description = file.read()

with open("requirements.txt") as read_file:
    REQUIRED = read_file.read().splitlines()

setup(
    name="sc3nb",
    version="0.0.1",
    description="SuperCollider3 (sc3) jupyter notebook class and magics",
    long_description=long_description,
    long_description_content_type="text/markdown",
    license="MIT",
    packages=find_packages(exclude=["tests"]),
    install_requires=REQUIRED,
    author="Thomas Hermann",
    author_email="thermann@techfak.uni-bielefeld.de",
    keywords=["sonification, sound synthesis"],
    url="https://github.com/thomas-hermann/sc3nb",
)
