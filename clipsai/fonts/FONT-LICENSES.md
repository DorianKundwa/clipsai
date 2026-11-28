# Bundled fonts

All faces in this folder are licensed under the SIL Open Font License 1.1, which
allows them to be bundled and redistributed with this package.

| File | Family | Upstream |
| --- | --- | --- |
| `Montserrat-ExtraBold.ttf` | Montserrat ExtraBold | https://fonts.google.com/specimen/Montserrat — see `Montserrat-OFL.txt` |
| `ArchivoBlack-Regular.ttf` | Archivo Black | https://fonts.google.com/specimen/Archivo+Black — see `ArchivoBlack-OFL.txt` |
| `NotoSerif-Bold.ttf` | Noto Serif Bold | https://fonts.google.com/noto/specimen/Noto+Serif — SIL OFL 1.1, Copyright 2022 The Noto Project Authors |

The full OFL 1.1 text is reproduced in `Montserrat-OFL.txt` and
`ArchivoBlack-OFL.txt`; it applies equally to Noto Serif.

Fonts are resolved through `clipsai.typography`; libass receives this folder as
its `fontsdir` so burned captions use these files rather than a fallback face.
