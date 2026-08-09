from nvidia_agentic_rag.agents.factory import PROMPT_VERSION, SYSTEM_PROMPT


def test_prompt_has_multicorpus_and_citation_rules() -> None:
    assert "agentic_rag_course_tool" in SYSTEM_PROMPT
    assert "research_paper_rag_tool" in SYSTEM_PROMPT
    assert "citation IDs" in SYSTEM_PROMPT
    assert "query-complexity levels" in SYSTEM_PROMPT
    assert PROMPT_VERSION in SYSTEM_PROMPT
