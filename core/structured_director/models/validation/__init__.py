"""按域校验函数包：从 models 两个超长 __post_init__ 原样抽取，顺序与消息不变。"""

from .document import validate_document
from .generation import validate_reference_generation

__all__ = ["validate_document", "validate_reference_generation"]
