from typing import Any

from retrostore.inventory import datastore_source


class FakeDatastoreEntity(dict[str, object]):
    def __init__(self, key: object, **properties: object) -> None:
        super().__init__(properties)
        self.key = key


class FakeQuery:
    def __init__(self, entities: list[FakeDatastoreEntity]) -> None:
        self._entities = entities

    def fetch(self) -> list[FakeDatastoreEntity]:
        return self._entities


class FakeClient:
    def __init__(self, entities: list[FakeDatastoreEntity]) -> None:
        self._entities = entities
        self.queried_kind: str | None = None

    def query(self, *, kind: str) -> FakeQuery:
        self.queried_kind = kind
        return FakeQuery(self._entities)


def test_source_exposes_queries_but_no_mutation_methods() -> None:
    client = FakeClient([FakeDatastoreEntity(123, name="value")])
    source = datastore_source.DatastoreSource(client)  # type: ignore[arg-type]

    entities = list(source.fetch_kind("Author"))

    assert client.queried_kind == "Author"
    assert entities[0].kind == "Author"
    assert entities[0].key == 123
    assert entities[0].properties == {"name": "value"}
    assert not hasattr(source, "put")
    assert not hasattr(source, "delete")


def test_default_database_label_is_translated_for_client(monkeypatch: Any) -> None:
    captured: dict[str, object] = {}

    def fake_client(**kwargs: object) -> FakeClient:
        captured.update(kwargs)
        return FakeClient([])

    monkeypatch.setattr(datastore_source.datastore, "Client", fake_client)

    datastore_source.create_datastore_source(
        project="test-project", database="(default)", auth="adc"
    )

    assert captured["project"] == "test-project"
    assert captured["database"] == ""
    assert captured["credentials"] is None


def test_named_database_is_passed_through(monkeypatch: Any) -> None:
    captured: dict[str, object] = {}

    def fake_client(**kwargs: object) -> FakeClient:
        captured.update(kwargs)
        return FakeClient([])

    monkeypatch.setattr(datastore_source.datastore, "Client", fake_client)

    datastore_source.create_datastore_source(
        project="test-project", database="retrostore", auth="adc"
    )

    assert captured["database"] == "retrostore"
