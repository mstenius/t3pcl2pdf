#!/usr/bin/env python3
"""
t3pcl2pdf.py - Convert T3 Scientific Word Processor PCL output to PDF.

T3 downloads its bitmap soft fonts to the HP LaserJet before each print job.
The .prt file contains only the document body, referencing those font IDs.
This script:
  1. Scans the .prt file for font-selection commands (ESC(<id>X).
  2. Prepends the matching .HPP soft-font data so the PCL stream is
     self-contained and gpcl6 can interpret it correctly.
  3. Removes T3's shadow-bold overprints (the same character printed 2-9
     times at sub-pixel offsets to simulate bold on paper) so the PDF does
     not show doubled/ghosted glyphs.
  4. Feeds the cleaned stream to gpcl6 to produce a searchable PDF.

Font-ID → .HPP mapping was derived from T3's LDPPELSV.BAT / LDPPROP.BAT /
LDPXPRSV.BAT batch files.

Usage:
  python3 t3pcl2pdf.py [options] input.prt [output.pdf]

Options:
  --hplj DIR        Path to T3 HPLJ font directory
                    (default: env T3_HPLJ_DIR, or auto-detect from common paths)
  --pcl-fonts DIR   Path to Ghostscript PCL URW fonts
                    (default: env PCLFONTSOURCE, or /opt/homebrew/share/ghostscript/pcl-fonts)
  --paper SIZE      Paper size: a4 or letter (default: a4)
  --no-dedup        Disable shadow-bold deduplication
  --help            Show this help message
"""

import os
import subprocess
import sys
import tempfile

# ---------------------------------------------------------------------------
# Font-ID → HPP filename table (portrait orientation, Swedish extended set)
# Derived from T3's LDPPELSV.BAT, LDPPROP.BAT, and LDPXPRSV.BAT.
# ---------------------------------------------------------------------------
FONT_TABLE = {
    2:  'BUILT12F.HPP',   # Built Up Elite
    3:  'CHEM12F.HPP',    # Chemistry Elite
    5:  'CYRIL12.HPP',    # Cyrillic Proportional
    6:  'FRAK12.HPP',     # Fraktur Proportional
    7:  'GREEK12.HPP',    # Greek Proportional
    8:  'IBM10.HPP',      # IBM 10pt Proportional
    9:  'IBM10F.HPP',     # IBM 10pt Fixed
    10: 'IBM12.HPP',      # IBM 12pt Proportional  (main body font)
    13: 'IBM12SL.HPP',    # IBM 12pt Slant
    14: 'IBM12SS.HPP',    # IBM 12pt Sans Serif
    15: 'IBM12TT.HPP',    # IBM 12pt Typewriter
    19: 'IBMU12F.HPP',    # IBMUpper Elite
    21: 'IBMU12SL.HPP',   # IBMUpper Slant
    22: 'IBMU12.HPP',     # IBMUpper 12pt  (superscripts, special chars)
    23: 'IBMU17SL.HPP',   # IBMUpper 17pt Slant
    24: 'IBMU17.HPP',     # IBMUpper 17pt
    25: 'ITAL10.HPP',     # Italics 10pt
    26: 'ITAL12.HPP',     # Italics 12pt
    31: 'LTAC12SL.HPP',   # Latin Accents Slant
    32: 'LTAC12.HPP',     # Latin Accents
    33: 'LTAC17SL.HPP',   # Latin Accents 17pt Slant
    34: 'LTAC17.HPP',     # Latin Accents 17pt
    35: 'S112F.HPP',      # S1 math symbols
    37: 'SCRIPT12.HPP',   # Script
    38: 'SMALL12.HPP',    # Small caps
    39: 'SYM12F.HPP',     # Symbol
    41: 'FRAKSV.HPP',     # Fraktur Swedish
    42: 'IB17SNSV.HPP',   # IBM 17pt Slant Swedish
    43: 'IB17SSSV.HPP',   # IBM 17pt SS Swedish
    44: 'IBM10FSV.HPP',   # IBM 10pt Fixed Swedish
    45: 'IBM10SV.HPP',    # IBM 10pt Swedish
    46: 'IBM17SV.HPP',    # IBM 17pt Swedish  (large title font)
    47: 'IBMELSV.HPP',    # IBM Elite Swedish
    49: 'IBMSKRM.HPP',    # IBM Skrivmaskin (typewriter)
    50: 'IBMSNESV.HPP',   # IBM Slant Swedish
    51: 'IBMSSSV.HPP',    # IBM SS Swedish
    52: 'IBMSV.HPP',      # IBM 12pt Swedish
    53: 'KU.HPP',         # Kursiv (italic) Swedish
    54: 'KU10.HPP',       # Kursiv 10pt
    55: 'KUEL.HPP',       # Kursiv Elite
    57: 'SKRIV.HPP',      # Skrivstil (handwriting)
    58: 'SMAA.HPP',       # Smaa (small)
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_hplj(hint: str | None) -> str:
    if hint:
        return hint
    env = os.environ.get('T3_HPLJ_DIR')
    if env:
        return env
    candidates = [
        os.path.expanduser('~/dos/drive-c/T3/HPLJ'),
        os.path.expanduser('~/drive-c/T3/HPLJ'),
        '/dos/drive-c/T3/HPLJ',
    ]
    for p in candidates:
        if os.path.isdir(p):
            return p
    return ''


def find_pcl_fonts(hint: str | None) -> str:
    if hint:
        return hint
    env = os.environ.get('PCLFONTSOURCE')
    if env:
        return env
    default = '/opt/homebrew/share/ghostscript/pcl-fonts'
    return default


def find_font_ids(data: bytes) -> list[int]:
    """Return sorted list of font IDs referenced by ESC(<id>X commands."""
    ids = set()
    i = 0
    while i < len(data) - 3:
        if data[i] == 0x1b and data[i + 1] == 0x28:
            j = i + 2
            digits = b''
            while j < len(data) and 0x30 <= data[j] <= 0x39:
                digits += bytes([data[j]])
                j += 1
            if j < len(data) and data[j] == 0x58 and digits:
                ids.add(int(digits))
            i = j
        else:
            i += 1
    return sorted(ids)


def font_preamble(font_id: int, hpp_path: str) -> bytes:
    """Return ESC*c<id>D + font data (registers the font with PCL interpreter)."""
    font_data = open(hpp_path, 'rb').read()
    assign_cmd = f'\x1b*c{font_id}D'.encode()
    return assign_cmd + font_data


# ---------------------------------------------------------------------------
# Shadow-bold deduplication
# ---------------------------------------------------------------------------

def deduplicate_shadow_bold(doc: bytes, threshold: int = 18) -> bytes:
    """
    T3 implements bold/emphasis by printing the same character N times at
    slightly offset X positions (up to 16 PCL units apart, ~0.05 inch at
    300 DPI).  On paper the ink merges; in a PDF each print is independent,
    producing visible ghosting.

    This function keeps only the LAST (rightmost) occurrence of each such
    run, so the PDF contains a single clean copy of every character.
    Body text (already single-print) is unaffected.

    Observed overprint counts by font:
      IBM17SV (17pt titles)  : 9x overprint
      IBM12   (body bold)    : 2-3x overprint
      KU      (italic)       : 3x overprint
    """
    # Tokenise the PCL stream
    tokens = []
    i = 0
    while i < len(doc):
        b = doc[i]
        if b != 0x1b:
            while i < len(doc) and doc[i] != 0x1b and doc[i] not in (0x0a, 0x0d, 0x0c):
                tokens.append(('char', doc[i], bytes([doc[i]])))
                i += 1
            if i < len(doc) and doc[i] in (0x0a, 0x0d, 0x0c):
                tokens.append(('raw', bytes([doc[i]])))
                i += 1
            continue

        start = i
        i += 1
        if i >= len(doc):
            tokens.append(('raw', doc[start:i]))
            break

        g = doc[i]
        i += 1

        if g in (ord('('), ord(')')):
            val = b''
            while i < len(doc) and chr(doc[i]).isdigit():
                val += bytes([doc[i]]); i += 1
            cmd = bytes([doc[i]]) if i < len(doc) else b''
            i += 1 if i < len(doc) else 0
            raw = bytes([0x1b, g]) + val + cmd
            if cmd == b'X':
                tokens.append(('font', int(val) if val else 0, raw))
            else:
                tokens.append(('raw', raw))
            continue

        if g in (ord('*'), ord('&')):
            sub = doc[i] if i < len(doc) else 0
            i += 1
            val = b''
            while i < len(doc) and (chr(doc[i]).isdigit() or doc[i] == ord('.')):
                val += bytes([doc[i]]); i += 1
            cmd = bytes([doc[i]]) if i < len(doc) else b''
            i += 1 if i < len(doc) else 0
            raw = bytes([0x1b, g, sub]) + val + cmd
            if g == ord('*') and sub == ord('p') and cmd == b'X':
                tokens.append(('move_x', int(val) if val else 0, raw))
            else:
                tokens.append(('raw', raw))
            continue

        tokens.append(('raw', doc[start:i]))

    # Deduplicate
    out = []
    cur_x = None

    j = 0
    while j < len(tokens):
        tok = tokens[j]
        kind = tok[0]

        if kind == 'move_x':
            cur_x = tok[1]
            out.append(tok[2])
            j += 1

        elif kind in ('font', 'raw'):
            out.append(tok[2] if len(tok) > 2 else tok[1])
            j += 1

        elif kind == 'char':
            ch = tok[1]
            first_x = cur_x
            pending = [(j, cur_x, tok[2])]
            k = j + 1
            lookahead_x = cur_x

            while k < len(tokens):
                t2 = tokens[k]
                if t2[0] == 'move_x':
                    lookahead_x = t2[1]
                    k += 1
                elif t2[0] == 'font':
                    k += 1
                elif t2[0] == 'char' and t2[1] == ch:
                    if (lookahead_x is not None and first_x is not None
                            and 0 <= (lookahead_x - first_x) <= threshold):
                        pending.append((k, lookahead_x, t2[2]))
                        k += 1
                    else:
                        break
                else:
                    break

            if len(pending) == 1:
                out.append(tok[2])
                j += 1
            else:
                last_x, last_raw = pending[-1][1], pending[-1][2]
                if last_x is not None and last_x != cur_x:
                    out.append(f'\x1b*p{last_x}X'.encode())
                out.append(last_raw)
                cur_x = last_x
                j = pending[-1][0] + 1

    return b''.join(out)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def build_pcl(prt_path: str, hplj: str, dedup: bool = True) -> bytes:
    """Assemble a self-contained PCL stream: font preambles + document body."""
    doc = open(prt_path, 'rb').read()
    ids = find_font_ids(doc)

    preamble = b''
    missing = []
    for fid in ids:
        hpp_name = FONT_TABLE.get(fid)
        if hpp_name is None:
            missing.append(fid)
            continue
        hpp_path = os.path.join(hplj, hpp_name)
        if not os.path.exists(hpp_path):
            missing.append(fid)
            print(f'  WARNING: {hpp_name} not found for font ID {fid}', file=sys.stderr)
            continue
        preamble += font_preamble(fid, hpp_path)

    if missing:
        print(f'  WARNING: no HPP mapping for font IDs {missing}', file=sys.stderr)

    body = deduplicate_shadow_bold(doc) if dedup else doc
    return preamble + body


def convert(prt_path: str, pdf_path: str, hplj: str, pcl_fonts: str,
            paper: str = 'a4', dedup: bool = True) -> None:
    pcl = build_pcl(prt_path, hplj, dedup)

    with tempfile.NamedTemporaryFile(suffix='.pcl', delete=False) as tmp:
        tmp.write(pcl)
        tmp_path = tmp.name

    try:
        env = os.environ.copy()
        env['PCLFONTSOURCE'] = pcl_fonts
        result = subprocess.run(
            ['gpcl6', '-dNOPAUSE', '-dBATCH',
             '-sDEVICE=pdfwrite', f'-sPAPERSIZE={paper}',
             f'-sOutputFile={pdf_path}', tmp_path],
            env=env, capture_output=True,
        )
        if result.returncode != 0:
            print(result.stderr.decode(errors='replace'), file=sys.stderr)
            sys.exit(result.returncode)
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> None:
    import argparse

    ap = argparse.ArgumentParser(
        description='Convert T3 Scientific Word Processor PCL output to PDF.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument('input', help='Input .prt file from T3/DOSBox')
    ap.add_argument('output', nargs='?', help='Output PDF (default: input.pdf)')
    ap.add_argument('--hplj', metavar='DIR',
                    help='Path to T3 HPLJ font directory '
                         '(env: T3_HPLJ_DIR)')
    ap.add_argument('--pcl-fonts', metavar='DIR',
                    help='Path to Ghostscript PCL URW fonts '
                         '(env: PCLFONTSOURCE)')
    ap.add_argument('--paper', default='a4', choices=['a4', 'letter'],
                    help='Paper size (default: a4)')
    ap.add_argument('--no-dedup', action='store_true',
                    help='Disable shadow-bold deduplication')

    args = ap.parse_args(argv)

    hplj = find_hplj(args.hplj)
    if not hplj or not os.path.isdir(hplj):
        print(
            'ERROR: T3 HPLJ font directory not found.\n'
            'Specify with --hplj DIR or set the T3_HPLJ_DIR environment variable.\n'
            'This is the HPLJ subdirectory of your T3 installation, e.g.:\n'
            '  ~/dos/drive-c/T3/HPLJ',
            file=sys.stderr,
        )
        sys.exit(1)

    pcl_fonts = find_pcl_fonts(args.pcl_fonts)

    prt = args.input
    pdf = args.output or (prt.rsplit('.', 1)[0] + '.pdf')
    dedup = not args.no_dedup

    ids = find_font_ids(open(prt, 'rb').read())
    print(f'Font IDs: {ids}')
    for fid in ids:
        print(f'  {fid:3d} → {FONT_TABLE.get(fid, "(unknown)")}')

    print(f'Converting {prt} → {pdf} (paper={args.paper}, dedup={dedup}) ...')
    convert(prt, pdf, hplj=hplj, pcl_fonts=pcl_fonts,
            paper=args.paper, dedup=dedup)
    size = os.path.getsize(pdf)
    print(f'Done: {pdf} ({size // 1024} KB)')


if __name__ == '__main__':
    main(sys.argv[1:])
