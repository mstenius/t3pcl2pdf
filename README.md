# t3pcl2pdf

Convert **T3 Scientific Word Processor** PCL print output to PDF.

Mårten Stenius - marten@stenius.org

**The T3 Scientific Word Processor** from the 1980s–90s could be set up to print to an HP LaserJet II printer. It did this by first downloading its own bitmap soft fonts to the printer, then sending the document. When running T3 in DOSBox with a virtual printer, this produces `.prt` files that `gpcl6` (Ghostscript's PCL interpreter) cannot handle correctly without those fonts — the result has wrong Swedish/special characters, garbled formula symbols, and oddly spread text.

This tool reconstructs a self-contained PCL stream by prepending the T3 bitmap fonts, then converts it to a PDF with layout and characters to reproduced to some extent.

As such, the result is not a replica of the original printouts but at least a link in the chain to export documents
in the archaic T3 format to something more accessible.

The script is the result of iterative experimentation with various sample documents with indispensable analytic help by Claude Opus 4.8 - both in figuring out how to get rid of the strange bold character effects and how to properly embed the fonts in the PCL streams before converting.

## Features

- Rendering of formula/math symbols (S1 and Symbol fonts)
- Removes T3's shadow-bold overprints so text is clean (not doubled/ghosted)
- Supports T3's full Swedish extended font set (58 fonts)
- Rendering of Swedish characters (å, ä, ö and uppercase equivalents)

## Prerequisites

### 0. DOSBox

Install DOSBox on your system using whatever method is best suited.

In your DOSBox `.conf`, configure a virtual LPT1 printer that writes to a file:

```ini
[parallel]
parallel1 = file timeout:4000 
```

This will direct any printer output to LPT1 to a `.prt` file in the directory configured in the `captures`
setting, such as: 

```ini
[dosbox]
...
captures = ~/dos/dosbox
```

### 1. Ghostscript with gpcl6

Use the preferred method on your system. For example, on MacOS X:

```bash
brew install ghostscript
```

Verify: `gpcl6 --version`

### 2. PCL URW fonts

On MacOS X the Homebrew Ghostscript package includes `gpcl6` but not the URW TrueType fonts it needs. They ship in the GhostPDL source tarball. Run this once:

```bash
GS_VERSION=$(gs --version)
curl -L "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs${GS_VERSION/./}/ghostpdl-${GS_VERSION}.tar.xz" \
     -o /tmp/ghostpdl.tar.xz
tar -xJf /tmp/ghostpdl.tar.xz "ghostpdl-${GS_VERSION}/pcl/urwfonts"
mkdir -p /opt/homebrew/share/ghostscript/pcl-fonts
 cp "ghostpdl-${GS_VERSION}/pcl/urwfonts/"*.ttf /opt/homebrew/share/ghostscript/pcl-fonts/
```

> If that URL doesn't work, find the matching tarball at  
> https://github.com/ArtifexSoftware/ghostpdl-downloads/releases

Apologies for the above, it is somewhat messy and could probably be simplified.

### 3. T3 installation with HPLJ fonts

You need a full T3 installation configured for HP LaserJet II printing. The recommended way is to (somehow) locate original T3 installation media and perform a complete installatin from scratch in your DOSBox environment.

Such an installation will contain `.HPP` bitmap font files (`IBM12.HPP`, `KU.HPP`, `IBM17SV.HPP`, etc.). In a typical DOSBox setup they live at:

```
~/dos/drive-c/T3/HPLJ/
```

The script auto-detects this path. If yours is elsewhere, use `--hplj` or set `T3_HPLJ_DIR`.

## Usage

Start T3 in DOSBox. In T3, open and print the desired document.

This should result in a `.prt` file in the configured captures directory.

Convert the `.prt` to pdf:

```bash
python3 t3pcl2pdf.py filename.prt
```

This produces `filename.pdf` in the same directory.

### Options

```
python3 t3pcl2pdf.py [options] input.prt [output.pdf]

  --hplj DIR       Path to T3 HPLJ font directory
                   (default: auto-detect, or env T3_HPLJ_DIR)
  --pcl-fonts DIR  Path to Ghostscript PCL URW fonts
                   (default: env PCLFONTSOURCE, or /opt/homebrew/share/ghostscript/pcl-fonts)
  --paper a4|letter  Paper size (default: a4)
  --no-dedup       Disable shadow-bold deduplication (shows original overprints)
```

### Examples

```bash
# Basic conversion (auto-detect T3 fonts)
python3 t3pcl2pdf.py filename.prt

# Explicit paths
python3 t3pcl2pdf.py --hplj ~/dos/drive-c/T3/HPLJ filename.prt output.pdf

# Via environment variables
export T3_HPLJ_DIR=~/dos/drive-c/T3/HPLJ
export PCLFONTSOURCE=/opt/homebrew/share/ghostscript/pcl-fonts
python3 t3pcl2pdf.py t3x_001.prt

# US Letter paper
python3 t3pcl2pdf.py --paper letter t3x_001.prt
```

## How it works

### Why standard gpcl6 fails with T3 output

T3's print process has two phases:

1. **Font loading**: Before printing, T3 runs batch files (`LDPPELSV.BAT` etc.) that send each bitmap soft font to the printer as a PCL soft-font download command.

2. **Document printing**: T3 sends the document, referencing those fonts by ID.

When captured to `.prt` files via DOSBox, only phase 2 is used — the font downloads happen in a separate process. `gpcl6` receives a PCL stream that references font IDs with no definitions, and falls back to URW vector fonts with incompatible character encodings.

### What this tool does

1. **Scans** the `.prt` file for `ESC(<id>X` font-selection commands to find which fonts are used.

2. **Prepends** the matching `.HPP` font data with `ESC*c<id>D` assignment commands, making the stream *self-contained*.

3. **Deduplicates** T3's shadow-bold overprints (see below).

4. **Pipes** the assembled stream through `gpcl6 -sDEVICE=pdfwrite`.

### Swedish character encoding

T3's bitmap fonts place Swedish characters at code positions 160–192. Standard HP PCL fonts use ISO-8859-1 at those positions. By embedding the T3 bitmap fonts, the script ensures the correct glyphs appear at each code point.

### Shadow-bold deduplication

T3 has no separate bold font. Instead it prints each "bold" character 2–9 times at slightly different horizontal positions (offsets of 1–16 PCL units, ≈0.003–0.05 inch at 300 DPI). On a real laser printer, the ink bleeds slightly and the overprints merge into visibly thicker strokes. In PDF, each print is a separate independent glyph, producing a shadow/double effect.

The deduplicator detects runs of the same character printed within 18 PCL units of each other and keeps only the last (rightmost) copy. The resulting PDF text is single-weight (lighter than the original printed bold) but clean and fully selectable.

Observed T3 overprint counts by font:
| Font | Purpose | Overprints |
|------|---------|------------|
| IBM17SV | 17pt titles | 9× |
| IBM12 | 12pt body bold | 2–3× |
| KU | Italic/kursiv | 3× |

## Font table

The following T3 font IDs (from `FONTNASV.TBL`) are supported:

| ID | HPP file | Description |
|----|----------|-------------|
| 2 | BUILT12F.HPP | Built Up Elite |
| 3 | CHEM12F.HPP | Chemistry |
| 5 | CYRIL12.HPP | Cyrillic |
| 6 | FRAK12.HPP | Fraktur |
| 7 | GREEK12.HPP | Greek |
| 8 | IBM10.HPP | IBM 10pt |
| 9 | IBM10F.HPP | IBM 10pt Fixed |
| 10 | IBM12.HPP | IBM 12pt (main body) |
| 13 | IBM12SL.HPP | IBM 12pt Slant |
| 14 | IBM12SS.HPP | IBM 12pt Sans Serif |
| 15 | IBM12TT.HPP | IBM 12pt Typewriter |
| 19 | IBMU12F.HPP | IBMUpper Elite |
| 21 | IBMU12SL.HPP | IBMUpper Slant |
| 22 | IBMU12.HPP | IBMUpper 12pt |
| 23 | IBMU17SL.HPP | IBMUpper 17pt Slant |
| 24 | IBMU17.HPP | IBMUpper 17pt |
| 25 | ITAL10.HPP | Italics 10pt |
| 26 | ITAL12.HPP | Italics 12pt |
| 31 | LTAC12SL.HPP | Latin Accents Slant |
| 32 | LTAC12.HPP | Latin Accents |
| 33 | LTAC17SL.HPP | Latin Accents 17pt Slant |
| 34 | LTAC17.HPP | Latin Accents 17pt |
| 35 | S112F.HPP | S1 math symbols |
| 37 | SCRIPT12.HPP | Script |
| 38 | SMALL12.HPP | Small caps |
| 39 | SYM12F.HPP | Symbol |
| 41 | FRAKSV.HPP | Fraktur Swedish |
| 42 | IB17SNSV.HPP | IBM 17pt Slant Swedish |
| 43 | IB17SSSV.HPP | IBM 17pt SS Swedish |
| 44 | IBM10FSV.HPP | IBM 10pt Fixed Swedish |
| 45 | IBM10SV.HPP | IBM 10pt Swedish |
| 46 | IBM17SV.HPP | IBM 17pt Swedish (titles) |
| 47 | IBMELSV.HPP | IBM Elite Swedish |
| 49 | IBMSKRM.HPP | IBM Typewriter Swedish |
| 50 | IBMSNESV.HPP | IBM Slant Swedish |
| 51 | IBMSSSV.HPP | IBM SS Swedish |
| 52 | IBMSV.HPP | IBM 12pt Swedish |
| 53 | KU.HPP | Kursiv (italic) Swedish |
| 54 | KU10.HPP | Kursiv 10pt |
| 55 | KUEL.HPP | Kursiv Elite |
| 57 | SKRIV.HPP | Skrivstil (handwriting) |
| 58 | SMAA.HPP | Smaa (small) |

## Known limitations

- **Bold weight**: After deduplication, bold/title text is rendered at normal (single-print) weight, which is lighter than the original printed output. This is inherent to the text-selectable PDF format — merging the overprints would require rasterisation, which makes text non-selectable.
- **Landscape fonts**: The `.HPL` landscape font files are not yet handled; landscape pages will use fallback fonts.
- **Non-Swedish T3 variants**: This font table covers the Swedish extended character set (`FONTNASV.TBL`). A base T3 installation uses a subset of these IDs.
- **Not really copy-paste ready**: Attempts to copy text from the PDF printout yields strings with spaces between words and other artefacts.

## Files

```
t3pcl2pdf/
└── t3pcl2pdf.py    Main conversion script
└── README.md       This file
```

## License

Public domain. 
