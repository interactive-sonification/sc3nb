# How does this work?

- **sclang** and **scsynth** are started as subprocesses and their outputs are collected.
- **scsynth** is then controlled via OSC
  * Direct control of the server shortcuts the detour via sclang and is both more efficient and promises a lower latency
- **sclang** communication is done with pipes (bi-directional) and with OSC for receiving return values
