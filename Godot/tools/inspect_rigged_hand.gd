extends SceneTree

const HAND_PATH := "res://assets/models/godot_humanoid_hands/RightHandHumanoid.gltf"

func _init() -> void:
	var resource := load(HAND_PATH)
	if resource == null:
		print("HAND_IMPORT_ERROR could not load ", HAND_PATH)
		quit(1)
		return

	print("HAND_RESOURCE ", resource.get_class())
	if resource is PackedScene:
		var root: Node = (resource as PackedScene).instantiate()
		print("HAND_SCENE_ROOT ", root.name, " ", root.get_class())
		_walk(root, 0)
		root.queue_free()
	else:
		print("HAND_RESOURCE_NOT_SCENE ", resource)
	quit()

func _walk(node: Node, depth: int) -> void:
	var indent := ""
	for _i in range(depth):
		indent += "  "
	print(indent, node.name, " [", node.get_class(), "]")
	if node is MeshInstance3D:
		var mesh: Mesh = (node as MeshInstance3D).mesh
		var surface_count: int = mesh.get_surface_count() if mesh != null else 0
		var aabb: AABB = mesh.get_aabb() if mesh != null else AABB()
		print(indent, "  MESH surfaces=", surface_count, " aabb=", aabb)
	if node is Skeleton3D:
		print(indent, "  SKELETON bones=", node.get_bone_count())
		for bone_i in range(node.get_bone_count()):
			print(
				indent,
				"    BONE ",
				bone_i,
				" name=",
				node.get_bone_name(bone_i),
				" parent=",
				node.get_bone_parent(bone_i),
				" rest=",
				node.get_bone_rest(bone_i),
				" global_rest=",
				node.get_bone_global_rest(bone_i)
			)
	for child in node.get_children():
		_walk(child, depth + 1)
