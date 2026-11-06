from __future__ import annotations

import unittest

from core.director_proposals.narration_codec import (
    parse_narration_review_proposal,
)
from core.director_proposals.schema_gen import ProposalError


class NarrationReviewAgentTests(unittest.IsolatedAsyncioTestCase):
    def test_unknown_fields_are_rejected(self) -> None:
        with self.assertRaisesRegex(ProposalError, "未声明"):
            parse_narration_review_proposal(
                """{
                  "reply_markdown":"已调整。",
                  "cue_updates":[{
                    "cue_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "seed":42,
                    "regenerate":true,
                    "text":"越权改正文"
                  }]
                }"""
            )


if __name__ == "__main__":
    unittest.main()
