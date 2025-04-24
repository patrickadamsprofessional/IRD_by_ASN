# BGP Prefix Lookup API

This FastAPI application provides a REST endpoint to query Internet Routing Registry (IRR) sources for IPv4 prefixes announced by a specific Autonomous System Number (ASN) using the `bgpq4` tool.

## Features

*   Retrieves IPv4 prefixes for a given ASN.
*   Allows specifying target IRR sources.
*   Uses defaults if parameters are omitted (ASN: AS400427, IRR: All known sources).
*   Validates ASN format and range (must be positive 32-bit, non-private).
*   Validates IRR sources against a predefined list.
*   Handles errors during script execution (e.g., timeouts, tool failures).
*   Provides interactive API documentation via Swagger UI (`/docs`) and ReDoc (`/redoc`).

## Prerequisites

Before running the application, ensure the following are installed on your **Unix/Linux** system:

1.  **Python 3.8+**
2.  **pip** (Python package installer)
3.  **bgpq4**: The core tool for querying IRR data. (Installation varies by distribution, e.g., `apt install bgpq4` or `yum install bgpq4`).
4.  **jq**: A command-line JSON processor. (e.g., `apt install jq` or `yum install jq`).
5.  **egrep** (or `grep -E`): Typically available by default as part of `grep`.

## Setup

1.  **Clone the repository or download the files** (`main.py`, `requirements.txt`, `tests/`, `pytest.ini`).

2.  **Navigate to the project directory**:
    ```bash
    cd /path/to/your/project
    ```

3.  **(Recommended) Create and activate a virtual environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    # On Windows (if using WSL or similar), it might be venv\Scripts\activate
    ```

4.  **Install Python dependencies (including test dependencies)**:
    ```bash
    pip install -r requirements.txt
    ```

## Running the Application

Use `uvicorn` to run the FastAPI application:

```bash
uvicorn main:app --host 0.0.0.0 --port 4242
```

For development, you can use the `--reload` flag to automatically restart the server when code changes are detected:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 4242
```

The API will be available at `http://localhost:8000` (or the appropriate IP/hostname if running on a different machine).

## Running Tests

Ensure you have installed the dependencies from `requirements.txt` (which includes `pytest` and `httpx`).

To run the unit tests, navigate to the project root directory (the one containing `main.py` and `pytest.ini`) and run:

```bash
pytest
```

Pytest will automatically discover and run the tests located in the `tests/` directory.
The tests use mocking to avoid executing the actual `bgpq4` command.

## API Endpoint

### GET /lookup

Retrieves BGP prefixes for an ASN.

**Query Parameters:**

*   `asn` (string, required): The target ASN. Can be provided with or without the "AS" prefix (e.g., "AS15169", "3356"). Defaults to "AS400427".
*   `irr` (string, optional): A comma-separated list of IRR sources to query (case-insensitive, e.g., "ripe,level3,radb"). If omitted, all known sources are queried. Must be a subset of the allowed sources (see `main.py` for the full list).

**Example Usage:**

*   Default query:
    `http://localhost:8000/lookup`
*   Query specific ASN:
    `http://localhost:8000/lookup?asn=AS15169`
*   Query specific ASN and specific IRR sources:
    `http://localhost:8000/lookup?asn=AS3356&irr=RIPE,LEVEL3`
*   Query using numeric ASN:
    `http://localhost:8000/lookup?asn=13335&irr=RADB`

**Successful Response (200 OK):**

```json
{
  "AS15169": [
    {
      "prefix": "8.8.8.0/24",
      "exact": true,
      "source": "RADB"
    },
    {
      "prefix": "8.8.4.4/32",
      "exact": true,
      "source": "RADB"
    }
    // ... other prefixes
  ]
}
```

**Error Responses:**

*   `400 Bad Request`: Invalid ASN or IRR source provided.
*   `500 Internal Server Error`: General server error or failure parsing script output.
*   `502 Bad Gateway`: The backend `bgpq4` script execution failed.
*   `504 Gateway Timeout`: The backend script execution timed out.

## Interactive Documentation

Once the application is running, you can access the interactive Swagger UI documentation at:
`http://localhost:8000/docs`

And the ReDoc documentation at:
`http://localhost:8000/redoc` 
