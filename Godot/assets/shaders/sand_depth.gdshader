shader_type spatial;
render_mode cull_back, depth_draw_opaque;
uniform float arg_1 = 1.0f;
uniform float arg_2 = 1.0f;
uniform float background = 0.5f;
uniform float eps_0 = 0.02f;
uniform float eps_1 = 0.08f;
uniform float displacement_scale = 1.0f;
uniform float baseline_height_offset = 0.0f;
uniform float material_strength = 0.0f;
uniform float depth_view_slope_strength = 1.35f;
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
    vec4 tex = texture(depth_map, sample_uv);
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

float depth_mask(vec2 uv) {
	vec2 sample_uv = uv * depth_uv_scale + depth_uv_offset;
	float h = texture(depth_map, sample_uv).r;
	float d = abs(h - background);
	float keep = smoothstep(eps_0, eps_1, d);
	float border = min(min(uv.x, 1.0 - uv.x), min(uv.y, 1.0 - uv.y));
	float border_fade = smoothstep(0.0, 0.035, border);
	return keep * border_fade;
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
	float relief = h - background;
	float shade = clamp(0.96 + relief * 0.22 - abs(relief) * 0.08, 0.76, 1.08);
	float grain = dot(tex.rgb, vec3(0.299, 0.587, 0.114));
	vec3 subtle_texture = base_sand_color * mix(0.78, 1.14, grain);
	vec3 material_color = mix(subtle_texture, tex.rgb, 0.55);
	vec3 mapped_color = mix(base_sand_color, material_color, clamp(material_strength, 0.0, 1.0));

	// The height map displaces the PlaneMesh in vertex(), but the source mesh
	// still carries a flat up-facing normal. Reconstruct the real triangle
	// normal from the displaced view-space position so raking lights reveal
	// grooves and ridges instead of shading the surface as one flat card.
	vec3 flat_normal = normalize(NORMAL);
	vec3 geometric_normal = normalize(cross(dFdx(VERTEX), dFdy(VERTEX)));
	if (dot(geometric_normal, flat_normal) < 0.0) {
		geometric_normal = -geometric_normal;
	}
	NORMAL = normalize(mix(flat_normal, geometric_normal, 0.94));

	// When Map blend is zero, turn the neutral material into a depth diagnostic
	// view. The cue is derived only from the rendered geometry: slope
	// darkening under the raking lights. It fades out before the RGB material
	// reaches its normal session strength.
	float depth_view = 1.0 - smoothstep(0.0, 0.62, material_strength);
	float slope = clamp(1.0 - dot(NORMAL, flat_normal), 0.0, 1.0);
	float slope_shade = clamp(
		1.04 - slope * depth_view_slope_strength,
		0.50,
		1.08
	);

	ALBEDO = mapped_color * shade * mix(1.0, slope_shade, depth_view);
	ROUGHNESS = mix(0.86, 0.94, depth_view);
	SPECULAR = mix(0.28, 0.12, depth_view);
}

//void light() {
//	// Called for every pixel for every light affecting the material.
//	// Uncomment to replace the default light processing function with this one.
//}
