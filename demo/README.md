# Static case explorer

Twelve cases precomputed on IBM AMLworld HI-Small (synthetic) by `muletrace demo build`: eight
accounts at evenly spaced ranks across the alert list of 9 September 2022 (false positives
included) and four accounts that received an accepted MED-style dispute in the simulated Pix
layer, with their fund-flow traces. Each case shows the calibrated score and reason codes, the
evidence, and a case file drafted by the model-free template baseline and checked by the fact
checker. No person has reviewed the case files, and no language model wrote them.

```bash
uv run muletrace demo build            # needs the prepared data, cached snapshots and model
python -m http.server --directory demo # then open http://localhost:8000
```

The page is plain HTML, CSS and JavaScript with no dependencies. `.github/workflows/pages.yml`
publishes this folder to GitHub Pages when it changes on `main`.

`cases.json` contains data derived from IBM AMLworld (CDLA-Sharing-1.0, see
[`data/LICENSES`](../data/LICENSES)) and synthetic Pix-layer descriptions.
