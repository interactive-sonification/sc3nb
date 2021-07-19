# Support, Caveats and Problems

We strongly encourage you to share any problems that arise using sc3nb with us.

There are some things to consider when using sc3nb.


- The shortcut `ctrl/cmd + .` does currently only work in classic Jupyter notebooks, yet not in JupyterLab. It also will import sc3nb as `sc3nb` and thus you should avoid variables with the name `sc3nb`.
- We depend on the output to stdout of sclang and scsynth in some cases such as the startup of the server - or more obviously - for the sclang output when using `cmd()` with verbosity. This means if some language settings or updates of sclang/scsynth change the outputs to something that we don't expect, stuff will fail. However this should be quite easy to patch.
- There is an [issue #104 in Jupyter](https://github.com/jupyter/jupyter_client/issues/104) that does leave sclang and scsynth running when restarting the Jupyter kernel. To avoid this we use `atexit` to cleanup the processes. However calling `exit()` on the SC instance should be preferred. To avoid conflicts with orphaned sclangs/scsynths we also look for leftover sclang/scsynth processes on starting either of them and we try to kill them. This might lead to killing sclang or scsynth processes that you wanted to keep alive. However, you can specify which parent processes are allowed for sclang/scsynth processes using the `allowed_parents` parameter.
- The SuperCollider objects are currently not guaranteed to be thread-safe, with the exception of Node (Synth & Group)
- Another thing about SuperCollider in general is, to keep in mind that there are limits in the network communication: currently we only support UDP and therefore have the corresponding limits. As an example, a Bundler will simply fail when you try to send too many messages.
