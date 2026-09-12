"""Extract <symbol> defs from the Inkscape electric-symbols sheet into a reusable library."""
import xml.etree.ElementTree as ET, re, copy, math

SVG = 'http://www.w3.org/2000/svg'
NS = '{%s}' % SVG
ET.register_namespace('', SVG)
ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')

GRID = 1.3229167          # fine grid, mm (5 px @96dpi)
COARSE = 2.6458333        # coarse grid, mm (10 px)

_tok = re.compile(r'[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?')

def path_points(d):
    toks = _tok.findall(d); pts=[]; i=0; cur=[0.0,0.0]; start=[0.0,0.0]; cmd=None
    def f():
        nonlocal i
        v=float(toks[i]); i+=1; return v
    while i < len(toks):
        if re.match(r'[A-Za-z]', toks[i]):
            cmd = toks[i]; i += 1
        if cmd in ('Z','z'):
            pts.append(tuple(start)); cur=list(start); cmd=None
            if i>=len(toks): break
            continue
        if i>=len(toks): break
        if   cmd=='M': cur=[f(),f()]; start=list(cur); pts.append(tuple(cur)); cmd='L'
        elif cmd=='m': cur=[cur[0]+f(),cur[1]+f()]; start=list(cur); pts.append(tuple(cur)); cmd='l'
        elif cmd=='L': cur=[f(),f()]; pts.append(tuple(cur))
        elif cmd=='l': cur=[cur[0]+f(),cur[1]+f()]; pts.append(tuple(cur))
        elif cmd=='H': cur=[f(),cur[1]]; pts.append(tuple(cur))
        elif cmd=='h': cur=[cur[0]+f(),cur[1]]; pts.append(tuple(cur))
        elif cmd=='V': cur=[cur[0],f()]; pts.append(tuple(cur))
        elif cmd=='v': cur=[cur[0],cur[1]+f()]; pts.append(tuple(cur))
        elif cmd in 'Cc':
            p=[f() for _ in range(6)]
            cur=[p[4],p[5]] if cmd=='C' else [cur[0]+p[4],cur[1]+p[5]]
            pts.append(tuple(cur))
        elif cmd in 'Ss':
            p=[f() for _ in range(4)]
            cur=[p[2],p[3]] if cmd=='S' else [cur[0]+p[2],cur[1]+p[3]]
            pts.append(tuple(cur))
        elif cmd in 'Aa':
            p=[f() for _ in range(7)]
            cur=[p[5],p[6]] if cmd=='A' else [cur[0]+p[5],cur[1]+p[6]]
            pts.append(tuple(cur))
        else:
            i += 1
    return pts


class Symbol:
    def __init__(self, el):
        self.id = el.get('id')
        ti = el.find(NS+'title')
        self.name = (''.join(ti.itertext()).strip() if ti is not None else '') or self.id
        self.el = el
        self._geom()

    def _geom(self):
        xs=[]; ys=[]; ends={}
        for e in self.el.iter():
            tag = e.tag.replace(NS,'')
            if tag=='path' and e.get('d'):
                p = path_points(e.get('d'))
                for q in p: xs.append(q[0]); ys.append(q[1])
                if p:
                    for q in (p[0], p[-1]):
                        k=(round(q[0],3), round(q[1],3)); ends[k]=ends.get(k,0)+1
            elif tag in ('circle','ellipse'):
                cx=float(e.get('cx',0)); cy=float(e.get('cy',0))
                rx=float(e.get('r') or e.get('rx') or 0); ry=float(e.get('r') or e.get('ry') or 0)
                xs += [cx-rx, cx+rx]; ys += [cy-ry, cy+ry]
            elif tag=='rect':
                x=float(e.get('x',0)); y=float(e.get('y',0))
                xs += [x, x+float(e.get('width',0))]; ys += [y, y+float(e.get('height',0))]
        self.bbox = (min(xs), min(ys), max(xs), max(ys)) if xs else (0,0,0,0)
        self.free_ends = sorted(k for k,v in ends.items() if v==1)

    @property
    def center(self):
        x0,y0,x1,y1 = self.bbox
        return ((x0+x1)/2.0, (y0+y1)/2.0)

    def body(self, keep=None):
        """Children without <title>, deep-copied.

        ``keep`` names the child ids to retain, which is how a wrapper that
        also encloses neighbouring geometry is reduced to just its device.
        """
        out = []
        for c in self.el:
            if c.tag == NS + 'title':
                continue
            if keep is not None and c.get('id') not in keep:
                continue
            out.append(copy.deepcopy(c))
        return out


def load(path):
    root = ET.parse(path).getroot()
    syms = {}
    for el in root.iter(NS+'symbol'):
        s = Symbol(el)
        syms[s.id] = s
    return root, syms
