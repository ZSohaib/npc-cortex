# GUT tests for the Godot client (pure mapping; no server needed).
# Live tests are commented out: start a BridgeServer (see
# examples/bridge_server.py) and uncomment to run them.
extends GutTest

var client: NpcCortexClient


func before_each() -> void:
	client = NpcCortexClient.new()
	client.base_url = "http://127.0.0.1:8471"
	add_child(client)


func after_each() -> void:
	client.queue_free()


func test_vec3_maps_by_identity_on_components() -> void:
	assert_eq(client._vec(Vector3(1, 2, 3)), [1, 2, 3])


func test_vec2_maps_by_identity_on_components() -> void:
	assert_eq(client._vec(Vector2(4, 5)), [4, 5])


func test_ready_strips_trailing_slash() -> void:
	client.base_url = "http://127.0.0.1:8471/"
	client._ready()
	assert_eq(client.base_url, "http://127.0.0.1:8471")


# -- live tests (need a BridgeServer) --------------------------------------
# func test_live_sync_and_pump() -> void:
# 	await client._call("/v1/sync", HTTPClient.METHOD_POST, {
# 		"players": [{"id": "p1", "position": [0, 0], "horizon": 50.0}],
# 		"npcs": [{"id": "n1", "position": [1, 0], "horizon": 50.0}]})
# 	await client.submit("tick", "n1")
# 	var resolved := 0
# 	for i in 100:
# 		resolved += await client.pump()
# 		if resolved > 0:
# 			break
# 	assert_gt(resolved, 0, "nothing resolved")
