extends SceneTree

const CJK_FONT_PATH := "res://assets/fonts/NotoSansSC-VF.ttf"
const SAMPLE_TEXT := "张伟王芳李娜陈晨刘洋黄静赵敏吴磊周雨欣徐子涵孙浩然马思远阿依古丽卓玛中文姓名测试：、。"


func _init() -> void:
	var font := load(CJK_FONT_PATH)
	if not (font is Font):
		push_error("Could not load CJK font: " + CJK_FONT_PATH)
		quit(1)
		return

	var missing := PackedStringArray()
	for index in range(SAMPLE_TEXT.length()):
		var codepoint := SAMPLE_TEXT.unicode_at(index)
		if codepoint <= 32:
			continue
		if not font.has_char(codepoint):
			missing.append("%s U+%04X" % [SAMPLE_TEXT.substr(index, 1), codepoint])

	var payload := {
		"names": ["张伟", "王芳", "李娜", "陈晨", "阿依古丽", "卓玛"],
		"note": "中文姓名测试：张伟、王芳、李娜、陈晨"
	}
	var encoded := JSON.stringify(payload)
	var decoded = JSON.parse_string(encoded)
	var json_ok := typeof(decoded) == TYPE_DICTIONARY and str(decoded.get("note", "")) == str(payload["note"])

	print(JSON.stringify({
		"font": CJK_FONT_PATH,
		"glyph_count_checked": SAMPLE_TEXT.length(),
		"missing_glyphs": missing,
		"json_roundtrip": json_ok
	}))
	quit(0 if missing.is_empty() and json_ok else 2)
