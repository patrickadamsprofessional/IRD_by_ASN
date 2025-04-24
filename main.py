import subprocess
import json
import shlex
import os
from typing import List, Optional, Set

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse

# --- Constants ---
DEFAULT_IRR_SOURCES: Set[str] = {
    "RADB", "RIPE", "NTTCOM", "APNIC", "AFRINIC", "ARIN", "BELL",
    "LEVEL3", "SAVVIS", "ALTDB", "REACH", "TC", "RPKI"
}
DEFAULT_IRR_LIST: List[str] = sorted(list(DEFAULT_IRR_SOURCES))

# Private ASN ranges (inclusive)
PRIVATE_ASN_RANGES = [
    (64512, 65534),       # 16-bit private range
    (4200000000, 4294967294) # 32-bit private range
]

MAX_32_BIT_UINT = 4294967295
COMMAND_TIMEOUT_SECONDS = 60 # Timeout for the bgpq4 command execution

# --- Validation Functions ---

def validate_asn(asn_str: str) -> Optional[str]:
    """
    Validates the ASN string.

    Checks:
    - If it starts with 'AS' (case-insensitive) and removes it.
    - If the remaining part is a valid integer.
    - If the integer is positive and within the 32-bit unsigned range.
    - If the integer falls within defined private ASN ranges.

    Returns:
        The formatted ASN string ('AS' + number) if valid, otherwise None.
    """
    asn_upper = asn_str.upper()
    numeric_part = asn_upper
    if asn_upper.startswith("AS"):
        numeric_part = asn_upper[2:]

    try:
        asn_int = int(numeric_part)
    except ValueError:
        return None # Not an integer

    # Check positive 32-bit integer range (technically 0 is valid but often not used for routing)
    if not (0 < asn_int <= MAX_32_BIT_UINT):
        return None # Out of range or non-positive

    # Check private ranges
    for start, end in PRIVATE_ASN_RANGES:
        if start <= asn_int <= end:
            return None # Private ASN

    # Return formatted ASN
    return f"AS{asn_int}"

def validate_irr_sources(irr_input: List[str]) -> Optional[List[str]]:
    """
    Validates the list of IRR source strings.

    Checks:
    - If all provided sources (case-insensitive) are present in the
      DEFAULT_IRR_SOURCES set.

    Returns:
        A list of validated IRR sources with canonical casing (from DEFAULT_IRR_SOURCES)
        if all are valid, otherwise None. Returns an empty list if input is empty.
    """
    if not irr_input:
        return [] # Allow empty list

    validated_list = []
    input_set_upper = {s.upper() for s in irr_input}
    default_set_upper = {s.upper() for s in DEFAULT_IRR_SOURCES}
    original_case_map = {s.upper(): s for s in DEFAULT_IRR_SOURCES}

    if not input_set_upper.issubset(default_set_upper):
        return None # Contains invalid sources

    # Return list with original casing from DEFAULT_IRR_SOURCES
    return sorted([original_case_map[s_upper] for s_upper in input_set_upper])

# --- FastAPI App ---

app = FastAPI(
    title="BGP Prefix Lookup API",
    description="Query IRR sources for prefixes announced by an ASN using bgpq4.",
    version="1.0.0",
)

@app.on_event("startup")
async def check_dependencies():
    """Check for required system dependencies on startup."""
    missing_tools = []
    for tool in ['bgpq4', 'jq', 'egrep']:
        if subprocess.run(['which', tool], capture_output=True, check=False).returncode != 0:
            missing_tools.append(tool)
    if missing_tools:
        raise RuntimeError(f"Missing required system tools: {', '.join(missing_tools)}. Please install them.")


@app.get(
    "/lookup",
    response_model=dict, # Expecting a dictionary like { "ASXXXX": [...] }
    summary="Get BGP prefixes for an ASN from specified IRR sources",
    description="""\
Retrieves IPv4 prefixes associated with a given Autonomous System Number (ASN)
by querying specified Internet Routing Registry (IRR) sources using the `bgpq4` tool.

- **ASN Validation**: Ensures the ASN is a valid, non-private, positive 32-bit integer.
- **IRR Validation**: Ensures all specified IRR sources are from the known list.
- **Defaults**: Uses AS400427 and all known IRR sources if not provided.
"""
)
async def get_prefixes(
    asn: str = Query(
        "AS400427",
        description="Target ASN (e.g., 'AS400427' or '400427'). Must be a valid, non-private, positive 32-bit integer.",
        examples=["AS15169", "3356"]
    ),
    irr: Optional[str] = Query(
        None,
        description=(
            "Comma-separated list of IRR sources to query (case-insensitive). "
            f"If omitted, defaults to all known sources: {', '.join(DEFAULT_IRR_LIST)}. "
            f"Must be a subset of these defaults."
        ),
        examples=["RIPE,LEVEL3", "radb"]
    )
):
    """
    FastAPI endpoint to perform the BGP prefix lookup.
    """
    # --- Input Validation ---
    validated_asn = validate_asn(asn)
    if not validated_asn:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid ASN format or value: '{asn}'. Must be a positive 32-bit non-private ASN."
        )

    irr_list_to_use: List[str]
    invalid_sources: Optional[Set[str]] = None

    if irr is None:
        irr_list_to_use = DEFAULT_IRR_LIST
    else:
        # Split, strip whitespace, and filter empty strings
        irr_input_list = [item.strip() for item in irr.split(',') if item.strip()]
        validated_irr_list = validate_irr_sources(irr_input_list)
        if validated_irr_list is None:
            # Identify invalid sources for the error message
            input_set_upper = {s.upper() for s in irr_input_list}
            default_set_upper = {s.upper() for s in DEFAULT_IRR_SOURCES}
            invalid_sources_set = input_set_upper - default_set_upper
            raise HTTPException(
                status_code=400,
                detail=(f"Invalid IRR source(s) provided: {', '.join(sorted(list(invalid_sources_set)))}. "
                        f"Allowed sources: {', '.join(DEFAULT_IRR_LIST)}")
            )
        irr_list_to_use = validated_irr_list

    if not irr_list_to_use:
        # Return empty result consistent with script behavior if no IRR sources are specified (or validated)
        return JSONResponse(content={validated_asn: []})

    # --- Command Construction ---
    loop_parts = []
    quoted_asn_arg = shlex.quote(validated_asn) # ASN for bgpq4 tool and jq --arg
    quoted_asn_key = shlex.quote(validated_asn) # ASN for the final JSON structure key

    for ird in irr_list_to_use:
        quoted_ird = shlex.quote(ird)
        # Construct the command part for a single IRR source
        # 2>/dev/null suppresses bgpq4 errors (e.g., connection issues to one IRR)
        # egrep -v exact filters out exact matches if needed (as in original script)
        cmd_part = (
            f"bgpq4 -S {quoted_ird} -4 -j -l{quoted_asn_arg} {quoted_asn_arg} 2>/dev/null | "
            f"jq --arg src {quoted_ird} --arg asn {quoted_asn_arg} "
            f"'select(.[$asn] != null) | .[$asn] |= map(. + {{source: $src}})' | "
            f"egrep -v exact"
        )
        loop_parts.append(cmd_part)

    # Combine loop parts: execute each part sequentially, piping the combined stdout
    # The outer parentheses create a subshell ensuring all output is piped together
    script_body = " ; ".join(loop_parts)
    # Final jq command aggregates results into the desired structure
    # If the script_body produces no output (e.g., ASN not found in any specified IRR),
    # jq -s will process empty input, resulting in `null` by default. We modify it
    # to return the desired empty structure { "ASN": [] }.
    final_command = (
        f"( {script_body} ) | "
        f"jq -s '{{ {quoted_asn_key}: (map(.{quoted_asn_key}) | flatten) }}'"
    )


    # --- Command Execution ---
    try:
        process = subprocess.run(
            final_command,
            shell=True,  # Necessary for pipes and subshells
            capture_output=True,
            text=True,
            check=False, # Manually check return code for better error context
            timeout=COMMAND_TIMEOUT_SECONDS
        )

        if process.returncode != 0:
            # Log details for server-side debugging
            print(f"Command failed with code {process.returncode}")
            print(f"Command: {final_command}")
            print(f"Stderr: {process.stderr.strip()}")
            # Provide a generic error to the client
            raise HTTPException(
                status_code=502, # Bad Gateway might be appropriate if backend script fails
                detail=f"Error executing backend BGP query script (code: {process.returncode}). See server logs."
            )

        # --- Result Parsing ---
        try:
            result_json = json.loads(process.stdout)
            # Ensure the primary key exists, even if empty (should be handled by final jq)
            if validated_asn not in result_json:
                 result_json[validated_asn] = []
            return JSONResponse(content=result_json)
        except json.JSONDecodeError:
            print(f"Failed to decode JSON from command output.")
            print(f"Command: {final_command}")
            print(f"Stdout: {process.stdout.strip()}")
            raise HTTPException(
                status_code=500,
                detail="Failed to parse JSON output from BGP query script."
            )

    except subprocess.TimeoutExpired:
        print(f"Command timed out after {COMMAND_TIMEOUT_SECONDS}s")
        print(f"Command: {final_command}")
        raise HTTPException(
            status_code=504, # Gateway Timeout
            detail=f"BGP query script execution timed out after {COMMAND_TIMEOUT_SECONDS} seconds."
        )
    except FileNotFoundError:
        # This typically means the shell (`/bin/sh`) wasn't found, highly unlikely.
        # Tool check at startup should handle bgpq4/jq/egrep missing.
        print("Error: Shell '/bin/sh' not found for subprocess execution.")
        raise HTTPException(
            status_code=500,
            detail="Failed to execute shell command. Server configuration error."
        )
    except Exception as e:
        # Catch any other unexpected errors during subprocess handling
        print(f"Unexpected error during command execution: {e}")
        print(f"Command: {final_command}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred during script execution. See server logs."
        )

# --- Optional: Uvicorn runner for direct execution ---
# if __name__ == "__main__":
#     import uvicorn
#     # Recommended: Run with `uvicorn main:app --reload` for development
#     uvicorn.run(app, host="0.0.0.0", port=8000) 
