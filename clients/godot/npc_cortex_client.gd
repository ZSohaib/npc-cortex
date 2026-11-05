# npc_cortex_client.gd -- Godot client for the npc-cortex HTTP bridge.
# Mirrors npc_cortex.client.RemoteBridge. Attach to a Node, set base_url,
# call sync_nodes() when transforms change, then pump() once per _process.
# Coordinate convention: Vector3(x, y, z) -> [x, y, z] (identity on
# components, see adapters/godot.py); Vector2(x, y) -> [x, y].
class_name NpcCortexClient
extends Node

signal remote_action(action: Dictionary)
signal speech(player_id: String, text: String)
signal bridge_error(message: String)

@export var base_url: String = "http://127.0.0.1:8471"
@export var timeout: float = 10.0

var _action_cursor: int = 0
var _delivered_cursor: int = 0
var _busy: bool = false


func _ready() -> void:
	base_url = base_url.rstrip("/")


func _request(path: String, method: int, body: Variant = null) -> Variant:
	var err: Array = []
	var query := HTTPClient.new()
	var parts := base_url.replace("http://", "").replace("https://", "").split(":")
	var host := parts[0]
	var port := int(parts[1]) if parts.size() > 1 else 80
	var use_tls := base_url.begins_with("https")
	if query.connect_to_host(host, port) != OK:
		emit_signal("bridge_error", "connect failed")
		return err
	while query.get_status() in [HTTPClient.STATUS_CONNECTING, HTTPClient.STATUS_RESOLVING]:
		query.poll()
		await get_tree().process_frame
	if query.get_status() != HTTPClient.STATUS_CONNECTED:
		emit_signal("bridge_error", "no connection")
		return err
	var headers := PackedStringArray(["Content-Type: application/json"])
	var payload := JSON.stringify(body if body != null else {})
	query.request(method, path, headers, payload)
	while query.get_status() == HTTPClient.STATUS_REQUESTING:
		query.poll()
		await get_tree().process_frame
	if not query.has_response():
		emit_signal("bridge_error", "empty response")
		return err
	var chunks := PackedByteArray()
	while query.get_status() == HTTPClient.STATUS_BODY:
		query.poll()
		chunks.append_array(query.read_response_body_chunk())
		await get_tree().process_frame
	var parsed := JSON.parse_string(chunks.get_string_from_utf8())
	if query.get_response_code() >= 300:
		var detail := str(parsed.get("detail", "")) if parsed is Dictionary else ""
		emit_signal("bridge_error", str(parsed.get("error", "http")) + ": " + detail)
		return err
	return [parsed]


func _call(path: String, method: int, body: Variant = null) -> Variant:
	var out: Variant = await _request(path, method, body)
	if out is Array and out.is_empty():
		return null
	return out[0]


# -- runtime mirror ------------------------------------------------------

func submit(kind: String, npc_id: String, speaker_id: Variant = null, text: Variant = null) -> void:
	await _call("/v1/submit", HTTPClient.METHOD_POST, {
		"kind": kind, "npc_id": npc_id, "speaker_id": speaker_id, "text": text})


func pump() -> int:
	var out: Variant = await _call("/v1/pump", HTTPClient.METHOD_POST, {})
	return int(out["resolved"]) if out is Dictionary else 0


func engage(player_id: String, action_name: String, parameters: Dictionary, duration: float) -> String:
	var out: Variant = await _call("/v1/engage", HTTPClient.METHOD_POST, {
		"player_id": player_id, "name": action_name,
		"parameters": parameters, "duration": duration})
	return str(out["handle"]) if out is Dictionary else ""


func cancel(handle: String) -> void:
	await _call("/v1/cancel", HTTPClient.METHOD_POST, {"handle": handle})


func observations(character_id: String) -> Array:
	var out: Variant = await _call(
		"/v1/observations?character_id=" + character_id.uri_encode(), HTTPClient.METHOD_GET)
	return out["records"] if out is Dictionary else []


func memory(npc_id: String) -> Dictionary:
	var out: Variant = await _call(
		"/v1/memory?npc_id=" + npc_id.uri_encode(), HTTPClient.METHOD_GET)
	return out if out is Dictionary else {"players": [], "npcs": []}


func surroundings(npc_id: String, radius: float = 20.0) -> Array:
	var out: Variant = await _call(
		"/v1/surroundings?npc_id=" + npc_id.uri_encode() + "&radius=%f" % radius,
		HTTPClient.METHOD_GET)
	return out["places"] if out is Dictionary else []


func knowledge(npc_id: String, actor_id: String = "", limit: int = -1) -> Dictionary:
	var path := "/v1/knowledge?npc_id=" + npc_id.uri_encode()
	if actor_id != "":
		path += "&actor_id=" + actor_id.uri_encode()
	if limit >= 0:
		path += "&limit=%d" % limit
	var out: Variant = await _call(path, HTTPClient.METHOD_GET)
	return out if out is Dictionary else {"history": [], "acquaintances": {}}


func register_action(action_name: String, parameters: Dictionary,
		min_implication: float = 0.0, broadcast: bool = false) -> void:
	await _call("/v1/register_action", HTTPClient.METHOD_POST, {
		"name": action_name, "parameters": parameters,
		"min_implication": min_implication, "broadcast": broadcast})


func sync_nodes(players: Array = [], npcs: Array = []) -> void:
	# Entries: {"node": Node2D/Node3D, "id": String, "horizon": float}
	var ps: Array = []
	for p in players:
		ps.append({"id": p["id"], "position": _vec(p["node"].position),
			"horizon": p.get("horizon", 10.0)})
	var ns: Array = []
	for n in npcs:
		ns.append({"id": n["id"], "position": _vec(n["node"].position),
			"horizon": n.get("horizon", 10.0)})
	await _call("/v1/sync", HTTPClient.METHOD_POST, {"players": ps, "npcs": ns})


func _vec(v: Variant) -> Array:
	if v is Vector3:
		return [v.x, v.y, v.z]
	return [v.x, v.y]


# -- per-frame driver ------------------------------------------------------

## Call once per _process: pumps, then emits remote_action/speech signals.
func tick() -> void:
	if _busy:
		return
	_busy = true
	await pump()
	var a: Variant = await _call("/v1/actions?since=%d" % _action_cursor, HTTPClient.METHOD_GET)
	if a is Dictionary:
		_action_cursor = int(a["next_since"])
		for action in a["actions"]:
			emit_signal("remote_action", action)
	var d: Variant = await _call("/v1/delivered?since=%d" % _delivered_cursor, HTTPClient.METHOD_GET)
	if d is Dictionary:
		_delivered_cursor = int(d["next_since"])
		for pair in d["delivered"]:
			emit_signal("speech", str(pair[0]), str(pair[1]))
	_busy = false
