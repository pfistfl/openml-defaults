import hashlib
import logging
import numpy as np
import pandas as pd
import sklearn.base
import sklearn.preprocessing
import typing


def hash_df(df: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(df, index=True).values).hexdigest()


def get_scaler(scaling_type: typing.Optional[str]) -> sklearn.base.TransformerMixin:
    legal_types = {
        'MinMaxScaler': sklearn.preprocessing.MinMaxScaler(),
        'StandardScaler': sklearn.preprocessing.StandardScaler()
    }
    if scaling_type not in legal_types:
        raise ValueError('Can not find scaling type: %s' % scaling_type)
    return legal_types[scaling_type]


def normalize_df_columnwise(df: pd.DataFrame, scaling_type: typing.Optional[str]) -> pd.DataFrame:
    logging.info('scaling dataframe (no specific measure indicated) with %s' % scaling_type)
    if scaling_type is None:
        return df

    scaler = get_scaler(scaling_type)
    for column in df.columns.values:
        res = scaler.fit_transform(df[column].values.reshape(-1, 1))[:, 0]
        df[column] = res
    return df


def create_a3r_frame(scoring_frame: pd.DataFrame, runtime_frame: pd.DataFrame) -> pd.DataFrame:
    """
    Replaces all occurrences of zero in the runtime frame with the min val (to
    prevent division by zero) and uses this frame to create a a3r frame.
    """
    min_val = np.min(runtime_frame.values[np.nonzero(runtime_frame.values)])
    runtime_frame = runtime_frame.replace(0, min_val)
    assert(np.array_equal(scoring_frame.columns.values, runtime_frame.columns.values))
    assert(np.array_equal(scoring_frame.shape, runtime_frame.shape))
    return scoring_frame / runtime_frame
