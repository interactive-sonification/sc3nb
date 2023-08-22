# Changelog

## Version 1.0.3

- Bundler Improvements
  - Improve Bundler.add and the respective example notebook
  - Add OSC Bundle splitting feature
- Reduce SC warning frequency
- Add curve argument to s1 SynthDef
- Use s1 instead of s2 in Server.blip
- Improve how the Sever init hooks are stored and allow removing them
- Save binary blobs of SynthDefs added using the SynthDef class
- Use pyamapping
- Update pre-commit hooks and GitHub actions
- Fix bugs and typos

[See all changes](https://github.com/interactive-sonification/sc3nb/compare/v1.0.2...v1.0.3)

## Version 1.0.2

- Improve Server.boot by checking first for already booted scsynth instance
- Improve ServerOptions hardware device specification
- Improve default SuperCollider installation paths for Windows
- Add Server.remote workaround for issue #15
- Fix a typo in node.py
- Improve docs
    - Add score notebook
    - Improve doc build and update CONTRIBUTING.md
- Update pre-commit hooks

[See all changes](https://github.com/interactive-sonification/sc3nb/compare/v1.0.1...v1.0.2)

## Version 1.0.1

- first PyPI release
