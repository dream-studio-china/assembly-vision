"""Metadata governance routes (C5): products, components, rules, models.

Organization-scoped list/create/draft/publish endpoints over immutable
versions. Published versions are never updated or deleted; changes create a
higher version. A published central version is registered metadata only and
never implies a device downloaded, validated, or activated the content.
Every mutation requires an idempotency key (create/draft) or returns the
already-published resource (publish) and writes an immutable audit event in
the same transaction.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response

from central_service.api.deps import (
    NOT_FOUND_RESPONSES,
    SECURITY,
    UNAUTHENTICATED_RESPONSES,
    _require_admin,
    get_repository,
)
from central_service.api.problems import ApiProblem
from central_service.api.schemas import (
    ArtifactOut,
    ComponentCreate,
    ComponentOut,
    ComponentPage,
    DatasetOut,
    DesiredConfigurationOut,
    MetricOut,
    ModelCreate,
    ModelDetailOut,
    ModelManifestIn,
    ModelPackageOut,
    ModelPage,
    ModelSummaryOut,
    ModelVersionOut,
    ProductCreate,
    ProductDetailOut,
    ProductOut,
    ProductPage,
    ProductSummaryOut,
    ProductVersionComponentOut,
    ProductVersionCreate,
    ProductVersionOut,
    PublishRequest,
    RuleCreate,
    RuleDetailOut,
    RuleOut,
    RulePage,
    RulePolicyIn,
    RulePolicyOut,
    RuleSummaryOut,
    RuleVersionCreate,
    RuleVersionOut,
)
from central_service.persistence.repository import (
    AdministratorRow,
    AmbiguousBarcodeError,
    CentralRepository,
    DesiredConfigurationRow,
    IdempotencyConflictError,
    IncompatibleVersionError,
    InvalidComponentError,
    InvalidManifestError,
    InvalidPolicyError,
    MetadataCodeExistsError,
    MetadataVersionConflictError,
    MetadataVersionNotFoundError,
    ModelNotFoundError,
    ModelPackageRow,
    ModelVersionRow,
    ProductComponentInput,
    ProductDetailRow,
    ProductNotFoundError,
    ProductRow,
    ProductVersionRow,
    RevisionMismatchError,
    RuleDetailRow,
    RuleNotFoundError,
    RulePolicyInput,
    RuleRow,
    RuleVersionRow,
)

router = APIRouter(tags=["metadata"])

_MAX_IDEMPOTENCY_KEY_LEN = 256

# Error type -> (HTTP status, problem code). Errors that name a stable
# resource (product/rule/model) carry a specific 404 code; version_id
# lookups share VERSION_NOT_FOUND.
_METADATA_ERROR_MAP: dict[type[Exception], tuple[int, str]] = {
    MetadataCodeExistsError: (409, "METADATA_CODE_EXISTS"),
    MetadataVersionNotFoundError: (404, "VERSION_NOT_FOUND"),
    MetadataVersionConflictError: (409, "VERSION_EXISTS"),
    IdempotencyConflictError: (409, "IDEMPOTENCY_CONFLICT"),
    InvalidComponentError: (422, "INVALID_COMPONENT"),
    InvalidPolicyError: (422, "INVALID_POLICY"),
    InvalidManifestError: (422, "INVALID_MANIFEST"),
    IncompatibleVersionError: (409, "INCOMPATIBLE_VERSION"),
    AmbiguousBarcodeError: (409, "AMBIGUOUS_BARCODE_MAPPING"),
    ProductNotFoundError: (404, "PRODUCT_NOT_FOUND"),
    RuleNotFoundError: (404, "RULE_NOT_FOUND"),
    ModelNotFoundError: (404, "MODEL_NOT_FOUND"),
    RevisionMismatchError: (412, "REVISION_MISMATCH"),
}


def _metadata_problem(exc: Exception) -> ApiProblem:
    """Map a repository governance error to an RFC 7807 problem response."""
    mapped = _METADATA_ERROR_MAP.get(type(exc))
    if mapped is None:
        raise exc
    status_code, code = mapped
    return ApiProblem(status_code=status_code, code=code, detail=str(exc))


def _valid_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except ValueError:
        return False


def _require_idempotency_key(header: str | None) -> str:
    if header is None or not header.strip():
        raise ApiProblem(
            status_code=422,
            code="IDEMPOTENCY_KEY_REQUIRED",
            detail="an Idempotency-Key header is required",
        )
    if len(header) > _MAX_IDEMPOTENCY_KEY_LEN:
        raise ApiProblem(
            status_code=422,
            code="IDEMPOTENCY_KEY_INVALID",
            detail="the idempotency key is too long",
        )
    return header


def _body_hash(body: Any) -> str:
    """Stable SHA-256 of a validated request body (C5 idempotency)."""
    raw = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _request_id(request: Request) -> str | None:
    value = request.state.request_id
    return str(value) if value is not None else None


def _product_summary_out(row: Any) -> ProductSummaryOut:
    return ProductSummaryOut(
        id=row.id,
        organization_id=row.organization_id,
        product_code=row.product_code,
        name=row.name,
        created_at=row.created_at,
        version_count=row.version_count,
        latest_version_id=row.latest_version_id,
        latest_version_number=row.latest_version_number,
        latest_version_status=row.latest_version_status,
    )


def _product_out(row: ProductRow) -> ProductOut:
    return ProductOut(
        id=row.id,
        organization_id=row.organization_id,
        product_code=row.product_code,
        name=row.name,
        created_at=row.created_at,
    )


def _product_version_out(version: ProductVersionRow) -> ProductVersionOut:
    return ProductVersionOut(
        id=version.id,
        organization_id=version.organization_id,
        product_id=version.product_id,
        product_code=version.product_code,
        version_id=version.version_id,
        version=version.version,
        status=version.status,
        barcodes=version.barcodes,
        components=[
            ProductVersionComponentOut(
                component_code=component.component_code,
                expected_count=component.expected_count,
            )
            for component in version.components
        ],
        published_at=version.published_at,
        published_by=version.published_by,
        publish_reason=version.publish_reason,
        created_at=version.created_at,
    )


def _product_detail_out(detail: ProductDetailRow) -> ProductDetailOut:
    product = detail.product
    return ProductDetailOut(
        id=product.id,
        organization_id=product.organization_id,
        product_code=product.product_code,
        name=product.name,
        created_at=product.created_at,
        versions=[_product_version_out(version) for version in detail.versions],
    )


def _rule_summary_out(row: Any) -> RuleSummaryOut:
    return RuleSummaryOut(
        id=row.id,
        organization_id=row.organization_id,
        rule_code=row.rule_code,
        name=row.name,
        created_at=row.created_at,
        version_count=row.version_count,
        latest_version_id=row.latest_version_id,
        latest_version_number=row.latest_version_number,
        latest_version_status=row.latest_version_status,
    )


def _rule_out(row: RuleRow) -> RuleOut:
    return RuleOut(
        id=row.id,
        organization_id=row.organization_id,
        rule_code=row.rule_code,
        name=row.name,
        created_at=row.created_at,
    )


def _rule_version_out(version: RuleVersionRow) -> RuleVersionOut:
    return RuleVersionOut(
        id=version.id,
        organization_id=version.organization_id,
        rule_id=version.rule_id,
        rule_code=version.rule_code,
        product_version_id=version.product_version_id,
        version_id=version.version_id,
        version=version.version,
        status=version.status,
        barcode_required=version.barcode_required,
        minimum_usable_frames=version.minimum_usable_frames,
        uncertain_maps_to_ng=version.uncertain_maps_to_ng,
        mandatory_gates=version.mandatory_gates,
        component_policies=[
            RulePolicyOut(
                component_code=policy.component_code,
                high_confidence=policy.high_confidence,
                medium_confidence=policy.medium_confidence,
                minimum_medium_detections=policy.minimum_medium_detections,
                require_adjacent_frames=policy.require_adjacent_frames,
                expected_count=policy.expected_count,
            )
            for policy in version.component_policies
        ],
        compatible_model_version_ids=version.compatible_model_version_ids,
        content_sha256=version.content_sha256,
        published_at=version.published_at,
        published_by=version.published_by,
        publish_reason=version.publish_reason,
        created_at=version.created_at,
    )


def _rule_detail_out(detail: RuleDetailRow) -> RuleDetailOut:
    rule = detail.rule
    return RuleDetailOut(
        id=rule.id,
        organization_id=rule.organization_id,
        rule_code=rule.rule_code,
        name=rule.name,
        created_at=rule.created_at,
        versions=[_rule_version_out(version) for version in detail.versions],
    )


def _model_summary_out(row: Any) -> ModelSummaryOut:
    return ModelSummaryOut(
        id=row.id,
        organization_id=row.organization_id,
        model_code=row.model_code,
        name=row.name,
        task=row.task,
        created_at=row.created_at,
        version_count=row.version_count,
        latest_version_id=row.latest_version_id,
        latest_version_number=row.latest_version_number,
        latest_version_status=row.latest_version_status,
    )


def _model_package_out(row: ModelPackageRow) -> ModelPackageOut:
    return ModelPackageOut(
        id=row.id,
        organization_id=row.organization_id,
        model_code=row.model_code,
        name=row.name,
        task=row.task,
        created_at=row.created_at,
    )


def _model_version_out(version: ModelVersionRow) -> ModelVersionOut:
    return ModelVersionOut(
        id=version.id,
        organization_id=version.organization_id,
        model_package_id=version.model_package_id,
        model_code=version.model_code,
        task=version.task,
        version_id=version.version_id,
        version=version.version,
        status=version.status,
        semantic_version=version.semantic_version,
        edge_version_label=version.edge_version_label,
        runtime=version.runtime,
        input_width=version.input_width,
        input_height=version.input_height,
        class_names=version.class_names,
        artifacts=[ArtifactOut.model_validate(artifact) for artifact in version.artifacts],
        datasets=[DatasetOut.model_validate(dataset) for dataset in version.datasets],
        split_strategy=version.split_strategy,
        source_revision=version.source_revision,
        training_config_revision=version.training_config_revision,
        metrics=[MetricOut.model_validate(metric) for metric in version.metrics],
        limitations=version.limitations,
        manifest_sha256=version.manifest_sha256,
        published_at=version.published_at,
        published_by=version.published_by,
        publish_reason=version.publish_reason,
        created_at=version.created_at,
    )


def _model_detail_out(detail: Any) -> ModelDetailOut:
    package = detail.package
    return ModelDetailOut(
        id=package.id,
        organization_id=package.organization_id,
        model_code=package.model_code,
        name=package.name,
        task=package.task,
        created_at=package.created_at,
        versions=[_model_version_out(version) for version in detail.versions],
    )


def _desired_configuration_out(row: DesiredConfigurationRow) -> DesiredConfigurationOut:
    return DesiredConfigurationOut(
        id=row.id,
        organization_id=row.organization_id,
        device_row_id=row.device_row_id,
        device_id=row.device_id,
        device_name=row.device_name,
        revision=row.revision,
        product_version_id=row.product_version_id,
        product_model_version_id=row.product_model_version_id,
        component_model_version_id=row.component_model_version_id,
        rule_version_id=row.rule_version_id,
        reason=row.reason,
        assigned_by=row.assigned_by,
        assigned_at=row.assigned_at,
        created_at=row.created_at,
    )


# -- components --------------------------------------------------------------


@router.get(
    "/components",
    response_model=ComponentPage,
    openapi_extra={"security": SECURITY},
    responses=UNAUTHENTICATED_RESPONSES,
)
def list_components(
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> ComponentPage:
    """The organization's component vocabulary (C5)."""
    return ComponentPage(
        items=[
            ComponentOut(
                id=row.id,
                organization_id=row.organization_id,
                component_code=row.component_code,
                display_name=row.display_name,
                created_at=row.created_at,
            )
            for row in repository.list_components(administrator.organization_id)
        ]
    )


@router.post(
    "/components",
    response_model=ComponentOut,
    status_code=201,
    openapi_extra={"security": SECURITY},
    responses={
        **UNAUTHENTICATED_RESPONSES,
        409: {
            "description": "Component code exists or the idempotency key was reused",
            "content": {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            },
        },
    },
)
def create_component(
    body: ComponentCreate,
    response: Response,
    request: Request,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ComponentOut:
    """Create a component in the organization vocabulary (C5)."""
    key = _require_idempotency_key(idempotency_key)
    try:
        result = repository.create_component(
            organization_id=administrator.organization_id,
            component_code=body.component_code,
            display_name=body.display_name,
            idempotency_key=key,
            request_hash=_body_hash(body),
            created_at=datetime.now(UTC),
            actor=administrator.username,
            request_id=_request_id(request),
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a problem response below
        raise _metadata_problem(exc) from exc
    if result.replayed:
        response.status_code = 200
    row = result.component
    return ComponentOut(
        id=row.id,
        organization_id=row.organization_id,
        component_code=row.component_code,
        display_name=row.display_name,
        created_at=row.created_at,
    )


# -- products ----------------------------------------------------------------


@router.get(
    "/products",
    response_model=ProductPage,
    openapi_extra={"security": SECURITY},
    responses=UNAUTHENTICATED_RESPONSES,
)
def list_products(
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> ProductPage:
    """Stable products with their latest governed version (C5)."""
    return ProductPage(
        items=[
            _product_summary_out(row)
            for row in repository.list_products(administrator.organization_id)
        ]
    )


@router.post(
    "/products",
    response_model=ProductOut,
    status_code=201,
    openapi_extra={"security": SECURITY},
    responses={
        **UNAUTHENTICATED_RESPONSES,
        409: {
            "description": "Product code exists or the idempotency key was reused",
            "content": {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            },
        },
    },
)
def create_product(
    body: ProductCreate,
    response: Response,
    request: Request,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ProductOut:
    """Create a stable product identity (C5)."""
    key = _require_idempotency_key(idempotency_key)
    try:
        result = repository.create_product(
            organization_id=administrator.organization_id,
            product_code=body.product_code,
            name=body.name,
            idempotency_key=key,
            request_hash=_body_hash(body),
            created_at=datetime.now(UTC),
            actor=administrator.username,
            request_id=_request_id(request),
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a problem response below
        raise _metadata_problem(exc) from exc
    if result.replayed:
        response.status_code = 200
    return _product_out(result.product)


@router.get(
    "/products/{product_id}",
    response_model=ProductDetailOut,
    openapi_extra={"security": SECURITY},
    responses={**UNAUTHENTICATED_RESPONSES, **NOT_FOUND_RESPONSES},
)
def get_product(
    product_id: int,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> ProductDetailOut:
    """A stable product with all its immutable versions (C5)."""
    detail = repository.get_product_detail(administrator.organization_id, product_id)
    if detail is None:
        raise ApiProblem(
            status_code=404,
            code="PRODUCT_NOT_FOUND",
            detail="the product does not exist in this organization",
        )
    return _product_detail_out(detail)


@router.post(
    "/products/{product_id}/versions",
    response_model=ProductVersionOut,
    status_code=201,
    openapi_extra={"security": SECURITY},
    responses={
        **UNAUTHENTICATED_RESPONSES,
        **NOT_FOUND_RESPONSES,
        409: {
            "description": "A version collision or idempotency key reuse",
            "content": {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            },
        },
        422: {
            "description": "Invalid component set or barcode values",
            "content": {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            },
        },
    },
)
def create_product_version(
    product_id: int,
    body: ProductVersionCreate,
    response: Response,
    request: Request,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ProductVersionOut:
    """Draft the next immutable product version (C5)."""
    key = _require_idempotency_key(idempotency_key)
    try:
        result = repository.create_product_version(
            organization_id=administrator.organization_id,
            product_id=product_id,
            barcodes=body.barcodes,
            required_components=[
                ProductComponentInput(
                    component_code=component.component_code,
                    expected_count=component.expected_count,
                )
                for component in body.components
            ],
            idempotency_key=key,
            request_hash=_body_hash(body),
            created_at=datetime.now(UTC),
            actor=administrator.username,
            request_id=_request_id(request),
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a problem response below
        raise _metadata_problem(exc) from exc
    if result.replayed:
        response.status_code = 200
    if result.version is None:
        raise ApiProblem(
            status_code=500,
            code="INTERNAL_ERROR",
            detail="the created product version could not be loaded",
        )
    return _product_version_out(result.version)


@router.get(
    "/product-versions/{version_id}",
    response_model=ProductVersionOut,
    openapi_extra={"security": SECURITY},
    responses={**UNAUTHENTICATED_RESPONSES, **NOT_FOUND_RESPONSES},
)
def get_product_version(
    version_id: str,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> ProductVersionOut:
    """One immutable product version (C5)."""
    if not _valid_uuid(version_id):
        raise ApiProblem(
            status_code=404,
            code="VERSION_NOT_FOUND",
            detail="the product version does not exist in this organization",
        )
    version = repository.get_product_version(administrator.organization_id, version_id)
    if version is None:
        raise ApiProblem(
            status_code=404,
            code="VERSION_NOT_FOUND",
            detail="the product version does not exist in this organization",
        )
    return _product_version_out(version)


@router.post(
    "/product-versions/{version_id}/publish",
    response_model=ProductVersionOut,
    status_code=200,
    openapi_extra={"security": SECURITY},
    responses={
        **UNAUTHENTICATED_RESPONSES,
        **NOT_FOUND_RESPONSES,
        409: {
            "description": "Ambiguous barcode mapping",
            "content": {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            },
        },
        422: {
            "description": "The version is not publishable",
            "content": {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            },
        },
    },
)
def publish_product_version(
    version_id: str,
    body: PublishRequest,
    request: Request,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> ProductVersionOut:
    """Validate and immutably publish a product version (C5).

    A repeated publish returns the already-published version without writing a
    second audit event. A published version is never updated or deleted.
    """
    if not _valid_uuid(version_id):
        raise ApiProblem(
            status_code=404,
            code="VERSION_NOT_FOUND",
            detail="the product version does not exist in this organization",
        )
    try:
        repository.publish_product_version(
            organization_id=administrator.organization_id,
            version_id=version_id,
            published_by=administrator.username,
            publish_reason=body.reason,
            published_at=datetime.now(UTC),
            actor=administrator.username,
            request_id=_request_id(request),
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a problem response below
        raise _metadata_problem(exc) from exc
    version = repository.get_product_version(administrator.organization_id, version_id)
    if version is None:
        raise ApiProblem(
            status_code=500,
            code="INTERNAL_ERROR",
            detail="the published product version could not be loaded",
        )
    return _product_version_out(version)


# -- rules -------------------------------------------------------------------


@router.get(
    "/rules",
    response_model=RulePage,
    openapi_extra={"security": SECURITY},
    responses=UNAUTHENTICATED_RESPONSES,
)
def list_rules(
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> RulePage:
    """Stable rules with their latest governed version (C5)."""
    return RulePage(
        items=[
            _rule_summary_out(row) for row in repository.list_rules(administrator.organization_id)
        ]
    )


@router.post(
    "/rules",
    response_model=RuleOut,
    status_code=201,
    openapi_extra={"security": SECURITY},
    responses={
        **UNAUTHENTICATED_RESPONSES,
        409: {
            "description": "Rule code exists or the idempotency key was reused",
            "content": {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            },
        },
    },
)
def create_rule(
    body: RuleCreate,
    response: Response,
    request: Request,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RuleOut:
    """Create a stable rule identity (C5)."""
    key = _require_idempotency_key(idempotency_key)
    try:
        result = repository.create_rule(
            organization_id=administrator.organization_id,
            rule_code=body.rule_code,
            name=body.name,
            idempotency_key=key,
            request_hash=_body_hash(body),
            created_at=datetime.now(UTC),
            actor=administrator.username,
            request_id=_request_id(request),
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a problem response below
        raise _metadata_problem(exc) from exc
    if result.replayed:
        response.status_code = 200
    return _rule_out(result.rule)


@router.get(
    "/rules/{rule_id}",
    response_model=RuleDetailOut,
    openapi_extra={"security": SECURITY},
    responses={**UNAUTHENTICATED_RESPONSES, **NOT_FOUND_RESPONSES},
)
def get_rule(
    rule_id: int,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> RuleDetailOut:
    """A stable rule with all its immutable versions (C5)."""
    detail = repository.get_rule_detail(administrator.organization_id, rule_id)
    if detail is None:
        raise ApiProblem(
            status_code=404,
            code="RULE_NOT_FOUND",
            detail="the rule does not exist in this organization",
        )
    return _rule_detail_out(detail)


@router.post(
    "/rules/{rule_id}/versions",
    response_model=RuleVersionOut,
    status_code=201,
    openapi_extra={"security": SECURITY},
    responses={
        **UNAUTHENTICATED_RESPONSES,
        **NOT_FOUND_RESPONSES,
        409: {
            "description": "A version collision or idempotency key reuse",
            "content": {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            },
        },
        422: {
            "description": "Invalid component policy",
            "content": {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            },
        },
    },
)
def create_rule_version(
    rule_id: int,
    body: RuleVersionCreate,
    response: Response,
    request: Request,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RuleVersionOut:
    """Draft the next immutable rule version (C5)."""
    key = _require_idempotency_key(idempotency_key)
    try:
        result = repository.create_rule_version(
            organization_id=administrator.organization_id,
            rule_id=rule_id,
            product_version_id=body.product_version_id,
            barcode_required=body.barcode_required,
            minimum_usable_frames=body.minimum_usable_frames,
            mandatory_gates=body.mandatory_gates,
            component_policies=[_rule_policy_input(policy) for policy in body.component_policies],
            compatible_component_model_version_ids=body.compatible_component_model_version_ids,
            idempotency_key=key,
            request_hash=_body_hash(body),
            created_at=datetime.now(UTC),
            actor=administrator.username,
            request_id=_request_id(request),
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a problem response below
        raise _metadata_problem(exc) from exc
    if result.replayed:
        response.status_code = 200
    if result.version is None:
        raise ApiProblem(
            status_code=500,
            code="INTERNAL_ERROR",
            detail="the created rule version could not be loaded",
        )
    return _rule_version_out(result.version)


def _rule_policy_input(policy: RulePolicyIn) -> RulePolicyInput:
    """Adapter from the API schema policy to the repository input dataclass."""
    return RulePolicyInput(
        component_code=policy.component_code,
        high_confidence=policy.high_confidence,
        medium_confidence=policy.medium_confidence,
        minimum_medium_detections=policy.minimum_medium_detections,
        require_adjacent_frames=policy.require_adjacent_frames,
        expected_count=policy.expected_count,
    )


@router.get(
    "/rule-versions/{version_id}",
    response_model=RuleVersionOut,
    openapi_extra={"security": SECURITY},
    responses={**UNAUTHENTICATED_RESPONSES, **NOT_FOUND_RESPONSES},
)
def get_rule_version(
    version_id: str,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> RuleVersionOut:
    """One immutable rule version (C5)."""
    if not _valid_uuid(version_id):
        raise ApiProblem(
            status_code=404,
            code="VERSION_NOT_FOUND",
            detail="the rule version does not exist in this organization",
        )
    version = repository.get_rule_version(administrator.organization_id, version_id)
    if version is None:
        raise ApiProblem(
            status_code=404,
            code="VERSION_NOT_FOUND",
            detail="the rule version does not exist in this organization",
        )
    return _rule_version_out(version)


@router.post(
    "/rule-versions/{version_id}/publish",
    response_model=RuleVersionOut,
    status_code=200,
    openapi_extra={"security": SECURITY},
    responses={
        **UNAUTHENTICATED_RESPONSES,
        **NOT_FOUND_RESPONSES,
        409: {
            "description": "The rule is incompatible with its product or models",
            "content": {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            },
        },
        422: {
            "description": "The rule policy set is incomplete",
            "content": {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            },
        },
    },
)
def publish_rule_version(
    version_id: str,
    body: PublishRequest,
    request: Request,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> RuleVersionOut:
    """Validate model/product compatibility and publish a rule version (C5)."""
    if not _valid_uuid(version_id):
        raise ApiProblem(
            status_code=404,
            code="VERSION_NOT_FOUND",
            detail="the rule version does not exist in this organization",
        )
    try:
        repository.publish_rule_version(
            organization_id=administrator.organization_id,
            version_id=version_id,
            published_by=administrator.username,
            publish_reason=body.reason,
            published_at=datetime.now(UTC),
            actor=administrator.username,
            request_id=_request_id(request),
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a problem response below
        raise _metadata_problem(exc) from exc
    version = repository.get_rule_version(administrator.organization_id, version_id)
    if version is None:
        raise ApiProblem(
            status_code=500,
            code="INTERNAL_ERROR",
            detail="the published rule version could not be loaded",
        )
    return _rule_version_out(version)


# -- models ------------------------------------------------------------------


@router.get(
    "/models",
    response_model=ModelPage,
    openapi_extra={"security": SECURITY},
    responses=UNAUTHENTICATED_RESPONSES,
)
def list_models(
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> ModelPage:
    """Stable model packages with their latest governed version (C5)."""
    return ModelPage(
        items=[
            _model_summary_out(row) for row in repository.list_models(administrator.organization_id)
        ]
    )


@router.post(
    "/models",
    response_model=ModelPackageOut,
    status_code=201,
    openapi_extra={"security": SECURITY},
    responses={
        **UNAUTHENTICATED_RESPONSES,
        409: {
            "description": "Model code exists or the idempotency key was reused",
            "content": {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            },
        },
    },
)
def create_model_package(
    body: ModelCreate,
    response: Response,
    request: Request,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ModelPackageOut:
    """Create a stable model package identity (C5)."""
    key = _require_idempotency_key(idempotency_key)
    try:
        result = repository.create_model_package(
            organization_id=administrator.organization_id,
            model_code=body.model_code,
            name=body.name,
            task=body.task,
            idempotency_key=key,
            request_hash=_body_hash(body),
            created_at=datetime.now(UTC),
            actor=administrator.username,
            request_id=_request_id(request),
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a problem response below
        raise _metadata_problem(exc) from exc
    if result.replayed:
        response.status_code = 200
    return _model_package_out(result.package)


@router.get(
    "/models/{model_id}",
    response_model=ModelDetailOut,
    openapi_extra={"security": SECURITY},
    responses={**UNAUTHENTICATED_RESPONSES, **NOT_FOUND_RESPONSES},
)
def get_model(
    model_id: int,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> ModelDetailOut:
    """A stable model package with all its immutable versions (C5)."""
    detail = repository.get_model_detail(administrator.organization_id, model_id)
    if detail is None:
        raise ApiProblem(
            status_code=404,
            code="MODEL_NOT_FOUND",
            detail="the model does not exist in this organization",
        )
    return _model_detail_out(detail)


@router.post(
    "/models/{model_id}/versions",
    response_model=ModelVersionOut,
    status_code=201,
    openapi_extra={"security": SECURITY},
    responses={
        **UNAUTHENTICATED_RESPONSES,
        **NOT_FOUND_RESPONSES,
        409: {
            "description": "A version collision or idempotency key reuse",
            "content": {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            },
        },
        422: {
            "description": "Invalid manifest",
            "content": {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            },
        },
    },
)
def create_model_version(
    model_id: int,
    body: ModelManifestIn,
    response: Response,
    request: Request,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ModelVersionOut:
    """Register the next immutable model version manifest (C5).

    Registration is declarative: artifact bytes are never fetched or verified
    server-side in M1, so the record never claims the artifact was validated.
    """
    key = _require_idempotency_key(idempotency_key)
    try:
        result = repository.create_model_version(
            organization_id=administrator.organization_id,
            model_package_id=model_id,
            manifest=body.model_dump(mode="json"),
            idempotency_key=key,
            request_hash=_body_hash(body),
            created_at=datetime.now(UTC),
            actor=administrator.username,
            request_id=_request_id(request),
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a problem response below
        raise _metadata_problem(exc) from exc
    if result.replayed:
        response.status_code = 200
    if result.version is None:
        raise ApiProblem(
            status_code=500,
            code="INTERNAL_ERROR",
            detail="the created model version could not be loaded",
        )
    return _model_version_out(result.version)


@router.get(
    "/model-versions/{version_id}",
    response_model=ModelVersionOut,
    openapi_extra={"security": SECURITY},
    responses={**UNAUTHENTICATED_RESPONSES, **NOT_FOUND_RESPONSES},
)
def get_model_version(
    version_id: str,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> ModelVersionOut:
    """One immutable model version (C5)."""
    if not _valid_uuid(version_id):
        raise ApiProblem(
            status_code=404,
            code="VERSION_NOT_FOUND",
            detail="the model version does not exist in this organization",
        )
    version = repository.get_model_version(administrator.organization_id, version_id)
    if version is None:
        raise ApiProblem(
            status_code=404,
            code="VERSION_NOT_FOUND",
            detail="the model version does not exist in this organization",
        )
    return _model_version_out(version)


@router.post(
    "/model-versions/{version_id}/publish",
    response_model=ModelVersionOut,
    status_code=200,
    openapi_extra={"security": SECURITY},
    responses={
        **UNAUTHENTICATED_RESPONSES,
        **NOT_FOUND_RESPONSES,
    },
)
def publish_model_version(
    version_id: str,
    body: PublishRequest,
    request: Request,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> ModelVersionOut:
    """Publish a declaratively registered model version (C5).

    Publication never claims server-side artifact verification; the edge
    validates bytes, checksums, compatibility, and last-known-good rollback
    locally during manual installation.
    """
    if not _valid_uuid(version_id):
        raise ApiProblem(
            status_code=404,
            code="VERSION_NOT_FOUND",
            detail="the model version does not exist in this organization",
        )
    try:
        repository.publish_model_version(
            organization_id=administrator.organization_id,
            version_id=version_id,
            published_by=administrator.username,
            publish_reason=body.reason,
            published_at=datetime.now(UTC),
            actor=administrator.username,
            request_id=_request_id(request),
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a problem response below
        raise _metadata_problem(exc) from exc
    version = repository.get_model_version(administrator.organization_id, version_id)
    if version is None:
        raise ApiProblem(
            status_code=500,
            code="INTERNAL_ERROR",
            detail="the published model version could not be loaded",
        )
    return _model_version_out(version)
