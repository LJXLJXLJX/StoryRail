"""文档编解码包（L1）：原 document_codec.py 按域拆为 codec/ 包。

public 签名保持不变：``serialize_document`` / ``_parse_document`` 由本包
再导出，`from core.structured_director.codec import X` 路径不变
（包目录取代原文件，import 语义保持）。各域文件只依赖 models/（L0）、
L1 公共词汇（schema/video_contracts）与 stdlib。
"""

from .document import _parse_document as _parse_document
from .document import serialize_document as serialize_document

__all__ = ["serialize_document"]
