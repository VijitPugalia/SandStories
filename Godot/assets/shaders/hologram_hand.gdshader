shader_type spatial;
render_mode blend_mix, depth_draw_alpha_prepass, cull_disabled, unshaded;

uniform vec4 core_color : source_color = vec4(0.35, 0.9, 1.0, 0.42);
uniform float alpha : hint_range(0.0, 1.0) = 0.42;
uniform float rim_power : hint_range(0.8, 6.0) = 2.3;
uniform float scanline_strength : hint_range(0.0, 1.0) = 0.16;
uniform float pulse_speed : hint_range(0.0, 4.0) = 0.9;

varying vec3 world_pos;

void vertex() {
	world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
	float view_facing = clamp(dot(normalize(NORMAL), normalize(VIEW)), 0.0, 1.0);
	float rim = pow(1.0 - view_facing, rim_power);
	float scan = sin((world_pos.y * 18.0 + TIME * pulse_speed) * 6.2831853) * 0.5 + 0.5;
	float pulse = sin(TIME * pulse_speed * 2.1) * 0.5 + 0.5;
	vec3 color = core_color.rgb * (0.68 + rim * 1.8 + scan * scanline_strength + pulse * 0.08);

	ALBEDO = color;
	EMISSION = color * (0.48 + rim * 1.35);
	ALPHA = clamp(alpha + rim * 0.32 + scan * 0.035, 0.0, 0.86);
	ROUGHNESS = 0.18;
}
