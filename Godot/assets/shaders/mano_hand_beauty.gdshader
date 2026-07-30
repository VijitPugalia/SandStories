shader_type spatial;
render_mode unshaded, depth_draw_opaque, cull_disabled;

uniform vec4 base_color : source_color = vec4(0.896, 0.456, 0.348, 1.0);
uniform vec4 shadow_color : source_color = vec4(0.486, 0.159, 0.135, 1.0);
uniform vec4 highlight_color : source_color = vec4(1.0, 0.753, 0.638, 1.0);
uniform vec4 rim_color : source_color = vec4(1.0, 0.847, 0.761, 1.0);
uniform float rim_strength : hint_range(0.0, 0.8) = 0.32;
uniform float emission_strength : hint_range(0.0, 0.2) = 0.035;
uniform float roughness : hint_range(0.0, 1.0) = 0.72;

varying vec3 world_position;
varying vec3 world_normal;

void vertex() {
	world_position = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	world_normal = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
}

void fragment() {
	vec3 normal = normalize(world_normal);
	if (!FRONT_FACING) {
		normal = -normal;
	}
	vec3 view_direction = normalize(CAMERA_POSITION_WORLD - world_position);
	vec3 light_direction = normalize(vec3(-0.42, 0.84, 0.34));

	float wrapped_light = clamp(
		(dot(normal, light_direction) + 0.34) / 1.34,
		0.0,
		1.0
	);
	float soft_light = smoothstep(0.0, 1.0, wrapped_light);
	float view_facing = abs(dot(normal, view_direction));
	float rim = pow(1.0 - clamp(view_facing, 0.0, 1.0), 2.2);
	float highlight = smoothstep(0.58, 1.0, soft_light);

	vec3 color = mix(
		shadow_color.rgb,
		base_color.rgb,
		0.24 + 0.76 * soft_light
	);
	color = mix(color, highlight_color.rgb, highlight * 0.22);
	color = mix(color, rim_color.rgb, rim * rim_strength);

	ALBEDO = color;
	EMISSION = color * emission_strength
		+ rim_color.rgb * rim * emission_strength * 0.7;
	METALLIC = 0.0;
	ROUGHNESS = roughness;
	SPECULAR = 0.26;
}
