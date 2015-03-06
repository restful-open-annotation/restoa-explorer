#!/usr/bin/env python

"""RESTful Open Annotation explorer.

Open Annotation proxy with server-side visualization.
"""

__author__ = 'Sampo Pyysalo'
__license__ = 'MIT'

import sys
import json
import urlparse
import cgi

import flask
import requests

from collections import namedtuple
from collections import defaultdict

from webargs import Arg
from webargs.flaskparser import use_args

from so2html import standoff_to_html

try:
    from development import DEBUG
    print >> sys.stderr, '########## Devel, DEBUG %s ##########' % DEBUG
except ImportError:
    DEBUG = False

API_ROOT = '/explore'

app = flask.Flask(__name__)

Standoff = namedtuple('MyStandoff', 'start end type')

def pretty(doc):
    return json.dumps(doc, sort_keys=True, indent=2, separators=(',', ': '))

def group_by_document(annotations, target_key='target'):
    """Given a list of Open Annotation objects, return dict with target
    documents as keys and lists of their annotations as values."""
    groups = defaultdict(list)
    for annotation in annotations:
        target = annotation[target_key]
        document = urlparse.urldefrag(target)[0]
        groups[document].append(annotation)
    return groups    

def filter_by_document(annotations, doc, target_key='target'):
    """Given a list of Open Annotation object, return the subset that
    have the given document as their target."""
    filtered = []
    for annotation in annotations:
        target = annotation[target_key]
        document = urlparse.urldefrag(target)[0]
        if document == doc:
            filtered.append(annotation)
    return filtered

def annotations_to_standoffs(annotations, target_key='target'):
    """Convert OA annotations to (start, end, type) triples."""
    standoffs = []
    for annotation in annotations:
        target = annotation[target_key]
        fragment = urlparse.urldefrag(target)[1]
        start_end = fragment.split('=', 1)[1]
        start, end = start_end.split(',')
        type_ = annotation['body']
        standoffs.append(Standoff(int(start), int(end), type_))
    return standoffs

def get_annotations(url):
    """Return list of annotations from RESTful Open Annotation store."""
    if not url.startswith('http://'): # TODO: use urlparse
        url = 'http://' + url
    request = requests.get(url)
    collection = request.json()
    annotations = collection['@graph']
    return annotations

def get_encoding(request):
    """Return encoding from the Content-Type of the given request, or None
    if no encoding is specified."""
    # Based on get_encoding_from_headers in Python Requests utils.py.
    # Note: by contrast to the Python Requests implementation, we do
    # *not* here follow RFC 2616 and fall back to ISO-8859-1 (Latin 1)
    # in the absence of a "charset" parameter for "text" content
    # types, but simply return None.
    content_type = request.headers.get('Content-Type')
    if content_type is None:
        return None
    value, parameters = cgi.parse_header(content_type)
    if 'charset' not in parameters:
        return None
    return paramseters['charset'].strip("'\"")

def get_document_text(url, encoding=None):
    """Return text of document from given URL.

    Currently assumes that the document is text/plain.
    """
    request = requests.get(url)
    # Strict RFC 2616 compliance (default to Latin 1 when no "charset"
    # given for text) can lead to misalignment issues when servers
    # fail to specify the encoding. To avoid this, check for missing
    # encodings and fall back on the apparent (charted detected)
    # encoding instead.
    if encoding is not None:
        request.encoding = encoding
    elif (get_encoding(request) is None and
          request.encoding.upper() == 'ISO-8859-1' and
          request.apparent_encoding != request.encoding):
        print 'Warning: breaking RFC 2616: ' \
            'using detected encoding (%s) instead of default (%s)' % \
            (request.apparent_encoding, request.encoding)
        request.encoding = request.apparent_encoding
    return request.text

@app.route(API_ROOT, methods=['GET', 'POST'])
@use_args({ 'url': Arg(str),
            'doc': Arg(str),
            'encoding': Arg(str),
            'style': Arg(str),
          })
def explore(args):
    url, doc = args['url'], args['doc']
    encoding, style = args['encoding'], args['style']
    if url is None:
        return select_url()
    elif doc is None:
        return select_doc(url)
    else:
        return visualize_doc(url, doc, encoding, style)

def visualize_doc(url, doc, text_encoding=None, style=None):
    if style is None:
        style = 'visualize'
    # We're stateless with no DB, so we need to get the annotations again
    annotations = get_annotations(url)
    doc_text = get_document_text(doc, text_encoding)
    filtered = filter_by_document(annotations, doc)
    if style == 'list':
        printed = { a['@id']: pretty({ k: v for k, v in a.items()
                                       if k != '@id' })
                    for a in annotations }
        return flask.render_template('annotations.html', annotations=filtered)
    else:
        standoffs = annotations_to_standoffs(filtered)
        return standoff_to_html(doc_text, standoffs,
                                legend=True, tooltips=True, links=True)

def doc_href(url, doc):
    return '%s?url=%s&doc=%s' % (API_ROOT, url, doc)

def select_doc(url):
    annotations = get_annotations(url)
    groups = group_by_document(annotations)
    doc_data = [ {
        'title': d,
        'href': doc_href(url, d),
        'count': len(groups[d]),
        } for d in groups ]
    return flask.render_template('documents.html', documents=doc_data)
    
@app.route(API_ROOT + '/<path:url>')
def explore_url(url):
    return explore({'url': url})

@app.route(API_ROOT, methods=['POST'])
def view_form_url():
    return view(flask.request.form['url'])

@app.route('/')
def root():
    return flask.redirect(API_ROOT)

def select_url():
    return flask.render_template('index.html', root=API_ROOT)

def main(argv):
    # TODO: don't serve directly
    if not DEBUG:
        app.run(host='0.0.0.0', port=7000, debug=False)
    else:
        app.run(debug=DEBUG, port=7000)

if __name__ == '__main__':
    sys.exit(main(sys.argv))
