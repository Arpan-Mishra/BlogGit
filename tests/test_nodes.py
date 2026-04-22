"""
TDD tests for app/agent/nodes.py — parse_github_url, make_repo_analyzer_node,
make_intake_node, and make_drafting_node.

RED phase: written before the implementation exists.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# parse_github_url
# ---------------------------------------------------------------------------


class TestParseGithubUrl:
    @pytest.mark.parametrize(
        "url,expected_owner,expected_repo",
        [
            ("https://github.com/owner/repo", "owner", "repo"),
            ("https://github.com/owner/repo.git", "owner", "repo"),
            ("https://github.com/owner/repo/", "owner", "repo"),
            ("https://github.com/my-org/my-repo", "my-org", "my-repo"),
            ("https://github.com/OWNER/REPO", "OWNER", "REPO"),
        ],
    )
    def test_valid_urls(self, url: str, expected_owner: str, expected_repo: str) -> None:
        from app.agent.nodes import parse_github_url

        owner, repo = parse_github_url(url)
        assert owner == expected_owner
        assert repo == expected_repo

    @pytest.mark.parametrize(
        "bad_url",
        [
            "https://gitlab.com/owner/repo",
            "not-a-url",
            "https://github.com/owner",  # missing repo segment
            "",
        ],
    )
    def test_invalid_urls_raise_value_error(self, bad_url: str) -> None:
        from app.agent.nodes import parse_github_url

        with pytest.raises(ValueError):
            parse_github_url(bad_url)


# ---------------------------------------------------------------------------
# make_repo_analyzer_node
# ---------------------------------------------------------------------------


class TestMakeRepoAnalyzerNode:
    def _make_state(self, repo_url: str = "https://github.com/owner/repo") -> dict:
        from app.agent.state import BlogState

        state: BlogState = {
            "user_id": "user-1",
            "session_id": "sess-1",
            "phase": "repo",
            "messages": [],
            "repo_url": repo_url,
            "repo_summary": None,
            "intake_answers": {},
            "current_draft": None,
            "revision_history": [],
            "notion_page_id": None,
            "notion_title": None,
            "medium_markdown": None,
            "medium_url": None,
            "linkedin_post": None,
            "linkedin_post_url": None,
            "outreach_dm": None,
        }
        return state

    def _make_mock_tools(self) -> list:
        """Return stub tool objects that the node can call."""
        readme_tool = MagicMock()
        readme_tool.name = "get_readme"
        readme_tool.ainvoke = AsyncMock(return_value="# Hello World\nA sample repo.")

        tree_tool = MagicMock()
        tree_tool.name = "get_file_tree"
        tree_tool.ainvoke = AsyncMock(return_value="src/\n  main.py\ntests/\n  test_main.py")

        commits_tool = MagicMock()
        commits_tool.name = "get_recent_commits"
        commits_tool.ainvoke = AsyncMock(
            return_value="abc1234 feat: initial commit\ndef5678 fix: correct typo"
        )

        return [readme_tool, tree_tool, commits_tool]

    def _make_mock_llm(self) -> MagicMock:
        from app.agent.state import RepoSummary

        summary = RepoSummary(
            language="Python",
            modules=("src",),
            purpose="A sample CLI tool.",
            notable_commits=("abc1234 feat: initial commit",),
            readme_excerpt="A sample repo.",
        )

        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=summary)
        return llm

    @pytest.mark.asyncio
    async def test_returns_state_with_repo_summary(self) -> None:
        from app.agent.nodes import make_repo_analyzer_node
        from app.agent.state import RepoSummary

        tools = self._make_mock_tools()
        llm = self._make_mock_llm()
        node = make_repo_analyzer_node(tools=tools, llm=llm)
        state = self._make_state()

        result = await node(state)

        assert "repo_summary" in result
        assert isinstance(result["repo_summary"], RepoSummary)

    @pytest.mark.asyncio
    async def test_advances_phase_to_intake(self) -> None:
        from app.agent.nodes import make_repo_analyzer_node

        tools = self._make_mock_tools()
        llm = self._make_mock_llm()
        node = make_repo_analyzer_node(tools=tools, llm=llm)
        state = self._make_state()

        result = await node(state)

        assert result.get("phase") == "intake"

    @pytest.mark.asyncio
    async def test_raises_value_error_for_missing_repo_url(self) -> None:
        from app.agent.nodes import make_repo_analyzer_node

        tools = self._make_mock_tools()
        llm = self._make_mock_llm()
        node = make_repo_analyzer_node(tools=tools, llm=llm)
        state = self._make_state(repo_url="")
        state["repo_url"] = None

        with pytest.raises(ValueError, match="repo_url"):
            await node(state)

    @pytest.mark.asyncio
    async def test_repo_summary_fields_are_populated(self) -> None:
        from app.agent.nodes import make_repo_analyzer_node
        from app.agent.state import RepoSummary

        tools = self._make_mock_tools()
        llm = self._make_mock_llm()
        node = make_repo_analyzer_node(tools=tools, llm=llm)
        state = self._make_state()

        result = await node(state)

        summary: RepoSummary = result["repo_summary"]
        assert summary.language
        assert summary.purpose
        assert isinstance(summary.modules, tuple)
        assert isinstance(summary.notable_commits, tuple)


# ---------------------------------------------------------------------------
# INTAKE_QUESTIONS constant
# ---------------------------------------------------------------------------


class TestIntakeQuestions:
    def test_has_five_questions(self) -> None:
        from app.agent.nodes import INTAKE_QUESTIONS

        assert len(INTAKE_QUESTIONS) == 5

    def test_first_question_is_audience(self) -> None:
        from app.agent.nodes import INTAKE_QUESTIONS

        key, _ = INTAKE_QUESTIONS[0]
        assert key == "audience"

    def test_last_question_is_extra_instructions(self) -> None:
        from app.agent.nodes import INTAKE_QUESTIONS

        key, _ = INTAKE_QUESTIONS[-1]
        assert key == "extra_instructions"

    def test_each_entry_is_key_text_tuple(self) -> None:
        from app.agent.nodes import INTAKE_QUESTIONS

        for key, text in INTAKE_QUESTIONS:
            assert isinstance(key, str) and key
            assert isinstance(text, str) and text

    def test_keys_are_unique(self) -> None:
        from app.agent.nodes import INTAKE_QUESTIONS

        keys = [k for k, _ in INTAKE_QUESTIONS]
        assert len(keys) == len(set(keys))


# ---------------------------------------------------------------------------
# make_intake_node
# ---------------------------------------------------------------------------


def _make_intake_state(
    messages: list | None = None,
    intake_answers: dict | None = None,
    phase: str = "intake",
) -> dict:
    from app.agent.state import RepoSummary

    summary = RepoSummary(
        language="Python",
        modules=("app",),
        purpose="A test repo.",
        notable_commits=(),
        readme_excerpt="Test readme.",
    )
    return {
        "user_id": "u1",
        "session_id": "s1",
        "phase": phase,
        "messages": messages or [],
        "repo_url": "https://github.com/owner/repo",
        "repo_summary": summary,
        "intake_answers": intake_answers or {},
        "current_draft": None,
        "revision_history": [],
        "notion_page_id": None,
        "notion_title": None,
        "medium_markdown": None,
        "medium_url": None,
        "linkedin_post": None,
        "linkedin_post_url": None,
        "outreach_dm": None,
    }


class TestMakeIntakeNode:
    @pytest.mark.asyncio
    async def test_asks_first_question_when_no_history(self) -> None:
        from langchain_core.messages import AIMessage

        from app.agent.nodes import INTAKE_QUESTIONS, make_intake_node

        node = make_intake_node()
        state = _make_intake_state()

        result = await node(state)

        messages = result["messages"]
        ai_messages = [m for m in messages if isinstance(m, AIMessage)]
        assert len(ai_messages) == 1
        _, q_text = INTAKE_QUESTIONS[0]
        assert q_text in ai_messages[0].content

    @pytest.mark.asyncio
    async def test_stores_answer_and_asks_next_question(self) -> None:
        from langchain_core.messages import AIMessage, HumanMessage

        from app.agent.nodes import INTAKE_QUESTIONS, make_intake_node

        _, q0_text = INTAKE_QUESTIONS[0]
        _, q1_text = INTAKE_QUESTIONS[1]

        node = make_intake_node()
        # State after Q0 was asked and user answered
        messages = [
            HumanMessage(content="https://github.com/owner/repo"),
            AIMessage(content=q0_text),
            HumanMessage(content="Senior engineers"),
        ]
        state = _make_intake_state(messages=messages)

        result = await node(state)

        # Answer stored
        assert result["intake_answers"].get("audience") == "Senior engineers"
        # Next question asked
        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert any(q1_text in m.content for m in ai_messages)

    @pytest.mark.asyncio
    async def test_phase_transitions_to_draft_when_all_answered(self) -> None:
        from langchain_core.messages import AIMessage, HumanMessage

        from app.agent.nodes import INTAKE_QUESTIONS, make_intake_node

        node = make_intake_node()

        # Build a message history with all 5 questions answered
        messages: list = [HumanMessage(content="initial")]
        for key, q_text in INTAKE_QUESTIONS:
            messages.append(AIMessage(content=q_text))
            messages.append(HumanMessage(content=f"Answer to {key}"))

        # Pop the last HumanMessage — the node should receive Q4 already asked
        # and the user's last answer as the final HumanMessage.
        # Remove the last answer so we can test the "last answer received" case.
        # Actually rebuild: all 5 Q-A pairs are complete, one extra HumanMessage
        # acts as the final answer. Let's keep all 5 answers and trigger transition.
        state = _make_intake_state(messages=messages)

        result = await node(state)

        assert result.get("phase") == "outline"

    @pytest.mark.asyncio
    async def test_intake_answers_accumulate(self) -> None:
        from langchain_core.messages import AIMessage, HumanMessage

        from app.agent.nodes import INTAKE_QUESTIONS, make_intake_node

        node = make_intake_node()
        _, q0_text = INTAKE_QUESTIONS[0]
        _, q1_text = INTAKE_QUESTIONS[1]

        # Q0 answered, Q1 answered, node should now store both
        messages = [
            HumanMessage(content="initial"),
            AIMessage(content=q0_text),
            HumanMessage(content="Audience answer"),
            AIMessage(content=q1_text),
            HumanMessage(content="Tone answer"),
        ]
        existing_answers = {"audience": "Audience answer"}
        state = _make_intake_state(messages=messages, intake_answers=existing_answers)

        result = await node(state)

        assert result["intake_answers"]["audience"] == "Audience answer"
        assert result["intake_answers"]["tone"] == "Tone answer"


# ---------------------------------------------------------------------------
# make_drafting_node
# ---------------------------------------------------------------------------


class TestMakeDraftingNode:
    def _make_mock_llm(self, draft_text: str = "# Draft\n\nContent here.") -> MagicMock:
        from langchain_core.messages import AIMessage

        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content=draft_text))
        return llm

    def _make_draft_state(self, intake_answers: dict | None = None) -> dict:
        from app.agent.state import RepoSummary

        summary = RepoSummary(
            language="Python",
            modules=("app", "tests"),
            purpose="A blog copilot tool.",
            notable_commits=("abc1234 feat: initial commit",),
            readme_excerpt="Blog Copilot turns repos into blog posts.",
        )
        return {
            "user_id": "u1",
            "session_id": "s1",
            "phase": "draft",
            "messages": [],
            "repo_url": "https://github.com/owner/repo",
            "repo_summary": summary,
            "intake_answers": intake_answers
            or {
                "audience": "Senior engineers",
                "tone": "Technical",
                "emphasis": "Architecture",
                "avoid": "Client names",
                "extra_instructions": "None",
            },
            "current_draft": None,
            "revision_history": [],
            "notion_page_id": None,
            "notion_title": None,
            "medium_markdown": None,
            "medium_url": None,
            "linkedin_post": None,
            "linkedin_post_url": None,
            "outreach_dm": None,
        }

    @pytest.mark.asyncio
    async def test_returns_current_draft(self) -> None:
        from app.agent.nodes import make_drafting_node

        llm = self._make_mock_llm("My blog post content.")
        node = make_drafting_node(llm=llm)
        state = self._make_draft_state()

        result = await node(state)

        assert result.get("current_draft") == "My blog post content."

    @pytest.mark.asyncio
    async def test_phase_set_to_revise(self) -> None:
        from app.agent.nodes import make_drafting_node

        node = make_drafting_node(llm=self._make_mock_llm())
        state = self._make_draft_state()

        result = await node(state)

        assert result.get("phase") == "revise"

    @pytest.mark.asyncio
    async def test_revision_history_contains_draft_version_1(self) -> None:
        from app.agent.nodes import make_drafting_node
        from app.agent.state import DraftVersion

        node = make_drafting_node(llm=self._make_mock_llm("Draft v1 content."))
        state = self._make_draft_state()

        result = await node(state)

        history = result.get("revision_history", [])
        assert len(history) == 1
        dv = history[0]
        assert isinstance(dv, DraftVersion)
        assert dv.version == 1
        assert dv.content == "Draft v1 content."

    @pytest.mark.asyncio
    async def test_raises_value_error_without_repo_summary(self) -> None:
        from app.agent.nodes import make_drafting_node

        node = make_drafting_node(llm=self._make_mock_llm())
        state = self._make_draft_state()
        state["repo_summary"] = None

        with pytest.raises(ValueError, match="repo_summary"):
            await node(state)

    @pytest.mark.asyncio
    async def test_llm_called_with_prompt_string(self) -> None:
        from app.agent.nodes import make_drafting_node

        llm = self._make_mock_llm()
        node = make_drafting_node(llm=llm)
        state = self._make_draft_state()

        await node(state)

        llm.ainvoke.assert_called_once()
        call_arg = llm.ainvoke.call_args[0][0]
        assert isinstance(call_arg, str)
        assert len(call_arg) > 50  # non-trivial prompt


# ---------------------------------------------------------------------------
# make_drafting_node with search_tool
# ---------------------------------------------------------------------------


class TestMakeDraftingNodeWithSearch:
    """Tests for make_drafting_node when a search_tool is injected."""

    def _make_draft_state(self) -> dict:
        from app.agent.state import RepoSummary

        summary = RepoSummary(
            language="Python",
            modules=("app",),
            purpose="A blog copilot tool.",
            notable_commits=("abc1234 feat: initial",),
            readme_excerpt="Blog Copilot.",
        )
        return {
            "user_id": "u1",
            "session_id": "s1",
            "phase": "draft",
            "messages": [],
            "repo_url": "https://github.com/owner/repo",
            "repo_summary": summary,
            "intake_answers": {
                "audience": "Senior engineers",
                "tone": "Technical",
                "emphasis": "Architecture",
                "avoid": "Client names",
                "extra_instructions": "Include info about LangGraph internals",
            },
            "current_draft": None,
            "revision_history": [],
            "notion_page_id": None,
            "notion_title": None,
            "medium_markdown": None,
            "medium_url": None,
            "linkedin_post": None,
            "linkedin_post_url": None,
            "outreach_dm": None,
        }

    def _make_llm_with_tool_call(self, search_result: str = "Search result content") -> MagicMock:
        """Return an LLM mock that fires one tool call then returns a final draft."""
        from langchain_core.messages import AIMessage

        # First response: LLM makes a tool call
        tool_call_response = MagicMock(spec=AIMessage)
        tool_call_response.content = ""
        tool_call_response.tool_calls = [
            {"name": "tavily_search", "args": {"query": "LangGraph internals"}, "id": "call-1"}
        ]

        # Second response: LLM returns the final draft
        final_response = AIMessage(content="# Draft with search context\n\nContent.")
        final_response_mock = MagicMock(spec=AIMessage)
        final_response_mock.content = "# Draft with search context\n\nContent."
        final_response_mock.tool_calls = []

        llm = MagicMock()
        # bind_tools returns a new LLM with tools bound
        bound_llm = MagicMock()
        bound_llm.ainvoke = AsyncMock(side_effect=[tool_call_response, final_response_mock])
        llm.bind_tools = MagicMock(return_value=bound_llm)
        # Fallback .ainvoke on original (should not be called in tool path)
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="fallback"))
        return llm

    def _make_search_tool(self, result: str = "Search result content") -> MagicMock:
        """Return a mock search tool."""
        tool = MagicMock()
        tool.name = "tavily_search"
        tool.ainvoke = AsyncMock(return_value={
            "query": "test",
            "results": [{"title": "Article", "url": "https://example.com", "content": result}],
        })
        return tool

    @pytest.mark.asyncio
    async def test_search_tool_not_provided_uses_plain_llm(self) -> None:
        """When no search_tool, node falls through to plain LLM invocation."""
        from langchain_core.messages import AIMessage

        from app.agent.nodes import make_drafting_node

        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="Plain draft."))
        node = make_drafting_node(llm=llm)
        state = self._make_draft_state()

        result = await node(state)

        assert result["current_draft"] == "Plain draft."
        # bind_tools should NOT have been called
        llm.bind_tools.assert_not_called() if hasattr(llm, "bind_tools") else None

    @pytest.mark.asyncio
    async def test_llm_bind_tools_called_with_search_tool(self) -> None:
        """When search_tool is provided, llm.bind_tools is called."""
        from app.agent.nodes import make_drafting_node

        llm = self._make_llm_with_tool_call()
        search_tool = self._make_search_tool()
        node = make_drafting_node(llm=llm, search_tool=search_tool)
        state = self._make_draft_state()

        await node(state)

        llm.bind_tools.assert_called_once_with([search_tool])

    @pytest.mark.asyncio
    async def test_search_tool_invoked_for_tool_call(self) -> None:
        """When LLM makes a tool call, the search_tool.ainvoke is called."""
        from app.agent.nodes import make_drafting_node

        llm = self._make_llm_with_tool_call()
        search_tool = self._make_search_tool()
        node = make_drafting_node(llm=llm, search_tool=search_tool)
        state = self._make_draft_state()

        await node(state)

        search_tool.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_final_draft_after_tool_calls(self) -> None:
        """Final draft comes from the LLM response after tool results are injected."""
        from app.agent.nodes import make_drafting_node

        llm = self._make_llm_with_tool_call()
        search_tool = self._make_search_tool()
        node = make_drafting_node(llm=llm, search_tool=search_tool)
        state = self._make_draft_state()

        result = await node(state)

        assert result["current_draft"] == "# Draft with search context\n\nContent."
        assert result["phase"] == "revise"

    @pytest.mark.asyncio
    async def test_no_infinite_loop_when_llm_keeps_calling_tools(self) -> None:
        """Tool-calling loop terminates after MAX_TOOL_ITERATIONS even if LLM never stops."""
        from langchain_core.messages import AIMessage

        from app.agent.nodes import make_drafting_node

        # LLM always returns a tool call, never a final text response
        always_tool_response = MagicMock(spec=AIMessage)
        always_tool_response.content = "partial"
        always_tool_response.tool_calls = [
            {"name": "tavily_search", "args": {"query": "foo"}, "id": "call-x"}
        ]
        bound_llm = MagicMock()
        bound_llm.ainvoke = AsyncMock(return_value=always_tool_response)

        llm = MagicMock()
        llm.bind_tools = MagicMock(return_value=bound_llm)

        search_tool = self._make_search_tool()
        node = make_drafting_node(llm=llm, search_tool=search_tool)
        state = self._make_draft_state()

        # Should complete without raising, not loop forever
        result = await node(state)

        assert "current_draft" in result
        assert result["phase"] == "revise"


# ---------------------------------------------------------------------------
# make_revision_node
# ---------------------------------------------------------------------------


class TestMakeRevisionNode:
    """Tests for make_revision_node — the blog post revision loop."""

    def _make_revision_state(
        self, current_draft: str = "# Original Draft\n\nSome content.", user_feedback: str = "Make it shorter."
    ) -> dict:
        from langchain_core.messages import AIMessage, HumanMessage

        return {
            "user_id": "u1",
            "session_id": "s1",
            "phase": "revise",
            "messages": [
                AIMessage(content=current_draft),
                HumanMessage(content=user_feedback),
            ],
            "repo_url": "https://github.com/owner/repo",
            "repo_summary": None,
            "intake_answers": {},
            "current_draft": current_draft,
            "revision_history": [],
            "notion_page_id": None,
            "notion_title": None,
            "medium_markdown": None,
            "medium_url": None,
            "linkedin_post": None,
            "linkedin_post_url": None,
            "outreach_dm": None,
        }

    def _make_mock_llm(self, draft_content: str = "# Revised Draft\n\nShorter content.") -> MagicMock:
        from langchain_core.messages import AIMessage

        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content=draft_content))
        return llm

    @pytest.mark.asyncio
    async def test_raises_without_current_draft(self) -> None:
        from app.agent.nodes import make_revision_node

        node = make_revision_node(llm=self._make_mock_llm())
        state = self._make_revision_state()
        state["current_draft"] = None

        with pytest.raises(ValueError, match="current_draft"):
            await node(state)

    @pytest.mark.asyncio
    async def test_returns_revised_draft(self) -> None:
        from app.agent.nodes import make_revision_node

        node = make_revision_node(llm=self._make_mock_llm("# Revised."))
        state = self._make_revision_state()

        result = await node(state)

        assert result["current_draft"] == "# Revised."

    @pytest.mark.asyncio
    async def test_phase_stays_revise(self) -> None:
        from app.agent.nodes import make_revision_node

        node = make_revision_node(llm=self._make_mock_llm())
        result = await node(self._make_revision_state())

        assert result["phase"] == "revise"

    @pytest.mark.asyncio
    async def test_revision_history_increments(self) -> None:
        from app.agent.nodes import make_revision_node
        from app.agent.state import DraftVersion

        node = make_revision_node(llm=self._make_mock_llm("Rev 1."))
        state = self._make_revision_state()
        state["revision_history"] = [DraftVersion(version=1, content="# Original Draft\n\nSome content.")]

        result = await node(state)

        history = result["revision_history"]
        assert len(history) == 2
        assert history[1].version == 2
        assert history[1].content == "Rev 1."

    @pytest.mark.asyncio
    async def test_user_feedback_stored_in_draft_version(self) -> None:
        from app.agent.nodes import make_revision_node
        from app.agent.state import DraftVersion

        node = make_revision_node(llm=self._make_mock_llm())
        state = self._make_revision_state(user_feedback="Add more code examples.")

        result = await node(state)

        latest: DraftVersion = result["revision_history"][-1]
        assert latest.user_feedback == "Add more code examples."

    @pytest.mark.asyncio
    async def test_revised_draft_appended_to_messages(self) -> None:
        from langchain_core.messages import AIMessage

        from app.agent.nodes import make_revision_node

        node = make_revision_node(llm=self._make_mock_llm("Revised content."))
        state = self._make_revision_state()
        initial_count = len(state["messages"])

        result = await node(state)

        new_messages = result["messages"][initial_count:]
        assert len(new_messages) == 1
        assert isinstance(new_messages[0], AIMessage)
        assert new_messages[0].content == "Revised content."

    @pytest.mark.asyncio
    async def test_llm_called_with_prompt_containing_draft_and_feedback(self) -> None:
        from app.agent.nodes import make_revision_node

        llm = self._make_mock_llm()
        node = make_revision_node(llm=llm)
        state = self._make_revision_state(
            current_draft="# Original Draft\n\nSome content.",
            user_feedback="Make it shorter.",
        )

        await node(state)

        llm.ainvoke.assert_called_once()
        prompt_arg = llm.ainvoke.call_args[0][0]
        assert isinstance(prompt_arg, str)
        assert "# Original Draft" in prompt_arg
        assert "Make it shorter." in prompt_arg


# ---------------------------------------------------------------------------
# _extract_citation_url
# ---------------------------------------------------------------------------


class TestExtractCitationUrl:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("add citation: https://example.com", "https://example.com"),
            ("please include https://arxiv.org/abs/1234 as a reference", "https://arxiv.org/abs/1234"),
            ("cite this https://openai.com/research", "https://openai.com/research"),
            ("add this reference https://paper.com/foo.", "https://paper.com/foo"),
            ("reference: https://docs.python.org/3/)", "https://docs.python.org/3/"),
        ],
    )
    def test_extracts_url_from_citation_intent(self, text: str, expected: str) -> None:
        from app.agent.nodes import _extract_citation_url

        assert _extract_citation_url(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "make the intro shorter",
            "add more technical depth",
            "https://example.com without citation keyword",
            "",
        ],
    )
    def test_returns_none_when_no_citation_intent(self, text: str) -> None:
        from app.agent.nodes import _extract_citation_url

        assert _extract_citation_url(text) is None


# ---------------------------------------------------------------------------
# Citation intercept in intake_node
# ---------------------------------------------------------------------------


class TestIntakeCitationIntercept:
    def _make_state(self, messages: list, user_citations: tuple = ()) -> dict:
        from app.agent.state import RepoSummary

        summary = RepoSummary(
            language="Python",
            modules=("app",),
            purpose="A test repo.",
            notable_commits=(),
            readme_excerpt="Test readme.",
        )
        return {
            "user_id": "u1",
            "session_id": "s1",
            "phase": "intake",
            "messages": messages,
            "repo_url": "https://github.com/owner/repo",
            "repo_summary": summary,
            "intake_answers": {},
            "user_citations": user_citations,
            "current_draft": None,
            "revision_history": [],
            "notion_page_id": None,
            "notion_title": None,
            "medium_markdown": None,
            "medium_url": None,
            "linkedin_post": None,
            "linkedin_post_url": None,
            "outreach_dm": None,
        }

    @pytest.mark.asyncio
    async def test_citation_message_appends_url_and_reraises_question(self) -> None:
        from langchain_core.messages import AIMessage, HumanMessage

        from app.agent.nodes import INTAKE_QUESTIONS, make_intake_node

        node = make_intake_node()
        _, q0_text = INTAKE_QUESTIONS[0]
        messages = [
            AIMessage(content=q0_text),
            HumanMessage(content="add citation: https://arxiv.org/abs/1234"),
        ]
        state = self._make_state(messages=messages)

        result = await node(state)

        assert result["phase"] == "intake"
        assert "https://arxiv.org/abs/1234" in result["user_citations"]
        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
        # The confirmation message should re-ask the current question
        assert any(q0_text in m.content for m in ai_messages)

    @pytest.mark.asyncio
    async def test_citation_accumulates_with_existing_citations(self) -> None:
        from langchain_core.messages import AIMessage, HumanMessage

        from app.agent.nodes import INTAKE_QUESTIONS, make_intake_node

        node = make_intake_node()
        _, q0_text = INTAKE_QUESTIONS[0]
        messages = [
            AIMessage(content=q0_text),
            HumanMessage(content="cite https://example.com please"),
        ]
        state = self._make_state(
            messages=messages,
            user_citations=("https://prior.com",),
        )

        result = await node(state)

        assert "https://prior.com" in result["user_citations"]
        assert "https://example.com" in result["user_citations"]


# ---------------------------------------------------------------------------
# Citation intercept in revision_node
# ---------------------------------------------------------------------------


class TestRevisionCitationIntercept:
    def _make_state(self, user_feedback: str, user_citations: tuple = ()) -> dict:
        from langchain_core.messages import HumanMessage

        from app.agent.state import RepoSummary

        summary = RepoSummary(
            language="Python",
            modules=("app",),
            purpose="A test repo.",
            notable_commits=(),
            readme_excerpt="Test readme.",
        )
        return {
            "user_id": "u1",
            "session_id": "s1",
            "phase": "revise",
            "messages": [HumanMessage(content=user_feedback)],
            "repo_url": "https://github.com/owner/repo",
            "repo_summary": summary,
            "intake_answers": {},
            "user_citations": user_citations,
            "current_draft": "# Draft\n\nContent here.",
            "revision_history": [],
            "notion_page_id": None,
            "notion_title": None,
            "medium_markdown": None,
            "medium_url": None,
            "linkedin_post": None,
            "linkedin_post_url": None,
            "outreach_dm": None,
        }

    def _make_mock_llm(self, content: str = "Revised.") -> MagicMock:
        from langchain_core.messages import AIMessage

        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content=content))
        return llm

    @pytest.mark.asyncio
    async def test_citation_url_extracted_and_stored_in_state(self) -> None:
        from app.agent.nodes import make_revision_node

        node = make_revision_node(llm=self._make_mock_llm())
        state = self._make_state("add citation: https://paper.ai/foo make intro shorter")

        result = await node(state)

        assert "https://paper.ai/foo" in result["user_citations"]

    @pytest.mark.asyncio
    async def test_citation_url_injected_into_llm_prompt(self) -> None:
        from app.agent.nodes import make_revision_node

        llm = self._make_mock_llm()
        node = make_revision_node(llm=llm)
        state = self._make_state("add citation: https://paper.ai/foo make intro shorter")

        await node(state)

        prompt = llm.ainvoke.call_args[0][0]
        assert "https://paper.ai/foo" in prompt


# ---------------------------------------------------------------------------
# _build_drafting_prompt with user_citations
# ---------------------------------------------------------------------------


class TestBuildDraftingPromptCitations:
    def _make_summary(self):
        from app.agent.state import RepoSummary

        return RepoSummary(
            language="Python",
            modules=("app",),
            purpose="A test tool.",
            notable_commits=(),
            readme_excerpt="Test.",
        )

    def test_user_citations_section_included_when_provided(self) -> None:
        from app.agent.nodes import _build_drafting_prompt

        prompt = _build_drafting_prompt(
            system_prompt="System.",
            repo_summary=self._make_summary(),
            intake_answers={},
            user_citations=("https://example.com", "https://another.org"),
        )

        assert "https://example.com" in prompt
        assert "https://another.org" in prompt
        assert "User-Provided Citations" in prompt

    def test_no_citations_section_when_empty(self) -> None:
        from app.agent.nodes import _build_drafting_prompt

        prompt = _build_drafting_prompt(
            system_prompt="System.",
            repo_summary=self._make_summary(),
            intake_answers={},
            user_citations=(),
        )

        assert "User-Provided Citations" not in prompt


# ---------------------------------------------------------------------------
# _is_approval
# ---------------------------------------------------------------------------


class TestIsApproval:
    @pytest.mark.parametrize(
        "text",
        [
            "yes",
            "Yes!",
            "looks good",
            "ok",
            "lgtm",
            "perfect",
            "approve",
            "fine",
            "proceed",
            "sounds good",
        ],
    )
    def test_approval_texts_return_true(self, text: str) -> None:
        from app.agent.nodes import _is_approval

        assert _is_approval(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "no, change the intro",
            "I don't like the structure, please add a section about testing",
            "make it shorter and remove the deployment section",
        ],
    )
    def test_non_approval_texts_return_false(self, text: str) -> None:
        from app.agent.nodes import _is_approval

        assert _is_approval(text) is False

    def test_long_affirmative_text_returns_false(self) -> None:
        from app.agent.nodes import _is_approval

        # >120 chars should not be treated as approval even if it starts affirmatively
        long_text = "yes " + "this looks good but please also add more details about the CI pipeline and deployment workflow " * 2
        assert _is_approval(long_text) is False


# ---------------------------------------------------------------------------
# make_outline_node
# ---------------------------------------------------------------------------


class TestOutlineNode:
    def _make_state(
        self,
        outline_plan: str | None = None,
        user_message: str = "looks good",
        user_citations: tuple = (),
    ) -> dict:
        from langchain_core.messages import HumanMessage

        from app.agent.state import RepoSummary

        summary = RepoSummary(
            language="Python",
            modules=("app",),
            purpose="A test repo.",
            notable_commits=("Add feature X",),
            readme_excerpt="Test readme.",
        )
        return {
            "user_id": "u1",
            "session_id": "s1",
            "phase": "outline",
            "messages": [HumanMessage(content=user_message)],
            "repo_url": "https://github.com/owner/repo",
            "repo_summary": summary,
            "intake_answers": {"audience": "developers"},
            "outline_plan": outline_plan,
            "user_citations": user_citations,
            "current_draft": None,
            "revision_history": [],
            "notion_page_id": None,
            "notion_title": None,
            "medium_markdown": None,
            "medium_url": None,
            "linkedin_post": None,
            "linkedin_post_url": None,
            "outreach_dm": None,
        }

    def _make_mock_llm(self, content: str = "## Outline\n\n1. Intro\n2. Body\n3. Conclusion") -> MagicMock:
        from langchain_core.messages import AIMessage

        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content=content))
        return llm

    @pytest.mark.asyncio
    async def test_first_invocation_generates_outline(self) -> None:
        from app.agent.nodes import make_outline_node

        llm = self._make_mock_llm()
        node = make_outline_node(llm=llm)
        state = self._make_state(outline_plan=None, user_message="start outline")

        result = await node(state)

        assert result["outline_plan"] is not None
        assert result["phase"] == "outline"
        assert llm.ainvoke.called

    @pytest.mark.asyncio
    async def test_approval_transitions_to_draft(self) -> None:
        from app.agent.nodes import make_outline_node

        node = make_outline_node(llm=self._make_mock_llm())
        state = self._make_state(outline_plan="## Outline\n\n1. Intro", user_message="looks good")

        result = await node(state)

        assert result["phase"] == "draft"

    @pytest.mark.asyncio
    async def test_feedback_revises_outline(self) -> None:
        from app.agent.nodes import make_outline_node

        revised = "## Revised Outline\n\n1. New Intro\n2. Body\n3. Conclusion"
        llm = self._make_mock_llm(content=revised)
        node = make_outline_node(llm=llm)
        state = self._make_state(
            outline_plan="## Outline\n\n1. Intro",
            user_message="please add a section about testing",
        )

        result = await node(state)

        assert result["phase"] == "outline"
        assert result["outline_plan"] == revised
        assert llm.ainvoke.called

    @pytest.mark.asyncio
    async def test_citation_intercept_during_outline(self) -> None:
        from app.agent.nodes import make_outline_node

        node = make_outline_node(llm=self._make_mock_llm())
        state = self._make_state(
            outline_plan="## Outline\n\n1. Intro",
            user_message="add citation: https://arxiv.org/paper",
        )

        result = await node(state)

        assert "https://arxiv.org/paper" in result["user_citations"]
        assert result["phase"] == "outline"

    @pytest.mark.asyncio
    async def test_outline_plan_stored_in_messages(self) -> None:
        from langchain_core.messages import AIMessage

        from app.agent.nodes import make_outline_node

        outline_text = "## Draft Outline\n\n1. Intro\n2. Implementation\n3. Conclusion"
        llm = self._make_mock_llm(content=outline_text)
        node = make_outline_node(llm=llm)
        state = self._make_state(outline_plan=None, user_message="start")

        result = await node(state)

        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert any(outline_text in m.content for m in ai_messages)
