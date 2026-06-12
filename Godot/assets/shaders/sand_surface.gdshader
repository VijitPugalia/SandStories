shader_type spatial;

uniform float height_scale : hint_range(0.0, 2.0) = 0.25;
uniform float noise_scale : hint_range(0.1, 20.0) = 4.0;
uniform vec2 offset = vec2(0.0, 0.0);

uniform float color_strength : hint_range(0.0, 1.0) = 1.0;

varying vec3 local_pos;

float hash12(vec2 p) {
	vec3 p3 = fract(vec3(p.x, p.y, p.x) * 0.1031);
	p3 += dot(p3, vec3(p3.y, p3.z, p3.x) + 33.33);
	return fract((p3.x + p3.y) * p3.z);
}

float noise2d(vec2 p) {
	vec2 i = floor(p);
	vec2 f = fract(p);

	float a = hash12(i);
	float b = hash12(i + vec2(1.0, 0.0));
	float c = hash12(i + vec2(0.0, 1.0));
	float d = hash12(i + vec2(1.0, 1.0));

	vec2 u = f * f * (3.0 - 2.0 * f);

	return mix(a, b, u.x)
	     + (c - a) * u.y * (1.0 - u.x)
	     + (d - b) * u.x * u.y;
}

float fbm(vec2 p) {
	float v = 0.0;
	float a = 0.5;

	for (int i = 0; i < 5; i++) {
		v += a * noise2d(p);

		p = vec2(
			1.6 * p.x + 1.2 * p.y,
		   -1.2 * p.x + 1.6 * p.y
		);

		a *= 0.5;
	}

	return v;
}

float hash13(vec3 p) {
	p = fract(p * 0.1031);
	p += dot(p, p.yzx + 33.33);
	return fract((p.x + p.y) * p.z);
}

void vertex() {
	vec2 p = VERTEX.xy * noise_scale + offset;
	float h = fbm(p) * height_scale;
	VERTEX.z += h * 0.6;
	local_pos = VERTEX;
}

void fragment() {
	// 用屏幕导数算当前三角面的面法线
	vec3 dx = dFdx(local_pos);
	vec3 dy = dFdy(local_pos);
	vec3 face_normal = normalize(cross(dx, dy));

	// 用面法线生成一个稳定随机值
	float h = hash13(face_normal * 19.731);

	// 灰度随机
	float v = mix(0.45, 0.85, h);
	vec3 random_color = vec3(v);

	ALBEDO = mix(vec3(0.8), random_color, color_strength);
}