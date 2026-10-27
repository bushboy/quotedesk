import pytest

from quotedesk.domain.shared.errors import ValidationError


def expect_validation(call, code, sentence):
    return expect_domain(call, ValidationError, code, sentence)


def expect_domain(call, error_type, code, sentence):
    with pytest.raises(error_type) as caught:
        call()
    error = caught.value
    assert type(error) is error_type
    assert not isinstance(error, ValueError)
    assert error.code == code
    assert error.sentence == sentence
    return error
