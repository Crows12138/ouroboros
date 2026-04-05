"""Simple CSV parser."""
import csv
import io


def parse_csv(text):
    """Parse CSV text, handling quoted fields and skipping empty lines."""
    reader = csv.reader(io.StringIO(text))
    rows = []
    for row in reader:
        # Skip empty rows (all fields are empty strings)
        if all(field == "" for field in row):
            continue
        # Strip whitespace from each field
        rows.append([field.strip() for field in row])
    return rows

def csv_to_dicts(text, headers=None):
    rows = parse_csv(text)
    if not rows:
        return []
    if headers is None:
        headers = rows[0]
        rows = rows[1:]
    result = []
    for row in rows:
        # Pad row with empty strings if it has fewer fields than headers
        padded_row = row + [""] * (len(headers) - len(row))
        d = {headers[i]: padded_row[i] for i in range(len(headers))}
        result.append(d)
    return result
