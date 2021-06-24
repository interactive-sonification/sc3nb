# sc3nb

sc3nb is a python package that offers an interface to SuperCollider3 (SC3), with special support to be used within jupyter notebooks.

* [Documentation](https://interactive-sonification.github.io/sc3nb)
* [Source code](https://github.com/interactive-sonification/sc3nb)
* [Bug reports](https://github.com/interactive-sonification/sc3nb/issues)


The goal of sc3nb is to facilitate the development of auditory displays and interactive sonifications by teaming up
* python (and particularly numpy, scipy, pandas, matplotlib etc.) for data science
* and SuperCollider3 for interactive real-time sound rendering.
​

It allows:
* to interface with the SuperCollider audio server (scsynth) aswell as the SuperCollider Language and Interpreter (sclang) via the SC class
* The SuperCollider audio server can be started and addressed via
  * OSC directly with OSC messages and bundles
  * Python implementations of Classes from SuperCollider like `Synth`, `SynthDef`, `Buffer` and `Bus`
  * the `Score` class for non-realtime synthesis
* use the SuperCollider language (sclang) interactively via a subprocess.
  * write SuperCollider language code in Jupyter Notebooks and let sclang evaluate it.
  * inject Python variables into your sclang code
  * get the results of the sclang code in Python
* helper functions such as linlin, cpsmidi, midicps, clip, ampdb, dbamp which work like their SC3 counterparts.


sc3nb can be used for
* multi-channel audio processing
* auditory display and sonification
* sound synthesis experiment
* audio applications in general such as games or GUI-enhancements
* signal analysis and plotting
* computer music and just-in-time music control
* any usecase that the SuperCollider 3 language supports


It is meant to grow into a backend for a sonification package, and can be used both from jupyter and in standard python software development.

## Installation

- To use sc3nb you need a installation of SuperCollider on your system. See [SuperCollider Download](https://supercollider.github.io/download) for installation files.
- To install sc3nb you can
  - install it locally in editable mode (i.e. changes to sc3nb code will automatically be "re-installed").
    - clone the repository from https://github.com/interactive-sonification/sc3nb
    - from inside the sc3nb directory run `pip install -e .`
  - or install it directly from GitHub using `pip install git+git://github.com/interactive-sonification/sc3nb@master`
  - we are also currently making sure that sc3nb can also be installed via `pip install sc3nb` from PyPI

## Examples

We provide examples in the form of Jupyter notebooks. You see them executed in the User Guide section of the [documentation](https://interactive-sonification.github.io/sc3nb) and also download them from the [sc3nb examples folder](https://github.com/interactive-sonification/sc3nb/tree/master/examples).
