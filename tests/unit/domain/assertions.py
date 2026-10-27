import pytest

from quotedesk.domain.shared.errors import ValidationError


def expect_validation(call, code, sentence):
    with pytest.raises(ValidationError) as caught:
        call()
    error = caught.value
    assert type(error) is ValidationError
    assert not isinstance(error, ValueError)
    assert error.code == code
    assert error.sentence == sentence
    return error
