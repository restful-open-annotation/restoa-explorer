#!/usr/bin/env python

"""Convert text and (start, end type) annotations into HTML."""

__author__ = 'Sampo Pyysalo'
__license__ = 'MIT'

import sys
import json
import re
import unicodedata

from collections import namedtuple
from itertools import chain

# the tag to use to mark annotated spans
TAG='span'

# vertical space between span boxes at different heights in pixels
# (including border)
VSPACE = 2

# text line height w/o annotations
BASE_LINE_HEIGHT = 24

# span type to HTML tag mapping for formatting spans.
FORMATTING_TYPE_TAG_MAP = {
    'bold': 'b',
    'italic': 'i',
    'sup': 'sup',
    'sub': 'sub',
    'section': 'section'
}

# "effectively zero" height for formatting tags
EPSILON = 0.0001

class Span(object):
    """Represents a marked span of text.

    Spans can represent either annotations or formatting. The former
    are rendered as text highligts, the latter as HTML formatting tags
    such as <i> and <p>.
    """
    def __init__(self, start, end, type_, formatting=None):
        """Initialize annotation or formatting span.

        If formatting is None, determine whether or not this is a
        formatting tag heuristically based on type_.
        """
        self.start = start
        self.end = end
        self.type = type_
        if formatting is not None:
            self.formatting = formatting
        else:
            self.formatting = type_ in FORMATTING_TYPE_TAG_MAP

        self.nested = set()
        self._height = None

        self.start_marker = None

    def tag(self):
        """Return HTML tag to use to render this marker."""
        # Non-formatting tags render into the general tag form
        # specified by the global config, formatting tags into HTML
        # tags according to a custom mapping.
        if not self.formatting:
            return TAG
        else:
            # TODO: very special case hack put in place to guess at
            # which CRAFT sections are headings. Remove ASAP.
            if self.type == 'section' and self.end - self.start < 100:
                if self.start < 10:
                    return 'h2'
                else:
                    return 'h3'
            return FORMATTING_TYPE_TAG_MAP.get(self.type, self.type)

    def sort_height(self):
        """Relative height of this tag for sorting purposes."""
        # Formatting tags have effectively zero height, i.e. they
        # should not affect the height of tags that wrap them. TODO:
        # this still leaves a height+1 effect when a formatting tag is
        # the only one nested by a regular one; fix this.
        # A very small value, EPSILON, is used as the height of
        # formatting tags to give correct sort order.
        own_height = 1 if not self.formatting else EPSILON
        if self._height is None:
            self._height = 0 if not self.nested else \
                max([n.height() for n in self.nested]) + own_height
        return self._height

    def height(self):
        """Relative height of this tag (except for sorting)."""
        # Simply eliminate the "virtual" EPSILON heights.
        return int(self.sort_height())

class Marker(object):
    def __init__(self, span, offset, is_end, cont_left=False, 
                 cont_right=False):
        self.span = span
        self.offset = offset
        self.is_end = is_end
        self.cont_left = cont_left
        self.cont_right = cont_right

        self.covered_left = False
        self.covered_right = False

        # at identical offsets, ending markers sort highest-last,
        # starting markers highest-first.
        self.sort_idx = self.span.sort_height() * (1 if self.is_end else -1)

        # store current start marker in span to allow ending markers
        # to affect tag style
        if not is_end:
            self.span.start_marker = self

    def __unicode__(self):
        if self.is_end:
            return u'</%s>' % self.span.tag()
        elif self.span.formatting:
            # Formatting tags take no style
            return u'<%s>' % self.span.tag()
        else:
            # TODO: this will produce redundant class combinations in
            # cases (e.g. "continueleft openleft")
            return u'<%s class="ann ann-h%d ann-t%s%s%s%s%s">' % \
                (self.span.tag(), self.span.height(), self.span.type,
                 u' ann-contleft' if self.cont_left else '',
                 u' ann-contright' if self.cont_right else '',
                 u' ann-openleft' if self.covered_left else '',
                 u' ann-openright' if self.covered_right else '')

def marker_sort(a, b):
    return cmp(a.offset, b.offset) or cmp(a.sort_idx, b.sort_idx)

def leftmost_sort(a, b):
    c = cmp(a.start, b.start)
    return c if c else cmp(b.end-b.start, a.end-a.start)    

def longest_sort(a, b):
    c = cmp(b.end-b.start, a.end-a.start)
    return c if c else cmp(a.start, b.start)

def resolve_heights(spans):
    # algorithm for determining visualized span height:

    # 1) define strict total order of spans (i.e. for each pair of
    # spans a, b, either a < b or b < a, with standard properties for
    # "<")

    # 2) traverse spans leftmost-first, keeping list of open spans,
    # and for each span, sort open spans in defined order and add
    # later spans to "nested" collections of each earlier span (NOTE:
    # this step is simple, but highly sub-optimal)

    # 3) resolve height as 0 for spans with no nested spans and
    # max(height(n)+1) for n in nested for others.

    open_span = []
    for s in sorted(spans, leftmost_sort):
        open_span = [o for o in open_span if o.end > s.start]
        open_span.append(s)
        # TODO: use a sorted container instead.
        open_span.sort(longest_sort)

        # WARNING: O(n^3) worst case!
        # TODO: I think that only spans just before and just after the
        # inserted span can have meaningful changes in their "nested"
        # collections. Ignore others.
        for i in range(len(open_span)):
            for j in range(i+1, len(open_span)):
                open_span[i].nested.add(open_span[j])

    return max(s.height() for s in spans) if spans else -1

LEGEND_CSS=""".legend {
  float:right;
  margin-left: 10px;
  border: 1px solid gray;
  font-size: 90%;
  background-color: #eee;
  padding: 10px;
  border-radius:         6px;
  -moz-border-radius:    6px;
  -webkit-border-radius: 6px;
  box-shadow: 0 5px 10px         rgba(0, 0, 0, 0.2);
  -moz-box-shadow: 0 5px 10px    rgba(0, 0, 0, 0.2);
  -webkit-box-shadow: 0 5px 10px rgba(0, 0, 0, 0.2);
  line-height: normal;
  font-family: sans-serif;
}
.legend span {
  display: block;
  padding: 2px;
  margin: 2px;
}
.clearfix { /* from bootstrap, to avoid legend overflow */
  *zoom: 1;
}
.clearfix:before,
.clearfix:after {
  display: table;
  line-height: 0;
  content: "";
}
.clearfix:after {
  clear: both;
}"""

BASE_CSS=""".ann {
  border: 1px solid gray;
  background-color: lightgray;
  border-radius:         3px;
  -moz-border-radius:    3px;
  -webkit-border-radius: 3px;
}
.ann-openright {
  border-right: none;
}
.ann-openleft {
  border-left: none;
}
.ann-contright {
  border-right: none;
  border-top-right-radius: 0;
  border-bottom-right-radius: 0;
}
.ann-contleft {
  border-left: none;
  border-top-left-radius: 0;
  border-bottom-left-radius: 0;
}"""

def line_height_css(height):
    if height == 0:
        return ''
    else:
        return 'line-height: %dpx;\n' % (BASE_LINE_HEIGHT+2*height*VSPACE)

def generate_css(max_height, color_map, legend):
    css = [LEGEND_CSS] if legend else []
    css.append(BASE_CSS)
    for i in range(max_height+1):
        css.append(""".ann-h%d {
  padding-top: %dpx;
  padding-bottom: %dpx;
  %s
}""" % (i, i*VSPACE, i*VSPACE, line_height_css(i)))
    for t,c in color_map.items():
        css.append(""".ann-t%s {
  background-color: %s;
  border-color: %s;
}""" % (t, c, darker_color(c)))
    return '\n'.join(css)

def uniq(s):
    """Return unique items in given sequence, preserving order."""
    # http://stackoverflow.com/a/480227
    seen = set()
    return [ i for i in s if i not in seen and not seen.add(i)]

def generate_legend(types, colors):
    parts = ['''<div class="legend">Legend<table>''']
    for f, c in zip(types, colors):
        t = css_class_string(f)
        tagl, tagr = '<%s class="ann ann-t%s">' % (TAG, t), '</%s>' % TAG
        parts.append('<tr><td>%s%s%s</td></tr>' % (tagl, f, tagr))
    parts.append('</table></div>')
    return ''.join(parts)

def _standoff_to_html(text, standoffs, legend):
    """standoff_to_html() implementation, don't invoke directly."""

    # Convert standoffs to spans and generate mapping from types to
    # colors. As type strings will be used as part of CSS class names,
    # normalize at this point.
    spans = [Span(so.start, so.end, css_class_string(so.type)) 
             for so in standoffs]

    types = uniq(s.type for s in spans if not s.formatting)
    colors = span_colors(types)
    color_map = dict(zip(types, colors))

    # generate legend if requested
    full_forms = uniq(so.type for so in standoffs)
    type_to_full_form = { css_class_string(f) : f for f in full_forms }
    legend_types = [ type_to_full_form[t] for t in types ]
    legend_html = generate_legend(legend_types, colors) if legend else ''

    # resolve height of each span by determining span nesting
    max_height = resolve_heights(spans)

    # Generate CSS as combination of boilerplate and height-specific
    # styles up to the required maximum height.
    css = generate_css(max_height, color_map, legend)

    # Decompose into separate start and end markers for conversion
    # into tags.
    markers = []
    for s in spans:
        markers.append(Marker(s, s.start, False))
        markers.append(Marker(s, s.end, True))
    markers.sort(marker_sort)
    
    # process markers to generate additional start and end markers for
    # instances where naively generated spans would cross.
    i, o, out = 0, 0, []
    open_span = set()
    while i < len(markers):        
        if o != markers[i].offset:
            out.append(text[o:markers[i].offset])
        o = markers[i].offset
        
        # collect markers opening or closing at this position and
        # determine max opening/closing marker height
        to_open, to_close = [], []
        max_change_height = -1
        last = None
        for j in range(i, len(markers)):
            if markers[j].offset != o:
                break
            if markers[j].is_end:
                to_close.append(markers[j])
            else:
                to_open.append(markers[j])
            max_change_height = max(max_change_height, markers[j].span.height())
            last = j

        # open spans of height < max_change_height must close to avoid
        # crossing tags; add also to spans to open to re-open and
        # make note of lowest "covered" depth.
        min_cover_height = float('inf') # TODO
        for s in open_span:
            if s.height() < max_change_height and s.end != o:
                s.start_marker.cont_right = True
                to_open.append(Marker(s, o, False, True))
                to_close.append(Marker(s, o, True))
                min_cover_height = min(min_cover_height, s.height())

        # mark any tags behind covering ones so that they will be
        # drawn without the crossing border
        for m in to_open:
            if m.span.height() > min_cover_height:
                m.covered_left = True
        for m in to_close:
            if m.span.height() > min_cover_height:
                m.span.start_marker.covered_right = True

        # reorder (note: might be unnecessary in cases; in particular,
        # close tags will typically be identical, so only their number
        # matters)
        to_open.sort(marker_sort)
        to_close.sort(marker_sort)

        # add tags to stream
        for m in to_close:
            out.append(m)
            open_span.remove(m.span)
        for m in to_open:
            out.append(m)
            open_span.add(m.span)
                
        i = last+1
    out.append(text[o:])

    if legend_html:
        out = [legend_html] + out

    return css, u''.join(unicode(o) for o in out)    

header_pre_css = """<!DOCTYPE html>
<html>
<head>
<style type="text/css">
"""

style_css = """html {
  background-color: #eee; 
  font-family: sans;
}
body { 
  background-color: #fff; 
  border: 1px solid #ddd;
  padding: 15px; margin: 15px;
  line-height: %dpx
}
section {
  padding: 15px;
}
""" % BASE_LINE_HEIGHT

header_post_css = """
</style>
</head>
<body class="clearfix">"""

trailer = """</body>
</html>"""

def darker_color(c, amount=0.3):
    """Given HTML-style #RRGGBB color string, return variant that is
    darker by the given amount."""

    import colorsys

    if c and c[0] == '#':
        c = c[1:]
    if len(c) != 6:
        raise ValueError
    r, g, b = map(lambda h: int(h, 16)/255., [c[0:2],c[2:4],c[4:6]])
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    v *= 1.0-amount
    r, g, b = [255*x for x in colorsys.hsv_to_rgb(h, s, v)]
    return '#%02x%02x%02x' % (r, g, b)

def random_colors(n, seed=None):
    import random
    import colorsys
    
    random.seed(seed)
    
    # based on http://stackoverflow.com/a/470747
    colors = []
    for i in range(n):
        hsv = (1.*i/n, 0.9 + random.random()/10, 0.9 + random.random()/10)
        rgb = tuple(255*x for x in colorsys.hsv_to_rgb(*hsv))
        colors.append('#%02x%02x%02x' % rgb)
    return colors

# Kelly's high-contrast colors [K Kelly, Color Eng., 3 (6) (1965)],
# via http://stackoverflow.com/a/4382138. Changes: black excluded as
# not applicable here, plus some reordering (numbers in comments give
# original order).
kelly_colors = [
#     '#000000', #  2 black
    '#FFB300', #  3 yellow
    '#007D34', # 10 green
    '#FF6800', #  5 orange
    '#A6BDD7', #  6 light blue
    '#C10020', #  7 red
    '#CEA262', #  8 buff
    '#817066', #  9 gray
#     '#FFFFFF', #  1 white
    '#803E75', #  4 purple
    '#F6768E', # 11 purplish pink
    '#00538A', # 12 blue
    '#FF7A5C', # 13 yellowish pink
    '#53377A', # 14 violet
    '#FF8E00', # 15 orange yellow
    '#B32851', # 16 purplish red
    '#F4C800', # 17 greenish yellow
    '#7F180D', # 18 reddish brown
    '#93AA00', # 19 yellow green
    '#593315', # 20 yellowish brown
    '#F13A13', # 21 reddish orange
    '#232C16', # 22 olive green
]

# Pre-set colors
type_color_map = {
    'Organism_subdivision':    '#ddaaaa',
    'Anatomical_system':       '#ee99cc',
    'Organ':                   '#ff95ee',
    'Multi-tissue_structure':  '#e999ff',
    'Tissue':                  '#cf9fff',
    'Developing_anatomical_structure': '#ff9fff',
    'Cell':                    '#cf9fff',
    'Cellular_component':      '#bbc3ff',
    'Organism_substance':      '#ffeee0',
    'Immaterial_anatomical_entity':    '#fff9f9',
    'Pathological_formation':  '#aaaaaa',
    'Cancer':  '#999999',
}

def span_colors(types):
    missing = [t for t in types if t not in type_color_map]
    if len(missing) <= len(kelly_colors):
        fill = kelly_colors[:len(missing)]
    else:
        fill = random_colors(len(missing), 1)
    colors = []
    i = 0
    for t in types:
        if t in type_color_map:
            colors.append(type_color_map[t])
        else:
            colors.append(fill[i])
            i += 1
    return colors

def css_class_string(s, encoding='utf-8'):
    """Given a non-empty string, return a variant that can be used as
    a CSS class name."""

    if not s or s.isspace():
        raise ValueError

    if isinstance(s, unicode):
        c = s
    else:
        c = s.decode(encoding)

    # adapted from http://stackoverflow.com/q/5574042
    c = unicodedata.normalize('NFKD', c).encode('ascii', 'ignore')
    c = re.sub(r'[^_a-zA-Z0-9-]', '-', c)
    c = re.sub(r'--+', '-', c)
    c = c.strip('-')

    if c and c[0].isdigit():
        c = '_' + c
    
    # Sanity check from http://stackoverflow.com/a/449000, see also
    # http://www.w3.org/TR/CSS21/grammar.html#scanner
    assert re.match(r'^-?[_a-zA-Z]+[_a-zA-Z0-9-]*', c), 'Internal error: %s' % s

    return c

def json_to_standoffs(j):
    try:
        spans = json.loads(j)
    except ValueError, e:
        print >> sys.stderr, 'json.loads failed for "%s": %s' % (j, e)
        raise

    MyStandoff = namedtuple('MyStandoff', 'start end type')

    # if any span is missing a type specification, assign a
    # simple numeric new one without repeating.

    missing_count = len([s for s in spans if len(s) < 3])

    standoffs, i = [], 0
    for s in spans:
        if len(s) < 1:
            continue # ignore empties
        if len(s) < 2:
            s = [s[0], s[0]] # map singletons to zero-width
        if len(s) < 3:
            s = [s[0], s[1], 'type-%d' % (i+1)]
            i += 1
        standoffs.append(MyStandoff(*s))

    return standoffs

def standoff_to_html(text, standoffs, legend=True):
    """Create HTML representation of given text and standoff
    annotations.
    """

    css, body = _standoff_to_html(text, standoffs, legend)
    return header_pre_css + style_css + css + header_post_css + body + trailer

def main(argv=None):
    if argv is None:
        argv = sys.argv

    if len(argv) == 4 and argv[1] == '-n':
        argv = argv[:1] + argv[2:]
        legend = False
    else:
        legend = True

    if len(argv) != 3:
        print >> sys.stderr, 'Usage:', argv[0], '[-n] TEXT SOJSON'
        print >> sys.stderr, '  e.g.', argv[0], '\'Bob, UK\' \'[[0,3,"Person"],[5,7,"GPE"]]\''
        return 1

    text = argv[1]
    standoffs = json_to_standoffs(argv[2])
    print standoff_to_html(text, standoffs, legend)

    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv))
