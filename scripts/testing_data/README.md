# NRRD testing data

Scripts that generate, verify and publish a suite of NRRD test images covering the variety of files that
[3D Slicer](https://www.slicer.org) reads and writes: 2D, 2D+t, 2D color (RGB/RGBA), 3D, 3D+t, 3D color,
displacement fields and velocity fields (3D and 3D+t), segmentations with and without overlapping segments,
diffusion weighted (DWI) and diffusion tensor (DTI) images, in LPS and in RAS coordinate systems, with gzip and
raw encodings and a detached header. The files were created for implementing and testing NRRD readers in other
software (for example [nibabel](https://github.com/nipy/nibabel/issues/356)).

The data files are **not** stored in this repository. They are attached as assets to the
[`TestingData` release](https://github.com/lassoan/slicerio/releases/tag/TestingData) of slicerio, together with
`manifest_rev001.json` that describes every file (purpose, source, how it was made, SHA256, size, expected NRRD header
fields, Slicer loader to use). Download pattern:

```
https://github.com/lassoan/slicerio/releases/download/TestingData/<filename>
https://github.com/lassoan/slicerio/releases/download/TestingData/manifest_rev001.json
```

The manifest carries a revision suffix so that later revisions of the data set can be published as additional
assets of the same release, each described by its own `manifest_<revision>.json`.

## Data set documentation

The content and rationale of every data set, the conventions used (coordinate systems, measurement frames,
displacement direction, 2D files, sequences, segmentations) and a per-file table are documented in
[README_rev001.md](README_rev001.md), which is also published as an asset of the release next to
`manifest_rev001.json`. Each data set revision has its own `README_<revision>.md` and `manifest_<revision>.json`.

## Scripts

| Script | Runs in | Purpose |
|--------|---------|---------|
| `generate_test_data.py` | Slicer | Downloads the sources, derives and writes every file, verifies that each file round-trips (reload and compare voxels, geometry, segments, gradients, transforms) and that the displacement fields reproduce the stored resampled images, writes `manifest_<revision>.json` into the output folder. |
| `check_test_data_in_slicer.py` | Slicer | Reads the manifest (`manifest_rev001.json` of the release by default, or a local path), downloads missing files (SHA256-verified), loads every file with the right loader and checks class, dimensions, components, frames, segments, layers, gradients and LPS/RAS twin geometry. |
| `run_in_slicer.py` | host Python | Runs one of the scripts above inside a running Slicer through the Web Server module's `exec` endpoint (can also start Slicer). |

### Running

Start Slicer with the Web Server "Slicer API exec" endpoint enabled (or enable it in the Web Server module GUI):

```
Slicer.exe --python-code "from WebServer import WebServerLogic; wsLogic = WebServerLogic(port=2016, enableExec=True); wsLogic.start()"
```

then, from the repository root (any Python with `requests`):

```
python scripts/testing_data/run_in_slicer.py generate_test_data.py --revision rev001
python scripts/testing_data/run_in_slicer.py check_test_data_in_slicer.py --manifest .testing_data/manifest_rev001.json
python scripts/testing_data/run_in_slicer.py check_test_data_in_slicer.py      # checks the published release
```

`--revision` (required) names the data set revision used in the manifest file name. `generate_test_data.py --only mrhead,dwi` regenerates selected groups only (`mrhead`, `visiblehuman`, `ctcardio`,
`displacement`, `segmentation`, `dwi`, `dti`); `--max-mb` sets the per-file size ceiling (default 10 MB).
The `ctcardio` group needs the **SequenceRegistration** and **SlicerElastix** extensions (install them with the
Extensions Manager). With a developer build of Slicer, their scripted modules can be loaded from source checkouts
instead: `--extra-module-paths "C:\path\SlicerElastix\Elastix\Elastix.py;C:\path\SlicerSequenceRegistration\SequenceRegistration\SequenceRegistration.py"`
(the Elastix module then needs the `Elastix/CustomElastixPath` application setting pointing to a folder with the
`elastix` and `transformix` executables).
Generated files go to the git-ignored `.testing_data/` folder in the repository root (`--output` overrides it);
downloads are cached in `.testing_data/cache/`. The scripts can also be started without the web server:
`Slicer.exe --no-main-window --python-script scripts/testing_data/generate_test_data.py -- --revision rev001 --output <dir>`.

### Publishing a new version of the data

1. Regenerate everything with a current Slicer build and make sure both scripts report success.
2. Upload all files of `.testing_data/` (including `manifest_<revision>.json`, excluding `cache/`) together with
   `scripts/testing_data/README_<revision>.md` as assets of the `TestingData`
   release, for example with the GitHub CLI:

   ```
   gh release create TestingData --title "Testing data" --notes "NRRD test data sets, see scripts/testing_data/README.md" .testing_data/*.nrrd .testing_data/*.nhdr .testing_data/*.gz .testing_data/manifest_rev001.json scripts/testing_data/README_rev001.md
   ```

   (use `gh release upload TestingData ...` to add files to the existing release). For a new revision of the data set,
   run the generator with e.g. `--revision rev002`, give changed data files new names (release assets are addressed by
   name, so an older manifest must keep pointing at unchanged files), upload the new files with `manifest_rev002.json`,
   write `README_rev002.md`, and update `MANIFEST_URL` in `check_test_data_in_slicer.py`.
3. Run `check_test_data_in_slicer.py` without arguments to verify the published assets.

The `TestingData` release tag is excluded from the PyPI publishing workflow (`.github/workflows/python-publish.yml`).
