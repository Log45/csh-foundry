"""Closed application format v1. Configuration is never executed as source code."""

import hashlib
import json
from datetime import datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from ontology_platform.queries.ast import AggregateRequest, QueryRequest, Sort

Id = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$", max_length=64)]
Scalar = str | int | float | bool | None


class ApplicationModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        allow_inf_nan=False,
        json_schema_serialization_defaults_required=True,
    )


class ApplicationValue(ApplicationModel):
    kind: Literal["literal", "state", "selected"] = "literal"
    value: Scalar = None
    state: Id | None = None
    property: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def shape(self) -> Self:
        if self.kind == "literal":
            if self.state or self.property:
                raise ValueError("Literal binding has no state or property")
        elif not self.state or self.value is not None:
            raise ValueError("ApplicationState bindings require a state ID and no literal")
        if self.property in {"__proto__", "prototype", "constructor"}:
            raise ValueError("Unsafe property")
        return self


class ApplicationState(ApplicationModel):
    id: Id
    data_type: Literal["string", "integer", "float", "boolean", "date", "selection"] = "string"
    initial: Scalar = None

    @model_validator(mode="after")
    def typed_initial(self) -> Self:
        if self.initial is None:
            return self
        expected: dict[str, type] = {
            "string": str,
            "date": str,
            "integer": int,
            "float": float,
            "boolean": bool,
        }
        if self.data_type == "selection" or type(self.initial) is not expected[self.data_type]:
            raise ValueError("ApplicationState initial value has incompatible type")
        return self


class ApplicationDependency(ApplicationModel):
    id: Id
    resource_id: UUID
    ontology_id: str = Field(min_length=1, max_length=200)
    schema_version: str = Field(min_length=1, max_length=200)
    policy: Literal["exact_active"] = "exact_active"


class ApplicationSourceQuery(QueryRequest):
    """Stored request configuration; preserve canonical query component identities."""

    model_config = ConfigDict(json_schema_mode_override="validation")


class ApplicationSourceAggregate(AggregateRequest):
    """Stored aggregate configuration."""

    model_config = ConfigDict(json_schema_mode_override="validation")


class ApplicationSource(ApplicationModel):
    id: Id
    dependency: Id
    kind: Literal["query", "aggregate"] = "query"
    query: ApplicationSourceQuery
    aggregate: ApplicationSourceAggregate | None = None
    filters: dict[str, ApplicationValue] = Field(default_factory=dict, max_length=16)

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if self.query.limit > 100 or self.query.cursor or self.query.offset:
            raise ValueError("Sources use pages of at most 100; runtime owns pagination")
        if (self.kind == "aggregate") != (self.aggregate is not None):
            raise ValueError("Aggregate source requires its canonical aggregate contract")
        return self


class ApplicationActionBinding(ApplicationModel):
    id: Id
    dependency: Id
    action_id: str = Field(min_length=1, max_length=200)
    parameters: dict[str, ApplicationValue] = Field(default_factory=dict, max_length=32)
    parameter_types: dict[str, str] = Field(default_factory=dict, max_length=32)
    confirm: bool = True
    refresh: list[Id] = Field(default_factory=list, max_length=16)


class ApplicationInteraction(ApplicationModel):
    id: Id
    widget: Id
    event: Literal["select", "change", "click"]
    kind: Literal["set", "navigate", "refresh"]
    target: Id


class ApplicationVisibility(ApplicationModel):
    state: Id
    operator: Literal["equals", "not_empty"] = "not_empty"
    value: Scalar = None


WidgetKind = Literal[
    "heading",
    "text",
    "label",
    "metric",
    "property",
    "detail",
    "table",
    "list",
    "status",
    "navigation",
    "section",
    "text_input",
    "number_input",
    "checkbox",
    "select",
    "date_input",
    "form",
    "action",
]


class ApplicationWidget(ApplicationModel):
    id: Id
    kind: WidgetKind
    label: str = Field(default="", max_length=200)
    text: str = Field(default="", max_length=4000)
    parent: Id | None = None
    layout: Literal["row", "column", "grid"] = "column"
    spacing: Literal["compact", "normal", "large"] = "normal"
    align: Literal["start", "center", "stretch"] = "stretch"
    source: Id | None = None
    state: Id | None = None
    property: str | None = Field(default=None, max_length=200)
    columns: list[str] = Field(default_factory=list, max_length=32)
    options: list[str] = Field(default_factory=list, max_length=100)
    page: Id | None = None
    action: Id | None = None
    visible: ApplicationVisibility | None = None


class ApplicationPage(ApplicationModel):
    id: Id
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    parameters: list[Id] = Field(default_factory=list, max_length=16)
    widgets: list[ApplicationWidget] = Field(default_factory=list, max_length=64)


class ApplicationDocument(ApplicationModel):
    format_version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    home: Id
    pages: list[ApplicationPage] = Field(default_factory=list, max_length=16)
    states: list[ApplicationState] = Field(default_factory=list, max_length=64)
    dependencies: list[ApplicationDependency] = Field(default_factory=list, max_length=16)
    sources: list[ApplicationSource] = Field(default_factory=list, max_length=16)
    actions: list[ApplicationActionBinding] = Field(default_factory=list, max_length=16)
    interactions: list[ApplicationInteraction] = Field(default_factory=list, max_length=128)

    @model_validator(mode="before")
    @classmethod
    def preflight(cls, value: Any) -> Any:
        if isinstance(value, dict):
            stack = [(value, 0)]
            while stack:
                item, depth = stack.pop()
                if depth > 24:
                    raise ValueError("ApplicationDocument nesting limit exceeded")
                if isinstance(item, dict):
                    if {"__proto__", "constructor", "prototype"} & item.keys():
                        raise ValueError("Unsafe document key")
                    stack.extend((v, depth + 1) for v in item.values())
                elif isinstance(item, (list, tuple)):
                    stack.extend((v, depth + 1) for v in item)
            if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > 60000:
                raise ValueError("Application document exceeds 60000 bytes")
        return value

    @model_validator(mode="after")
    def expanded_size(self) -> Self:
        if len(self.canonical().encode()) > 60000:
            raise ValueError("Expanded application document exceeds 60000 bytes")
        return self

    def canonical(self) -> str:
        return json.dumps(
            self.model_dump(mode="json", by_alias=True),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def digest(self) -> str:
        return hashlib.sha256(self.canonical().encode()).hexdigest()


class ApplicationDiagnostic(ApplicationModel):
    code: str
    message: str
    node: str | None = None


class ApplicationValidation(ApplicationModel):
    valid: bool
    diagnostics: list[ApplicationDiagnostic] = Field(default_factory=list, max_length=128)


class SaveApplicationDraft(ApplicationModel):
    expected_revision: int = Field(ge=0)
    document: ApplicationDocument


class ApplicationDraftView(ApplicationModel):
    revision: int
    document: ApplicationDocument


class PublishApplication(ApplicationModel):
    expected_revision: int = Field(ge=1)


class PublishedApplicationVersion(ApplicationModel):
    id: UUID
    application_id: UUID
    sequence: int
    format_version: Literal[1] = 1
    document: ApplicationDocument
    digest: str
    manifest: list[ApplicationDependency]
    created_by: str
    created_at: datetime


class ApplicationRuntimeQuery(ApplicationModel):
    source_id: Id
    state: dict[str, JsonValue] = Field(default_factory=dict, max_length=64)
    order_by: list[Sort] | None = Field(default=None, max_length=4)
    cursor: str | None = Field(default=None, max_length=16384)


def validate(document: ApplicationDocument) -> ApplicationValidation:
    errors: list[ApplicationDiagnostic] = []

    def fail(code: str, node: str | None = None) -> None:
        if len(errors) < 128:
            errors.append(
                ApplicationDiagnostic(code=code, message=code.replace("_", " "), node=node)
            )

    all_ids: set[str] = set()
    collections: list[Any] = [
        document.pages,
        document.states,
        document.dependencies,
        document.sources,
        document.actions,
        document.interactions,
        *[p.widgets for p in document.pages],
    ]
    for collection in collections:
        for item in collection:
            if item.id in all_ids:
                fail("duplicate_id", item.id)
            all_ids.add(item.id)
    pages = {p.id for p in document.pages}
    states = {s.id: s for s in document.states}
    sources = {s.id: s for s in document.sources}
    dependencies = {d.id for d in document.dependencies}
    actions = {a.id for a in document.actions}
    widgets = {w.id: w for p in document.pages for w in p.widgets}
    if document.home not in pages:
        fail("home_page_missing")
    if sum(len(p.widgets) for p in document.pages) > 256:
        fail("total_widget_limit")

    def binding(v: ApplicationValue, node: str) -> None:
        if v.kind != "literal" and v.state not in states:
            fail("state_reference_invalid", node)
        if v.kind == "selected" and (
            v.state not in states or states[v.state].data_type != "selection"
        ):
            fail("selection_binding_invalid", node)

    for source in document.sources:
        if source.dependency not in dependencies:
            fail("dependency_reference_invalid", source.id)
        for v in source.filters.values():
            binding(v, source.id)
    for action in document.actions:
        if action.dependency not in dependencies:
            fail("dependency_reference_invalid", action.id)
        if set(action.parameters) != set(action.parameter_types):
            fail("action_parameter_types_missing", action.id)
        for v in action.parameters.values():
            binding(v, action.id)
        if set(action.refresh) - sources.keys():
            fail("refresh_reference_invalid", action.id)
    for page in document.pages:
        local = {w.id: w for w in page.widgets}
        if set(page.parameters) - states.keys():
            fail("page_parameter_invalid", page.id)
        for w in page.widgets:
            common = {"id", "kind", "label", "parent", "visible"}
            catalog = {
                "heading": {"text"},
                "text": {"text"},
                "label": {"text"},
                "section": {"layout", "spacing", "align"},
                "form": {"layout", "spacing", "align"},
                "table": {"source", "state", "columns"},
                "list": {"source", "state", "columns"},
                "metric": {"source", "property"},
                "detail": {"state", "property"},
                "property": {"state", "property"},
                "status": {"state", "property"},
                "navigation": {"page"},
                "action": {"action"},
                "text_input": {"state"},
                "number_input": {"state"},
                "checkbox": {"state"},
                "date_input": {"state"},
                "select": {"state", "options"},
            }
            allowed = common | catalog[w.kind]
            for name, field in ApplicationWidget.model_fields.items():
                if name not in allowed and getattr(w, name) != field.get_default(
                    call_default_factory=True
                ):
                    fail("widget_configuration_incompatible", w.id)
            for value, options in [
                (w.source, set(sources)),
                (w.state, set(states)),
                (w.page, pages),
                (w.action, actions),
            ]:
                if value is not None and value not in options:
                    fail("widget_reference_invalid", w.id)
            input_types = {
                "text_input": {"string"},
                "date_input": {"date"},
                "number_input": {"integer", "float"},
                "checkbox": {"boolean"},
                "select": {"string"},
                "detail": {"selection"},
                "property": {"selection"},
                "status": {"selection"},
                "table": {"selection"},
                "list": {"selection"},
            }
            if w.state in states and w.kind in input_types:
                if states[w.state].data_type not in input_types[w.kind]:
                    fail("widget_state_type_invalid", w.id)
            if w.source in sources:
                source_kind = sources[w.source].kind
                if (w.kind == "metric" and source_kind != "aggregate") or (
                    w.kind in {"table", "list"} and source_kind != "query"
                ):
                    fail("widget_source_shape_invalid", w.id)
            if w.visible and w.visible.state not in states:
                fail("visibility_reference_invalid", w.id)
            if w.kind in {"table", "list", "metric"} and not w.source:
                fail("widget_source_required", w.id)
            if (
                w.kind
                in {
                    "text_input",
                    "number_input",
                    "checkbox",
                    "select",
                    "date_input",
                    "detail",
                    "property",
                    "status",
                }
                and not w.state
            ):
                fail("widget_state_required", w.id)
            if w.kind == "navigation" and not w.page or w.kind == "action" and not w.action:
                fail("widget_target_required", w.id)
            if w.parent and (
                w.parent not in local or local[w.parent].kind not in {"section", "form"}
            ):
                fail("layout_parent_invalid", w.id)
            seen = {w.id}
            parent = w.parent
            while parent and parent in local:
                if parent in seen or len(seen) >= 8:
                    fail("layout_cycle_or_depth", w.id)
                    break
                seen.add(parent)
                parent = local[parent].parent
    seen_events: set[tuple[str, str]] = set()
    for i in document.interactions:
        if (i.widget, i.event) in seen_events:
            fail("ambiguous_interaction", i.id)
        seen_events.add((i.widget, i.event))
        if i.widget not in widgets:
            fail("interaction_widget_invalid", i.id)
        targets = pages if i.kind == "navigate" else sources if i.kind == "refresh" else states
        if i.target not in targets:
            fail("interaction_target_invalid", i.id)
    # Events are only emitted by user gestures; applying state never emits another event.
    return ApplicationValidation(valid=not errors, diagnostics=errors)


# Module-local convenience aliases; public OpenAPI identities remain application-specific.
Model = ApplicationModel
Value = ApplicationValue
State = ApplicationState
Dependency = ApplicationDependency
SourceQuery = ApplicationSourceQuery
SourceAggregate = ApplicationSourceAggregate
Source = ApplicationSource
Action = ApplicationActionBinding
Interaction = ApplicationInteraction
Visibility = ApplicationVisibility
Widget = ApplicationWidget
Page = ApplicationPage
Document = ApplicationDocument
Diagnostic = ApplicationDiagnostic
Validation = ApplicationValidation
Save = SaveApplicationDraft
Draft = ApplicationDraftView
Publish = PublishApplication
Published = PublishedApplicationVersion
RuntimeQuery = ApplicationRuntimeQuery
