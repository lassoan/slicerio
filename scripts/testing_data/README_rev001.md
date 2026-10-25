# slicerio NRRD testing data, revision rev001

A suite of 34 NRRD files for implementing and testing NRRD readers and writers (for example
[nibabel NRRD support](https://github.com/nipy/nibabel/issues/356)). The files cover the variety of NRRD files that
[3D Slicer](https://www.slicer.org) reads and writes: 2D and 2D+t images, RGB and RGBA color images, 3D images
with anisotropic spacing and with oblique axes, 3D+t sequences, displacement fields and velocity fields (3D and 3D+t),
segmentations with and without overlapping segments, diffusion weighted (DWI) and diffusion tensor (DTI) images,
in LPS and in RAS coordinate systems, with gzip and raw encodings and a detached header.

All files are realistic (real anatomy, native or lightly reduced resolution) so that a reader's output can be judged
visually, and every file is at most 10 MB.

Files are assets of the `TestingData` release of slicerio:

```
https://github.com/lassoan/slicerio/releases/download/TestingData/<filename>
https://github.com/lassoan/slicerio/releases/download/TestingData/manifest_rev001.json
```

`manifest_rev001.json` lists every file with its size, SHA256 checksum, the main NRRD header fields, the Slicer
loader that reads it and the expected result of loading it (node class, dimensions, components, frames, segments,
layers, gradients, twin files that must load to the same geometry). The scripts that generated and verified the
files are in `scripts/testing_data/` of the [slicerio repository](https://github.com/lassoan/slicerio).

## How the files were made and verified

All files were written by **3D Slicer 5.13 (2026-10-24)** with its own file writers, from data loaded and processed
in Slicer, except the files marked *pynrrd* in the table: those are variants that Slicer cannot write (true 2D images,
RAS-space twins, 6-component symmetric tensors), derived with [pynrrd](https://github.com/mhe/pynrrd) from a
Slicer-written file, voxel values untouched.

Every file was verified by

- reloading it into Slicer and comparing voxels, geometry, components, frames, segments, gradients and transforms
  with the data it was written from (round trip);
- resampling images through the stored displacement fields and comparing the result voxel-for-voxel with the stored
  `*_resampled` reference images (also for the RAS twins of the fields);
- loading every file in Slicer 5.13 and in Slicer 5.12.4 (`check_test_data_in_slicer.py`);
- reading every file with pynrrd.

### Sources and acknowledgements

- **MRHead** (T1 MRI of a head), **CTCardioSeq** (4D cardiac CT), **DWIVolume**, **DTIBrain** and **BaselineVolume**
  are 3D Slicer [SampleData](https://slicer.readthedocs.io/en/latest/user_guide/modules/sampledata.html) sets.
- **Visible Human**: cryosections `a_vm1001.png` to `a_vm1240.png` (every 3rd slice) of the
  [Visible Human Project](https://www.nlm.nih.gov/research/visible/visible_human.html) male data set,
  *Courtesy of the U.S. National Library of Medicine*.
- The 3D+t displacement fields were computed by image registration with the
  [SequenceRegistration](https://github.com/moselhy/SlicerSequenceRegistration) extension of Slicer, which runs
  [Elastix](https://elastix.lumc.nl/) through the [SlicerElastix](https://github.com/lassoan/SlicerElastix)
  extension. The 3D displacement fields, the velocity fields and the segmentations are synthetic, derived from the
  images above.

## Data sets and rationale

### MRHead family (`MRHead_*`)

The base image `MRHead_3D.nrrd` is the SampleData MRHead resampled to a **deliberately anisotropic spacing of
1 x 1.25 x 1.6 mm** (256x205x106 voxels): every axis differs from every other by at least 20%, so a reader that
confuses axis order or spacing produces a visibly distorted image. MRHead was acquired sagittally, so its file axes
are not in R/A/S order either (axis 0 runs posterior, axis 1 inferior, axis 2 left), which exercises direction
cosines with permuted axes. All other MRHead-derived files (2D slice, RAS twin, raw and detached-header variants,
oblique volume, displacement and velocity fields, segmentations) share this geometry or are derived from it, so they
can be overlaid on each other.

- **Encodings**: `MRHead_3D.nrrd` is gzip encoded; `MRHead_3D_raw.nrrd` is raw (uncompressed, 2x downsampled to keep
  the file small); `MRHead_3D_detached.nhdr` + `MRHead_3D_detached.raw.gz` is a detached header with a
  gzip-compressed data file (`data file:` field).
- **Oblique axes**: `MRHead_3D_oblique.nrrd` is the same anatomy resampled onto a grid whose axes are rotated by
  20°, 10° and -5° about R, A and S (axes remain orthogonal, spacing unchanged). The grid is centered on the original
  volume and cropped to the largest box that fits inside it, so there is no padding: resampling the oblique volume
  back onto the axis-aligned grid reproduces `MRHead_3D.nrrd` within interpolation error (the generator checks this).
  A reader that mishandles non-axis-aligned direction cosines places this volume at the wrong position or
  orientation relative to `MRHead_3D.nrrd`.
- **2D**: `MRHead_2D.nrrd` is a true 2D NRRD (`dimension: 2`, `space dimension: 2`): the mid-sagittal slice with
  1 x 1.25 mm pixels.

### Visible Human color images (`VisibleHumanHead_*`)

Color cryosections of the Visible Human male head provide realistic **RGB** (`RGB-color` axis, 3 x unsigned char)
and **RGBA** (`RGBA-color`, 4 x unsigned char) data. The 3D volumes are cropped to the head, 4x block-averaged in
plane (1.32 mm pixels) and use every 3rd slice (3 mm). The alpha channel is a tissue mask (255 in the body, 0 in the
blue embedding gel and black background), so it carries information rather than a constant. The 2D files hold one
full-resolution (0.33 mm) cryosection as true 2D images (color axis + two `domain` axes, 2D space). The in-plane
orientation (anterior up, patient's left to the right of the image) is approximate: the photographs are not
registered to a scanner coordinate frame.

### Cardiac CT time series (`CTCardio_*`)

Five phases (0, 0.1, ... 0.4 s) of the 10-phase SampleData 4D cardiac CT, written as a Slicer **volume sequence**
(`.seq.nrrd`): the time axis is the last NRRD axis with kind `list`, the frame times are in `axis 3 index values`,
and `DataNodeClassName` tells Slicer what node type to create. `CTCardio_2Dt.seq.nrrd` is a true 2D+t file (one
axial slice of each frame, 2 `domain` axes + `list` axis, 2D space); Slicer has no 2D sequence reader and loads it
as one 5-component vector volume.

### Displacement fields and warped references

Displacement fields are the files most prone to convention errors, so each one ships with a **reference image
resampled through it** by Slicer:

- `MRHead_displacement.nrrd` is a synthetic thin-plate-spline deformation of MRHead (8 mm push in the center, ripple
  on a ring) converted to a grid transform on a 4x downsampled MRHead grid and written by Slicer's Transforms
  module. Slicer writes `displacement field type:=resampling` (the field is the *from-parent* / resampling
  transform: the output voxel at physical position `p` takes the input value at `p + d(p)`, with `d` in LPS) and
  `intent_code:=1006` (NIFTI_INTENT_DISPVECT, used in NRRD files as a de facto marker of displacement fields).
  `MRHead_displacement_resampled.nrrd` is `MRHead_3D.nrrd` resampled through it (linear interpolation, same grid).
- `MRHead_oblique_displacement.nrrd` is the identical physical deformation sampled on the oblique grid, with
  `MRHead_oblique_displacement_resampled.nrrd` as its reference.
- `CTCardio_3Dt_displacement.seq.nrrd` is a **3D+t displacement field sequence from image registration**: every
  cardiac phase of `CTCardio_3Dt.seq.nrrd` was registered to phase 0 (Elastix, "generic (all)" preset: affine +
  B-spline) and the resulting transforms (fixed frame 0 -> moving frame i, i.e. resampling transforms) were sampled
  on the 2x downsampled grid of frame 0 (frame 0 is the zero field). Slicer's transform sequence storage node wrote
  it with the same `intent_code:=1006` and `displacement field type:=resampling` fields as single displacement
  fields, and Slicer loads it back as a sequence of grid transforms. The reference
  `CTCardio_3Dt_displacement_resampled.seq.nrrd` is the motion-compensated sequence: frame i of
  `CTCardio_3Dt.seq.nrrd` resampled through displacement frame i onto the grid of frame 0, so all its frames
  resemble frame 0.

### Velocity fields

`MRHead_velocity.nrrd` (3D) and `CTCardio_3Dt_velocity.seq.nrrd` (3D+t, 4D-flow-MRI-like pulsatile swirl) are
synthetic smooth vector fields that are **not** transforms: 3 float32 `vector` components with an identity
`measurement frame`, no `displacement field type` and no intent code. The component axis is labelled `velocity`
with unit `mm/s` (`labels` and `units` fields), which is how Slicer stores the quantity and unit of voxel values.

### Segmentations (`.seg.nrrd`)

Slicer segmentations are NRRD files with `Segment<N>_*` header fields (ID, name, color, label value, layer, extent,
terminology tags) and `Segmentation_*` fields (source representation, conversion parameters); see
[SegmentationFileFormat.md](https://github.com/lassoan/slicerio/blob/main/SegmentationFileFormat.md).

- `MRHead_segmentation.seg.nrrd`: three **non-overlapping** segments (intensity tiers 20-60, 60-100, >100 of
  MRHead) stored in **one layer**: a plain 3D unsigned char labelmap.
- `MRHead_segmentation_overlapping.seg.nrrd`: three segments from **overlapping** intensity ranges (20-80, 60-140,
  >100). Overlapping segments cannot share a labelmap, so the file is **4D**: the first axis (kind `list`) indexes
  the layers, `space directions` starts with `none`, `Segment<N>_Layer` selects the layer and `Segment<N>_LabelValue`
  the value within it. The two non-overlapping segments share a layer, so the file has 2 layers for 3 segments.
- `MRHead_segmentation_oblique.seg.nrrd`: the non-overlapping tiers computed on the oblique volume (oblique
  `space directions` in a segmentation).

### Diffusion MRI

- `DWI_small.nrrd`: diffusion weighted MRI (SampleData DWI cropped to the head, b0 + 6 gradient directions). The
  gradient axis has kind `list`; `modality:=DWMRI`, `DWMRI_b-value:=1000` and `DWMRI_gradient_0000` ...
  `DWMRI_gradient_0006` key/value fields hold the diffusion encoding, and a `measurement frame` relates gradient
  directions to the image space. Slicer's Teem-based writer writes DWI in **RAS** space. `DWI_small_b0.nrrd` is the
  b=0 image as a plain scalar volume written by Slicer's ITK writer in **LPS**: the same physical grid expressed in
  the other coordinate system.
- `DTIBrain_3D_tensor.nrrd`: diffusion tensor image (SampleData DTI-Brain, native resolution) with a `3D-matrix`
  axis of 9 float components (row-major tensor), a `measurement frame`, RAS space.
  `DTIBrain_3D_tensor_symmetric.nrrd` stores the same tensors with the 6 unique components (`3D-symmetric-matrix`:
  xx xy xz yy yz zz). `DTIBrain_FA.nrrd` is the fractional anisotropy computed from the tensors on the same grid
  (LPS). `DTIBrain_baseline.nrrd` is the baseline anatomical image of the same Slicer diffusion tutorial; its grid
  differs from the DTI (different acquisition), so it is a companion image, not a voxel-aligned b0.

## Conventions worth knowing

- **Coordinate systems.** Slicer's ITK-based writers (scalar and vector volumes, sequences, displacement fields)
  write `space: left-posterior-superior`; the Teem-based writer used for DWI and DTI writes
  `space: right-anterior-superior` with a `measurement frame`. The `*_RAS*` files are twins of LPS files with the
  geometry converted to RAS (first two components of `space directions` and `space origin` negated, voxels
  unchanged); each must load at exactly the same physical position as its LPS original.
- **Vector components and measurement frame.** In the RAS twins of vector fields the components stay in LPS and
  `measurement frame: (-1,0,0) (0,-1,0) (0,0,1)` maps them to the RAS space. This is the only RAS form Slicer accepts
  as a transform: Slicer requires an identity measurement frame after converting to LPS, and it ignores the
  measurement frame when loading vector volumes. A RAS file whose vector components are in RAS with an identity
  measurement frame is valid NRRD, but Slicer would flip its x/y components (see `notes` in the manifest).
- **Displacement direction.** `displacement field type:=resampling` means the field maps output (fixed) positions to
  input (moving) positions. The `*_resampled*` files were produced exactly this way, so they verify both the
  direction and the coordinate system in which a reader applies the field.
- **2D files.** ITK (and therefore Slicer) refuses a file whose `space dimension` differs from the number of
  `domain` axes, so true 2D files use `space dimension: 2` with 2x2 `space directions` instead of a 3D `space`.
- **Sequences.** Slicer appends the time axis as the last axis with kind `list`; the component axis (color, vector)
  is the first axis. Frame index values are in `axis 3 index values` (or `axis 2 index values` for 2D+t).

## Files

Axes are given in NRRD order (`sizes` / `kinds`). Spacing is the length of the `space directions` vectors.

| File | Axes (sizes / kinds) | Type, space, spacing (mm) | Content | Relationship to other files |
|------|----------------------|---------------------------|---------|-----------------------------|
| `MRHead_3D.nrrd` | 256x205x106 / domain domain domain | short, LPS, 1 x 1.25 x 1.6, gzip | T1 MRI of a head (MRHead resampled to anisotropic spacing) | Base image of all `MRHead_*` files |
| `MRHead_3D_RAS.nrrd` | 256x205x106 / domain domain domain | short, RAS, 1 x 1.25 x 1.6, gzip | Same voxels as `MRHead_3D.nrrd` | RAS twin: must load at the same position as `MRHead_3D.nrrd` (pynrrd) |
| `MRHead_3D_raw.nrrd` | 128x102x53 / domain domain domain | short, LPS, 2 x 2.5 x 3.2, raw | MRHead 2x downsampled | Uncompressed variant of `MRHead_3D.nrrd` |
| `MRHead_3D_detached.nhdr` + `MRHead_3D_detached.raw.gz` | 128x102x53 / domain domain domain | short, LPS, 2 x 2.5 x 3.2, gzip data file | MRHead 2x downsampled | Detached-header variant of `MRHead_3D_raw.nrrd` (identical voxels) |
| `MRHead_3D_oblique.nrrd` | 182x146x75 / domain domain domain | short, LPS, 1 x 1.25 x 1.6, oblique axes | MRHead resampled onto a rotated grid cropped inside the original | Same anatomy and physical location as `MRHead_3D.nrrd` (Slicer, resampled) |
| `MRHead_2D.nrrd` | 256x205 / domain domain | short, 2D space, 1 x 1.25 | Mid-sagittal slice | Slice 53 of axis 2 of `MRHead_3D.nrrd` (pynrrd) |
| `VisibleHumanHead_3D_RGB.nrrd` | 3x190x200x80 / RGB-color domain domain domain | uchar, LPS, 1.32 x 1.32 x 3 | Color cryosections of the Visible Human male head | Same voxels as the first 3 channels of the RGBA file |
| `VisibleHumanHead_3D_RGBA.nrrd` | 4x190x200x80 / RGBA-color domain domain domain | uchar, LPS, 1.32 x 1.32 x 3 | Same with alpha = tissue mask | RGB channels identical to `VisibleHumanHead_3D_RGB.nrrd` |
| `VisibleHumanHead_2D_RGB.nrrd` | 3x760x800 / RGB-color domain domain | uchar, 2D space, 0.33 x 0.33 | One cryosection (a_vm1120) at full resolution | 2D counterpart of the 3D RGB volume (pynrrd) |
| `VisibleHumanHead_2D_RGBA.nrrd` | 4x760x800 / RGBA-color domain domain | uchar, 2D space, 0.33 x 0.33 | Same slice with alpha = tissue mask | 2D counterpart of the 3D RGBA volume (pynrrd) |
| `CTCardio_3Dt.seq.nrrd` | 128x104x72x5 / domain domain domain list | short, LPS, 1.15 x 1.15 x 2, t = 0..0.4 s | 5 phases of a cardiac CT | Input of the registration; frame 0 is the fixed frame of the displacement sequence |
| `CTCardio_2Dt.seq.nrrd` | 128x104x5 / domain domain list | short, 2D space, 1.15 x 1.15 | Axial slice 36 of every phase | 2D+t extract of `CTCardio_3Dt.seq.nrrd` (pynrrd); Slicer loads it as a 5-component vector volume |
| `CTCardio_3Dt_displacement.seq.nrrd` | 3x64x52x36x5 / vector domain domain domain list | float, LPS, 2.3 x 2.3 x 4.1; intent_code 1006, resampling | Registration transforms frame 0 -> frame i (frame 0 = zero field) | Warps frames of `CTCardio_3Dt.seq.nrrd` into `CTCardio_3Dt_displacement_resampled.seq.nrrd`; loads in Slicer as transform sequence |
| `CTCardio_3Dt_displacement_RAS.seq.nrrd` | 3x64x52x36x5 / vector domain domain domain list | float, RAS, measurement frame diag(-1,-1,1) | Same field, geometry in RAS | RAS twin of `CTCardio_3Dt_displacement.seq.nrrd` (pynrrd); warps identically |
| `CTCardio_3Dt_displacement_resampled.seq.nrrd` | 128x104x72x5 / domain domain domain list | short, LPS, 1.15 x 1.15 x 2 | Motion-compensated sequence (all frames resemble frame 0) | Frame i = frame i of `CTCardio_3Dt.seq.nrrd` resampled through displacement frame i |
| `CTCardio_3Dt_velocity.seq.nrrd` | 3x64x52x36x5 / vector domain domain domain list | float, LPS, 2.3 x 2.3 x 4.1; labels velocity, units mm/s | Synthetic pulsatile swirling velocity field | Same grid as the displacement sequence; not a transform |
| `MRHead_displacement.nrrd` | 3x64x51x26 / vector domain domain domain | double, LPS, 4 x 5.1 x 6.7, raw; intent_code 1006, resampling | Synthetic thin-plate-spline deformation (max 5 mm) as Slicer grid transform | Applied to `MRHead_3D.nrrd` gives `MRHead_displacement_resampled.nrrd` |
| `MRHead_displacement_RAS.nrrd` | 3x64x51x26 / vector domain domain domain | double, RAS, measurement frame diag(-1,-1,1) | Same field, geometry in RAS | RAS twin of `MRHead_displacement.nrrd` (pynrrd); warps identically |
| `MRHead_displacement_resampled.nrrd` | 256x205x106 / domain domain domain | short, LPS, 1 x 1.25 x 1.6 | MRHead warped by the displacement field | Reference for `MRHead_displacement.nrrd` (and its RAS twin) |
| `MRHead_oblique_displacement.nrrd` | 3x46x36x19 / vector domain domain domain | double, LPS, 4 x 5.2 x 6.6, oblique axes | The same physical deformation sampled on the oblique grid | Applied to `MRHead_3D_oblique.nrrd` gives `MRHead_oblique_displacement_resampled.nrrd` |
| `MRHead_oblique_displacement_resampled.nrrd` | 182x146x75 / domain domain domain | short, LPS, 1 x 1.25 x 1.6, oblique axes | Oblique MRHead warped by the oblique field | Reference for `MRHead_oblique_displacement.nrrd` |
| `MRHead_velocity.nrrd` | 3x128x102x53 / vector domain domain domain | float, LPS, 2 x 2.5 x 3.2; labels velocity, units mm/s | Synthetic smooth swirling velocity field | On the grid of `MRHead_3D_raw.nrrd`; not a transform |
| `MRHead_velocity_RAS.nrrd` | 3x128x102x53 / vector domain domain domain | float, RAS, measurement frame diag(-1,-1,1) | Same field, geometry in RAS | RAS twin of `MRHead_velocity.nrrd` (pynrrd) |
| `MRHead_segmentation.seg.nrrd` | 256x205x106 / domain domain domain | uchar, LPS, 1 x 1.25 x 1.6 | 3 non-overlapping intensity-tier segments, one layer | Segments `MRHead_3D.nrrd`; same grid |
| `MRHead_segmentation_RAS.seg.nrrd` | 256x205x106 / domain domain domain | uchar, RAS | Same segmentation, geometry in RAS | RAS twin of `MRHead_segmentation.seg.nrrd` (pynrrd) |
| `MRHead_segmentation_oblique.seg.nrrd` | 182x146x75 / domain domain domain | uchar, LPS, oblique axes | The intensity tiers of the oblique volume | Segments `MRHead_3D_oblique.nrrd`; same grid |
| `MRHead_segmentation_overlapping.seg.nrrd` | 2x256x205x106 / list domain domain domain | uchar, LPS, 1 x 1.25 x 1.6 | 3 segments from overlapping intensity ranges in 2 layers | Segments `MRHead_3D.nrrd`; 4D layout of a segmentation |
| `DWI_small.nrrd` | 7x92x119x80 / list domain domain domain | ushort, RAS, 1.5 x 1.5 x 1.5; DWMRI fields, measurement frame | Diffusion weighted MRI, b0 + 6 directions (b = 1000) | b0 image also in `DWI_small_b0.nrrd` |
| `DWI_small_b0.nrrd` | 92x119x80 / domain domain domain | ushort, LPS, 1.5 x 1.5 x 1.5 | The b=0 image of the DWI | Same physical grid as `DWI_small.nrrd`, written in LPS |
| `DTIBrain_3D_tensor.nrrd` | 9x144x144x85 / 3D-matrix domain domain domain | float, RAS, 1.67 x 1.67 x 1.7; measurement frame | Diffusion tensors (9 components, row-major) | Source of the symmetric variant and of the FA map |
| `DTIBrain_3D_tensor_symmetric.nrrd` | 6x144x144x85 / 3D-symmetric-matrix domain domain domain | float, RAS, 1.67 x 1.67 x 1.7 | Same tensors, 6 unique components | Derived from `DTIBrain_3D_tensor.nrrd` (pynrrd) |
| `DTIBrain_FA.nrrd` | 144x144x85 / domain domain domain | float, LPS, 1.67 x 1.67 x 1.7 | Fractional anisotropy (0..1) | Same physical grid as `DTIBrain_3D_tensor.nrrd`, written in LPS |
| `DTIBrain_baseline.nrrd` | 256x256x51 / domain domain domain | short, LPS, 1 x 1 x 2.6 | Baseline anatomical image of the diffusion tutorial | Companion of the DTI from the same tutorial; different grid |
