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

Both need network. Neither runs in CI: `build_signatures.py --check` guards the
generated file against the vendored numbers, and re-vendoring is a decision
somebody makes — a capture appearing or changing upstream should land as a
reviewable diff, not as a build that quietly starts describing different roads.
