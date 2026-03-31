```python
"""
CSV parsing function with robust delimiter detection, header handling, and error management.
"""

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Union, List, Dict, Any, Optional, IO, Tuple


@dataclass
class ParseResult:
    """Results from CSV parsing operation with metadata."""
    data: List[Dict[str, str]]
    warnings: List[str]
    rows_skipped: int
    delimiter: str
    has_header: bool
    headers: List[str]


def parse_csv(
    source: Union[str, Path, IO[str]],
    *,
    delimiters: Optional[str] = None,
    sample_size: int = 4096,
    assume_header: Optional[bool] = None
) -> ParseResult:
    """
    Parse messy CSV data with automatic delimiter detection and header handling.
    
    Handles inconsistent delimiters, missing headers, and various edge cases
    commonly found in real-world CSV files.
    
    Args:
        source: File path, string data, or file-like object to parse
        delimiters: Candidate delimiters to test (default: ',;|\t')
        sample_size: Bytes to read for format detection
        assume_header: Force header assumption (True/False/None for auto-detect)
    
    Returns:
        ParseResult containing parsed data, warnings, and metadata
    
    Example:
        >>> result = parse_csv('messy_data.csv')
        >>> print(f"Found {len(result.data)} rows with delimiter '{result.delimiter}'")
        >>> for warning in result.warnings:
        ...     print(f"Warning: {warning}")
    """
    warnings = []
    rows_skipped = 0
    
    try:
        # Normalize input to string data
        sample, full_data = _read_source(source, sample_size)
        
        # Detect delimiter
        delimiter = detect_delimiter(sample, delimiters)
        if not delimiter:
            raise ValueError("Could not determine delimiter from sample data")
        
        # Detect headers
        has_header = detect_headers(sample, delimiter, assume_header)
        
        # Parse the data
        data, headers, parse_warnings, skipped = parse_rows(
            full_data, delimiter, has_header
        )
        
        warnings.extend(parse_warnings)
        rows_skipped += skipped
        
        return ParseResult(
            data=data,
            warnings=warnings,
            rows_skipped=rows_skipped,
            delimiter=delimiter,
            has_header=has_header,
            headers=headers
        )
        
    except Exception as e:
        warnings.append(f"Parse error: {str(e)}")
        return ParseResult(
            data=[],
            warnings=warnings,
            rows_skipped=0,
            delimiter=',',
            has_header=False,
            headers=[]
        )


def detect_delimiter(sample: str, candidate_delimiters: Optional[str] = None) -> str:
    """
    Detect the most likely delimiter in CSV sample data.
    
    Uses csv.Sniffer with fallback to consistency analysis.
    """
    if not sample.strip():
        return ','
    
    candidates = candidate_delimiters or ',;|\t'
    
    # Try csv.Sniffer first
    try:
        
sniffer = csv.Sniffer()
        dialect = sniffer.sniff(sample, delimiters=candidates)

        return dialect.delimiter
    except (csv.Error, Exception):
        pass
    
    # Fallback: test consistency across rows
    return _find_consistent_delimiter(sample, candidates)


def detect_headers(sample: str, delimiter: str, assume_header: Optional[bool] = None) -> bool:
    """
    Detect if the first row contains headers using heuristics.
    
    Combines csv.Sniffer.has_header() with additional consistency checks.
    """
    if assume_header is not None:
        return assume_header
    
    if not sample.strip():
        return False
    
    try:
        # Use csv.Sniffer heuristic
        
sniffer = csv.Sniffer()
        has_header_guess = sniffer.has_header(sample)

        
        # Additional check: compare first row types vs data rows
        reader = csv.reader(io.StringIO(sample), delimiter=delimiter)
        rows = [row for row in reader if any(cell.strip() for cell in row)][:5]
        
        if len(rows) < 2:
            return has_header_guess
        
        # Check if first row values look like headers (non-numeric, different from data)
        first_row = rows[0]
        second_row = rows[1] if len(rows) > 1 else []
        
        header_indicators = 0
        for i, (header_val, data_val) in enumerate(zip(first_row, second_row)):
            # Headers often contain letters, data often numeric
            if header_val.strip() and not header_val.strip().replace('.', '').replace('-', '').isdigit():
                if data_val.strip().replace('.', '').replace('-', '').isdigit():
                    header_indicators += 1
        
        # Combine sniffer result with our heuristic
        confidence = header_indicators / max(len(first_row), 1)
        return has_header_guess or confidence > 0.3
        
    except (csv.Error, Exception):
        return False


def parse_rows(
    data: str, 
    delimiter: str, 
    has_header: bool
) -> Tuple[List[Dict[str, str]], List[str], List[str], int]:
    """
    Parse CSV rows into structured data with error handling.
    
    Returns tuple of (parsed_data, headers, warnings, rows_skipped).
    """
    warnings = []
    rows_skipped = 0
    parsed_data = []
    headers = []
    
    try:
        reader = csv.reader(
            io.StringIO(data), 
            delimiter=delimiter,
            quoting=csv.QUOTE_MINIMAL,
            skipinitialspace=True
        )
        
        all_rows = []
        for row_num, row in enumerate(reader):
            # Skip completely empty rows
            if not any(cell.strip() for cell in row):
                rows_skipped += 1
                continue
            all_rows.append((row_num + 1, row))
        
        if not all_rows:
            return [], [], ["No data rows found"], 0
        
        # Handle headers
        if has_header and all_rows:
            _, header_row = all_rows[0]
            headers = [col.strip() or f"column_{i+1}" for i, col in enumerate(header_row)]
            data_rows = all_rows[1:]
        else:
            # Generate default headers
            max_cols = max(len(row) for _, row in all_rows) if all_rows else 0
            headers = [f"column_{i+1}" for i in range(max_cols)]
            data_rows = all_rows
        
        # Parse data rows
        for row_num, row in data_rows:
            try:
                # Pad or trim row to match header count
                if len(row) < len(headers):
                    row.extend([''] * (len(headers) - len(row)))
                    warnings.append(f"Row {row_num}: Padded missing columns")
                elif len(row) > len(headers):
                    row = row[:len(headers)]
                    warnings.append(f"Row {row_num}: Trimmed extra columns")
                
                # Create row dictionary
                row_dict = {header: cell.strip() for header, cell in zip(headers, row)}
                parsed_data.append(row_dict)
                
            except Exception as e:
                warnings.append(f"Row {row_num}: Skipped due to error - {str(e)}")
                rows_skipped += 1
        
        return parsed_data, headers, warnings, rows_skipped
        
    except Exception as e:
        return [], [], [f"Failed to parse rows: {str(e)}"], 0


def _read_source(source: Union[str, Path, IO[str]], sample_size: int) -> Tuple[str, str]:
    """Read and return (sample, full_data) from various source types."""
    if hasattr(source, 'read'):
        # File-like object
        content = source.read()
        if hasattr(source, 'seek'):
            source.seek(0)
        return content[:sample_size], content
    
    elif isinstance(source, (str, Path)):
        if isinstance(source, str) and ('\n' in source or ',' in source or ';' in source):
            # Assume it's CSV data string
            return source[:sample_size], source
        else:
            # Assume it's a file path
            try:
                path = Path(source)
                with path.open('r', encoding='utf-8', newline='') as f:
                    content = f.read()
                return content[:sample_size], content
            except UnicodeDecodeError:
                # Fallback to latin-1 encoding
                with path.open('r', encoding='latin-1', newline='') as f:
                    content = f.read()
                return content[:sample_size], content
    
    raise TypeError(f"Unsupported source type: {type(source)}")


def _find_consistent_delimiter(sample: str, candidates: str) -> str:
    """Find delimiter with most consistent column count across rows."""
    
best_delimiter = ','
    best_score = 0
    
    for delimiter in candidates:
        try:
            reader = csv.reader(io.StringIO(sample), delimiter=delimiter)
            rows = [row for row in reader if any(row)][:10]  # Check first 10 rows
            
            if len(rows) < 2:
                continue
            
            # Calculate consistency score
            col_counts = [len(row) for row in rows]
            if col_counts and max(col_counts) > 1:
                most_common_count = max(set(col_counts), key=col_counts.count)
                consistency = col_counts.count(most_common_count) / len(col_counts)
                score = consistency * most_common_count  # Favor more columns
                
                if score > best_score:
                    best_score = score
                    best_delimiter = delimiter
        except csv.Error:
            continue
    
    return best_delimiter



# Test cases for validation
def test_parse_csv():
    """Example test cases demonstrating the function's capabilities."""
    
    # Test 1: Semicolon-delimited with headers
    data1 = "Name;Age;City\nAlice;30;New York\nBob;25;London"
    result1 = parse_csv(data1)
    assert result1.delimiter == ';'
    assert result1.has_header == True
    assert len(result1.data) == 2
    assert result1.data[0]['Name'] == 'Alice'
    
    # Test 2: Tab-delimited without headers
    data2 = "John\t35\tParis\nJane\t28\tTokyo"
    result2 = parse_csv(data2, assume_header=False)
    assert result2.delimiter == '\t'
    assert result2.has_header == False
    assert result2.headers == ['column_1', 'column_2', 'column_3']
    
    # Test 3: Messy data with empty rows and inconsistent columns
    data3 = "A,B,C\n1,2,3\n\n4,5\n6,7,8,9"
    result3 = parse_csv(data3)
    assert result3.rows_skipped == 1  # Empty row
    assert len(result3.warnings) == 2  # Missing column + extra column warnings
    
    # Test 4: File path input
    # result4 = parse_csv('test.csv')  # Uncomment to test with actual file
    
    print("All tests passed!")


if __name__ == "__main__":
    test_parse_csv()
```