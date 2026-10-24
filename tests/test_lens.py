"""Tests for the Lens integration."""

import json

import probatio
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    label_registry as lr,
    llm,
)
from homeassistant.setup import async_setup_component

from custom_components.lens.const import DOMAIN


@pytest.fixture
async def entry(hass: HomeAssistant) -> MockConfigEntry:
    """Set up Lens alongside the llm integration that provides Assist."""
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "llm", {})
    entry = MockConfigEntry(domain=DOMAIN, title="Lens")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture
def entities(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Create one entity of each status."""
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    area = ar.async_get(hass).async_create("Kitchen")
    label = lr.async_get(hass).async_create("Important")
    device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("demo", "lamp")},
        name="Kitchen Lamp",
        manufacturer="Acme",
        model="L1",
        sw_version="1.2",
    )
    dev_reg.async_update_device(device.id, area_id=area.id)

    active = ent_reg.async_get_or_create(
        "light",
        "demo",
        "active",
        device_id=device.id,
        suggested_object_id="ceiling",
        original_name="Ceiling",
    )
    ent_reg.async_update_entity(
        active.entity_id, labels={label.label_id}, aliases=["Big light"]
    )
    hass.states.async_set(
        active.entity_id, "on", {"friendly_name": "Ceiling", "brightness": 200}
    )

    ent_reg.async_get_or_create(
        "sensor",
        "demo",
        "disabled",
        suggested_object_id="old_temp",
        disabled_by=er.RegistryEntryDisabler.USER,
        original_name="Old temp",
    )
    hidden = ent_reg.async_get_or_create(
        "switch",
        "demo",
        "hidden",
        suggested_object_id="pump",
        hidden_by=er.RegistryEntryHider.USER,
    )
    hass.states.async_set(hidden.entity_id, "off")
    ent_reg.async_get_or_create("sensor", "zha", "notloaded", suggested_object_id="ghost")
    hass.states.async_set("sensor.yaml_thing", "12", {"friendly_name": "YAML Thing"})


async def call(
    hass: HomeAssistant, tool: str, args: dict | None = None
) -> llm.ToolResult:
    """Call a Lens tool the way the MCP server does, through a merged API."""
    llm_context = llm.LLMContext(
        platform="test",
        context=Context(),
        language="en",
        assistant="conversation",
        device_id=None,
    )
    api = await llm.async_get_api(hass, ["assist", "lens"], llm_context)
    result = await api.async_call_tool(
        llm.ToolInput(tool_name=f"lens__{tool}", tool_args=args or {})
    )
    json.dumps(result.data, ensure_ascii=False)  # must not raise
    return result


async def test_setup_and_unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Setup registers the API and unload removes it."""
    assert entry.state is ConfigEntryState.LOADED
    assert "lens" in {api.id for api in llm.async_get_apis(hass)}

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert "lens" not in {api.id for api in llm.async_get_apis(hass)}


async def test_tools_metadata(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Tools are tagged read-only and owned by Lens."""
    llm_context = llm.LLMContext("test", None, "en", "conversation", None)
    instance = await llm.async_get_api(hass, "lens", llm_context)
    assert {t.name for t in instance.tools} == {
        "ListEntityDomains",
        "ListEntities",
        "GetEntity",
    }
    for tool in instance.tools:
        assert tool.integration == "lens"
        assert tool.annotations.read_only
        assert not tool.annotations.destructive
        assert tool.annotations.idempotent
        assert not tool.annotations.open_world
    assert "Assist" in instance.api_prompt

    for tool in instance.tools:
        schema = probatio.to_openapi(tool.parameters, openapi_version="3.1.0")
        json.dumps(schema)
        for field, spec in schema["properties"].items():
            assert spec.get("description"), f"{tool.name}.{field}"


async def test_domains_and_statuses(hass: HomeAssistant, entities: None) -> None:
    """Every status is classified correctly."""
    result = await call(hass, "ListEntityDomains")
    assert not result.error
    data = result.data
    assert data["total_entities"] == 5
    assert data["domains"]["light"]["by_status"]["active"] == 1
    assert data["domains"]["switch"]["by_status"]["hidden"] == 1
    assert data["domains"]["sensor"]["total"] == 3
    sensor = data["domains"]["sensor"]["by_status"]
    assert sensor["disabled"] == 1
    assert sensor["not_loaded"] == 1
    assert sensor["not_in_registry"] == 1

    rows = (await call(hass, "ListEntities")).data["entities"]
    assert {r["entity_id"]: r["status"] for r in rows} == {
        "light.ceiling": "active",
        "sensor.ghost": "not_loaded",
        "sensor.old_temp": "disabled",
        "sensor.yaml_thing": "not_in_registry",
        "switch.pump": "hidden",
    }


async def test_list_entities_filters(hass: HomeAssistant, entities: None) -> None:
    """Filters narrow the list."""

    async def ids(**args) -> list[str]:
        result = await call(hass, "ListEntities", args)
        assert not result.error, result.data
        return [r["entity_id"] for r in result.data["entities"]]

    assert await ids(domain="sensor") == [
        "sensor.ghost",
        "sensor.old_temp",
        "sensor.yaml_thing",
    ]
    assert await ids(status="disabled") == ["sensor.old_temp"]
    assert await ids(search="KITCHEN") == ["light.ceiling"]
    assert await ids(search="yaml thing") == ["sensor.yaml_thing"]
    assert await ids(area="kitchen") == ["light.ceiling"]
    assert await ids(integration="zha") == ["sensor.ghost"]

    row = (await call(hass, "ListEntities", {"domain": "light"})).data["entities"][0]
    assert row == {
        "entity_id": "light.ceiling",
        "name": "Ceiling",
        "state": "on",
        "status": "active",
        "integration": "demo",
        "area": "Kitchen",
        "device": "Kitchen Lamp",
    }


async def test_list_entities_paging(hass: HomeAssistant, entities: None) -> None:
    """Paging and ids_only."""
    page1 = (await call(hass, "ListEntities", {"limit": 2, "ids_only": True})).data
    assert page1["total_matching"] == 5
    assert page1["returned"] == 2
    assert page1["next_offset"] == 2
    assert page1["entities"] == ["light.ceiling", "sensor.ghost"]

    page3 = (
        await call(hass, "ListEntities", {"limit": 2, "offset": 4, "ids_only": True})
    ).data
    assert page3["entities"] == ["switch.pump"]
    assert page3["next_offset"] is None

    big = await call(hass, "ListEntities", {"limit": 5000, "ids_only": True})
    assert not big.error
    too_big = await call(hass, "ListEntities", {"limit": 2000})
    assert too_big.error
    assert "1000" in too_big.data["error"]


async def test_bad_input(hass: HomeAssistant, entities: None) -> None:
    """Bad arguments return a helpful error instead of raising."""
    result = await call(hass, "ListEntities", {"status": "broken"})
    assert result.error
    assert "status" in result.data["error"]

    result = await call(hass, "ListEntities", {"bogus": 1})
    assert result.error

    result = await call(hass, "GetEntity", {})
    assert result.error
    assert "entity_id" in result.data["error"]


async def test_get_entity_active(hass: HomeAssistant, entities: None) -> None:
    """Detail for an active entity."""
    result = await call(hass, "GetEntity", {"entity_id": "light.ceiling"})
    assert not result.error
    data = result.data
    assert data["status"] == "active"
    assert data["state"] == "on"
    assert data["attributes"]["brightness"] == 200
    assert isinstance(data["last_changed"], str)
    reg = data["registry"]
    assert reg["unique_id"] == "active"
    assert reg["integration"] == "demo"
    assert reg["area"] == "Kitchen"
    assert reg["labels"] == ["Important"]
    assert reg["aliases"] == ["Big light"]
    assert isinstance(reg["created_at"], str)
    assert data["device"] == {
        "name": "Kitchen Lamp",
        "manufacturer": "Acme",
        "model": "L1",
        "sw_version": "1.2",
    }


async def test_get_entity_disabled(hass: HomeAssistant, entities: None) -> None:
    """Detail for a disabled entity, which has no state."""
    result = await call(hass, "GetEntity", {"entity_id": "sensor.old_temp"})
    assert not result.error
    data = result.data
    assert data["status"] == "disabled"
    assert data["state"] is None
    assert data["registry"]["disabled_by"] == "user"
    assert data["registry"]["original_name"] == "Old temp"
    assert data["name"] == "Old temp"


async def test_get_entity_unknown(hass: HomeAssistant, entities: None) -> None:
    """Unknown entity IDs return an error."""
    result = await call(hass, "GetEntity", {"entity_id": "light.nope"})
    assert result.error
    assert "light.nope" in result.data["error"]


async def test_config_flow(hass: HomeAssistant) -> None:
    """The config flow creates one entry and refuses a second."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "form"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == "create_entry"
    assert result["title"] == "Lens"

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "abort"
    assert result["reason"] == "single_instance_allowed"
