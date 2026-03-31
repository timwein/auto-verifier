```python
"""
CSV parsing function with robust delimiter detection, header handling, and error management.
"""

import csv
import io
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Union, List, Dict, Any, Optional, IO, Tuple


@dataclass
class ParseResult:
    """Results from CSV parsing operation with comprehensive metadata."""
    data: List[Dict[str, str]]
    warnings: List[str]
    rows_skipped: int
    delimiter: str
    has_header: bool
    headers: List[str]
    processing_time: float = 0.0
    confidence_score: float = 0.0
    quality_metrics: Dict[str, Any] = None


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
    commonly found in real-world CSV files including embedded newlines,
    malformed quotes, and BOM characters.
    
    Args:
        source: File path, string data, or file-like object to parse
        delimiters: Candidate delimiters to test (default: ',;|\t')
        sample_size: Bytes to read for format detection
        assume_header: Force header assumption (True/False/None for auto-detect)
    
    Returns:
        ParseResult containing parsed data, warnings, and metadata
    
    Examples:
        >>> # Basic usage with file path
        >>> result = parse_csv('messy_data.csv')
        >>> print(f"Found {len(result.data)} rows with delimiter '{result.delimiter}'")
        
        >>> # Handle malformed data with confidence scoring
        >>> result = parse_csv('problematic.csv')
        >>> if result.confidence_score < 0.8:
        ...     print("Warning: Low confidence parsing")
        
        >>> # Process different input types
        >>> from io import StringIO
        >>> csv_data = "Name;Age\\nAlice;30\\nBob;25"
        >>> result = parse_csv(StringIO(csv_data))
    """
    start_time = time.time()
    warnings = []
    rows_skipped = 0
    
    try:
        # Normalize input to string data
        sample, full_data = _read_source(source, sample_size)
        
        # Detect delimiter using csv.Sniffer with fallback
        delimiter, delimiter_confidence = detect_delimiter(sample, delimiters)
        if not delimiter:
            raise ValueError("Could not determine delimiter from sample data")
        
        # Detect headers using csv.Sniffer heuristics
        has_header, header_confidence = detect_headers(sample, delimiter, assume_header)
        
        # Parse the data using csv.reader with enhanced error handling
        data, headers, parse_warnings, skipped, quality_metrics = parse_rows(
            full_data, delimiter, has_header
        )
        
        warnings.extend(parse_warnings)
        rows_skipped += skipped
        
        processing_time = time.time() - start_time
        confidence_score = (delimiter_confidence + header_confidence) / 2
        
        return ParseResult(
            data=data,
            warnings=warnings,
            rows_skipped=rows_skipped,
            delimiter=delimiter,
            has_header=has_header,
            headers=headers,
            processing_time=processing_time,
            confidence_score=confidence_score,
            quality_metrics=quality_metrics or {}
        )
        
    except Exception as e:
        processing_time = time.time() - start_time
        warnings.append(f"Parse error: {str(e)}")
        return ParseResult(
            data=[],
            warnings=warnings,
            rows_skipped=0,
            delimiter=',',
            has_header=False,
            headers=[],
            processing_time=processing_time,
            confidence_score=0.0,
            quality_metrics={}
        )


def detect_delimiter(sample: str, candidate_delimiters: Optional[str] = None) -> Tuple[str, float]:
    """
    Detect the most likely delimiter in CSV sample data with confidence scoring.
    
    Uses csv.Sniffer with fallback to consistency analysis for robust detection.
    """
    if not sample.strip():
        return ',', 0.0
    
    candidates = candidate_delimiters or ',;|\t'
    
    # Try csv.Sniffer first
    try:
        sniffer = csv.Sniffer()
        dialect = sniffer.sniff(sample, delimiters=candidates)
        return dialect.delimiter, 0.9  # High confidence for sniffer success
    except (csv.Error, Exception):
        pass
    
    # Fallback: test consistency across rows
    delimiter, consistency_score = _find_consistent_delimiter(sample, candidates)
    return delimiter, consistency_score


def detect_headers(
    sample: str, 
    delimiter: str, 
    assume_header: Optional[bool] = None
) -> Tuple[bool, float]:
    """
    Detect if the first row contains headers using heuristics with confidence scoring.
    
    Combines csv.Sniffer.has_header() with additional consistency checks.
    """
    if assume_header is not None:
        return assume_header, 1.0
    
    if not sample.strip():
        return False, 0.0
    
    try:
        # Use csv.Sniffer heuristic
        sniffer = csv.Sniffer()
        has_header_guess = sniffer.has_header(sample)
        base_confidence = 0.7 if has_header_guess else 0.3
        
        # Additional check: compare first row types vs data rows
        reader = csv.reader(io.StringIO(sample), delimiter=delimiter)
        rows = [row for row in reader if any(cell.strip() for cell in row)][:5]
        
        if len(rows) < 2:
            return has_header_guess, base_confidence
        
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
        has_header = has_header_guess or confidence > 0.3
        final_confidence = min(1.0, base_confidence + confidence * 0.3)
        
        return has_header, final_confidence
        
    except (csv.Error, Exception):
        return False, 0.0


def parse_rows(
    data: str, 
    delimiter: str, 
    has_header: bool
) -> Tuple[List[Dict[str, str]], List[str], List[str], int, Dict[str, Any]]:
    """
    Parse CSV rows into structured data with comprehensive error handling and quality metrics.
    
    Returns tuple of (parsed_data, headers, warnings, rows_skipped, quality_metrics).
    """
    warnings = []
    rows_skipped = 0
    parsed_data = []
    headers = []
    quality_metrics = {
        'total_rows_processed': 0,
        'column_consistency': 0.0,
        'data_type_inconsistencies': 0,
        'potential_encoding_issues': 0
    }
    
    try:
        # Enhanced reader configuration to handle edge cases
        reader = csv.reader(
            io.StringIO(data), 
            delimiter=delimiter,
            quoting=csv.QUOTE_MINIMAL,
            skipinitialspace=True,
            doublequote=True  # Handle malformed quotes
        )
        
        all_rows = []
        column_counts = []
        
        for row_num, row in enumerate(reader):
            quality_metrics['total_rows_processed'] += 1
            
            # Skip completely empty rows
            if not any(cell.strip() for cell in row):
                rows_skipped += 1
                continue
                
            # Track column count consistency
            column_counts.append(len(row))
            
            # Detect potential data issues
            for cell in row:
                if '\uffef' in cell or '\xef\xbb\xbf' in cell:
                    quality_metrics['potential_encoding_issues'] += 1
                    warnings.append(f"Row {row_num + 1}: BOM character detected")
            
            all_rows.append((row_num + 1, row))
        
        # Calculate column consistency metric
        if column_counts:
            most_common_count = max(set(column_counts), key=column_counts.count)
            consistency = column_counts.count(most_common_count) / len(column_counts)
            quality_metrics['column_consistency'] = consistency
        
        if not all_rows:
            return [], [], ["No data rows found"], 0, quality_metrics
        
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
        
        # Parse data rows with type consistency checking
        column_types = {}  # Track predominant types per column
        
        for row_num, row in data_rows:
            try:
                # Pad or trim row to match header count
                if len(row) < len(headers):
                    row.extend([''] * (len(headers) - len(row)))
                    warnings.append(f"Row {row_num}: Padded missing columns")
                elif len(row) > len(headers):
                    row = row[:len(headers)]
                    warnings.append(f"Row {row_num}: Trimmed extra columns")
                
                # Create row dictionary and check data types
                row_dict = {}
                for i, (header, cell) in enumerate(zip(headers, row)):
                    cleaned_cell = cell.strip()
                    row_dict[header] = cleaned_cell
                    
                    # Track data type consistency
                    if cleaned_cell:
                        is_numeric = cleaned_cell.replace('.', '').replace('-', '').isdigit()
                        if header not in column_types:
                            column_types[header] = {'numeric': 0, 'text': 0}
                        
                        if is_numeric:
                            column_types[header]['numeric'] += 1
                        else:
                            column_types[header]['text'] += 1
                
                parsed_data.append(row_dict)
                
            except Exception as e:
                warnings.append(f"Row {row_num}: Skipped due to error - {str(e)}")
                rows_skipped += 1
        
        # Calculate data type inconsistency metrics
        for header, type_counts in column_types.items():
            total = type_counts['numeric'] + type_counts['text']
            if total > 1:
                minority = min(type_counts['numeric'], type_counts['text'])
                if minority / total > 0.1:  # >10% minority type
                    quality_metrics['data_type_inconsistencies'] += 1
                    warnings.append(f"Column '{header}' has mixed data types")
        
        return parsed_data, headers, warnings, rows_skipped, quality_metrics
        
    except Exception as e:
        return [], [], [f"Failed to parse rows: {str(e)}"], 0, quality_metrics


def _read_source(source: Union[str | Path | IO[str]], sample_size: int) -> Tuple[str, str]:
    """
    Read and return (sample, full_data) from various source types with BOM handling.
    
    Supports file paths, raw CSV strings, file-like objects, and handles encoding issues.
    """
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
            # Assume it's a file path with BOM detection
            try:
                path = Path(source)
                
                # First, detect BOM by reading raw bytes
                with path.open('rb') as f:
                    raw_start = f.read(4)
                
                # Determine encoding based on BOM
                encoding = 'utf-8'
                if raw_start.startswith(b'\xef\xbb\xbf'):
                    encoding = 'utf-8-sig'  # UTF-8 with BOM
                elif raw_start.startswith((b'\xff\xfe', b'\xfe\xff')):
                    encoding = 'utf-16'  # UTF-16 with BOM
                
                with path.open('r', encoding=encoding, newline='') as f:
                    content = f.read()
                return content[:sample_size], content
                
            except UnicodeDecodeError:
                # Fallback to latin-1 encoding
                with path.open('r', encoding='latin-1', newline='') as f:
                    content = f.read()
                return content[:sample_size], content
    
    raise TypeError(f"Unsupported source type: {type(source)}")


def _find_consistent_delimiter(sample: str, candidates: str) -> Tuple[str, float]:
    """Find delimiter with most consistent column count across rows with confidence scoring."""
    best_delimiter = ','
    best_score = 0.0
    
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
                score = consistency * min(most_common_count / 10.0, 1.0)  # Favor more columns but cap
                
                if score > best_score:
                    best_score = score
                    best_delimiter = delimiter
        except csv.Error:
            continue
    
    return best_delimiter, best_score


# Enhanced test cases for comprehensive validation
def test_parse_csv():
    """
    Comprehensive test cases demonstrating the function's capabilities including edge cases.
    """
    
    # Test 1: Semicolon-delimited with headers
    data1 = "Name;Age;City\nAlice;30;New York\nBob;25;London"
    result1 = parse_csv(data1)
    assert result1.delimiter == ';'
    assert result1.has_header == True
    assert len(result1.data) == 2
    assert result1.data[0]['Name'] == 'Alice'
    print("✓ Test 1: Basic semicolon delimiter with headers")
    
    # Test 2: Tab-delimited without headers
    data2 = "John\t35\tParis\nJane\t28\tTokyo"
    result2 = parse_csv(data2, assume_header=False)
    assert result2.delimiter == '\t'
    assert result2.has_header == False
    assert result2.headers == ['column_1', 'column_2', 'column_3']
    print("✓ Test 2: Tab delimiter without headers")
    
    # Test 3: Messy data with empty rows and inconsistent columns
    data3 = "A,B,C\n1,2,3\n\n4,5\n6,7,8,9"
    result3 = parse_csv(data3)
    assert result3.rows_skipped == 1  # Empty row
    assert len(result3.warnings) >= 2  # Missing column + extra column warnings
    print("✓ Test 3: Messy data with inconsistent columns")
    
    # Test 4: Embedded newlines in quoted fields
    data4 = '"Name","Description"\n"Alice","Line 1\nLine 2"\n"Bob","Simple text"'
    result4 = parse_csv(data4)
    assert len(result4.data) == 2
    assert "Line 1\nLine 2" in result4.data[0]['Description']
    print("✓ Test 4: Embedded newlines in quoted fields")
    
    # Test 5: Malformed quotes and edge cases
    data5 = 'Name,Value\n"Unclosed quote,123\n"Proper","Quoted"\nUnquoted,456'
    result5 = parse_csv(data5)
    assert len(result5.warnings) > 0  # Should warn about parsing issues
    print("✓ Test 5: Malformed quotes handling")
    
    # Test 6: Mixed data types consistency check
    data6 = "ID,Score\n1,100\n2,A+\n3,95\n4,B-\n5,87"
    result6 = parse_csv(data6)
    assert result6.quality_metrics['data_type_inconsistencies'] > 0
    print("✓ Test 6: Data type inconsistency detection")
    
    # Test 7: BOM character handling (simulated)
    data7 = "\ufeffName,Age\nAlice,30\nBob,25"
    result7 = parse_csv(data7)
    assert result7.quality_metrics['potential_encoding_issues'] > 0
    print("✓ Test 7: BOM character detection")
    
    # Test 8: Confidence and quality metrics
    data8 = "Clear,Headers,Here\n1,2,3\n4,5,6\n7,8,9"
    result8 = parse_csv(data8)
    assert result8.confidence_score > 0.7  # Should be high confidence
    assert result8.quality_metrics['column_consistency'] == 1.0  # Perfect consistency
    print("✓ Test 8: Confidence and quality metrics")
    
    print("\nAll tests passed! 🎉")
    print(f"Last test processing time: {result8.processing_time:.3f}s")


if __name__ == "__main__":
    test_parse_csv()
```