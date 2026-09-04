import pytest
from divoom_lib.utils import logger_utils

def test_print_info(capsys):
    """Test print_info function."""
    message = "This is an informational message."
    logger_utils.print_info(message)
    captured = capsys.readouterr()
    assert captured.out == f"[ ==> ] {message}\n"
    assert captured.err == ""

def test_print_wrn(capsys):
    """Test print_wrn function."""
    message = "This is a warning message."
    logger_utils.print_wrn(message)
    captured = capsys.readouterr()
    assert captured.out == f"[ Wrn ] {message}\n"
    assert captured.err == ""

def test_print_err(capsys):
    """Test print_err function."""
    message = "This is an error message."
    logger_utils.print_err(message)
    captured = capsys.readouterr()
    assert captured.out == f"[ Err ] {message}\n"
    assert captured.err == ""

def test_print_ok(capsys):
    """Test print_ok function."""
    message = "This is a success message."
    logger_utils.print_ok(message)
    captured = capsys.readouterr()
    assert captured.out == f"[ Ok  ] {message}\n"
    assert captured.err == ""
