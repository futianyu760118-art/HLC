"""Tests for AI assistant context management fixes.

Covers:
1. Classifier enhancements: person-job-fit, extended verbs, job requirements
   query routing, pronoun in workset mentions, _named_subject_assessment.
2. Pronoun resolution: EntityMemory.resolve() with InMemoryEntityStore.
3. Fallback answer: _fallback_answer() pronoun / job-query / general paths.
4. Entity persistence: _persist_entities_to_memory() from orchestrator.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from services.assistant_core.schemas import AssistantContext, ExecutionResult, RouteDecision
from services.assistant_core.intent_router.classifier import (
    TrackClassifier,
    TRACK_A,
    TRACK_B,
    TRACK_C,
    _named_subject_assessment,
    GENERATION_KEYWORDS,
    WORKSET_MENTIONS,
)
from services.assistant_core.intent_router.entity_memory import (
    EntityMemory,
    NamedEntity,
    InMemoryEntityStore,
    CANDIDATE,
    EMPLOYEE,
)
from services.assistant_core.executors.dialogue_executor import _fallback_answer
from services.assistant_core.legacy_orchestrator import _persist_entities_to_memory


# ---- helpers ---------------------------------------------------------------

def _ctx(
    role: str = 'hr_admin',
    session_id: str = 'sess-ctx-test',
    history: list | None = None,
) -> AssistantContext:
    return AssistantContext(
        user_id='u-test',
        role=role,
        session_id=session_id,
        history=history or [],
    )


# ===========================================================================
# 1. Classifier enhancement tests
# ===========================================================================


class TestClassifierPersonJobFit:
    """Person-job-fit assessment should route to TRACK_B (generation).

    Note: _named_subject_assessment runs before the candidate_job_fit regex
    and captures many of the same messages as ``person_assessment``.  Both
    intents route to TRACK_B with ``named_subject_evidence`` context, so
    the critical assertion is the track, not the exact intent name.
    """

    def test_person_job_fit_standard(self) -> None:
        """Named person + fit verb + job standard → TRACK_B generation."""
        decision = TrackClassifier().classify('吴明华符合供应链总监的标准吗', _ctx())
        assert decision.route_track == TRACK_B
        assert decision.intent in ('candidate_job_fit', 'person_assessment')
        assert 'named_subject_evidence' in decision.required_context

    def test_person_job_fit_with_negation(self) -> None:
        """'是否满足' variant should also route to generation track."""
        decision = TrackClassifier().classify('张三是否满足岗位要求', _ctx())
        assert decision.route_track == TRACK_B
        assert decision.intent in ('candidate_job_fit', 'person_assessment')

    def test_person_job_fit_shengren(self) -> None:
        decision = TrackClassifier().classify('李四能否胜任这个职位', _ctx())
        assert decision.route_track == TRACK_B
        assert decision.intent in ('candidate_job_fit', 'person_assessment')


class TestClassifierNamedAssessmentWithNewVerbs:
    """Extended verbs in _named_subject_assessment should be recognized."""

    def test_manzu_verb(self) -> None:
        decision = TrackClassifier().classify('吴明华满足岗位要求吗', _ctx())
        # Should route to TRACK_B (generation), not C (dialogue)
        assert decision.route_track == TRACK_B

    def test_pipei_verb(self) -> None:
        decision = TrackClassifier().classify('王五匹配这个岗位吗', _ctx())
        assert decision.route_track == TRACK_B


class TestClassifierJobRequirementsQuery:
    """Job requirements/standards queries should route to TRACK_A."""

    def test_job_requirements_query(self) -> None:
        decision = TrackClassifier().classify('供应链总监的岗位标准是什么', _ctx())
        assert decision.route_track == TRACK_A
        assert decision.intent == 'job_requirements_query'

    def test_job_requirements_tiaojian(self) -> None:
        """Job conditions query without data verbs → job_requirements_query."""
        decision = TrackClassifier().classify('产品经理岗位条件', _ctx())
        assert decision.route_track == TRACK_A
        assert decision.intent == 'job_requirements_query'

    def test_job_zhize_query(self) -> None:
        decision = TrackClassifier().classify('这个职位的职责是什么', _ctx())
        assert decision.route_track == TRACK_A
        assert decision.intent == 'job_requirements_query'


class TestClassifierPronounInWorksetMentions:
    """Pronouns '他'/'她' should be recognized as workset mentions."""

    def test_ta_in_workset_mentions(self) -> None:
        assert '他' in WORKSET_MENTIONS

    def test_she_in_workset_mentions(self) -> None:
        assert '她' in WORKSET_MENTIONS

    def test_pronoun_triggers_workset_context(self) -> None:
        """Messages containing '他' should be recognized as followup generation context."""
        decision = TrackClassifier().classify('帮他生成面试题', _ctx())
        # '他' is in WORKSET_MENTIONS, and '生成...面试题' triggers generation
        assert decision.route_track == TRACK_B
        assert 'candidate_workset' in decision.required_context or 'latest_workset' in decision.required_context


class TestNamedSubjectAssessmentExtendedVerbs:
    """_named_subject_assessment should recognize new verbs."""

    @pytest.mark.parametrize('verb', ['符合', '满足', '适合', '胜任', '匹配'])
    def test_extended_verbs_recognized(self, verb: str) -> None:
        text = f'{verb}吴明华的'
        assert _named_subject_assessment(text) is True

    def test_original_verbs_still_work(self) -> None:
        assert _named_subject_assessment('评价吴明华的') is True
        assert _named_subject_assessment('评估张三这个人') is True


class TestGenerationKeywordsExtended:
    """GENERATION_KEYWORDS should contain the newly added verbs."""

    @pytest.mark.parametrize('kw', ['符合', '满足', '胜任', '匹配', '达标', '合格', '够格'])
    def test_new_keywords_present(self, kw: str) -> None:
        assert kw in GENERATION_KEYWORDS


# ===========================================================================
# 2. Pronoun resolution tests
# ===========================================================================


class TestResolvePronounHe:
    """After storing a candidate entity, '他' should be resolved to the name."""

    def test_resolve_pronoun_he(self) -> None:
        store = InMemoryEntityStore()
        mem = EntityMemory(store)
        session_id = 'sess-pronoun-he'

        # Store a candidate entity
        now = time.time()
        mem.set(session_id, NamedEntity(
            type=CANDIDATE,
            value='吴明华',
            source_turn_index=1,
            expires_at=now + 1800,
        ))

        resolved, trace = mem.resolve('他怎么样', session_id, now=now)
        assert '吴明华' in resolved
        assert trace['pronouns_found'] == ['他']
        assert any(s['replaced_with'] == '吴明华' for s in trace['substitutions'])


class TestResolvePronounThisPerson:
    """'这个人' should be resolved to a specific name."""

    def test_resolve_pronoun_this_person(self) -> None:
        store = InMemoryEntityStore()
        mem = EntityMemory(store)
        session_id = 'sess-this-person'

        now = time.time()
        mem.set(session_id, NamedEntity(
            type=CANDIDATE,
            value='张三',
            source_turn_index=2,
            expires_at=now + 1800,
        ))

        resolved, trace = mem.resolve('这个人怎么样', session_id, now=now)
        assert '张三' in resolved
        assert '这个人' in trace['pronouns_found']


class TestResolveNoEntityReturnsOriginal:
    """When no entity is stored, pronouns should not be resolved."""

    def test_resolve_no_entity_returns_original(self) -> None:
        store = InMemoryEntityStore()
        mem = EntityMemory(store)
        session_id = 'sess-no-entity'

        now = time.time()
        resolved, trace = mem.resolve('他怎么样', session_id, now=now)
        # '他' is found as pronoun but cannot be replaced → stays in output
        assert resolved == '他怎么样'
        # pronouns_found contains '他' but substitution has replaced_with=None
        assert '他' in trace['pronouns_found']


class TestResolvePicksLatestEntity:
    """When multiple entities exist, resolve picks the one with the highest source_turn_index."""

    def test_resolve_picks_latest_entity(self) -> None:
        store = InMemoryEntityStore()
        mem = EntityMemory(store)
        session_id = 'sess-latest-entity'

        now = time.time()
        # Store two candidates; the later one should win
        mem.set(session_id, NamedEntity(
            type=CANDIDATE,
            value='旧候选人',
            source_turn_index=1,
            expires_at=now + 1800,
        ))
        mem.set(session_id, NamedEntity(
            type=CANDIDATE,
            value='新候选人',
            source_turn_index=5,
            expires_at=now + 1800,
        ))

        resolved, trace = mem.resolve('他怎么样', session_id, now=now)
        # '他' should be resolved to the latest candidate
        assert '新候选人' in resolved


# ===========================================================================
# 3. Fallback answer tests
# ===========================================================================


class TestFallbackPronounMessage:
    """Pronoun-containing messages should get a pronoun-specific fallback."""

    def test_fallback_pronoun_message(self) -> None:
        result = _fallback_answer('他的情况怎么样')
        assert '姓名' in result or '人员' in result

    def test_fallback_pronoun_she(self) -> None:
        result = _fallback_answer('她的简历')
        assert '姓名' in result or '人员' in result

    def test_fallback_pronoun_gai_candidate(self) -> None:
        result = _fallback_answer('该候选人怎么样')
        assert '姓名' in result or '人员' in result


class TestFallbackJobQuery:
    """Job-requirement queries should get a job-specific fallback."""

    def test_fallback_job_query(self) -> None:
        result = _fallback_answer('岗位要求是什么')
        assert '岗位' in result


class TestFallbackGeneral:
    """General messages should still get the original generic fallback."""

    def test_fallback_general(self) -> None:
        result = _fallback_answer('今天天气怎么样')
        # Should be the generic fallback (not pronoun or job specific)
        assert '我可以直接回答' in result or '私有数据' in result


# ===========================================================================
# 4. Entity persistence tests
# ===========================================================================


class TestPersistEntitiesFromWorkset:
    """Candidate entities from workset results should be written to entity_memory."""

    def test_persist_entities_from_workset(self) -> None:
        store = InMemoryEntityStore()
        mem = EntityMemory(store)
        session_id = 'sess-persist-workset'

        result = ExecutionResult(
            summary='查询结果',
            entities=[
                {'type': 'candidate', 'entity_id': 'c1', 'title': '吴明华'},
                {'type': 'job', 'entity_id': 'j1', 'title': '供应链总监'},
            ],
            worksets=[{
                'id': 'ws1',
                'items': [
                    {'entity_type': 'candidate', 'entity_id': 'c1', 'title': '吴明华'},
                    {'entity_type': 'job', 'entity_id': 'j1', 'title': '供应链总监'},
                ],
            }],
            session_id=session_id,
        )
        ctx = _ctx(session_id=session_id)

        with patch('services.assistant_core.legacy_orchestrator._entity_memory', mem):
            _persist_entities_to_memory('查一下候选人', result, ctx)

        # Candidate entity should be stored
        stored = store.load(session_id)
        candidate_entities = [e for e in stored if e.type == 'candidate']
        assert len(candidate_entities) >= 1
        assert candidate_entities[0].value == '吴明华'


class TestPersistEntitiesFromMessage:
    """Person names extracted from the message should be written to entity_memory."""

    def test_persist_entities_from_message(self) -> None:
        store = InMemoryEntityStore()
        mem = EntityMemory(store)
        session_id = 'sess-persist-msg'

        result = ExecutionResult(
            summary='查询结果',
            entities=[],
            worksets=[],
            session_id=session_id,
        )
        ctx = _ctx(session_id=session_id)

        # '吴明华的简历' contains a named subject that _extract_named_subject can pick up
        with patch('services.assistant_core.legacy_orchestrator._entity_memory', mem):
            _persist_entities_to_memory('吴明华的简历', result, ctx)

        stored = store.load(session_id)
        candidate_entities = [e for e in stored if e.type == 'candidate']
        assert len(candidate_entities) >= 1
        assert candidate_entities[0].value == '吴明华'
