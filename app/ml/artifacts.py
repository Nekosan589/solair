# app/ml/artifacts.py
"""
Loads the trained X-ANFIS model (via its own save_model/load_model
mechanism — NOT plain pickle) plus the input and output scalers.
"""
from typing import Any, Optional
import xanfis.models.base_anfis as base_anfis

# 1. Inject the missing private attribute so Python can find it during deserialization
if not hasattr(base_anfis.CustomANFIS, '__get_strength_by_blend'):
    # Point the missing name to its internal name-mangled version
    base_anfis.CustomANFIS.__get_strength_by_blend = base_anfis.CustomANFIS._CustomANFIS__get_strength_by_blend # type: ignore


from xanfis import GdAnfisRegressor
import pickle

_model: Optional[Any] = None
_scaler_x: Optional[Any] = None
_scaler_y: Optional[Any] = None


def load_artifacts(model_load_path: str, model_filename: str, scaler_x_path: str, scaler_y_path: str) -> None:
    global _model, _scaler_x, _scaler_y

    # X-ANFIS models must be loaded via their own static load_model(),
    # matching how save_model() wrote them.
    _model = GdAnfisRegressor.load_model(load_path=model_load_path, filename=model_filename)

    with open(scaler_x_path, "rb") as f:
        _scaler_x = pickle.load(f)

    with open(scaler_y_path, "rb") as f:
        _scaler_y = pickle.load(f)


def get_model() -> Any:
    if _model is None:
        raise RuntimeError("Model not loaded — load_artifacts() must run on app startup")
    return _model


def get_scaler_x() -> Any:
    if _scaler_x is None:
        raise RuntimeError("scaler_X not loaded — load_artifacts() must run on app startup")
    return _scaler_x


def get_scaler_y() -> Any:
    if _scaler_y is None:
        raise RuntimeError("scaler_y not loaded — load_artifacts() must run on app startup")
    return _scaler_y