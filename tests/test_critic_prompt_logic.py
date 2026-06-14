"""Test case to verify Critic logic on distiller evidence output."""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

# Ensure parent directory is in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow import Graph
from skills import SkillRegistry, run_skill
from schemas import AgentResult
from gateway import ensure_gateway


@pytest.mark.asyncio
async def test_critic_verifies_distiller_evidence_quotes():
    """Test that Critic passes when evidence supports fields,
    and fails when fields are fabricated or mismatch the evidence."""
    ensure_gateway()
    registry = SkillRegistry()
    registry.get("critic").provider_pin = "gemini"

    # Case A: Correct evidence quotes matching the fields -> PASS
    distiller_output_pass = {
        "fields": {
            "birth_date": "April 30, 1916",
            "death_date": "February 24, 2001"
        },
        "evidence": {
            "birth_date": "April 30, 1916",
            "death_date": "February 24, 2001"
        },
        "rationale": "Extracted birth and death dates from Wikipedia."
    }

    g_pass = Graph()
    distiller_pass = g_pass.add_node("distiller", inputs=["USER_QUERY"])
    g_pass.g.nodes[distiller_pass]["status"] = "complete"
    g_pass.g.nodes[distiller_pass]["result"] = AgentResult(
        success=True,
        agent_name="distiller",
        output=distiller_output_pass,
        elapsed_s=0.1
    )

    critic_pass = g_pass.add_node("critic", inputs=["USER_QUERY", distiller_pass], metadata={
        "target": distiller_pass,
        "question": "Verify birth and death date of Claude Shannon."
    })

    result_pass, _ = await run_skill(
        registry.get("critic"),
        critic_pass,
        g_pass.g.nodes,
        session_id="test_sess_critic_pass",
        query="Fetch birth and death date of Claude Shannon",
        failure_report=None
    )

    assert result_pass.success is True
    assert result_pass.output.get("verdict") == "pass"

    # Case B: Fabricated fields mismatching the evidence -> FAIL
    distiller_output_fail = {
        "fields": {
            "birth_date": "January 1, 1900",  # Fabricated mismatch
            "death_date": "December 31, 2099"  # Fabricated mismatch
        },
        "evidence": {
            "birth_date": "April 30, 1916",  # Truth
            "death_date": "February 24, 2001"  # Truth
        },
        "rationale": "Extracted birth and death dates."
    }

    g_fail = Graph()
    distiller_fail = g_fail.add_node("distiller", inputs=["USER_QUERY"])
    g_fail.g.nodes[distiller_fail]["status"] = "complete"
    g_fail.g.nodes[distiller_fail]["result"] = AgentResult(
        success=True,
        agent_name="distiller",
        output=distiller_output_fail,
        elapsed_s=0.1
    )

    critic_fail = g_fail.add_node("critic", inputs=["USER_QUERY", distiller_fail], metadata={
        "target": distiller_fail,
        "question": "Verify birth and death date of Claude Shannon."
    })

    result_fail, _ = await run_skill(
        registry.get("critic"),
        critic_fail,
        g_fail.g.nodes,
        session_id="test_sess_critic_fail",
        query="Fetch birth and death date of Claude Shannon",
        failure_report=None
    )

    assert result_fail.success is True
    assert result_fail.output.get("verdict") == "fail"
