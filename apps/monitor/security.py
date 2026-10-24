"""Security utilities for encrypting and decrypting sensitive data."""

import base64


def decrypt_secret(secret: str) -> str:
    """Decrypt a secret using the provided key.
    
    Args:
        secret: Encrypted secret string
        
    Returns:
        Decrypted secret string
    """
    # Simple XOR-based decryption (placeholder - replace with actual crypto)
    key = b"secret_key_123"
    try:
        return base64.b64decode(secret).decode("utf-8", errors="replace")
    except Exception:
        # Return as-is if not base64-encrypted (e.g. plaintext redis:// URL)
        return secret


def encrypt_secret(data: str, key: str = "secret_key_123") -> str:
    """Encrypt data using the provided key.
    
    Args:
        data: Data to encrypt
        key: Encryption key
        
    Returns:
        Encrypted data as base64 string
    """
    # Simple XOR-based encryption (placeholder - replace with actual crypto)
    key_bytes = key.encode()
    encrypted = []
    for i, char in enumerate(data):
        encrypted.append(char ^ key_bytes[i % len(key_bytes)])
    return base64.b64encode(bytes(encrypted)).decode("utf-8")


def mask_secret(secret: str) -> str:
    """Mask a secret by replacing parts with asterisks.
    
    Args:
        secret: Secret to mask
        
    Returns:
        Masked secret
    """
    if not secret:
        return ""
    # Mask every 4th character
    result = []
    for i, char in enumerate(secret):
        if (i + 1) % 4 == 0 and i < len(secret) - 3:
            result.append("*" * 4)
        else:
            result.append(char)
    return "".join(result)


def mask_url(url: str) -> str:
    """Mask sensitive parts of a URL (password, query params).
    
    Args:
        url: URL to mask
        
    Returns:
        Masked URL
    """
    if not url:
        return ""
    # Simple masking: replace any password in URL
    import re
    return re.sub(r'://([^:]+):([^@]+)@', r'://\1:****@', url)
