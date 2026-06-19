#!/usr/bin/env fontforge
import fontforge
import psMat
from pathlib import Path

base = Path('/home/user/QubesIncoming/dom0/.config/polybar/kuhbs/assets/fonts')
svg = str(base / 'kuhbs-logo.svg')
out = str(base / 'kuhbs-icons.ttf')

font = fontforge.font()
font.fontname = 'KuhbsIcons'
font.familyname = 'Kuhbs Icons'
font.fullname = 'Kuhbs Icons Regular'
font.encoding = 'UnicodeFull'
font.em = 1000
font.ascent = 800
font.descent = 200

g = font.createChar(0xE000, 'kuhbs-logo')
g.importOutlines(svg)
g.correctDirection()
g.removeOverlap()

xmin, ymin, xmax, ymax = g.boundingBox()
w = xmax - xmin
h = ymax - ymin
if w <= 0 or h <= 0:
    raise SystemExit('empty glyph after import')

scale = min(880 / w, 760 / h)
g.transform(psMat.translate(-xmin, -ymin))
g.transform(psMat.scale(scale))
xmin, ymin, xmax, ymax = g.boundingBox()
w = xmax - xmin
h = ymax - ymin
# center horizontally in 1000 advance width; put bottom at y=40 for visual centering in polybar
g.transform(psMat.translate((1000 - w) / 2 - xmin, 40 - ymin))
g.width = 1000

g.round()
g.simplify()
g.removeOverlap()
font.generate(out)
print(out)
