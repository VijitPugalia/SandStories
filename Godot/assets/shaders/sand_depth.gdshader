shader_type spatial;
render_mode cull_back, blend_mix, depth_prepass_alpha;
uniform float arg_1 = 1.0f;
uniform float arg_2 = 1.0f;
uniform float background = 0.5f;
uniform float eps_0 = 0.02f;
uniform float eps_1 = 0.08f;
uniform float displacement_scale = 1.0f;
uniform float material_strength = 0.0f;
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
	VERTEX.y -= (h / arg_1) * displacement_scale;
	
}

void fragment() {
	vec2 texture_uv = UV * texture_uv_scale + texture_uv_offset;
    vec4 tex = texture(texture_map, texture_uv);
	float mask = sample_surface_mask(UV);
	float h = check_depth(UV);
	float relief = h - background;
	float shade = clamp(0.90 + relief * 0.42 - abs(relief) * 0.18, 0.60, 1.08);
	float grain = dot(tex.rgb, vec3(0.299, 0.587, 0.114));
	vec3 subtle_texture = base_sand_color * mix(0.78, 1.14, grain);
	vec3 material_color = mix(subtle_texture, tex.rgb, 0.55);
	vec3 mapped_color = mix(base_sand_color, material_color, clamp(material_strength, 0.0, 1.0));
	ALBEDO = mapped_color * shade;
	ROUGHNESS = 0.92;
	ALPHA = mask;
}

//void light() {
//	// Called for every pixel for every light affecting the material.
//	// Uncomment to replace the default light processing function with this one.
//}
