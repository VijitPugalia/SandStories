extends SceneTree

const WIDTH := 960
const HEIGHT := 720
const SURFACE_WIDTH := 5.6
const SURFACE_DEPTH := 4.2
const HEIGHT_SCALE := 0.62
const NORMAL_STRENGTH := 0.42

const LIGHT_PRESETS := {
	"left": {"rotation": Vector3(-58.0, -42.0, 0.0), "energy": 4.2},
	"right": {"rotation": Vector3(-58.0, 42.0, 0.0), "energy": 4.2},
	"raking": {"rotation": Vector3(-28.0, -62.0, 0.0), "energy": 4.8},
}

const CAMERA_PRESETS := {
	"top": {"position": Vector3(0.0, 7.5, 0.01), "target": Vector3.ZERO, "up": Vector3.FORWARD, "size": 6.45},
	"oblique": {"position": Vector3(4.0, 6.2, 4.2), "target": Vector3(0.0, -0.04, 0.0), "up": Vector3.UP, "size": 6.25},
	"low": {"position": Vector3(-4.8, 3.15, 5.4), "target": Vector3(0.0, -0.03, 0.0), "up": Vector3.UP, "size": 6.25},
}

const DEPTH_SHADER := """
shader_type spatial;
render_mode cull_back, depth_draw_opaque;

uniform sampler2D depth_map : filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D surface_mask : filter_linear, repeat_disable;
uniform sampler2D rgb_map : filter_linear_mipmap_anisotropic, repeat_disable;
uniform float height_scale = 0.62;
uniform float normal_strength = 0.42;
uniform vec3 sand_color = vec3(0.58, 0.55, 0.48);
uniform bool use_rgb = false;
uniform float rgb_gain = 0.42;

float valid_mask(vec2 uv) {
	float border = min(min(uv.x, 1.0 - uv.x), min(uv.y, 1.0 - uv.y));
	return texture(surface_mask, uv).r * smoothstep(0.0, 0.012, border);
}

float sample_height(vec2 uv) {
	vec2 texel = 1.0 / vec2(textureSize(depth_map, 0));
	float depth = 0.0;
	depth += texture(depth_map, uv + texel * vec2(-1.0, -1.0)).r;
	depth += texture(depth_map, uv + texel * vec2( 0.0, -1.0)).r;
	depth += texture(depth_map, uv + texel * vec2( 1.0, -1.0)).r;
	depth += texture(depth_map, uv + texel * vec2(-1.0,  0.0)).r;
	depth += texture(depth_map, uv).r * 2.0;
	depth += texture(depth_map, uv + texel * vec2( 1.0,  0.0)).r;
	depth += texture(depth_map, uv + texel * vec2(-1.0,  1.0)).r;
	depth += texture(depth_map, uv + texel * vec2( 0.0,  1.0)).r;
	depth += texture(depth_map, uv + texel * vec2( 1.0,  1.0)).r;
	depth /= 10.0;
	return (0.5 - depth) * height_scale * valid_mask(uv);
}

void vertex() {
	VERTEX.y += sample_height(UV);
}

void fragment() {
	vec2 texel = 1.0 / vec2(textureSize(depth_map, 0));
	float h_l = sample_height(UV - vec2(texel.x, 0.0));
	float h_r = sample_height(UV + vec2(texel.x, 0.0));
	float h_d = sample_height(UV - vec2(0.0, texel.y));
	float h_u = sample_height(UV + vec2(0.0, texel.y));
	vec3 tangent_x = vec3(2.0 * texel.x * 5.6, (h_r - h_l) * normal_strength, 0.0);
	vec3 tangent_z = vec3(0.0, (h_u - h_d) * normal_strength, 2.0 * texel.y * 4.2);
	NORMAL = normalize(cross(tangent_z, tangent_x));
	float mask = valid_mask(UV);
	vec3 base = use_rgb ? texture(rgb_map, UV).rgb * rgb_gain : sand_color;
	ALBEDO = base * mix(0.72, 1.06, mask);
	ROUGHNESS = 0.94;
}
"""

var output_dir := ""
var mask_path := ""
var jobs: Array[Dictionary] = []


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() < 3:
		push_error("Usage: --output DIR --mask MASK --job FRAME:DEPTH[:LIGHT] ...")
		quit(2)
		return
	_parse_args(args)
	if output_dir.is_empty() or mask_path.is_empty() or jobs.is_empty():
		push_error("Missing --output, --mask, or --job")
		quit(2)
		return
	DirAccess.make_dir_recursive_absolute(output_dir)
	call_deferred("_render_all")


func _parse_args(args: PackedStringArray) -> void:
	var index := 0
	while index < args.size():
		match args[index]:
			"--output":
				index += 1
				output_dir = args[index]
			"--mask":
				index += 1
				mask_path = args[index]
			"--job":
				index += 1
				var parts := args[index].split("|")
				if parts.size() >= 2:
					jobs.append({
						"frame": parts[0],
						"depth": parts[1],
						"light": parts[2] if parts.size() > 2 else "left",
						"camera": parts[3] if parts.size() > 3 else "top",
						"style": parts[4] if parts.size() > 4 else "clay",
						"rgb": parts[5] if parts.size() > 5 else "",
					})
		index += 1


func _render_all() -> void:
	var mask_texture := _load_texture(mask_path)
	if mask_texture == null:
		push_error("Cannot load mask: " + mask_path)
		quit(3)
		return

	for job in jobs:
		var depth_texture := _load_texture(str(job.depth))
		if depth_texture == null:
			push_error("Cannot load depth: " + str(job.depth))
			continue
		var rgb_texture: Texture2D = null
		if not str(job.rgb).is_empty():
			rgb_texture = _load_texture(str(job.rgb))
		await _render_job(job, depth_texture, mask_texture, rgb_texture)
	quit()


func _render_job(job: Dictionary, depth_texture: Texture2D, mask_texture: Texture2D, rgb_texture: Texture2D) -> void:
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
	environment.background_color = Color(0.075, 0.078, 0.074)
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = Color(0.72, 0.75, 0.72)
	environment.ambient_light_energy = 0.42
	world.environment = environment

	var surface := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(SURFACE_WIDTH, SURFACE_DEPTH)
	plane.subdivide_width = 319
	plane.subdivide_depth = 239
	surface.mesh = plane
	var material := ShaderMaterial.new()
	var shader := Shader.new()
	var style := str(job.style)
	shader.code = DEPTH_SHADER.replace("render_mode cull_back, depth_draw_opaque;", "render_mode wireframe, cull_back, depth_draw_opaque;") if style == "wire" else DEPTH_SHADER
	material.shader = shader
	material.set_shader_parameter("depth_map", depth_texture)
	material.set_shader_parameter("surface_mask", mask_texture)
	material.set_shader_parameter("height_scale", HEIGHT_SCALE)
	material.set_shader_parameter("normal_strength", NORMAL_STRENGTH)
	if style == "rgb" and rgb_texture != null:
		material.set_shader_parameter("rgb_map", rgb_texture)
		material.set_shader_parameter("use_rgb", true)
	elif style == "wire":
		material.set_shader_parameter("sand_color", Vector3(0.04, 0.72, 0.96))
	surface.material_override = material
	viewport.add_child(surface)

	var light_name := str(job.light)
	var preset: Dictionary = LIGHT_PRESETS.get(light_name, LIGHT_PRESETS.left)
	var light := DirectionalLight3D.new()
	light.rotation_degrees = preset.rotation
	light.light_energy = float(preset.energy) * (0.34 if style == "rgb" else 0.78)
	light.light_color = Color(1.0, 0.97, 0.90)
	light.shadow_enabled = true
	viewport.add_child(light)

	var fill := DirectionalLight3D.new()
	fill.rotation_degrees = Vector3(-68.0, 145.0, 0.0)
	fill.light_energy = 0.22 if style == "rgb" else 0.55
	fill.light_color = Color(0.66, 0.76, 0.92)
	fill.shadow_enabled = false
	viewport.add_child(fill)

	var camera := Camera3D.new()
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	var camera_name := str(job.camera)
	var camera_preset: Dictionary = CAMERA_PRESETS.get(camera_name, CAMERA_PRESETS.top)
	camera.size = float(camera_preset.size)
	camera.near = 0.1
	camera.far = 30.0
	viewport.add_child(camera)
	camera.look_at_from_position(camera_preset.position, camera_preset.target, camera_preset.up)
	camera.current = true

	await process_frame
	await process_frame
	await process_frame
	RenderingServer.force_draw(false)
	await process_frame

	var image := viewport.get_texture().get_image()
	var filename := "reconstruction_%s_%s_%s_%s.png" % [str(job.frame), light_name, camera_name, style]
	var result := image.save_png(output_dir.path_join(filename))
	if result != OK:
		push_error("Failed to save " + filename)
	else:
		print("Saved ", output_dir.path_join(filename))
	viewport.queue_free()
	await process_frame


func _load_texture(path: String) -> ImageTexture:
	var image := Image.new()
	if image.load(path) != OK:
		return null
	image.generate_mipmaps()
	return ImageTexture.create_from_image(image)
