"""
Input validation and sanitization utilities for security
"""
import re
from typing import Optional
from bleach import clean


def sanitize_filename(filename: str) -> str:
    """
    Remove dangerous characters from filename to prevent directory traversal attacks
    
    Args:
        filename: Original filename
        
    Returns:
        Sanitized filename with dangerous characters replaced
        
    Examples:
        >>> sanitize_filename("../../etc/passwd")
        'etcpasswd'
        >>> sanitize_filename("file<script>.txt")
        'file_script_.txt'
    """
    if not filename:
        return "unnamed_file"
    
    # First, use os.path.basename to remove any directory path
    import os
    filename = os.path.basename(filename)
    
    # Remove path separators and dangerous characters
    # Replace: / \ : * ? " < > |
    sanitized = re.sub(r'[/\\:*?"<>|]', '_', filename)
    
    # Remove any sequences of dots to prevent traversal
    sanitized = re.sub(r'\.\.+', '_', sanitized)
    
    # Remove any leading dots to prevent hidden files
    sanitized = sanitized.lstrip('.')
    
    # Ensure the filename is not empty after sanitization
    if not sanitized:
        sanitized = "unnamed_file"
    
    # Limit filename length to 255 characters (filesystem limit)
    if len(sanitized) > 255:
        # Keep the extension using os.path.splitext for reliability
        import os
        name, ext = os.path.splitext(sanitized)
        max_name_length = 255 - len(ext)
        sanitized = name[:max_name_length] + ext
    
    return sanitized


def sanitize_html(text: str) -> str:
    """
    Remove/escape HTML tags to prevent XSS attacks
    
    Args:
        text: Input text that may contain HTML
        
    Returns:
        Sanitized text with HTML tags escaped
        
    Examples:
        >>> sanitize_html("<script>alert('xss')</script>Hello")
        '&lt;script&gt;alert('xss')&lt;/script&gt;Hello'
        >>> sanitize_html("Normal text")
        'Normal text'
    """
    if not text:
        return ""
    
    # Escape all HTML tags instead of stripping them
    # This prevents XSS while preserving the text content
    return clean(text, tags=[], strip=False)


def validate_file_extension(filename: str, allowed_extensions: set) -> bool:
    """
    Check if file extension is in the allowed list
    
    Args:
        filename: Name of the file
        allowed_extensions: Set of allowed extensions (lowercase, without dot)
        
    Returns:
        True if extension is allowed, False otherwise
        
    Examples:
        >>> validate_file_extension("document.pdf", {'pdf', 'doc'})
        True
        >>> validate_file_extension("script.exe", {'pdf', 'doc'})
        False
    """
    if not filename:
        return False
    
    # Get file extension (lowercase)
    file_ext = filename.split('.')[-1].lower() if '.' in filename else ''
    
    return file_ext in allowed_extensions


def get_safe_file_extension(filename: str) -> str:
    """
    Extract file extension safely
    
    Args:
        filename: Name of the file
        
    Returns:
        File extension in lowercase without the dot
        
    Examples:
        >>> get_safe_file_extension("document.PDF")
        'pdf'
        >>> get_safe_file_extension("archive.tar.gz")
        'gz'
    """
    if not filename:
        return ''
    
    import os
    _, ext = os.path.splitext(filename)
    # Remove leading dot and convert to lowercase
    return ext.lstrip('.').lower()


# Allowed file extensions for document uploads
ALLOWED_DOCUMENT_EXTENSIONS = {
    'pdf',      # Adobe PDF
    'doc',      # Microsoft Word (legacy)
    'docx',     # Microsoft Word
    'xls',      # Microsoft Excel (legacy)
    'xlsx',     # Microsoft Excel
    'jpg',      # JPEG images
    'jpeg',     # JPEG images
    'png',      # PNG images
    'gif',      # GIF images
    'txt',      # Plain text
    'csv',      # CSV data
}
