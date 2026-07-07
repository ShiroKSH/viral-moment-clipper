from backend.services.sentence_segmenter import split_plain_text


def test_split_plain_text_handles_russian_sentences():
    text = "Это первый тезис. Почему это важно? Потому что зритель досмотрит."
    assert split_plain_text(text) == ["Это первый тезис.", "Почему это важно?", "Потому что зритель досмотрит."]
