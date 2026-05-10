"""Tests for sanitizer workflow nodes — coverage gaps."""
import pytest
from unittest.mock import MagicMock, patch


class TestSanitizerWorkflowNodesInit:
    def test_exports_sanitizer_node(self):
        from plugins.security.sanitizer.workflow.nodes import SanitizerNode, __all__
        assert "SanitizerNode" in __all__
        assert SanitizerNode is not None


class TestInterventionNode:
    @pytest.mark.asyncio
    async def test_execute_with_threats(self):
        from plugins.security.sanitizer.workflow.nodes.intervention_node import InterventionNode
        node = InterventionNode()
        result = await node.execute({
            "threats": ["jailbreak", "injection"],
            "severity": "high",
        })
        assert result["activated"] is True
        assert result["threat_type"] == "jailbreak"
        assert isinstance(result["response"], str)

    @pytest.mark.asyncio
    async def test_execute_no_threats(self):
        from plugins.security.sanitizer.workflow.nodes.intervention_node import InterventionNode
        node = InterventionNode()
        result = await node.execute({})
        assert result["activated"] is True
        assert result["threat_type"] == "unknown"

    def test_metadata(self):
        from plugins.security.sanitizer.workflow.nodes.intervention_node import InterventionNode
        node = InterventionNode()
        meta = node.get_metadata()
        assert meta.node_type == "intervention.respond"


class TestSanitizerNode:
    def test_metadata(self):
        with patch("plugins.security.sanitizer.workflow.nodes.sanitizer_node.get_sanitizer"):
            from plugins.security.sanitizer.workflow.nodes.sanitizer_node import SanitizerNode
            node = SanitizerNode()
            meta = node.get_metadata()
            assert "sanitizer" in meta.id.lower() or "sanitizer" in meta.name.lower()

    @pytest.mark.asyncio
    async def test_execute_safe_text(self):
        mock_result = MagicMock()
        mock_result.is_safe = True
        mock_result.needs_intervention = False
        mock_result.severity = "none"
        mock_result.threats_detected = []
        mock_result.patterns_matched = []
        mock_result.clean_text = "hello"
        mock_result.scan_time_ms = 0.5

        mock_sanitizer = MagicMock()
        mock_sanitizer.sanitize.return_value = mock_result

        with patch("plugins.security.sanitizer.workflow.nodes.sanitizer_node.get_sanitizer", return_value=mock_sanitizer):
            from plugins.security.sanitizer.workflow.nodes.sanitizer_node import SanitizerNode
            node = SanitizerNode()
            result = await node.execute({"text": "hello"})

        assert result["is_safe"] is True
        assert result["severity"] == "none"
