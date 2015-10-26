"""JTS type casting. Patterned on okfn/messy-tables"""
# -*- coding: utf-8 -*-
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import os
import re
import decimal
import datetime
import time
import json
import operator
import base64
import binascii
import uuid
from dateutil.parser import parse as date_parse
import rfc3987
import unicodedata
import jsonschema
from . import compat, utilities, exceptions


class JTSType(object):

    """Base class for all JSON Table Schema types."""

    py = type(None)
    name = ''
    formats = ('default',)

    def __init__(self, field=None, **kwargs):
        """Setup some variables for easy access. `field` is the field schema."""

        self.field = field

        if self.field:
            self.format = self.field['format']
            self.required = self.field['constraints']['required']
        else:
            self.format = 'default'
            self.required = True

    def cast(self, value):
        if self.required and value in (None, ''):
            raise exceptions.RequiredFieldError(
                '{0} is a required field'.format(self.field)
            )

        # cast with the appropriate handler, falling back to default if none

        if self.format.startswith('fmt'):
            _format = 'fmt'
        else:
            _format = self.format

        _handler = 'cast_{0}'.format(_format)

        if self.has_format(_format) and hasattr(self, _handler):
            return getattr(self, _handler)(value)

        return self.cast_default(value)

    def can_cast(self, value):
        try:
            self.cast(value)
            return True
        except exceptions.InvalidCastError:
            return False

    def cast_default(self, value):
        """Return boolean if the value can be cast to the type/format."""

        if self._type_check(value):
            return value

        try:
            if not self.py == compat.str:
                return self.py(value)

        except (ValueError, TypeError, decimal.InvalidOperation) as e:
            raise exceptions.InvalidCastError(e.message)

        raise exceptions.InvalidCastError('Could not cast value')

    def has_format(self, _format):
        return _format in self.formats

    def _type_check(self, value):
        return isinstance(value, self.py)


class StringType(JTSType):

    py = compat.str
    name = 'string'
    formats = ('default', 'email', 'uri', 'binary', 'uuid')
    email_pattern = re.compile(r'[^@]+@[^@]+\.[^@]+')

    def cast_email(self, value):
        if not self._type_check(value):
            raise exceptions.InvalidStringType(
                '{0} is not of type {1}'.format(value, self.py)
            )

        if not re.match(self.email_pattern, value):
            raise exceptions.InvalidEmail(
                '{0} is not a valid email'.format(value)
            )
        return value

    def cast_uri(self, value):
        if not self._type_check(value):
            return False

        try:
            rfc3987.parse(value, rule="URI")
            return value
        except ValueError:
            raise exceptions.InvalidURI('{0} is not a valid uri'.format(value))

    def cast_binary(self, value):
        if not self._type_check(value):
            raise exceptions.InvalidStringType()

        try:
            base64.b64decode(value)
        except binascii.Error as e:
            raise exceptions.InvalidBinary(e.message)
        return value

    def cast_uuid(self, value):
        """Return `value` if is a uuid, else return False."""

        if not self._type_check(value):
            raise exceptions.InvalidStringType(
                '{0} is not of type {1}'.format(value, self.py)
            )
        try:
            uuid.UUID(value, version=4)
            return value
        except ValueError as e:
            raise exceptions.InvalidUUID(e.message)


class IntegerType(JTSType):
    py = int
    name = 'integer'


class NumberType(JTSType):

    py = decimal.Decimal
    name = 'number'
    formats = ('default', 'currency')
    separators = ',; '
    currencies = u''.join(unichr(i) for i
                          in range(0xffff)
                          if unicodedata.category(unichr(i)) == 'Sc')

    def cast_currency(self, value):
        value = re.sub('[{0}{1}]'.format(self.separators, self.currencies),
                       '', value)
        try:
            return decimal.Decimal(value)
        except decimal.InvalidOperation:
            raise exceptions.InvalidCurrency(
                '{0} is not a valid currency'.format(value)
            )


class BooleanType(JTSType):

    py = bool
    name = 'boolean'
    true_values = utilities.TRUE_VALUES
    false_values = utilities.FALSE_VALUES

    def cast_default(self, value):
        """Return boolean if `value` can be cast as type `self.py`"""

        if isinstance(value, self.py):
            return value
        else:
            try:
                value = value.strip().lower()
            except AttributeError:
                pass

            if value in (self.true_values):
                return True
            elif value in (self.false_values):
                return False
            else:
                raise exceptions.InvalidBooleanType(
                    '{0} is not a boolean value'.format(value)
                )


class NullType(JTSType):

    py = type(None)
    name = 'null'
    null_values = utilities.NULL_VALUES

    def cast_default(self, value):
        if isinstance(value, self.py):
            return value
        else:
            value = value.strip().lower()
            if value in self.null_values:
                return None
            else:
                raise exceptions.InvalidNoneType(
                    '{0} is not a none type'.format(value)
                )


class ArrayType(JTSType):

    py = list
    name = 'array'

    def cast_default(self, value):
        """Return boolean if `value` can be cast as type `self.py`"""

        if isinstance(value, self.py):
            return value
        try:
            array_type = json.loads(value)
            if isinstance(array_type, self.py):
                return array_type
            else:
                raise exceptions.InvalidArrayType('Not an array')

        except (TypeError, ValueError):
            raise exceptions.InvalidArrayType(
                '{0} is not a array type'.format(value)
            )


class ObjectType(JTSType):

    py = dict
    name = 'object'

    def cast_default(self, value):
        if isinstance(value, self.py):
            return value
        try:
            json_value = json.loads(value)
            if isinstance(json_value, self.py):
                return json_value
            else:
                raise exceptions.InvalidObjectType()
        except (TypeError, ValueError) as e:
            raise exceptions.InvalidObjectType(e.message)


class DateType(JTSType):

    py = datetime.date
    name = 'date'
    formats = ('default', 'any', 'fmt')
    ISO8601 = '%Y-%m-%d'

    # TODO: stuff from messy tables for date parsing, to replace this simple format map?
    # https://github.com/okfn/messytables/blob/master/messytables/dateparser.py#L10
    raw_formats = ['DD/MM/YYYY', 'DD/MM/YY', 'YYYY/MM/DD']
    py_formats = ['%d/%m/%Y', '%d/%m/%y', '%Y/%m/%d']
    format_map = dict(zip(raw_formats, py_formats))

    def cast_default(self, value):
        try:
            return datetime.datetime.strptime(value, self.ISO8601).date()
        except (TypeError, ValueError) as e:
            raise exceptions.InvalidDateType(e.message)

    def cast_any(self, value):
        try:
            return date_parse(value).date()
        except (TypeError, ValueError) as e:
            raise exceptions.InvalidDateType(e.message)

    def cast_fmt(self, value):
        try:
            date_format = self.format.strip('fmt:')
            return datetime.datetime.strptime(value, date_format).date()
        except (TypeError, ValueError) as e:
            raise exceptions.InvalidDateType(e.message)


class TimeType(JTSType):

    py = time
    name = 'time'
    formats = ('default', 'any', 'fmt')
    ISO8601 = '%H:%M:%S'

    # TODO: stuff from messy tables for date parsing, to replace this simple format map?
    # https://github.com/okfn/messytables/blob/master/messytables/dateparser.py#L10
    raw_formats = ['HH/MM/SS']
    py_formats = ['%H:%M:%S']
    format_map = dict(zip(raw_formats, py_formats))

    def cast_default(self, value):
        try:
            struct_time = time.strptime(value, self.ISO8601)
            return datetime.time(struct_time.tm_hour, struct_time.tm_min,
                                 struct_time.tm_sec)
        except (TypeError, ValueError) as e:
            raise exceptions.InvalidTimeType(e.message)

    def cast_any(self, value):
        try:
            return date_parse(value).time()
        except (TypeError, ValueError) as e:
            raise exceptions.InvalidTimeType(e.message)

    def cast_fmt(self, value):
        time_format = self.format.strip('fmt:')
        try:
            return datetime.datetime.strptime(value, time_format).time()
        except (TypeError, ValueError) as e:
            raise exceptions.InvalidTimeType(e.message)


class DateTimeType(JTSType):

    py = datetime.datetime
    name = 'datetime'
    formats = ('default', 'any', 'fmt')
    ISO8601 = '%Y-%m-%dT%H:%M:%SZ'

    # TODO: stuff from messy tables for date parsing, to replace this simple format map?
    # https://github.com/okfn/messytables/blob/master/messytables/dateparser.py#L10
    raw_formats = ['DD/MM/YYYYThh/mm/ss']
    py_formats = ['%Y/%m/%dT%H:%M:%S']
    format_map = dict(zip(raw_formats, py_formats))

    def cast_default(self, value):
        try:
            return datetime.datetime.strptime(value, self.ISO8601)
        except (TypeError, ValueError) as e:
            raise exceptions.InvalidDateTimeType(e.message)

    def cast_any(self, value):
        try:
            return date_parse(value)
        except (TypeError, ValueError) as e:
            raise exceptions.InvalidDateTimeType(e.message)

    def cast_fmt(self, value):
        try:
            format = self.format.strip('fmt:')
            return datetime.datetime.strptime(value, format)
        except (TypeError, ValueError) as e:
            raise exceptions.InvalidDateTimeType(e.message)


class GeoPointType(JTSType):

    py = compat.str, list, dict
    name = 'geopoint'
    formats = ('default', 'array', 'object')

    def _check_latitude_longtiude_range(self, geopoint):
        longitude = geopoint[0]
        latitude = geopoint[1]
        if longitude >= 180 or longitude <= -180:
            raise exceptions.InvalidGeoPointType(
                'longtitude should be between -180 and 180, '
                'found: {0}'.format(longitude)
            )
        elif latitude >= 90 or latitude <= -90:
            raise exceptions.InvalidGeoPointType(
                'latitude should be between -90 and 90, '
                'found: {0}'.format(latitude)
            )

    def cast_default(self, value):
        try:
            if self._type_check(value):
                points = value.split(',')
                if len(points) == 2:
                    try:
                        geopoints = [decimal.Decimal(points[0].strip()),
                                     decimal.Decimal(points[1].strip())]
                        # TODO: check degree minute second formats?
                        self._check_latitude_longtiude_range(geopoints)
                        return geopoints
                    except decimal.DecimalException as e:
                        raise exceptions.InvalidGeoPointType(
                            e.message
                        )
                else:
                    raise exceptions.InvalidGeoPointType(
                        '{0}: point is not of length 2'.format(value)
                    )
        except (TypeError, ValueError) as e:
            raise exceptions.InvalidGeoPointType(e.message)

    def cast_array(self, value):
        try:
            json_value = json.loads(value)
            if isinstance(json_value, list) and len(json_value) == 2:
                try:
                    longitude = json_value[0].strip()
                    latitude = json_value[1].strip()
                except AttributeError:
                    longitude = json_value[0]
                    latitude = json_value[1]

                try:
                    geopoints = [decimal.Decimal(longitude),
                                 decimal.Decimal(latitude)]
                    self._check_latitude_longtiude_range(geopoints)
                    return geopoints
                except decimal.DecimalException as e:
                    raise exceptions.InvalidGeoPointType(
                        e.message
                    )
            else:
                raise exceptions.InvalidGeoPointType(
                    '{0}: point is not of length 2'.format(value)
                )
        except (TypeError, ValueError) as e:
            raise exceptions.InvalidGeoPointType(e.message)

    def cast_object(self, value):
        try:
            json_value = json.loads(value)

            try:
                longitude = json_value['longitude'].strip()
                latitude = json_value['latitude'].strip()
            except AttributeError:
                longitude = json_value['longitude']
                latitude = json_value['latitude']
            except KeyError as e:
                raise exceptions.InvalidGeoPointType(
                    e.message
                )

            try:
                geopoints = [decimal.Decimal(longitude),
                             decimal.Decimal(latitude)]
                # TODO: check degree minute second formats?
                self._check_latitude_longtiude_range(geopoints)
                return geopoints
            except decimal.DecimalException as e:
                raise exceptions.InvalidGeoPointType(
                    e.message
                )
        except (TypeError, ValueError) as e:
            raise exceptions.InvalidGeoPointType(e.message)


def load_geojson_schema():
    filepath = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                            'geojson/geojson.json')
    with open(filepath) as f:
        json_table_schema = json.load(f)
    return json_table_schema

geojson_schema = load_geojson_schema()


class GeoJSONType(JTSType):

    py = dict
    name = 'geojson'
    formats = ('default', 'topojson')
    spec = {
        'types': ['Point', 'MultiPoint', 'LineString', 'MultiLineString',
                  'Polygon', 'MultiPolygon', 'GeometryCollection', 'Feature',
                  'FeatureCollection']
    }

    def cast_default(self, value):
        if isinstance(value, self.py):
            try:
                jsonschema.validate(value, geojson_schema)
                return value
            except jsonschema.exceptions.ValidationError as e:
                raise exceptions.InvalidGeoJSONType(e.message)
        if isinstance(value, compat.str):
            try:
                geojson = json.loads(value)
                jsonschema.validate(geojson, geojson_schema)
                return geojson
            except (TypeError, ValueError) as e:
                raise exceptions.InvalidGeoJSONType(e.message)
            except jsonschema.exceptions.ValidationError as e:
                raise exceptions.InvalidGeoJSONType(e.message)

    def cast_topojson(self, value):
        raise NotImplementedError


class AnyType(JTSType):

    name = 'any'

    def cast(self, value):
        return True


def _available_types():
    """Return available types."""
    return (AnyType, StringType, BooleanType, NumberType, IntegerType,
            NullType, DateType, TimeType, DateTimeType, ArrayType, ObjectType,
            GeoPointType, GeoJSONType)


class TypeGuesser(object):

    """Guess the type for a value.

    Returns:
        * A tuple  of ('type', 'format')

    """

    def __init__(self, type_options=None):
        self._types = _available_types()
        self.type_options = type_options or {}

    def cast(self, value):
        for _type in reversed(self._types):
            result = _type(self.type_options.get(_type.name, {})).can_cast(value)
            if result:
                # TODO: do format guessing
                rv = (_type.name, 'default')
                break

        return rv


class TypeResolver(object):

    """Get the best matching type/format from a list of possible ones."""

    def __init__(self):
        self._types = _available_types()

    def get(self, results):

        variants = set(results)

        # only one candidate... that's easy.
        if len(variants) == 1:
            rv = {
                'type': results[0][0],
                'format': results[0][1],
            }

        else:
            counts = {}
            for result in results:
                if counts.get(result):
                    counts[result] += 1
                else:
                    counts[result] = 1

            # tuple representation of `counts` dict, sorted by values of `counts`
            sorted_counts = sorted(counts.items(), key=operator.itemgetter(1),
                                   reverse=True)
            rv = {
                'type': sorted_counts[0][0][0],
                'format': sorted_counts[0][0][1]
            }


        return rv
