"""
Benford's Law Fraud Detection Service
======================================
Statistical analysis of invoice amounts to detect anomalies
using Benford's Law chi-square goodness-of-fit test.

Reference: ISA 315 Risk Assessment - Analytical Procedures
"""

from typing import List, Dict, Optional
import numpy as np
from scipy import stats
from decimal import Decimal
import logging

logger = logging.getLogger("finai.benford")


class BenfordAnalyzer:
    """
    Statistical fraud detection using Benford's Law.
    
    Benford's Law states that in naturally occurring datasets,
    the first digit distribution follows a predictable pattern:
    - 1 appears ~30.1% of the time
    - 2 appears ~17.6% of the time
    ... and so on.
    
    Deviation from this pattern can indicate manipulation or fraud.
    """
    
    # Benford's Law expected first digit distribution
    BENFORD_DISTRIBUTION = {
        1: 0.30103,  # log10(2) - log10(1)
        2: 0.17609,  # log10(3) - log10(2)
        3: 0.12494,  # log10(4) - log10(3)
        4: 0.09691,
        5: 0.07918,
        6: 0.06695,
        7: 0.05799,
        8: 0.05115,
        9: 0.04576,
    }
    
    MIN_SAMPLE_SIZE = 30  # Chi-square test requires minimum samples
    SIGNIFICANCE_LEVEL = 0.05  # 5% significance level (p-value threshold)
    
    def analyze_invoices(
        self, 
        invoices,
        amount_field: str = "total_amount"
    ) -> Dict:
        """
        Analyze a batch of invoices for Benford's Law deviation.
        
        Args:
            invoices: List of Invoice model instances
            amount_field: Field name containing the amount to analyze
        
        Returns:
            {
                'chi_squared': float,           # Chi-square test statistic
                'p_value': float,               # Statistical significance
                'benford_deviation': str,       # 'significant' | 'normal' | 'insufficient_data'
                'confidence': float,            # 1 - p_value (confidence in anomaly)
                'sample_size': int,             # Number of invoices analyzed
                'first_digits': Dict,           # Distribution of first digits observed
                'status': str                   # 'red_flag' | 'warning' | 'normal'
            }
        """
        
        # Extract positive amounts
        amounts = []
        for invoice in invoices:
            try:
                amount = getattr(invoice, amount_field, None)
                if amount and float(amount) > 0:
                    amounts.append(float(amount))
            except (ValueError, TypeError, AttributeError):
                continue
        
        # Need minimum sample size for chi-square test
        if len(amounts) < self.MIN_SAMPLE_SIZE:
            logger.warning(
                f"Insufficient data for Benford's Law analysis: {len(amounts)} < {self.MIN_SAMPLE_SIZE}"
            )
            return {
                'chi_squared': None,
                'p_value': None,
                'benford_deviation': 'insufficient_data',
                'confidence': 0.0,
                'sample_size': len(amounts),
                'first_digits': {},
                'status': 'normal',
                'message': f'Need {self.MIN_SAMPLE_SIZE}+ invoices, got {len(amounts)}'
            }
        
        # Extract first digits
        first_digits = []
        for amount in amounts:
            # Convert to string, remove decimal point, get first digit
            amount_str = str(int(abs(amount)))
            if amount_str and amount_str[0].isdigit():
                first_digits.append(int(amount_str[0]))
        
        if not first_digits:
            return {
                'chi_squared': None,
                'p_value': None,
                'benford_deviation': 'insufficient_data',
                'confidence': 0.0,
                'sample_size': 0,
                'first_digits': {},
                'status': 'normal',
                'message': 'No valid amounts found'
            }
        
        # Calculate observed frequency distribution
        observed_counts = np.bincount(first_digits, minlength=10)[1:]  # Exclude 0
        observed_freq = observed_counts / len(first_digits)
        
        # Expected Benford distribution
        expected_freq = np.array(
            [self.BENFORD_DISTRIBUTION[i] for i in range(1, 10)]
        )
        
        # Chi-square goodness-of-fit test
        # Note: We multiply by sample size because chisquare expects observed frequencies
        expected_counts = expected_freq * len(first_digits)
        
        try:
            chi2_stat, p_value = stats.chisquare(
                f_obs=observed_counts,
                f_exp=expected_counts
            )
        except Exception as e:
            logger.error(f"Chi-square test failed: {str(e)}")
            return {
                'chi_squared': None,
                'p_value': None,
                'benford_deviation': 'error',
                'confidence': 0.0,
                'sample_size': len(first_digits),
                'first_digits': {},
                'status': 'error',
                'message': f'Analysis error: {str(e)}'
            }
        
        # Determine deviation status
        is_significant = p_value < self.SIGNIFICANCE_LEVEL
        deviation_status = 'significant' if is_significant else 'normal'
        
        # Risk flagging
        if is_significant and chi2_stat > 20:
            risk_status = 'red_flag'  # High likelihood of manipulation
        elif is_significant:
            risk_status = 'warning'   # Moderate deviation, review recommended
        else:
            risk_status = 'normal'    # Passes Benford's test
        
        # Build output with observed digit distribution
        first_digit_dist = {}
        for digit in range(1, 10):
            idx = digit - 1
            first_digit_dist[str(digit)] = {
                'observed': round(float(observed_freq[idx]), 4),
                'expected': round(self.BENFORD_DISTRIBUTION[digit], 4),
                'count': int(observed_counts[idx])
            }
        
        result = {
            'chi_squared': float(chi2_stat),
            'p_value': float(p_value),
            'benford_deviation': deviation_status,
            'confidence': 1 - p_value,
            'sample_size': len(first_digits),
            'first_digits': first_digit_dist,
            'status': risk_status,
        }
        
        if is_significant:
            result['recommendation'] = (
                'Manual review recommended' if risk_status == 'warning'
                else 'Potential fraud detected - escalate to senior auditor'
            )
        
        return result
    
    def analyze_single_amount(self, amount: Decimal) -> Dict:
        """
        Analyze a single amount value's first digit against Benford's expectation.
        Less statistically valid than batch analysis, but useful for single-item review.
        """
        try:
            amount_int = int(abs(float(amount)))
            first_digit = int(str(amount_int)[0])
            
            expected_prob = self.BENFORD_DISTRIBUTION.get(first_digit, 0)
            
            return {
                'first_digit': first_digit,
                'expected_probability': round(expected_prob, 4),
                'note': 'Single-item analysis - not statistically significant'
            }
        except (ValueError, TypeError, IndexError):
            return {
                'error': 'Invalid amount for first digit extraction'
            }
