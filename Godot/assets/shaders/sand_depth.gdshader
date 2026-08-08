shader_type spatial;
render_mode cull_back, depth_draw_opaque, unshaded;

uniform float arg_1 = 1.0f;
uniform float arg_2 = 1.0f;
uniform float background = 0.5f;
uniform float eps_0 = 0.02f;
uniform float eps_1 = 0.08f;
uniform float displacement_scale = 1.0f;
uniform float baseline_height_offset = 0.0f;
uniform float material_strength = 0.0f;
uniform float depth_view_slope_strength = 1.35f;

// Camera-independent world-space lighting controls.
// Direction points from the surface toward the fixed key light.
uniform vec3 fixed_light_direction_world = vec3(-0.45, 0.82, 0.35);
uniform float fixed_light_strength = 0.50;
uniform float fixed_ambient_strength = 0.68;

// Physical depth encoding contract parameters
uniform float detail_scale_m = 0.004;
uniform float neutral_gray = 128.0;

// Configurable depth-derived cavity / curvature controls
uniform float cavity_strength = 0.35;
uniform float cavity_clamp = 0.50;
uniform float noise_threshold_m = 0.0005;

// Optional A/B comparison toggle for RGB edge detection
uniform bool use_rgb_grooves = false;
uniform float rgb_groove_strength = 0.0;

uniform vec3 base_sand_color = vec3(0.66, 0.64, 0.58);
uniform vec2 depth_uv_offset = vec2(0.0, 0.0);
uniform vec2 depth_uv_scale = vec2(1.0, 1.0);
uniform vec2 texture_uv_offset = vec2(0.0, 0.0);
uniform vec2 texture_uv_scale = vec2(1.0, 1.0);
uniform sampler2D texture_map;
uniform sampler2D depth_map;
uniform sampler2D surface_mask;
uniform bool use_surface_mask = false;

float sample_surface_mask(vec2 uv) {
	if (!use_surface_mask) {
		return 1.0;
	}
	float mask = texture(surface_mask, uv).r;
	float border = min(min(uv.x, 1.0 - uv.x), min(uv.y, 1.0 - uv.y));
	float border_fade = smoothstep(0.0, 0.02, border);
	return clamp(mask * border_fade, 0.0, 1.0);
}

float check_depth(vec2 uv) {
	vec2 sample_uv = uv * depth_uv_scale + depth_uv_offset;
	float texel = 1.0f / float(textureSize(depth_map, 0).x);
	float h = 0.0;
	h += texture(depth_map, sample_uv + vec2(-texel, -texel)).r;
	h += texture(depth_map, sample_uv + vec2( 0.0,   -texel)).r;
	h += texture(depth_map, sample_uv + vec2( texel, -texel)).r;
	h += texture(depth_map, sample_uv + vec2(-texel,  0.0)).r;
	h += texture(depth_map, sample_uv + vec2( 0.0,    0.0)).r;
	h += texture(depth_map, sample_uv + vec2( texel,  0.0)).r;
	h += texture(depth_map, sample_uv + vec2(-texel,  texel)).r;
	h += texture(depth_map, sample_uv + vec2( 0.0,    texel)).r;
	h += texture(depth_map, sample_uv + vec2( texel,  texel)).r;
	h /= 9.0;
	float d = abs(h - background);
	float keep = smoothstep(eps_0, eps_1, d);
	h = mix(background, h, keep);
	return h;
}

// Convert encoded 0..1 depth map value to physical delta height in meters
float depth_to_meters(float raw_h) {
	float normalized_delta = (raw_h * 255.0 - neutral_gray) / 96.0;
	return -normalized_delta * detail_scale_m;
}

float rgb_luminance(vec2 uv) {
	vec3 color = texture(texture_map, clamp(uv, vec2(0.0), vec2(1.0))).rgb;
	return dot(color, vec3(0.299, 0.587, 0.114));
}

float rgb_groove_signal(vec2 uv) {
	if (!use_rgb_grooves || rgb_groove_strength <= 0.001) {
		return 0.0;
	}
	vec2 texel = 1.0 / vec2(textureSize(texture_map, 0));
	float center = rgb_luminance(uv);
	float neighborhood = 0.0;
	neighborhood += rgb_luminance(uv + vec2(-texel.x, -texel.y));
	neighborhood += rgb_luminance(uv + vec2(0.0, -texel.y));
	neighborhood += rgb_luminance(uv + vec2(texel.x, -texel.y));
	neighborhood += rgb_luminance(uv + vec2(-texel.x, 0.0));
	neighborhood += rgb_luminance(uv + vec2(texel.x, 0.0));
	neighborhood += rgb_luminance(uv + vec2(-texel.x, texel.y));
	neighborhood += rgb_luminance(uv + vec2(0.0, texel.y));
	neighborhood += rgb_luminance(uv + vec2(texel.x, texel.y));
	neighborhood /= 8.0;
	float dark_contrast = max(0.0, neighborhood - center);
	float edge_gate = smoothstep(0.008, 0.075, dark_contrast);
	return edge_gate * clamp(dark_contrast * 8.0 * rgb_groove_strength, 0.0, 1.0);
}

void vertex() {
	float mask = sample_surface_mask(UV);
	float h = check_depth(UV);
	h = mix(background, h, mask);
	h += baseline_height_offset * mask;
	VERTEX.y -= (h / arg_1) * displacement_scale;
}

void fragment() {
	vec2 texture_uv = UV * texture_uv_scale + texture_uv_offset;
	vec4 tex = texture(texture_map, texture_uv);
	float mask = sample_surface_mask(UV);
	if (mask < 0.5) {
		discard;
	}
	float h = check_depth(UV);
	h += baseline_height_offset * mask;

	// Physical texel dimensions (plane mesh 5.5m x 5.5m)
	vec2 tex_size = vec2(textureSize(depth_map, 0));
	vec2 texel_uv = 1.5 / tex_size;
	float world_dx = 5.5 / max(tex_size.x, 1.0);
	float world_dy = 5.5 / max(tex_size.y, 1.0);

	// 4-tap Central Difference with Discontinuity Safeguards
	float h_c = depth_to_meters(h);
	float raw_l = check_depth(UV + vec2(-texel_uv.x, 0.0));
	float raw_r = check_depth(UV + vec2( texel_uv.x, 0.0));
	float raw_u = check_depth(UV + vec2(0.0, -texel_uv.y));
	float raw_d = check_depth(UV + vec2(0.0,  texel_uv.y));

	float h_l = depth_to_meters(raw_l);
	float h_r = depth_to_meters(raw_r);
	float h_u = depth_to_meters(raw_u);
	float h_d = depth_to_meters(raw_d);

	// Reject Discontinuities (e.g. step size > 15mm across occlusion / hand borders)
	const float MAX_DISCONTINUITY_M = 0.015;
	if (abs(h_l - h_c) > MAX_DISCONTINUITY_M) h_l = h_c;
	if (abs(h_r - h_c) > MAX_DISCONTINUITY_M) h_r = h_c;
	if (abs(h_u - h_c) > MAX_DISCONTINUITY_M) h_u = h_c;
	if (abs(h_d - h_c) > MAX_DISCONTINUITY_M) h_d = h_c;

	// Central Difference Gradients with Noise Floor Suppression
	float dh_dx = (h_r - h_l) / (2.0 * world_dx);
	float dh_dy = (h_d - h_u) / (2.0 * world_dy);
	if (abs(h_r - h_l) < noise_threshold_m) dh_dx = 0.0;
	if (abs(h_d - h_u) < noise_threshold_m) dh_dy = 0.0;

	// The sampled slope is in the plane's local space, while fragment NORMAL
    // and Godot's LIGHT vector are in view space. Transform this direction into
    // view space so moving the camera does not rotate the apparent lighting.
    vec3 depth_slope_normal_local = normalize(vec3(-dh_dx * 2.5, 1.0, -dh_dy * 2.5));
    vec3 depth_slope_normal_world = normalize(
        MODEL_NORMAL_MATRIX * depth_slope_normal_local
    );

	vec3 flat_normal_world = normalize(MODEL_NORMAL_MATRIX * vec3(0.0, 1.0, 0.0));
	vec3 geometric_normal_view = normalize(cross(dFdx(VERTEX), dFdy(VERTEX)));
	vec3 geometric_normal_world = normalize(mat3(INV_VIEW_MATRIX) * geometric_normal_view);
	if (dot(geometric_normal_world, flat_normal_world) < 0.0) {
		geometric_normal_world = -geometric_normal_world;
	}
	vec3 surface_normal_world = normalize(
		mix(depth_slope_normal_world, geometric_normal_world, 0.35)
	);
	NORMAL = normalize(mat3(VIEW_MATRIX) * surface_normal_world);

	// Depth Relief & Noise-Floor Suppressed Cavity Occlusion
	float relief = (h - background) * 0.85;
	float shade = clamp(0.98 + relief * 0.55 - abs(relief) * 0.10, 0.72, 1.16);

	float laplacian_m = (h_l + h_r + h_u + h_d - 4.0 * h_c);
	float depth_cavity = 0.0;
	if (abs(laplacian_m) > noise_threshold_m) {
		depth_cavity = clamp(laplacian_m * 80.0 * cavity_strength, -0.20, cavity_clamp);
	}

	float grain = dot(tex.rgb, vec3(0.299, 0.587, 0.114));
	vec3 subtle_texture = base_sand_color * mix(0.78, 1.14, grain);
	vec3 material_color = mix(subtle_texture, tex.rgb, 0.88);
	vec3 mapped_color = mix(base_sand_color, material_color, clamp(material_strength, 0.0, 1.0));

	float rgb_groove = rgb_groove_signal(UV) * mask;
	vec3 groove_mapped = mapped_color * (1.0 - rgb_groove * 0.40);

	float depth_view = mix(0.32, 1.0, 1.0 - smoothstep(0.0, 0.62, material_strength));
	float slope = clamp(1.0 - dot(surface_normal_world, flat_normal_world), 0.0, 1.0);
	float slope_shade = clamp(
		1.04 - slope * depth_view_slope_strength,
		0.50,
		1.08
	);

	vec3 fixed_light_direction = normalize(fixed_light_direction_world);
	float fixed_diffuse = max(dot(surface_normal_world, fixed_light_direction), 0.0);
	float stable_light = clamp(
		fixed_ambient_strength + fixed_diffuse * fixed_light_strength,
		0.0,
		1.18
	);

	vec3 depth_shaded_color = (
		groove_mapped * shade - vec3(depth_cavity * 0.28)
	) * mix(1.0, slope_shade, depth_view);
	ALBEDO = max(depth_shaded_color * stable_light, vec3(0.0));
	ROUGHNESS = mix(0.86, 0.94, depth_view);
	SPECULAR = 0.0;
}

//void light() {
//	// Called for every pixel for every light affecting the material.
//	// Uncomment to replace the default light processing function with this one.
//}
