# groundgate-calibrate

This package moved into groundgate. From groundgate 0.11, the tool is the command
`groundgate calibrate`, with the same steps and options. It is experimental.

```bash
pip uninstall groundgate-calibrate
pip install "groundgate>=0.11"
groundgate calibrate --help
```

This is the last release of groundgate-calibrate. It requires `groundgate>=0.11`. The
`groundgate-calibrate` command prints one line that tells you to change, then runs
`groundgate calibrate` with your arguments.

[Measure a judge's thresholds](https://github.com/mohanraj00/groundgate/blob/main/docs/howto/calibrate.md)
runs every step. [The calibrate reference](https://github.com/mohanraj00/groundgate/blob/main/docs/calibrate.md)
gives each command and each rule.
