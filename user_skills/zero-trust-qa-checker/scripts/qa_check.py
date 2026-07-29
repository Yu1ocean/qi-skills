import os
import sys
import json
import difflib

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 qa_check.py '<json_config>'")
        sys.exit(1)

    try:
        config = json.loads(sys.argv[1])
    except Exception as e:
        print(f"Error parsing JSON: {e}")
        sys.exit(1)

    asset_type = config.get("type", "file")
    asset_id = config.get("id")
    expected = config.get("expected", {})

    results = []
    status = "SUCCESS"
    diff = ""

    if asset_type == "file":
        if not os.path.exists(asset_id):
            status = "FAILED"
            results.append(f"File {asset_id} does not exist.")
        else:
            # Check size
            if "min_size" in expected:
                actual_size = os.path.getsize(asset_id)
                if actual_size < expected["min_size"]:
                    status = "FAILED"
                    results.append(f"File size {actual_size} is less than expected {expected['min_size']}.")
            
            # Check content
            if "content" in expected:
                with open(asset_id, 'r') as f:
                    actual_content = f.read()
                if actual_content.strip() != expected["content"].strip():
                    status = "FAILED"
                    results.append("Content mismatch.")
                    # Generate Diff
                    diff_list = difflib.ndiff(
                        expected["content"].splitlines(keepends=True),
                        actual_content.splitlines(keepends=True)
                    )
                    diff = "".join(diff_list)

            # Check line count
            if "line_count" in expected:
                with open(asset_id, 'r') as f:
                    actual_lines = len(f.readlines())
                if actual_lines != expected["line_count"]:
                    status = "FAILED"
                    results.append(f"Line count mismatch. Expected {expected['line_count']}, found {actual_lines}.")

    elif asset_type == "lark_entity":
        # Placeholder for Lark check, as it requires API calls
        # The script will rely on the Agent to provide actual state for validation if it's already pulled
        actual_state = config.get("actual")
        if not actual_state:
            status = "FAILED"
            results.append("Lark validation requires 'actual' state to be pulled and provided to the checker.")
        else:
            # Compare JSON
            if expected != actual_state:
                status = "FAILED"
                results.append("Lark entity state mismatch.")
                diff = json.dumps({"expected": expected, "actual": actual_state}, indent=2)

    # Output report
    report = {
        "status": status,
        "results": results,
        "diff": diff,
        "instruction": "MUST RETRY" if status == "FAILED" else "PASSED"
    }

    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
