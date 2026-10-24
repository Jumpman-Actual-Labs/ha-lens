"""The Lens LLM API: read-only tools that list every entity."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, override

import probatio

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    label_registry as lr,
    llm,
)

from .const import (
    DEFAULT_LIMIT,
    DOMAIN,
    MAX_LIMIT,
    MAX_LIMIT_IDS_ONLY,
    STATUS_ACTIVE,
    STATUS_DISABLED,
    STATUS_HIDDEN,
    STATUS_NOT_IN_REGISTRY,
    STATUS_NOT_LOADED,
    STATUSES,
)

API_PROMPT = (
    "Lens gives read-only access to every entity in Home Assistant, including "
    "entities that are disabled, hidden, not loaded, or not exposed to Assist. "
    "Each entity has a status: active (registered and has a state), disabled, "
    "hidden, not_loaded (registered but has no state) or not_in_registry "
    "(has a state but no registry entry, such as YAML entities without a "
    "unique_id). Start with ListEntityDomains for an overview, then use "
    "ListEntities with filters and paging (follow next_offset until it is "
    "null) to find entities, then GetEntity for full detail on one entity. "
    "Lens cannot change anything; to control a device, use the Assist tools, "
    "which only work for entities exposed to Assist."
)

READ_ONLY = llm.ToolAnnotations(
    read_only=True, destructive=False, idempotent=True, open_world=False
)


def _json_safe(value: Any) -> Any:
    """Convert a value to something json.dumps can serialize."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_json_safe(v) for v in value), key=str)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _error(message: str) -> llm.ToolResult:
    """Return an error result."""
    return llm.ToolResult(data={"error": message}, error=True)


def _status(entry: er.RegistryEntry | None, state: State | None) -> str:
    """Classify an entity."""
    if entry is None:
        return STATUS_NOT_IN_REGISTRY
    if entry.disabled_by is not None:
        return STATUS_DISABLED
    if entry.hidden_by is not None:
        return STATUS_HIDDEN
    if state is None:
        return STATUS_NOT_LOADED
    return STATUS_ACTIVE


class _Registries:
    """Snapshot of the registries used to build rows."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.entities = er.async_get(hass)
        self.devices = dr.async_get(hass)
        self.areas = ar.async_get(hass)

    def device(self, entry: er.RegistryEntry | None) -> dr.DeviceEntry | None:
        if entry is None or entry.device_id is None:
            return None
        return self.devices.async_get(entry.device_id)

    def area_name(
        self, entry: er.RegistryEntry | None, device: dr.DeviceEntry | None
    ) -> str | None:
        area_id = entry.area_id if entry else None
        if area_id is None and device is not None:
            area_id = device.area_id
        if area_id is None:
            return None
        area = self.areas.async_get_area(area_id)
        return area.name if area else None

    def row(self, entity_id: str) -> dict[str, Any]:
        """Build the summary row for one entity."""
        entry = self.entities.async_get(entity_id)
        state = self.hass.states.get(entity_id)
        device = self.device(entry)
        name = None
        if state is not None:
            name = state.name
        if not name and entry is not None:
            name = entry.name or entry.original_name
        return {
            "entity_id": entity_id,
            "name": name,
            "state": state.state if state else None,
            "status": _status(entry, state),
            "integration": entry.platform if entry else None,
            "area": self.area_name(entry, device),
            "device": (device.name_by_user or device.name) if device else None,
        }

    def all_entity_ids(self) -> list[str]:
        """Return every entity ID from the registry and the state machine."""
        ids = set(self.entities.entities)
        ids.update(self.hass.states.async_entity_ids())
        return sorted(ids)

    def all_rows(self) -> list[dict[str, Any]]:
        return [self.row(entity_id) for entity_id in self.all_entity_ids()]


class LensTool(llm.Tool):
    """Base class for Lens tools."""

    integration = DOMAIN
    annotations = READ_ONLY

    @override
    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> llm.ToolResult:
        """Validate arguments and run the tool."""
        try:
            args = self.parameters(tool_input.tool_args or {})
        except probatio.Invalid as err:
            return _error(f"Invalid arguments: {err}")
        return self._run(hass, args)

    def _run(self, hass: HomeAssistant, args: dict[str, Any]) -> llm.ToolResult:
        raise NotImplementedError


class ListEntityDomainsTool(LensTool):
    """Count entities per domain and status."""

    name = "ListEntityDomains"
    title = "List entity domains"
    description = (
        "Overview of every entity in Home Assistant: the total entity count "
        "and, for each domain, a total plus counts by status (active, "
        "disabled, hidden, not_loaded, not_in_registry). Use this first."
    )
    parameters = probatio.Schema({})

    @override
    def _run(self, hass: HomeAssistant, args: dict[str, Any]) -> llm.ToolResult:
        domains: dict[str, dict[str, Any]] = {}
        rows = _Registries(hass).all_rows()
        for row in rows:
            domain = row["entity_id"].split(".", 1)[0]
            counts = domains.setdefault(
                domain, {"total": 0, "by_status": dict.fromkeys(STATUSES, 0)}
            )
            counts["total"] += 1
            counts["by_status"][row["status"]] += 1
        return llm.ToolResult(
            data={"total_entities": len(rows), "domains": dict(sorted(domains.items()))}
        )


class ListEntitiesTool(LensTool):
    """List entities with filters and paging."""

    name = "ListEntities"
    title = "List entities"
    description = (
        "List entities sorted by entity_id, with optional filters. Results "
        "are paged: pass next_offset as offset to get the next page; "
        "next_offset is null when there are no more. Set ids_only to get "
        "just entity IDs with a larger page size."
    )
    parameters = probatio.Schema(
        {
            probatio.Optional(
                "domain",
                description="Only entities in this domain, e.g. light or sensor.",
            ): str,
            probatio.Optional(
                "status",
                description=(
                    "Only entities with this status. active: registered and "
                    "has a state; disabled: disabled in the registry; hidden: "
                    "hidden in the registry; not_loaded: registered but has "
                    "no state; not_in_registry: has a state but no registry "
                    "entry."
                ),
            ): probatio.In(list(STATUSES)),
            probatio.Optional(
                "search",
                description=(
                    "Case-insensitive text to find in the entity ID, name, "
                    "area, device or integration."
                ),
            ): str,
            probatio.Optional(
                "area",
                description="Only entities in the area with this exact name (case-insensitive).",
            ): str,
            probatio.Optional(
                "integration",
                description="Only entities from this integration (platform), e.g. hue or zha.",
            ): str,
            probatio.Optional(
                "ids_only",
                default=False,
                description="Return only entity IDs instead of full rows.",
            ): bool,
            probatio.Optional(
                "limit",
                default=DEFAULT_LIMIT,
                description=(
                    f"Page size. Default {DEFAULT_LIMIT}, max {MAX_LIMIT}, "
                    f"or max {MAX_LIMIT_IDS_ONLY} when ids_only is true."
                ),
            ): probatio.All(int, probatio.Range(min=1, max=MAX_LIMIT_IDS_ONLY)),
            probatio.Optional(
                "offset",
                default=0,
                description="Number of matching entities to skip, for paging.",
            ): probatio.All(int, probatio.Range(min=0)),
        }
    )

    @override
    def _run(self, hass: HomeAssistant, args: dict[str, Any]) -> llm.ToolResult:
        ids_only: bool = args["ids_only"]
        limit: int = args["limit"]
        offset: int = args["offset"]
        if not ids_only and limit > MAX_LIMIT:
            return _error(
                f"limit can be at most {MAX_LIMIT} (or {MAX_LIMIT_IDS_ONLY} "
                "with ids_only set to true)"
            )

        domain = args.get("domain", "").strip().lower()
        status = args.get("status")
        search = args.get("search", "").strip().lower()
        area = args.get("area", "").strip().lower()
        integration = args.get("integration", "").strip().lower()

        regs = _Registries(hass)
        matches = []
        for entity_id in regs.all_entity_ids():
            if domain and entity_id.split(".", 1)[0] != domain:
                continue
            row = regs.row(entity_id)
            if status and row["status"] != status:
                continue
            if area and (row["area"] or "").lower() != area:
                continue
            if integration and (row["integration"] or "").lower() != integration:
                continue
            if search and not any(
                search in (row[key] or "").lower()
                for key in ("entity_id", "name", "area", "device", "integration")
            ):
                continue
            matches.append(row)

        page = matches[offset : offset + limit]
        next_offset = offset + len(page)
        return llm.ToolResult(
            data={
                "total_matching": len(matches),
                "offset": offset,
                "returned": len(page),
                "next_offset": next_offset if next_offset < len(matches) else None,
                "entities": (
                    [row["entity_id"] for row in page]
                    if ids_only
                    else _json_safe(page)
                ),
            }
        )


class GetEntityTool(LensTool):
    """Return full detail for one entity."""

    name = "GetEntity"
    title = "Get entity"
    description = (
        "Full detail for one entity, including disabled ones: status, state, "
        "attributes, last changed/updated, registry details and device."
    )
    parameters = probatio.Schema(
        {
            probatio.Required(
                "entity_id",
                description="The entity ID, e.g. light.kitchen.",
            ): str,
        }
    )

    @override
    def _run(self, hass: HomeAssistant, args: dict[str, Any]) -> llm.ToolResult:
        entity_id = args["entity_id"].strip().lower()
        regs = _Registries(hass)
        entry = regs.entities.async_get(entity_id)
        state = hass.states.get(entity_id)
        if entry is None and state is None:
            return _error(
                f"Unknown entity {entity_id}. Use ListEntities with search to "
                "find the right entity ID."
            )

        row = regs.row(entity_id)
        result: dict[str, Any] = {
            "entity_id": entity_id,
            "name": row["name"],
            "status": row["status"],
            "state": state.state if state else None,
            "attributes": dict(state.attributes) if state else None,
            "last_changed": state.last_changed if state else None,
            "last_updated": state.last_updated if state else None,
            "registry": None,
            "device": None,
        }

        if entry is not None:
            device = regs.device(entry)
            config_entry = (
                hass.config_entries.async_get_entry(entry.config_entry_id)
                if entry.config_entry_id
                else None
            )
            labels = lr.async_get(hass)
            result["registry"] = {
                "unique_id": entry.unique_id,
                "integration": entry.platform,
                "config_entry": config_entry.title if config_entry else None,
                "name": entry.name,
                "original_name": entry.original_name,
                "disabled_by": entry.disabled_by,
                "hidden_by": entry.hidden_by,
                "entity_category": entry.entity_category,
                "device_class": entry.device_class or entry.original_device_class,
                "unit_of_measurement": entry.unit_of_measurement,
                "area": regs.area_name(entry, device),
                "labels": sorted(
                    label.name
                    for label_id in entry.labels
                    if (label := labels.async_get_label(label_id))
                ),
                "aliases": [a for a in entry.aliases if isinstance(a, str)],
                "created_at": entry.created_at,
                "modified_at": entry.modified_at,
            }
            if device is not None:
                result["device"] = {
                    "name": device.name_by_user or device.name,
                    "manufacturer": device.manufacturer,
                    "model": device.model,
                    "sw_version": device.sw_version,
                }

        return llm.ToolResult(data=_json_safe(result))


class LensAPI(llm.API):
    """Read-only API that lists every entity."""

    @override
    async def async_get_api_instance(
        self, llm_context: llm.LLMContext
    ) -> llm.APIInstance:
        """Return the API instance."""
        return llm.APIInstance(
            api=self,
            api_prompt=API_PROMPT,
            llm_context=llm_context,
            tools=[ListEntityDomainsTool(), ListEntitiesTool(), GetEntityTool()],
        )
