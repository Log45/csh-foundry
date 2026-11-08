"""Project-governed definitions, immutable input pins and authorized provenance."""

from typing import Any, cast
from uuid import UUID, uuid4

from ontology_schema.models import OntologyDefinition
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ontology_platform.branching.service import page
from ontology_platform.db.governance import missing
from ontology_platform.db.models import (
    ExecutionInput,
    ExecutionJob,
    MappingDefinition,
    MaterializationRecord,
    Version,
)
from ontology_platform.errors import ApplicationError
from ontology_platform.execution.config import ExecutionSettings
from ontology_platform.mappings.contracts import (
    MappingDefinitionView,
    MappingPreview,
    MappingRun,
    MappingSpec,
)
from ontology_platform.mappings.engine import encode, mapped
from ontology_platform.objects.relationships import link_type
from ontology_platform.objects.validation import object_type
from ontology_platform.pipelines.contracts import ExecutionJobView
from ontology_platform.pipelines.service import PipelineService
from ontology_platform.projects.service import conflict
from ontology_platform.security.interfaces import Principal


class MappingService(PipelineService):
    resource_kind = "MAPPING"

    def target(
        self, s: Session, p: Principal, spec: MappingSpec, write: bool = False
    ) -> OntologyDefinition:
        asset = self.resource(s, p, spec.target_resource_id)
        if (asset.resource_type, asset.ontology_id, asset.schema_version) != (
            "ONTOLOGY_VERSION",
            spec.ontology_id,
            spec.schema_version,
        ):
            raise conflict("Target must reference the pinned ontology version")
        if write:
            self.project(s, p, asset.project_id, write=True)
        self.authorizer.require(p, "schema:read", f"{p.tenant_id}/{spec.ontology_id}")
        root = self.ontology(s, p, spec.ontology_id, write=write)
        version = s.get(Version, (p.tenant_id, spec.ontology_id, spec.schema_version))
        if (
            version is None
            or version.status != "PUBLISHED"
            or root.active_version != spec.schema_version
        ):
            raise conflict("Mapping requires the exact active published schema")
        schema = OntologyDefinition.model_validate_json(version.definition_json)
        for item in spec.objects:
            typed = object_type(schema, item.object_type)
            props = {v.id: v for v in typed.properties}
            primary = props[typed.primary_key]
            if typed.primary_key in item.properties:
                raise conflict("Primary key is supplied exclusively by identity")
            if len(item.identity.components) > 1:
                if primary.data_type != "string":
                    raise conflict("Composite keys require string primary key")
            elif item.identity.components[0].conversion != primary.data_type:
                raise conflict("Identity conversion must match canonical primary key")
            for name, value in item.properties.items():
                prop = props.get(name)
                if (
                    prop is None
                    or prop.array
                    or prop.data_type != value.conversion
                    or (prop.precision is not None and prop.precision > 38)
                ):
                    raise conflict("Property or conversion is incompatible")
                if value.nulls == "allow" and not prop.nullable:
                    raise conflict("Property is not nullable")
                if value.column is None or value.nulls == "default":
                    from ontology_platform.mappings.conversion import evaluate

                    try:
                        prop.validate_value(
                            evaluate(
                                value, {value.column: None} if value.column is not None else {}
                            )
                        )
                    except ValueError as exc:
                        raise conflict("Invalid constant or default") from exc
            if any(
                v.required
                and v.id != typed.primary_key
                and v.id not in item.properties
                and not v.has_default
                and v.default is None
                for v in typed.properties
            ):
                raise conflict("Required property is unmapped")
            if write:
                for operation in (
                    "object:create",
                    "object:update",
                    "edit:reconcile",
                    "edit:initialize_source",
                ):
                    self.authorizer.require(
                        p, operation, f"{p.tenant_id}/{schema.id}/objects/{typed.id}"
                    )
                for property_id in (typed.primary_key, *item.properties):
                    self.authorizer.require(
                        p,
                        "property:update",
                        f"{p.tenant_id}/{schema.id}/objects/{typed.id}/properties/{property_id}",
                    )
        for relationship in spec.relationships:
            typed_link = link_type(schema, relationship.link_type)
            if (typed_link.source_type, typed_link.target_type) != (
                relationship.source.object_type,
                relationship.target.object_type,
            ):
                raise conflict("Link endpoints are incompatible")
            for endpoint in (relationship.source, relationship.target):
                typed = object_type(schema, endpoint.object_type)
                primary = next(v for v in typed.properties if v.id == typed.primary_key)
                if (len(endpoint.identity.components) > 1 and primary.data_type != "string") or (
                    len(endpoint.identity.components) == 1
                    and primary.data_type != endpoint.identity.components[0].conversion
                ):
                    raise conflict("Endpoint identity is incompatible")
            if write:
                self.authorizer.require(
                    p, "link:create", f"{p.tenant_id}/{schema.id}/links/{typed_link.id}"
                )
        # Scalar subset is explicit; reject nested, binary and unsupported temporal precision.
        allowed = {
            "String",
            "Int8",
            "Int16",
            "Int32",
            "Int64",
            "UInt8",
            "UInt16",
            "UInt32",
            "UInt64",
            "Float32",
            "Float64",
            "Boolean",
            "Date",
            "Null",
        }
        if any(
            t not in allowed
            and not t.startswith(("Decimal(", "Datetime(time_unit='us'", "Datetime(time_unit='ms'"))
            for t in spec.columns.values()
        ):
            raise conflict("Unsupported source logical type")
        return schema

    def definition(self, s: Session, p: Principal, key: UUID, version: UUID) -> MappingDefinition:  # type: ignore[override]
        self.artifact(s, p, key)
        row = s.get(MappingDefinition, (p.tenant_id, key, version))
        if row is None:
            raise missing("Mapping definition")
        return row

    def publish(self, p: Principal, key: UUID, spec: MappingSpec) -> MappingDefinitionView:  # type: ignore[override]
        if p.authentication_method == "job":
            raise ApplicationError(
                "forbidden", "Job grants do not authorize definition changes", 403
            )
        with self.scope(p) as s:
            self.artifact(s, p, key, True)
            self.target(s, p, spec, True)
            sequence = (
                s.scalar(
                    select(func.max(MappingDefinition.sequence)).where(
                        MappingDefinition.tenant_id == p.tenant_id,
                        MappingDefinition.mapping_id == key,
                    )
                )
                or 0
            )
            row = MappingDefinition(
                tenant_id=p.tenant_id,
                mapping_id=key,
                id=uuid4(),
                sequence=sequence + 1,
                target_resource_id=spec.target_resource_id,
                ontology_id=spec.ontology_id,
                schema_version=spec.schema_version,
                specification=spec.model_dump(mode="json"),
                created_by=p.principal_id,
            )
            s.add(row)
            s.flush()
            self.audit(s, p, "mapping_publish", row.id)
            return MappingDefinitionView.model_validate(row)

    def definitions(  # type: ignore[override]
        self, p: Principal, key: UUID, limit: int = 50, offset: int = 0
    ) -> list[MappingDefinitionView]:
        page(limit, offset)
        with self.scope(p) as s:
            self.artifact(s, p, key)
            return [
                MappingDefinitionView.model_validate(r)
                for r in s.scalars(
                    select(MappingDefinition)
                    .where(
                        MappingDefinition.tenant_id == p.tenant_id,
                        MappingDefinition.mapping_id == key,
                    )
                    .order_by(MappingDefinition.sequence.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ]

    def inputs(
        self, s: Session, p: Principal, body: MappingRun | MappingPreview, spec: MappingSpec
    ) -> tuple[Any, Any]:
        datasets = self.datasets()
        datasets.artifact(s, p, body.dataset_id)
        logical = datasets.record(s, p, body.dataset_id, body.version_id)
        physical = datasets.version(s, p, body.dataset_id, body.version_id)
        if logical.state != "COMMITTED" or physical.state != "COMMITTED":
            raise conflict("Source must be committed")
        columns = {
            v["name"]: v["logical_type"]
            for v in cast(list[dict[str, Any]], logical.result["schema"])
        }
        if any(columns.get(name) != dtype for name, dtype in spec.columns.items()):
            raise conflict("Source schema contract mismatch")
        return logical, physical

    def preview(self, p: Principal, key: UUID, body: MappingRun | MappingPreview) -> dict[str, Any]:
        with self.scope(p) as s:
            self.artifact(s, p, key)
            if isinstance(body, MappingRun):
                definition = self.definition(s, p, key, body.definition_id)
                spec = MappingSpec.model_validate(definition.specification)
            else:
                spec = body.specification
            schema = self.target(s, p, spec)
            logical, _ = self.inputs(s, p, body, spec)
            columns = cast(list[dict[str, Any]], logical.result["schema"])
            values: list[dict[str, Any]] = []
            errors = []
            for index, row in enumerate(cast(list[list[Any]], logical.result["preview"])[:20]):
                try:
                    for value in mapped(
                        spec, schema, dict(zip([v["name"] for v in columns], row, strict=True))
                    ):
                        if len(values) < 20 and len(encode(values + [value]).encode()) <= 65536:
                            values.append(value)
                except (ValueError, ApplicationError):
                    errors.append({"record": index + 1, "code": "invalid_mapping_record"})
            return {
                "validation": "sample-only",
                "full_source_validated": False,
                "preview": values[:20],
                "diagnostics": errors,
            }

    def start(self, p: Principal, key: UUID, body: MappingRun) -> ExecutionJobView:  # type: ignore[override]
        with self.scope(p) as s:
            resource = self.artifact(s, p, key, True)
            definition = self.definition(s, p, key, body.definition_id)
            spec = MappingSpec.model_validate(definition.specification)
            self.target(s, p, spec, True)
            logical, physical = self.inputs(s, p, body, spec)
            limits = ExecutionSettings()
            self.capacity(s, p, limits)
            job = ExecutionJob(
                tenant_id=p.tenant_id,
                id=uuid4(),
                resource_id=key,
                project_id=resource.project_id,
                kind="MATERIALIZATION",
                mapping_definition_id=definition.id,
                request=body.model_dump(mode="json") | {"schema": logical.result["schema"]},
                principal=p.model_dump(mode="json"),
                limits=limits.model_dump(mode="json"),
            )
            s.add(job)
            s.flush()
            s.add(
                ExecutionInput(
                    tenant_id=p.tenant_id,
                    job_id=job.id,
                    name="source",
                    dataset_id=body.dataset_id,
                    version_id=body.version_id,
                    checksum=physical.checksum,
                )
            )
            from ontology_platform.security.job_grants import create as create_job_grant

            create_job_grant(s, self.authorizer, p, job)
            self.audit(s, p, "mapping_run_queue", job.id)
            return ExecutionJobView.model_validate(job)

    def provenance(
        self, p: Principal, key: UUID, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        page(limit, offset)
        with self.scope(p) as s:
            job = self.job(s, p, key)
            if job.kind != "MATERIALIZATION" or job.mapping_definition_id is None:
                raise missing("Materialization")
            definition = self.definition(s, p, job.resource_id, job.mapping_definition_id)
            spec = MappingSpec.model_validate(definition.specification)
            self.resource(s, p, spec.target_resource_id)
            self.authorizer.require(p, "schema:read", f"{p.tenant_id}/{spec.ontology_id}")
            source = s.get(ExecutionInput, (p.tenant_id, key, "source"))
            assert source is not None
            self.datasets().record(s, p, source.dataset_id, source.version_id)
            from ontology_platform.objects.service import ObjectService

            objects = ObjectService(self.sessions, self.authorizer, session=s)
            result = []
            for row in s.scalars(
                select(MaterializationRecord)
                .where(
                    MaterializationRecord.tenant_id == p.tenant_id,
                    MaterializationRecord.run_id == key,
                )
                .order_by(MaterializationRecord.target_key)
                .limit(limit)
                .offset(offset)
            ):
                target = row.target
                try:
                    if target["kind"] == "object":
                        objects.get(p, spec.ontology_id, str(target["type"]), str(target["id"]))
                    else:
                        self.authorizer.require(
                            p,
                            "link:read",
                            f"{p.tenant_id}/{spec.ontology_id}/links/{target['link_type']}",
                        )
                        objects.get(
                            p,
                            spec.ontology_id,
                            str(target["source_type"]),
                            str(target["source_id"]),
                        )
                        objects.get(
                            p,
                            spec.ontology_id,
                            str(target["target_type"]),
                            str(target["target_id"]),
                        )
                except ApplicationError as exc:
                    if exc.status_code in {403, 404}:
                        continue
                    raise
                result.append(
                    {
                        "run_id": str(key),
                        "mapping_id": str(job.resource_id),
                        "definition_id": str(definition.id),
                        "dataset_id": str(source.dataset_id),
                        "version_id": str(source.version_id),
                        "artifact_version_id": str(source.version_id),
                        "checksum": source.checksum,
                        "ontology_id": spec.ontology_id,
                        "schema_version": spec.schema_version,
                        "source_record": row.source_record,
                        "target": target,
                        "operation": row.operation,
                        "created_at": row.created_at.isoformat(),
                        "principal_id": job.principal["principal_id"],
                        "run_state": job.state,
                    }
                )
            return result

    def source_runs(
        self, p: Principal, dataset: UUID, version: UUID, limit: int, offset: int
    ) -> list[ExecutionJobView]:
        page(limit, offset)
        with self.scope(p) as s:
            self.datasets().record(s, p, dataset, version)
            result = []
            for job in s.scalars(
                select(ExecutionJob)
                .join(
                    ExecutionInput,
                    (ExecutionInput.tenant_id == ExecutionJob.tenant_id)
                    & (ExecutionInput.job_id == ExecutionJob.id),
                )
                .where(
                    ExecutionJob.tenant_id == p.tenant_id,
                    ExecutionJob.kind == "MATERIALIZATION",
                    ExecutionInput.dataset_id == dataset,
                    ExecutionInput.version_id == version,
                )
                .order_by(ExecutionJob.created_at.desc(), ExecutionJob.id)
                .limit(limit)
                .offset(offset)
            ):
                try:
                    self.artifact(s, p, job.resource_id)
                except ApplicationError as exc:
                    if exc.status_code in {403, 404}:
                        continue
                    raise
                result.append(ExecutionJobView.model_validate(job))
            return result

    def target_runs(
        self, p: Principal, ontology: str, target: dict[str, str], limit: int, offset: int
    ) -> list[dict[str, Any]]:
        page(limit, offset)
        with self.scope(p) as s:
            from ontology_platform.objects.service import ObjectService

            objects = ObjectService(self.sessions, self.authorizer, session=s)
            if target["kind"] == "object":
                objects.get(p, ontology, target["type"], target["id"])
            else:
                self.authorizer.require(
                    p, "link:read", f"{p.tenant_id}/{ontology}/links/{target['link_type']}"
                )
                objects.get(p, ontology, target["source_type"], target["source_id"])
                objects.get(p, ontology, target["target_type"], target["target_id"])
            result = []
            for job in s.scalars(
                select(ExecutionJob)
                .join(
                    MaterializationRecord,
                    (MaterializationRecord.tenant_id == ExecutionJob.tenant_id)
                    & (MaterializationRecord.run_id == ExecutionJob.id),
                )
                .join(
                    MappingDefinition,
                    (MappingDefinition.tenant_id == ExecutionJob.tenant_id)
                    & (MappingDefinition.mapping_id == ExecutionJob.resource_id)
                    & (MappingDefinition.id == ExecutionJob.mapping_definition_id),
                )
                .where(
                    ExecutionJob.tenant_id == p.tenant_id,
                    MappingDefinition.ontology_id == ontology,
                    MaterializationRecord.target.contains(target),
                )
                .order_by(ExecutionJob.created_at.desc(), ExecutionJob.id)
                .limit(limit)
                .offset(offset)
            ):
                try:
                    self.artifact(s, p, job.resource_id)
                    definition = self.definition(s, p, job.resource_id, job.mapping_definition_id)  # type: ignore[arg-type]
                    self.resource(s, p, definition.target_resource_id)
                    source = s.get(ExecutionInput, (p.tenant_id, job.id, "source"))
                    assert source is not None
                    self.datasets().record(s, p, source.dataset_id, source.version_id)
                except ApplicationError as exc:
                    if exc.status_code in {403, 404}:
                        continue
                    raise
                result.append(
                    {
                        "run_id": str(job.id),
                        "mapping_id": str(job.resource_id),
                        "definition_id": str(definition.id),
                        "dataset_id": str(source.dataset_id),
                        "version_id": str(source.version_id),
                        "checksum": source.checksum,
                        "state": job.state,
                    }
                )
            return result
