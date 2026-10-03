from app import login


def test_missing_email_returns_validation_error():
    response, status = login({})

    assert status == 400
    assert response == {"error": "email is required"}
