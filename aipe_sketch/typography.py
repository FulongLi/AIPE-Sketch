"""Apply the drawing agent's typography policy to emitted SVG files."""
import re

from . import config


_FONT_FAMILY = re.compile(r'(?<!-)font-family\s*:\s*[^;]+')
_FONT_WEIGHT = re.compile(r'font-weight\s*:\s*[^;]+')
_INKSCAPE_FONT = re.compile(r'-inkscape-font-specification\s*:\s*[^;]+')
_TEXT_TAGS = frozenset({'text', 'tspan', 'textPath'})


def _local_name(tag):
    return tag.rsplit('}', 1)[-1] if isinstance(tag, str) else ''


def style_with_project_font(style=''):
    """Return *style* with the project-wide font family and weight."""
    family = f'font-family:{config.FONT_FAMILY_CSS}'
    weight = f'font-weight:{config.FONT_WEIGHT}'
    if _FONT_FAMILY.search(style):
        style = _FONT_FAMILY.sub(family, style)
    else:
        style = f'{style.rstrip(";")};{family}' if style else family
    if _FONT_WEIGHT.search(style):
        style = _FONT_WEIGHT.sub(weight, style)
    else:
        style = f'{style.rstrip(";")};{weight}'
    if _INKSCAPE_FONT.search(style):
        style = _INKSCAPE_FONT.sub(
            f"-inkscape-font-specification:'{config.FONT_FAMILY}'", style)
    return style


def apply_svg_font(root):
    """Enforce the project font on text and copied inherited declarations."""
    for element in root.iter():
        style = element.get('style', '')
        is_text = _local_name(element.tag) in _TEXT_TAGS
        if is_text or 'font-family' in style:
            element.set('style', style_with_project_font(style))
        if 'font-family' in element.attrib:
            element.set('font-family', config.FONT_FAMILY)
        if is_text and 'font-weight' in element.attrib:
            element.set('font-weight', str(config.FONT_WEIGHT))
    return root
