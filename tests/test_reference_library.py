from __future__ import annotations

import unittest

from core.director_proposals.reference_library_codec import (
    parse_reference_library_proposal,
)
from core.director_proposals.schema_gen import ProposalError


class ReferenceLibraryAgentTests(unittest.IsolatedAsyncioTestCase):
    def test_agent_rejects_unknown_card_fields(self) -> None:
        with self.assertRaisesRegex(ProposalError, "未声明"):
            parse_reference_library_proposal(
                """{
                  "characters":[{
                    "name":"小满","visual_description":"短发",
                    "voice_description":"","model_prompt":"cinematic"
                  }],"narrator":null
                }"""
            )


if __name__ == "__main__":
    unittest.main()
