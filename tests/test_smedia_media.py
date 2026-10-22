"""Working out what the owner actually sent us."""


class FakePhoto:
    file_id = "PHOTO_FILE_ID"


class FakeAnimation:
    file_id = "GIF_FILE_ID"


class FakeDocument:
    def __init__(self, mime_type):
        self.mime_type = mime_type
        self.file_id = "DOC_FILE_ID"


class FakeMessage:
    def __init__(self, photo=None, animation=None, document=None):
        self.photo = photo
        self.animation = animation
        self.document = document


def test_a_photo_is_used_as_the_start_image():
    from plugins.smedia import media_from_message

    assert media_from_message(FakeMessage(photo=FakePhoto())) == (
        "photo",
        "PHOTO_FILE_ID",
    )


def test_a_gif_is_used_as_the_start_gif():
    from plugins.smedia import media_from_message

    assert media_from_message(FakeMessage(animation=FakeAnimation())) == (
        "animation",
        "GIF_FILE_ID",
    )


def test_a_document_is_not_used_directly():
    """Telegram binds a file_id to its type, so a document id cannot be sent as a photo."""
    from plugins.smedia import media_from_message

    assert media_from_message(FakeMessage(document=FakeDocument("image/png"))) == (
        None,
        None,
    )


def test_an_image_file_can_be_re_uploaded_as_a_photo():
    from plugins.smedia import document_media_type

    assert document_media_type(FakeDocument("image/png")) == "photo"


def test_a_jpeg_file_can_be_re_uploaded_as_a_photo():
    from plugins.smedia import document_media_type

    assert document_media_type(FakeDocument("image/jpeg")) == "photo"


def test_an_mp4_file_can_be_re_uploaded_as_a_gif():
    from plugins.smedia import document_media_type

    assert document_media_type(FakeDocument("video/mp4")) == "animation"


def test_a_pdf_file_cannot_be_used():
    from plugins.smedia import document_media_type

    assert document_media_type(FakeDocument("application/pdf")) is None


def test_a_file_without_a_mime_type_cannot_be_used():
    from plugins.smedia import document_media_type

    assert document_media_type(FakeDocument(None)) is None


def test_there_is_no_document_at_all():
    from plugins.smedia import document_media_type

    assert document_media_type(None) is None
