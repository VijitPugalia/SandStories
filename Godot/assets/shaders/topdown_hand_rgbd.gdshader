shader_type spatial;
render_mode blend_mix, depth_draw_opaque, cull_disabled, unshaded;

uniform float arg_1 = 11.625;
uniform float background = 1.0;
uniform float eps_0 = 0.08;
uniform float eps_1 = 0.415;
uniform float displacement_scale = 1.0;
uniform float baseline_height_offset = 0.0;
uniform float hand_clearance = 0.006;
uniform float hand_max_lift_meters = 0.36;
uniform float hand_world_units_per_meter = 3.0;
uniform vec2 depth_uv_offset = vec2(0.0, 0.0);
uniform vec2 depth_uv_scale = vec2(1.0, 1.0);
uniform vec2 texture_uv_offset = vec2(0.0, 0.0);
uniform vec2 texture_uv_scale = vec2(1.0, 1.0);
uniform sampler2D depth_map;
uniform sampler2D hand_overlay : source_color;
uniform sampler2D hand_geometry;

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

float measured_lift_world(vec2 uv) {
	vec2 geometry_uv = uv * texture_uv_scale + texture_uv_offset;
	float encoded_lift = texture(hand_geometry, geometry_uv).r;
	return encoded_lift * hand_max_lift_meters * hand_world_units_per_meter;
}

void vertex() {
	float sand_height = check_depth(UV) + baseline_height_offset;
	VERTEX.y -= (sand_height / arg_1) * displacement_scale;
	VERTEX.y += measured_lift_world(UV) + hand_clearance;
}

void fragment() {
	vec2 texture_uv = UV * texture_uv_scale + texture_uv_offset;
	vec4 overlay = texture(hand_overlay, texture_uv);
	if (overlay.a < 0.35) {
		discard;
	}

	vec2 texture_size = vec2(textureSize(hand_geometry, 0));
	vec2 texel = 1.0 / texture_size;
	float left = measured_lift_world(UV - vec2(texel.x, 0.0));
	float right = measured_lift_world(UV + vec2(texel.x, 0.0));
	float up = measured_lift_world(UV - vec2(0.0, texel.y));
	float down = measured_lift_world(UV + vec2(0.0, texel.y));
	float pixel_world_x = 5.5 / texture_size.x;
	float pixel_world_y = 5.5 / texture_size.y;
	float slope_x = (right - left) / max(2.0 * pixel_world_x, 0.0001);
	float slope_y = (down - up) / max(2.0 * pixel_world_y, 0.0001);
	vec3 measured_normal = normalize(vec3(-slope_x, 1.0, -slope_y));
	vec3 light_direction = normalize(vec3(-0.38, 0.82, 0.43));
	float diffuse = clamp(dot(measured_normal, light_direction), 0.0, 1.0);
	float confidence = texture(hand_geometry, texture_uv).g;
	float shade = mix(0.82, 1.16, diffuse);
	shade = mix(0.94, shade, smoothstep(0.02, 0.35, confidence));

	ALBEDO = clamp(overlay.rgb * shade, vec3(0.0), vec3(1.0));
	EMISSION = overlay.rgb * 0.018;
}
