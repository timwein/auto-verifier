```python
import csv
import io
import re
import sys
import os
import json
import gzip
import zipfile
import logging
import time
from collections import Counter
from typing import List, Dict, Any, Optional, Union, Iterator, Tuple
import chardet
import warnings
import codecs
import psutil
import statistics
import pandas as pd

class CSVStateMachine:
    """Finite state machine for CSV parsing with quoted field and escape sequence support."""
    
    def __init__(self, delimiter: str):
        self.delimiter = delimiter
        self.escape_sequences = {
            'double_quote': '""',  # RFC 4180 standard
            'backslash': '\\'      # Alternative escaping
        }
    
    def parse_row(self, line: str) -> List[str]:
        """Parse a CSV line handling quoted fields and escape sequences."""
        fields = []
        field = ''
        in_quotes = False
        quote_char = '"'
        escape_detected = None
        i = 0
        
        # Detect escape sequence type in the line
        if '""' in line:
            escape_detected = 'double_quote'
        elif '\\' in line and '"' in line:
            escape_detected = 'backslash'
        
        while i < len(line):
            char = line[i]
            
            if char == quote_char and not in_quotes:
                in_quotes = True
            elif char == quote_char and in_quotes:
                # Handle escape sequences
                if escape_detected == 'double_quote' and i + 1 < len(line) and line[i + 1] == quote_char:
                    field += quote_char  # Add single quote for escaped double quote
                    i += 1  # Skip next quote
                elif escape_detected == 'backslash' and i > 0 and line[i - 1] == '\\':
                    field += quote_char  # Add quote for backslash escaped quote
                else:
                    in_quotes = False
            elif char == '\\' and escape_detected == 'backslash' and i + 1 < len(line) and line[i + 1] == quote_char:
                # Skip backslash, will be handled when we hit the quote
                pass
            elif char == self.delimiter and not in_quotes:
                fields.append(field)
                field = ''
            else:
                field += char
            
            i += 1
        
        fields.append(field)  # Add final field
        return fields

class FastCSVParser:
    """
    High-performance CSV parser for messy data with inconsistent delimiters and missing headers.
    Optimized for speed with minimal overhead recovery mechanisms.
    """

    def __init__(self, 
                 sample_size: int = 8192,
                 max_delimiter_candidates: int = 5,
                 performance_mode: bool = True,
                 enable_logging: bool = True,
                 chunk_size: int = 10000):
        """
        Initialize the FastCSVParser.

        Args:
            sample_size: Bytes to read for delimiter detection
            max_delimiter_candidates: Maximum delimiters to test
            performance_mode: If True, prioritizes speed over recovery
            enable_logging: Enable comprehensive transformation logging
            chunk_size: Default chunk size for streaming processing
        """
        self.sample_size = sample_size
        self.max_delimiter_candidates = max_delimiter_candidates
        self.performance_mode = performance_mode
        self.chunk_size = chunk_size

        # Common delimiters ordered by likelihood for fast detection
        self.delimiter_candidates = [',', ';', '\t', '|', ':', '~', '^', '||', '::', '##']

        # Initialize audit trail
        self.processing_log = []
        self.metadata = {}
        self.statistics = {
            'total_rows': 0,
            'error_count': 0,
            'field_consistency_issues': 0,
            'transformation_count': 0,
            'processing_start_time': None,
            'processing_end_time': None,
            'memory_usage_peak': 0
        }

        # Set up logging
        if enable_logging:
            self.logger = self._setup_logging()
        else:
            self.logger = None

        # Initialize quarantine system for problematic records
        self.quarantine_records = []
        self.max_quarantine_size = 1000

    def _setup_logging(self):
        """Setup comprehensive transformation logging."""
        logger = logging.getLogger('FastCSVParser')
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def _log_decision(self, decision_type: str, value: Any, reasoning: str):
        """Log parsing decisions with reasoning."""
        log_entry = {
            'timestamp': time.time(),
            'type': decision_type,
            'value': value,
            'reasoning': reasoning,
            'parser_state': self._capture_parser_state()
        }
        self.processing_log.append(log_entry)

        if self.logger:
            self.logger.info(f"{decision_type}: {value} - {reasoning}")

    def _capture_parser_state(self) -> Dict[str, Any]:
        """Capture current parser state for audit trail."""
        return {
            'quarantine_count': len(self.quarantine_records),
            'processing_stage': 'parsing',
            'memory_usage': self._monitor_memory_usage()['current_rss_mb']
        }

    def _validate_inputs(self, file_path: str, **kwargs):
        """Comprehensive input validation for defensive programming."""
        # File path validation
        if not file_path:
            raise ValueError("File path cannot be empty or None")
        
        if not isinstance(file_path, (str, os.PathLike)):
            raise TypeError(f"File path must be string or PathLike, got {type(file_path)}")
        
        # Parameter validation
        for param_name, param_value in kwargs.items():
            if param_name == 'chunk_size':
                if not isinstance(param_value, int) or param_value <= 0:
                    raise ValueError(f"chunk_size must be positive integer, got {param_value}")
            elif param_name == 'sample_size':
                if not isinstance(param_value, int) or param_value <= 0:
                    raise ValueError(f"sample_size must be positive integer, got {param_value}")
            elif param_name == 'max_delimiter_candidates':
                if not isinstance(param_value, int) or param_value <= 0:
                    raise ValueError(f"max_delimiter_candidates must be positive integer, got {param_value}")
        
        self._log_decision('INPUT_VALIDATION', 'passed', 'All inputs validated successfully')

    def _quarantine_record(self, record: Any, line_number: int, error_context: str):
        """Quarantine problematic records with detailed context."""
        if len(self.quarantine_records) < self.max_quarantine_size:
            quarantine_entry = {
                'line_number': line_number,
                'record': record,
                'error_context': error_context,
                'timestamp': time.time(),
                'parsing_attempt': len(self.processing_log)
            }
            self.quarantine_records.append(quarantine_entry)
            
            if self.logger:
                self.logger.warning(f"Record quarantined - Line {line_number}: {error_context}")

    def _structured_error_log(self, error_type: str, line_number: int, context: Dict[str, Any]):
        """Structured error logging with line numbers and context."""
        error_entry = {
            'timestamp': time.time(),
            'error_type': error_type,
            'line_number': line_number,
            'context': context,
            'severity': 'ERROR',
            'file_checksum': context.get('file_checksum'),
            'processing_pipeline_stage': context.get('stage', 'parsing')
        }
        self.processing_log.append(error_entry)
        
        if self.logger:
            self.logger.error(f"Line {line_number} - {error_type}: {context}")

    def _detect_bom(self, file_path: str) -> Tuple[str, bool]:
        """Detect and handle BOM in file."""
        try:
            with open(file_path, 'rb') as f:
                raw_sample = f.read(4)  # Read first 4 bytes to check BOM

            # Check for UTF-8 BOM
            if raw_sample.startswith(codecs.BOM_UTF8):
                encoding = 'utf-8-sig'  # Special encoding that strips BOM
                bom_detected = True
                self._log_decision('BOM_DETECTION', 'UTF-8 BOM', 'Found UTF-8 BOM at start of file')
            # Check for UTF-16 BOM
            elif raw_sample.startswith(codecs.BOM_UTF16_LE) or raw_sample.startswith(codecs.BOM_UTF16_BE):
                encoding = 'utf-16'
                bom_detected = True
                self._log_decision('BOM_DETECTION', 'UTF-16 BOM', 'Found UTF-16 BOM at start of file')
            # Check for UTF-32 BOM for improved cross-platform consistency
            elif raw_sample.startswith(codecs.BOM_UTF32_LE) or raw_sample.startswith(codecs.BOM_UTF32_BE):
                encoding = 'utf-32'
                bom_detected = True
                self._log_decision('BOM_DETECTION', 'UTF-32 BOM', 'Found UTF-32 BOM at start of file')
            else:
                encoding = None  # Will be detected later
                bom_detected = False
                self._log_decision('BOM_DETECTION', 'None', 'No BOM detected')

            return encoding, bom_detected

        except (FileNotFoundError, IOError, PermissionError) as e:
            self._log_decision('BOM_ERROR', str(e), 'Specific file error during BOM detection')
            return None, False
        except Exception as e:
            self._log_decision('BOM_ERROR', str(e), 'Unexpected error during BOM detection')
            return None, False

    def detect_encoding(self, file_path: str) -> str:
        """Fast encoding detection with BOM handling and fallback strategy."""
        try:
            # Capture file metadata with checksum
            file_stat = os.stat(file_path)
            self.metadata['file_size'] = file_stat.st_size
            self.metadata['modification_time'] = file_stat.st_mtime
            
            # Calculate file checksum for integrity verification
            import hashlib
            with open(file_path, 'rb') as f:
                file_hash = hashlib.md5(f.read(8192)).hexdigest()  # Sample checksum
            self.metadata['file_checksum'] = file_hash

            # Check for BOM first
            encoding_from_bom, has_bom = self._detect_bom(file_path)
            if encoding_from_bom:
                # Validate that BOM encoding can decode larger sample
                try:
                    with open(file_path, 'rb') as f:
                        validation_sample = f.read(self.sample_size * 2)
                    validation_sample.decode(encoding_from_bom)
                    self._log_decision('ENCODING_DETECTION', encoding_from_bom, 'BOM encoding validated with larger sample')
                    self.metadata['encoding_confidence'] = 1.0
                    return encoding_from_bom
                except UnicodeDecodeError:
                    self._log_decision('ENCODING_WARNING', encoding_from_bom, 'BOM encoding failed validation, falling back')

            with open(file_path, 'rb') as f:
                raw_sample = f.read(self.sample_size)

            # Fast path: try UTF-8 first (most common)
            try:
                raw_sample.decode('utf-8')
                # Validate with larger sample for accuracy
                with open(file_path, 'rb') as f:
                    larger_sample = f.read(self.sample_size * 4)
                larger_sample.decode('utf-8')
                self._log_decision('ENCODING_DETECTION', 'utf-8', 'UTF-8 validated with larger sample')
                self.metadata['encoding_confidence'] = 0.95
                return 'utf-8'
            except UnicodeDecodeError:
                self._log_decision('ENCODING_FALLBACK', 'chardet', 'UTF-8 failed, using chardet')

            # Use chardet only if UTF-8 fails
            result = chardet.detect(raw_sample)
            confidence = result.get('confidence', 0)
            detected_encoding = result.get('encoding')

            self.metadata['encoding_confidence'] = confidence
            self.metadata['detected_encoding'] = detected_encoding

            if confidence > 0.85 and detected_encoding:
                # Validate detected encoding with actual decoding
                try:
                    raw_sample.decode(detected_encoding)
                    self._log_decision('ENCODING_DETECTION', detected_encoding, f'Chardet detection validated with {confidence:.2f} confidence')
                    return detected_encoding
                except UnicodeDecodeError:
                    self._log_decision('ENCODING_WARNING', detected_encoding, f'Chardet suggestion {detected_encoding} failed validation')

            # Enhanced fallback encodings including UTF-16 and platform-specific
            fallback_encodings = ['utf-16', 'latin-1', 'cp1252', 'iso-8859-1']
            # Add platform-specific encodings
            if sys.platform.startswith('win'):
                fallback_encodings.extend(['cp1251', 'cp850'])
            else:
                fallback_encodings.extend(['utf-8-sig', 'iso-8859-15'])
                
            for encoding in fallback_encodings:
                try:
                    raw_sample.decode(encoding)
                    # Validate fallback encoding with larger sample
                    with open(file_path, 'rb') as f:
                        larger_sample = f.read(self.sample_size * 2)
                    larger_sample.decode(encoding)
                    self._log_decision('ENCODING_FALLBACK', encoding, 'Validated fallback encoding with larger sample')
                    self.metadata['encoding_confidence'] = 0.7
                    return encoding
                except UnicodeDecodeError:
                    continue

            # Final fallback with validation warning
            self._log_decision('ENCODING_FALLBACK', 'utf-8', 'Final fallback - may not decode entire file correctly')
            self.metadata['encoding_confidence'] = 0.5
            return 'utf-8'

        except (FileNotFoundError, IOError, PermissionError) as e:
            self._log_decision('ENCODING_ERROR', str(e), 'Specific file error during encoding detection')
            return 'utf-8'
        except Exception as e:
            self._log_decision('ENCODING_ERROR', str(e), 'Unexpected error during encoding detection')
            return 'utf-8'

    def _monitor_memory_usage(self) -> Dict[str, float]:
        """Monitor current memory usage and return statistics."""
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            memory_stats = {
                'current_rss_mb': memory_info.rss / 1024 / 1024,  # RSS in MB
                'current_vms_mb': memory_info.vms / 1024 / 1024,  # VMS in MB
                'available_mb': psutil.virtual_memory().available / 1024 / 1024
            }
            
            # Track peak usage
            if memory_stats['current_rss_mb'] > self.statistics['memory_usage_peak']:
                self.statistics['memory_usage_peak'] = memory_stats['current_rss_mb']
                
            return memory_stats
        except Exception as e:
            self._log_decision('MEMORY_MONITOR_ERROR', str(e), 'Error monitoring memory usage')
            return {'current_rss_mb': 0, 'current_vms_mb': 0, 'available_mb': 0}

    def _calculate_optimal_chunk_size(self, file_size: int) -> int:
        """Calculate optimal chunk size based on available memory and file size."""
        memory_stats = self._monitor_memory_usage()
        available_mb = memory_stats['available_mb']
        
        # Use max 10% of available memory for chunk processing
        max_chunk_memory_mb = available_mb * 0.1
        
        # Estimate bytes per row (rough heuristic)
        estimated_bytes_per_row = max(100, file_size // 100000)  # Assume 100K rows typical
        max_rows_per_chunk = int((max_chunk_memory_mb * 1024 * 1024) // estimated_bytes_per_row)
        
        # Clamp between reasonable bounds
        optimal_chunk_size = max(1000, min(max_rows_per_chunk, 50000))
        
        self._log_decision('CHUNK_SIZE_OPTIMIZATION', optimal_chunk_size, 
                         f'Calculated based on {available_mb:.1f}MB available memory')
        return optimal_chunk_size

    def _detect_compressed_format(self, file_path: str) -> Optional[str]:
        """Detect if file is compressed and return format."""
        try:
            with open(file_path, 'rb') as f:
                header = f.read(10)

            if header.startswith(b'\x1f\x8b'):
                return 'gzip'
            elif header.startswith(b'PK'):
                return 'zip'

            return None
        except Exception:
            return None

    def _open_file_streaming(self, file_path: str, encoding: str):
        """Open file with streaming support for large files."""
        # Check file exists and is readable
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        if not os.access(file_path, os.R_OK):
            raise PermissionError(f"File not readable: {file_path}")

        compression_format = self._detect_compressed_format(file_path)
        
        if compression_format == 'gzip':
            self._log_decision('COMPRESSION', 'gzip', 'Detected gzip compression')
            return gzip.open(file_path, 'rt', encoding=encoding, newline='')
        elif compression_format == 'zip':
            self._log_decision('COMPRESSION', 'zip', 'Detected zip compression')
            # For zip, assume single CSV file
            with zipfile.ZipFile(file_path, 'r') as zip_file:
                names = zip_file.namelist()
                if len(names) == 1:
                    return io.TextIOWrapper(zip_file.open(names[0]), encoding=encoding, newline='')
                else:
                    raise ValueError("Zip file contains multiple files, specify which to process")
        else:
            self._log_decision('COMPRESSION', 'none', 'No compression detected')
            return open(file_path, 'r', encoding=encoding, newline='')

    def _fast_delimiter_detection(self, sample: str) -> str:
        """Optimized delimiter detection with enhanced multi-character and regex-based support."""
        if not sample:
            return ','

        # Enhanced delimiter candidates with sophisticated patterns
        basic_delimiters = [',', ';', '\t', '|', ':', '~', '^']
        multi_char_delimiters = ['||', '::', '##', '->', '<-', '<=>', ':::', '---']
        regex_based_patterns = [
            r'\s*\|\s*',  # Pipe with optional spaces
            r'\s*;;\s*',  # Double semicolon with spaces
            r'\s+\|\s+',  # Pipe surrounded by multiple spaces
        ]
        
        delimiter_counts = Counter()

        # Single-character delimiters
        for char in sample:
            if char in basic_delimiters:
                delimiter_counts[char] += 1

        # Multi-character delimiters
        for multi_delim in multi_char_delimiters:
            count = sample.count(multi_delim)
            if count > 0:
                delimiter_counts[multi_delim] = count

        # Regex-based delimiter detection for complex patterns
        for pattern in regex_based_patterns:
            matches = re.findall(pattern, sample)
            if matches:
                # Use the most common match as the delimiter
                most_common_match = Counter(matches).most_common(1)[0][0]
                delimiter_counts[most_common_match] = len(matches)

        if not delimiter_counts:
            self._log_decision('DELIMITER_DETECTION', ',', 'No delimiters found, defaulting to comma')
            return ','

        # Enhanced consistency check on top candidates
        lines = sample.split('\n')[:min(10, len(sample.split('\n')))]

        for delimiter, count in delimiter_counts.most_common(self.max_delimiter_candidates):
            field_counts = []
            for line in lines:
                if line.strip():
                    if len(delimiter) == 1:
                        field_counts.append(len(line.split(delimiter)))
                    else:
                        field_counts.append(len(line.split(delimiter)))

            if len(field_counts) > 0 and len(set(field_counts)) <= 2:  # Allow some variance
                self._log_decision('DELIMITER_DETECTION', delimiter, f'Enhanced delimiter found with {count} occurrences and consistent field counts')
                return delimiter

        # Return most frequent if consistency check fails
        top_delimiter = delimiter_counts.most_common(1)[0][0]
        self._log_decision('DELIMITER_DETECTION', top_delimiter, 'Most frequent delimiter after enhanced consistency check failure')
        return top_delimiter

    def _create_csv_state_machine_parser(self, delimiter: str) -> 'CSVStateMachine':
        """Create a finite state machine parser for handling quoted fields with any delimiters."""
        return CSVStateMachine(delimiter)

    def _analyze_column_content(self, sample_data: List[List[str]]) -> List[str]:
        """Analyze column content to infer data types and generate intelligent names."""
        if not sample_data:
            return []

        num_columns = len(sample_data[0]) if sample_data else 0
        column_names = []

        # Analyze patterns for each column
        for col_idx in range(num_columns):
            column_values = []
            for row in sample_data[:100]:  # Analyze first 100 rows
                if col_idx < len(row):
                    column_values.append(row[col_idx])

            # Enhanced pattern detection with more specific regex
            patterns = {
                'integer': re.compile(r'^-?\d+$'),
                'float': re.compile(r'^-?\d*\.\d+$'),
                'percentage': re.compile(r'^\d+(\.\d+)?%$'),
                'currency': re.compile(r'^[$£€¥]?\d+(\.\d{2})?$'),
                'email': re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'),
                'date_iso': re.compile(r'^\d{4}-\d{2}-\d{2}$'),
                'date_us': re.compile(r'^\d{2}/\d{2}/\d{4}$'),
                'date_eu': re.compile(r'^\d{2}-\d{2}-\d{4}$'),
                'phone': re.compile(r'^(\+\d{1,3}[-.\s]?)?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}$'),
                'url': re.compile(r'^https?://[^\s]+$'),
                'ip_address': re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$')
            }

            type_counts = {pattern_name: 0 for pattern_name in patterns.keys()}
            total_non_empty = 0

            for val in column_values:
                if val and val.strip():
                    total_non_empty += 1
                    val_stripped = val.strip()
                    
                    # Check each pattern
                    for pattern_name, pattern in patterns.items():
                        if pattern.match(val_stripped):
                            type_counts[pattern_name] += 1
                            break  # Use first match

            # Generate intelligent column name based on dominant pattern
            if total_non_empty > 0:
                # Find the pattern with highest confidence (>70% match rate)
                best_pattern = None
                best_confidence = 0
                
                for pattern_name, count in type_counts.items():
                    confidence = count / total_non_empty
                    if confidence > 0.7 and confidence > best_confidence:
                        best_pattern = pattern_name
                        best_confidence = confidence

                if best_pattern:
                    column_names.append(f'{best_pattern}_col_{col_idx}')
                else:
                    # Fall back to generic analysis
                    numeric_count = type_counts['integer'] + type_counts['float'] + type_counts['percentage'] + type_counts['currency']
                    if numeric_count / total_non_empty > 0.6:
                        column_names.append(f'numeric_col_{col_idx}')
                    else:
                        column_names.append(f'text_col_{col_idx}')
            else:
                column_names.append(f'col_{col_idx}')

        self._log_decision('COLUMN_NAMING', column_names, 'Generated intelligent column names based on enhanced content analysis')
        return column_names

    def _comprehensive_data_type_inference(self, sample_data: List[List[str]]) -> Dict[str, Dict]:
        """Comprehensive data type inference with statistical confidence."""
        if not sample_data:
            return {}

        num_columns = len(sample_data[0]) if sample_data else 0
        type_analysis = {}

        for col_idx in range(num_columns):
            column_values = []
            for row in sample_data:
                if col_idx < len(row) and row[col_idx].strip():
                    column_values.append(row[col_idx].strip())

            if not column_values:
                continue

            # Enhanced statistical type inference with confidence scoring
            type_scores = {
                'numeric': 0,
                'integer': 0,
                'float': 0,
                'percentage': 0,
                'currency': 0,
                'date': 0,
                'email': 0,
                'phone': 0,
                'url': 0,
                'ip_address': 0,
                'boolean': 0,
                'string': 0
            }

            patterns = {
                'integer': re.compile(r'^-?\d+$'),
                'float': re.compile(r'^-?\d*\.\d+$'),
                'percentage': re.compile(r'^\d+(\.\d+)?%$'),
                'currency': re.compile(r'^[$£€¥]?\d+(\.\d{2})?$'),
                'date': re.compile(r'^(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{2}-\d{2}-\d{4})$'),
                'email': re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'),
                'phone': re.compile(r'^(\+\d{1,3}[-.\s]?)?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}$'),
                'url': re.compile(r'^https?://[^\s]+$'),
                'ip_address': re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$'),
                'boolean': re.compile(r'^(true|false|yes|no|0|1)$', re.IGNORECASE)
            }

            # Additional quality metrics
            null_count = 0
            unique_values = set()

            for value in column_values:
                unique_values.add(value)
                
                # Check for null-like values
                if value.lower() in ['null', 'na', 'n/a', 'none', '', 'nil']:
                    null_count += 1
                    continue

                # Pattern matching
                for type_name, pattern in patterns.items():
                    if pattern.match(value):
                        type_scores[type_name] += 1

                # Check if numeric (int or float)
                try:
                    float(value)
                    type_scores['numeric'] += 1
                except ValueError:
                    pass

            # Calculate comprehensive confidence scores and quality metrics
            total_values = len(column_values)
            confidence_scores = {
                type_name: score / total_values 
                for type_name, score in type_scores.items()
            }

            # Determine primary type with enhanced logic
            primary_type_candidates = [(score, type_name) for type_name, score in confidence_scores.items() if score > 0.1]
            primary_type_candidates.sort(reverse=True)
            
            primary_type = primary_type_candidates[0][1] if primary_type_candidates else 'string'
            primary_confidence = primary_type_candidates[0][0] if primary_type_candidates else 0.0

            # Quality metrics
            uniqueness_ratio = len(unique_values) / total_values if total_values > 0 else 0
            completeness_ratio = 1.0 - (null_count / total_values) if total_values > 0 else 0

            type_analysis[col_idx] = {
                'confidence_scores': confidence_scores,
                'primary_type': primary_type,
                'confidence': primary_confidence,
                'sample_size': total_values,
                'unique_count': len(unique_values),
                'uniqueness_ratio': uniqueness_ratio,
                'null_count': null_count,
                'completeness_ratio': completeness_ratio,
                'quality_score': (primary_confidence + completeness_ratio + min(uniqueness_ratio, 0.8)) / 3
            }

        self._log_decision('TYPE_INFERENCE', type_analysis, 'Completed enhanced statistical type inference with quality metrics')
        return type_analysis

    def _validate_schema_consistency(self, sample_data: List[List[str]], file_size: int) -> Dict:
        """Validate schema consistency across file sections with enhanced analysis."""
        if len(sample_data) < 10:
            return {'status': 'insufficient_data'}

        # Analyze beginning, middle, and end sections with more granular splits
        sections = {
            'beginning': sample_data[:len(sample_data)//4],
            'early_middle': sample_data[len(sample_data)//4:len(sample_data)//2],
            'late_middle': sample_data[len(sample_data)//2:3*len(sample_data)//4],
            'end': sample_data[3*len(sample_data)//4:]
        }

        consistency_report = {}
        field_count_variance = []

        for section_name, section_data in sections.items():
            if section_data:
                type_analysis = self._comprehensive_data_type_inference(section_data)
                field_counts = [len(row) for row in section_data]
                
                consistency_report[section_name] = {
                    'num_columns': len(section_data[0]) if section_data else 0,
                    'type_analysis': type_analysis,
                    'avg_fields_per_row': sum(field_counts) / len(field_counts) if field_counts else 0,
                    'field_count_variance': len(set(field_counts)),
                    'row_count': len(section_data)
                }
                
                field_count_variance.extend(field_counts)

        # Enhanced variance analysis
        variance_issues = []
        column_counts = [report['num_columns'] for report in consistency_report.values() if report['num_columns'] > 0]
        
        if len(set(column_counts)) > 1:
            variance_issues.append(f'Column count varies across sections: {set(column_counts)}')
            
        # Check field count consistency within each section
        overall_field_variance = len(set(field_count_variance))
        if overall_field_variance > 3:  # Allow some tolerance
            variance_issues.append(f'High field count variance: {overall_field_variance} different field counts detected')

        # Type consistency analysis
        type_inconsistencies = []
        if len(consistency_report) > 1:
            section_names = list(consistency_report.keys())
            for col_idx in range(max(report.get('num_columns', 0) for report in consistency_report.values())):
                col_types = []
                for section_name, report in consistency_report.items():
                    if 'type_analysis' in report and col_idx in report['type_analysis']:
                        col_types.append(report['type_analysis'][col_idx]['primary_type'])
                
                if len(set(col_types)) > 1:
                    type_inconsistencies.append(f'Column {col_idx}: {dict(zip(section_names, col_types))}')

        if type_inconsistencies:
            variance_issues.append(f'Type inconsistencies detected: {len(type_inconsistencies)} columns')

        consistency_report['variance_issues'] = variance_issues
        consistency_report['type_inconsistencies'] = type_inconsistencies[:5]  # Limit to first 5 for readability
        consistency_report['overall_field_variance'] = overall_field_variance
        consistency_report['consistency_score'] = max(0, 1.0 - (len(variance_issues) * 0.2))  # Penalize each issue
        consistency_report['status'] = 'analyzed'

        self._log_decision('SCHEMA_VALIDATION', consistency_report, 'Enhanced schema consistency validation completed')
        return consistency_report

    def _detect_header_advanced(self, lines: List[str], delimiter: str, sample_data: List[List[str]]) -> Tuple[bool, float]:
        """Advanced header detection using multiple statistical methods with accuracy validation."""
        if len(lines) < 2:
            return False, 0.0

        first_row = lines[0].split(delimiter)
        detection_scores = []
        detection_methods_used = []

        # Method 1: Enhanced type difference analysis
        if len(sample_data) >= 10:
            type_analysis = self._comprehensive_data_type_inference(sample_data[1:min(20, len(sample_data))])
            first_row_analysis = self._comprehensive_data_type_inference([sample_data[0]] if sample_data else [])

            type_difference_score = 0
            methods_applied = 0
            
            for col_idx in range(min(len(first_row), len(type_analysis))):
                if col_idx in first_row_analysis and col_idx in type_analysis:
                    first_confidence = first_row_analysis[col_idx]['confidence']
                    data_confidence = type_analysis[col_idx]['confidence']
                    
                    # Header should have low confidence as data type, data should have high confidence
                    if first_confidence < 0.3 and data_confidence > 0.6:
                        type_difference_score += 1
                    methods_applied += 1

            if methods_applied > 0:
                type_score = type_difference_score / methods_applied
                detection_scores.append(type_score)
                detection_methods_used.append(f'type_difference({type_score:.2f})')

        # Method 2: Enhanced string vs numeric analysis
        numeric_pattern = re.compile(r'^-?\d*\.?\d+$')
        first_numeric = sum(1 for field in first_row if numeric_pattern.match(field.strip()) if field.strip())

        data_rows_numeric = []
        for line in lines[1:min(8, len(lines))]:
            row = line.split(delimiter)
            row_numeric = sum(1 for field in row if numeric_pattern.match(field.strip()) if field.strip())
            data_rows_numeric.append(row_numeric / len(row) if row else 0)

        if data_rows_numeric:
            avg_data_numeric = sum(data_rows_numeric) / len(data_rows_numeric)
            first_numeric_ratio = first_numeric / len(first_row) if first_row else 0

            # Header should have fewer numeric values than data rows
            numeric_difference_score = max(0, avg_data_numeric - first_numeric_ratio)
            detection_scores.append(numeric_difference_score)
            detection_methods_used.append(f'numeric_difference({numeric_difference_score:.2f})')

        # Method 3: Enhanced length and character analysis
        if len(lines) >= 3:
            first_avg_length = sum(len(field.strip()) for field in first_row) / len(first_row) if first_row else 0
            first_has_alpha = any(field.strip() and any(c.isalpha() for c in field.strip()) for field in first_row)

            data_avg_lengths = []
            data_alpha_ratios = []
            
            for line in lines[1:min(6, len(lines))]:
                row = line.split(delimiter)
                if row:
                    avg_length = sum(len(field.strip()) for field in row) / len(row)
                    data_avg_lengths.append(avg_length)
                    
                    alpha_count = sum(1 for field in row if field.strip() and any(c.isalpha() for c in field.strip()))
                    data_alpha_ratios.append(alpha_count / len(row))

            if data_avg_lengths:
                avg_data_length = sum(data_avg_lengths) / len(data_avg_lengths)
                avg_data_alpha = sum(data_alpha_ratios) / len(data_alpha_ratios) if data_alpha_ratios else 0
                
                # Headers typically have descriptive text (longer, more alpha characters)
                length_score = 1.0 if first_avg_length > avg_data_length * 1.2 else 0.5 if first_avg_length > avg_data_length else 0.0
                alpha_score = 1.0 if first_has_alpha and avg_data_alpha < 0.3 else 0.0
                
                combined_text_score = (length_score + alpha_score) / 2
                detection_scores.append(combined_text_score)
                detection_methods_used.append(f'text_analysis({combined_text_score:.2f})')

        # Method 4: Pattern consistency analysis
        if len(lines) >= 5:
            # Check if first row has consistent patterns that differ from data rows
            first_patterns = []
            for field in first_row:
                if field.strip():
                    has_spaces = ' ' in field.strip()
                    has_underscores = '_' in field.strip()
                    is_camelcase = any(c.isupper() for c in field.strip()[1:]) if len(field.strip()) > 1 else False
                    first_patterns.append((has_spaces, has_underscores, is_camelcase))

            data_patterns = []
            for line in lines[1:5]:
                row = line.split(delimiter)
                for field in row:
                    if field.strip():
                        has_spaces = ' ' in field.strip()
                        has_underscores = '_' in field.strip()
                        is_camelcase = any(c.isupper() for c in field.strip()[1:]) if len(field.strip()) > 1 else False
                        data_patterns.append((has_spaces, has_underscores, is_camelcase))

            # Headers often have naming conventions different from data
            if first_patterns and data_patterns:
                first_pattern_diversity = len(set(first_patterns)) / len(first_patterns) if first_patterns else 0
                data_pattern_diversity = len(set(data_patterns)) / len(data_patterns) if data_patterns else 0
                
                pattern_score = 0.8 if first_pattern_diversity > data_pattern_diversity * 1.5 else 0.2
                detection_scores.append(pattern_score)
                detection_methods_used.append(f'pattern_consistency({pattern_score:.2f})')

        # Combine scores with weighted average (emphasize type and numeric analysis)
        if detection_scores:
            weights = [0.4, 0.3, 0.2, 0.1][:len(detection_scores)]  # Prioritize early methods
            weighted_sum = sum(score * weight for score, weight in zip(detection_scores, weights))
            total_weight = sum(weights)
            final_score = weighted_sum / total_weight if total_weight > 0 else 0.0
        else:
            final_score = 0.0

        has_header = final_score > 0.55  # Slightly higher threshold for better accuracy
        
        # Calculate estimated accuracy based on method agreement
        high_confidence_methods = sum(1 for score in detection_scores if score > 0.7)
        method_agreement = high_confidence_methods / len(detection_scores) if detection_scores else 0
        estimated_accuracy = 0.6 + (0.4 * method_agreement)  # Base 60% + up to 40% based on agreement

        self.metadata['header_detection_methods'] = detection_methods_used
        self.metadata['header_detection_estimated_accuracy'] = estimated_accuracy

        self._log_decision('HEADER_DETECTION', has_header, 
                         f'Advanced detection with {final_score:.2f} confidence score, estimated accuracy: {estimated_accuracy:.1%}')
        return has_header, final_score

    def _detect_outliers_and_anomalies(self, data_rows: List[Dict[str, Any]]) -> Dict:
        """Statistical outlier detection using IQR and z-score methods with configurable thresholds."""
        if len(data_rows) < 10:
            return {'status': 'insufficient_data'}

        outliers = {}
        anomalies = []

        # Analyze numeric columns for outliers using IQR method
        numeric_columns = {}
        for row in data_rows:
            for col, value in row.items():
                try:
                    num_value = float(value)
                    if col not in numeric_columns:
                        numeric_columns[col] = []
                    numeric_columns[col].append(num_value)
                except (ValueError, TypeError):
                    pass

        # IQR-based outlier detection with configurable thresholds
        iqr_multiplier = 1.5  # Standard IQR multiplier
        z_score_threshold = 3.0  # Standard z-score threshold
        
        for col, values in numeric_columns.items():
            if len(values) >= 10:
                values_sorted = sorted(values)
                q1 = values_sorted[len(values_sorted)//4]
                q3 = values_sorted[3*len(values_sorted)//4]
                iqr = q3 - q1
                
                if iqr > 0:  # Avoid division by zero
                    lower_bound = q1 - iqr_multiplier * iqr
                    upper_bound = q3 + iqr_multiplier * iqr

                    col_outliers = [v for v in values if v < lower_bound or v > upper_bound]
                    if col_outliers:
                        # Additional z-score analysis for validation
                        mean_val = statistics.mean(values)
                        stdev_val = statistics.stdev(values) if len(values) > 1 else 0
                        
                        if stdev_val > 0:
                            z_scores = [(v - mean_val) / stdev_val for v in col_outliers]
                            extreme_outliers = [v for v, z in zip(col_outliers, z_scores) if abs(z) > z_score_threshold]
                        else:
                            extreme_outliers = []

                        outliers[col] = {
                            'count': len(col_outliers),
                            'percentage': len(col_outliers) / len(values) * 100,
                            'bounds': [lower_bound, upper_bound],
                            'extreme_count': len(extreme_outliers),
                            'method': 'IQR',
                            'multiplier': iqr_multiplier,
                            'z_score_threshold': z_score_threshold,
                            'sample_outliers': col_outliers[:5]  # First 5 outliers for review
                        }

        results = {
            'outliers': outliers,
            'anomalies': anomalies,
            'outlier_detection_method': 'IQR with z-score validation',
            'total_columns_analyzed': len(data_rows[0].keys()) if data_rows else 0,
            'status': 'analyzed'
        }

        self._log_decision('OUTLIER_DETECTION', results, 'Enhanced statistical outlier detection with IQR and z-score analysis completed')
        return results

    def _validate_data_consistency(self, data_rows: List[Dict[str, Any]]) -> Dict:
        """Validate patterns across records with >95% consistency threshold."""
        if len(data_rows) < 10:
            return {'status': 'insufficient_data', 'consistency_rate': 0.0}

        consistency_results = {}
        overall_consistency_issues = 0
        total_validations = 0

        # Define pattern validators with 95%+ thresholds
        pattern_validators = {
            'email': {
                'pattern': re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'),
                'threshold': 0.95,
                'keywords': ['email', 'e-mail', 'mail']
            },