# File formats for image segmentations

## Commonly used file formats

### DICOM

DICOM allows saving image segmentations along with rich, structured metadata in a standard, very well documented way in [DICOM Segmentation](https://dicom.nema.org/dicom/2013/output/chtml/part03/sect_A.51.html).

Pro:
- Compatibility with clinical software: DICOM is universally supported by all clinical imaging softare, DICOM Segmentation is not very widely supported but its adoption is increasing.
- Long-term stability: DICOM format is changed very slowly and carefully
- Rich, structured metadata storage, all defined carefully in the DICOM standard

Con:
- Standard is very large, complex
- Low performance: size of segmentation metadata may be huge (magnitudes larger than the segmentation data itself), encoding and decoding can be magnitudes slower compared to simple 3D image formats

### NRRD

Very simple and efficient file format for storing multi-dimensional images. 3D Slicer and related software established convention for [storing segmentation metadata](https://slicer.readthedocs.io/en/latest/developer_guide/modules/segmentations.html#segmentation-labelmap-file-format-seg-nrrd) (commonly referred to as `.seg.nrrd` files).

Pro:
- Very simple
- Compatibility with research software and toolkits: most libraries and research application support this file format
- Common convention exists for storing essential metadata
- File header is human-readable: easily readable, modifiable with any text editor

Con:
- Not compatible with clinical software
- Common conventions for metadata storage only include essential metadata (not as rich or structured as DICOM)

### NIFTI

Very limited, yet complex and ambiguous file format. Unfortunately, for historical reasons, it is commonly used in medical image computing.

Pro:
- Compatibility with research software and toolkits: most libraries and research application support this file format
- Somewhat simple: simpler than DICOM, but much more complex than NRRD
- It can store some neuroimaging-specific metadata in a standard way: this makes the file format beneficial for neuroimaging

Con:
- Orientation definition in NIFTI files can be ambiguous: there are multiple ways to define orientation, they can be both present, and contain contradicting information. Various softare will interpret these ambiguous files differently. See for example these discussions: [1](https://www.openfmri.org/dataset-orientation-issues/), [2](https://discourse.slicer.org/t/orientation-origin/23365), [3](https://github.com/spinalcordtoolbox/spinalcordtoolbox/issues/3283)
- Not compatible with clinical software
- Common convention for storing essential metadata does not exist
- File header is not human-readable: you cannot use a text editor/viewer to see the actual file header but you always have to rely on a parser to give you an interpretation of the file header

## Recommended file formats

- DICOM format is recommended for long-term archival due to compatibility and stability of the file format and the ability to encode rich, structured metadata in a well-defined manner.
- NRRD file format is recommended for local storage and data exchange, due to its simplicity, efficiency, and non-ambiguity.
- NIFTI format usage may be justified for neuroimaging, as many neuroimaging pipelines only support this format.
