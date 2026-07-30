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
uniform float shell_texture_strength = 0.58;
uniform float shell_edge_extension_texels = 2.0;
uniform float shell_normal_radius_texels = 2.0;
uniform vec3 shell_color : source_color = vec3(0.72, 0.43, 0.34);
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

float overlay_alpha(vec2 uv) {
	vec2 texture_uv = uv * texture_uv_scale + texture_uv_offset;
	return texture(hand_overlay, texture_uv).a;
}

vec2 measured_lift_and_weight(vec2 uv) {
	float weight = step(0.35, overlay_alpha(uv));
	return vec2(measured_lift_world(uv) * weight, weight);
}

float edge_extended_lift_world(vec2 uv) {
	float center_lift = measured_lift_world(uv);
	if (overlay_alpha(uv) >= 0.35) {
		return center_lift;
	}

	vec2 texel = 1.0 / vec2(textureSize(hand_geometry, 0));
	vec2 radius = texel * shell_edge_extension_texels;
	vec2 half_radius = radius * 0.5;
	vec2 accumulated = vec2(0.0);
	accumulated += measured_lift_and_weight(uv + vec2( half_radius.x, 0.0));
	accumulated += measured_lift_and_weight(uv + vec2(-half_radius.x, 0.0));
	accumulated += measured_lift_and_weight(uv + vec2(0.0,  half_radius.y));
	accumulated += measured_lift_and_weight(uv + vec2(0.0, -half_radius.y));
	accumulated += measured_lift_and_weight(uv + vec2( half_radius.x,  half_radius.y));
	accumulated += measured_lift_and_weight(uv + vec2(-half_radius.x,  half_radius.y));
	accumulated += measured_lift_and_weight(uv + vec2( half_radius.x, -half_radius.y));
	accumulated += measured_lift_and_weight(uv + vec2(-half_radius.x, -half_radius.y));
	accumulated += measured_lift_and_weight(uv + vec2( radius.x, 0.0));
	accumulated += measured_lift_and_weight(uv + vec2(-radius.x, 0.0));
	accumulated += measured_lift_and_weight(uv + vec2(0.0,  radius.y));
	accumulated += measured_lift_and_weight(uv + vec2(0.0, -radius.y));
	accumulated += measured_lift_and_weight(uv + vec2( radius.x,  radius.y));
	accumulated += measured_lift_and_weight(uv + vec2(-radius.x,  radius.y));
	accumulated += measured_lift_and_weight(uv + vec2( radius.x, -radius.y));
	accumulated += measured_lift_and_weight(uv + vec2(-radius.x, -radius.y));
	if (accumulated.y > 0.0) {
		return accumulated.x / accumulated.y;
	}
	return center_lift;
}

void vertex() {
	float sand_height = check_depth(UV) + baseline_height_offset;
	VERTEX.y -= (sand_height / arg_1) * displacement_scale;
	VERTEX.y += edge_extended_lift_world(UV) + hand_clearance;
}

void fragment() {
	vec2 texture_uv = UV * texture_uv_scale + texture_uv_offset;
	vec4 overlay = texture(hand_overlay, texture_uv);
	if (overlay.a < 0.35) {
		discard;
	}

	vec2 texture_size = vec2(textureSize(hand_geometry, 0));
	vec2 texel = shell_normal_radius_texels / texture_size;
	float left = measured_lift_world(UV - vec2(texel.x, 0.0));
	float right = measured_lift_world(UV + vec2(texel.x, 0.0));
	float up = measured_lift_world(UV - vec2(0.0, texel.y));
	float down = measured_lift_world(UV + vec2(0.0, texel.y));
	float pixel_world_x = 5.5 * shell_normal_radius_texels / texture_size.x;
	float pixel_world_y = 5.5 * shell_normal_radius_texels / texture_size.y;
	float slope_x = (right - left) / max(2.0 * pixel_world_x, 0.0001);
	float slope_y = (down - up) / max(2.0 * pixel_world_y, 0.0001);
	vec3 measured_normal = normalize(vec3(-slope_x, 1.0, -slope_y));

	vec3 light_direction = normalize(vec3(-0.38, 0.82, 0.43));
	float diffuse = clamp(dot(measured_normal, light_direction), 0.0, 1.0);
	float confidence = texture(hand_geometry, texture_uv).g;
	float measured_shade = mix(0.78, 1.18, diffuse);
	measured_shade = mix(0.94, measured_shade, smoothstep(0.02, 0.35, confidence));

	float source_luminance = dot(
		overlay.rgb,
		vec3(0.2126, 0.7152, 0.0722)
	);
	float source_tone = smoothstep(0.22, 0.78, source_luminance);
	float texture_shade = mix(0.76, 1.12, source_tone);
	float shade = mix(measured_shade, measured_shade * texture_shade, shell_texture_strength);
	vec3 color = clamp(shell_color * shade, vec3(0.0), vec3(1.0));

	ALBEDO = color;
	EMISSION = color * 0.012;
}
