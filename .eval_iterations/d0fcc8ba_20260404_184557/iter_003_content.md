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

    def _validate_parameters(self, file_path: str, max_errors: int, chunk_size: Optional[int], 
                           recovery_strategy: str, encoding: Optional[str], delimiter: Optional[str]):
        """Comprehensive input validation for all parameters."""
        # File path validation
        if not isinstance(file_path, str):
            raise TypeError("file_path must be a string")
        if not file_path.strip():
            raise ValueError("file_path cannot be empty")
            
        # Max errors validation
        if not isinstance(max_errors, int):
            raise TypeError("max_errors must be an integer")
        if max_errors < 0:
            raise ValueError("max_errors must be non-negative")
        if max_errors > 10000:
            warnings.warn("max_errors > 10000 may cause excessive memory usage", UserWarning)
            
        # Chunk size validation
        if chunk_size is not None:
            if not isinstance(chunk_size, int):
                raise TypeError("chunk_size must be an integer or None")
            if chunk_size <= 0:
                raise ValueError("chunk_size must be positive")
            if chunk_size > 1000000:
                warnings.warn("chunk_size > 1M may cause memory issues", UserWarning)
                
        # Recovery strategy validation
        valid_strategies = {'fast_fail', 'skip', 'pad', 'quarantine'}
        if recovery_strategy not in valid_strategies:
            raise ValueError(f"recovery_strategy must be one of {valid_strategies}")
            
        # Encoding validation
        if encoding is not None and not isinstance(encoding, str):
            raise TypeError("encoding must be a string or None")
            
        # Delimiter validation
        if delimiter is not None:
            if not isinstance(delimiter, str):
                raise TypeError("delimiter must be a string or None")
            if len(delimiter) == 0:
                raise ValueError("delimiter cannot be empty string")
        
        self._log_decision('PARAMETER_VALIDATION', 'success', 'All parameters validated successfully')

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

            if confidence > 0.85 and detected_encoding:  # Increased confidence threshold for better accuracy
                self._log_decision('ENCODING_DETECTION', detected_encoding, f'Chardet detection with {confidence:.2f} confidence')
                return detected_encoding

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
        """Statistical outlier detection and anomaly detection using IQR and z-score methods."""
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
                        import statistics
                        mean_val = statistics.mean(values)
                        stdev_val = statistics.stdev(values) if len(values) > 1 else 0
                        
                        if stdev_val > 0:
                            z_scores = [(v - mean_val) / stdev_val for v in col_outliers]
                            extreme_outliers = [v for v, z in zip(col_outliers, z_scores) if abs(z) > 3]
                        else:
                            extreme_outliers = []

                        outliers[col] = {
                            'count': len(col_outliers),
                            'percentage': len(col_outliers) / len(values) * 100,
                            'bounds': [lower_bound, upper_bound],
                            'extreme_count': len(extreme_outliers),
                            'method': 'IQR',
                            'multiplier': iqr_multiplier,
                            'sample_outliers': col_outliers[:5]  # First 5 outliers for review
                        }

        # Enhanced pattern consistency validation with configurable thresholds
        pattern_consistency = {}
        consistency_threshold = 0.95  # 95% consistency threshold
        
        for col in data_rows[0].keys():
            values = [row[col] for row in data_rows[:min(200, len(data_rows))] if row.get(col)]

            if len(values) < 5:
                continue

            # Enhanced pattern checks
            pattern_checks = {
                'email': {
                    'pattern': re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'),
                    'description': 'email format'
                },
                'phone': {
                    'pattern': re.compile(r'^(\+\d{1,3}[-.\s]?)?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}$'),
                    'description': 'phone number format'
                },
                'date_iso': {
                    'pattern': re.compile(r'^\d{4}-\d{2}-\d{2}$'),
                    'description': 'ISO date format (YYYY-MM-DD)'
                },
                'url': {
                    'pattern': re.compile(r'^https?://[^\s]+$'),
                    'description': 'URL format'
                },
                'numeric': {
                    'pattern': re.compile(r'^-?\d*\.?\d+$'),
                    'description': 'numeric format'
                }
            }

            for pattern_name, pattern_info in pattern_checks.items():
                if pattern_name.lower() in col.lower() or any(keyword in col.lower() for keyword in pattern_name.split('_')):
                    valid_count = sum(1 for val in values if pattern_info['pattern'].match(str(val).strip()))
                    consistency_rate = valid_count / len(values) if values else 0
                    
                    if consistency_rate < consistency_threshold:  # Only report if below threshold
                        invalid_samples = [val for val in values[:10] if not pattern_info['pattern'].match(str(val).strip())]
                        
                        pattern_consistency[col] = {
                            'expected_pattern': pattern_info['description'],
                            'consistency_rate': consistency_rate,
                            'valid_count': valid_count,
                            'total_count': len(values),
                            'threshold': consistency_threshold,
                            'invalid_samples': invalid_samples[:3]  # First 3 invalid samples
                        }

        # Anomaly detection for categorical data
        categorical_anomalies = {}
        for col in data_rows[0].keys():
            values = [str(row[col]).strip() for row in data_rows[:min(500, len(data_rows))] if row.get(col)]
            
            if len(values) >= 20:  # Only analyze columns with sufficient data
                value_counts = Counter(values)
                total_values = len(values)
                
                # Detect very rare values (potential anomalies)
                rare_threshold = max(1, total_values * 0.01)  # 1% threshold, minimum 1
                rare_values = {val: count for val, count in value_counts.items() if count <= rare_threshold}
                
                if rare_values and len(rare_values) / len(value_counts) > 0.1:  # More than 10% are rare values
                    categorical_anomalies[col] = {
                        'rare_values_count': len(rare_values),
                        'rare_percentage': len(rare_values) / len(value_counts) * 100,
                        'total_unique_values': len(value_counts),
                        'rare_threshold': rare_threshold,
                        'sample_rare_values': list(rare_values.items())[:5]
                    }

        results = {
            'outliers': outliers,
            'anomalies': anomalies,
            'pattern_consistency': pattern_consistency,
            'categorical_anomalies': categorical_anomalies,
            'outlier_detection_method': 'IQR with z-score validation',
            'consistency_threshold': consistency_threshold,
            'total_columns_analyzed': len(data_rows[0].keys()) if data_rows else 0,
            'status': 'analyzed'
        }

        self._log_decision('QUALITY_VALIDATION', results, 'Enhanced statistical quality validation with IQR and z-score analysis completed')
        return results

    def _validate_data_consistency(self, data_rows: List[Dict[str, Any]]) -> Dict:
        """Validate patterns across records with configurable consistency thresholds."""
        if len(data_rows) < 10:
            return {'status': 'insufficient_data', 'consistency_rate': 0.0}

        consistency_results = {}
        overall_consistency_issues = 0
        total_validations = 0

        # Define pattern validators with thresholds
        pattern_validators = {
            'email': {
                'pattern': re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'),
                'threshold': 0.95,
                'keywords': ['email', 'e-mail', 'mail']
            },
            'phone': {
                'pattern': re.compile(r'^(\+\d{1,3}[-.\s]?)?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}$'),
                'threshold': 0.90,
                'keywords': ['phone', 'tel', 'mobile', 'number']
            },
            'url': {
                'pattern': re.compile(r'^https?://[^\s]+$'),
                'threshold': 0.95,
                'keywords': ['url', 'link', 'website', 'site']
            },
            'date_iso': {
                'pattern': re.compile(r'^\d{4}-\d{2}-\d{2}$'),
                'threshold': 0.90,
                'keywords': ['date', 'created', 'updated', 'time']
            },
            'numeric_id': {
                'pattern': re.compile(r'^\d+$'),
                'threshold': 0.98,
                'keywords': ['id', 'number', 'count', 'quantity']
            }
        }

        # Check pattern consistency for each column
        for col_name in data_rows[0].keys():
            col_values = [str(row.get(col_name, '')).strip() for row in data_rows[:min(200, len(data_rows))] 
                         if row.get(col_name) and str(row.get(col_name)).strip()]
            
            if len(col_values) < 10:
                continue

            # Determine if this column should follow a specific pattern
            col_lower = col_name.lower()
            for pattern_name, validator in pattern_validators.items():
                if any(keyword in col_lower for keyword in validator['keywords']):
                    valid_count = sum(1 for val in col_values if validator['pattern'].match(val))
                    consistency_rate = valid_count / len(col_values)
                    total_validations += 1

                    if consistency_rate < validator['threshold']:
                        overall_consistency_issues += 1
                        invalid_samples = [val for val in col_values[:20] 
                                         if not validator['pattern'].match(val)][:5]
                        
                        consistency_results[col_name] = {
                            'pattern_type': pattern_name,
                            'expected_threshold': validator['threshold'],
                            'actual_consistency_rate': consistency_rate,
                            'valid_count': valid_count,
                            'total_count': len(col_values),
                            'passed': False,
                            'invalid_samples': invalid_samples
                        }
                    else:
                        consistency_results[col_name] = {
                            'pattern_type': pattern_name,
                            'expected_threshold': validator['threshold'],
                            'actual_consistency_rate': consistency_rate,
                            'valid_count': valid_count,
                            'total_count': len(col_values),
                            'passed': True
                        }
                    break

        # Calculate overall consistency rate
        if total_validations > 0:
            overall_consistency_rate = 1.0 - (overall_consistency_issues / total_validations)
        else:
            overall_consistency_rate = 1.0  # No validations means no issues

        # Additional cross-field consistency checks
        cross_field_issues = []
        
        # Check for duplicate rows
        row_strings = [str(sorted(row.items())) for row in data_rows[:100]]
        duplicate_count = len(row_strings) - len(set(row_strings))
        if duplicate_count > 0:
            cross_field_issues.append(f'Found {duplicate_count} duplicate rows in sample')

        # Check for inconsistent field counts
        field_counts = [len(row) for row in data_rows[:100]]
        if len(set(field_counts)) > 1:
            cross_field_issues.append(f'Inconsistent field counts: {set(field_counts)}')

        results = {
            'column_consistency': consistency_results,
            'overall_consistency_rate': overall_consistency_rate,
            'total_validations_performed': total_validations,
            'consistency_issues_found': overall_consistency_issues,
            'cross_field_issues': cross_field_issues,
            'meets_95_percent_threshold': overall_consistency_rate >= 0.95,
            'status': 'completed'
        }

        self._log_decision('CONSISTENCY_VALIDATION', results, 
                         f'Pattern consistency validation completed with {overall_consistency_rate:.1%} overall rate')
        return results

    def _generate_data_profile(self, data_rows: List[Dict[str, Any]]) -> Dict:
        """Generate comprehensive data profiling statistics with distributions and quality metrics."""
        if not data_rows:
            return {'status': 'no_data'}

        profile = {
            'total_rows': len(data_rows),
            'columns': {},
            'overall_quality_score': 0.0
        }

        column_quality_scores = []

        # Analyze each column comprehensively
        for col in data_rows[0].keys():
            values = [row.get(col, '') for row in data_rows]
            non_empty_values = [v for v in values if v and str(v).strip()]

            col_profile = {
                'total_values': len(values),
                'non_empty_count': len(non_empty_values),
                'null_count': len(values) - len(non_empty_values),
                'null_percentage': (len(values) -