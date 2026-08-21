# vendor/

Third-party data this repository builds on, and the licence it arrives under.

## `circuits.json`

Measurements distilled from [zetetos/gt-telemetry](https://github.com/zetetos/gt-telemetry)
`data/circuits/*.json` — 84 recordings of a car going round a GT7 circuit, MIT
licensed, licence text in `gt-telemetry-LICENSE`.

Each row is one recording reduced to what `tools/build_signatures.py` needs: the
bounding box of the line, its two endpoints, its length, the names to match it to
`catalog/tracks.json` by, and the line itself at one point every `path_step_m`
metres **in driving order**. The `sha256` is of the upstream file the numbers
came from.

The line is thinned rather than carried whole. That is not a size compromise: the
app indexes a path on a 20 m grid to work out which way round a lap went, so a
finer spacing changes no answer it can give. It happens to take 35 MB to 350 kB.

Driving order is the one property that has to survive — a bounding box cannot
tell a layout from its reverse, and the order the road is driven in is what
separates them. A line sorted by position would be worse than no line, because
it would produce a confident wrong answer instead of a decline.

Nothing here may draw borders from these lines: a capture is one line down the
middle of the road and carries no width, so any edge derived from it would be
invented. See the header of `tools/vendor_captures.py`.

Refresh it, and see whether upstream has moved, with:

```
python tools/vendor_captures.py            # rewrite from upstream main
python tools/vendor_captures.py --check    # fail if upstream has moved
```

Both need network, and both print what moved — which circuits appeared,
vanished, or were re-recorded — rather than only a count.

`.github/workflows/vendor.yml` runs the refresh weekly. When upstream has moved
and everything still passes, it rebuilds `signatures.json`, runs the whole check
suite and **merges itself**, then asks the pack and the site to republish —
a merge made by a workflow does not start one, so main would otherwise carry
signatures that nothing published.

It stops and opens a **draft pull request** when the new data includes a name
that maps to no configuration, or when any check fails. The signature build
refuses such a name on purpose: it is either a circuit worth a row or an
upstream rename worth a line in `CAPTURE_NAME_FIXES`, and the file cannot tell
which. The re-vendored captures are already on the branch, so making the call
and pushing is the only work left.

Neither command runs on an ordinary pull request. `build_signatures.py --check`
is what guards the generated file there, offline, against whatever is vendored.
