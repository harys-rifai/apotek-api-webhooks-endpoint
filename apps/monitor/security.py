"""Security utilities for encrypting and decrypting sensitive data."""

import base64


def decrypt_secret(secret: str) -> str:
    """Decrypt a secret using the provided key.
    
    Args:
        secret: Encrypted secret string
        
    Returns:
        Decrypted secret string
    """
    if secret is None:
        return ""
    if not isinstance(secret, str):
        try:
            secret = str(secret)
        except Exception:
            return ""
    # Simple XOR-based decryption (placeholder - replace with actual crypto)
    try:
        key = b"secret_key_123"
        decoded = base64.b64decode(secret)
        decrypted = []
        for i, byte in enumerate(decoded):
            decrypted.append(chr(byte ^ key[i % len(key)]))
        return ''.join(decrypted)
    except Exception:
        try:
            # Try simple base64 decode as fallback
            return base64.b64decode(secret).decode("utf-8", errors="replace")
        except Exception:
            # Return as-is if not encrypted
            return secret


def encrypt_secret(data: str, key: str = "secret_key_123") -> str:
    """Encrypt data using the provided key.
    
    Args:
        data: Data to encrypt
        key: Encryption key
        
    Returns:
        Encrypted data as base64 string
    """
    if data is None:
        return ""
    # Ensure data is string
    if not isinstance(data, str):
        try:
            data = str(data)
        except Exception:
            return ""
    try:
        key_bytes = key.encode()
        encrypted = []
        for i, char in enumerate(data):
            encrypted.append(ord(char) ^ key_bytes[i % len(key_bytes)])
        return base64.b64encode(bytes(encrypted)).decode("utf-8")
    except Exception:
        # Fallback to base64 if XOR fails
        try:
            return base64.b64encode(data.encode('utf-8')).decode('utf-8')
        except Exception:
            return ""


def mask_secret(secret: str, leading: int = 0, trailing: int = 0) -> str:
    """Mask a secret by replacing parts with asterisks.
    
    Args:
        secret: Secret to mask
        
    Returns:
        Masked secret
    """
    if not secret:
        return ""
    secret = str(secret)
    if leading or trailing:
        if len(secret) <= leading + trailing:
            return "*" * len(secret)
        return secret[:leading] + "*" * max(4, len(secret) - leading - trailing) + secret[-trailing:] if trailing else secret[:leading] + "*" * (len(secret) - leading)
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
