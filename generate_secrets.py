#!/usr/bin/env python3
"""
Generate secure secrets for Employee Cabinet application.

Usage:
    python generate_secrets.py --type secret_key
    python generate_secrets.py --type password
    python generate_secrets.py --type all
"""

import secrets
import string
import argparse
import sys


def generate_secret_key(length: int = 64) -> str:
    """
    Generate a cryptographically secure SECRET_KEY.
    
    Args:
        length: Length of the key (minimum 32, recommended 64)
    
    Returns:
        A secure random string suitable for SECRET_KEY
    """
    if length < 32:
        raise ValueError("SECRET_KEY length must be at least 32 characters")
    
    # Use URL-safe base64 alphabet for compatibility
    alphabet = string.ascii_letters + string.digits + '-_'
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def generate_password(length: int = 32, include_special: bool = True) -> str:
    """
    Generate a strong random password.
    
    Args:
        length: Length of the password (minimum 16, recommended 32)
        include_special: Include special characters
    
    Returns:
        A strong random password
    """
    if length < 16:
        raise ValueError("Password length must be at least 16 characters")
    
    # Build character set
    alphabet = string.ascii_letters + string.digits
    if include_special:
        # Use a safe subset of special characters
        alphabet += '!@#$%^&*()_+-=[]{}|;:,.<>?'
    
    # Ensure at least one of each type
    password = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
    ]
    
    if include_special:
        password.append(secrets.choice('!@#$%^&*()_+-=[]{}|;:,.<>?'))
    
    # Fill the rest randomly
    password.extend(secrets.choice(alphabet) for _ in range(length - len(password)))
    
    # Shuffle to avoid predictable patterns
    password_list = list(password)
    for i in range(len(password_list) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        password_list[i], password_list[j] = password_list[j], password_list[i]
    
    return ''.join(password_list)


def main():
    parser = argparse.ArgumentParser(
        description='Generate secure secrets for Employee Cabinet',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Generate a SECRET_KEY:
    python generate_secrets.py --type secret_key

  Generate a password for SWAGGER_PASSWORD:
    python generate_secrets.py --type password

  Generate all secrets at once:
    python generate_secrets.py --type all

  Generate with custom length:
    python generate_secrets.py --type secret_key --length 128
    python generate_secrets.py --type password --length 48
        """
    )
    
    parser.add_argument(
        '--type',
        choices=['secret_key', 'password', 'all'],
        required=True,
        help='Type of secret to generate'
    )
    
    parser.add_argument(
        '--length',
        type=int,
        help='Length of the secret (default: 64 for secret_key, 32 for password)'
    )
    
    parser.add_argument(
        '--no-special',
        action='store_true',
        help='Exclude special characters from passwords'
    )
    
    args = parser.parse_args()
    
    try:
        if args.type == 'secret_key':
            length = args.length or 64
            key = generate_secret_key(length)
            print("\n" + "="*70)
            print("SECRET_KEY (copy this to your .env file):")
            print("="*70)
            print(key)
            print("="*70)
            print(f"Length: {len(key)} characters")
            print("\nAdd to your .env file:")
            print(f"SECRET_KEY={key}")
            print()
        
        elif args.type == 'password':
            length = args.length or 32
            pwd = generate_password(length, not args.no_special)
            print("\n" + "="*70)
            print("Generated Password (copy this to your .env file):")
            print("="*70)
            print(pwd)
            print("="*70)
            print(f"Length: {len(pwd)} characters")
            print("\nExample usage in .env:")
            print(f"SWAGGER_PASSWORD={pwd}")
            print(f"POSTGRES_PASSWORD={pwd}")
            print()
        
        elif args.type == 'all':
            print("\n" + "="*70)
            print("GENERATED SECRETS - Copy these to your .env file")
            print("="*70)
            
            secret_key = generate_secret_key(64)
            swagger_pwd = generate_password(32, not args.no_special)
            postgres_pwd = generate_password(32, not args.no_special)
            
            print("\n# Application Secret Key")
            print(f"SECRET_KEY={secret_key}")
            
            print("\n# Swagger Documentation Password")
            print(f"SWAGGER_PASSWORD={swagger_pwd}")
            
            print("\n# Database Password (example)")
            print(f"POSTGRES_PASSWORD={postgres_pwd}")
            
            print("\n" + "="*70)
            print("SECURITY REMINDER:")
            print("1. Never commit these secrets to git")
            print("2. Use different secrets for dev/staging/production")
            print("3. Store production secrets in a secure vault")
            print("4. Rotate secrets regularly")
            print("="*70)
            print()
    
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
