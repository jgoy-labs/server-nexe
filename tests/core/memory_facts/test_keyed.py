"""pla-memoria-fiable, F-C: the change of a fact is found by its key, not by closeness."""
import json
from types import SimpleNamespace

import pytest

from core.memory_facts import intents, keyed
from core.memory_facts.keyed import KeyedFact

pytestmark = pytest.mark.asyncio


def _fact(attribute="age", value="46", statement="L'usuari té 46 anys", intent="set", entity="user"):
    return KeyedFact(entity, attribute, value, statement, intent)


class FakeMemory:
    def __init__(self, rows):
        self.rows = rows

    async def collection_exists(self, name):
        return True

    async def scroll(self, collection, limit=50, offset=None):
        return [SimpleNamespace(id=i, payload=r) for i, r in enumerate(self.rows)], None


class FakePort:
    def __init__(self, rows=(), save_result=None):
        self.memory = FakeMemory(list(rows))
        self.saved = []
        self.save_result = save_result or {"success": True, "document_id": "doc"}

    async def get_memory_api(self):
        return self.memory

    async def save_to_memory(self, content, session_id, metadata=None, collections=None, force=False):
        self.saved.append((content, metadata))
        self.forced = getattr(self, "forced", []) + [force]
        return dict(self.save_result)


def _session():
    return SimpleNamespace(id="s1", _pending_replace=None)


def _row(text, attribute, value_norm, entity="user"):
    return {"text": text, "entity": entity, "attribute": attribute, "value_norm": value_norm}


class TestParse:
    def test_reads_the_facts(self):
        raw = json.dumps({"facts": [{"entity": "user", "attribute": "age", "value": "46",
                                      "statement": "L'usuari té 46 anys", "intent": "change"}]})
        facts = keyed.parse(raw)
        assert len(facts) == 1 and facts[0].intent == "change" and facts[0].value == "46"

    def test_thinking_and_fences_are_ignored(self):
        raw = '<think>hmm {"x":1}</think>```json\n{"facts": []}\n```'
        assert keyed.parse(raw) == []

    @pytest.mark.parametrize("raw", ["", "no json here", '{"facts": "nope"}', "[1,2]", '{"facts": [1}'])
    def test_what_is_not_the_json_asked_for_is_none(self, raw):
        assert keyed.parse(raw) is None

    def test_an_unknown_intent_is_a_plain_set(self):
        raw = json.dumps({"facts": [{"attribute": "age", "value": "1", "statement": "x" * 6, "intent": "weird"}]})
        assert keyed.parse(raw)[0].intent == "set"


class TestGrounded:
    def test_a_value_the_user_never_wrote_is_dropped(self):
        assert keyed.grounded([_fact(value="99")], "Tinc 46 anys") == []

    def test_a_value_in_the_message_stays_even_with_other_accents_and_case(self):
        fact = _fact(attribute="pets", value="BRUC", statement="El gos de l'usuari es diu Bruc")
        assert keyed.grounded([fact], "Ara el meu gos es diu Bruc.") == [fact]

    def test_a_value_with_a_word_of_the_message_around_it_is_still_the_users(self):
        fact = _fact(attribute="pets", value="gos Tro", statement="El gos de l'usuari es diu Tro")
        assert keyed.grounded([fact], "El meu gos es diu Tro.") == [fact]

    def test_a_value_with_a_word_the_user_never_wrote_is_an_invention(self):
        fact = _fact(attribute="pets", value="Bruc abans Rex", statement="El gos de l'usuari es diu Bruc")
        assert keyed.grounded([fact], "Ara el meu gos es diu Bruc.") == []

    def test_a_delete_needs_no_value(self):
        fact = _fact(attribute="phone", value="", statement="", intent="delete")
        assert keyed.grounded([fact], "Oblida el meu telèfon") == [fact]

    def test_a_fact_without_a_sentence_or_attribute_is_dropped(self):
        assert keyed.grounded([_fact(statement="")], "Tinc 46 anys") == []
        assert keyed.grounded([_fact(attribute="")], "Tinc 46 anys") == []


class TestKey:
    @pytest.mark.parametrize("word", ["age", "edat", "edad", "Age", "years"])
    def test_the_same_thing_in_any_language_is_one_key(self, word):
        assert _fact(attribute=word).key == ("user", "age")

    def test_phone_in_three_languages(self):
        assert {_fact(attribute=w).key for w in ("phone", "telèfon", "teléfono", "mòbil")} == {("user", "phone")}

    def test_the_speaker_is_user(self):
        assert _fact(entity="I").key[0] == "user" and _fact(entity="usuari").key[0] == "user"
        assert _fact(entity="sister").key[0] == "sister"

    def test_an_unknown_attribute_keeps_its_own_slug(self):
        assert _fact(attribute="Favourite colour").key == ("user", "favourite_colour")

    def test_pets_hold_several_values(self):
        assert _fact(attribute="dog").multi is True and _fact(attribute="age").multi is False

    def test_the_value_is_compared_without_accents_or_spaces(self):
        assert _fact(value="600 111-222").value_norm == "600111222"
        assert _fact(value="Girona").value_norm == _fact(value="  girona ").value_norm


class TestComparable:
    @pytest.mark.parametrize("value", ["45", "45 anys", "45 years", "45 años", " 45 "])
    def test_a_number_is_the_number_whatever_its_unit(self, value):
        assert _fact(value=value).value_norm == "45"

    def test_a_phone_is_its_digits(self):
        assert _fact(value="+34 600 111 222").value_norm == "34600111222"
        assert _fact(value="600111222").value_norm == "600111222"

    def test_an_email_or_a_name_is_not_collapsed_to_its_digits(self):
        assert _fact(value="jordi2@example.com").value_norm != _fact(value="anna2@example.com").value_norm
        assert _fact(value="Tro").value_norm == "tro"

    def test_the_grounding_still_reads_the_raw_value(self):
        assert keyed.grounded([_fact(value="45 anys")], "Tinc 45 anys.")


class TestPetEntities:
    @pytest.mark.parametrize("entity,attribute", [("dog", "name"), ("gos", "nom"), ("perro", "name"), ("cat", "")])
    def test_the_name_of_a_pet_is_a_value_of_the_users_pets(self, entity, attribute):
        assert _fact(entity=entity, attribute=attribute).key == ("user", "pets")

    @pytest.mark.parametrize("attribute", ["dog_name", "pet_name_current", "name_of_dog", "gos_nom"])
    def test_a_name_written_in_words_around_pet_is_still_the_pets(self, attribute):
        assert _fact(attribute=attribute).key == ("user", "pets")

    def test_its_age_is_another_fact(self):
        assert _fact(entity="dog", attribute="age").key == ("dog", "age")


class TestKnownHint:
    def test_the_names_in_use_reach_the_prompt(self):
        hint = keyed.known_hint([{"entity": "user", "attribute": "pets", "value": "Tro"},
                                 {"entity": "user", "attribute": "age", "value": ""}])
        assert "user.pets = Tro" in hint and "user.age" in hint and "same name" in hint

    def test_nothing_known_adds_nothing(self):
        assert keyed.known_hint([]) == ""


class TestApply:
    async def test_a_new_key_is_saved_with_its_key(self):
        port, session = FakePort(), _session()
        out = await keyed.apply([_fact()], session, port)
        assert out.handled and out.saved == 1 and out.kept == ["L'usuari té 46 anys"]
        meta = port.saved[0][1]
        assert (meta["entity"], meta["attribute"], meta["value_norm"], meta["cardinality"]) == ("user", "age", "46", "single")
        assert session._pending_replace is None

    async def test_the_same_value_is_nothing_even_in_another_language(self):
        port = FakePort([_row("User is 46 years old", "age", "46")])
        out = await keyed.apply([_fact(statement="L'usuari té 46 anys")], _session(), port)
        assert port.saved == [] and out.saved == 0 and out.kept == ["User is 46 years old"]

    async def test_another_value_arms_a_change_and_saves_nothing(self):
        port, session = FakePort([_row("User is 45 years old", "age", "45")]), _session()
        out = await keyed.apply([_fact()], session, port)
        assert port.saved == [] and out.saved == 0
        assert session._pending_replace["old"] == "User is 45 years old"
        assert session._pending_replace["new"] == "L'usuari té 46 anys"
        assert session._pending_replace["keyed"]["attribute"] == "age"

    async def test_the_dog_that_embeddings_could_not_tell(self):
        port, session = FakePort([_row("El meu gos es diu Tro", "pets", "tro")]), _session()
        fact = _fact(attribute="dog", value="Bruc", statement="El gos de l'usuari es diu Bruc")
        await keyed.apply([fact], session, port)
        assert session._pending_replace["old"] == "El meu gos es diu Tro" and port.saved == []

    async def test_another_entity_is_another_key(self):
        port = FakePort([_row("La meva germana té 30 anys", "age", "30", entity="sister")])
        out = await keyed.apply([_fact(value="46")], _session(), port)
        assert out.saved == 1

    async def test_a_fact_saved_before_keys_existed_falls_back_to_closeness(self):
        port = FakePort(save_result={"success": False, "duplicate": True, "same": False,
                                     "similar_to": "User is 45 years old"})
        session = _session()
        out = await keyed.apply([_fact()], session, port)
        assert out.saved == 0 and session._pending_replace["old"] == "User is 45 years old"

    async def test_a_duplicate_of_the_same_text_is_kept_not_asked(self):
        port = FakePort(save_result={"success": False, "duplicate": True, "same": True})
        session = _session()
        out = await keyed.apply([_fact()], session, port)
        assert out.kept == ["L'usuari té 46 anys"] and session._pending_replace is None

    async def test_a_delete_is_left_to_its_own_conversation(self):
        port, session = FakePort([_row("Phone 1", "phone", "1")]), _session()
        out = await keyed.apply([_fact(attribute="phone", value="", statement="", intent="delete")], session, port)
        assert port.saved == [] and session._pending_replace is None and out.handled


class TestReplaceKeepsTheKey:
    async def test_the_yes_saves_the_new_fact_with_its_key(self):
        class Port(FakePort):
            async def preview_delete_from_memory(self, content, collections=None):
                return {"success": True, "candidates": [{"id": "1", "text": content}]}

            async def delete_memory_entries(self, entries):
                return {"success": True, "deleted": 1}

        port, session = Port(), _session()
        session._pending_replace = {"old": "User is 45 years old", "new": "L'usuari té 46 anys",
                                    "keyed": _fact().metadata()}
        out = await intents._replace_confirm(session, port)
        assert out.mem_saved == 1
        assert port.saved[0][1]["attribute"] == "age" and port.saved[0][1]["value_norm"] == "46"


class TestOnePendingAtATime:
    """Review 19/10, finding 1: a yes meant for one question must never reach another."""

    class Port:
        def detect_intent(self, message):
            return "chat", None

        def matches_clear_all_confirm(self, message):
            return message.strip().lower() in {"sí", "si", "yes"}

    def _session(self):
        return SimpleNamespace(id="s", _pending_clear_all=False, _pending_partial_delete={"content": "x", "entries": []},
                               _pending_replace={"old": "a", "new": "b"})

    @pytest.mark.parametrize("answer", ["no", "sí"])
    def test_whichever_is_answered_the_others_are_dropped(self, answer):
        session = self._session()
        intent, _ = intents.detect_with_pending(session, answer, self.Port())
        assert session._pending_replace is None
        assert intent == ("delete_confirm" if answer == "sí" else "chat")

    def test_a_yes_to_the_change_alone_confirms_it(self):
        session = self._session()
        session._pending_partial_delete = None
        assert intents.detect_with_pending(session, "sí", self.Port())[0] == "replace_confirm"
        assert session._pending_replace == {"old": "a", "new": "b"}

    def test_nothing_pending_changes_nothing(self):
        session = SimpleNamespace(id="s")
        assert intents.detect_with_pending(session, "sí", self.Port())[0] == "chat"


class TestSeveralChangesInOneMessage:
    """Finding 3: the second change used to overwrite the first."""

    async def test_both_wait_for_one_yes(self):
        port, session = FakePort([_row("User is 45 years old", "age", "45"), _row("Viu a Vic", "location", "vic")]), _session()
        facts = [_fact(), _fact(attribute="city", value="Girona", statement="L'usuari viu a Girona")]
        await keyed.apply(facts, session, port)
        pending = session._pending_replace
        assert pending["old"] == "User is 45 years old" and pending["more"][0]["old"] == "Viu a Vic"

    def test_one_question_names_them_all(self):
        session = _session()
        intents.arm_replace(session, "A", "A2")
        intents.arm_replace(session, "B", "B2")
        question = intents.replace_question(session, accompany=True, lang="en")
        assert "«A» → «A2»" in question and "«B» → «B2»" in question and "yes" in question

    async def test_one_yes_does_them_all(self):
        class Port(FakePort):
            removed = []

            async def preview_delete_from_memory(self, content, collections=None):
                return {"success": True, "candidates": [{"id": content, "text": content}]}

            async def delete_memory_entries(self, entries):
                self.removed += [e["text"] for e in entries]
                return {"success": True, "deleted": 1}

        port, session = Port(), _session()
        intents.arm_replace(session, "A", "A2", {"type": "user_fact", "attribute": "a"})
        intents.arm_replace(session, "B", "B2")
        out = await intents._replace_confirm(session, port)
        assert port.removed == ["A", "B"] and out.mem_saved == 2 and out.mem_deleted == 2
        assert [s[0] for s in port.saved] == ["A2", "B2"] and port.forced == [True, True]

    async def test_a_new_fact_that_was_refused_is_not_called_done(self):
        class Port(FakePort):
            async def preview_delete_from_memory(self, content, collections=None):
                return {"success": True, "candidates": [{"id": "1", "text": content}]}

            async def delete_memory_entries(self, entries):
                return {"success": True, "deleted": 1}

        port = Port(save_result={"success": False, "document_id": None})
        session = _session()
        intents.arm_replace(session, "A", "A2")
        out = await intents._replace_confirm(session, port)
        assert out.mem_saved == 0 and "A2" in out.text and "Done" not in out.text and "canviat" not in out.text


class TestTwoFactsOfOneMessage:
    """Finding 4: the memory is read once, so the facts of a message do not meet each other."""

    async def test_a_dog_and_a_cat_are_both_saved(self):
        port = FakePort()
        facts = [_fact(attribute="pets", value="Tro", statement="L'usuari té un gos que es diu Tro"),
                 _fact(attribute="pets", value="Mixa", statement="L'usuari té una gata que es diu Mixa")]
        session = _session()
        out = await keyed.apply(facts, session, port)
        assert out.saved == 2 and session._pending_replace is None

    async def test_the_age_of_the_dog_is_not_its_name(self):
        port = FakePort([_row("El gos es diu Tro", "pets", "tro")])
        out = await keyed.apply([_fact(entity="dog", attribute="age", value="3", statement="El gos té 3 anys")], _session(), port)
        assert out.saved == 1


class TestTheCloseFactCarriesAnotherKey:
    """Finding 5: closeness proves nothing when the key says otherwise."""

    async def test_the_sisters_age_is_not_the_users(self):
        class Port(FakePort):
            def __init__(self):
                super().__init__([_row("La germana de l'usuari té 45 anys", "age", "45", entity="sister")])
                self.calls = 0

            async def save_to_memory(self, content, session_id, metadata=None, collections=None, force=False):
                self.calls += 1
                self.saved.append((content, metadata))
                if not force:
                    return {"success": False, "duplicate": True, "same": False,
                            "similar_to": "La germana de l'usuari té 45 anys"}
                return {"success": True, "document_id": "d"}

        port, session = Port(), _session()
        out = await keyed.apply([_fact(value="46")], session, port)
        assert out.saved == 1 and port.calls == 2 and session._pending_replace is None

    async def test_an_unkeyed_old_fact_still_arms_by_closeness(self):
        port = FakePort(save_result={"success": False, "duplicate": True, "same": False, "similar_to": "User is 45 years old"})
        session = _session()
        await keyed.apply([_fact()], session, port)
        assert session._pending_replace["old"] == "User is 45 years old"


class TestUncovered:
    def test_the_tag_a_fact_accounts_for_is_dropped_and_the_other_stays(self):
        facts = [_fact(value="Jordi", attribute="name", statement="L'usuari es diu Jordi")]
        tags = ["L'usuari es diu Jordi", "L'usuari té 46 anys"]
        assert keyed.uncovered(tags, facts) == ["L'usuari té 46 anys"]

    def test_a_number_is_found_whatever_the_sentence(self):
        assert keyed.uncovered(["User is 46 years old"], [_fact(value="46 anys")]) == []

    def test_no_facts_covers_nothing(self):
        assert keyed.uncovered(["x" * 6], []) == ["x" * 6]


class TestWhatTheEngineIsAsked:
    def test_an_in_process_engine_gets_the_system_prompt_apart(self):
        import inspect

        async def chat(messages, system="", session_id="default", stream_callback=None, **kwargs):
            ...

        kwargs = keyed._call_kwargs(inspect.signature(chat), "SYS", "hello there")
        assert kwargs["system"] == "SYS" and kwargs["messages"] == [{"role": "user", "content": "hello there"}]
        assert kwargs["session_id"] == "memory-extract" and "response_schema" not in kwargs

    def test_ollama_gets_the_shape_and_the_model(self):
        import inspect

        def chat(model, messages, stream=True, images=None, thinking_enabled=False, response_schema=None):
            ...

        kwargs = keyed._call_kwargs(inspect.signature(chat), "SYS", "hello there")
        assert kwargs["response_schema"] is keyed.EXTRACT_SCHEMA and "model" in kwargs
        assert kwargs["messages"][0] == {"role": "system", "content": "SYS"}

    async def test_a_coroutine_reply_is_read_too(self):
        async def reply():
            return {"response": '{"facts": []}'}

        assert "facts" in await keyed._drain(reply())
