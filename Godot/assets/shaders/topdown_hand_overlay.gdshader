shader_type spatial;
render_mode blend_mix, depth_draw_never, depth_test_disabled, cull_disabled, unshaded;

uniform float arg_1 = 11.625;
uniform float background = 1.0;
uniform float eps_0 = 0.08;
uniform float eps_1 = 0.415;
uniform float displacement_scale = 1.0;
uniform float baseline_height_offset = 0.0;
uniform float hand_lift = 0.032;
uniform vec2 depth_uv_offset = vec2(0.0, 0.0);
uniform vec2 depth_uv_scale = vec2(1.0, 1.0);
uniform vec2 texture_uv_offset = vec2(0.0, 0.0);
uniform vec2 texture_uv_scale = vec2(1.0, 1.0);
uniform sampler2D depth_map;
uniform sampler2D hand_overlay : source_color;

float check_depth(vec2 uv) {
	vec2 sample_uv = uv * depth_uv_scale + depth_uv_offset;
	float texel = 1.0 / float(textureSize(depth_map, 0).x);
	float h = 0.0;
	h += texture(depth_map, sample_uv + vec2(-texel, -texel)).r;
	h += texture(depth_map, sample_uv + vec2( 0.0,   -texel)).r;
	h += texture(depth_map, sample_uv + vec2( texel, -texel)).r;
	h += texture(depth_map, sample_uv + vec2(-texel,  0.0)).r;
	h += texture(depth_map, sample_uv).r;
	h += texture(depth_map, sample_uv + vec2( texel,  0.0)).r;
	h += texture(depth_map, sample_uv + vec2(-texel,  texel)).r;
	h += texture(depth_map, sample_uv + vec2( 0.0,    texel)).r;
	h += texture(depth_map, sample_uv + vec2( texel,  texel)).r;
	h /= 9.0;
	float keep = smoothstep(eps_0, eps_1, abs(h - background));
	return mix(background, h, keep);
}

void vertex() {
	float h = check_depth(UV) + baseline_height_offset;
	VERTEX.y -= (h / arg_1) * displacement_scale;
	VERTEX.y += hand_lift;
}

void fragment() {
	vec2 texture_uv = UV * texture_uv_scale + texture_uv_offset;
	vec4 overlay = texture(hand_overlay, texture_uv);
	if (overlay.a < 0.02) {
		discard;
	}
	ALBEDO = overlay.rgb;
	EMISSION = overlay.rgb * 0.035;
	ALPHA = overlay.a;
}
