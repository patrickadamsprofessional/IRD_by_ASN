import subprocess
import json
from unittest.mock import patch, MagicMock

import pytest
from httpx import AsyncClient

# Assuming your FastAPI app instance is named 'app' in 'main.py'
# Adjust the import if your file/instance name is different
from main import app, DEFAULT_IRR_LIST # Import app and defaults

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio

# Default ASN and a sample known ASN for testing
DEFAULT_ASN = "AS400427"
KNOWN_ASN = "AS15169"
NUMERIC_ASN = "15169"

# --- Fixtures ---

@pytest.fixture
def mock_subprocess_run():
    """Fixture to mock subprocess.run."""
    with patch("main.subprocess.run") as mock_run:
        # Default mock behavior (successful 'which' calls for dependencies)
        def default_side_effect(*args, **kwargs):
            cmd_list = args[0] # First argument is the command
            mock_proc = MagicMock(spec=subprocess.CompletedProcess)
            if isinstance(cmd_list, list) and cmd_list[0] == 'which':
                # Assume tools exist by default for most tests
                mock_proc.returncode = 0
                mock_proc.stdout = f"/usr/bin/{cmd_list[1]}"
                mock_proc.stderr = ""
            else:
                # Default for the main command - let tests override
                # Return a placeholder that can be parsed as JSON
                mock_proc.returncode = 0
                # Use a valid ASN from input if possible, else default
                asn_in_cmd = DEFAULT_ASN # Placeholder
                if isinstance(cmd_list, str):
                    # Very basic extraction, might need improvement
                    parts = cmd_list.split()
                    asn_args = [p for p in parts if p.startswith('AS') and p.count('AS') == 1]
                    if asn_args:
                        asn_in_cmd = asn_args[0].strip("'") # Remove quotes if shlex added them

                mock_proc.stdout = json.dumps({ asn_in_cmd: [] })
                mock_proc.stderr = ""
            return mock_proc

        mock_run.side_effect = default_side_effect
        yield mock_run

@pytest.fixture
async def client(mock_subprocess_run): # Client depends on the mock being active
    """Async test client fixture."""
    # The AsyncClient context manager handles startup/shutdown events,
    # including the dependency check which uses the mock
    async with AsyncClient(app=app, base_url="http://test") as test_client:
        yield test_client

# Helper function to simplify mocking the main command execution
def mock_main_command(mock_fixture, return_code=0, stdout_json=None, stderr="", raise_exception=None):
    """Sets up the mock_subprocess_run fixture for the main command execution."""
    command_response = None
    if raise_exception:
        command_response = raise_exception
    else:
        mock_process = MagicMock(spec=subprocess.CompletedProcess)
        mock_process.returncode = return_code
        # Ensure stdout is a string, even if empty or based on JSON
        mock_process.stdout = json.dumps(stdout_json) if stdout_json is not None else ""
        mock_process.stderr = stderr
        command_response = mock_process

    # Create a side effect that handles 'which' calls and the main command
    def dynamic_side_effect(*args, **kwargs):
        cmd_arg = args[0]
        # Check if it's a 'which' call (list of strings)
        if isinstance(cmd_arg, list) and len(cmd_arg) > 0 and cmd_arg[0] == 'which':
            # Successful 'which' call
            mock_which_proc = MagicMock(spec=subprocess.CompletedProcess)
            mock_which_proc.returncode = 0
            mock_which_proc.stdout = f"/usr/bin/{cmd_arg[1]}" if len(cmd_arg) > 1 else "/usr/bin/tool"
            mock_which_proc.stderr = ""
            return mock_which_proc
        # Otherwise, assume it's the main shell command (string)
        elif isinstance(cmd_arg, str):
            if isinstance(command_response, Exception):
                raise command_response
            return command_response
        # Handle unexpected call types gracefully (optional)
        else:
             pytest.fail(f"Unexpected call to subprocess.run with args: {args}")

    mock_fixture.side_effect = dynamic_side_effect


# --- Test Cases ---

# --- Success Cases ---

async def test_lookup_success_default_asn(client, mock_subprocess_run):
    """Test successful lookup with default ASN and default IRRs."""
    expected_output = {DEFAULT_ASN: [{"prefix": "192.0.2.0/24", "source": "RIPE"}]}
    mock_main_command(mock_subprocess_run, stdout_json=expected_output)

    response = await client.get("/lookup")

    assert response.status_code == 200
    assert response.json() == expected_output
    # Check subprocess was called for the main command
    main_cmd_called = any(isinstance(c.args[0], str) for c in mock_subprocess_run.call_args_list)
    assert main_cmd_called


async def test_lookup_success_specific_asn(client, mock_subprocess_run):
    """Test successful lookup with a specific valid ASN."""
    expected_output = {KNOWN_ASN: [{"prefix": "8.8.8.0/24", "source": "RADB"}]}
    mock_main_command(mock_subprocess_run, stdout_json=expected_output)

    response = await client.get(f"/lookup?asn={KNOWN_ASN}")

    assert response.status_code == 200
    assert response.json() == expected_output


async def test_lookup_success_numeric_asn(client, mock_subprocess_run):
    """Test successful lookup with a numeric ASN string."""
    expected_output = {KNOWN_ASN: [{"prefix": "8.8.8.0/24", "source": "RADB"}]}
    mock_main_command(mock_subprocess_run, stdout_json=expected_output)

    response = await client.get(f"/lookup?asn={NUMERIC_ASN}") # Use numeric ASN

    assert response.status_code == 200
    assert response.json() == expected_output # Output key should still be 'ASXXXX'


async def test_lookup_success_specific_irr(client, mock_subprocess_run):
    """Test successful lookup with specific valid IRR sources."""
    expected_output = {KNOWN_ASN: [{"prefix": "8.8.4.4/32", "source": "RIPE"}]}
    mock_main_command(mock_subprocess_run, stdout_json=expected_output)

    response = await client.get(f"/lookup?asn={KNOWN_ASN}&irr=RIPE,LEVEL3")

    assert response.status_code == 200
    assert response.json() == expected_output
    # Further check: verify the shell command string in the mock call args contains
    # references only to RIPE and LEVEL3.
    shell_command_arg = next((c.args[0] for c in mock_subprocess_run.call_args_list if isinstance(c.args[0], str)), None)
    assert shell_command_arg is not None
    assert "-S 'RIPE'" in shell_command_arg
    assert "-S 'LEVEL3'" in shell_command_arg
    # Check a default source is NOT present
    assert "-S 'RADB'" not in shell_command_arg


async def test_lookup_success_mixed_case_irr(client, mock_subprocess_run):
    """Test successful lookup with mixed-case IRR sources."""
    expected_output = {KNOWN_ASN: [{"prefix": "8.8.4.4/32", "source": "RIPE"}]}
    mock_main_command(mock_subprocess_run, stdout_json=expected_output)

    response = await client.get(f"/lookup?asn={KNOWN_ASN}&irr=ripe,LeVeL3") # Mixed case

    assert response.status_code == 200
    assert response.json() == expected_output
    # Verify canonical names used in command
    shell_command_arg = next((c.args[0] for c in mock_subprocess_run.call_args_list if isinstance(c.args[0], str)), None)
    assert shell_command_arg is not None
    assert "-S 'RIPE'" in shell_command_arg  # Should use canonical RIPE
    assert "-S 'LEVEL3'" in shell_command_arg # Should use canonical LEVEL3


async def test_lookup_asn_not_found(client, mock_subprocess_run):
    """Test lookup where ASN is valid but yields no results from script."""
    expected_output = {KNOWN_ASN: []}
    mock_main_command(mock_subprocess_run, stdout_json=expected_output)

    response = await client.get(f"/lookup?asn={KNOWN_ASN}")

    assert response.status_code == 200
    assert response.json() == expected_output


async def test_lookup_empty_irr_input(client, mock_subprocess_run):
    """Test lookup when irr parameter is empty or just commas."""
    expected_output = {KNOWN_ASN: []} # Expect empty result as per code logic

    # No mocking needed for the main command as it shouldn't run

    response = await client.get(f"/lookup?asn={KNOWN_ASN}&irr=,")

    assert response.status_code == 200
    assert response.json() == expected_output
    # Verify subprocess was NOT called for the BGP query
    main_cmd_called = any(isinstance(c.args[0], str) for c in mock_subprocess_run.call_args_list)
    assert not main_cmd_called

# --- Input Validation Error Cases ---

@pytest.mark.parametrize("invalid_asn", [
    "ASABC", "AS1.2", "AS-10", "AS0", # Invalid format/value
    "64512", "AS65534", # Private 16-bit
    "4200000000", "AS4294967294", # Private 32-bit
    "AS4294967296" # Out of range
])
async def test_lookup_invalid_asn_format(client, mock_subprocess_run, invalid_asn):
    """Test lookup with various invalid ASN formats/values."""
    response = await client.get(f"/lookup?asn={invalid_asn}")

    assert response.status_code == 400
    assert "Invalid ASN format or value" in response.json()["detail"]
    # Verify subprocess was not called for the BGP query
    main_cmd_called = any(isinstance(c.args[0], str) for c in mock_subprocess_run.call_args_list)
    assert not main_cmd_called


@pytest.mark.parametrize("invalid_irr_param", [
    "INVALID",
    "RIPE,INVALID",
    "INVALID,RADB"
])
async def test_lookup_invalid_irr(client, mock_subprocess_run, invalid_irr_param):
    """Test lookup with invalid IRR sources."""
    response = await client.get(f"/lookup?asn={KNOWN_ASN}&irr={invalid_irr_param}")

    assert response.status_code == 400
    assert "Invalid IRR source(s) provided" in response.json()["detail"]
    # Extract the invalid source name(s) for the check
    expected_invalid = {s.upper() for s in invalid_irr_param.split(',') if s.upper() not in [i.upper() for i in DEFAULT_IRR_LIST]}
    response_detail = response.json()["detail"]
    for invalid in expected_invalid:
        assert invalid in response_detail

    # Verify subprocess was not called for the BGP query
    main_cmd_called = any(isinstance(c.args[0], str) for c in mock_subprocess_run.call_args_list)
    assert not main_cmd_called

# --- Script Execution Error Cases ---

async def test_lookup_script_execution_fail(client, mock_subprocess_run):
    """Test lookup when the backend script returns a non-zero exit code."""
    mock_main_command(mock_subprocess_run, return_code=1, stderr="Error: bgpq4 connection failed")

    response = await client.get(f"/lookup?asn={KNOWN_ASN}")

    assert response.status_code == 502 # Bad Gateway
    assert "Error executing backend BGP query script" in response.json()["detail"]
    assert "code: 1" in response.json()["detail"]


async def test_lookup_script_timeout(client, mock_subprocess_run):
    """Test lookup when the backend script times out."""
    timeout_exception = subprocess.TimeoutExpired(cmd="some shell command", timeout=60)
    mock_main_command(mock_subprocess_run, raise_exception=timeout_exception)

    response = await client.get(f"/lookup?asn={KNOWN_ASN}")

    assert response.status_code == 504 # Gateway Timeout
    assert "timed out after 60 seconds" in response.json()["detail"]


async def test_lookup_script_json_decode_error(client, mock_subprocess_run):
    """Test lookup when the script output is not valid JSON."""
    # We need to mock the raw stdout, not use the JSON helper
    mock_process = MagicMock(spec=subprocess.CompletedProcess)
    mock_process.returncode = 0
    mock_process.stdout = "This is not JSON{]}[" # Invalid JSON output
    mock_process.stderr = ""
    command_response = mock_process

    def dynamic_side_effect(*args, **kwargs):
        cmd_arg = args[0]
        if isinstance(cmd_arg, list) and cmd_arg[0] == 'which':
            mock_which_proc = MagicMock(spec=subprocess.CompletedProcess)
            mock_which_proc.returncode = 0
            mock_which_proc.stdout = f"/usr/bin/{cmd_arg[1]}" if len(cmd_arg) > 1 else "/usr/bin/tool"
            mock_which_proc.stderr = ""
            return mock_which_proc
        elif isinstance(cmd_arg, str):
            return command_response # Return the mock process with bad stdout
        else:
            pytest.fail(f"Unexpected call to subprocess.run with args: {args}")
    mock_subprocess_run.side_effect = dynamic_side_effect

    response = await client.get(f"/lookup?asn={KNOWN_ASN}")

    assert response.status_code == 500 # Internal Server Error
    assert "Failed to parse JSON output" in response.json()["detail"]

# NOTE: Startup dependency check test omitted due to complexity with patching and async client startup.
# Manual testing or alternative approaches might be needed for robust startup checks.

</rewritten_file> 