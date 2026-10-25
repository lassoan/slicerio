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

## Files

All files were written by 3D Slicer 5.13 (2026-10) itself, except where the "Written by" column says *pynrrd*:
those are variants Slicer cannot write (true 2D images, RAS-space twins, 6-component symmetric tensors), derived
with [pynrrd](https://github.com/mhe/pynrrd) from a Slicer-written file and then verified by loading them into
Slicer. Every file loads in Slicer 5.13 and 5.12.4 (`check_test_data_in_slicer.py`). Sizes are approximate;
`manifest_rev001.json` has exact sizes and SHA256 checksums.

| File | Kind | Space | Written by | Size | Description |
|------|------|-------|------------|------|-------------|
| `MRHead_3D.nrrd` | 3D | LPS | Slicer | 4.4 MB | 3D scalar volume (short), gzip encoding. MRHead resampled to **anisotropic spacing 1 x 1.25 x 1.6 mm** (every axis differs by at least 20%, so axis-order mistakes show up), 256x205x106 voxels. All other MRHead-derived files use this grid. |
| `MRHead_3D_RAS.nrrd` | 3D | RAS | pynrrd | 4.1 MB | Same voxels with the geometry expressed in RAS (`space directions`/`space origin` x,y negated); loads at the identical position. |
| `MRHead_3D_oblique.nrrd` | 3D (oblique) | LPS | Slicer | 1.8 MB | `MRHead_3D.nrrd` resampled onto an **oblique grid** (axes rotated 20°, 10°, -5° about R, A, S; still orthogonal; same spacing) that is cropped to lie inside the original volume (182x146x75 voxels), so there is no padding. Same anatomy at the same physical location as `MRHead_3D.nrrd`; resampling one onto the other's grid lets you compare them. |
| `MRHead_3D_raw.nrrd` | 3D | LPS | Slicer | 1.4 MB | Raw (uncompressed) encoding, 2x downsampled (128x102x53). |
| `MRHead_3D_detached.nhdr` + `MRHead_3D_detached.raw.gz` | 3D | LPS | Slicer | 0.5 MB | Detached header with gzip-compressed data file, 2x downsampled. |
| `MRHead_2D.nrrd` | 2D | 2D | pynrrd | 0.04 MB | True 2D image (`dimension: 2`, `space dimension: 2`): mid-sagittal slice of `MRHead_3D.nrrd`, 256x205 pixels of 1 x 1.25 mm. |
| `VisibleHumanHead_3D_RGB.nrrd` | 3D+RGB | LPS | Slicer | 6.9 MB | RGB color volume (`RGB-color` axis + 3 domain axes, unsigned char), 190x200x80 @ 1.32x1.32x3 mm, Visible Human head. |
| `VisibleHumanHead_3D_RGBA.nrrd` | 3D+RGBA | LPS | Slicer | 7.5 MB | Same with an alpha channel (`RGBA-color`): 255 in the body, 0 in the blue embedding gel / black background. |
| `VisibleHumanHead_2D_RGB.nrrd` | 2D+RGB | 2D | pynrrd | 1.3 MB | True 2D RGB image (`RGB-color` + 2 domain axes, 2D space), one cryosection at full 0.33 mm resolution. |
| `VisibleHumanHead_2D_RGBA.nrrd` | 2D+RGBA | 2D | pynrrd | 1.4 MB | Same with alpha = tissue mask. |
| `CTCardio_3Dt.seq.nrrd` | 3D+t | LPS | Slicer | 6.8 MB | Volume sequence (Slicer `.seq.nrrd`): 5 cardiac phases, 128x104x72 short; time is the last (`list`) axis, `axis 3 index values` holds the frame times. |
| `CTCardio_2Dt.seq.nrrd` | 2D+t | 2D | pynrrd | 0.1 MB | True 2D+t: one axial slice of every frame (2 domain axes + `list` axis, 2D space). Slicer loads it as one 5-component vector volume, not as a sequence. |
| `MRHead_displacement.nrrd` | 3D+displacement | LPS | Slicer | 2.0 MB | Displacement field (`vector` axis, double, 64x51x26 @ 4x5x6.4 mm) written by Slicer as a grid transform, `displacement field type: resampling`, `intent_code: 1006`, raw encoding (Slicer default for transforms). |
| `MRHead_displacement_resampled.nrrd` | 3D (reference) | LPS | Slicer | 4.1 MB | `MRHead_3D.nrrd` resampled through `MRHead_displacement.nrrd` (linear interpolation, same grid as the source image). |
| `MRHead_oblique_displacement.nrrd` | 3D+displacement (oblique) | LPS | Slicer | 0.8 MB | The same physical deformation as `MRHead_displacement.nrrd`, sampled on a 4x downsampled grid of the oblique volume (oblique `space directions`). |
| `MRHead_oblique_displacement_resampled.nrrd` | 3D (reference, oblique) | LPS | Slicer | 1.7 MB | `MRHead_3D_oblique.nrrd` resampled through `MRHead_oblique_displacement.nrrd`. |
| `MRHead_displacement_RAS.nrrd` | 3D+displacement | RAS | pynrrd | 2.0 MB | RAS-space twin: geometry in RAS, vector components kept in LPS, `measurement frame: (-1,0,0) (0,-1,0) (0,0,1)`. Loads in Slicer as a transform and warps identically. |
| `MRHead_velocity.nrrd` | 3D+velocity | LPS | Slicer | 5.2 MB | Synthetic smooth velocity field (float32, `vector` axis labelled `velocity` with unit `mm/s`, identity `measurement frame`), 128x102x53. Not a transform (no `displacement field type`). |
| `MRHead_velocity_RAS.nrrd` | 3D+velocity | RAS | pynrrd | 4.8 MB | RAS-space twin (components in LPS, `measurement frame` diag(-1,-1,1)). |
| `CTCardio_3Dt_displacement.seq.nrrd` | 3D+t+displacement | LPS | Slicer | 5.4 MB | Vector volume sequence (`vector` + 3 domain + `list`): 5 displacement fields (64x52x36, float32) obtained by **image registration** of the cardiac phases to phase 0 with the [SequenceRegistration](https://github.com/moselhy/SlicerSequenceRegistration) extension (Elastix, "generic (all)" preset: affine + B-spline). Frame i maps frame 0 positions to frame i positions (frame 0 is the zero field). Written by Slicer's transform sequence storage node with the same `intent_code:=1006` and `displacement field type:=resampling` key/value fields as single displacement fields; Slicer loads it back as a sequence of grid transform nodes. |
| `CTCardio_3Dt_displacement_resampled.seq.nrrd` | 3D+t (reference) | LPS | Slicer | 6.7 MB | Motion-compensated sequence: frame i of `CTCardio_3Dt.seq.nrrd` resampled through displacement frame i onto the grid of frame 0 (all frames resemble frame 0). |
| `CTCardio_3Dt_displacement_RAS.seq.nrrd` | 3D+t+displacement | RAS | pynrrd | 5.4 MB | RAS-space twin of the displacement sequence (components in LPS, `measurement frame` diag(-1,-1,1)). |
| `CTCardio_3Dt_velocity.seq.nrrd` | 3D+t+velocity | LPS | Slicer | 3.7 MB | Synthetic pulsatile swirling velocity field sequence (float32), 4D-flow-MRI-like; the component axis carries `labels: "velocity"` and `units: "mm/s"`. |
| `MRHead_segmentation.seg.nrrd` | 3D segmentation | LPS | Slicer | 0.4 MB | Slicer segmentation, 3 non-overlapping segments in one layer: 3D unsigned char labelmap + `Segment<N>_*` fields (name, color, label value, layer, extent, terminology). |
| `MRHead_segmentation_RAS.seg.nrrd` | 3D segmentation | RAS | pynrrd | 0.4 MB | RAS-space twin (header-only change). |
| `MRHead_segmentation_oblique.seg.nrrd` | 3D segmentation (oblique) | LPS | Slicer | 0.2 MB | The same intensity tiers computed on `MRHead_3D_oblique.nrrd`: a segmentation with oblique `space directions`. |
| `MRHead_segmentation_overlapping.seg.nrrd` | 3D segmentation (overlapping) | LPS | Slicer | 0.6 MB | 3 segments from **overlapping intensity ranges** of the anatomy (20-80, 60-140, >100) stored in 2 layers: 4D file (`list` axis first, `space directions` starts with `none`); `Segment<N>_Layer` selects the layer, `Segment<N>_LabelValue` the value within it (the two non-overlapping segments share a layer). |
| `DWI_small.nrrd` | 3D DWI | RAS | Slicer | 10.1 MB | Diffusion weighted MRI: b0 + 6 gradient images (`list` axis, unsigned short, 92x119x80 @ 1.5 mm) with `modality:=DWMRI`, `DWMRI_b-value`, `DWMRI_gradient_NNNN` and `measurement frame`. Slicer's Teem-based writer writes DWI in RAS. |
| `DWI_small_b0.nrrd` | 3D | LPS | Slicer | 1.2 MB | The b0 image of `DWI_small.nrrd` as a scalar volume (ITK writer, LPS): same physical grid as the RAS DWI file. |
| `DTIBrain_3D_tensor.nrrd` | 3D DTI | RAS | Slicer | 9.5 MB | Diffusion tensor volume: `3D-matrix` axis (9 float components, row-major tensor) + 3 domain axes, `measurement frame`, 144x144x85 @ 1.67 mm; RAS (Teem writer). |
| `DTIBrain_3D_tensor_symmetric.nrrd` | 3D DTI | RAS | pynrrd | 6.9 MB | Same tensors with the 6 unique components (`3D-symmetric-matrix`: xx xy xz yy yz zz). |
| `DTIBrain_FA.nrrd` | 3D | LPS | Slicer | 1.1 MB | Fractional anisotropy computed from the tensors, same grid (ITK writer, LPS). |
| `DTIBrain_baseline.nrrd` | 3D | LPS | Slicer | 2.9 MB | Baseline anatomical image of Slicer's diffusion tutorial (256x256x51 @ 1x1x2.6 mm). Its grid differs from the DTI (different acquisition); it is a companion image, not a voxel-aligned b0. |

### Sources and acknowledgements

- **MRHead**, **CTCardioSeq** (4D cardiac CT), **DWIVolume**, **DTIBrain**, **BaselineVolume**: 3D Slicer
  [SampleData](https://slicer.readthedocs.io/en/latest/user_guide/modules/sampledata.html) sets, loaded and
  re-saved by Slicer (cropped / downsampled / truncated as described above).
- **Visible Human**: cryosections `a_vm1001.png` to `a_vm1240.png` (every 3rd slice) of the
  [Visible Human Project](https://www.nlm.nih.gov/research/visible/visible_human.html) male data set,
  *Courtesy of the U.S. National Library of Medicine*, cropped to the head and 4x block-averaged. The in-plane
  orientation was set so that anterior is up and the patient's left is on the image's left-to-right axis; it is
  approximate (the photographs are not registered to a scanner frame).
- The 3D+t displacement fields come from image registration of the cardiac CT phases with the
  [SequenceRegistration](https://github.com/moselhy/SlicerSequenceRegistration) extension, which runs
  [Elastix](https://elastix.lumc.nl/) through the [SlicerElastix](https://github.com/lassoan/SlicerElastix) extension.
  The 3D displacement field, the velocity fields and the segmentations are synthetic, derived from the images above.

### Conventions worth knowing

- **Coordinate systems.** Slicer's ITK-based writers (scalar/vector volumes, `.seq.nrrd` sequences, displacement
  fields) always write `space: left-posterior-superior`; its Teem-based writer used for DWI and DTI writes
  `space: right-anterior-superior` with a `measurement frame`. The `*_RAS*` files are synthetic twins of LPS files
  with the geometry converted to RAS; they must load at exactly the same physical position as their LPS originals.
- **Vector components and measurement frame.** In the RAS twins of vector fields the components are kept in LPS and
  `measurement frame: (-1,0,0) (0,-1,0) (0,0,1)` maps them to the RAS space. This is the only RAS form that Slicer
  accepts as a transform: Slicer requires an identity measurement frame after conversion to LPS, and it ignores the
  measurement frame when loading vector volumes. A RAS file whose vector components are in RAS with an identity
  measurement frame is valid NRRD but Slicer would flip its x/y components (see `notes` in `manifest_rev001.json`).
- **Displacement fields.** `displacement field type: resampling` (what Slicer writes) means the field is the
  *from-parent* transform: the output image value at physical position `p` is the input image sampled at
  `p + d(p)`, with `d` in LPS. The `*_resampled*` files were produced exactly this way and let you verify that a
  reader applies the field in the right direction and coordinate system. The 3D+t displacement sequence uses the
  same convention and the same key/value fields (`intent_code:=1006`, `displacement field type:=resampling`), with
  the time axis appended as the last (`list`) axis: frame i is the registration result "fixed frame 0 → moving
  frame i", so resampling frame i through it yields the motion-compensated frame stored in
  `CTCardio_3Dt_displacement_resampled.seq.nrrd`. Slicer recognizes the intent code and loads such a file as a
  sequence of grid transforms rather than vector volumes.
- **Geometry checks.** The MRHead grid is deliberately anisotropic (1 x 1.25 x 1.6 mm) and the `*_oblique*` files
  put the same anatomy on a rotated grid that is cropped inside the original volume. A reader that confuses axis
  order, spacing or direction cosines will place these volumes differently; resampling the oblique volume onto
  the axis-aligned grid must reproduce `MRHead_3D.nrrd` (the generator checks this).
- **2D files.** ITK (and therefore Slicer) refuses a file whose `space dimension` differs from the number of `domain`
  axes, so true 2D files use `space dimension: 2` with 2x2 `space directions` instead of a 3D `space`.
- **Segmentations.** See [SegmentationFileFormat.md](../../SegmentationFileFormat.md) for the `.seg.nrrd` fields.

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
2. Upload all files of `.testing_data/` (including `manifest_<revision>.json`, excluding `cache/`) as assets of the `TestingData`
   release, for example with the GitHub CLI:

   ```
   gh release create TestingData --title "Testing data" --notes "NRRD test data sets, see scripts/testing_data/README.md" .testing_data/*.nrrd .testing_data/*.nhdr .testing_data/*.gz .testing_data/manifest_rev001.json
   ```

   (use `gh release upload TestingData ...` to add files to the existing release). For a new revision of the data set,
   run the generator with e.g. `--revision rev002`, give changed data files new names (release assets are addressed by
   name, so an older manifest must keep pointing at unchanged files), upload the new files with `manifest_rev002.json`,
   and update `MANIFEST_URL` in `check_test_data_in_slicer.py`.
3. Run `check_test_data_in_slicer.py` without arguments to verify the published assets.

The `TestingData` release tag is excluded from the PyPI publishing workflow (`.github/workflows/python-publish.yml`).
