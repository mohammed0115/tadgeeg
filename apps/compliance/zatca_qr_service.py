"""
ZATCA Phase 2 QR Code Generation Service
=========================================
Implements ZATCA Technical Specification v2.0 for e-invoicing.
Generates TLV-encoded QR codes for invoice validation and submission.

Reference:
  - ZATCA Phase 2 Technical Specification v2.0
  - TLV Tag-Length-Value encoding format
"""

import base64
import hashlib
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from decimal import Decimal

import qrcode
from qrcode.image.pure import PyPNGImage

logger = logging.getLogger("finai.zatca")


class ZATCAQRService:
    """
    ZATCA Phase 2 QR Code generation service.
    
    Encodes invoice details in TLV (Tag-Length-Value) format per ZATCA spec.
    Tags used:
      0x01: Seller VAT ID
      0x02: Timestamp (ISO 8601)
      0x03: Invoice Total Amount
      0x04: VAT Total Amount
      0x05: Invoice Hash (SHA256 of last signed QR)
    """
    
    # QR Code generation parameters
    QR_VERSION = 13  # Version 13 supports up to 2953 bytes
    QR_ERROR_CORRECTION = qrcode.constants.ERROR_CORRECT_L  # Low error correction
    QR_BOX_SIZE = 10
    
    # TLV Tag definitions per ZATCA spec
    TAG_SELLER_VAT = 0x01
    TAG_TIMESTAMP = 0x02
    TAG_INVOICE_TOTAL = 0x03
    TAG_VAT_TOTAL = 0x04
    TAG_INVOICE_HASH = 0x05
    
    def generate_qr_code(
        self,
        invoice: Any,
        previous_invoice_hash: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate ZATCA Phase 2 QR code for an invoice.
        
        Args:
            invoice: Invoice model instance with required fields
            previous_invoice_hash: Hash of previous invoice (for chaining, optional)
        
        Returns:
            {
                'qr_code': PIL Image object,
                'qr_base64': str,              # Base64 encoded QR for storage
                'tlv_data': str,               # Base64 encoded TLV data
                'hash': str,                   # SHA256 hash of QR content
                'status': 'success' or 'error',
                'message': str
            }
        """
        
        try:
            # Validate required fields
            validation = self._validate_invoice_data(invoice)
            if not validation['valid']:
                return {
                    'qr_code': None,
                    'qr_base64': None,
                    'tlv_data': None,
                    'hash': None,
                    'status': 'error',
                    'message': validation['message']
                }
            
            # Build TLV array
            tlv_array = self._build_tlv_array(
                invoice,
                previous_invoice_hash
            )
            
            # Encode TLV to binary
            tlv_binary = self._encode_tlv(tlv_array)
            
            # Base64 encode for QR content
            tlv_base64 = base64.b64encode(tlv_binary).decode('utf-8')
            
            # Calculate hash of QR content (SHA256)
            qr_hash = hashlib.sha256(tlv_binary).hexdigest()
            
            # Generate QR code
            try:
                qr = qrcode.QRCode(
                    version=self.QR_VERSION,
                    error_correction=self.QR_ERROR_CORRECTION,
                    box_size=self.QR_BOX_SIZE,
                )
                qr.add_data(tlv_base64)
                qr.make(fit=True)
                
                # Generate image
                qr_image = qr.make_image(fill_color="black", back_color="white")
                
                logger.info(
                    f"QR code generated successfully for invoice {invoice.invoice_number}"
                )
                
                return {
                    'qr_code': qr_image,
                    'qr_base64': self._image_to_base64(qr_image),
                    'tlv_data': tlv_base64,
                    'hash': qr_hash,
                    'status': 'success',
                    'message': 'QR code generated successfully'
                }
            
            except Exception as e:
                logger.error(f"QR code generation failed: {str(e)}")
                return {
                    'qr_code': None,
                    'qr_base64': None,
                    'tlv_data': tlv_base64,
                    'hash': qr_hash,
                    'status': 'error',
                    'message': f'QR visualization failed: {str(e)}'
                }
        
        except Exception as e:
            logger.exception(f"ZATCA QR generation error: {str(e)}")
            return {
                'qr_code': None,
                'qr_base64': None,
                'tlv_data': None,
                'hash': None,
                'status': 'error',
                'message': f'Fatal error: {str(e)}'
            }
    
    def _validate_invoice_data(self, invoice: Any) -> Dict[str, Any]:
        """Validate that invoice has all required fields for QR generation."""
        
        required_fields = {
            'vendor_vat_number': 'Seller VAT number',
            'invoice_date': 'Invoice date/timestamp',
            'total_amount': 'Invoice total amount',
            'vat_amount': 'VAT total amount',
        }
        
        for field, label in required_fields.items():
            if not hasattr(invoice, field):
                return {
                    'valid': False,
                    'message': f'Missing required field: {label} ({field})'
                }
            
            value = getattr(invoice, field)
            if value is None or value == '':
                return {
                    'valid': False,
                    'message': f'Required field is empty: {label}'
                }
        
        # Additional validation: VAT number format (Saudi = 15 digits)
        vat_num = str(invoice.vendor_vat_number).strip()
        if len(vat_num) != 15 or not vat_num.isdigit():
            logger.warning(
                f"VAT number format unusual: {vat_num} (expected 15 digits)"
            )
        
        return {'valid': True, 'message': 'Validation passed'}
    
    def _build_tlv_array(
        self,
        invoice: Any,
        previous_invoice_hash: Optional[str] = None
    ) -> list:
        """
        Build TLV (Tag-Length-Value) array per ZATCA specification.
        
        Returns:
            List of (tag, data_bytes) tuples
        """
        
        tlv_array = []
        
        # Tag 0x01: Seller VAT ID (15 digits for Saudi Arabia)
        vat_id = str(invoice.vendor_vat_number).strip()
        tlv_array.append((
            self.TAG_SELLER_VAT,
            vat_id.encode('utf-8')
        ))
        
        # Tag 0x02: Timestamp (ISO 8601 format)
        # Use invoice_date or created_at
        timestamp = invoice.invoice_date or invoice.created_at
        if hasattr(timestamp, 'isoformat'):
            timestamp_str = timestamp.isoformat()
        else:
            timestamp_str = str(timestamp)
        tlv_array.append((
            self.TAG_TIMESTAMP,
            timestamp_str.encode('utf-8')
        ))
        
        # Tag 0x03: Invoice Total Amount
        total = Decimal(str(invoice.total_amount))
        total_str = f"{total:.2f}"
        tlv_array.append((
            self.TAG_INVOICE_TOTAL,
            total_str.encode('utf-8')
        ))
        
        # Tag 0x04: VAT Total Amount
        vat = Decimal(str(invoice.vat_amount))
        vat_str = f"{vat:.2f}"
        tlv_array.append((
            self.TAG_VAT_TOTAL,
            vat_str.encode('utf-8')
        ))
        
        # Tag 0x05: Invoice Hash
        # Use file hash from extracted_data or computed hash
        if hasattr(invoice, 'extracted_data') and isinstance(invoice.extracted_data, dict):
            file_hash = invoice.extracted_data.get('file_hash', '')
        else:
            file_hash = previous_invoice_hash or ''
        
        if not file_hash:
            # Compute hash from invoice contents as fallback
            invoice_content = f"{vat_id}{timestamp_str}{total_str}{vat_str}"
            file_hash = hashlib.sha256(invoice_content.encode()).hexdigest()
        
        tlv_array.append((
            self.TAG_INVOICE_HASH,
            file_hash.encode('utf-8')
        ))
        
        return tlv_array
    
    def _encode_tlv(self, tlv_array: list) -> bytes:
        """
        Encode TLV array to binary format per ZATCA spec.
        Binary format: [TAG][LENGTH][VALUE]...
        
        - TAG: 1 byte
        - LENGTH: 1 byte (data length)
        - VALUE: variable length bytes
        """
        
        encoded = bytearray()
        
        for tag, data in tlv_array:
            if isinstance(data, str):
                data = data.encode('utf-8')
            
            data_len = len(data)
            
            # Ensure length fits in 1 byte (max 255)
            if data_len > 255:
                logger.warning(
                    f"TLV tag {hex(tag)}: data length {data_len} exceeds 255, truncating"
                )
                data = data[:255]
                data_len = 255
            
            # Append: TAG + LENGTH + DATA
            encoded.append(tag)
            encoded.append(data_len)
            encoded.extend(data)
        
        return bytes(encoded)
    
    def _image_to_base64(self, image) -> str:
        """Convert PIL Image to base64 PNG string."""
        try:
            import io
            
            img_bytes = io.BytesIO()
            image.save(img_bytes, format='PNG')
            img_bytes.seek(0)
            
            base64_str = base64.b64encode(img_bytes.getvalue()).decode('utf-8')
            return f"data:image/png;base64,{base64_str}"
        
        except Exception as e:
            logger.error(f"Failed to convert image to base64: {str(e)}")
            return ""


def generate_invoice_qr(
    invoice,
    previous_invoice_hash: Optional[str] = None
) -> Dict[str, Any]:
    """
    Convenience function to generate QR code for an invoice.
    
    Usage:
        from apps.compliance.zatca_qr_service import generate_invoice_qr
        
        result = generate_invoice_qr(invoice_obj)
        if result['status'] == 'success':
            invoice.qr_code_image = result['qr_base64']
            invoice.save()
    """
    service = ZATCAQRService()
    return service.generate_qr_code(invoice, previous_invoice_hash)
