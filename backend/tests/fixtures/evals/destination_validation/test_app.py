from app import search


def test_missing_destination_returns_validation_error():
    response, status = search({})

    assert status == 400
    assert response == {"error": "destination is required"}
