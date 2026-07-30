extends SceneTree


const DEFAULT_SESSION_ROOT := (
	"res://assets/processed_sessions/"
	+ "session_kinect_20260623_154953_virtual_hand_v8_mano_rgbd_hard9"
)


func _initialize() -> void:
	var session_root := DEFAULT_SESSION_ROOT
	var expected_frames := 9
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with("--session-root="):
			session_root = argument.trim_prefix("--session-root=")
		elif argument.begins_with("--expected-frames="):
			expected_frames = int(argument.trim_prefix("--expected-frames="))

	var main_script := load("res://scripts/main.gd")
	if main_script == null:
		push_error("Cannot load main.gd")
		quit(1)
		return

	var session_file := FileAccess.open(
		session_root.path_join("session.json"), FileAccess.READ
	)
	var manifest_file := FileAccess.open(
		session_root.path_join("processed_manifest.json"), FileAccess.READ
	)
	if session_file == null or manifest_file == null:
		push_error("Cannot open MANO preview session/manifest")
		quit(1)
		return
	var session = JSON.parse_string(session_file.get_as_text())
	var manifest = JSON.parse_string(manifest_file.get_as_text())
	if (
		typeof(session) != TYPE_DICTIONARY
		or typeof(manifest) != TYPE_DICTIONARY
		or manifest.get("frames", []).size() != expected_frames
	):
		push_error("Invalid MANO preview session/manifest")
		quit(1)
		return

	var mesh_frame: Dictionary = {}
	for candidate in manifest["frames"]:
		if (
			typeof(candidate) == TYPE_DICTIONARY
			and str(candidate.get("virtualHandMesh", "")) != ""
		):
			mesh_frame = candidate
			break
	if mesh_frame.is_empty():
		push_error("MANO session contains no mesh frame")
		quit(1)
		return
	var mesh_path := session_root.path_join(
		str(mesh_frame.get("virtualHandMesh", ""))
	)
	var node := Node3D.new()
	node.set_script(main_script)
	root.add_child(node)
	node.gesture_layer = Node3D.new()
	node.add_child(node.gesture_layer)
	node.data_sources = {"virtual_hand_mesh": mesh_path}
	node.processed_surface_frames = manifest["frames"]
	node.call("_build_mano_hand_surface")

	var mesh_node: MeshInstance3D = node.mano_hand_surface_node
	if mesh_node == null or not mesh_node.visible or mesh_node.mesh == null:
		push_error("MANO preview mesh node did not build")
		quit(1)
		return
	var mesh: ArrayMesh = mesh_node.mesh
	var arrays := mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
	var indices: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
	if (
		vertices.size() != 778
		or normals.size() != 778
		or indices.size() != 1538 * 3
	):
		push_error(
			"Unexpected MANO mesh sizes: %d/%d/%d"
			% [vertices.size(), normals.size(), indices.size()]
		)
		quit(1)
		return

	var material: StandardMaterial3D = node.mano_hand_material
	if (
		material == null
		or material.transparency != BaseMaterial3D.TRANSPARENCY_DISABLED
		or material.depth_draw_mode
			!= BaseMaterial3D.DEPTH_DRAW_OPAQUE_ONLY
	):
		push_error("MANO preview material is not opaque/depth-writing")
		quit(1)
		return

	print(
		"MANO preview validated: frames=%d vertices=%d faces=%d aabb=%s"
		% [
			expected_frames,
			vertices.size(),
			indices.size() / 3,
			str(mesh.get_aabb())
		]
	)
	quit()
