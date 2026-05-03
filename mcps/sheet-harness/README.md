# TAIA Sheet Harness - Deployment Guide

## Overview
TAIA Sheet Harness is an MCP (Model Context Protocol) server that enables LLMs to interact with Excel-based test plans. It provides automated test execution tracking, result recording, and screenshot embedding capabilities — all accessible through the TAIA chat interface.

## Architecture

### Services
- **MCP Server (Port 8006)**: SSE-based protocol for LLM orchestration (Claude, OpenAI, etc.)

### Key Features
✅ Import Excel test workbooks  
✅ Read test cases with automatic section header detection  
✅ Write OK/NG results with color coding  
✅ Embed screenshots into pre-existing tabs  
✅ Atomic saves with backup retention (5 versions)  
✅ File locking for concurrent access  
✅ TAIA-native integration (no separate web UI)  

## Quick Start

### 1. Build and Deploy

```bash
cd /path/to/taia-sheet-harness
docker compose up -d --build
```

### 2. Verify Services

```bash
# Check logs
docker compose logs -f

# Expected output:
# taia-sheet-harness  | INFO: Starting TAIA Sheet Harness (MCP only)...
# taia-sheet-harness  | INFO: MCP server (SSE) on port 8006
```

## Usage

### Via MCP (Claude Desktop / Cursor / etc.)

Configure your MCP client:

**Claude Desktop:**
```json
{
  "mcpServers": {
    "taia-sheet-harness": {
      "command": "docker",
      "args": [
        "compose",
        "-f",
        "/path/to/taia-sheet-harness/docker-compose.yml",
        "run",
        "--rm",
        "taia-sheet-harness"
      ]
    }
  }
}
```

**Cursor:**
```json
{
  "mcpServers": {
    "taia-sheet-harness": {
      "command": "docker",
      "args": [
        "compose",
        "-f",
        "/path/to/taia-sheet-harness/docker-compose.yml",
        "run",
        "--rm",
        "taia-sheet-harness"
      ]
    }
  }
}
```

Available MCP tools:

#### `import_workbook_tool`
Import an Excel test workbook.

```python
result = import_workbook_tool(
    file_b64="<base64-encoded-xlsx>",
    filename="test_plan.xlsx",
    overwrite=False
)
# Returns: {ok, workbook_id, test_count, ok_count, ng_count, untested_count}
```

#### `get_test_cases`
Read all test cases from a workbook.

```python
result = get_test_cases(
    workbook_id="test_plan",
    untested_only=False  # Set True to get only untested cases
)
# Returns: {ok, count, test_cases: [{row, test_no, prerequisite, test_detail, ...}]}
```

#### `write_result_tool`
Write test result to a specific row.

```python
result = write_result_tool(
    workbook_id="test_plan",
    row=5,                    # From get_test_cases
    ok_ng="OK",               # or "NG"
    notes="All assertions passed"
)
# Returns: {ok, row, ok_ng, message}
```

#### `embed_screenshot_tool`
Embed a screenshot into a test's screenshot tab.

```python
result = embed_screenshot_tool(
    workbook_id="test_plan",
    test_no=3,                # Test number from column A
    image_b64="<base64-png>",
    caption="Login page timeout",
    step_number=1
)
# Returns: {ok, tab_name, message}
```

#### `get_workbook_summary_tool`
Get summary statistics.

```python
result = get_workbook_summary_tool(workbook_id="test_plan")
# Returns: {ok, test_count, ok_count, ng_count, untested_count, screenshot_tabs}
```
curl http://localhost:8007/ | grep -A10 "workbook-item"
```

## Excel File Format

### Required Tab Structure

| Index | Tab Name | Purpose |
|-------|----------|---------|
| 0 | `Cover` | Skipped |
| 1 | `Revisions` | Skipped |
| 2 | `Main` (any name) | **Test cases - always index 2** |
| 3+ | `No.2`, `No.8-10` | Screenshot tabs (pre-created) |

### Main Sheet Columns (1-based)

| Col | Letter | Field | Written By |
|-----|--------|-------|-----------|
| 1 | A | No (test number) | User |
| 2 | B | Prerequisite | User |
| 3 | C | Test Detail | User |
| 4 | D | Expected Results | User |
| 5 | E | Test Case Data No. | User |
| 6 | F | Remarks | User + **TAIA** |
| 7 | G | Num of test cases | User |
| 8 | H | Test Date | **TAIA** |
| 9 | I | Test OK/NG | **TAIA** |
| 10 | J | Test Tester | **TAIA** |
| 11 | K | Review Date | Human only |
| 12 | L | Review OK/NG | Human only |
| 13 | M | Review Reviewer | Human only |

### Row Rules
- **Row 1**: Header
- **Row 2+**: Data
- Skip rows where Col A is empty or non-numeric (section headers)
- Only rows with numeric Col A are test cases

### Screenshot Tab Naming

- `No.2` → Test #2
- `No.8-10` → Tests #8, #9, #10

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKBOOKS_DIR` | `/workbooks` | Storage directory for Excel files |
| `PORT_MCP` | `8006` | MCP server port |
| `PORT_API` | `8007` | FastAPI server port |
| `SHEET_HARNESS_HOST` | `localhost` | Host for download URLs |
| `LOCK_TIMEOUT_SECONDS` | `10` | File lock timeout |
| `MAX_WORKBOOKS` | `100` | Maximum number of workbooks |

### Docker Compose Example

```yaml
version: '3.8'
services:
  taia-sheet-harness:
    build: ./taia-sheet-harness
    container_name: taia-sheet-harness
    restart: unless-stopped
    ports:
      - "8006:8006"  # MCP
      - "8007:8007"  # HTTP
    volumes:
      - taia-workbooks:/workbooks
    environment:
      WORKBOOKS_DIR: "/workbooks"
      PORT_MCP: "8006"
      PORT_API: "8007"
      SHEET_HARNESS_HOST: "your-domain.com"
      LOCK_TIMEOUT_SECONDS: "10"
      MAX_WORKBOOKS: "100"

volumes:
  taia-workbooks:
```

## Testing

### Run Tests

```bash
cd mcps/sheet-harness
.venv/Scripts/python -m pytest tests/ -v
```

### Run Demo

```bash
cd mcps/sheet-harness
.venv/Scripts/python demo.py
```

## File Storage

### Directory Structure

```
/workbooks/
├── project_a.xlsx
├── project_b.xlsx
└── .backups/
    ├── project_a_20240430_140512_123456.xlsx
    └── project_b_20240430_141000_654321.xlsx
```

### Backup Policy
- Automatic backup before each write
- Keeps last 5 versions per workbook
- Stored in `.backups/` subdirectory

## Troubleshooting

### Services Won't Start
```bash
# Check if ports are in use
netstat -ano | findstr :8006
netstat -ano | findstr :8007

# Check logs
docker compose logs taia-sheet-harness
```

### Upload Fails
- Ensure file is `.xlsx` format
- Check `MAX_WORKBOOKS` limit
- Verify `WORKBOOKS_DIR` is writable

### Write Results Fails
- Verify workbook exists (call `import_workbook` first)
- Check row number is valid (from `get_test_cases`)
- Ensure file is not locked by another process

### Screenshot Not Embedding
- Verify screenshot tab exists (`No.X` format)
- Check image is valid PNG/JPEG
- Ensure image size < 10MB base64

## Security Considerations

- **No authentication**: Suitable for internal networks only
- **File validation**: Only `.xlsx` files accepted
- **Path traversal**: Workbook IDs sanitized
- **Resource limits**: Max file size and workbook count enforced

## Performance

- **Concurrent writes**: File locking prevents corruption
- **Atomic saves**: No partial writes on crash
- **Memory efficient**: Streaming for large files

## Integration with LLMs

### Claude Desktop Example

```json
{
  "mcpServers": {
    "taia-sheet-harness": {
      "command": "docker",
      "args": [
        "compose",
        "-f",
        "/opt/taia/docker-compose.yml",
        "run",
        "--rm",
        "taia-sheet-harness"
      ]
    }
  }
}
```

### Sample LLM Prompt

```
You have access to the TAIA Sheet Harness. Help me manage test execution:

1. Import the test plan from test_plan.xlsx
2. Get all untested test cases
3. For each test case:
   - Execute the test (simulate or run actual test)
   - Write OK/NG result
   - If failed, embed screenshot
4. Provide summary of results
5. Generate download link for updated workbook
```

## Support

For issues or questions:
- Check logs: `docker compose logs taia-sheet-harness`
- Run tests: `pytest tests/ -v`
- Review demo: `python demo.py`

## License

Internal TAIA project - All rights reserved.
