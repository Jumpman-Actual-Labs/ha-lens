# Lens

Lens lets MCP clients such as Claude see **every** entity in Home Assistant, not
just the ones exposed to Assist.

Home Assistant's built-in [Model Context Protocol Server](https://www.home-assistant.io/integrations/mcp_server/)
offers the Assist API, so a connected client can only see entities you have
exposed to Assist. Lens registers a second LLM API with read-only tools that
list every entity and entity ID, including disabled, hidden and not-loaded
ones, without exposing any of them for control. Select both Assist and Lens in
the MCP Server and your client gets Assist's control tools plus Lens's listing
tools.

**Nothing in Lens can control entities.** Every tool only reads the entity,
device and area registries and the current states. Control still goes through
Assist, and only for entities you have exposed to it.

## Tools

| Tool | Arguments | Returns |
| --- | --- | --- |
| `ListEntityDomains` | none | Total entity count and, per domain, a total plus counts by status. |
| `ListEntities` | `domain`, `status`, `search`, `area`, `integration`, `ids_only`, `limit` (default 200, max 1000, or 5000 with `ids_only`), `offset` | `total_matching`, `offset`, `returned`, `next_offset` (null when done) and `entities`: rows of `entity_id`, `name`, `state`, `status`, `integration`, `area`, `device`, or just IDs with `ids_only`. Sorted by entity ID. |
| `GetEntity` | `entity_id` (required) | Status, state, attributes, last changed/updated, registry detail (unique ID, integration, config entry, names, disabled/hidden by, category, device class, unit, area, labels, aliases, created/modified) and device (name, manufacturer, model, firmware). Works for disabled entities. |

All arguments are optional except `entity_id`. `search` is a case-insensitive
substring match across entity ID, name, area, device and integration; `area` is
an exact, case-insensitive area name; `integration` is the platform, such as
`hue` or `zha`.

Through the MCP Server the tools appear namespaced, for example
`lens__ListEntities`.

## Statuses

| Status | Meaning |
| --- | --- |
| `active` | In the entity registry and has a state. |
| `disabled` | Disabled in the entity registry (`disabled_by` is set). |
| `hidden` | Hidden in the entity registry (`hidden_by` is set). |
| `not_loaded` | In the entity registry but has no state, for example because its integration failed to load. |
| `not_in_registry` | Has a state but no registry entry, such as YAML entities without a `unique_id`. |

## Install

Requires Home Assistant 2026.10 or later.

1. In HACS, open the menu and choose **Custom repositories**. Add
   `https://github.com/Jumpman-Actual-Labs/ha-lens` with type **Integration**.
2. Install **Lens** from HACS.
3. Restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration** and add **Lens**.
5. Open the **Model Context Protocol Server** integration, choose
   **Reconfigure**, and select **Lens** alongside **Assist**.
6. Reconnect your MCP client (for Claude, disconnect and reconnect the Home
   Assistant connector) so it picks up the new tools.

## Development

Tests use `pytest-homeassistant-custom-component` on Python 3.14. Its latest
release pins Home Assistant 2026.10.2, so install with uv and the override file:

```bash
uv pip install -r requirements_test.txt --override requirements_override.txt
```

```bash
pytest
```
