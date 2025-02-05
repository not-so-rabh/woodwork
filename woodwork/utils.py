
import ast
import importlib
import re

import numpy as np
import pandas as pd

import woodwork as ww


def import_or_none(library):
    """Attempts to import the requested library.

    Args:
        library (str): the name of the library
    Returns: the library if it is installed, else None
    """
    try:
        return importlib.import_module(library)
    except ImportError:
        return None


def camel_to_snake(s):
    s = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', s)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s).lower()


def _convert_input_to_set(semantic_tags, error_language='semantic_tags', validate=True):
    """Takes input as a single string, a list of strings, or a set of strings
        and returns a set with the supplied values. If no values are supplied,
        an empty set will be returned."""
    if not semantic_tags:
        return set()

    if validate:
        _validate_tags_input_type(semantic_tags, error_language)

    if isinstance(semantic_tags, str):
        return {semantic_tags}

    if isinstance(semantic_tags, list):
        semantic_tags = set(semantic_tags)

    if validate:
        _validate_string_tags(semantic_tags, error_language)

    return semantic_tags


def _validate_tags_input_type(semantic_tags, error_language):
    if type(semantic_tags) not in [list, set, str]:
        raise TypeError(f"{error_language} must be a string, set or list")


def _validate_string_tags(semantic_tags, error_language):
    if not all([isinstance(tag, str) for tag in semantic_tags]):
        raise TypeError(f"{error_language} must contain only strings")


def read_csv(filepath=None,
             name=None,
             index=None,
             time_index=None,
             semantic_tags=None,
             logical_types=None,
             use_standard_tags=True,
             validate=True,
             **kwargs):
    """Read data from the specified CSV file and return a DataFrame with initialized Woodwork typing information.

    Args:
        filepath (str): A valid string path to the file to read
        name (str, optional): Name used to identify the DataFrame.
        index (str, optional): Name of the index column.
        time_index (str, optional): Name of the time index column.
        semantic_tags (dict, optional): Dictionary mapping column names in the dataframe to the
            semantic tags for the column. The keys in the dictionary should be strings
            that correspond to columns in the underlying dataframe. There are two options for
            specifying the dictionary values:
            (str): If only one semantic tag is being set, a single string can be used as a value.
            (list[str] or set[str]): If multiple tags are being set, a list or set of strings can be
            used as the value.
            Semantic tags will be set to an empty set for any column not included in the
            dictionary.
        logical_types (dict[str -> LogicalType], optional): Dictionary mapping column names in
            the dataframe to the LogicalType for the column. LogicalTypes will be inferred
            for any columns not present in the dictionary.
        use_standard_tags (bool, optional): If True, will add standard semantic tags to columns based
            on the inferred or specified logical type for the column. Defaults to True.
        validate (bool, optional): Whether parameter and data validation should occur. Defaults to True. Warning:
                Should be set to False only when parameters and data are known to be valid.
                Any errors resulting from skipping validation with invalid inputs may not be easily understood.
        **kwargs: Additional keyword arguments to pass to the underlying ``pandas.read_csv`` function. For more
            information on available keywords refer to the pandas documentation.

    Returns:
        pd.DataFrame: DataFrame created from the specified CSV file with Woodwork typing information initialized.
    """
    dataframe = pd.read_csv(filepath, **kwargs)
    dataframe.ww.init(name=name,
                      index=index,
                      time_index=time_index,
                      semantic_tags=semantic_tags,
                      logical_types=logical_types,
                      use_standard_tags=use_standard_tags,
                      validate=validate)
    return dataframe


def import_or_raise(library, error_msg):
    """Attempts to import the requested library.  If the import fails, raises an
    ImportError with the supplied error message.

    Args:
        library (str): the name of the library
        error_msg (str): error message to return if the import fails
    """
    try:
        return importlib.import_module(library)
    except ImportError:
        raise ImportError(error_msg)


def _is_s3(string):
    """Checks if the given string is a s3 path. Returns a boolean."""
    return "s3://" in string


def _is_url(string):
    """Checks if the given string is an url path. Returns a boolean."""
    return 'http' in string


def _reformat_to_latlong(latlong, use_list=False):
    """Reformats LatLong columns to be tuples of floats. Uses np.nan for null values."""
    if _is_null_latlong(latlong):
        return np.nan

    if isinstance(latlong, str):
        try:
            # Serialized latlong columns from csv or parquet will be strings, so null values will be
            # read as the string 'nan' in pandas and Dask and 'NaN' in Koalas
            # neither of which which is interpretable as a null value
            if 'nan' in latlong:
                latlong = latlong.replace('nan', 'None')
            if 'NaN' in latlong:
                latlong = latlong.replace('NaN', 'None')
            latlong = ast.literal_eval(latlong)
        except ValueError:
            pass

    if isinstance(latlong, (tuple, list)):
        if len(latlong) != 2:
            raise ValueError(f'LatLong values must have exactly two values. {latlong} does not have two values.')

        latitude, longitude = map(_to_latlong_float, latlong)

        # (np.nan, np.nan) should be counted as a single null value
        if pd.isnull(latitude) and pd.isnull(longitude):
            return np.nan

        if use_list:
            return [latitude, longitude]
        return (latitude, longitude)

    raise ValueError(f'LatLongs must either be a tuple, a list, or a string representation of a tuple. {latlong} does not fit the criteria.')


def _to_latlong_float(val):
    """Attempts to convert a value to a float, propagating null values."""
    if _is_null_latlong(val):
        return np.nan

    try:
        return float(val)
    except (ValueError, TypeError):
        raise ValueError(f'Latitude and Longitude values must be in decimal degrees. The latitude or longitude represented by {val} cannot be converted to a float.')


def _is_valid_latlong_series(series):
    """Returns True if all elements in the series contain properly formatted LatLong values,
    otherwise returns False"""
    dd = import_or_none('dask.dataframe')
    ks = import_or_none('databricks.koalas')
    if dd and isinstance(series, dd.Series):
        series = series.compute()
    if ks and isinstance(series, ks.Series):
        series = series.to_pandas()
        bracket_type = list
    else:
        bracket_type = tuple
    if series.apply(_is_valid_latlong_value, args=(bracket_type,)).all():
        return True
    return False


def _is_valid_latlong_value(val, bracket_type=tuple):
    """Returns True if the value provided is a properly formatted LatLong value for a
    pandas, Dask or Koalas Series, otherwise returns False."""
    if isinstance(val, bracket_type) and len(val) == 2:
        latitude, longitude = val
        if isinstance(latitude, float) and isinstance(longitude, float):
            if pd.isnull(latitude) and pd.isnull(longitude):
                return False
            return True
    elif isinstance(val, float) and pd.isnull(val):
        return True
    return False


def _is_null_latlong(val):
    if isinstance(val, str):
        return val == 'None' or val == 'nan' or val == 'NaN'

    # Since we can have list inputs here, pd.isnull will not have a relevant truth value for lists
    return not isinstance(val, list) and pd.isnull(val)


def get_valid_mi_types():
    """
    Generate a list of LogicalTypes that are valid for calculating mutual information. Note that
    index columns are not valid for calculating mutual information, but their types may be
    returned by this function.

    Args:
        None

    Returns:
        list(LogicalType): A list of the LogicalTypes that can be use to calculate mutual information
    """
    valid_types = []
    for ltype in ww.type_system.registered_types:
        if 'category' in ltype.standard_tags:
            valid_types.append(ltype)
        elif 'numeric' in ltype.standard_tags:
            valid_types.append(ltype)
        elif (ltype == ww.logical_types.Datetime or ltype == ww.logical_types.Boolean or
                ltype == ww.logical_types.BooleanNullable):
            valid_types.append(ltype)

    return valid_types


def _get_column_logical_type(series, logical_type, name):
    if logical_type:
        return _parse_logical_type(logical_type, name)
    else:
        return ww.type_system.infer_logical_type(series)


def _parse_logical_type(logical_type, name):
    if isinstance(logical_type, str):
        logical_type = ww.type_system.str_to_logical_type(logical_type)
    ltype_class = ww.type_sys.utils._get_ltype_class(logical_type)
    if ltype_class == ww.logical_types.Ordinal and not isinstance(logical_type, ww.logical_types.Ordinal):
        raise TypeError("Must use an Ordinal instance with order values defined")
    if ltype_class in ww.type_system.registered_types:
        return logical_type
    else:
        raise TypeError(f"Invalid logical type specified for '{name}'")
