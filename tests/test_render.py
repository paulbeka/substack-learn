from html.parser import HTMLParser

from french_bot.render import render_html, render_markdown


class Document(HTMLParser):
    def __init__(self, value):
        super().__init__()
        self.tags, self.text = [], []
        self.feed(value)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)

    def handle_data(self, data):
        self.text.append(data)


def test_complete_deterministic_template(lesson):
    text = render_markdown(lesson)
    assert text == render_markdown(lesson)
    assert text.index("## Comprehension questions") < text.index("## Answers")
    page = Document(render_html(lesson))
    assert page.tags.count("table") == 1
    assert page.tags.count("li") == 6
    assert "L'homme a deux stylos." in "".join(page.text)
    assert "Get a new beginner" not in render_markdown(lesson, include_cta=False)


def test_model_text_cannot_create_html_or_links(lesson):
    payload = "<script>alert(1)</script> [click](javascript:alert(1)) ![image](https://evil.test/a)"
    lesson.title_french = payload
    lesson.grammar_explanation_english = payload
    lesson.vocabulary[0].english = "a | table\n# heading"
    page = Document(render_html(lesson))
    assert not {"script", "img", "a"} & set(page.tags)
    assert page.tags.count("h1") == 1
    assert payload in "".join(page.text)
