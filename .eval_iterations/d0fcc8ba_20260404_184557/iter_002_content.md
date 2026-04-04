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

class FastCSVParser:
    """
    High-performance CSV parser for messy data with inconsistent delimiters and missing headers.
    Optimized for speed with minimal overhead recovery mechanisms.
    """

    def __init__(self, 
                 sample_size: int = 8192,
                 max_delimiter_candidates: int = 5,
                 performance_mode: bool = True,
                 enable_logging: bool = True):
        """
        Initialize the FastCSVParser.

        Args:
            sample_size: Bytes to read for delimiter detection
            max_delimiter_candidates: Maximum delimiters to test
            performance_mode: If True, prioritizes speed over recovery
            enable_logging: Enable comprehensive transformation logging
        """
        self.sample_size = sample_size
        self.max_delimiter_candidates = max_delimiter_candidates
        self.performance_mode = performance_mode

        # Common delimiters ordered by likelihood for fast detection
        self.delimiter_candidates = [',', ';', '\t', '|', ':', '~', '^', '||', '::', '##']

        # Initialize audit trail
        self.processing_log = []
        self.metadata = {}
        self.statistics = {
            'total_rows': 0,
            'error_count': 0,
            'field_consistency_issues': 0,
            'transformation_count': 0
        }

        # Set up logging
        if enable_logging:
            self.logger = self._setup_logging()
        else:
            self.logger = None

    def _setup_logging(self):
        """Setup comprehensive transformation logging."""
        logger = logging.getLogger('FastCSVParser')
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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
            'reasoning': reasoning
        }
        self.processing_log.append(log_entry)

        if self.logger:
            self.logger.info(f"{decision_type}: {value} - {reasoning}")

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
            else:
                encoding = None  # Will be detected later
                bom_detected = False
                self._log_decision('BOM_DETECTION', 'None', 'No BOM detected')

            return encoding, bom_detected

        except Exception as e:
            self._log_decision('BOM_ERROR', str(e), 'Error during BOM detection')
            return None, False

    def detect_encoding(self, file_path: str) -> str:
        """Fast encoding detection with BOM handling and fallback strategy."""
        try:
            # Capture file metadata
            file_stat = os.stat(file_path)
            self.metadata['file_size'] = file_stat.st_size
            self.metadata['modification_time'] = file_stat.st_mtime

            # Check for BOM first
            encoding_from_bom, has_bom = self._detect_bom(file_path)
            if encoding_from_bom:
                self._log_decision('ENCODING_DETECTION', encoding_from_bom, 'Encoding determined from BOM')
                return encoding_from_bom

            with open(file_path, 'rb') as f:
                raw_sample = f.read(self.sample_size)

            # Fast path: try UTF-8 first (most common)
            try:
                raw_sample.decode('utf-8')
                self._log_decision('ENCODING_DETECTION', 'utf-8', 'UTF-8 decoding successful on fast path')
                return 'utf-8'
            except UnicodeDecodeError:
                self._log_decision('ENCODING_FALLBACK', 'chardet', 'UTF-8 failed, using chardet')

            # Use chardet only if UTF-8 fails
            result = chardet.detect(raw_sample)
            confidence = result.get('confidence', 0)
            detected_encoding = result.get('encoding')

            self.metadata['encoding_confidence'] = confidence
            self.metadata['detected_encoding'] = detected_encoding

            if confidence > 0.7 and detected_encoding:
                self._log_decision('ENCODING_DETECTION', detected_encoding, f'Chardet detection with {confidence:.2f} confidence')
                return detected_encoding

            # Enhanced fallback encodings including UTF-16
            for encoding in ['utf-16', 'latin-1', 'cp1252', 'iso-8859-1']:
                try:
                    raw_sample.decode(encoding)
                    self._log_decision('ENCODING_FALLBACK', encoding, 'Successful fallback encoding')
                    return encoding
                except UnicodeDecodeError:
                    continue

            self._log_decision('ENCODING_FALLBACK', 'utf-8', 'Final fallback to utf-8')
            return 'utf-8'  # Final fallback

        except Exception as e:
            self._log_decision('ENCODING_ERROR', str(e), 'Error during encoding detection')
            return 'utf-8'

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

    def _open_file(self, file_path: str, encoding: str):
        """Open file handling compression."""
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
        """Optimized delimiter detection with multi-character support."""
        if not sample:
            return ','

        # Count occurrences of delimiter candidates including multi-character
        delimiter_counts = Counter()

        # Single-character delimiters
        for char in sample:
            if char in [',', ';', '\t', '|', ':', '~', '^']:
                delimiter_counts[char] += 1

        # Multi-character delimiters
        for multi_delim in ['||', '::', '##']:
            count = sample.count(multi_delim)
            if count > 0:
                delimiter_counts[multi_delim] = count

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
                self._log_decision('DELIMITER_DETECTION', delimiter, f'Delimiter found with {count} occurrences and consistent field counts')
                return delimiter

        # Return most frequent if consistency check fails
        top_delimiter = delimiter_counts.most_common(1)[0][0]
        self._log_decision('DELIMITER_DETECTION', top_delimiter, 'Most frequent delimiter after consistency check failure')
        return top_delimiter

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

            # Pattern detection
            numeric_pattern = re.compile(r'^-?\d*\.?\d+$')
            email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
            date_pattern = re.compile(r'^(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{2}-\d{2}-\d{4})$')
            phone_pattern = re.compile(r'^(\+\d{1,3}[-.\s]?)?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}$')

            numeric_count = sum(1 for val in column_values if numeric_pattern.match(val.strip()) if val.strip())
            email_count = sum(1 for val in column_values if email_pattern.match(val.strip()) if val.strip())
            date_count = sum(1 for val in column_values if date_pattern.match(val.strip()) if val.strip())
            phone_count = sum(1 for val in column_values if phone_pattern.match(val.strip()) if val.strip())

            total_non_empty = sum(1 for val in column_values if val.strip())

            # Generate intelligent column name based on content analysis
            if total_non_empty > 0:
                if numeric_count / total_non_empty > 0.8:
                    column_names.append(f'numeric_col_{col_idx}')
                elif email_count / total_non_empty > 0.8:
                    column_names.append(f'email_col_{col_idx}')
                elif date_count / total_non_empty > 0.8:
                    column_names.append(f'date_col_{col_idx}')
                elif phone_count / total_non_empty > 0.8:
                    column_names.append(f'phone_col_{col_idx}')
                else:
                    column_names.append(f'text_col_{col_idx}')
            else:
                column_names.append(f'col_{col_idx}')

        self._log_decision('COLUMN_NAMING', column_names, 'Generated intelligent column names based on content analysis')
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

            # Statistical type inference with confidence scoring
            type_scores = {
                'numeric': 0,
                'integer': 0,
                'float': 0,
                'date': 0,
                'email': 0,
                'phone': 0,
                'string': 0
            }

            patterns = {
                'integer': re.compile(r'^-?\d+$'),
                'float': re.compile(r'^-?\d*\.\d+$'),
                'date': re.compile(r'^(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{2}-\d{2}-\d{4})$'),
                'email': re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'),
                'phone': re.compile(r'^(\+\d{1,3}[-.\s]?)?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}$')
            }

            for value in column_values:
                for type_name, pattern in patterns.items():
                    if pattern.match(value):
                        type_scores[type_name] += 1

                # Check if numeric (int or float)
                try:
                    float(value)
                    type_scores['numeric'] += 1
                except ValueError:
                    pass

            # Calculate confidence scores
            total_values = len(column_values)
            confidence_scores = {
                type_name: score / total_values 
                for type_name, score in type_scores.items()
            }

            # Determine primary type
            primary_type = max(confidence_scores.items(), key=lambda x: x[1])

            type_analysis[col_idx] = {
                'confidence_scores': confidence_scores,
                'primary_type': primary_type[0],
                'confidence': primary_type[1],
                'sample_size': total_values
            }

        self._log_decision('TYPE_INFERENCE', type_analysis, 'Completed statistical type inference with confidence scoring')
        return type_analysis

    def _validate_schema_consistency(self, sample_data: List[List[str]], file_size: int) -> Dict:
        """Validate schema consistency across file sections."""
        if len(sample_data) < 10:
            return {'status': 'insufficient_data'}

        # Analyze beginning, middle, and end sections
        sections = {
            'beginning': sample_data[:len(sample_data)//3],
            'middle': sample_data[len(sample_data)//3:2*len(sample_data)//3],
            'end': sample_data[2*len(sample_data)//3:]
        }

        consistency_report = {}

        for section_name, section_data in sections.items():
            if section_data:
                type_analysis = self._comprehensive_data_type_inference(section_data)
                consistency_report[section_name] = {
                    'num_columns': len(section_data[0]) if section_data else 0,
                    'type_analysis': type_analysis
                }

        # Check for variance
        variance_issues = []
        if len(set([report['num_columns'] for report in consistency_report.values()])) > 1:
            variance_issues.append('Column count varies across sections')

        consistency_report['variance_issues'] = variance_issues
        consistency_report['status'] = 'analyzed'

        self._log_decision('SCHEMA_VALIDATION', consistency_report, 'Schema consistency validation completed')
        return consistency_report

    def _detect_header_advanced(self, lines: List[str], delimiter: str, sample_data: List[List[str]]) -> Tuple[bool, float]:
        """Advanced header detection using multiple statistical methods."""
        if len(lines) < 2:
            return False, 0.0

        first_row = lines[0].split(delimiter)

        # Multiple detection methods
        detection_scores = []

        # Method 1: Type difference analysis
        if len(sample_data) >= 10:
            type_analysis = self._comprehensive_data_type_inference(sample_data[1:10])  # Skip potential header
            first_row_analysis = self._comprehensive_data_type_inference([sample_data[0]] if sample_data else [])

            type_difference_score = 0
            for col_idx in range(min(len(first_row), len(type_analysis))):
                if col_idx in first_row_analysis and col_idx in type_analysis:
                    first_confidence = first_row_analysis[col_idx]['confidence']
                    data_confidence = type_analysis[col_idx]['confidence']
                    if abs(first_confidence - data_confidence) > 0.3:
                        type_difference_score += 1

            detection_scores.append(type_difference_score / len(first_row) if first_row else 0)

        # Method 2: String vs numeric analysis
        numeric_pattern = re.compile(r'^-?\d*\.?\d+$')
        first_numeric = sum(1 for field in first_row if numeric_pattern.match(field.strip()) if field.strip())

        data_rows_numeric = []
        for line in lines[1:min(6, len(lines))]:
            row = line.split(delimiter)
            row_numeric = sum(1 for field in row if numeric_pattern.match(field.strip()) if field.strip())
            data_rows_numeric.append(row_numeric / len(row) if row else 0)

        avg_data_numeric = sum(data_rows_numeric) / len(data_rows_numeric) if data_rows_numeric else 0
        first_numeric_ratio = first_numeric / len(first_row) if first_row else 0

        numeric_difference_score = max(0, avg_data_numeric - first_numeric_ratio)
        detection_scores.append(numeric_difference_score)

        # Method 3: Length and character analysis
        if len(lines) >= 3:
            first_avg_length = sum(len(field) for field in first_row) / len(first_row) if first_row else 0

            data_avg_lengths = []
            for line in lines[1:4]:
                row = line.split(delimiter)
                avg_length = sum(len(field) for field in row) / len(row) if row else 0
                data_avg_lengths.append(avg_length)

            avg_data_length = sum(data_avg_lengths) / len(data_avg_lengths) if data_avg_lengths else 0
            length_score = 1.0 if first_avg_length > avg_data_length * 0.8 else 0.0
            detection_scores.append(length_score)

        # Combine scores
        final_score = sum(detection_scores) / len(detection_scores) if detection_scores else 0.0
        has_header = final_score > 0.5

        self._log_decision('HEADER_DETECTION', has_header, f'Advanced detection with {final_score:.2f} confidence score')
        return has_header, final_score

    def _detect_outliers_and_anomalies(self, data_rows: List[Dict[str, Any]]) -> Dict:
        """Statistical outlier detection and anomaly detection."""
        if len(data_rows) < 10:
            return {'status': 'insufficient_data'}

        outliers = {}
        anomalies = []

        # Analyze numeric columns for outliers
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

        # IQR-based outlier detection
        for col, values in numeric_columns.items():
            if len(values) >= 10:
                values.sort()
                q1 = values[len(values)//4]
                q3 = values[3*len(values)//4]
                iqr = q3 - q1
                lower_bound = q1 - 1.5 * iqr
                upper_bound = q3 + 1.5 * iqr

                col_outliers = [v for v in values if v < lower_bound or v > upper_bound]
                if col_outliers:
                    outliers[col] = {
                        'count': len(col_outliers),
                        'percentage': len(col_outliers) / len(values) * 100,
                        'bounds': [lower_bound, upper_bound]
                    }

        # Pattern consistency validation
        pattern_consistency = {}
        for col in data_rows[0].keys():
            values = [row[col] for row in data_rows[:100] if row.get(col)]

            # Check email consistency
            if 'email' in col.lower():
                email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
                valid_emails = sum(1 for val in values if email_pattern.match(str(val).strip()))
                consistency_rate = valid_emails / len(values) if values else 0
                pattern_consistency[col] = {
                    'type': 'email',
                    'consistency_rate': consistency_rate,
                    'valid_count': valid_emails,
                    'total_count': len(values)
                }

        results = {
            'outliers': outliers,
            'anomalies': anomalies,
            'pattern_consistency': pattern_consistency,
            'status': 'analyzed'
        }

        self._log_decision('QUALITY_VALIDATION', results, 'Statistical quality validation completed')
        return results

    def _generate_data_profile(self, data_rows: List[Dict[str, Any]]) -> Dict:
        """Generate comprehensive data profiling statistics."""
        if not data_rows:
            return {'status': 'no_data'}

        profile = {
            'total_rows': len(data_rows),
            'columns': {}
        }

        # Analyze each column
        for col in data_rows[0].keys():
            values = [row.get(col, '') for row in data_rows]
            non_empty_values = [v for v in values if v and str(v).strip()]

            col_profile = {
                'total_values': len(values),
                'non_empty_count': len(non_empty_values),
                'null_count': len(values) - len(non_empty_values),
                'null_percentage': (len(values) - len(non_empty_values)) / len(values) * 100,
                'unique_count': len(set(str(v) for v in non_empty_values)),
                'uniqueness_rate': len(set(str(v) for v in non_empty_values)) / len(non_empty_values) if non_empty_values else 0
            }

            # Type distribution
            type_counts = {'string': 0, 'numeric': 0, 'date': 0, 'other': 0}
            for value in non_empty_values:
                str_val = str(value).strip()
                if re.match(r'^-?\d*\.?\d+$', str_val):
                    type_counts['numeric'] += 1
                elif re.match(r'^(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})$', str_val):
                    type_counts['date'] += 1
                elif str_val:
                    type_counts['string'] += 1
                else:
                    type_counts['other'] += 1

            col_profile['type_distribution'] = type_counts
            profile['columns'][col] = col_profile

        self._log_decision('DATA_PROFILING', profile, 'Comprehensive data profiling completed')
        return profile

    def _get_memory_usage(self) -> Dict:
        """Monitor current memory usage."""
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            return {
                'rss_mb': memory_info.rss / 1024 / 1024,
                'vms_mb': memory_info.vms / 1024 / 1024,
                'percent': process.memory_percent()
            }
        except ImportError:
            return {'error': 'psutil not available'}

    def _calculate_optimal_chunk_size(self, file_size: int) -> int:
        """Calculate optimal chunk size based on file size and available memory."""
        try:
            available_memory = psutil.virtual_memory().available
            # Use 10% of available memory or 100MB, whichever is smaller
            optimal_size = min(available_memory * 0.1, 100 * 1024 * 1024)

            # Convert to approximate row count (assuming average 100 bytes per row)
            chunk_rows = int(optimal_size / 100)

            self._log_decision('CHUNK_SIZE', chunk_rows, f'Calculated based on {available_memory/1024/1024:.1f}MB available memory')
            return max(1000, min(chunk_rows, 50000))  # Between 1K and 50K rows

        except ImportError:
            return 10000  # Default fallback

    def parse_csv_fast(self, 
                      file_path: str,
                      encoding: Optional[str] = None,
                      delimiter: Optional[str] = None,
                      has_header: Optional[bool] = None,
                      max_errors: int = 100,
                      chunk_size: Optional[int] = None,
                      recovery_strategy: str = 'fast_fail') -> Iterator[Dict[str, Any]]:
        """
        High-performance CSV parsing with comprehensive features and audit trail.

        Args:
            file_path: Path to CSV file
            encoding: File encoding (auto-detected if None)
            delimiter: Column delimiter (auto-detected if None)  
            has_header: Whether file has header row (auto-detected if None)
            max_errors: Maximum parsing errors before failing
            chunk_size: Rows per chunk for memory optimization
            recovery_strategy: 'fast_fail', 'skip', 'pad', or 'quarantine'

        Yields:
            Dictionary records from CSV with metadata
        """

        start_time = time.time()
        processing_start = time.time()

        # Capture processing metadata
        self.metadata.update({
            'file_path': file_path,
            'processing_timestamp': processing_start,
            'parameters': {
                'max_errors': max_errors,
                'chunk_size': chunk_size,
                'recovery_strategy': recovery_strategy
            }
        })

        # Auto-detect encoding if not provided
        if encoding is None:
            encoding = self.detect_encoding(file_path)

        self.metadata['encoding_used'] = encoding

        # Calculate optimal chunk size if not provided
        file_size = os.path.getsize(file_path)
        if chunk_size is None:
            chunk_size = self._calculate_optimal_chunk_size(file_size)

        try:
            with self._open_file(file_path, encoding) as f:
                # Read sample for parameter detection
                sample = f.read(self.sample_size)
                f.seek(0)

                # Auto-detect delimiter if not provided
                if delimiter is None:
                    delimiter = self._fast_delimiter_detection(sample)

                self.metadata['delimiter_used'] = delimiter

                # Enhanced CSV reader configuration
                csv.field_size_limit(min(sys.maxsize, 2**20))  # 1MB field limit

                # 
Use pandas for better performance with pyarrow engine when available

                # But maintain compatibility with csv module for complex scenarios

                try:
                    # Try to use pandas with pyarrow for optimal performance
                    import pandas as pd

                    # Reset file position for pandas
                    f.seek(0)

                    # 
Use pyarrow engine for significantly better performance with parallelism

                    df_chunk_iter = pd.read_csv(
                        f,
                        delimiter=delimiter,
                        chunksize=chunk_size,
                        engine='pyarrow' if hasattr(pd, 'read_csv') else 'c',
                        encoding=encoding,
                        header='infer' if has_header is None else (0 if has_header else None),
                        on_bad_lines='skip' if recovery_strategy == 'skip' else 'error'
                    )

                    self._log_decision('PARSER_ENGINE', 'pandas_pyarrow', 'Using pandas with pyarrow engine for optimal performance')

                    # Process chunks with memory monitoring
                    for chunk_df in df_chunk_iter:
                        memory_usage = self._get_memory_usage()
                        self.metadata['peak_memory_mb'] = max(
                            self.metadata.get('peak_memory_mb', 0),
                            memory_usage.get('rss_mb', 0)
                        )

                        # Convert DataFrame to dict records
                        for record in chunk_df.to_dict('records'):
                            self.statistics['total_rows'] += 1
                            yield record

                    return

                except (ImportError, Exception) as e:
                    # Fallback to csv module
                    self._log_decision('PARSER_FALLBACK', 'csv_module', f'Pandas/pyarrow unavailable: {str(e)}')
                    f.seek(0)

                # Fallback to csv module processing
                reader = csv.reader(f, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)

                # Process first few lines for header detection and schema analysis
                first_lines = []
                line_count = 0
                sample_data = []

                for line in reader:
                    if line:  # Skip empty lines
                        first_lines.append(line)
                        sample_data.append(line)
                        line_count += 1
                        if line_count >= 20:  # Increased sample size for better schema inference
                            break

                if not first_lines:
                    self._log_decision('PARSE_ERROR', 'empty_file', 'No data found in file')
                    return

                # Advanced header detection if not provided
                if has_header is None:
                    sample_lines = [delimiter.join(row) for row in sample_data[:10]]
                    has_header, confidence = self._detect_header_advanced(sample_lines, delimiter, sample_data)
                    self.metadata['header_detection_confidence'] = confidence

                # Set up column headers with intelligent naming
                if has_header and first_lines:
                    headers = [str(h).strip() for h in first_lines[0]]
                    data_start_idx = 1
                    self._log_decision('HEADERS', headers, 'Using detected headers from file')
                else:
                    headers = self._analyze_column_content(sample_data)
                    data_start_idx = 0
                    self._log_decision('HEADERS', headers, 'Generated intelligent headers based on content analysis')

                self.metadata['headers'] = headers

                # Perform comprehensive analysis
                data_sample = []
                for i in range(data_start_idx, min(len(sample_data), data_start_idx + 100)):
                    if len(sample_data[i]) == len(headers):
                        data_sample.append(dict(zip(headers, sample_data[i])))

                # Generate comprehensive analysis
                self.metadata['type_analysis'] = self._comprehensive_data_type_inference(sample_data[data_start_idx:])
                self.metadata['schema_validation'] = self._validate_schema_consistency(sample_data[data_start_idx:], file_size)
                self.metadata['data_profile'] = self._generate_data_profile(data_sample)

                # Quality validation
                if len(data_sample) >= 10:
                    quality_results = self._detect_outliers_and_anomalies(data_sample)
                    self.metadata['quality_analysis'] = quality_results

                # Reset file for full processing
                f.seek(0)
                reader = csv.reader(f, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)

                # Skip processed lines
                for _ in range(len(first_lines)):
                    try:
                        next(reader)
                    except StopIteration:
                        break

                # Yield data from buffered first lines
                error_count = 0
                malformed_records = []

                for line in first_lines[data_start_idx:]:
                    try:
                        record = self._process_record(line, headers, recovery_strategy, malformed_records)
                        if record:
                            self.statistics['total_rows'] += 1
                            yield record

                    except Exception as e:
                        error_count += 1
                        self.statistics['error_count'] = error_count
                        self._handle_error(e, error_count, max_errors, recovery_strategy)

                # Process remaining file in chunks for memory efficiency
                chunk_buffer = []

                for row in reader:
                    try:
                        if not row:  # Skip empty rows
                            continue

                        chunk_buffer.append(row)

                        # Process chunk when buffer is full
                        if len(chunk_buffer) >= chunk_size:
                            yield from self._process_chunk(chunk_buffer, headers, recovery_strategy, malformed_records)

                            # Monitor memory usage
                            memory_usage = self._get_memory_usage()
                            self.metadata['peak_memory_mb'] = max(
                                self.metadata.get('peak_memory_mb', 0),
                                memory_usage.get('rss_mb', 0)
                            )

                            chunk_buffer = []

                    except csv.Error as e:
                        error_count += 1
                        self.statistics['error_count'] = error_count
                        self._handle_error(e, error_count, max_errors, recovery_strategy)
                    except Exception as e:
                        error_count += 1
                        self.statistics['error_count'] = error_count
                        self._handle_error(e, error_count, max_errors, recovery_strategy)

                # Process remaining records in buffer
                if chunk_buffer:
                    yield from self._process_chunk(chunk_buffer, headers, recovery_strategy, malformed_records)

                # Store malformed records for audit
                if malformed_records:
                    self.metadata['malformed_records'] = malformed_records[:100]  # Store first 100 for review

        except UnicodeDecodeError as e:
            error_msg = f"Encoding error with {encoding}: {e}"
            self._log_decision('FATAL_ERROR', 'encoding', error_msg)
            raise ValueError(error_msg)
        except Exception as e:
            error_msg = f"Failed to parse CSV: {e}"
            self._log_decision('FATAL_ERROR', 'parsing', error_msg)
            raise ValueError(error_msg)
        finally:
            # Finalize metadata
            self.metadata['processing_duration'] = time.time() - processing_start
            self.metadata['statistics'] = self.statistics

    def _process_record(self, row: List[str], headers: List[str], recovery_strategy: str, malformed_records: List) -> Optional[Dict[str, Any]]:
        """Process individual record with recovery strategy."""
        if len(row) == len(headers):
            return dict(zip(headers, row))

        self.statistics['field_consistency_issues'] += 1

        if recovery_strategy == 'fast_fail':
            # Fast fail mode: skip malformed rows
            return None
        elif recovery_strategy == 'skip':
            # Skip malformed records
            return None
        elif recovery_strategy == 'pad':
            # Pad or truncate to match header count
            if len(row) > len(headers):
                row = row[:len(headers)]
            else:
                row.extend([''] * (len(headers) - len(row)))

            self.statistics['transformation_count'] += 1
            self._log_decision('TRANSFORMATION', 'field_padding', f'Adjusted field count from {len(row)} to {len(headers)}')
            return dict(zip(headers, row))
        elif recovery_strategy == 'quarantine':
            # Store malformed record for review
            malformed_records.append({
                'row_data': row,
                'expected_fields': len(headers),
                'actual_fields': len(row),
                'row_number': self.statistics['total_rows']
            })
            return None

        return None

    def _process_chunk(self, chunk: List[List[str]], headers: List[str], recovery_strategy: str, malformed_records: List) -> Iterator[Dict[str, Any]]:
        """Process a chunk of records efficiently."""
        for row in chunk:
            record = self._process_record(row, headers, recovery_strategy, malformed_records)
            if record:
                self.statistics['total_rows'] += 1
                yield record

    def _handle_error(self, error: Exception, error_count: int, max_errors: int, recovery_strategy: str):
        """Handle parsing errors based on strategy."""
        if recovery_strategy == 'fast_fail' and error_count > max_errors:
            raise ValueError(f"Too many parsing errors (>{max_errors})")

        self._log_decision('ERROR_HANDLING', str(error), f'Error {error_count} handled with strategy: {recovery_strategy}')

    def generate_audit_report(self) -> Dict[str, Any]:
        """Generate comprehensive audit report for compliance."""
        report = {
            'metadata': self.metadata,
            'processing_log': self.processing_log,
            'statistics': self.statistics,
            'timestamp': time.time(),
            'parser_version': '1.0.0'
        }

        # Add success rates and quality metrics
        if self.statistics['total_rows'] > 0:
            report['success_rate'] = (
                (self.statistics['total_rows'] - self.statistics['error_count']) / 
                self.statistics['total_rows']
            )

        report['quality_score'] = self._calculate_quality_score()

        self._log_decision('AUDIT_REPORT', 'generated', 'Comprehensive audit report generated for compliance')
        return report

    def _calculate_quality_score(self) -> float:
        """Calculate overall data quality score."""
        factors = []

        # Error rate factor
        if self.statistics['total_rows'] > 0:
            error_rate = self.statistics['error_count'] / self.statistics['total_rows']
            error_score = max(0, 1.0 - error_rate)
            factors.append(error_score)

        # Field consistency factor
        if self.statistics['total_rows'] > 0:
            consistency_rate = 1.0 - (self.statistics['field_consistency_issues'] / self.statistics['total_rows'])
            factors.append(max(0, consistency_rate))

        # Schema validation factor
        schema_validation = self.metadata.get('schema_validation', {})
        if schema_validation.get('variance_issues'):
            factors.append(0.8)  # Reduced score for schema issues
        else:
            factors.append(1.0)

        return sum(factors) / len(factors) if factors else 0.0

def parse_messy_csv(file_path: str,
                   encoding: Optional[str] = None,
                   delimiter: Optional[str] = None, 
                   has_header: Optional[bool] = None,
                   performance_mode: bool = True,
                   max_errors: int = 100,
                   sample_size: int = 8192,
                   chunk_size: Optional[int] = None,
                   recovery_strategy: str = 'fast_fail',
                   enable_audit: bool = True) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Convenience function to parse messy CSV files with automatic parameter detection and audit trail.

    Args:
        file_path: Path to the CSV file
        encoding: File encoding (auto-detected if None)
        delimiter: Column delimiter (auto-detected if None)
        has_header: Whether file has header row (auto-detected if None)
        performance_mode: Prioritize speed over error recovery
        max_errors: Maximum parsing errors before failing
        sample_size: Bytes to sample for auto-detection
        chunk_size: Rows per chunk for memory optimization
        recovery_strategy: 'fast_fail', 'skip', 'pad', or 'quarantine'
        enable_audit: Generate comprehensive audit report

    Returns:
        Tuple of (parsed data, audit report)

    Example:
        >>> data, audit = parse_messy_csv('messy_data.csv', enable_audit=True)
        >>> print(f"Parsed {len(data)} rows with {audit['statistics']['error_count']} errors")
        >>> print(f"Quality score: {audit['quality_score']:.2f}")
    """
    parser = FastCSVParser(
        sample_size=sample_size,
        performance_mode=performance_mode,
        enable_logging=enable_audit
    )

    data = list(parser.parse_csv_fast(
        file_path=file_path,
        encoding=encoding,
        delimiter=delimiter,
        has_header=has_header,
        max_errors=max_errors,
        chunk_size=chunk_size,
        recovery_strategy=recovery_strategy
    ))

    audit_report = parser.generate_audit_report() if enable_audit else {}

    return data, audit_report

# Usage examples and performance optimization
if __name__ == "__main__":
    # Example 1: Basic usage with auto-detection and audit
    try:
        data, audit = parse_messy_csv('sample.csv', enable_audit=True)
        print(f"Successfully parsed {len(data)} rows")
        print(f"Quality score: {audit.get('quality_score', 0):.2f}")
        if data:
            print("Columns:", list(data[0].keys()))

        # Save audit report
        with open('parsing_audit.json', 'w') as f:
            json.dump(audit, f, indent=2, default=str)

    except Exception as e:
        print(f"Error: {e}")

    # Example 2: Advanced usage with streaming and memory monitoring
    parser = FastCSVParser(performance_mode=True, enable_logging=True)

    try:
        records = []
        for record in parser.parse_csv_fast(
            'large_file.csv',
            delimiter=';',
            has_header=True,
            max_errors=50,
            chunk_size=5000,
            recovery_strategy='pad'
        ):
            records.append(record)

            # Monitor progress for large files
            if len(records) % 10000 == 0:
                memory_info = parser._get_memory_usage()
                print(f"Processed {len(records)} records, Memory: {memory_info.get('rss_mb', 0):.1f}MB")

        print(f"Processed {len(records)} records")

        # Generate comprehensive audit report
        audit = parser.generate_audit_report()
        print(f"Parse quality score: {audit['quality_score']:.2f}")
        print(f"Processing time: {audit['metadata']['processing_duration']:.2f}s")