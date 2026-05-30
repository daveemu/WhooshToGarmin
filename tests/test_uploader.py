"""Tests for the Garmin upload response parsing."""

from __future__ import annotations

from whooshtogarmin.uploader import parse_upload_response


def test_successful_upload_returns_activity_id():
    response = {
        "detailedImportResult": {
            "successes": [{"internalId": 987654321, "externalId": "abc"}],
            "failures": [],
        }
    }
    result = parse_upload_response(response)
    assert result.uploaded is True
    assert result.duplicate is False
    assert result.activity_id == 987654321


def test_duplicate_activity_is_detected():
    response = {
        "detailedImportResult": {
            "successes": [],
            "failures": [
                {
                    "internalId": 111,
                    "messages": [{"code": 202, "content": "Duplicate Activity"}],
                }
            ],
        }
    }
    result = parse_upload_response(response)
    assert result.uploaded is False
    assert result.duplicate is True
    assert result.activity_id == 111


def test_unknown_failure_is_neither_uploaded_nor_duplicate():
    response = {
        "detailedImportResult": {
            "successes": [],
            "failures": [{"internalId": 1, "messages": [{"code": 1, "content": "boom"}]}],
        }
    }
    result = parse_upload_response(response)
    assert result.uploaded is False
    assert result.duplicate is False


def test_empty_response_is_handled():
    result = parse_upload_response({})
    assert result.uploaded is False
    assert result.duplicate is False


def test_non_dict_response_is_handled():
    result = parse_upload_response(None)
    assert result.uploaded is False
    assert result.duplicate is False
