#!/usr/bin/env python

"""RESTful Open Annotation explorer.

Proxy for RESTful Open Annotations with server-side visualization.
"""

__author__ = 'Sampo Pyysalo'
__license__ = 'MIT'

import sys
import json
import urlparse
import urllib
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

# Key for the list of collection items in RESTful OA collection
# response.
ITEMS_KEY = '@graph'

Standoff = namedtuple('MyStandoff', 'start end type')

app = flask.Flask(__name__)

@app.before_request
def log_request():
    app.logger.info('%s %s' % (flask.request, flask.request.args))

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

def get_collection(url):
    """Return annotation collection from RESTful Open Annotation store."""
    response = requests.get(url)
    response.raise_for_status()
    collection = response.json()
    return collection

def get_annotations(url):
    """Return list of annotations from RESTful Open Annotation store."""
    collection = get_collection(url)
    annotations = collection[ITEMS_KEY]
    return annotations

def get_encoding(response):
    """Return encoding from the Content-Type of the given response, or None
    if no encoding is specified."""
    # Based on get_encoding_from_headers in Python Requests utils.py.
    # Note: by contrast to the Python Requests implementation, we do
    # *not* here follow RFC 2616 and fall back to ISO-8859-1 (Latin 1)
    # in the absence of a "charset" parameter for "text" content
    # types, but simply return None.
    content_type = response.headers.get('Content-Type')
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
    response = requests.get(url)
    # Strict RFC 2616 compliance (default to Latin 1 when no "charset"
    # given for text) can lead to misalignment issues when servers
    # fail to specify the encoding. To avoid this, check for missing
    # encodings and fall back on the apparent (charted detected)
    # encoding instead.
    if encoding is not None:
        response.encoding = encoding
    elif (get_encoding(response) is None and
          response.encoding.upper() == 'ISO-8859-1' and
          response.apparent_encoding != response.encoding):
        app.logger.warning('Breaking RFC 2616: ' \
            'using detected encoding (%s) instead of default (%s)' % \
            (response.apparent_encoding, response.encoding))
        response.encoding = response.apparent_encoding
    return response.text

def fix_url(url):
    """Fix potentially incomplete client-provided URL."""
    # Note: urlparse gives unexpected results when given an
    # incomplete url with a port and a path but no scheme:
    # >>> urlparse.urlparse('example.org:80/foo').scheme
    # 'example.org'
    # We're avoiding this issue by prepending a default scheme
    # if there's no obvious one present.
    def has_scheme(u):
        return u.startswith('http://') or u.startswith('https://')
    if not has_scheme(url):
        url = 'http://' + url
    return url

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
    url = fix_url(url)
    if doc is None:
        return select_doc(url)
    else:
        return visualize(url, doc, encoding, style)

def is_relative(url):
    return urlparse.urlparse(url).netloc == ''

def rewrite_links(collection, base, proxy_url):
    """Rewrite collection navigation links to go through a proxy.

    Given a representation of a collection resource received from a
    RESTful Open Annotation server, rewrite all links it contains to
    go through this proxy.
    """
    # TODO: use @context instead of this ad-hoc list to decide
    # which values are URIs.
    uri_keys = set(['next', 'prev', 'start', 'last'])
    new_collection = {}
    for key, value in collection.iteritems():
        if key in uri_keys:
            if is_relative(value):
                value = urlparse.urljoin(base, value)
            value = proxy_url + urllib.quote(value)
        new_collection[key] = value
    # TODO: recurse
    return new_collection

def visualize(url, doc, text_encoding=None, style=None):
    if style is None:
        style = 'visualize'

    # We're stateless with no DB, so we need to get the annotations again
    collection = get_collection(url)
    proxy_root = flask.request.base_url + '?url='
    collection = rewrite_links(collection, url, proxy_root)
    annotations = collection[ITEMS_KEY]

    if doc == 'all': # TODO: avoid magic string
        filtered = annotations
        doc_text = None
    else:
        filtered = filter_by_document(annotations, doc)
        doc_text = get_document_text(doc, text_encoding)

    if style == 'list':
        return flask.render_template('annotations.html',
                                     collection=collection,
                                     annotations=filtered)
    else:
        if doc == 'all':
            return 'Sorry, can only visualize a single document at a time!'
        standoffs = annotations_to_standoffs(filtered)
        return standoff_to_html(doc_text, standoffs,
                                legend=True, tooltips=True, links=True)

def doc_href(url, doc):
    return '%s?url=%s&doc=%s' % (API_ROOT, urllib.quote(url),
                                 urllib.quote(doc))

def select_doc(url):
    annotations = get_annotations(url)
    groups = group_by_document(annotations)
    doc_data = [ {
        'title': d,
        'href': doc_href(url, d),
        'count': len(groups[d]),
        } for d in groups ]
    quoted_url = urllib.quote(url)
    return flask.render_template('documents.html', url=quoted_url,
                                 documents=doc_data)
    
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
    #app.logger.addHandler(log_handler())
    if not DEBUG:
        app.run(host='0.0.0.0', port=7000, debug=False)
    else:
        app.run(debug=DEBUG, port=7000)

if __name__ == '__main__':
    sys.exit(main(sys.argv))
