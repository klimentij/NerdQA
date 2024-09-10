from enum import Enum
from typing import Optional, Union


class TrimType(Enum):
    START = 'START'
    END = 'END'
    MIDDLE = 'MIDDLE'

class Trim:
    """
    A class to handle trimming of inputs.

    Attributes
    ----------
    name : str
        The name of the input to trim.
    trim_type : TrimType
        The type of trimming to perform.
    min_length : int
        The minimum length (in tokens) of the input after trimming.
    max_length : int
        Don't let the input exceed this length (in tokens) anyway.
    """
    def __init__(self, name: str, trim_type: Union[str, TrimType], min_length: Optional[int] = 0, max_length: Optional[int] = None):
        self.name = name

        if isinstance(trim_type, str):
            try:
                self.trim_type = TrimType(trim_type.upper())
            except ValueError:
                raise ValueError(f"Invalid trim_type. Must be one of {[t.value for t in list(TrimType)]}")
        elif isinstance(trim_type, TrimType):
            self.trim_type = trim_type
        else:
            raise TypeError("trim_type must be either a str or a TrimType")

        if min_length is not None:
            if min_length < 0:
                raise ValueError("min_length cannot be negative")

        self.min_length = min_length

        if max_length is not None:
            if max_length < 0:
                raise ValueError("max_length cannot be negative")

            if min_length is not None and max_length < min_length:
                raise ValueError("max_length cannot be less than min_length")

        self.max_length = max_length