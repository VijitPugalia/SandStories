extends SceneTree

const WIDTH := 960
const HEIGHT := 720
const SHADER_PATH := "res://assets/shaders/sand_depth.gdshader"

var depth_path := ""
var mask_path := ""
var rgb_path := ""
var output_dir := ""
var material_strength := 0.0


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	var index := 0
	while index < args.size():
		match args[index]:
			"--depth":
				index += 1
				depth_path = args[index]
			"--mask":
				index += 1
				mask_path = args[index]
			"--rgb":
				index += 1
				rgb_path = args[index]
			"--output":
				index += 1
				output_dir = args[index]
			"--material-strength":
				index += 1
				material_strength = float(args[index])
		index += 1
	if depth_path.is_empty() or mask_path.is_empty() or output_dir.is_empty():
		push_error(
			"Usage: --depth DEPTH --mask MASK --output DIR [--rgb RGB]"
		)
		quit(2)
		return
	DirAccess.make_dir_recursive_absolute(output_dir)
	call_deferred("_render_all")


func _render_all() -> void:
	var depth := _load_texture(depth_path)
	var mask := _load_texture(mask_path)
	var rgb := _load_texture(rgb_path) if not rgb_path.is_empty() else depth
	var shader := load(SHADER_PATH) as Shader
	if depth == null or mask == null or rgb == null or shader == null:
		push_error("Cannot load a required runtime depth-lighting resource")
		quit(3)
		return

	await _render_view(
		"top",
		Vector3(0.0, 7.5, 0.01),
		Vector3.FORWARD,
		6.2,
		depth,
		mask,
		rgb,
		shader
	)
	await _render_view(
		"oblique",
		Vector3(3.4, 5.4, 4.2),
		Vector3.UP,
		6.4,
		depth,
		mask,
		rgb,
		shader
	)
	quit()


func _render_view(
	label: String,
	camera_position: Vector3,
	camera_up: Vector3,
	camera_size: float,
	depth: Texture2D,
	mask: Texture2D,
	rgb: Texture2D,
	shader: Shader
) -> void:
	var viewport := SubViewport.new()
	viewport.size = Vector2i(WIDTH, HEIGHT)
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.render_target_clear_mode = SubViewport.CLEAR_MODE_ALWAYS
	viewport.transparent_bg = false
	root.add_child(viewport)

	var world := World3D.new()
	viewport.world_3d = world
	var environment := Environment.new()
	environment.background_mode = Environment.BG_COLOR
	environment.background_color = Color(0.58, 0.63, 0.60)
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = Color(0.55, 0.60, 0.64)
	environment.ambient_light_energy = 0.30
	world.environment = environment

	var plane := PlaneMesh.new()
	plane.size = Vector2(5.5, 5.5)
	plane.subdivide_width = 256
	plane.subdivide_depth = 256
	var surface := MeshInstance3D.new()
	surface.mesh = plane
	var material := ShaderMaterial.new()
	material.shader = shader
	material.set_shader_parameter("depth_map", depth)
	material.set_shader_parameter("texture_map", rgb)
	material.set_shader_parameter("surface_mask", mask)
	material.set_shader_parameter("use_surface_mask", true)
	material.set_shader_parameter("arg_1", 11.625)
	material.set_shader_parameter("background", 1.0)
	material.set_shader_parameter("eps_0", 0.08)
	material.set_shader_parameter("eps_1", 0.415)
	material.set_shader_parameter("displacement_scale", -5.0)
	material.set_shader_parameter("material_strength", material_strength)
	surface.material_override = material
	viewport.add_child(surface)

	var key := DirectionalLight3D.new()
	key.rotation_degrees = Vector3(-28, -42, 0)
	key.light_color = Color(1.0, 0.91, 0.78)
	key.light_energy = 1.65
	key.shadow_enabled = true
	viewport.add_child(key)

	var fill := DirectionalLight3D.new()
	fill.rotation_degrees = Vector3(-62, 132, 0)
	fill.light_color = Color(0.68, 0.80, 1.0)
	fill.light_energy = 0.34
	viewport.add_child(fill)

	var camera := Camera3D.new()
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.size = camera_size
	camera.near = 0.1
	camera.far = 30.0
	viewport.add_child(camera)
	camera.look_at_from_position(
		camera_position,
		Vector3(0.0, 0.20, 0.0),
		camera_up
	)
	camera.current = true

	for _frame in range(5):
		await process_frame
	RenderingServer.force_draw(false)
	await process_frame

	var image := viewport.get_texture().get_image()
	var output_path := output_dir.path_join(
		"runtime_depth_lighting_%s.png" % label
	)
	var result := image.save_png(output_path)
	if result != OK:
		push_error("Failed to save " + output_path)
	else:
		print("Saved ", output_path)
	viewport.queue_free()
	await process_frame


func _load_texture(path: String) -> ImageTexture:
	var image := Image.new()
	if image.load(path) != OK:
		return null
	image.generate_mipmaps()
	return ImageTexture.create_from_image(image)
