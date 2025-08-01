from src.klaudecode.utils.str_utils import extract_xml_content


class TestExtractXmlContent:
    def test_simple_tag(self):
        text = "<tag>content</tag>"
        result = extract_xml_content(text, "tag")
        assert result == "content"

    def test_tag_with_newlines(self):
        text = """<code>
def hello():
    print("world")
</code>"""
        result = extract_xml_content(text, "code")
        expected = '\ndef hello():\n    print("world")\n'
        assert result == expected

    def test_tag_with_multiline_content(self):
        text = "<description>This is a\nmultiline content\nwith multiple lines</description>"
        result = extract_xml_content(text, "description")
        assert result == "This is a\nmultiline content\nwith multiple lines"

    def test_tag_not_found(self):
        text = "<other>content</other>"
        result = extract_xml_content(text, "missing")
        assert result == ""

    def test_empty_tag(self):
        text = "<tag></tag>"
        result = extract_xml_content(text, "tag")
        assert result == ""

    def test_nested_tags_same_name(self):
        text = "<tag>outer<tag>inner</tag>content</tag>"
        result = extract_xml_content(text, "tag")
        # Non-greedy match returns the first complete match
        assert result == "outer<tag>inner"

    def test_tag_with_attributes_should_not_match(self):
        text = '<tag attr="value">content</tag>'
        result = extract_xml_content(text, "tag")
        # Current regex doesn't handle tags with attributes
        assert result == ""

    def test_case_sensitive(self):
        text = "<Tag>content</Tag>"
        result = extract_xml_content(text, "tag")
        assert result == ""

    def test_multiple_occurrences(self):
        text = "<tag>first</tag> some text <tag>second</tag>"
        result = extract_xml_content(text, "tag")
        # Should return the first match
        assert result == "first"

    def test_tag_in_larger_text(self):
        text = "Some prefix text <important>key content</important> and suffix"
        result = extract_xml_content(text, "important")
        assert result == "key content"

    def test_special_characters_in_content(self):
        text = "<data>!@#$%^&*()_+{}|:<>?[]\\;'\",./ content</data>"
        result = extract_xml_content(text, "data")
        assert result == "!@#$%^&*()_+{}|:<>?[]\\;'\",./ content"
