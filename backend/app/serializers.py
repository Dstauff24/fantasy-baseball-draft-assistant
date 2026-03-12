from dataclasses import asdict, is_dataclass
from typing import Any


def to_dict(obj: Any) -> Any:
    """JSON-safe conversion for dataclasses and nested containers."""
    if is_dataclass(obj):
        return {k: to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_dict(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)