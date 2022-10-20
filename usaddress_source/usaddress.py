#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import print_function
from builtins import zip
from builtins import str
import os
import sys
import string
import re
try:
    from collections import OrderedDict
except ImportError:
    from ordereddict import OrderedDict
import warnings

from definitions import LABELS, PARENT_LABEL, GROUP_LABEL, MODEL_FILE, MODEL_PATH, DIRECTIONS, STREET_NAMES, TAGGER, US_VALID_ZIPCODES

import pycrfsuite
import probableparsing

# Possible validation exceptiosn

class InvalidUSStateError(Exception):
    pass

class InvalidPlaceNameError(Exception):
    # Invalid PlaceName error is associated with either the city or the county that is provided
    # on an address. If the PlaceName is not associated with either the city or the county that is
    # given with the appropriate zipcode that is provided, then the place name error is raised.
    pass


class InvalidZipCodeError(Exception):
    pass


class InvalidStreetError(Exception):
    pass

# The address components are based upon the `United States Thoroughfare,
# Landmark, and Postal Address Data Standard
# http://www.urisa.org/advocacy/united-states-thoroughfare-landmark-and-postal-address-data-standard

try:
    TAGGER = pycrfsuite.Tagger()
    TAGGER.open(MODEL_PATH)
except IOError:
    warnings.warn('You must train the model (parserator train --trainfile '
                  'FILES) to create the %s file before you can use the parse '
                  'and tag methods' % MODEL_FILE)

def validate_tagged_address(address_string, tags):

    valid_zip_code = US_VALID_ZIPCODES.get(tags.get('ZipCode'))
    if  valid_zip_code == None:
        raise InvalidZipCodeError("Zipcode provided {tags.get('ZipCode')} in address '{address_string}' is invalid and does not exist.")

    if valid_zip_code.get('state') != tags.get('StateName'):
        raise InvalidUSStateError("State provided {tags.get('StateName')} is not associated with zipcode {tags.get('ZipCode')}, state that is associated with the zipcode is {valid_zip_code.get('state')}")

    if valid_zip_code.get('city') != tags.get('PlaceName') and valid_zip_cdoe.get('county') != tags.get('PlaceName'):
        raise InvalidPlaceNameError('The place name that is provided {tags.get("PlaceName")} for zipcode {tags.get("ZipCode")} does not match either the city or the county name that is associated with that zip code. The city and county that is associated with that zip code are {valid_zip_code.get("city")} and {valid_zip_code.get("county")}.')


def validate_parsed_address(address_string, parsed_items):

    for item in parsed_items:
        if item[0] == 'ZipCode':
            zip_code_provided = item[1]
            valid_zip_code = US_VALID_ZIPCODES.get(item[1])
        if item[0] == 'StateName':
            state = item[1]
        if item[0] == 'PlaceName':
            placename = item[1]

    if  valid_zip_code == None:
        raise InvalidZipCodeError("Zipcode provided {zip_code_provided} in address '{address_string}' is invalid and does not exist.")

    if valid_zip_code.get('state') != state:
        raise InvalidUSStateError("State provided {state} is not associated with zipcode {zip_code_provided}, state that is associated with the zipcode is {valid_zip_code.get('state')}")

    if valid_zip_code.get('city') != placename and valid_zip_cdoe.get('county') != placename:
        raise InvalidPlaceNameError('The place name that is provided {placename} for zipcode {zip_code_provided} does not match either the city or the county name that is associated with that zip code. The city and county that is associated with that zip code are {valid_zip_code.get("city")} and {valid_zip_code.get("county")}.')


def parse(address_string, validate=False):
    tokens = tokenize(address_string)

    if not tokens:
        return []

    features = tokens2features(tokens)

    tags = TAGGER.tag(features)
    
    parsed_result = list(zip(tokens, tags))

    if validate == True:
        validate_parsed_address(address_string, parsed_result)

    return parsed_result


def tag(address_string, tag_mapping=None, validate=False):
    tagged_address = OrderedDict()

    last_label = None
    is_intersection = False
    og_labels = []

    for token, label in parse(address_string):
        if label == 'IntersectionSeparator':
            is_intersection = True
        if 'StreetName' in label and is_intersection:
            label = 'Second' + label

        # saving old label
        og_labels.append(label)
        # map tag to a new tag if tag mapping is provided
        if tag_mapping and tag_mapping.get(label):
            label = tag_mapping.get(label)
        else:
            label = label

        if label == last_label:
            tagged_address[label].append(token)
        elif label not in tagged_address:
            tagged_address[label] = [token]
        else:
            raise RepeatedLabelError(address_string, parse(address_string),
                                     label)

        last_label = label

    for token in tagged_address:
        component = ' '.join(tagged_address[token])
        component = component.strip(" ,;")
        tagged_address[token] = component

    if 'AddressNumber' in og_labels and not is_intersection:
        address_type = 'Street Address'
    elif is_intersection and 'AddressNumber' not in og_labels:
        address_type = 'Intersection'
    elif 'USPSBoxID' in og_labels:
        address_type = 'PO Box'
    else:
        address_type = 'Ambiguous'

    if validate == True:
        validate_tagged_address(address_string, tagged_address)

    return tagged_address, address_type


def tokenize(address_string):
    if isinstance(address_string, bytes):
        address_string = str(address_string, encoding='utf-8')
    address_string = re.sub('(&#38;)|(&amp;)', '&', address_string)
    re_tokens = re.compile(r"""
    \(*\b[^\s,;#&()]+[.,;)\n]*   # ['ab. cd,ef '] -> ['ab.', 'cd,', 'ef']
    |
    [#&]                       # [^'#abc'] -> ['#']
    """,
                           re.VERBOSE | re.UNICODE)

    tokens = re_tokens.findall(address_string)

    if not tokens:
        return []

    return tokens


def tokenFeatures(token):
    if token in (u'&', u'#', u'½'):
        token_clean = token
    else:
        token_clean = re.sub(r'(^[\W]*)|([^.\w]*$)', u'', token,
                             flags=re.UNICODE)

    token_abbrev = re.sub(r'[.]', u'', token_clean.lower())
    features = {
        'abbrev': token_clean[-1] == u'.',
        'digits': digits(token_clean),
        'word': (token_abbrev
                 if not token_abbrev.isdigit()
                 else False),
        'trailing.zeros': (trailingZeros(token_abbrev)
                           if token_abbrev.isdigit()
                           else False),
        'length': (u'd:' + str(len(token_abbrev))
                   if token_abbrev.isdigit()
                   else u'w:' + str(len(token_abbrev))),
        'endsinpunc': (token[-1]
                       if bool(re.match('.+[^.\w]', token, flags=re.UNICODE))
                       else False),
        'directional': token_abbrev in DIRECTIONS,
        'street_name': token_abbrev in STREET_NAMES,
        'has.vowels': bool(set(token_abbrev[1:]) & set('aeiou')),
    }

    return features


def tokens2features(address):
    feature_sequence = [tokenFeatures(address[0])]
    previous_features = feature_sequence[-1].copy()

    for token in address[1:]:
        token_features = tokenFeatures(token)
        current_features = token_features.copy()

        feature_sequence[-1]['next'] = current_features
        token_features['previous'] = previous_features

        feature_sequence.append(token_features)

        previous_features = current_features

    feature_sequence[0]['address.start'] = True
    feature_sequence[-1]['address.end'] = True

    if len(feature_sequence) > 1:
        feature_sequence[1]['previous']['address.start'] = True
        feature_sequence[-2]['next']['address.end'] = True

    return feature_sequence


def digits(token):
    if token.isdigit():
        return 'all_digits'
    elif set(token) & set(string.digits):
        return 'some_digits'
    else:
        return 'no_digits'


def trailingZeros(token):
    results = re.findall(r'(0+)$', token)
    if results:
        return results[0]
    else:
        return ''


class RepeatedLabelError(probableparsing.RepeatedLabelError):
    REPO_URL = 'https://github.com/datamade/usaddress/issues/new'
    DOCS_URL = 'https://usaddress.readthedocs.io/'
