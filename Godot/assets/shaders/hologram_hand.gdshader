shader_type spatial;
render_mode blend_mix, depth_prepass_alpha, cull_back;

uniform vec4 core_color : source_color = vec4(0.44, 0.72, 0.68, 0.74);
uniform float alpha : hint_range(0.0, 1.0) = 0.68;
uniform float rim_power : hint_range(0.8, 6.0) = 2.4;
uniform float scanline_strength : hint_range(0.0, 1.0) = 0.018;
uniform float pulse_speed : hint_range(0.0, 4.0) = 0.18;
uniform float pulse_offset = 0.0;

varying vec3 world_pos;

void vertex() {
	world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
	float view_facing = abs(dot(normalize(NORMAL), normalize(VIEW)));
	float rim = pow(1.0 - view_facing, rim_power);
	float scan = sin((world_pos.y * 11.0 + TIME * pulse_speed + pulse_offset) * 6.2831853) * 0.5 + 0.5;
	float pulse = sin(TIME * pulse_speed * 1.7 + pulse_offset) * 0.5 + 0.5;
	vec3 body = mix(core_color.rgb * 0.62, core_color.rgb * 0.82, view_facing);
	vec3 color = body + core_color.rgb * (rim * 0.11 + scan * scanline_strength + pulse * 0.008);

	ALBEDO = color;
	EMISSION = core_color.rgb * (0.012 + rim * 0.08 + scan * scanline_strength * 0.6);
	ALPHA = clamp(alpha * (0.97 + rim * 0.05) + scan * 0.006, 0.0, 0.94);
	ALPHA_SCISSOR_THRESHOLD = 0.5;
	METALLIC = 0.0;
	ROUGHNESS = 0.56;
	SPECULAR = 0.24;
}
