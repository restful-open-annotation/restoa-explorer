#!/usr/bin/env python

"""RESTful Open Annotation explorer."""

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

DEBUG = True

API_ROOT = '/explore'

app = flask.Flask(__name__)

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
          })
def explore(args):
    url, doc, encoding = args['url'], args['doc'], args['encoding']
    if url is None:
        return select_url()
    elif doc is None:
        return select_doc(url)
    else:
        return visualize_doc(url, doc, encoding)

def visualize_doc(url, doc, text_encoding=None):
    # We're stateless with no DB, so we need to get the annotations again
    annotations = get_annotations(url)
    doc_text = get_document_text(doc, text_encoding)
    filtered = filter_by_document(annotations, doc)
    printed = { a['@id']: pretty({ k: v for k, v in a.items() if k != '@id' })
                for a in annotations }
    return flask.render_template('annotations.html', annotations=filtered)

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

@app.route('/css/<path:path>')
def style(path):
    return flask.send_from_directory('css', path)

@app.route('/img/<path:path>')
def image(path):
    return flask.send_from_directory('img', path)

def main(argv):
    app.run(debug=DEBUG, port=8090)

if __name__ == '__main__':
    sys.exit(main(sys.argv))
