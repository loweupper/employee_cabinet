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
        '......etcpasswd'
        >>> sanitize_filename("file<script>.txt")
        'filescript.txt'
    """
    if not filename:
        return "unnamed_file"
    
    # Remove path separators and dangerous characters
    # Replace: / \ : * ? " < > |
    sanitized = re.sub(r'[/\\:*?"<>|]', '_', filename)
    
    # Remove any leading dots to prevent hidden files
    sanitized = sanitized.lstrip('.')
    
    # Ensure the filename is not empty after sanitization
    if not sanitized:
        sanitized = "unnamed_file"
    
    # Limit filename length to 255 characters (filesystem limit)
    if len(sanitized) > 255:
        # Keep the extension
        name, ext = sanitized.rsplit('.', 1) if '.' in sanitized else (sanitized, '')
        max_name_length = 255 - len(ext) - 1 if ext else 255
        sanitized = name[:max_name_length] + ('.' + ext if ext else '')
    
    return sanitized


def sanitize_html(text: str) -> str:
    """
    Remove HTML/script tags to prevent XSS attacks
    
    Args:
        text: Input text that may contain HTML
        
    Returns:
        Sanitized text with all HTML tags removed
        
    Examples:
        >>> sanitize_html("<script>alert('xss')</script>Hello")
        'Hello'
        >>> sanitize_html("Normal text")
        'Normal text'
    """
    if not text:
        return ""
    
    # Remove all HTML tags and strip whitespace
    return clean(text, tags=[], strip=True)


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
    if not filename or '.' not in filename:
        return ''
    
    return filename.split('.')[-1].lower()


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
